"""
SQL Rewrite Rules — declarative rule definitions for cross-dialect SQL transformation.

Architecture:
    RewriteRule (data) + apply_rules() (executor) = declarative engine

    Simple rules use pattern/replace strings (regex substitution).
    Complex rules use apply callables (programmatic transformation).
    The executor dispatches based on which fields are set.

Rule structure:
    id           — unique identifier (e.g. "mssql_to_pg_top_to_limit")
    name         — human-readable name (e.g. "TOP → LIMIT")
    description  — Chinese description of the transformation
    source_db    — source dialect
    target_db    — target dialect
    pattern      — regex pattern (for simple rules)
    replace      — replacement string (for simple rules)
    apply        — transformation function (for complex rules)
    confidence   — per-rule confidence score (0.0-1.0)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

from .ast_normalizer import NormalizedAst, normalize


# ---------------------------------------------------------------------------
# Shared datepart → SQL-standard unit maps
# ---------------------------------------------------------------------------

# Used by DATEADD → INTERVAL rules.  Maps MSSQL datepart abbreviations to
# PostgreSQL INTERVAL unit names.  quarter is mapped to MONTH with a
# multiplier (handled in the apply function, not in this map).
_DATEPART_TO_INTERVAL_MAP: dict[str, str] = {
    "year": "YEAR",
    "yy": "YEAR",
    "yyyy": "YEAR",
    "quarter": "MONTH",   # multiplied by 3 in apply function
    "qq": "MONTH",
    "q": "MONTH",
    "month": "MONTH",
    "mm": "MONTH",
    "m": "MONTH",
    "dayofyear": "DAY",
    "dy": "DAY",
    "y": "DAY",
    "day": "DAY",
    "dd": "DAY",
    "d": "DAY",
    "week": "WEEK",
    "wk": "WEEK",
    "ww": "WEEK",
    "hour": "HOUR",
    "hh": "HOUR",
    "minute": "MINUTE",
    "mi": "MINUTE",
    "n": "MINUTE",
    "second": "SECOND",
    "ss": "SECOND",
    "s": "SECOND",
}

# Used by DATEPART → EXTRACT rules.  Maps MSSQL datepart abbreviations to
# PostgreSQL EXTRACT field names.  Differs from _DATEPART_TO_INTERVAL_MAP in:
#   quarter → QUARTER (not MONTH), dayofyear → DOY (not DAY),
#   adds weekday/dw → DOW.
_DATEPART_TO_EXTRACT_MAP: dict[str, str] = {
    "year": "YEAR",
    "yy": "YEAR",
    "yyyy": "YEAR",
    "quarter": "QUARTER",
    "qq": "QUARTER",
    "q": "QUARTER",
    "month": "MONTH",
    "mm": "MONTH",
    "m": "MONTH",
    "dayofyear": "DOY",
    "dy": "DOY",
    "y": "DOY",
    "day": "DAY",
    "dd": "DAY",
    "d": "DAY",
    "week": "WEEK",
    "wk": "WEEK",
    "ww": "WEEK",
    "weekday": "DOW",
    "dw": "DOW",
    "hour": "HOUR",
    "hh": "HOUR",
    "minute": "MINUTE",
    "mi": "MINUTE",
    "n": "MINUTE",
    "second": "SECOND",
    "ss": "SECOND",
    "s": "SECOND",
}

# Datepart units that need quarter → month multiplication in DATEADD conversion.
_QUARTER_UNITS: frozenset[str] = frozenset({"quarter", "qq", "q"})


# ---------------------------------------------------------------------------
# Rule dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RewriteRule:
    """A single declarative SQL dialect rewrite rule.

    A rule MUST have either:
      - (pattern + replace) for simple regex-based rewrites, OR
      - apply for complex programmatic transformations.

    Fields:
        id:          Unique identifier across all rule sets.
        name:        Human-readable rule name (e.g. "TOP → LIMIT").
        description: Chinese description of the transformation.
        source_db:   Source database dialect (mssql / kingbasees / dm8).
        target_db:   Target database dialect.
        pattern:     Regex pattern to match (simple rules only).
        replace:     Replacement string — may use \\1, \\2 back-references.
        apply:       Callable (sql, norm_ast) → rewritten_sql (complex rules).
        confidence:  Per-rule confidence in [0.0, 1.0].
    """

    id: str
    name: str
    description: str
    source_db: str
    target_db: str
    pattern: str | None = None
    replace: str | None = None
    apply: Callable[[str, NormalizedAst], str] | None = None
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Applied rule result (returned by apply_rules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedRuleInfo:
    """Record of a rule that was successfully applied during rewriting."""

    name: str
    description: str
    confidence: float = 1.0


# ===========================================================================
# Complex rule apply functions
# ===========================================================================
# Only rules that cannot be expressed as simple pattern/replace regex live here.
# Simple rewrites are declared inline in the rule lists below.
# ===========================================================================


def _apply_top_to_limit(sql: str, norm: NormalizedAst) -> str:
    """Replace SELECT TOP N with SELECT ... LIMIT N.

    Does NOT rewrite TOP N PERCENT — that syntax has no direct equivalent
    and is handled by the TOP PERCENT warning rule instead.
    """
    if not norm.has_top:
        return sql
    # Skip TOP...PERCENT — cannot be mechanically translated to LIMIT
    if re.search(r"\bTOP\s+\d+(\.\d+)?\s+PERCENT", sql, re.IGNORECASE):
        return sql
    return (
        re.sub(
            r"\bSELECT\s+TOP\s+(\d+)\b",
            r"SELECT",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        + f"\nLIMIT {norm.limit}"
    )


def _apply_fetch_first_to_limit(sql: str, norm: NormalizedAst) -> str:
    """Replace FETCH FIRST N ROWS ONLY with LIMIT N."""
    return re.sub(
        r"\s*FETCH\s+FIRST\s+\d+\s+ROWS?\s+ONLY",
        f" LIMIT {norm.limit}",
        sql,
        flags=re.IGNORECASE,
    )


def _apply_isnull_to_coalesce(sql: str, norm: NormalizedAst) -> str:
    """Replace ISNULL(a, b) with COALESCE(a, b)."""
    result = sql
    for arg1, arg2 in norm.isnull_calls:
        pattern = re.compile(
            r"\bISNULL\s*\(\s*"
            + re.escape(arg1)
            + r"\s*,\s*"
            + re.escape(arg2)
            + r"\s*\)",
            re.IGNORECASE,
        )
        result = pattern.sub(f"COALESCE({arg1}, {arg2})", result)
    return result


def _apply_isnull_to_nvl(sql: str, norm: NormalizedAst) -> str:
    """Replace ISNULL(a, b) with NVL(a, b) for DM8 (Oracle-compatible)."""
    result = sql
    for arg1, arg2 in norm.isnull_calls:
        pattern = re.compile(
            r"\bISNULL\s*\(\s*"
            + re.escape(arg1)
            + r"\s*,\s*"
            + re.escape(arg2)
            + r"\s*\)",
            re.IGNORECASE,
        )
        result = pattern.sub(f"NVL({arg1}, {arg2})", result)
    return result


def _apply_len_to_length(sql: str, norm: NormalizedAst) -> str:
    """Replace LEN(expr) with LENGTH(expr)."""
    result = sql
    for arg in norm.len_calls:
        pattern = re.compile(
            r"\bLEN\s*\(\s*" + re.escape(arg) + r"\s*\)",
            re.IGNORECASE,
        )
        result = pattern.sub(f"LENGTH({arg})", result)
    return result


def _apply_brackets_to_quotes(sql: str, norm: NormalizedAst) -> str:
    """Replace [identifier] with "identifier" (PG-style quoting)."""
    result = sql
    for ident in norm.bracket_idents:
        bracketed = f"[{ident}]"
        if bracketed in result:
            result = result.replace(bracketed, f'"{ident}"')
    return result


def _apply_charindex_to_position(sql: str, _norm: NormalizedAst) -> str:
    """Replace CHARINDEX(a, b) with POSITION(a IN b)."""
    pattern = re.compile(
        r"\bCHARINDEX\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )

    def _replacement(m: re.Match) -> str:
        needle = m.group(1).strip()
        haystack = m.group(2).strip()
        return f"POSITION({needle} IN {haystack})"

    return pattern.sub(_replacement, sql)


def _apply_patindex_warning(sql: str, _norm: NormalizedAst) -> str:
    """Flag PATINDEX as needing manual conversion."""
    if re.search(r"\bPATINDEX\s*\(", sql, re.IGNORECASE):
        return (
            "-- WARNING: PATINDEX requires manual conversion "
            "(SQL Server pattern → POSIX regex)\n"
            + sql
        )
    return sql


def _apply_dateadd_to_interval(sql: str, _norm: NormalizedAst) -> str:
    """Replace DATEADD(unit, n, date) with date + INTERVAL 'n' unit."""
    pattern = re.compile(
        r"\bDATEADD\s*\(\s*(\w+)\s*,\s*(-?\d+)\s*,\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )

    def _replacement(m: re.Match) -> str:
        unit = m.group(1).lower()
        n = m.group(2).strip()
        date_expr = m.group(3).strip()

        # Quarter needs multiplication (3 months per quarter)
        if unit in _QUARTER_UNITS:
            return f"({date_expr} + INTERVAL '{int(n) * 3}' MONTH)"

        pg_unit = _DATEPART_TO_INTERVAL_MAP.get(unit, unit.upper())
        return f"({date_expr} + INTERVAL '{n}' {pg_unit})"

    return pattern.sub(_replacement, sql)


def _apply_datediff_to_subtract(sql: str, _norm: NormalizedAst) -> str:
    """Rewrite DATEDIFF(unit, a, b) using EXTRACT and AGE functions."""
    pattern = re.compile(
        r"\bDATEDIFF\s*\(\s*(\w+)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )

    def _replacement(m: re.Match) -> str:
        unit = m.group(1).lower()
        start_expr = m.group(2).strip()
        end_expr = m.group(3).strip()

        if unit in ("day", "dd", "d"):
            return f"EXTRACT(DAY FROM ({end_expr} - {start_expr}))"
        elif unit in ("month", "mm", "m"):
            return (
                f"EXTRACT(YEAR FROM AGE({end_expr}, {start_expr})) * 12 + "
                f"EXTRACT(MONTH FROM AGE({end_expr}, {start_expr}))"
            )
        elif unit in ("year", "yy", "yyyy"):
            return f"EXTRACT(YEAR FROM AGE({end_expr}, {start_expr}))"

        # Fallback: keep original with warning
        return (
            f"-- WARNING: DATEDIFF({m.group(1)}, ...) requires manual conversion\n"
            f"DATEDIFF({m.group(1)}, {start_expr}, {end_expr})"
        )

    return pattern.sub(_replacement, sql)


def _apply_datepart_to_extract(sql: str, _norm: NormalizedAst) -> str:
    """Replace DATEPART(unit, date) with EXTRACT(unit FROM date)."""
    pattern = re.compile(
        r"\bDATEPART\s*\(\s*(\w+)\s*,\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )

    def _replacement(m: re.Match) -> str:
        unit = m.group(1).lower()
        date_expr = m.group(2).strip()
        extract_field = _DATEPART_TO_EXTRACT_MAP.get(unit, unit.upper())
        return f"EXTRACT({extract_field} FROM {date_expr})"

    return pattern.sub(_replacement, sql)


def _apply_top_percent_warning(sql: str, _norm: NormalizedAst) -> str:
    """Flag TOP N PERCENT as needing manual conversion."""
    if re.search(r"\bTOP\s+\d+(\.\d+)?\s+PERCENT", sql, re.IGNORECASE):
        return (
            "-- WARNING: TOP N PERCENT not directly translatable — "
            "use PERCENT_RANK() or NTILE\n"
            + sql
        )
    return sql


# -- Reverse rules (KingbaseES / PG → MSSQL) ---------------------------------


def _apply_limit_to_top(sql: str, norm: NormalizedAst) -> str:
    """Reverse: LIMIT N → SELECT TOP N."""
    if not norm.limit:
        return sql
    result = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql, flags=re.IGNORECASE)
    result = re.sub(
        r"\bSELECT\b",
        f"SELECT TOP {norm.limit}",
        result,
        count=1,
        flags=re.IGNORECASE,
    )
    return result


def _apply_coalesce_to_isnull(sql: str, _norm: NormalizedAst) -> str:
    """Reverse COALESCE(a, b) → ISNULL(a, b) — only safe with 2 args."""
    pattern = re.compile(
        r"\bCOALESCE\s*\(\s*([^,]+?)\s*,\s*([^,)]+?)\s*\)",
        re.IGNORECASE,
    )
    return pattern.sub(r"ISNULL(\1, \2)", sql)


def _apply_quotes_to_brackets(sql: str, _norm: NormalizedAst) -> str:
    """Reverse: "identifier" → [identifier] (MSSQL quoting)."""
    pattern = re.compile(r'"([a-zA-Z_][a-zA-Z0-9_]*)"')
    return pattern.sub(r"[\1]", sql)


# ===========================================================================
# Phase 2 — Production-grade apply functions
# ===========================================================================

# -- MSSQL CONVERT style code → PostgreSQL TO_CHAR format string mapping --
_CONVERT_STYLE_TO_PG_FMT: dict[int, str] = {
    101: 'MM/DD/YYYY',   # US
    102: 'YYYY.MM.DD',   # ANSI
    103: 'DD/MM/YYYY',   # UK/French
    104: 'DD.MM.YYYY',   # German
    105: 'DD-MM-YYYY',   # Italian
    106: 'DD Mon YYYY',  # Abbreviated month
    107: 'Mon DD, YYYY', # US with month name
    108: 'HH24:MI:SS',   # Time only
    110: 'MM-DD-YYYY',   # US dash
    111: 'YYYY/MM/DD',   # Japan
    112: 'YYYYMMDD',     # ISO compact
    120: 'YYYY-MM-DD HH24:MI:SS',  # ODBC
    121: 'YYYY-MM-DD HH24:MI:SS.MS',  # ODBC with ms
    126: 'YYYY-MM-DD"T"HH24:MI:SS',  # ISO8601
}

# -- DATENAME unit → TO_CHAR format mapping --
_DATENAME_TO_CHAR_MAP: dict[str, str] = {
    'weekday': 'TMDay',   'dw': 'TMDay',
    'month':   'TMMonth', 'mm': 'TMMonth',
    'year':    'YYYY',    'yy': 'YY', 'yyyy': 'YYYY',
    'quarter': '"Q"Q',
    'dayofyear': 'DDD',   'dy': 'DDD',
    'week':    'WW',      'wk': 'WW',
    'hour':    'HH24',    'hh': 'HH24',
    'minute':  'MI',      'mi': 'MI',
    'second':  'SS',      'ss': 'SS',
}

# -- MSSQL .NET date format → PostgreSQL TO_CHAR format mapping --
_DOTNET_TO_PG_FMT: dict[str, str] = {
    'yyyy': 'YYYY', 'yy': 'YY',
    'MM': 'MM', 'M': 'FMMM',
    'dd': 'DD', 'd': 'FMDD',
    'HH': 'HH24', 'hh': 'HH12',
    'mm': 'MI',
    'ss': 'SS',
    'tt': 'AM',
    'dddd': 'TMDay', 'ddd': 'Dy',
}


def _convert_dotnet_fmt_to_pg(fmt: str) -> str:
    """Convert .NET date format string to PostgreSQL TO_CHAR format."""
    result = fmt.strip("'\"")  # remove quotes
    for mssql_key, pg_val in _DOTNET_TO_PG_FMT.items():
        result = result.replace(mssql_key, pg_val)
    return result


def _apply_sysdatetime_to_now(sql: str, _norm: NormalizedAst) -> str:
    """Replace SYSDATETIME() with NOW()."""
    return re.sub(r"\bSYSDATETIME\s*\(\s*\)", "NOW()", sql, flags=re.IGNORECASE)


def _apply_sysdatetimeoffset_to_now(sql: str, _norm: NormalizedAst) -> str:
    """Replace SYSDATETIMEOFFSET() with NOW()."""
    return re.sub(r"\bSYSDATETIMEOFFSET\s*\(\s*\)", "NOW()", sql, flags=re.IGNORECASE)


def _apply_sysdatetime_to_sysdate(sql: str, _norm: NormalizedAst) -> str:
    """Replace SYSDATETIME() with SYSDATE (DM8)."""
    return re.sub(r"\bSYSDATETIME\s*\(\s*\)", "SYSDATE", sql, flags=re.IGNORECASE)


def _apply_sysdatetimeoffset_to_systimestamp(sql: str, _norm: NormalizedAst) -> str:
    """Replace SYSDATETIMEOFFSET() with SYSTIMESTAMP (DM8)."""
    return re.sub(r"\bSYSDATETIMEOFFSET\s*\(\s*\)", "SYSTIMESTAMP", sql, flags=re.IGNORECASE)


def _apply_eomonth_to_date_trunc(sql: str, _norm: NormalizedAst) -> str:
    """Replace EOMONTH(date) with (DATE_TRUNC('month', date) + INTERVAL '1 month' - INTERVAL '1 day')::date."""
    pattern = re.compile(r"\bEOMONTH\s*\(\s*([^)]+?)\s*\)", re.IGNORECASE)
    def _repl(m: re.Match) -> str:
        date_expr = m.group(1).strip()
        return f"(DATE_TRUNC('month', {date_expr}) + INTERVAL '1 month' - INTERVAL '1 day')::date"
    return pattern.sub(_repl, sql)


def _apply_eomonth_to_last_day(sql: str, _norm: NormalizedAst) -> str:
    """Replace EOMONTH(date) with LAST_DAY(date) (DM8)."""
    return re.sub(
        r"\bEOMONTH\s*\(\s*([^)]+?)\s*\)",
        r"LAST_DAY(\1)",
        sql,
        flags=re.IGNORECASE,
    )


def _apply_format_to_tochar(sql: str, norm: NormalizedAst) -> str:
    """Replace FORMAT(expr, fmt) with TO_CHAR(expr, pg_fmt)."""
    result = sql
    for expr, fmt in norm.format_calls:
        pg_fmt = _convert_dotnet_fmt_to_pg(fmt)
        old = f"FORMAT({expr}, {fmt})"
        new = f"TO_CHAR({expr}, '{pg_fmt}')"
        if old in result:
            result = result.replace(old, new)
        else:
            # Fallback: regex-based replacement
            pattern = re.compile(
                r"\bFORMAT\s*\(\s*" + re.escape(expr) + r"\s*,\s*" + re.escape(fmt) + r"\s*\)",
                re.IGNORECASE,
            )
            result = pattern.sub(f"TO_CHAR({expr}, '{pg_fmt}')", result)
    return result


def _apply_iif_to_case(sql: str, norm: NormalizedAst) -> str:
    """Replace IIF(cond, t, f) with CASE WHEN cond THEN t ELSE f END."""
    result = sql
    for cond, t_val, f_val in norm.iif_calls:
        pattern = re.compile(
            r"\bIIF\s*\(\s*"
            + re.escape(cond)
            + r"\s*,\s*"
            + re.escape(t_val)
            + r"\s*,\s*"
            + re.escape(f_val)
            + r"\s*\)",
            re.IGNORECASE,
        )
        replacement = f"CASE WHEN {cond} THEN {t_val} ELSE {f_val} END"
        result = pattern.sub(replacement, result)
    return result


def _apply_datename_to_tochar(sql: str, _norm: NormalizedAst) -> str:
    """Replace DATENAME(unit, date) with TO_CHAR(date, fmt)."""
    pattern = re.compile(
        r"\bDATENAME\s*\(\s*(\w+)\s*,\s*([^)]+?)\s*\)",
        re.IGNORECASE,
    )
    def _repl(m: re.Match) -> str:
        unit = m.group(1).lower()
        date_expr = m.group(2).strip()
        pg_fmt = _DATENAME_TO_CHAR_MAP.get(unit, unit.upper())
        return f"TO_CHAR({date_expr}, '{pg_fmt}')"
    return pattern.sub(_repl, sql)


def _apply_try_cast_warning(sql: str, norm: NormalizedAst) -> str:
    """Flag TRY_CAST/TRY_CONVERT as needing manual conversion."""
    if norm.try_cast_count > 0:
        return (
            "-- WARNING: TRY_CAST/TRY_CONVERT not directly supported — "
            "use CAST with exception handling or custom function\n"
            + sql
        )
    return sql


def _apply_convert_style(sql: str, norm: NormalizedAst) -> str:
    """Replace CONVERT(type, expr, style) with TO_CHAR(expr, fmt) or CAST."""
    result = sql
    for type_str, expr, style in norm.convert_style_calls:
        style_int = int(style)
        pg_fmt = _CONVERT_STYLE_TO_PG_FMT.get(style_int)
        old_pattern = re.compile(
            r"\bCONVERT\s*\(\s*" + re.escape(type_str) + r"\s*,\s*"
            + re.escape(expr) + r"\s*,\s*" + style + r"\s*\)",
            re.IGNORECASE,
        )
        if pg_fmt:
            replacement = f"TO_CHAR({expr}, '{pg_fmt}')"
        else:
            replacement = f"CAST({expr} AS {type_str})"
        result = old_pattern.sub(replacement, result)
    return result


def _apply_identity_to_lastval(sql: str, _norm: NormalizedAst) -> str:
    """Replace @@IDENTITY and SCOPE_IDENTITY() with LASTVAL()."""
    result = re.sub(r"@@IDENTITY\b", "LASTVAL()", sql, flags=re.IGNORECASE)
    result = re.sub(r"\bSCOPE_IDENTITY\s*\(\s*\)", "LASTVAL()", result, flags=re.IGNORECASE)
    return result


def _apply_ident_current_warning(sql: str, _norm: NormalizedAst) -> str:
    """Flag IDENT_CURRENT as needing sequence name mapping."""
    if re.search(r"\bIDENT_CURRENT\s*\(", sql, re.IGNORECASE):
        return (
            "-- WARNING: IDENT_CURRENT('table') requires manual mapping to "
            "CURRVAL('table_column_seq') — sequence name depends on target schema\n"
            + sql
        )
    return sql


def _apply_concat_to_pipe(sql: str, norm: NormalizedAst) -> str:
    """Replace CONCAT(a, b, ...) with a || b || ..."""
    result = sql
    for args in norm.concat_calls:
        old = "CONCAT(" + ", ".join(args) + ")"
        new = " || ".join(args)
        if old in result:
            result = result.replace(old, new)
        else:
            pattern = re.compile(
                r"\bCONCAT\s*\(" + r"\s*,\s*".join(re.escape(a) for a in args) + r"\)",
                re.IGNORECASE,
            )
            result = pattern.sub(" || ".join(args), result)
    # Fallback: catch any remaining CONCAT(...) that may have been altered
    # by prior rules (e.g. ISNULL→COALESCE changed inner args).
    result = _replace_remaining_concat(result)
    return result


def _replace_remaining_concat(sql: str) -> str:
    """Replace any remaining CONCAT(...) calls with || concatenation."""
    pattern = re.compile(r"\bCONCAT\s*\(", re.IGNORECASE)
    result = sql
    while True:
        m = pattern.search(result)
        if not m:
            break
        start = m.start()
        paren_start = m.end() - 1  # position of '('
        # Find matching closing paren
        depth = 0
        i = paren_start
        while i < len(result):
            if result[i] == '(':
                depth += 1
            elif result[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            break  # unmatched paren, stop
        inner = result[paren_start + 1:i]
        # Split by top-level commas
        args = _split_top_level(inner)
        replacement = " || ".join(a.strip() for a in args)
        result = result[:start] + replacement + result[i + 1:]
    return result


def _split_top_level(s: str) -> list[str]:
    """Split string by commas at parenthesis depth 0."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


def _apply_concat_ws_warning(sql: str, _norm: NormalizedAst) -> str:
    """Flag CONCAT_WS for DM8 (not supported)."""
    if re.search(r"\bCONCAT_WS\s*\(", sql, re.IGNORECASE):
        return (
            "-- WARNING: CONCAT_WS not supported in DM8 — "
            "use custom concatenation with NVL\n"
            + sql
        )
    return sql


def _apply_quotename_warning(sql: str, _norm: NormalizedAst) -> str:
    """Flag QUOTENAME as needing manual conversion."""
    if re.search(r"\bQUOTENAME\s*\(", sql, re.IGNORECASE):
        return (
            "-- WARNING: QUOTENAME requires manual conversion — "
            "use quote_ident() or format()\n"
            + sql
        )
    return sql


def _apply_with_rollup(sql: str, norm: NormalizedAst) -> str:
    """Replace GROUP BY col1, col2 WITH ROLLUP with GROUPING SETS."""
    if not norm.has_rollup:
        return sql
    pattern = re.compile(
        r"\bGROUP\s+BY\s+(.+?)\s+WITH\s+ROLLUP\b",
        re.IGNORECASE | re.DOTALL,
    )
    def _repl(m: re.Match) -> str:
        cols_str = m.group(1).strip()
        cols = [c.strip() for c in cols_str.split(',')]
        n = len(cols)
        # Generate GROUPING SETS: (c1,c2,...,cn), (c1,...,cn-1), ..., (c1), ()
        sets = []
        for i in range(n, -1, -1):
            if i == 0:
                sets.append("()")
            else:
                sets.append(f"({', '.join(cols[:i])})")
        return f"GROUP BY GROUPING SETS ({', '.join(sets)})"
    return pattern.sub(_repl, sql)


def _apply_with_cube(sql: str, norm: NormalizedAst) -> str:
    """Replace GROUP BY col1, col2 WITH CUBE with GROUPING SETS (all combinations)."""
    if not norm.has_cube:
        return sql
    pattern = re.compile(
        r"\bGROUP\s+BY\s+(.+?)\s+WITH\s+CUBE\b",
        re.IGNORECASE | re.DOTALL,
    )
    def _repl(m: re.Match) -> str:
        cols_str = m.group(1).strip()
        cols = [c.strip() for c in cols_str.split(',')]
        # Generate all subsets (2^n combinations)
        from itertools import combinations
        sets = []
        for size in range(len(cols), -1, -1):
            for combo in combinations(cols, size):
                if combo:
                    sets.append(f"({', '.join(combo)})")
                else:
                    sets.append("()")
        return f"GROUP BY GROUPING SETS ({', '.join(sets)})"
    return pattern.sub(_repl, sql)


def _apply_select_into(sql: str, norm: NormalizedAst) -> str:
    """Replace SELECT ... INTO new_table FROM ... with CREATE TABLE new_table AS SELECT ..."""
    if not norm.has_select_into:
        return sql
    pattern = re.compile(
        r"\bSELECT\b(.*?)\bINTO\s+([#\w.]+)\s+(FROM\b.*)",
        re.IGNORECASE | re.DOTALL,
    )
    def _repl(m: re.Match) -> str:
        select_cols = m.group(1).strip()
        table_name = m.group(2).strip()
        # Remove # prefix from temp tables
        if table_name.startswith('#'):
            table_name = table_name[1:]
            if not table_name:
                table_name = "temp_table"
        from_clause = m.group(3).strip()
        return f"CREATE TABLE {table_name} AS\nSELECT {select_cols}\n{from_clause}"
    return pattern.sub(_repl, sql)


