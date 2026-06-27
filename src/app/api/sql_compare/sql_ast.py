"""
Lightweight SQL AST — pattern-based, not a full parser.

Detects dialect-specific syntax patterns for compatibility scoring:
  - SELECT TOP N
  - MSSQL functions: GETDATE(), ISNULL(), LEN(), NEWID()
  - Bracket identifiers: [column_name]
  - FETCH FIRST N ROWS ONLY (ANSI SQL)
  - Statement type classification

Design: No external dependencies. Regex-based detection sufficient for
the known dialect-difference patterns identified in Phase 0 research.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SqlAst:
    """Lightweight AST capturing dialect-sensitive SQL features."""

    statement_type: str = "UNKNOWN"  # SELECT, INSERT, UPDATE, DELETE, WITH, etc.
    has_top: bool = False
    top_value: int | None = None
    has_fetch_first: bool = False
    fetch_first_value: int | None = None
    has_brackets: bool = False
    bracket_idents: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    raw_sql: str = ""


# ---------------------------------------------------------------------------
# Known MSSQL-specific functions not in standard SQL
# ---------------------------------------------------------------------------

_MSSQL_SPECIFIC_FUNCTIONS = [
    "GETDATE",
    "GETUTCDATE",
    "ISNULL",
    "LEN",
    "NEWID",
    "CHARINDEX",
    "PATINDEX",
    "STUFF",
    "DATEADD",
    "DATEDIFF",
    "DATEPART",
    "DATENAME",
    "REPLICATE",
    "SPACE",
    "SCOPE_IDENTITY",
    "ROWCOUNT",
]

# All known dialect-sensitive functions (subset that differs across our 3 DBs)
_DIALECT_FUNCTIONS = [
    "GETDATE",
    "GETUTCDATE",
    "ISNULL",
    "LEN",
    "NEWID",
    "TOP",
    "CHARINDEX",
    "DATEADD",
    "DATEDIFF",
    "DATEPART",
]


def parse_ast(sql: str) -> SqlAst:
    """Parse SQL into a lightweight pattern-based AST.

    Detects statement type, dialect-specific syntax (TOP, FETCH FIRST,
    bracket identifiers), and catalogues known dialect-sensitive functions.

    Args:
        sql: Raw SQL string.

    Returns:
        SqlAst with extracted features.
    """
    ast = SqlAst(raw_sql=sql)
    upper = sql.upper().strip()

    # -- Statement type --
    ast.statement_type = _detect_statement_type(upper)

    # -- TOP N --
    top_match = re.match(r"SELECT\s+TOP\s+(\d+)", upper, re.IGNORECASE)
    if top_match:
        ast.has_top = True
        ast.top_value = int(top_match.group(1))

    # -- FETCH FIRST N ROWS ONLY --
    fetch_match = re.search(
        r"FETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY",
        upper,
        re.IGNORECASE,
    )
    if fetch_match:
        ast.has_fetch_first = True
        ast.fetch_first_value = int(fetch_match.group(1))

    # -- Bracket identifiers --
    bracket_matches = re.findall(r"\[([^\]]+)\]", sql)
    if bracket_matches:
        ast.has_brackets = True
        ast.bracket_idents = bracket_matches

    # -- Dialect-sensitive functions --
    for func in _DIALECT_FUNCTIONS:
        pattern = rf"\b{func}\s*\("
        if re.search(pattern, upper):
            ast.functions.append(func)

    # TOP is detected as a keyword, not a function, but still relevant
    if ast.has_top and "TOP" not in ast.functions:
        ast.functions.append("TOP")

    # -- Table names (simple extraction: FROM / JOIN keywords) --
    ast.tables = _extract_tables(sql)

    return ast


def _detect_statement_type(upper_sql: str) -> str:
    """Detect the SQL statement type from the first keyword."""
    first_word_match = re.match(r"^(\w+)", upper_sql)
    if not first_word_match:
        return "UNKNOWN"

    first_word = first_word_match.group(1).upper()

    if first_word == "SELECT":
        return "SELECT"
    if first_word == "INSERT":
        return "INSERT"
    if first_word == "UPDATE":
        return "UPDATE"
    if first_word == "DELETE":
        return "DELETE"
    if first_word in ("WITH",):
        # WITH may be CTE prefix — check for SELECT later
        if re.search(r"\bSELECT\b", upper_sql):
            return "SELECT"
        return "WITH"
    if first_word == "EXEC" or first_word == "EXECUTE":
        return "EXECUTE"
    if first_word == "CALL":
        return "CALL"
    if first_word == "SHOW":
        return "SHOW"
    if first_word == "EXPLAIN":
        return "EXPLAIN"

    return "UNKNOWN"


# SQL keywords that could be mistaken for table names
_SQL_KEYWORDS = frozenset({
    "FROM", "WHERE", "VALUES", "SELECT", "AND", "OR", "NOT",
    "IN", "AS", "ON", "GROUP", "ORDER", "HAVING", "LIMIT",
    "OFFSET", "UNION", "INTERSECT", "EXCEPT", "SET", "INTO",
    "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "FULL",
    "NATURAL", "JOIN", "USING", "WHEN", "THEN", "ELSE", "END",
    "CASE", "EXISTS", "BETWEEN", "LIKE", "IS", "NULL",
})


def _extract_tables(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses.

    Simple regex-based extraction — NOT a full SQL parser.
    Handles: FROM table, FROM schema.table, FROM [schema].[table],
    JOIN table, JOIN schema.table, FROM table alias.

    Uses capture group 1 to reliably extract the table name
    (not the alias) from the matched pattern.
    """
    tables: list[str] = []

    # Match FROM/JOIN <schema.>?<table> with optional alias
    # Capture group 1 = the table name (after schema prefix, before alias)
    table_pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+"
        r"(?:\[?[a-zA-Z_][a-zA-Z0-9_]*\]?\.)?"   # optional schema prefix
        r"\[?([a-zA-Z_][a-zA-Z0-9_]*)\]?"           # capture group 1: table name
        r"(?:\s+(?:AS\s+)?[a-zA-Z_][a-zA-Z0-9_]*)?", # optional alias
        re.IGNORECASE,
    )
    for match in table_pattern.finditer(sql):
        table = match.group(1)
        if table and table.upper() not in _SQL_KEYWORDS:
            tables.append(table)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tables:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique
