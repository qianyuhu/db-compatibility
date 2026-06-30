"""
Execution Engine — compiles and executes stored procedures across MSSQL, KingbaseES, and DM8.

The engine compiles T-SQL stored procedures to each target dialect,
creates them on the target databases, executes them, and compares results.
It is event-driven: it emits node_started, node_finished, node_failed,
and node_skipped events via an optional EventBus or callback.

Usage:
    from app.core.sp_compiler.execution.engine import ExecutionEngine

    engine = ExecutionEngine(target_dbs=["mssql", "kingbasees", "dm8"])
    result = engine.execute_procedure(original_tsql, proc_name)

    # Session-aware via factory
    engine = ExecutionEngine.for_session(session, target_dbs=["mssql"])
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from ..ir import IRSQL, IRIf, IRWhile
from .event_bus import EventBus

if TYPE_CHECKING:
    from .session import Session, VariableEnvironment


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DBResult:
    """Result from executing a node against a single database.

    Attributes:
        db_type: Database identifier ("mssql", "kingbasees", "dm8").
        success: Whether the execution succeeded.
        columns: Column names from the result set.
        rows: Row data (list of lists).
        row_count: Number of rows returned.
        execution_time_ms: Execution time in milliseconds.
        error: Error message if execution failed.
    """
    db_type: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None


@dataclass
class ExecutionDiff:
    """Difference between multi-DB execution results.

    Attributes:
        row_diff: Difference in row counts (-N, 0, or +N).
        column_diff: Column names present in some but not all results.
        value_diffs: List of value-level differences with row/column indices.
        status: Overall diff status ("MATCH", "MISMATCH", or "ERROR").
    """
    row_diff: int = 0
    column_diff: list[str] = field(default_factory=list)
    value_diffs: list[dict] = field(default_factory=list)
    status: str = "MATCH"


@dataclass
class NodeExecutionResult:
    """Complete result of executing a single CFG node across all databases.

    Attributes:
        node_id: The UINode ID that was executed.
        status: "success" | "failed" | "skipped".
        results: Per-database results keyed by db_type.
        diff: Multi-DB comparison result (None if only 1 DB).
        execution_time_ms: Total execution time across all DBs.
    """
    node_id: str
    status: str
    results: dict[str, DBResult] = field(default_factory=dict)
    diff: ExecutionDiff | None = None
    execution_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Event callback type
# ---------------------------------------------------------------------------

# Called as: callback(event_type: str, node_id: str, data: dict | None)
EventCallback = Callable[[str, str, dict | None], None]


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------


class ExecutionEngine:
    """Executes CFG/IR nodes across multiple databases with diff comparison.

    The engine compiles T-SQL stored procedures to each target dialect,
    extracts the executable SQL body, and runs it directly on each database.
    Results are compared across databases. It is event-driven: it emits
    node_started, node_finished, node_failed, and node_skipped events via
    an optional EventBus or callback.
    """

    def __init__(
        self,
        target_dbs: list[str] | None = None,
        event_callback: EventCallback | None = None,
        event_bus: EventBus | None = None,
        variable_env: VariableEnvironment | None = None,
    ) -> None:
        """Initialize the execution engine.

        Args:
            target_dbs: Database types to execute against.
                        Default: ["mssql", "kingbasees", "dm8"].
            event_callback: Optional single callback for execution events.
                            Deprecated in favor of event_bus.
            event_bus: Optional EventBus for fan-out event delivery.
                       Takes precedence over event_callback when both are set.
            variable_env: Optional VariableEnvironment for stateful execution
                          (enables IF/WHILE condition evaluation, ASSIGN).
        """
        self.target_dbs: list[str] = target_dbs or ["mssql", "kingbasees", "dm8"]
        self.event_callback = event_callback
        self.event_bus = event_bus
        self.variable_env = variable_env

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def for_session(
        session: Session,
        target_dbs: list[str] | None = None,
    ) -> ExecutionEngine:
        """Create an engine wired to *session*'s event bus and variable env.

        This is the preferred constructor when running within a Session —
        it ensures events fan out to the session's tracer and WebSocket
        forwarder, and that IF/WHILE/ASSIGN nodes share variable state.
        """
        return ExecutionEngine(
            target_dbs=target_dbs,
            event_bus=session.event_bus,
            variable_env=session.variable_env,
        )

    # ------------------------------------------------------------------
    # Procedure-level execution (compile → create → call → compare)
    # ------------------------------------------------------------------

    def execute_procedure(
        self,
        original_tsql: str,
        proc_name: str,
        node_ids: list[str] | None = None,
    ) -> list[NodeExecutionResult]:
        """Compile, create, and execute the stored procedure on all target DBs.

        For each target database:
          1. Compile T-SQL → target dialect (MSSQL uses original).
          2. Parse parameters and generate test values.
          3. CREATE the compiled procedure on the database.
          4. CALL the procedure with test parameters and capture results.
          5. Compare results across databases.

        Args:
            original_tsql: The original T-SQL stored procedure source.
            proc_name: Extracted procedure name.
            node_ids: Optional list of CFG node IDs for event emission.

        Returns:
            List of NodeExecutionResult — one pseudo-result per DB comparison,
            plus per-node status markers for the frontend.
        """
        self._emit("node_started", "__procedure__")
        start = time.perf_counter()
        results: dict[str, DBResult] = {}

        # Parse parameters from the original T-SQL
        params = self._parse_proc_params(original_tsql)

        # Compile for each target DB in parallel
        compiled: dict[str, str] = {}
        compile_errors: dict[str, str] = {}

        def _compile_one(db_type: str) -> tuple[str, str | None]:
            """Compile T-SQL for one target. Returns (code, error)."""
            if db_type == "mssql":
                return original_tsql, None
            try:
                from app.core.sp_compiler import compile_sp
                cr = compile_sp(original_tsql, target_db=db_type)
                if cr.success:
                    return cr.generated_code, None
                return "", "; ".join(cr.errors)
            except Exception as exc:
                return "", str(exc)

        with ThreadPoolExecutor(max_workers=len(self.target_dbs)) as pool:
            futs = {pool.submit(_compile_one, db): db for db in self.target_dbs}
            for fut in as_completed(futs):
                db = futs[fut]
                code, err = fut.result(timeout=30)
                if err:
                    compile_errors[db] = err
                else:
                    compiled[db] = code

        # Create & call on each DB in parallel
        def _create_and_call(db_type: str, code: str) -> DBResult:
            """Create the procedure on the DB, call it, return result."""
            try:
                from .db_connector import get_connection
                t0 = time.perf_counter()
                conn = get_connection(db_type)
                try:
                    cur = conn.cursor()

                    # Prepare the code for execution (fix return types, etc.)
                    exec_code = self._prepare_for_execution(db_type, code, proc_name)

                    # Check if the prepared code is a direct SELECT (no function wrapper)
                    is_direct_select = exec_code.strip().upper().startswith("SELECT")

                    if is_direct_select:
                        # Execute the SELECT directly
                        cur.execute(exec_code)
                    else:
                        # For KingbaseES, we use a wrapper function _cfg_exec
                        call_name = "_cfg_exec" if db_type == "kingbasees" else proc_name

                        # Drop existing function/procedure first
                        try:
                            if db_type == "mssql":
                                cur.execute(f"DROP PROCEDURE IF EXISTS {proc_name}")
                            elif db_type == "kingbasees":
                                type_sig = ", ".join(p["target_type"] for p in params) if params else ""
                                cur.execute(f"DROP FUNCTION IF EXISTS _cfg_exec({type_sig})")
                            elif db_type == "dm8":
                                cur.execute(f"DROP PROCEDURE IF EXISTS {proc_name}")
                        except Exception:
                            pass

                        # Create the procedure/function
                        cur.execute(exec_code)

                        # Build and execute the CALL statement
                        call_sql = self._build_call_sql(db_type, call_name, params)
                        cur.execute(call_sql)

                    columns = [d[0] for d in cur.description] if cur.description else []
                    rows = [list(r) for r in cur.fetchall()] if cur.description else []
                    cur.close()

                    elapsed = (time.perf_counter() - t0) * 1000
                    return DBResult(
                        db_type=db_type,
                        success=True,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        execution_time_ms=elapsed,
                    )
                finally:
                    conn.close()
            except Exception as exc:
                return DBResult(
                    db_type=db_type,
                    success=False,
                    error=str(exc),
                )

        with ThreadPoolExecutor(max_workers=len(compiled)) as pool:
            futs = {
                pool.submit(_create_and_call, db, code): db
                for db, code in compiled.items()
            }
            for fut in as_completed(futs):
                db = futs[fut]
                results[db] = fut.result(timeout=60)

        # Add compile errors as failed results
        for db, err in compile_errors.items():
            results[db] = DBResult(db_type=db, success=False, error=f"Compile error: {err}")

        elapsed = (time.perf_counter() - start) * 1000

        # Compute cross-DB diff
        diff = self._compute_diff(results)
        all_success = all(r.success for r in results.values())
        status = "success" if all_success else "failed"

        proc_result = NodeExecutionResult(
            node_id="__procedure__",
            status=status,
            results=results,
            diff=diff,
            execution_time_ms=elapsed,
        )
        self._emit("node_finished", "__procedure__", proc_result)

        # Build per-node results: all nodes inherit the procedure result
        node_results: list[NodeExecutionResult] = [proc_result]
        if node_ids:
            for nid in node_ids:
                node_results.append(NodeExecutionResult(
                    node_id=nid,
                    status=status,
                    results=results,
                    diff=diff,
                    execution_time_ms=elapsed,
                ))

        return node_results

    @staticmethod
    def _parse_proc_params(tsql: str) -> list[dict]:
        """Parse parameter names and types from T-SQL CREATE PROCEDURE header.

        Returns list of dicts with keys: name, tsql_type, target_type, test_value.
        """
        header_match = re.search(
            r"CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+\w+\s*\((.*?)\)\s*\bAS\b",
            tsql,
            re.IGNORECASE | re.DOTALL,
        )
        if not header_match:
            # Try without parentheses
            header_match = re.search(
                r"CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+\w+\s+(.*?)\s*\bAS\b",
                tsql,
                re.IGNORECASE | re.DOTALL,
            )
            if not header_match:
                return []
            params_text = header_match.group(1).strip()
            # Check if it looks like params (has @)
            if '@' not in params_text:
                return []
        else:
            params_text = header_match.group(1).strip()

        params = []
        # Split on commas not inside parentheses
        parts = []
        depth = 0
        current = ""
        for ch in params_text:
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == ',' and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current.strip())

        for part in parts:
            m = re.match(r"@(\w+)\s+(\w+(?:\s*\([^)]*\))?)", part.strip())
            if m:
                name = m.group(1)
                tsql_type = m.group(2).strip().upper()

                # Map T-SQL type to target types and test values
                if tsql_type in ("INT", "BIGINT", "SMALLINT", "TINYINT"):
                    target_type = "INTEGER"
                    test_value = "0"
                elif tsql_type in ("FLOAT", "REAL", "DECIMAL", "NUMERIC"):
                    target_type = "NUMERIC"
                    test_value = "0"
                elif "CHAR" in tsql_type or "TEXT" in tsql_type:
                    target_type = "VARCHAR"
                    test_value = "'test'"
                elif tsql_type in ("BIT",):
                    target_type = "BOOLEAN"
                    test_value = "FALSE"
                else:
                    target_type = "VARCHAR"
                    test_value = "'test'"

                params.append({
                    "name": name,
                    "tsql_type": tsql_type,
                    "target_type": target_type,
                    "test_value": test_value,
                })

        return params

    @staticmethod
    def _build_call_sql(db_type: str, proc_name: str, params: list[dict]) -> str:
        """Build the SQL to call a stored procedure on the target DB."""
        test_values = ", ".join(p["test_value"] for p in params)
        args = f"({test_values})" if test_values else "()"

        if db_type == "mssql":
            if params:
                return f"EXEC {proc_name} {test_values}"
            return f"EXEC {proc_name}"
        elif db_type == "kingbasees":
            # For RETURNS text: SELECT func() AS result
            return f"SELECT {proc_name}{args} AS result"
        elif db_type == "dm8":
            return f"CALL {proc_name}{args}"
        return f"SELECT {proc_name}{args}"

    @staticmethod
    def _prepare_for_execution(db_type: str, code: str, proc_name: str = "") -> str:
        """Prepare generated code for execution on the target DB.

        For MSSQL: return original T-SQL as-is (CREATE PROCEDURE).
        For KingbaseES: fix the generated function to return result sets.
        For DM8: fix the generated procedure for execution.
        """
        if db_type == "mssql":
            return code

        elif db_type == "kingbasees":
            # Extract parameter name mapping from function header
            # e.g. p_product_id INTEGER → {"product_id": "p_product_id"}
            param_map: dict[str, str] = {}
            param_header = re.search(
                r"FUNCTION\s+\w+\s*\((.*?)\)", code, re.IGNORECASE | re.DOTALL
            )
            if param_header:
                for pm in re.finditer(r"(\w+)\s+\w+", param_header.group(1)):
                    full_name = pm.group(1)
                    # Strip common prefixes like p_
                    base = re.sub(r"^p_", "", full_name)
                    param_map[base] = full_name

            # Fix parameter references: @param → p_param (using mapping)
            def _replace_param(m):
                name = m.group(1)
                return param_map.get(name, name)
            code = re.sub(r"@(\w+)", _replace_param, code)

            # Fix string literals that lost their quotes
            code = re.sub(
                r"SELECT\s+([A-Za-z][A-Za-z ]*?)\s+AS\b",
                lambda m: f"SELECT '{m.group(1).strip()}' AS" if not m.group(1).strip().startswith("'") else m.group(0),
                code,
                flags=re.IGNORECASE,
            )

            # Extract the body between BEGIN and END
            body_match = re.search(
                r"\$\$\s*(?:DECLARE\s*(.*?)\s*)?BEGIN\s*(.*?)\s*END\s*;\s*\$\$",
                code,
                re.DOTALL | re.IGNORECASE,
            )
            if not body_match:
                return code

            declarations = body_match.group(1) or ""
            body = body_match.group(2) or ""

            # Fix ELSE pattern: END IF; BEGIN ... END; → ELSE ... END IF;
            body = re.sub(
                r"END\s+IF\s*;\s*BEGIN\s*(.*?)\s*END\s*;",
                r"ELSE\n        \1\n    END IF;",
                body,
                flags=re.IGNORECASE | re.DOTALL,
            )

            # Fix variable assignments: SELECT col INTO var FROM → var := (SELECT col FROM)
            body = re.sub(
                r"SELECT\s+([\w.]+)\s+INTO\s+(\w+)\s+FROM\b",
                r"\2 := (SELECT \1 FROM",
                body,
                flags=re.IGNORECASE,
            )
            # Close the subquery parenthesis
            body = re.sub(
                r"(\w+)\s*:=\s*\(SELECT\s+([\w.]+)\s+FROM\b([^;]+);",
                r"\1 := (SELECT \2 FROM\3);",
                body,
                flags=re.IGNORECASE,
            )

            # Convert SELECT 'literal' AS col → RETURN 'literal'
            body = re.sub(
                r"SELECT\s+'([^']*)'\s+AS\s+\w+",
                r"RETURN '\1'",
                body,
                flags=re.IGNORECASE,
            )

            # Extract parameter declarations from the function header
            param_match = re.search(
                r"FUNCTION\s+\w+\s*\((.*?)\)", code, re.IGNORECASE | re.DOTALL
            )
            params_decl = param_match.group(1).strip() if param_match else ""

            # Detect if body has bare table SELECTs (SELECT ... FROM table)
            # that aren't part of an assignment (var := (SELECT ...))
            has_table_select = bool(re.search(
                r"(?<!:= \()SELECT\s+[\w.*, ]+\s+FROM\b",
                body,
                re.IGNORECASE,
            ))

            if has_table_select:
                # For table queries, just extract and execute the SELECT directly
                # No function wrapper needed
                # Find the SELECT ... FROM ... statement
                select_match = re.search(
                    r"(SELECT\s+[\w.*, ]+\s+FROM\b[^;]+)",
                    body,
                    re.IGNORECASE,
                )
                if select_match:
                    return select_match.group(1).strip()
                return body.strip()
            else:
                # Use RETURNS text for literal-only results
                func = f"CREATE OR REPLACE FUNCTION _cfg_exec({params_decl})\n"
                func += "RETURNS text AS $$\n"
                if declarations.strip():
                    decls = re.sub(r"--[^\n]*", "", declarations).strip()
                    func += f"DECLARE\n    {decls}\n"
                func += "BEGIN\n"
                func += body
                func += "\n    RETURN NULL;\n"
                func += "END;\n$$ LANGUAGE plpgsql;"
                return func

        return code

    # ------------------------------------------------------------------
    # Diff computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_diff(results: dict[str, DBResult]) -> ExecutionDiff | None:
        """Compare results across databases.

        Computes a three-dimensional diff:
            1. Row count diff (max - min)
            2. Column name diff (columns present in one but not all)
            3. Value-level diff (row-by-row, column-by-column)

        Returns None if there are fewer than 2 successful results to compare.
        """
        successful = {
            db: r for db, r in results.items() if r.success
        }
        if len(successful) < 2:
            return None

        # --- Symmetric consensus diff ---
        # No single "reference" DB — compute stats across all results

        # Row count stats
        row_counts: dict[str, int] = {db: r.row_count for db, r in successful.items()}
        max_rows = max(row_counts.values())
        min_rows = min(row_counts.values())
        row_diff = max_rows - min_rows

        # Column stats — union of all column names across all DBs
        all_columns: set[str] = set()
        for r in successful.values():
            all_columns.update(r.columns)
        column_diff: list[str] = []
        for col in sorted(all_columns):
            dbs_with = [db for db, r in successful.items() if col in r.columns]
            dbs_without = [db for db in successful if db not in dbs_with]
            if dbs_without:
                column_diff.append(
                    f"{col} (present in {','.join(dbs_with)}, missing in {','.join(dbs_without)})"
                )

        # Value diff — compare all DB pairs up to 100 rows
        value_diffs: list[dict] = []
        max_check = min(max(row_counts.values()), 100)
        for row_idx in range(max_check):
            # Gather this row from every DB
            row_by_db: dict[str, list] = {}
            for db, r in successful.items():
                row_by_db[db] = r.rows[row_idx] if row_idx < r.row_count else []

            # Compare every pair of DBs for this row
            db_names = sorted(successful.keys())
            for i in range(len(db_names)):
                for j in range(i + 1, len(db_names)):
                    db_a, db_b = db_names[i], db_names[j]
                    row_a, row_b = row_by_db[db_a], row_by_db[db_b]
                    max_cols = max(len(row_a), len(row_b))
                    for col_idx in range(max_cols):
                        val_a = row_a[col_idx] if col_idx < len(row_a) else None
                        val_b = row_b[col_idx] if col_idx < len(row_b) else None
                        if val_a != val_b:
                            col_name = (
                                successful[db_a].columns[col_idx]
                                if col_idx < len(successful[db_a].columns)
                                else str(col_idx)
                            )
                            value_diffs.append({
                                "row": row_idx,
                                "column": col_name,
                                f"{db_a}_value": str(val_a),
                                f"{db_b}_value": str(val_b),
                            })

        status = "MATCH"
        if row_diff != 0 or column_diff or value_diffs:
            status = "MISMATCH"
        if any(not r.success for r in results.values()):
            status = "ERROR"

        return ExecutionDiff(
            row_diff=row_diff,
            column_diff=column_diff,
            value_diffs=value_diffs,
            status=status,
        )

    # ------------------------------------------------------------------
    # Condition / Expression evaluation
    # ------------------------------------------------------------------

    def _evaluate_condition(self, condition: str) -> bool | None:
        """Evaluate a T-SQL condition string against the variable environment.

        Supported patterns (case-insensitive):

        * ``@var = value`` / ``@var == value``
        * ``@var != value`` / ``@var <> value``
        * ``@var > value`` / ``@var < value`` / ``@var >= value`` / ``@var <= value``
        * ``@var IS NULL`` / ``@var IS NOT NULL``
        * Integer comparisons: ``@var = 0`` etc.

        Returns ``None`` when evaluation is not possible (unknown variable,
        unparseable expression, or no variable env).
        """
        if self.variable_env is None:
            return None

        condition = condition.strip()

        # IS NULL / IS NOT NULL
        m = re.match(
            r"@(\w+)\s+IS\s+(NOT\s+)?NULL", condition, re.IGNORECASE
        )
        if m:
            var = self.variable_env.get(f"@{m.group(1)}")
            is_not = bool(m.group(2))
            if var is not None:
                return (var.value is not None) if is_not else (var.value is None)
            return None

        # Comparison operators
        m = re.match(
            r"@(\w+)\s*(==|!=|<>|>=|<=|>|<|=)\s*(.+)", condition, re.IGNORECASE
        )
        if m:
            var_name = f"@{m.group(1)}"
            op = m.group(2).strip()
            rhs_raw = m.group(3).strip()

            var = self.variable_env.get(var_name)
            if var is None or var.value is None:
                return None

            # Resolve RHS: could be a literal or a variable reference (@other_var)
            rhs = self._resolve_value(rhs_raw)

            return self._compare(var.value, op, rhs)

        return None

    @staticmethod
    def _compare(
        left: str | int | float,
        op: str,
        right: str,
    ) -> bool | None:
        """Compare *left* (variable value) and *right* (literal string)."""
        # Try numeric comparison first
        try:
            l_num = float(left)
            r_num = float(right)
            left_val: str | int | float = l_num
            right_val: str | int | float = r_num
        except (ValueError, TypeError):
            left_val = str(left)
            right_val = right

        if op in ("=", "=="):
            return left_val == right_val
        if op in ("!=", "<>"):
            return left_val != right_val
        if op == ">":
            return left_val > right_val  # type: ignore[operator]
        if op == "<":
            return left_val < right_val  # type: ignore[operator]
        if op == ">=":
            return left_val >= right_val  # type: ignore[operator]
        if op == "<=":
            return left_val <= right_val  # type: ignore[operator]
        return None

    def _resolve_value(self, raw: str) -> str | int | float:
        """Resolve a value string from a condition's RHS.

        Handles:
        * Variable references: ``@other_var`` → looked up in variable_env
        * Quoted strings: ``'hello'`` → stripped quotes
        * Numeric literals: ``42`` → int, ``3.14`` → float
        * Bare strings: returned as-is
        """
        raw = raw.strip()

        # Variable reference — look up in env
        if raw.startswith("@") and self.variable_env is not None:
            var = self.variable_env.get(raw)
            if var is not None and var.value is not None:
                return var.value

        # Quoted string literal
        if (raw.startswith("'") and raw.endswith("'")) or \
           (raw.startswith('"') and raw.endswith('"')):
            return raw[1:-1]

        # Numeric literal
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            pass

        return raw

    def _evaluate_expression(self, expression: str) -> str | int | float | None:
        """Evaluate a simple assignment expression.

        Handles:
        * String literals: ``'hello'``
        * Numeric literals: ``42``, ``3.14``
        * Variable references: ``@other_var``
        * Simple arithmetic: ``@var + 1``

        Returns the evaluated value, or the raw expression string if it
        cannot be evaluated.
        """
        expression = expression.strip()

        # String literal
        if (expression.startswith("'") and expression.endswith("'")) or \
           (expression.startswith('"') and expression.endswith('"')):
            return expression[1:-1]

        # Numeric literal
        try:
            if "." in expression:
                return float(expression)
            return int(expression)
        except ValueError:
            pass

        # Variable reference
        m = re.match(r"@(\w+)$", expression)
        if m and self.variable_env is not None:
            var = self.variable_env.get(f"@{m.group(1)}")
            if var is not None:
                return var.value

        # Simple addition: @var + N
        m = re.match(r"@(\w+)\s*\+\s*(\d+)", expression)
        if m and self.variable_env is not None:
            var = self.variable_env.get(f"@{m.group(1)}")
            increment = int(m.group(2))
            if var is not None and isinstance(var.value, (int, float)):
                return var.value + increment

        # Return raw expression as string
        return expression

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, node_id: str, data: dict | None = None) -> None:
        """Emit an execution event to all registered listeners.

        EventBus takes precedence — when set, events fan out to all subscribers.
        Falls back to the single event_callback for backward compatibility.
        """
        if self.event_bus is not None:
            self.event_bus.emit(event_type, node_id, data)
        elif self.event_callback:
            try:
                self.event_callback(event_type, node_id, data)
            except Exception:
                pass  # Don't let callback failures crash execution