def _apply_update_from_join(sql: str, norm: NormalizedAst) -> str:
    """Rewrite UPDATE alias SET ... FROM ... JOIN to subquery form.

    Pattern: UPDATE t SET t.col = val FROM t JOIN other ON ...
    Target:  UPDATE t SET col = val FROM (SELECT ... ) AS _src WHERE ...

    This is a simplified rewrite — complex cases get a WARNING.
    """
    if not norm.has_update_from:
        return sql
    # Simple case: UPDATE alias SET alias.col = expr FROM alias JOIN other ON cond WHERE ...
    pattern = re.compile(
        r"\bUPDATE\s+(\w+)\s+SET\s+(.*?)"
        r"\bFROM\s+(\w+)\s+(\w+)\s+"
        r"(INNER\s+JOIN|LEFT\s+JOIN|JOIN)\s+(\w+)\s+(\w+)\s+ON\s+(.*?)"
        r"(?:\bWHERE\s+(.*))?",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql.strip())
    if not m:
        return (
            "-- WARNING: UPDATE...FROM...JOIN requires manual conversion — "
            "consider rewriting as UPDATE with subquery or MERGE\n"
            + sql
        )

    target_alias = m.group(1)
    set_clause = m.group(2).strip().rstrip(',').rstrip()
    from_table = m.group(3)
    from_alias = m.group(4)
    join_type = m.group(5).upper()
    join_table = m.group(6)
    join_alias = m.group(7)
    join_cond = m.group(8).strip()
    where_clause = m.group(9).strip() if m.group(9) else None

    # Remove alias prefix from SET clause
    set_clean = re.sub(rf"\b{re.escape(target_alias)}\.", "", set_clause)

    # Build subquery
    subq = f"SELECT {join_alias}.*, {from_alias}.* FROM {from_table} {from_alias} {join_type} {join_table} {join_alias} ON {join_cond}"
    if where_clause:
        subq += f" WHERE {where_clause}"

    return (
        f"UPDATE {from_table}\nSET {set_clean}\n"
        f"FROM ({subq}) AS _src\n"
        f"WHERE {from_table}.{join_cond.split('=')[0].strip().split('.')[-1].strip()} = _src.{join_cond.split('=')[0].strip().split('.')[-1].strip()}"
    )


