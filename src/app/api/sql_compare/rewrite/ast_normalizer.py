"""
AST Normalizer — produces a dialect-neutral SQL representation.

Extends the lightweight pattern-based parser in sql_ast.py to produce
a NormalizedAst that captures dialect-sensitive features in a common
structure suitable for rule-based rewriting.

Normalized structure:
{
    "type": "SELECT",
    "limit": 10,                   # unified LIMIT clause
    "has_top": false,              # natively uses TOP?
    "has_brackets": false,         # natively uses bracket idents?
    "functions": ["GETDATE"],      # dialect-sensitive functions present
    "tables": ["users"],
    "isnull_calls": [["a","b"]],  # ISNULL(a,b) → COALESCE(a,b)
    "len_calls": ["col1"],         # LEN(col) → LENGTH(col)
}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.api.sql_compare.sql_ast import parse_ast


# ---------------------------------------------------------------------------
# Normalized AST
# ---------------------------------------------------------------------------


@dataclass
class NormalizedAst:
    """Dialect-neutral AST used as the common representation for rewriting.

    All dialect-specific features are unified into standard equivalents:
      - TOP / FETCH FIRST → unified `limit`
      - Bracket identifiers → flag `has_brackets`
      - Dialect functions catalogued in `functions`
    """

    statement_type: str = "UNKNOWN"
    limit: int | None = None           # unified row limit
    has_top: bool = False              # original used TOP syntax
    has_fetch_first: bool = False      # original used FETCH FIRST syntax
    has_brackets: bool = False         # original used [bracket] identifiers
    bracket_idents: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)   # dialect functions found
    isnull_calls: list[list[str]] = field(default_factory=list)  # [[arg1, arg2], ...]
    len_calls: list[str] = field(default_factory=list)            # [column, ...]
    getdate_calls: int = 0             # count of GETDATE() calls
    newid_calls: int = 0               # count of NEWID() calls
    tables: list[str] = field(default_factory=list)
    raw_sql: str = ""


def normalize(sql: str) -> NormalizedAst:
    """Normalize raw SQL into a dialect-neutral NormalizedAst.

    Builds on the existing SqlAst parser and adds function call
    extraction for specific dialect patterns.

    Args:
        sql: Raw SQL string (any dialect).

    Returns:
        NormalizedAst with unified structure.
    """
    ast = parse_ast(sql)
    norm = NormalizedAst(
        statement_type=ast.statement_type,
        limit=ast.top_value or ast.fetch_first_value,
        has_top=ast.has_top,
        has_fetch_first=ast.has_fetch_first,
        has_brackets=ast.has_brackets,
        bracket_idents=list(ast.bracket_idents),
        functions=list(ast.functions),
        tables=list(ast.tables),
        raw_sql=sql,
    )

    upper = sql.upper()

    # -- LIMIT N (PostgreSQL / MySQL style) --
    if norm.limit is None:
        limit_match = re.search(r"\bLIMIT\s+(\d+)\s*$", upper)
        if limit_match:
            norm.limit = int(limit_match.group(1))

    # -- ISNULL(a, b) calls --
    norm.isnull_calls = _extract_isnull_args(sql)

    # -- LEN(column) calls --
    norm.len_calls = _extract_len_args(sql)

    # -- GETDATE() count --
    norm.getdate_calls = len(
        re.findall(r"\bGETDATE\s*\(\s*\)", upper)
    )

    # -- NEWID() count --
    norm.newid_calls = len(
        re.findall(r"\bNEWID\s*\(\s*\)", upper)
    )

    return norm


# ---------------------------------------------------------------------------
# Function call extractors
# ---------------------------------------------------------------------------


def _extract_isnull_args(sql: str) -> list[list[str]]:
    """Extract arguments from ISNULL(arg1, arg2) calls.

    Returns a list of [arg1, arg2] pairs.  Handles simple arguments
    (identifiers, string literals, numbers).
    """
    results: list[list[str]] = []
    # Match ISNULL( with balanced parens — simplified for known patterns
    pattern = re.compile(
        r"\bISNULL\s*\(\s*"
        r"([^,)]+(?:\([^)]*\))?)"   # arg1 — allow nested func call
        r"\s*,\s*"
        r"([^)]+)"                   # arg2
        r"\s*\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        arg1 = m.group(1).strip()
        arg2 = m.group(2).strip()
        results.append([arg1, arg2])
    return results


def _extract_len_args(sql: str) -> list[str]:
    """Extract arguments from LEN(expr) calls."""
    results: list[str] = []
    pattern = re.compile(
        r"\bLEN\s*\(\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        results.append(m.group(1).strip())
    return results
