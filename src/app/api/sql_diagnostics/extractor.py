"""
SQL Object Extractor — identifies tables, columns, functions, and joins from SQL.

Extracts structured object references from raw SQL text using regex patterns.
Not a full SQL parser — focused on the dialect-difference objects that matter
for cross-DB compatibility analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Object reference dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TableRef:
    """A table reference extracted from a FROM or JOIN clause."""

    name: str
    alias: str | None = None
    schema: str | None = None


@dataclass
class ColumnRef:
    """A column reference extracted from SELECT, WHERE, ON, etc."""

    name: str                     # column name only (e.g. "id")
    table_ref: str | None = None  # table name or alias (e.g. "users")
    full_name: str = ""           # "users.id" or "id"


@dataclass
class FunctionRef:
    """A function call extracted from SQL."""

    name: str                     # function name (e.g. "GETDATE")
    args: list[str] = field(default_factory=list)
    raw: str = ""                 # original text (e.g. "GETDATE()")


@dataclass
class JoinRef:
    """A JOIN clause extracted from SQL."""

    join_type: str = "INNER"      # INNER / LEFT / RIGHT / FULL / CROSS
    table: str = ""
    alias: str | None = None
    condition: str | None = None  # ON / USING condition text


@dataclass
class ExtractedObjects:
    """Complete set of objects extracted from a SQL statement."""

    tables: list[TableRef] = field(default_factory=list)
    columns: list[ColumnRef] = field(default_factory=list)
    functions: list[FunctionRef] = field(default_factory=list)
    joins: list[JoinRef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Known dialect-sensitive functions (from Phase 0/1 research)
# ---------------------------------------------------------------------------

_DIALECT_FUNCTIONS: set[str] = {
    "GETDATE", "GETUTCDATE", "ISNULL", "LEN", "NEWID",
    "CHARINDEX", "PATINDEX", "STUFF", "DATEADD", "DATEDIFF",
    "DATEPART", "DATENAME", "REPLICATE", "SPACE",
    "SCOPE_IDENTITY", "ROWCOUNT",
}

# Standard SQL functions — always compatible across DBs
_STANDARD_FUNCTIONS: set[str] = {
    "COUNT", "SUM", "AVG", "MIN", "MAX",
    "COALESCE", "NULLIF", "CAST", "CONVERT",
    "UPPER", "LOWER", "TRIM", "LTRIM", "RTRIM",
    "SUBSTRING", "REPLACE", "LEFT", "RIGHT",
    "ABS", "ROUND", "CEILING", "FLOOR",
    "NOW", "CURRENT_TIMESTAMP", "CURRENT_DATE",
    "EXTRACT", "POSITION", "LENGTH",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE",
    "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
    "STRING_AGG", "ARRAY_AGG",
    "CONCAT", "CONCAT_WS",
    "DATE_TRUNC", "DATE_PART",
    "JSON_EXTRACT", "JSON_QUERY", "JSON_VALUE",
    "GREATEST", "LEAST",
    "ISNULL",  # exists in MySQL but not PG
}

# SQL keywords that should NOT be extracted as column/table names
_SQL_KEYWORDS: frozenset[str] = frozenset({
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "AS", "ON",
    "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT",
    "EXCEPT", "SET", "INTO", "VALUES", "INSERT", "UPDATE", "DELETE",
    "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "FULL", "NATURAL",
    "JOIN", "USING", "WHEN", "THEN", "ELSE", "END", "CASE",
    "EXISTS", "BETWEEN", "LIKE", "IS", "NULL", "TRUE", "FALSE",
    "DISTINCT", "ALL", "ANY", "SOME", "TOP", "PERCENT",
    "ASC", "DESC", "NULLS", "FIRST", "LAST",
    "CREATE", "ALTER", "DROP", "TABLE", "INDEX", "VIEW",
    "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CONSTRAINT",
    "WITH", "RECURSIVE", "RETURNING",
    "BY", "FOR", "TO", "OF", "IF", "ONLY", "FETCH", "ROWS", "ROW",
    "BEGIN", "COMMIT", "ROLLBACK", "TRANSACTION",
    "DECLARE", "EXEC", "EXECUTE", "CALL", "GRANT", "REVOKE",
    "OVER", "PARTITION", "WINDOW",
})

# Words that look like identifiers but are common SQL patterns
_IDENTIFIER_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_objects(sql: str) -> ExtractedObjects:
    """Extract all object references from a SQL statement.

    Args:
        sql: Raw SQL string.

    Returns:
        ExtractedObjects with tables, columns, functions, and joins.
    """
    # Normalize whitespace and remove comments
    cleaned = _remove_comments(sql)
    cleaned = " ".join(cleaned.split())

    tables = _extract_tables(cleaned)
    joins = _extract_joins(cleaned)
    functions = _extract_functions(cleaned)
    columns = _extract_columns(cleaned, tables)

    return ExtractedObjects(
        tables=tables,
        columns=columns,
        functions=functions,
        joins=joins,
    )


# ---------------------------------------------------------------------------
# Comment removal
# ---------------------------------------------------------------------------


def _remove_comments(sql: str) -> str:
    """Remove SQL comments (-- line comments and /* block comments */)."""
    # Remove block comments
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    # Remove line comments (but preserve the rest of the line)
    sql = re.sub(r'--[^\n]*', '', sql)
    return sql


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


def _extract_tables(sql: str) -> list[TableRef]:
    """Extract table references from FROM and JOIN clauses.

    Handles:
        FROM table_name
        FROM table_name alias
        FROM table_name AS alias
        FROM schema.table_name
        FROM [schema].[table_name]  (MSSQL brackets)
        JOIN table_name ...
    """
    tables: list[TableRef] = []
    seen: set[str] = set()

    # Match FROM/JOIN <table> with optional schema, alias, and brackets
    pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+'
        r'(?:\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?\.)?'   # optional schema (group 1)
        r'\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?'             # table name (group 2)
        r'(?:\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?'  # optional alias (group 3)
        r'(?:\s|$|\(|;)',                              # terminator
        re.IGNORECASE,
    )

    for m in pattern.finditer(sql):
        name = m.group(2)
        if not name or name.upper() in _SQL_KEYWORDS:
            continue

        schema = m.group(1)
        alias = m.group(3)

        # Deduplicate by resolved name
        key = f"{schema}.{name}" if schema else name
        if alias:
            key += f":{alias}"
        if key.lower() in seen:
            continue
        seen.add(key.lower())

        tables.append(TableRef(
            name=name,
            alias=alias,
            schema=schema,
        ))

    return tables


# ---------------------------------------------------------------------------
# Column extraction
# ---------------------------------------------------------------------------


def _extract_columns(sql: str, tables: list[TableRef]) -> list[ColumnRef]:
    """Extract column references from SELECT, WHERE, ON, GROUP BY, ORDER BY.

    Builds a mapping from aliases to table names, then resolves column
    references to their owning table where possible.
    """
    columns: list[ColumnRef] = []
    seen: set[str] = set()

    # Build alias → table mapping
    alias_to_table: dict[str, str] = {}
    for t in tables:
        if t.alias:
            alias_to_table[t.alias.lower()] = t.name

    # Extract columns that appear in SELECT, WHERE, ON, GROUP BY, ORDER BY, HAVING
    # Pattern: [table.]column_name
    col_pattern = re.compile(
        r'(?:^|\s|,|\()'                              # boundary
        r'(?:\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?\.)?'      # optional table prefix (group 1)
        r'\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?'              # column name (group 2)
        r'(?:\s*[,\)]|\s+(?:FROM|WHERE|ON|AND|OR|GROUP|ORDER|HAVING|LIMIT|ASC|DESC|$))',
        re.IGNORECASE,
    )

    for m in col_pattern.finditer(sql):
        col_name = m.group(2)
        table_prefix = m.group(1)

        if not col_name or col_name.upper() in _SQL_KEYWORDS:
            continue
        # Skip if it looks like a function call (followed by parenthesis)
        if _is_function_call(sql, m.start(), m.end()):
            continue

        # Resolve table reference
        resolved_table = None
        if table_prefix:
            resolved_table = alias_to_table.get(table_prefix.lower(), table_prefix)

        full_name = f"{resolved_table}.{col_name}" if resolved_table else col_name

        if full_name.lower() in seen:
            continue
        seen.add(full_name.lower())

        columns.append(ColumnRef(
            name=col_name,
            table_ref=resolved_table,
            full_name=full_name,
        ))

    return columns


def _is_function_call(sql: str, match_start: int, match_end: int) -> bool:
    """Check if a matched identifier in sql is immediately followed by '('."""
    rest = sql[match_end:].lstrip()
    return rest.startswith("(")


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


def _extract_functions(sql: str) -> list[FunctionRef]:
    """Extract function calls from SQL.

    Detects:
        - Dialect-sensitive functions (GETDATE, ISNULL, etc.)
        - Standard SQL functions (COUNT, SUM, etc.)
        - TOP N (pseudo-function keyword)
    """
    functions: list[FunctionRef] = []
    seen: set[str] = set()

    # -- Extract TOP as a pseudo-function --
    top_match = re.search(r'\bSELECT\s+TOP\s+(\d+)\b', sql, re.IGNORECASE)
    if top_match:
        raw = f"TOP {top_match.group(1)}"
        if raw.upper() not in seen:
            seen.add(raw.upper())
            functions.append(FunctionRef(
                name="TOP",
                args=[top_match.group(1)],
                raw=raw,
            ))

    # -- Extract function calls: FUNC(args) --
    # Two passes: first known dialect functions, then others
    func_pattern = re.compile(
        r'\b([A-Z_][A-Z0-9_]*)\s*\(',
        re.IGNORECASE,
    )

    for m in func_pattern.finditer(sql):
        name = m.group(1).upper()
        raw_start = m.start()
        raw_end = _find_closing_paren(sql, m.end() - 1)

        if raw_end == -1:
            continue

        raw = sql[raw_start:raw_end + 1]

        if raw.upper() in seen:
            continue
        seen.add(raw.upper())

        # Skip if it looks like a table/column context (e.g., "t.value(")
        if m.start() > 0 and sql[m.start() - 1] == '.':
            continue

        # Extract args
        args_str = sql[m.end():raw_end]
        args = _parse_args(args_str) if args_str.strip() else []

        functions.append(FunctionRef(
            name=name,
            args=args,
            raw=raw,
        ))

    return functions


def _find_closing_paren(sql: str, open_paren_pos: int) -> int:
    """Find the position of the matching closing parenthesis."""
    depth = 0
    for i in range(open_paren_pos, len(sql)):
        if sql[i] == '(':
            depth += 1
        elif sql[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _parse_args(args_str: str) -> list[str]:
    """Parse function arguments, respecting nested parens and string literals."""
    args: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False
    string_char = ''

    for ch in args_str:
        if in_string:
            current.append(ch)
            if ch == string_char:
                in_string = False
            continue

        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            current.append(ch)
            continue

        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
            continue

        current.append(ch)

    if current:
        args.append(''.join(current).strip())

    return [a for a in args if a]


# ---------------------------------------------------------------------------
# Join extraction
# ---------------------------------------------------------------------------


def _extract_joins(sql: str) -> list[JoinRef]:
    """Extract JOIN clauses with type, target table, alias, and condition."""
    joins: list[JoinRef] = []

    # Match: [type] JOIN table [alias] ON condition
    join_pattern = re.compile(
        r'\b((?:INNER|LEFT|RIGHT|FULL|CROSS|NATURAL)\s+)?'
        r'(?:(?:OUTER\s+)?)?'
        r'JOIN\s+'
        r'\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?'               # table name (group 2)
        r'(?:\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?'     # optional alias (group 3)
        r'(?:\s+ON\s+(.+?))?'                               # ON condition (group 4)
        r'(?=\s+(?:INNER|LEFT|RIGHT|FULL|CROSS|JOIN|WHERE|GROUP|ORDER|HAVING|LIMIT)|$)',
        re.IGNORECASE,
    )

    for m in join_pattern.finditer(sql):
        join_type_str = (m.group(1) or '').strip().upper() or 'INNER'
        # Remove trailing OUTER if present
        join_type_str = re.sub(r'\s+OUTER$', '', join_type_str)

        table = m.group(2)
        alias = m.group(3)
        condition = m.group(4)

        if not table or table.upper() in _SQL_KEYWORDS:
            continue

        joins.append(JoinRef(
            join_type=join_type_str,
            table=table,
            alias=alias,
            condition=condition.strip() if condition else None,
        ))

    return joins