def _apply_delete_from_join(sql: str, norm: NormalizedAst) -> str:
    """Rewrite DELETE alias FROM ... JOIN to subquery form.

    Pattern: DELETE oi FROM OrderItem oi JOIN [Order] o ON oi.order_id = o.order_id WHERE ...
    Target:  DELETE FROM OrderItem WHERE order_id IN (SELECT o.order_id FROM [Order] o WHERE ...)

    Simplified rewrite — complex cases get a WARNING.
    """
    if not norm.has_delete_from:
        return sql
    pattern = re.compile(
        r"\bDELETE\s+(\w+)\s+"
        r"\bFROM\s+(\w+)\s+(\w+)\s+"
        r"(INNER\s+JOIN|LEFT\s+JOIN|JOIN)\s+(\w+)\s+(\w+)\s+ON\s+(.*?)"
        r"(?:\bWHERE\s+(.*))?",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql.strip())
    if not m:
        return (
            "-- WARNING: DELETE...FROM...JOIN requires manual conversion — "
            "consider rewriting as DELETE with subquery\n"
            + sql
        )

    del_alias = m.group(1)
    from_table = m.group(2)
    from_alias = m.group(3)
    join_type = m.group(5)
    join_table = m.group(5) if len(m.groups()) >= 5 else ''
    join_alias = m.group(6) if len(m.groups()) >= 6 else ''
    join_cond = m.group(7).strip() if m.group(7) else ''
    where_clause = m.group(8).strip() if m.group(8) and len(m.groups()) >= 8 else None

    # Extract the key column from the join condition for the subquery
    # Simple heuristic: use the column from the delete table
    key_col = join_cond.split('=')[0].strip().split('.')[-1].strip()

    subq_where = ""
    if where_clause:
        subq_where = f" WHERE {where_clause}"

    return (
        f"DELETE FROM {from_table}\n"
        f"WHERE {key_col} IN (\n"
        f"    SELECT {from_alias}.{key_col}\n"
        f"    FROM {from_table} {from_alias}"
        f"{' ' + join_type + ' ' + join_table + ' ' + join_alias + ' ON ' + join_cond if join_type else ''}"
        f"{subq_where}\n)"
    )


def _apply_for_xml_json_warning(sql: str, norm: NormalizedAst) -> str:
    """Flag FOR XML / FOR JSON as needing application-layer handling."""
    if norm.has_for_xml or norm.has_for_json:
        fmt = "XML" if norm.has_for_xml else "JSON"
        return (
            f"-- WARNING: FOR {fmt} not supported — "
            f"requires application-layer serialization or json_agg/xmlagg\n"
            + sql
        )
    return sql


def _apply_output_clause_warning(sql: str, norm: NormalizedAst) -> str:
    """Flag OUTPUT clause as needing manual conversion."""
    if norm.has_output_clause:
        return (
            "-- WARNING: OUTPUT clause (inserted./deleted.) not supported — "
            "use RETURNING (PG/KB) or manual SELECT after DML\n"
            + sql
        )
    return sql


# ===========================================================================
# Declarative rule lists
# ===========================================================================


# --- MSSQL → KingbaseES / PostgreSQL (14 rules) -----------------------------

