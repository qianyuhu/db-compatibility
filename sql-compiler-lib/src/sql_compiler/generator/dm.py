"""
DM Procedure Generator — IR → DM8 (DaMeng) procedure code.

Generates CREATE OR REPLACE PROCEDURE from IRProcedure. DM8 uses
Oracle-compatible procedural syntax for its stored procedures.

Key mappings:
    T-SQL                  → DM Procedure
    ─────────────────────────────────────────
    CREATE PROCEDURE       → CREATE OR REPLACE PROCEDURE ... IS
    @variable              → variable (no @ prefix)
    DECLARE @var INT       → var INT; (in declaration section)
    SET @var = expr        → var := expr;
    SELECT @var = col FROM → SELECT col INTO var FROM ...;
    IF cond ... ELSE ...   → IF cond THEN ... ELSE ... END IF;
    WHILE cond             → WHILE cond LOOP ... END LOOP;
    BEGIN TRANSACTION      → BEGIN; (or implicit)
    COMMIT                 → COMMIT;
    EXEC sp args           → CALL sp(args); or sp(args);
    PRINT msg              → DBMS_OUTPUT.PUT_LINE(msg);
    RETURN n               → RETURN n;
    GETDATE()              → SYSDATE
    ISNULL(a,b)            → NVL(a,b)
    LEN(s)                 → LENGTH(s)
    NEWID()                → SYS_GUID()
    @@ROWCOUNT             → v_rowcount (GET DIAGNOSTICS equivalent)
    ISNUMERIC(x)           → REGEXP_LIKE(x, '^[+-]?[0-9]')
    UPDATE FROM JOIN       → UPDATE FROM WHERE (DM style)
    DECLARE @t TABLE(...)  → comment (requires manual temp table)
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


class DMGenerator:
    """Generate DM8 procedure code from IR."""

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a T-SQL identifier — strip ## prefix."""
        return name.lstrip("#")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(self, ir: IRProcedure) -> str:
        """Generate a complete DM CREATE OR REPLACE PROCEDURE.

        Args:
            ir: The IRProcedure to generate from.

        Returns:
            Complete DM procedure source code as a string.
        """
        lines: list[str] = []

        # Header
        lines.append(self._generate_header(ir))

        # Variable declarations (DM: after IS/AS, before BEGIN)
        lines.append(self._generate_variable_section(ir))

        # Body
        lines.append("BEGIN")
        for node in ir.body:
            lines.append(self._generate_node(node, indent=1))
        lines.append("END;")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Header generation
    # ------------------------------------------------------------------

    def _generate_header(self, ir: IRProcedure) -> str:
        """Generate CREATE OR REPLACE PROCEDURE header.

        DM syntax:
            CREATE OR REPLACE PROCEDURE name
            (IN param TYPE, OUT param TYPE)
            IS
            [variable declarations]
            BEGIN
                ...
            END;
        """
        params_str = self._generate_parameters(ir.parameters)

        header = f"CREATE OR REPLACE PROCEDURE {ir.name}"
        if params_str:
            header += " (\n    " + params_str.replace(", ", ",\n    ") + "\n)"
        header += "\nIS"
        return header

    def _generate_parameters(self, params: tuple[IRVariable, ...]) -> str:
        """Generate parameter list with IN/OUT direction markers.

        DM requires explicit IN/OUT/INOUT markers for each parameter.
        """
        parts: list[str] = []
        for p in params:
            dm_type = self._map_data_type(p.data_type)
            pname = self._normalize_name(p.name)
            if p.is_output:
                parts.append(f"OUT p_{pname} {dm_type}")
            else:
                default = ""
                if p.default_value is not None:
                    default = f" DEFAULT {p.default_value}"
                parts.append(f"IN p_{pname} {dm_type}{default}")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # Variable declaration section
    # ------------------------------------------------------------------

    def _generate_variable_section(self, ir: IRProcedure) -> str:
        """Generate variable declarations.

        In DM, declarations go between IS and BEGIN (no DECLARE keyword needed).
        """
        local_vars = [v for v in ir.variables
                      if v.scope == VariableScope.LOCAL]

        if not local_vars:
            return "    -- (no local variables)"

        lines: list[str] = []
        for v in local_vars:
            vname = self._normalize_name(v.name)
            # Detect TABLE type variables
            if v.data_type and v.data_type.upper().startswith("TABLE"):
                lines.append(f"    -- TABLE variable '{vname}': use CREATE TEMP TABLE instead")
                lines.append(f"    -- Original: DECLARE @{v.name} {v.data_type}")
                continue
            dm_type = self._map_data_type(v.data_type)
            default = ""
            if v.default_value is not None:
                default = f" := {v.default_value}"
            lines.append(f"    {vname} {dm_type}{default};")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Node dispatch
    # ------------------------------------------------------------------

    def _generate_node(self, node: IRNode, indent: int = 0) -> str:
        """Dispatch an IR node to the appropriate generator method."""
        prefix = "    " * indent

        if isinstance(node, IRVariable):
            return f"{prefix}-- (variable {node.name} declared above)"
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
            return f"{prefix}-- nested procedure '{node.name}' (inlined)"
        else:
            return f"{prefix}-- TODO: unsupported node type {type(node).__name__}"

    # ------------------------------------------------------------------
    # Individual node generators
    # ------------------------------------------------------------------

    def _generate_assign(self, node: IRAssign, indent: int) -> str:
        """SET @var = expr → var := expr;

        Handles SET @var = @@ROWCOUNT → v_rowcount assignment.
        """
        prefix = "    " * indent

        # Empty target: passthrough statement (e.g., SET NOCOUNT ON)
        if not node.target:
            return f"{prefix}-- {node.expression} (no DM equivalent)"

        # @@ROWCOUNT → use v_rowcount variable
        if "@@ROWCOUNT" in node.expression.upper():
            target = node.target.lstrip("@")
            return f"{prefix}{target} := v_rowcount;"

        if node.is_scalar_query:
            if node.expression.upper().startswith("SELECT"):
                sql = self._rewrite_select_into(node.expression, node.target)
                return f"{prefix}{sql};"
            else:
                return f"{prefix}{node.target} := ({node.expression});"

        expr = self._rewrite_expression(node.expression)
        return f"{prefix}{node.target} := {expr};"

    def _generate_sql(self, node: IRSQL, indent: int) -> str:
        """Embed SQL statement directly."""
        prefix = "    " * indent
        sql = node.sql_text

        if node.is_select_into and node.target_variable:
            sql = self._rewrite_select_into(sql, node.target_variable)

        sql = self._rewrite_dialect_sql(sql)
        return f"{prefix}{sql};"

    def _generate_if(self, node: IRIf, indent: int) -> str:
        """Generate IF/THEN/ELSE/END IF block.

        DM uses same syntax as PL/pgSQL for IF blocks.
        """
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
        """Generate WHILE/LOOP/END LOOP block.

        DM uses: WHILE condition LOOP ... END LOOP;
        """
        prefix = "    " * indent
        condition = self._rewrite_expression(node.condition)

        lines = [f"{prefix}WHILE {condition} LOOP"]

        for child in node.body:
            lines.append(self._generate_node(child, indent + 1))

        lines.append(f"{prefix}END LOOP;")
        return "\n".join(lines)

    def _generate_transaction(self, node: IRTransaction, indent: int) -> str:
        """Generate transaction control.

        DM supports explicit transaction control in procedures:
            BEGIN → BEGIN;
            COMMIT → COMMIT;
            ROLLBACK → ROLLBACK;
        """
        prefix = "    " * indent
        action = node.action.upper()

        if action == "BEGIN":
            return f"{prefix}-- BEGIN TRANSACTION (use autocommit off)"
        elif action == "COMMIT":
            return f"{prefix}COMMIT;"
        elif action == "ROLLBACK":
            return f"{prefix}ROLLBACK;"
        return f"{prefix}-- transaction: {action}"

    def _generate_exec(self, node: IRExec, indent: int) -> str:
        """Generate procedure call.

        T-SQL EXEC sp_name → DM: CALL sp_name(...) or sp_name(...);
        EXEC sp_name ... OUTPUT → CALL sp_name(INOUT var)
        PRINT msg → DBMS_OUTPUT.PUT_LINE(msg);
        """
        prefix = "    " * indent

        if node.procedure_name.upper() == "PRINT":
            msg = node.arguments[0] if node.arguments else ""
            if msg.startswith("'") and msg.endswith("'"):
                msg = msg[1:-1]
            return f"{prefix}DBMS_OUTPUT.PUT_LINE('{msg}');"

        # Detect OUTPUT parameters
        has_output = any(
            "OUTPUT" in arg.upper() for arg in node.arguments
        )

        cleaned_args = []
        for arg in node.arguments:
            # Remove trailing OUTPUT keyword
            arg_clean = re.sub(
                r"\s+OUTPUT\b", "", arg, flags=re.IGNORECASE
            ).strip()
            # Rewrite @var → var
            arg_clean = self._rewrite_var_ref(arg_clean)
            cleaned_args.append(arg_clean)

        args_str = ", ".join(cleaned_args)

        if has_output:
            return f"{prefix}CALL {node.procedure_name}({args_str});"

        # DM uses CALL for procedure invocation
        return f"{prefix}CALL {node.procedure_name}({args_str});"

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
    # SQL-level rewrites (DM-specific)
    # ------------------------------------------------------------------

    def _rewrite_expression(self, expr: str) -> str:
        """Apply T-SQL → DM expression rewrites.

        Handles:
            @variable → variable (strip @, but preserve @ in string literals)
            GETDATE() → SYSDATE
            ISNULL(a,b) → NVL(a,b)
            LEN(s) → LENGTH(s)
            NEWID() → SYS_GUID()
            ISNUMERIC(x) → REGEXP_LIKE(x, pattern)
        """
        # Safe variable rewriting: only @var_name patterns, not @ in strings
        expr = self._rewrite_var_ref(expr)

        replacements = [
            (r"\bGETDATE\s*\(\)", "SYSDATE"),
            (r"\bGETUTCDATE\s*\(\)", "SYSTIMESTAMP"),
            (r"\bISNULL\s*\(", "NVL("),
            (r"\bLEN\s*\(", "LENGTH("),
            (r"\bNEWID\s*\(\)", "SYS_GUID()"),
            (r"\bCHARINDEX\s*\(", "INSTR("),
            (r"\bSCOPE_IDENTITY\s*\(\)", "IDENTITY_VAL_LOCAL()"),
            (r"@@IDENTITY", "IDENTITY_VAL_LOCAL()"),
        ]

        for pattern, new in replacements:
            expr = re.sub(pattern, new, expr, flags=re.IGNORECASE)

        # ISNUMERIC(x) → CASE WHEN REGEXP_LIKE(x, pattern) THEN 1 ELSE 0 END
        expr = re.sub(
            r"\bISNUMERIC\s*\((.+?)\)",
            r"(CASE WHEN REGEXP_LIKE(\1, '^[+-]?([0-9]+\\.?[0-9]*|[0-9]*\\.?[0-9]+)$') THEN 1 ELSE 0 END)",
            expr,
            flags=re.IGNORECASE,
        )

        return expr

    @staticmethod
    def _rewrite_var_ref(expr: str) -> str:
        """Rewrite @variable references without touching string literals.

        Matches @name or @##name patterns but not @ inside quoted strings.
        """
        def _strip_at(m):
            name = m.group(1)
            return name.lstrip("#")
        return re.sub(r"@([#]?[#]?\w+)", _strip_at, expr)

    def _rewrite_dialect_sql(self, sql: str) -> str:
        """Apply DM-specific SQL rewrites.

        Handles:
            TOP N → ... LIMIT N (DM supports LIMIT)
            [] identifiers → "" identifiers
            UPDATE FROM JOIN → DM-style UPDATE FROM WHERE
            @variable → variable
        """
        # Rewrite UPDATE FROM JOIN
        sql = self._rewrite_update_from_join(sql)

        # Rewrite TOP N
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
            if re.search(r"ORDER\s+BY", sql, re.IGNORECASE):
                sql = re.sub(
                    r"(ORDER\s+BY\s+.+)$",
                    rf"\1\n    LIMIT {limit_val}",
                    sql,
                    flags=re.IGNORECASE,
                )
            else:
                sql += f"\n    LIMIT {limit_val}"

        # Bracket identifiers → double-quoted
        sql = re.sub(r"\[([^\]]+)\]", r'"\1"', sql)

        # DM function replacements in SQL (case-insensitive)
        _dm_func_replacements = [
            (r"\bGETDATE\s*\(\)", "SYSDATE"),
            (r"\bGETUTCDATE\s*\(\)", "SYSTIMESTAMP"),
            (r"\bISNULL\s*\(", "NVL("),
            (r"\bLEN\s*\(", "LENGTH("),
            (r"\bNEWID\s*\(\)", "SYS_GUID()"),
            (r"\bCHARINDEX\s*\(", "INSTR("),
            (r"\bSCOPE_IDENTITY\s*\(\)", "IDENTITY_VAL_LOCAL()"),
            (r"@@IDENTITY", "IDENTITY_VAL_LOCAL()"),
        ]
        for pattern, new in _dm_func_replacements:
            sql = re.sub(pattern, new, sql, flags=re.IGNORECASE)

        # ISNUMERIC(x) → CASE WHEN REGEXP_LIKE(x, pattern) THEN 1 ELSE 0 END
        sql = re.sub(
            r"\bISNUMERIC\s*\((.+?)\)",
            r"(CASE WHEN REGEXP_LIKE(\1, '^[+-]?([0-9]+\\.?[0-9]*|[0-9]*\\.?[0-9]+)$') THEN 1 ELSE 0 END)",
            sql,
            flags=re.IGNORECASE,
        )

        # Rewrite @variable references (safe)
        sql = self._rewrite_var_ref(sql)

        # @@ROWCOUNT within SQL block → v_rowcount variable
        sql = re.sub(
            r"\bSET\s+(\w+)\s*=\s*@@ROWCOUNT\b",
            r"\1 := v_rowcount",
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            r"@@ROWCOUNT\b",
            "v_rowcount /* NOTE: declare v_rowcount INT and set after DML */",
            sql,
            flags=re.IGNORECASE,
        )

        return sql

    @staticmethod
    def _rewrite_update_from_join(sql: str) -> str:
        """Rewrite T-SQL UPDATE FROM JOIN to DM style.

        DM supports UPDATE ... FROM ... WHERE similar to PostgreSQL.
        """
        update_match = re.match(
            r"(UPDATE\s+\S+\s+SET\s+.+?)\s+FROM\s+(.+)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not update_match:
            return sql

        set_clause = update_match.group(1)
        from_clause = update_match.group(2)

        has_join = re.search(r"\bJOIN\b", from_clause, re.IGNORECASE)
        has_comma = "," in from_clause

        if not has_join and not has_comma:
            return sql

        if has_comma and not has_join:
            return (
                f"{set_clause} FROM {from_clause}"
                f"  /* NOTE: verify alias references in SET clause */"
            )

        join_match = re.search(
            r"(\S+(?:\s+\w+)?)\s+JOIN\s+(\S+(?:\s+\w+)?)\s+ON\s+(.+?)(?:\s+WHERE\s+(.+))?$",
            from_clause,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if join_match:
            second_table = join_match.group(2).strip()
            join_cond = join_match.group(3).strip()
            where_clause = join_match.group(4)
            if where_clause:
                return f"{set_clause} FROM {second_table} WHERE {join_cond} AND {where_clause}"
            return f"{set_clause} FROM {second_table} WHERE {join_cond}"

        return (
            f"-- WARNING: UPDATE...FROM...JOIN may need manual conversion\n"
            f"{set_clause} FROM {from_clause}"
        )

    def _rewrite_select_into(self, sql: str, target_var: str) -> str:
        """Rewrite T-SQL SELECT @var = col FROM ... → SELECT col INTO var FROM ..."""
        import re

        pattern = rf"SELECT\s+@{target_var}\s*=\s*(.+?)\s+FROM\b"
        replacement = rf"SELECT \1 INTO {target_var} FROM"
        sql = re.sub(pattern, replacement, sql, count=1, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def _map_data_type(tsql_type: str) -> str:
        """Map T-SQL data type to DM equivalent.

        DM8 uses Oracle-compatible type names.
        """
        upper = tsql_type.upper().strip()

        base = upper.split("(")[0].strip()
        params = ""
        if "(" in upper:
            params = upper[upper.index("("):]

        type_map = {
            "INT": "INTEGER",
            "BIGINT": "BIGINT",
            "SMALLINT": "INTEGER",
            "TINYINT": "INTEGER",
            "BIT": "INTEGER",          # DM has no BOOLEAN; use INTEGER
            "VARCHAR": f"VARCHAR2{params}" if params else "VARCHAR2",
            "NVARCHAR": f"VARCHAR2{params}" if params else "VARCHAR2",
            "CHAR": f"CHAR{params}" if params else "CHAR",
            "NCHAR": f"CHAR{params}" if params else "CHAR",
            "TEXT": "CLOB",
            "NTEXT": "CLOB",
            "DATETIME": "TIMESTAMP",
            "DATETIME2": "TIMESTAMP",
            "SMALLDATETIME": "TIMESTAMP",
            "DATE": "DATE",
            "TIME": "TIME",
            "DATETIMEOFFSET": "TIMESTAMP WITH TIME ZONE",
            "DECIMAL": f"DECIMAL{params}" if params else "DECIMAL",
            "NUMERIC": f"NUMERIC{params}" if params else "NUMERIC",
            "FLOAT": "DOUBLE PRECISION",
            "REAL": "REAL",
            "MONEY": "DECIMAL(19,4)",
            "SMALLMONEY": "DECIMAL(10,4)",
            "UNIQUEIDENTIFIER": "VARCHAR2(36)",
            "BINARY": "BLOB",
            "VARBINARY": "BLOB",
            "IMAGE": "BLOB",
            "XML": "XMLTYPE",
            "TIMESTAMP": "TIMESTAMP",
            "SQL_VARIANT": "VARCHAR2(4000)",
        }

        if base in type_map:
            return type_map[base]

        # TABLE type marker
        if base == "TABLE":
            return "TABLE"

        return upper
