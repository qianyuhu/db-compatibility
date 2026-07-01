"""
PL/pgSQL Generator — IR → PostgreSQL/KingbaseES PL/pgSQL procedure code.

Generates CREATE OR REPLACE FUNCTION from IRProcedure. The output is
executable PL/pgSQL that runs on both PostgreSQL and KingbaseES (which
uses PostgreSQL wire protocol).

Key mappings:
    T-SQL                  → PL/pgSQL
    ─────────────────────────────────────────
    CREATE PROCEDURE       → CREATE OR REPLACE FUNCTION ... RETURNS void AS $$
    @variable              → variable (no @ prefix)
    DECLARE @var INT       → var INT; (in DECLARE block)
    SET @var = expr        → var := expr;
    SELECT @var = col FROM → SELECT col INTO var FROM ...;
    IF cond ... ELSE ...   → IF cond THEN ... ELSE ... END IF;
    WHILE cond             → WHILE cond LOOP ... END LOOP;
    BEGIN TRANSACTION      → BEGIN; (or implicit in function)
    COMMIT                 → COMMIT;
    EXEC sp args           → PERFORM sp(args); / CALL sp(INOUT args)
    PRINT msg              → RAISE NOTICE '%', msg;
    RETURN n               → RETURN n;
    GETDATE()              → NOW()
    ISNULL(a,b)            → COALESCE(a,b)
    LEN(s)                 → LENGTH(s)
    NEWID()                → gen_random_uuid()
    @@ROWCOUNT             → GET DIAGNOSTICS var = ROW_COUNT
    ISNUMERIC(x)           → (x ~ '^[+-]?[0-9]')::int
    UPDATE FROM JOIN       → UPDATE FROM WHERE (PostgreSQL style)
    DECLARE @t TABLE(...)  → CREATE TEMP TABLE (with comment)
"""

from __future__ import annotations

import re

from ..ir import (
    IRAssign,
    IRBlock,
    IRExec,
    IRIf,
    IRNode,
    IRProcedure,
    IRReturn,
    IRSQL,
    IRTransaction,
    IRVariable,
    IRWhile,
    VariableScope,
)