MSSQL_TO_PG_RULES: list[RewriteRule] = [
    # TOP PERCENT must be checked BEFORE TOP→LIMIT, otherwise the TOP
    # keyword is consumed by TOP→LIMIT before the PERCENT warning fires.
    RewriteRule(
        id="mssql_to_pg_top_percent_warning",
        name="TOP PERCENT 警告",
        description="TOP N PERCENT 无法自动转换，标记为需要手动处理",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_top_percent_warning,
        confidence=0.50,
    ),
    RewriteRule(
        id="mssql_to_pg_top_to_limit",
        name="TOP → LIMIT",
        description="将 SELECT TOP N 改写为 SELECT ... LIMIT N",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_top_to_limit,
        confidence=0.98,
    ),
    RewriteRule(
        id="mssql_to_pg_getdate_to_now",
        name="GETDATE → NOW",
        description="将 GETDATE() 替换为 NOW()",
        source_db="mssql",
        target_db="kingbasees",
        pattern=r"\bGETDATE\s*\(\s*\)",
        replace="NOW()",
        confidence=0.95,
    ),
    RewriteRule(
        id="mssql_to_pg_getutcdate_to_current_timestamp",
        name="GETUTCDATE → CURRENT_TIMESTAMP",
        description="将 GETUTCDATE() 替换为 CURRENT_TIMESTAMP",
        source_db="mssql",
        target_db="kingbasees",
        pattern=r"\bGETUTCDATE\s*\(\s*\)",
        replace="CURRENT_TIMESTAMP",
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_pg_isnull_to_coalesce",
        name="ISNULL → COALESCE",
        description="将 ISNULL(a, b) 替换为 COALESCE(a, b)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_isnull_to_coalesce,
        confidence=0.92,
    ),
    RewriteRule(
        id="mssql_to_pg_len_to_length",
        name="LEN → LENGTH",
        description="将 LEN(expr) 替换为 LENGTH(expr)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_len_to_length,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_pg_newid_to_gen_random_uuid",
        name="NEWID → gen_random_uuid",
        description="将 NEWID() 替换为 gen_random_uuid()",
        source_db="mssql",
        target_db="kingbasees",
        pattern=r"\bNEWID\s*\(\s*\)",
        replace="gen_random_uuid()",
        confidence=0.95,
    ),
    RewriteRule(
        id="mssql_to_pg_brackets_to_quotes",
        name='[标识符] → "标识符"',
        description="将方括号标识符改写为双引号标识符",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_brackets_to_quotes,
        confidence=0.85,
    ),
    RewriteRule(
        id="mssql_to_pg_charindex_to_position",
        name="CHARINDEX → POSITION",
        description="将 CHARINDEX(a, b) 替换为 POSITION(a IN b)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_charindex_to_position,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_pg_patindex_warning",
        name="PATINDEX 警告",
        description="PATINDEX 语法不兼容，标记为需要手动转换",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_patindex_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_pg_dateadd_to_interval",
        name="DATEADD → + INTERVAL",
        description="将 DATEADD(unit, n, date) 替换为 date + INTERVAL 'n' UNIT",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_dateadd_to_interval,
        confidence=0.82,
    ),
    RewriteRule(
        id="mssql_to_pg_datediff_to_extract",
        name="DATEDIFF → EXTRACT",
        description="将 DATEDIFF(unit, a, b) 替换为 EXTRACT 表达式",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_datediff_to_subtract,
        confidence=0.75,
    ),
    RewriteRule(
        id="mssql_to_pg_datepart_to_extract",
        name="DATEPART → EXTRACT",
        description="将 DATEPART(unit, date) 替换为 EXTRACT(unit FROM date)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_datepart_to_extract,
        confidence=0.88,
    ),
    RewriteRule(
        id="mssql_to_pg_fetch_first_to_limit",
        name="FETCH FIRST → LIMIT",
        description="将 FETCH FIRST N ROWS ONLY 改写为 LIMIT N",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_fetch_first_to_limit,
        confidence=0.95,
    ),
    # ---- Phase 2: Production-grade rules ----
    RewriteRule(
        id="mssql_to_pg_output_clause_warning",
        name="OUTPUT 子句警告",
        description="OUTPUT inserted./deleted. 不支持，标记需手动转换",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_output_clause_warning,
        confidence=0.30,
    ),
    RewriteRule(
        id="mssql_to_pg_try_cast_warning",
        name="TRY_CAST/TRY_CONVERT 警告",
        description="TRY_CAST/TRY_CONVERT 不支持，标记需手动转换",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_try_cast_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_pg_sysdatetime_to_now",
        name="SYSDATETIME → NOW",
        description="将 SYSDATETIME() 替换为 NOW()",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_sysdatetime_to_now,
        confidence=0.92,
    ),
    RewriteRule(
        id="mssql_to_pg_sysdatetimeoffset_to_now",
        name="SYSDATETIMEOFFSET → NOW",
        description="将 SYSDATETIMEOFFSET() 替换为 NOW()",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_sysdatetimeoffset_to_now,
        confidence=0.80,
    ),
    RewriteRule(
        id="mssql_to_pg_eomonth",
        name="EOMONTH → DATE_TRUNC",
        description="将 EOMONTH(date) 替换为 DATE_TRUNC + INTERVAL 表达式",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_eomonth_to_date_trunc,
        confidence=0.78,
    ),
    RewriteRule(
        id="mssql_to_pg_format",
        name="FORMAT → TO_CHAR",
        description="将 FORMAT(expr, fmt) 替换为 TO_CHAR(expr, pg_fmt)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_format_to_tochar,
        confidence=0.70,
    ),
    RewriteRule(
        id="mssql_to_pg_iif",
        name="IIF → CASE WHEN",
        description="将 IIF(cond, t, f) 替换为 CASE WHEN cond THEN t ELSE f END",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_iif_to_case,
        confidence=0.95,
    ),
    RewriteRule(
        id="mssql_to_pg_datename",
        name="DATENAME → TO_CHAR",
        description="将 DATENAME(unit, date) 替换为 TO_CHAR(date, fmt)",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_datename_to_tochar,
        confidence=0.72,
    ),
    RewriteRule(
        id="mssql_to_pg_convert_style",
        name="CONVERT(style) → TO_CHAR",
        description="将 CONVERT(type, expr, style) 替换为 TO_CHAR 或 CAST",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_convert_style,
        confidence=0.65,
    ),
    RewriteRule(
        id="mssql_to_pg_identity",
        name="@@IDENTITY/SCOPE_IDENTITY → LASTVAL",
        description="将 @@IDENTITY 和 SCOPE_IDENTITY() 替换为 LASTVAL()",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_identity_to_lastval,
        confidence=0.60,
    ),
    RewriteRule(
        id="mssql_to_pg_ident_current_warning",
        name="IDENT_CURRENT 警告",
        description="IDENT_CURRENT 需要手动映射序列名",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_ident_current_warning,
        confidence=0.45,
    ),
    RewriteRule(
        id="mssql_to_pg_concat",
        name="CONCAT → ||",
        description="将 CONCAT(a, b, ...) 替换为 a || b || ...",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_concat_to_pipe,
        confidence=0.88,
    ),
    RewriteRule(
        id="mssql_to_pg_quotename_warning",
        name="QUOTENAME 警告",
        description="QUOTENAME 需要手动转换",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_quotename_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_pg_with_rollup",
        name="WITH ROLLUP → GROUPING SETS",
        description="将 GROUP BY ... WITH ROLLUP 改写为 GROUPING SETS",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_with_rollup,
        confidence=0.70,
    ),
    RewriteRule(
        id="mssql_to_pg_with_cube",
        name="WITH CUBE → GROUPING SETS",
        description="将 GROUP BY ... WITH CUBE 改写为 GROUPING SETS（全组合）",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_with_cube,
        confidence=0.60,
    ),
    RewriteRule(
        id="mssql_to_pg_select_into",
        name="SELECT INTO → CREATE TABLE AS",
        description="将 SELECT ... INTO table 改写为 CREATE TABLE AS SELECT",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_select_into,
        confidence=0.75,
    ),
    RewriteRule(
        id="mssql_to_pg_update_from_join",
        name="UPDATE FROM JOIN → 子查询",
        description="将 UPDATE alias SET ... FROM ... JOIN 改写为子查询形式",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_update_from_join,
        confidence=0.55,
    ),
    RewriteRule(
        id="mssql_to_pg_delete_from_join",
        name="DELETE FROM JOIN → 子查询",
        description="将 DELETE alias FROM ... JOIN 改写为 DELETE WHERE IN 子查询",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_delete_from_join,
        confidence=0.55,
    ),
    RewriteRule(
        id="mssql_to_pg_for_xml_json_warning",
        name="FOR XML/JSON 警告",
        description="FOR XML/JSON 不支持，需应用层处理",
        source_db="mssql",
        target_db="kingbasees",
        apply=_apply_for_xml_json_warning,
        confidence=0.30,
    ),
]


# --- MSSQL → DM8 (12 rules) -------------------------------------------------

