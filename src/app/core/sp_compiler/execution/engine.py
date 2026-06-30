"""
Execution Engine — executes CFG/IR nodes against MSSQL, KingbaseES, and DM8.

Each node's SQL is executed in parallel across all configured databases.
Results are compared and diffs computed. The engine is event-driven: it
emits node_started, node_finished, and node_failed events via an optional
callback, which the WebSocket layer hooks into for real-time UI updates.

Usage:
    from app.core.sp_compiler.execution.engine import ExecutionEngine

    engine = ExecutionEngine(target_dbs=["mssql", "kingbasees", "dm8"])
    result = engine.execute_node(ui_node)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ir import IRSQL, IRIf, IRWhile
from .event_bus import EventBus


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

    The engine wraps the existing `execute_sql()` function to provide
    node-level execution semantics. It handles:
        - SQL nodes: execute the SQL text against all target DBs
        - IF/WHILE nodes: evaluate the condition (structural — condition
          truthiness depends on prior DB state; returns placeholder)
        - ASSIGN nodes: no DB execution needed (in-memory state)
        - Other nodes: skipped

    All DB connections are made inline via execute_sql() — no persistent
    session state is maintained.
    """

    def __init__(
        self,
        target_dbs: list[str] | None = None,
        event_callback: EventCallback | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialize the execution engine.

        Args:
            target_dbs: Database types to execute against.
                        Default: ["mssql", "kingbasees", "dm8"].
            event_callback: Optional single callback for execution events.
                            Deprecated in favor of event_bus.
            event_bus: Optional EventBus for fan-out event delivery.
                       Takes precedence over event_callback when both are set.
        """
        self.target_dbs: list[str] = target_dbs or ["mssql", "kingbasees", "dm8"]
        self.event_callback = event_callback
        self.event_bus = event_bus

    # ------------------------------------------------------------------
    # Node execution
    # ------------------------------------------------------------------

    def execute_node(self, ui_node: dict) -> NodeExecutionResult:
        """Execute a single UI node against all target databases.

        Args:
            ui_node: Dict with keys:
                - id (str): Node identifier
                - type (str): "sql" | "if" | "while" | "exec" | "assign" | etc.
                - source (dict): IR source info including sql_text, condition, etc.

        Returns:
            NodeExecutionResult with per-DB results and diff.
        """
        node_id = ui_node.get("id", "unknown")
        node_type = ui_node.get("type", "sql")
        source = ui_node.get("source", {})

        self._emit("node_started", node_id)

        try:
            if node_type == "sql":
                result = self._execute_sql_node(node_id, source)
            elif node_type in ("if", "while"):
                result = self._execute_branch_node(node_id, node_type, source)
            elif node_type == "exec":
                result = self._execute_exec_node(node_id, source)
            elif node_type == "assign":
                result = self._execute_assign_node(node_id, source)
            else:
                result = self._skip_node(node_id, node_type)

            self._emit("node_finished", node_id, result)
            return result

        except Exception as exc:
            result = NodeExecutionResult(
                node_id=node_id,
                status="failed",
                execution_time_ms=0.0,
            )
            self._emit("node_failed", node_id, {"error": str(exc)})
            return result

    # ------------------------------------------------------------------
    # Node type handlers
    # ------------------------------------------------------------------

    def _execute_sql_node(self, node_id: str, source: dict) -> NodeExecutionResult:
        """Execute a SQL node — runs the SQL text against all target DBs."""
        sql_text = source.get("sql_text", "").strip()
        if not sql_text:
            return NodeExecutionResult(
                node_id=node_id,
                status="skipped",
            )

        start = time.perf_counter()
        results: dict[str, DBResult] = {}

        with ThreadPoolExecutor(max_workers=len(self.target_dbs)) as pool:
            futures = {
                pool.submit(self._timed_execute, db_type, sql_text): db_type
                for db_type in self.target_dbs
            }
            for future in as_completed(futures):
                db_type = futures[future]
                try:
                    results[db_type] = future.result(timeout=30)
                except Exception as exc:
                    results[db_type] = DBResult(
                        db_type=db_type,
                        success=False,
                        error=str(exc),
                    )

        elapsed = (time.perf_counter() - start) * 1000

        # Compute diff across results
        diff = self._compute_diff(results)

        all_success = all(r.success for r in results.values())
        status = "success" if all_success else "failed"

        return NodeExecutionResult(
            node_id=node_id,
            status=status,
            results=results,
            diff=diff,
            execution_time_ms=elapsed,
        )

    def _execute_branch_node(
        self, node_id: str, node_type: str, source: dict
    ) -> NodeExecutionResult:
        """Handle IF/WHILE nodes. These are structural — no SQL execution.

        Branch nodes are placeholders in the graph. Their conditions cannot be
        evaluated without live DB state from prior nodes. We mark them as
        skipped but preserve the condition for the UI to display.
        """
        return NodeExecutionResult(
            node_id=node_id,
            status="skipped",
        )

    def _execute_exec_node(self, node_id: str, source: dict) -> NodeExecutionResult:
        """Handle EXEC nodes. The procedure name is extracted but cannot be
        directly executed since referenced procedures may not exist on all DBs.
        """
        return NodeExecutionResult(
            node_id=node_id,
            status="skipped",
        )

    def _execute_assign_node(self, node_id: str, source: dict) -> NodeExecutionResult:
        """Handle ASSIGN nodes. Variable assignments are in-memory state
        within the SP execution context — no DB round-trip needed.
        """
        return NodeExecutionResult(
            node_id=node_id,
            status="skipped",
        )

    def _skip_node(self, node_id: str, node_type: str) -> NodeExecutionResult:
        """Skip a node type that has no executable semantics."""
        return NodeExecutionResult(
            node_id=node_id,
            status="skipped",
        )

    # ------------------------------------------------------------------
    # SQL execution (wrapping existing execute_sql)
    # ------------------------------------------------------------------

    @staticmethod
    def _timed_execute(db_type: str, sql: str) -> DBResult:
        """Execute SQL against one database and time it.

        Uses the existing execute_sql() from the sql_demo service layer.
        Falls back gracefully if the service is unavailable (e.g., unit tests).
        """
        try:
            from app.api.sql_demo.service import execute_sql

            t0 = time.perf_counter()
            raw = execute_sql(db_type, sql)
            elapsed = (time.perf_counter() - t0) * 1000

            return DBResult(
                db_type=db_type,
                success=raw.get("success", False),
                columns=list(raw.get("columns", [])),
                rows=[list(row) for row in raw.get("rows", [])],
                row_count=raw.get("row_count", 0),
                execution_time_ms=elapsed,
                error=raw.get("error"),
            )
        except ImportError:
            return DBResult(
                db_type=db_type,
                success=False,
                error="execute_sql not available (service layer not loaded)",
            )
        except Exception as exc:
            return DBResult(
                db_type=db_type,
                success=False,
                error=str(exc),
            )

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