class PlPgSQLGenerator:
    """Generate PL/pgSQL procedure code from IR for KingbaseES / PostgreSQL."""

    def __init__(self) -> None:
        self._param_names: set[str] = set()

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a T-SQL identifier for PL/pgSQL.
        
        Strips ## prefix (T-SQL global temp naming convention) since
        PL/pgSQL doesn't support # in identifiers.
        """
        return name.lstrip("#")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(self, ir: IRProcedure) -> str:
        """Generate a complete PL/pgSQL CREATE OR REPLACE FUNCTION.

        Args:
            ir: The IRProcedure to generate from.

        Returns:
            Complete PL/pgSQL source code as a string.
        """
        # Store parameter names for expression rewriting (normalized, without ## prefix)
        self._param_names = {self._normalize_name(p.name) for p in ir.parameters}

        lines: list[str] = []

        # Header
        lines.append(self._generate_header(ir))

        # DECLARE section
        lines.append(self._generate_declare_section(ir))

        # Body
        lines.append("BEGIN")
        for node in ir.body:
            lines.append(self._generate_node(node, indent=1))
        lines.append("END;")

        # Footer
        lines.append("$$ LANGUAGE plpgsql;")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Header generation
    # ------------------------------------------------------------------

    def _generate_header(self, ir: IRProcedure) -> str:
        """Generate CREATE OR REPLACE FUNCTION header with parameters."""
        params_str = self._generate_parameters(ir.parameters)

        header = f"CREATE OR REPLACE FUNCTION {ir.name}("
        if params_str:
            header += "\n    " + params_str.replace(", ", ",\n    ")
        header += "\n)"
        header += "\nRETURNS void AS $$"
        return header

    def _generate_parameters(self, params: tuple[IRVariable, ...]) -> str:
        """Generate parameter list for the function signature.

        T-SQL @param TYPE → PL/pgSQL p_param TYPE [DEFAULT ...]

        OUTPUT parameters are handled differently in PL/pgSQL
        (RETURNS TABLE or OUT parameters). For v1, we use INOUT.
        """
        parts: list[str] = []
        for p in params:
            pg_type = self._map_data_type(p.data_type)
            pname = self._normalize_name(p.name)
            if p.is_output:
                parts.append(f"INOUT p_{pname} {pg_type}")
            else:
                default = ""
                if p.default_value is not None:
                    default = f" DEFAULT {p.default_value}"
                parts.append(f"p_{pname} {pg_type}{default}")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # DECLARE section
    # ------------------------------------------------------------------

    def _generate_declare_section(self, ir: IRProcedure) -> str:
        """Generate the DECLARE section for local variables.

        All locally-declared variables go in the DECLARE block.
        Parameters are already in the function signature, so they're excluded.
        """
        local_vars = [v for v in ir.variables
                      if v.scope == VariableScope.LOCAL]

        if not local_vars:
            return "DECLARE\n    -- (no local variables)"

        lines = ["DECLARE"]
        for v in local_vars:
            vname = self._normalize_name(v.name)
            # Detect TABLE type variables → generate temp table comment
            if v.data_type and v.data_type.upper().startswith("TABLE"):
                lines.append(f"    -- TABLE variable '{vname}': use CREATE TEMP TABLE instead")
                lines.append(f"    -- Original: DECLARE @{v.name} {v.data_type}")
                continue
            pg_type = self._map_data_type(v.data_type)
            default = ""
            if v.default_value is not None:
                default = f" := {v.default_value}"
            lines.append(f"    {vname} {pg_type}{default};")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Node dispatch
    # ------------------------------------------------------------------

    def _generate_node(self, node: IRNode, indent: int = 0) -> str:
        """Dispatch an IR node to the appropriate generator method."""
        prefix = "    " * indent

        if isinstance(node, IRVariable):
            return self._generate_variable_node(node, indent)
        elif isinstance(node, IRAssign):
            return self._generate_assign(node, indent)
        elif isinstance(node, IRSQL):
            return self._generate_sql(node, indent)
        elif isinstance(node, IRIf):
            return self._generate_if(node, indent)
        elif isinstance(node, IRWhile):
            return self._generate_while(node, indent)
        elif isinstance(node, IRTransaction):
            return self._generate_transaction(node, indent)
        elif isinstance(node, IRExec):
            return self._generate_exec(node, indent)
        elif isinstance(node, IRBlock):
            return self._generate_block(node, indent)
        elif isinstance(node, IRReturn):
            return self._generate_return(node, indent)
        elif isinstance(node, IRProcedure):
            # Nested procedure — unlikely but handle
            return f"{prefix}-- nested procedure '{node.name}' (inlined)"
        else:
            return f"{prefix}-- TODO: unsupported node type {type(node).__name__}"

    # ------------------------------------------------------------------
    # Individual node generators
    # ------------------------------------------------------------------

    def _generate_variable_node(self, node: IRVariable, indent: int) -> str:
        """Variables are handled in DECLARE section; skip in body."""
        vname = self._normalize_name(node.name)
        if node.scope == VariableScope.LOCAL:
            return f"{'    ' * indent}-- (variable {vname} declared in DECLARE section)"
        return f"{'    ' * indent}-- parameter: {vname}"

    def _generate_assign(self, node: IRAssign, indent: int) -> str:
        """SET @var = expr → var := expr;

        Handles SELECT @var = col FROM table → SELECT col INTO var FROM table;
        Handles SET NOCOUNT ON → -- SET NOCOUNT ON (PL/pgSQL equivalent)
        Handles SET @var = @@ROWCOUNT → GET DIAGNOSTICS var = ROW_COUNT;
        """
        prefix = "    " * indent

        # Empty target: statement without variable (e.g., SET NOCOUNT ON)
        if not node.target:
            return f"{prefix}-- {node.expression} (no PL/pgSQL equivalent)"

        target = self._normalize_name(node.target)

        # @@ROWCOUNT → GET DIAGNOSTICS var = ROW_COUNT
        if "@@ROWCOUNT" in node.expression.upper():
            return f"{prefix}GET DIAGNOSTICS {target} = ROW_COUNT;"

        if node.is_scalar_query:
            # SELECT ... INTO var pattern
            if node.expression.upper().startswith("SELECT"):
                # Insert INTO clause: SELECT col INTO var FROM ...
                sql = self._rewrite_select_into(node.expression, target)
                return f"{prefix}{sql};"
            else:
                return f"{prefix}{target} := ({node.expression});"

        # Standard assignment
        expr = self._rewrite_expression(node.expression)
        return f"{prefix}{target} := {expr};"

    def _generate_sql(self, node: IRSQL, indent: int) -> str:
        """Embed SQL statement directly.

        For SELECT @var = col FROM table, rewrite to SELECT col INTO var FROM.
        """
        prefix = "    " * indent
        sql = node.sql_text

        # Rewrite SELECT @var = col to SELECT col INTO var
        if node.is_select_into and node.target_variable:
            sql = self._rewrite_select_into(sql, node.target_variable)

        # Apply dialect rewrites
        sql = self._rewrite_dialect_sql(sql)

        return f"{prefix}{sql};"

    def _generate_if(self, node: IRIf, indent: int) -> str:
        """Generate IF/THEN/ELSE/END IF block."""
        prefix = "    " * indent
        condition = self._rewrite_expression(node.condition)

        lines = [f"{prefix}IF {condition} THEN"]

        for child in node.then_body:
            lines.append(self._generate_node(child, indent + 1))

        if node.else_body:
            lines.append(f"{prefix}ELSE")
            for child in node.else_body:
                lines.append(self._generate_node(child, indent + 1))

        lines.append(f"{prefix}END IF;")
        return "\n".join(lines)

    def _generate_while(self, node: IRWhile, indent: int) -> str:
        """Generate WHILE/LOOP/END LOOP block."""
        prefix = "    " * indent
        condition = self._rewrite_expression(node.condition)

        lines = [f"{prefix}WHILE {condition} LOOP"]

        for child in node.body:
            lines.append(self._generate_node(child, indent + 1))

        lines.append(f"{prefix}END LOOP;")
        return "\n".join(lines)

    def _generate_transaction(self, node: IRTransaction, indent: int) -> str:
        """Generate transaction control statement.

        In PL/pgSQL functions, transactions are managed by the caller.
        BEGIN is a block marker, not a transaction start.
        """
        prefix = "    " * indent
        action = node.action.upper()

        if action == "BEGIN":
            return f"{prefix}-- BEGIN TRANSACTION (transaction control delegated to caller)"
        elif action == "COMMIT":
            return f"{prefix}-- COMMIT (transaction control delegated to caller)"
        elif action == "ROLLBACK":
            # PL/pgSQL supports ROLLBACK only in exception handlers
            return f"{prefix}-- ROLLBACK (use EXCEPTION block in PL/pgSQL)"
        return f"{prefix}-- transaction: {action}"

    def _generate_exec(self, node: IRExec, indent: int) -> str:
        """Generate procedure call.

        T-SQL EXEC sp_name → PL/pgSQL PERFORM sp_name(...)
        EXEC sp_name ... OUTPUT → CALL sp_name(INOUT var)
        PRINT msg → RAISE NOTICE '%', msg
        """
        prefix = "    " * indent

        if node.procedure_name.upper() == "PRINT":
            msg = node.arguments[0] if node.arguments else ""
            # Strip outer quotes if present
            if msg.startswith("'") and msg.endswith("'"):
                msg = msg[1:-1]
            return f"{prefix}RAISE NOTICE '%', '{msg}';"

        # Detect OUTPUT parameters and rewrite
        has_output = any(
            "OUTPUT" in arg.upper() for arg in node.arguments
        )

        if has_output:
            # CALL with INOUT parameters
            cleaned_args = []
            for arg in node.arguments:
                # Remove trailing OUTPUT keyword
                arg_clean = re.sub(
                    r"\s+OUTPUT\b", "", arg, flags=re.IGNORECASE
                ).strip()
                # Rewrite @var → var/p_var
                arg_clean = self._rewrite_expression(arg_clean)
                cleaned_args.append(arg_clean)
            args_str = ", ".join(cleaned_args)
            return f"{prefix}CALL {node.procedure_name}({args_str});"

        # Standard procedure call (no OUTPUT)
        cleaned_args = [self._rewrite_expression(a) for a in node.arguments]
        args_str = ", ".join(cleaned_args)
        return f"{prefix}PERFORM {node.procedure_name}({args_str});"

    def _generate_block(self, node: IRBlock, indent: int) -> str:
        """Generate anonymous BEGIN...END block."""
        prefix = "    " * indent

        lines = [f"{prefix}BEGIN"]
        for child in node.body:
            lines.append(self._generate_node(child, indent + 1))
        lines.append(f"{prefix}END;")
        return "\n".join(lines)

    def _generate_return(self, node: IRReturn, indent: int) -> str:
        """Generate RETURN statement."""
        prefix = "    " * indent
        if node.value:
            return f"{prefix}RETURN {node.value};"
        return f"{prefix}RETURN;"

    # ------------------------------------------------------------------
    # SQL-level rewrites
    # ------------------------------------------------------------------

    def _rewrite_expression(self, expr: str) -> str:
        """Apply T-SQL → PL/pgSQL expression rewrites.

        Handles:
            @variable → p_variable (for parameters) or variable (for locals)
            GETDATE() → NOW()
            ISNULL(a,b) → COALESCE(a,b)
            LEN(s) → LENGTH(s)
            NEWID() → gen_random_uuid()
        """
        import re

        # Rewrite @param → p_param for parameters, @var → var for locals
        # Handles @## prefixed names (e.g., @##user → p_user)
        def _rewrite_var(m):
            raw_name = m.group(1)  # may include ## prefix
            name = self._normalize_name(raw_name)
            if name in self._param_names:
                return f"p_{name}"
            return name

        expr = re.sub(r"@([#]?[#]?\w+)", _rewrite_var, expr)

        # Function name replacements (case-insensitive)
        replacements = [
            (r"\bGETDATE\s*\(\)", "NOW()"),
            (r"\bGETUTCDATE\s*\(\)", "CURRENT_TIMESTAMP"),
            (r"\bISNULL\s*\(", "COALESCE("),
            (r"\bLEN\s*\(", "LENGTH("),
            (r"\bNEWID\s*\(\)", "gen_random_uuid()"),
            (r"\bCHARINDEX\s*\(", "POSITION("),
            (r"\bSCOPE_IDENTITY\s*\(\)", "lastval()"),
            (r"@@IDENTITY", "lastval()"),
        ]

        for pattern, new in replacements:
            expr = re.sub(pattern, new, expr, flags=re.IGNORECASE)

        # ISNUMERIC(x) → CASE WHEN x ~ '^[+-]?([0-9]+\\.?[0-9]*|[0-9]*\\.?[0-9]+)$' THEN 1 ELSE 0 END
        expr = re.sub(
            r"\bISNUMERIC\s*\((.+?)\)",
            r"(CASE WHEN \1 ~ '^[+-]?([0-9]+\\.?[0-9]*|[0-9]*\\.?[0-9]+)$' THEN 1 ELSE 0 END)",
            expr,
            flags=re.IGNORECASE,
        )

        return expr

    def _rewrite_dialect_sql(self, sql: str) -> str:
        """Apply dialect-level SQL rewrites.

        Handles:
            TOP N → LIMIT N
            [] identifiers → "" identifiers
            UPDATE FROM JOIN → PostgreSQL-style UPDATE FROM WHERE
            @variable → p_variable / variable
        """
        import re

        # Rewrite UPDATE FROM JOIN → PostgreSQL style
        sql = self._rewrite_update_from_join(sql)

        # Rewrite TOP N → LIMIT N
        top_match = re.search(
            r"SELECT\s+TOP\s+(\d+)",
            sql,
            flags=re.IGNORECASE,
        )
        if top_match:
            limit_val = top_match.group(1)
            sql = re.sub(
                r"SELECT\s+TOP\s+\d+",
                "SELECT",
                sql,
                flags=re.IGNORECASE,
            )
            # Append LIMIT before ORDER BY or at end
            if re.search(r"ORDER\s+BY", sql, re.IGNORECASE):
                sql = re.sub(
                    r"(ORDER\s+BY\s+.+?)$",
                    rf"\1\n    LIMIT {limit_val}",
                    sql,
                    flags=re.IGNORECASE,
                )
            else:
                sql += f"\n    LIMIT {limit_val}"

        # Rewrite bracket identifiers to double-quoted
        sql = re.sub(r"\[([^\]]+)\]", r'"\1"', sql)

        # Apply function-level rewrites (case-insensitive)
        func_replacements = [
            (r"\bGETDATE\s*\(\)", "NOW()"),
            (r"\bGETUTCDATE\s*\(\)", "CURRENT_TIMESTAMP"),
            (r"\bISNULL\s*\(", "COALESCE("),
            (r"\bLEN\s*\(", "LENGTH("),
            (r"\bNEWID\s*\(\)", "gen_random_uuid()"),
            (r"\bCHARINDEX\s*\(", "POSITION("),
            (r"\bSCOPE_IDENTITY\s*\(\)", "lastval()"),
            (r"@@IDENTITY", "lastval()"),
        ]
        for pattern, new in func_replacements:
            sql = re.sub(pattern, new, sql, flags=re.IGNORECASE)

        # ISNUMERIC(x) → CASE WHEN x ~ regex THEN 1 ELSE 0 END
        sql = re.sub(
            r"\bISNUMERIC\s*\((.+?)\)",
            r"(CASE WHEN \1 ~ '^[+-]?([0-9]+\\.?[0-9]*|[0-9]*\\.?[0-9]+)$' THEN 1 ELSE 0 END)",
            sql,
            flags=re.IGNORECASE,
        )

        # Rewrite @param → p_param for parameters, @var → var for locals
        # Handles @## prefixed names (e.g., @##user → p_user)
        def _rewrite_var(m):
            raw_name = m.group(1)
            name = self._normalize_name(raw_name)
            if name in self._param_names:
                return f"p_{name}"
            return name
        sql = re.sub(r"@([#]?[#]?\w+)", _rewrite_var, sql)

        # @@ROWCOUNT within SQL block → GET DIAGNOSTICS
        sql = re.sub(
            r"\bSET\s+(\w+)\s*=\s*@@ROWCOUNT\b",
            r"GET DIAGNOSTICS \1 = ROW_COUNT",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            r"@@ROWCOUNT\b",
            "ROW_COUNT /* NOTE: use GET DIAGNOSTICS var = ROW_COUNT after DML */",
            sql,
            flags=re.IGNORECASE,
        )

        return sql

    @staticmethod
    def _rewrite_update_from_join(sql: str) -> str:
        """Rewrite T-SQL UPDATE FROM JOIN to PostgreSQL style.

        T-SQL:  UPDATE t SET col = expr FROM t [alias] JOIN s ON ...
        PG:     UPDATE t SET col = expr FROM s WHERE t.key = s.key

        T-SQL:  UPDATE t SET col = expr FROM t a, s b WHERE a.x = b.y
        PG:     UPDATE t SET col = expr FROM s b WHERE a.x = b.y

        This is a best-effort rewrite; complex cases are annotated with WARNING.
        """
        import re

        # Pattern: UPDATE <table> SET ... FROM <table> <alias> JOIN ...
        # or:      UPDATE <table> SET ... FROM <table> <alias>, <table2> ...
        update_match = re.match(
            r"(UPDATE\s+\S+\s+SET\s+.+?)\s+FROM\s+(.+)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not update_match:
            return sql

        set_clause = update_match.group(1)
        from_clause = update_match.group(2)

        # Check if FROM clause contains JOIN or comma-separated tables
        has_join = re.search(r"\bJOIN\b", from_clause, re.IGNORECASE)
        has_comma = "," in from_clause

        if not has_join and not has_comma:
            return sql  # Simple UPDATE without multi-table FROM

        # For comma-style: FROM tableA a, tableB b WHERE ... is already PG-compatible
        # PostgreSQL supports UPDATE ... FROM table WHERE ...
        # We just need to remove the target table alias from the FROM clause
        if has_comma and not has_join:
            # Already close to PG syntax, keep as-is with comment
            return (
                f"{set_clause} FROM {from_clause}"
                f"  /* NOTE: verify alias references in SET clause */"
            )

        # For JOIN style: convert JOIN ON to WHERE
        # Extract: FROM t1 JOIN t2 ON t1.x = t2.y
        join_match = re.search(
            r"(\S+(?:\s+\w+)?)\s+JOIN\s+(\S+(?:\s+\w+)?)\s+ON\s+(.+?)(?:\s+WHERE\s+(.+))?$",
            from_clause,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if join_match:
            first_table = join_match.group(1).strip()
            second_table = join_match.group(2).strip()
            join_cond = join_match.group(3).strip()
            where_clause = join_match.group(4)

            if where_clause:
                new_from = f"{set_clause} FROM {second_table} WHERE {join_cond} AND {where_clause}"
            else:
                new_from = f"{set_clause} FROM {second_table} WHERE {join_cond}"
            return new_from

        # Fallback: add warning comment
        return (
            f"-- WARNING: UPDATE...FROM...JOIN may need manual conversion\n"
            f"{set_clause} FROM {from_clause}"
        )

    def _rewrite_select_into(self, sql: str, target_var: str) -> str:
        """Rewrite T-SQL SELECT @var = col FROM ... → SELECT col INTO var FROM ..."""
        import re

        # Pattern: SELECT @var = column_expression FROM table ...
        # → SELECT column_expression INTO var FROM table ...
        pattern = rf"SELECT\s+@{target_var}\s*=\s*(.+?)\s+FROM\b"
        replacement = rf"SELECT \1 INTO {target_var} FROM"
        sql = re.sub(pattern, replacement, sql, count=1, flags=re.IGNORECASE)

        return sql

    @staticmethod
    def _map_data_type(tsql_type: str) -> str:
        """Map T-SQL data type to PostgreSQL equivalent.

        Handles:
            INT, BIGINT, SMALLINT, TINYINT → same
            VARCHAR(n) → VARCHAR(n)
            NVARCHAR(n) → VARCHAR(n)
            DATETIME → TIMESTAMP
            BIT → BOOLEAN
            MONEY → NUMERIC(19,4)
            UNIQUEIDENTIFIER → UUID
            IMAGE → BYTEA
            VARBINARY(n) → BYTEA
        """
        upper = tsql_type.upper().strip()

        # Extract base type and parameters
        base = upper.split("(")[0].strip()
        params = ""
        if "(" in upper:
            params = upper[upper.index("("):]

        type_map = {
            "INT": "INTEGER",
            "BIGINT": "BIGINT",
            "SMALLINT": "SMALLINT",
            "TINYINT": "SMALLINT",
            "BIT": "BOOLEAN",
            "VARCHAR": f"VARCHAR{params}" if params else "VARCHAR",
            "NVARCHAR": f"VARCHAR{params}" if params else "VARCHAR",
            "CHAR": f"CHAR{params}" if params else "CHAR",
            "NCHAR": f"CHAR{params}" if params else "CHAR",
            "TEXT": "TEXT",
            "NTEXT": "TEXT",
            "DATETIME": "TIMESTAMP",
            "DATETIME2": "TIMESTAMP",
            "SMALLDATETIME": "TIMESTAMP",
            "DATE": "DATE",
            "TIME": "TIME",
            "DATETIMEOFFSET": "TIMESTAMPTZ",
            "DECIMAL": f"DECIMAL{params}" if params else "DECIMAL",
            "NUMERIC": f"NUMERIC{params}" if params else "NUMERIC",
            "FLOAT": "DOUBLE PRECISION",
            "REAL": "REAL",
            "MONEY": "NUMERIC(19,4)",
            "SMALLMONEY": "NUMERIC(10,4)",
            "UNIQUEIDENTIFIER": "UUID",
            "BINARY": "BYTEA",
            "VARBINARY": "BYTEA",
            "IMAGE": "BYTEA",
            "XML": "XML",
            "TIMESTAMP": "TIMESTAMP",
            "SQL_VARIANT": "TEXT",
        }

        if base in type_map:
            return type_map[base]

        # TABLE type → not a standard data type, handle as temp table marker
        if base == "TABLE":
            return "TABLE"  # Caller should handle specially

        # Fallback: keep as-is
        return upper
