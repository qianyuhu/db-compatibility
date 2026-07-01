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

from .sql_ast import parse_ast


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
    # -- Phase 2 fields (migration difficulties) --
    has_update_from: bool = False       # UPDATE...FROM JOIN pattern
    has_delete_from: bool = False       # DELETE alias FROM...JOIN pattern
    has_rollup: bool = False            # GROUP BY ... WITH ROLLUP
    has_cube: bool = False              # GROUP BY ... WITH CUBE
    has_select_into: bool = False       # SELECT ... INTO new_table
    has_output_clause: bool = False     # OUTPUT inserted./deleted.
    has_for_xml: bool = False           # FOR XML RAW/AUTO/PATH
    has_for_json: bool = False          # FOR JSON AUTO/PATH
    format_calls: list[list[str]] = field(default_factory=list)   # [[expr, fmt], ...]
    iif_calls: list[list[str]] = field(default_factory=list)      # [[cond, t, f], ...]
    concat_calls: list[list[str]] = field(default_factory=list)   # [[a, b, ...], ...]
    try_cast_count: int = 0             # TRY_CAST / TRY_CONVERT occurrences
    convert_style_calls: list[list[str]] = field(default_factory=list)  # [[type, expr, style], ...]


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

    # -- UPDATE ... FROM pattern (MSSQL proprietary) --
    norm.has_update_from = bool(re.search(
        r"\bUPDATE\s+\w+\s+SET\b.*?\bFROM\b", sql, re.IGNORECASE | re.DOTALL
    ))

    # -- DELETE alias FROM ... JOIN pattern --
    norm.has_delete_from = bool(re.search(
        r"\bDELETE\s+\w+\s+\bFROM\b", sql, re.IGNORECASE
    ))

    # -- WITH ROLLUP / WITH CUBE --
    norm.has_rollup = bool(re.search(r"\bWITH\s+ROLLUP\b", upper))
    norm.has_cube = bool(re.search(r"\bWITH\s+CUBE\b", upper))

    # -- SELECT INTO --
    norm.has_select_into = bool(re.search(
        r"\bSELECT\b.*?\bINTO\s+[#\w]", sql, re.IGNORECASE | re.DOTALL
    ))

    # -- OUTPUT clause --
    norm.has_output_clause = bool(re.search(
        r"\bOUTPUT\b\s+(inserted|deleted)\b", sql, re.IGNORECASE
    ))

    # -- FOR XML / FOR JSON --
    norm.has_for_xml = bool(re.search(r"\bFOR\s+XML\b", upper))
    norm.has_for_json = bool(re.search(r"\bFOR\s+JSON\b", upper))

    # -- FORMAT(expr, fmt) calls --
    norm.format_calls = _extract_format_args(sql)

    # -- IIF(cond, t, f) calls --
    norm.iif_calls = _extract_iif_args(sql)

    # -- CONCAT(a, b, ...) calls --
    norm.concat_calls = _extract_concat_args(sql)

    # -- TRY_CAST / TRY_CONVERT count --
    norm.try_cast_count = len(re.findall(r"\bTRY_(?:CAST|CONVERT)\s*\(", upper))

    # -- CONVERT(type, expr, style) calls --
    norm.convert_style_calls = _extract_convert_args(sql)

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


def _extract_format_args(sql: str) -> list[list[str]]:
    """Extract arguments from FORMAT(expr, fmt [, culture]) calls."""
    results: list[list[str]] = []
    pattern = re.compile(
        r"\bFORMAT\s*\(\s*"
        r"([^,]+?)\s*,\s*"
        r"([^,)]+(?:\([^)]*\))?[^,)]*?)"
        r"(?:\s*,\s*([^)]+?))?"
        r"\s*\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        expr = m.group(1).strip()
        fmt = m.group(2).strip()
        results.append([expr, fmt])
    return results


def _extract_iif_args(sql: str) -> list[list[str]]:
    """Extract arguments from IIF(cond, true_val, false_val) calls."""
    results: list[list[str]] = []
    # Simple 3-arg pattern — handles most cases
    pattern = re.compile(
        r"\bIIF\s*\(\s*"
        r"(.+?)\s*,\s*"
        r"(.+?)\s*,\s*"
        r"(.+?)\s*\)"
        r"(?=\s*(?:FROM|WHERE|ORDER|GROUP|HAVING|UNION|;|\)|$))",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(sql):
        results.append([m.group(1).strip(), m.group(2).strip(), m.group(3).strip()])
    return results


def _extract_concat_args(sql: str) -> list[list[str]]:
    """Extract arguments from CONCAT(a, b, ...) calls."""
    results: list[list[str]] = []
    pattern = re.compile(
        r"\bCONCAT\s*\(([^)]+)\)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        args_str = m.group(1)
        # Split by comma, respecting nested parens
        args = _split_args(args_str)
        if len(args) >= 2:
            results.append([a.strip() for a in args])
    return results


def _extract_convert_args(sql: str) -> list[list[str]]:
    """Extract arguments from CONVERT(type, expr, style) calls."""
    results: list[list[str]] = []
    pattern = re.compile(
        r"\bCONVERT\s*\(\s*"
        r"(\w+(?:\([^)]*\))?)\s*,\s*"   # target type
        r"([^,]+?)\s*,\s*"               # expression
        r"(\d+)\s*\)",                    # style code
        re.IGNORECASE,
    )
    for m in pattern.finditer(sql):
        results.append([m.group(1).strip(), m.group(2).strip(), m.group(3).strip()])
    return results


def _split_args(s: str) -> list[str]:
    """Split a comma-separated argument list, respecting nested parentheses."""
    args: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch == '(' :
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        args.append(''.join(current))
    return args
