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

RULE_REGISTRY: dict[tuple[str, str], list[RewriteRule]] = {
    ("mssql", "kingbasees"): MSSQL_TO_PG_RULES,
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