MSSQL_TO_DM8_RULES: list[RewriteRule] = [
    # TOP PERCENT must be checked BEFORE TOP→LIMIT (same ordering constraint
    # as the PG rule set above).
    RewriteRule(
        id="mssql_to_dm8_top_percent_warning",
        name="TOP PERCENT 警告",
        description="TOP N PERCENT 无法自动转换，标记为需要手动处理",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_top_percent_warning,
        confidence=0.50,
    ),
    RewriteRule(
        id="mssql_to_dm8_top_to_limit",
        name="TOP → LIMIT",
        description="将 SELECT TOP N 改写为 SELECT ... LIMIT N",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_top_to_limit,
        confidence=0.95,
    ),
    RewriteRule(
        id="mssql_to_dm8_getdate_to_sysdate",
        name="GETDATE → SYSDATE",
        description="将 GETDATE() 替换为 SYSDATE",
        source_db="mssql",
        target_db="dm8",
        pattern=r"\bGETDATE\s*\(\s*\)",
        replace="SYSDATE",
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_getutcdate_to_systimestamp",
        name="GETUTCDATE → SYSTIMESTAMP",
        description="将 GETUTCDATE() 替换为 SYSTIMESTAMP",
        source_db="mssql",
        target_db="dm8",
        pattern=r"\bGETUTCDATE\s*\(\s*\)",
        replace="SYSTIMESTAMP",
        confidence=0.85,
    ),
    RewriteRule(
        id="mssql_to_dm8_isnull_to_nvl",
        name="ISNULL → NVL",
        description="将 ISNULL(a, b) 替换为 NVL(a, b)（DM8 Oracle 兼容模式）",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_isnull_to_nvl,
        confidence=0.88,
    ),
    RewriteRule(
        id="mssql_to_dm8_len_to_length",
        name="LEN → LENGTH",
        description="将 LEN(expr) 替换为 LENGTH(expr)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_len_to_length,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_newid_to_sys_guid",
        name="NEWID → SYS_GUID",
        description="将 NEWID() 替换为 SYS_GUID()",
        source_db="mssql",
        target_db="dm8",
        pattern=r"\bNEWID\s*\(\s*\)",
        replace="SYS_GUID()",
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_brackets_to_quotes",
        name='[标识符] → "标识符"',
        description="将方括号标识符改写为双引号标识符",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_brackets_to_quotes,
        confidence=0.85,
    ),
    RewriteRule(
        id="mssql_to_dm8_charindex_to_position",
        name="CHARINDEX → POSITION",
        description="将 CHARINDEX(a, b) 替换为 POSITION(a IN b)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_charindex_to_position,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_dateadd_to_interval",
        name="DATEADD → + INTERVAL",
        description="将 DATEADD(unit, n, date) 替换为 date + INTERVAL 表达式",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_dateadd_to_interval,
        confidence=0.80,
    ),
    RewriteRule(
        id="mssql_to_dm8_datediff_to_extract",
        name="DATEDIFF → EXTRACT",
        description="将 DATEDIFF(unit, a, b) 替换为 EXTRACT 表达式",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_datediff_to_subtract,
        confidence=0.75,
    ),
    RewriteRule(
        id="mssql_to_dm8_datepart_to_extract",
        name="DATEPART → EXTRACT",
        description="将 DATEPART(unit, date) 替换为 EXTRACT(unit FROM date)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_datepart_to_extract,
        confidence=0.85,
    ),
    # ---- Phase 2: Production-grade rules ----
    RewriteRule(
        id="mssql_to_dm8_output_clause_warning",
        name="OUTPUT 子句警告",
        description="OUTPUT inserted./deleted. 不支持，标记需手动转换",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_output_clause_warning,
        confidence=0.30,
    ),
    RewriteRule(
        id="mssql_to_dm8_try_cast_warning",
        name="TRY_CAST/TRY_CONVERT 警告",
        description="TRY_CAST/TRY_CONVERT 不支持，标记需手动转换",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_try_cast_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_dm8_sysdatetime_to_sysdate",
        name="SYSDATETIME → SYSDATE",
        description="将 SYSDATETIME() 替换为 SYSDATE",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_sysdatetime_to_sysdate,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_sysdatetimeoffset_to_systimestamp",
        name="SYSDATETIMEOFFSET → SYSTIMESTAMP",
        description="将 SYSDATETIMEOFFSET() 替换为 SYSTIMESTAMP",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_sysdatetimeoffset_to_systimestamp,
        confidence=0.78,
    ),
    RewriteRule(
        id="mssql_to_dm8_eomonth",
        name="EOMONTH → LAST_DAY",
        description="将 EOMONTH(date) 替换为 LAST_DAY(date)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_eomonth_to_last_day,
        confidence=0.90,
    ),
    RewriteRule(
        id="mssql_to_dm8_format",
        name="FORMAT → TO_CHAR",
        description="将 FORMAT(expr, fmt) 替换为 TO_CHAR(expr, fmt)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_format_to_tochar,
        confidence=0.70,
    ),
    RewriteRule(
        id="mssql_to_dm8_iif",
        name="IIF → CASE WHEN",
        description="将 IIF(cond, t, f) 替换为 CASE WHEN cond THEN t ELSE f END",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_iif_to_case,
        confidence=0.95,
    ),
    RewriteRule(
        id="mssql_to_dm8_datename",
        name="DATENAME → TO_CHAR",
        description="将 DATENAME(unit, date) 替换为 TO_CHAR(date, fmt)",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_datename_to_tochar,
        confidence=0.72,
    ),
    RewriteRule(
        id="mssql_to_dm8_convert_style",
        name="CONVERT(style) → TO_CHAR",
        description="将 CONVERT(type, expr, style) 替换为 TO_CHAR 或 CAST",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_convert_style,
        confidence=0.65,
    ),
    RewriteRule(
        id="mssql_to_dm8_identity",
        name="@@IDENTITY/SCOPE_IDENTITY → LASTVAL",
        description="将 @@IDENTITY 和 SCOPE_IDENTITY() 替换为 LASTVAL()",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_identity_to_lastval,
        confidence=0.55,
    ),
    RewriteRule(
        id="mssql_to_dm8_ident_current_warning",
        name="IDENT_CURRENT 警告",
        description="IDENT_CURRENT 需要手动映射序列名",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_ident_current_warning,
        confidence=0.45,
    ),
    RewriteRule(
        id="mssql_to_dm8_concat",
        name="CONCAT → ||",
        description="将 CONCAT(a, b, ...) 替换为 a || b || ...",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_concat_to_pipe,
        confidence=0.85,
    ),
    RewriteRule(
        id="mssql_to_dm8_concat_ws_warning",
        name="CONCAT_WS 警告",
        description="CONCAT_WS 在 DM8 中不支持，标记需手动转换",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_concat_ws_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_dm8_quotename_warning",
        name="QUOTENAME 警告",
        description="QUOTENAME 需要手动转换",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_quotename_warning,
        confidence=0.40,
    ),
    RewriteRule(
        id="mssql_to_dm8_with_rollup",
        name="WITH ROLLUP → GROUPING SETS",
        description="将 GROUP BY ... WITH ROLLUP 改写为 GROUPING SETS",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_with_rollup,
        confidence=0.70,
    ),
    RewriteRule(
        id="mssql_to_dm8_with_cube",
        name="WITH CUBE → GROUPING SETS",
        description="将 GROUP BY ... WITH CUBE 改写为 GROUPING SETS（全组合）",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_with_cube,
        confidence=0.60,
    ),
    RewriteRule(
        id="mssql_to_dm8_select_into",
        name="SELECT INTO → CREATE TABLE AS",
        description="将 SELECT ... INTO table 改写为 CREATE TABLE AS SELECT",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_select_into,
        confidence=0.75,
    ),
    RewriteRule(
        id="mssql_to_dm8_update_from_join",
        name="UPDATE FROM JOIN → 子查询",
        description="将 UPDATE alias SET ... FROM ... JOIN 改写为子查询形式",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_update_from_join,
        confidence=0.55,
    ),
    RewriteRule(
        id="mssql_to_dm8_delete_from_join",
        name="DELETE FROM JOIN → 子查询",
        description="将 DELETE alias FROM ... JOIN 改写为 DELETE WHERE IN 子查询",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_delete_from_join,
        confidence=0.55,
    ),
    RewriteRule(
        id="mssql_to_dm8_for_xml_json_warning",
        name="FOR XML/JSON 警告",
        description="FOR XML/JSON 不支持，需应用层处理",
        source_db="mssql",
        target_db="dm8",
        apply=_apply_for_xml_json_warning,
        confidence=0.30,
    ),
]


# --- KingbaseES → MSSQL reverse rules (6 rules) -----------------------------

