"""
SQL Object Risk Analyzer — maps extracted objects to cross-DB risk levels.

For each extracted object (table, column, function, join), determines:
  1. Compatibility with each target database
  2. Risk level based on rewriteability and known incompatibilities
  3. Specific issues / failure reasons

Uses the existing rewrite rule engine to determine if a dialect function
can be automatically rewritten.

Two entry points:
  - analyze_objects(objects, db_types) — original, takes ExtractedObjects
  - analyze_objects_from_context(ctx) — kernel path, takes SQLSemanticContext
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.api.sql_compare.rewrite.rules import RULE_REGISTRY, RewriteRule

from .diagnose_schemas import (
    ColumnDiagnostic,
    DiagnoseSummary,
    DbCompatibility,
    FunctionDiagnostic,
    JoinDiagnostic,
    RiskLevel,
    RiskSummary,
    TableDiagnostic,
)
from .extractor import ExtractedObjects, FunctionRef

if TYPE_CHECKING:
    from app.core.sql_kernel.semantic_context import SQLSemanticContext

# ---------------------------------------------------------------------------
# Known incompatibilities per database
# ---------------------------------------------------------------------------

# Functions that are KNOWN to be supported in each DB (beyond standard SQL)
_DB_NATIVE_FUNCTIONS: dict[str, set[str]] = {
    "mssql": {
        "GETDATE", "GETUTCDATE", "ISNULL", "LEN", "NEWID",
        "CHARINDEX", "PATINDEX", "DATEADD", "DATEDIFF", "DATEPART",
        "STUFF", "REPLICATE", "SPACE", "SCOPE_IDENTITY", "ROWCOUNT",
        "TOP",
    },
    "kingbasees": {
        "NOW", "CURRENT_TIMESTAMP", "COALESCE", "LENGTH",
        "POSITION", "EXTRACT", "AGE",
        "gen_random_uuid",
    },
    "dm8": {
        "SYSDATE", "SYSTIMESTAMP", "NVL", "LENGTH",
        "POSITION", "EXTRACT",
        "SYS_GUID",
    },
}

# Dialect functions that the rewrite engine CAN handle (has a rule)
# This is checked dynamically via RULE_REGISTRY but we cache known rewrite pairs


# ---------------------------------------------------------------------------
# Analyzer result types
# ---------------------------------------------------------------------------


@dataclass
class ObjectAnalysis:
    """Complete analysis result for a single SQL statement."""

    tables: list[TableDiagnostic] = field(default_factory=list)
    columns: list[ColumnDiagnostic] = field(default_factory=list)
    functions: list[FunctionDiagnostic] = field(default_factory=list)
    joins: list[JoinDiagnostic] = field(default_factory=list)
    summary: DiagnoseSummary = field(default_factory=DiagnoseSummary)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_objects(
    objects: ExtractedObjects,
    db_types: list[str],
) -> ObjectAnalysis:
    """Analyze extracted objects for cross-DB compatibility.

    Args:
        objects: Extracted SQL objects from the extractor.
        db_types: Target database types to check compatibility against.

    Returns:
        ObjectAnalysis with per-object risk levels and compatibility maps.
    """
    tables = [_analyze_table(t, db_types) for t in objects.tables]
    columns = [_analyze_column(c, db_types) for c in objects.columns]
    functions = [_analyze_function(f, db_types) for f in objects.functions]
    joins = [_analyze_join(j, db_types) for j in objects.joins]

    summary = _build_summary(tables, columns, functions, joins)

    return ObjectAnalysis(
        tables=tables,
        columns=columns,
        functions=functions,
        joins=joins,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Kernel entry point — uses pre-built SQLSemanticContext
# ---------------------------------------------------------------------------


def analyze_objects_from_context(
    ctx: "SQLSemanticContext",
) -> ObjectAnalysis:
    """Analyze SQL objects for cross-DB compatibility using a pre-built context.

    This is the kernel path — it uses the context's pre-extracted objects
    instead of requiring a separate ExtractedObjects parameter.

    Args:
        ctx: Pre-built SQLSemanticContext from the kernel.

    Returns:
        ObjectAnalysis with per-object risk levels and compatibility maps.
    """
    db_types = [ctx.target_db]

    tables = [_analyze_table(t, db_types) for t in ctx.tables]
    columns = [_analyze_column(c, db_types) for c in ctx.columns]
    functions = [_analyze_function(f, db_types) for f in ctx.functions]
    joins = [_analyze_join(j, db_types) for j in ctx.joins]

    summary = _build_summary(tables, columns, functions, joins)

    return ObjectAnalysis(
        tables=tables,
        columns=columns,
        functions=functions,
        joins=joins,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Table analysis
# ---------------------------------------------------------------------------


def _analyze_table(table, db_types: list[str]) -> TableDiagnostic:
    """Analyze a table reference for cross-DB compatibility.

    Table-level risks:
      - Bracket identifiers [table] — not supported in PG/DM8
      - Reserved word table names
      - Names with special characters
    """
    issues: list[str] = []
    db_compat: dict[str, bool] = {}

    has_brackets = bool(re.search(r'[\[\]]', table.name))
    is_reserved = table.name.upper() in _SQL_RESERVED_WORDS

    for db in db_types:
        compat = True
        db_issues: list[str] = []

        if has_brackets and db != "mssql":
            db_issues.append(f"Bracket quoting [ ] not supported in {db}")
            compat = False

        if is_reserved and db != "mssql":
            db_issues.append(f"'{table.name}' is a reserved word in {db}")

        db_compat[db] = compat
        if db_issues:
            issues.extend(db_issues)

    risk = _table_risk(issues, has_brackets, is_reserved)

    return TableDiagnostic(
        name=table.name,
        alias=table.alias,
        risk=risk,
        issues=issues,
        db_compatibility=db_compat,
    )


def _table_risk(issues: list[str], has_brackets: bool, is_reserved: bool) -> RiskLevel:
    """Determine table risk level."""
    if has_brackets:
        return RiskLevel.MEDIUM
    if is_reserved:
        return RiskLevel.LOW
    if issues:
        return RiskLevel.LOW
    return RiskLevel.NONE


# ---------------------------------------------------------------------------
# Column analysis
# ---------------------------------------------------------------------------


def _analyze_column(column, db_types: list[str]) -> ColumnDiagnostic:
    """Analyze a column reference for cross-DB compatibility.

    Column-level risks:
      - Bracket identifiers around column name
      - DB-specific type indicators in the name (e.g., 'uniqueidentifier')
      - Reserved word column names
    """
    issues: list[str] = []
    db_compat: dict[str, bool] = {}

    has_brackets = bool(re.search(r'[\[\]]', column.name))
    is_reserved = column.name.upper() in _SQL_RESERVED_WORDS

    for db in db_types:
        compat = True
        db_issues: list[str] = []

        if has_brackets and db != "mssql":
            db_issues.append(f"Bracket quoting [ ] not supported in {db}")
            compat = False

        if is_reserved and db != "mssql":
            db_issues.append(f"'{column.name}' is a reserved word in {db}")

        db_compat[db] = compat
        if db_issues:
            issues.extend(db_issues)

    risk = RiskLevel.LOW if issues else RiskLevel.NONE

    return ColumnDiagnostic(
        name=column.full_name,
        column=column.name,
        table_ref=column.table_ref,
        risk=risk,
        issues=issues,
        db_compatibility=db_compat,
    )


# ---------------------------------------------------------------------------
# Function analysis
# ---------------------------------------------------------------------------


def _analyze_function(func: FunctionRef, db_types: list[str]) -> FunctionDiagnostic:
    """Analyze a function call for cross-DB compatibility.

    Risk classification for functions:
      NONE   — standard SQL function, compatible everywhere
      LOW    — can be automatically rewritten (confidence ≥ 0.9)
      MEDIUM — can be rewritten but needs review (confidence < 0.9)
      HIGH   — dialect function with no rewrite rule for this direction
      CRITICAL — fundamental incompatibility (very rare)
    """
    issues: list[str] = []
    db_compat: dict[str, bool] = {}
    has_rewrite_rule = False

    name = func.name.upper()

    for db in db_types:
        if _is_compatible_function(name, db):
            db_compat[db] = True
        else:
            # Check if there's a rewrite rule covering this function
            rewrite_available = _has_rewrite_coverage(name, db)
            if rewrite_available:
                has_rewrite_rule = True
                db_compat[db] = True
                issues.append(f"'{func.raw}' requires rewrite for {db}")
            else:
                db_compat[db] = False
                issues.append(f"'{func.raw}' not supported in {db}")

    risk = _function_risk(name, db_compat, has_rewrite_rule)

    return FunctionDiagnostic(
        name=name,
        raw=func.raw,
        risk=risk,
        issues=issues,
        db_compatibility=db_compat,
        has_rewrite_rule=has_rewrite_rule,
    )


def _is_compatible_function(name: str, db_type: str) -> bool:
    """Check if a function is natively supported in the given database."""
    # Standard SQL functions are compatible everywhere
    if name in {
        "COUNT", "SUM", "AVG", "MIN", "MAX",
        "COALESCE", "NULLIF", "CAST",
        "UPPER", "LOWER", "TRIM",
        "SUBSTRING", "REPLACE",
        "ABS", "ROUND", "CEILING", "FLOOR",
        "CURRENT_TIMESTAMP", "CURRENT_DATE",
        "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE",
        "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
        "CONCAT",
    }:
        return True

    # Check DB-specific native support
    native = _DB_NATIVE_FUNCTIONS.get(db_type, set())
    if name in native:
        return True

    return False


def _has_rewrite_coverage(function_name: str, target_db: str) -> bool:
    """Check if the rewrite engine has a rule covering this function → target DB.

    Searches all rule sets for a rule whose name contains the function name
    and targets the given database.
    """
    for (src, tgt), rules in RULE_REGISTRY.items():
        if tgt != target_db:
            continue
        for rule in rules:
            if function_name.upper() in rule.name.upper():
                return True
    return False


def _function_risk(
    name: str,
    db_compat: dict[str, bool],
    has_rewrite: bool,
) -> RiskLevel:
    """Determine function risk level based on compatibility across DBs."""
    all_compat = all(db_compat.values())
    any_compat = any(db_compat.values())

    if all_compat and not has_rewrite:
        # TOP is a special case — it's a pseudo-function that always needs care
        if name == "TOP":
            return RiskLevel.LOW
        return RiskLevel.NONE

    if all_compat and has_rewrite:
        return RiskLevel.LOW

    if any_compat and has_rewrite:
        return RiskLevel.MEDIUM

    if not any_compat:
        return RiskLevel.HIGH

    return RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# Join analysis
# ---------------------------------------------------------------------------


def _analyze_join(join, db_types: list[str]) -> JoinDiagnostic:
    """Analyze a JOIN clause for cross-DB compatibility.

    Most JOIN types are standard SQL.  FULL OUTER JOIN and CROSS JOIN
    may have subtle semantic differences across databases.
    """
    issues: list[str] = []
    db_compat: dict[str, bool] = {}

    join_type = join.join_type.upper()
    risk = RiskLevel.NONE

    # FULL OUTER JOIN — supported everywhere but semantics may differ
    if join_type in ("FULL",):
        risk = RiskLevel.LOW
        issues.append("FULL OUTER JOIN may have semantic differences across databases")

    # CROSS JOIN — supported everywhere but some DBs optimize differently
    if join_type in ("CROSS",):
        risk = RiskLevel.LOW
        issues.append("CROSS JOIN behavior may vary with optimizer settings")

    # NATURAL JOIN — not recommended, behavior varies
    if join_type in ("NATURAL",):
        risk = RiskLevel.MEDIUM
        issues.append("NATURAL JOIN is not recommended for cross-DB compatibility")

    for db in db_types:
        db_compat[db] = True  # Joins are generally compatible

    return JoinDiagnostic(
        join_type=join_type,
        table=join.table,
        alias=join.alias,
        condition=join.condition,
        risk=risk,
        issues=issues,
        db_compatibility=db_compat,
    )


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _build_summary(
    tables: list[TableDiagnostic],
    columns: list[ColumnDiagnostic],
    functions: list[FunctionDiagnostic],
    joins: list[JoinDiagnostic],
) -> DiagnoseSummary:
    """Build a summary counting objects by risk level."""

    def _count(items, risk_level: RiskLevel) -> int:
        return sum(1 for item in items if item.risk == risk_level)

    def _make_summary(items) -> RiskSummary:
        return RiskSummary(
            NONE=_count(items, RiskLevel.NONE),
            LOW=_count(items, RiskLevel.LOW),
            MEDIUM=_count(items, RiskLevel.MEDIUM),
            HIGH=_count(items, RiskLevel.HIGH),
            CRITICAL=_count(items, RiskLevel.CRITICAL),
        )

    total = len(tables) + len(columns) + len(functions) + len(joins)

    return DiagnoseSummary(
        total_objects=total,
        tables=_make_summary(tables),
        columns=_make_summary(columns),
        functions=_make_summary(functions),
        joins=_make_summary(joins),
    )


# ---------------------------------------------------------------------------
# SQL reserved words (subset that commonly causes issues)
# ---------------------------------------------------------------------------

_SQL_RESERVED_WORDS: frozenset[str] = frozenset({
    "ORDER", "GROUP", "SELECT", "FROM", "WHERE", "TABLE",
    "INDEX", "VIEW", "USER", "ROLE", "SCHEMA", "DATABASE",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "KEY", "VALUE", "TYPE", "NAME", "STATE", "STATUS",
    "LEVEL", "SIZE", "DATE", "TIME", "TIMESTAMP",
    "ROW", "COLUMN", "CHECK", "DEFAULT", "PRIMARY",
    "FOREIGN", "REFERENCES", "CONSTRAINT",
    "ASC", "DESC", "LIMIT", "OFFSET", "FETCH",
    "UNION", "INTERSECT", "EXCEPT",
    "GRANT", "REVOKE", "DENY",
    "COMMIT", "ROLLBACK", "SAVEPOINT",
    "CROSS", "FULL", "INNER", "JOIN", "LEFT", "NATURAL",
    "OUTER", "RIGHT", "ON",
    "BETWEEN", "IN", "IS", "LIKE", "NOT", "NULL",
    "AND", "OR", "XOR", "TRUE", "FALSE",
    "ANY", "ALL", "SOME", "EXISTS",
    "BEGIN", "DECLARE", "EXEC", "EXECUTE", "CALL",
})