KINGBASEES_TO_MSSQL_RULES: list[RewriteRule] = [
    RewriteRule(
        id="kingbasees_to_mssql_limit_to_top",
        name="LIMIT → TOP",
        description="将 LIMIT N 改写为 SELECT TOP N（前置）",
        source_db="kingbasees",
        target_db="mssql",
        apply=_apply_limit_to_top,
        confidence=0.85,
    ),
    RewriteRule(
        id="kingbasees_to_mssql_now_to_getdate",
        name="NOW → GETDATE",
        description="将 NOW() 替换为 GETDATE()",
        source_db="kingbasees",
        target_db="mssql",
        pattern=r"\bNOW\s*\(\s*\)",
        replace="GETDATE()",
        confidence=0.95,
    ),
    RewriteRule(
        id="kingbasees_to_mssql_coalesce_to_isnull",
        name="COALESCE → ISNULL",
        description="将 COALESCE(a, b) 替换为 ISNULL(a, b)（仅双参数时安全）",
        source_db="kingbasees",
        target_db="mssql",
        apply=_apply_coalesce_to_isnull,
        confidence=0.70,
    ),
    RewriteRule(
        id="kingbasees_to_mssql_length_to_len",
        name="LENGTH → LEN",
        description="将 LENGTH(expr) 替换为 LEN(expr)",
        source_db="kingbasees",
        target_db="mssql",
        pattern=r"\bLENGTH\s*\(",
        replace="LEN(",
        confidence=0.85,
    ),
    RewriteRule(
        id="kingbasees_to_mssql_gen_random_uuid_to_newid",
        name="gen_random_uuid → NEWID",
        description="将 gen_random_uuid() 替换为 NEWID()",
        source_db="kingbasees",
        target_db="mssql",
        pattern=r"\bgen_random_uuid\s*\(\s*\)",
        replace="NEWID()",
        confidence=0.95,
    ),
    RewriteRule(
        id="kingbasees_to_mssql_quotes_to_brackets",
        name='"..." → [...]',
        description="将双引号标识符改写为方括号标识符",
        source_db="kingbasees",
        target_db="mssql",
        apply=_apply_quotes_to_brackets,
        confidence=0.80,
    ),
]


# ===========================================================================
# Rule registry
# ===========================================================================

# --- MSSQL → KingbaseES MSSQL-compat (filtered rules) -----------------------
# Remote KingbaseES servers typically run in MSSQL compatibility mode, which
# natively supports GETDATE, ISNULL, LEN, TOP, [brackets], NEWID, DATEADD,
# FORMAT, CONCAT, EOMONTH, @@IDENTITY, IIF, etc.  Only structural rewrites
# (TOP→LIMIT, bracket→quote, etc.) are needed; function-level rewrites to
# PG-specific syntax (gen_random_uuid, INTERVAL, TO_CHAR, ||, LASTVAL) must
# be SKIPPED because those PG functions are unavailable in MSSQL compat mode.

_KBES_MSSQL_COMPAT_SKIP_IDS: set[str] = {
    "mssql_to_pg_newid_to_gen_random_uuid",   # NEWID() works natively
    "mssql_to_pg_dateadd_to_interval",         # DATEADD() works natively; INTERVAL syntax unsupported
    "mssql_to_pg_datediff_to_subtract",        # DATEDIFF() works natively
    "mssql_to_pg_datepart_to_extract",         # DATEPART() works natively
    "mssql_to_pg_eomonth",                     # EOMONTH() works natively
    "mssql_to_pg_format",                      # FORMAT() works natively; TO_CHAR datetime type mismatch
    "mssql_to_pg_datename",                    # DATENAME() works natively
    "mssql_to_pg_convert_style",               # CONVERT(style) works natively
    "mssql_to_pg_identity",                    # @@IDENTITY works natively; LASTVAL() unavailable
    "mssql_to_pg_concat",                      # CONCAT() works natively; || operator type mismatch
    "mssql_to_pg_iif",                         # IIF() works natively in MSSQL compat
}

MSSQL_TO_KBES_MSSQL_RULES: list[RewriteRule] = [
    r for r in MSSQL_TO_PG_RULES
    if r.id not in _KBES_MSSQL_COMPAT_SKIP_IDS
]

RULE_REGISTRY: dict[tuple[str, str], list[RewriteRule]] = {
    ("mssql", "kingbasees"): MSSQL_TO_KBES_MSSQL_RULES,
    ("mssql", "dm8"): MSSQL_TO_DM8_RULES,
    ("kingbasees", "mssql"): KINGBASEES_TO_MSSQL_RULES,
    ("kingbasees", "dm8"): [],                    # TBD
    ("dm8", "mssql"): [],                        # TBD
    ("dm8", "kingbasees"): [],                   # TBD
}


# ===========================================================================
# Public API
# ===========================================================================


def get_rules(source_db: str, target_db: str) -> list[RewriteRule]:
    """Get all rewrite rules for a given source→target pair.

    Args:
        source_db: Source database dialect (mssql, kingbasees, dm8).
        target_db: Target database dialect (mssql, kingbasees, dm8).

    Returns:
        List of RewriteRule instances, possibly empty if no rules defined.
    """
    return RULE_REGISTRY.get((source_db, target_db), [])


def apply_rules(
    sql: str,
    norm: NormalizedAst,
    rules: list[RewriteRule],
) -> tuple[str, list[AppliedRuleInfo], list[str]]:
    """Apply rewrite rules sequentially against a normalized AST.

    This is the centralized rule executor.  For each rule:
      1. If rule.apply is set → call it with (current_sql, current_norm)
      2. Else if rule.pattern + rule.replace are set → regex substitute
      3. On success (SQL changed) → record in applied list, refresh AST
      4. On failure → log warning, skip rule, keep previous SQL

    Args:
        sql:  Current SQL string (may have been modified by prior rules).
        norm: NormalizedAst for the *original* SQL (refreshed after each hit).
        rules: Ordered list of RewriteRule instances to attempt.

    Returns:
        Tuple of (rewritten_sql, applied_rules, warnings).
    """
    current_sql = sql
    current_norm = norm
    applied: list[AppliedRuleInfo] = []
    warnings: list[str] = []

    for rule in rules:
        before = current_sql
        try:
            if rule.apply is not None:
                current_sql = rule.apply(current_sql, current_norm)
            elif rule.pattern is not None and rule.replace is not None:
                current_sql = re.sub(
                    rule.pattern,
                    rule.replace,
                    current_sql,
                    flags=re.IGNORECASE,
                )
            else:
                # Malformed rule — neither apply nor pattern+replace set
                warnings.append(
                    f"Rule '{rule.name}' ({rule.id}) has no apply function "
                    f"and no pattern/replace — skipping."
                )
                continue
        except Exception as exc:
            warnings.append(
                f"Rule '{rule.name}' failed with error: {exc}. "
                f"Skipping this rule."
            )
            current_sql = before
            continue

        # Record if the rule changed anything
        if current_sql != before:
            applied.append(
                AppliedRuleInfo(
                    name=rule.name,
                    description=rule.description,
                    confidence=rule.confidence,
                )
            )
            current_norm = normalize(current_sql)  # refresh AST for next rules

    return current_sql, applied, warnings


def compute_overall_confidence(confidences: list[float]) -> float:
    """Compute overall confidence as the geometric mean of per-rule confidences.

    Geometric mean penalizes low-confidence rules more heavily than
    arithmetic mean, giving a conservative estimate.

    Args:
        confidences: Confidence values of rules that were actually applied.

    Returns:
        Overall confidence score in [0.0, 1.0]. Returns 1.0 if empty.
    """
    if not confidences:
        return 1.0

    product = math.prod(confidences)
    return product ** (1.0 / len(confidences))
