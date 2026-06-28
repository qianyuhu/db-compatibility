"""
Data Drift Analyzer — predicts row-level and column-level data differences.

Analyses how data values may shift between source and target database execution
without actually running the queries. Focuses on three drift categories:

    1. Row-level drift — table row counts may differ (JOIN multiplicity, NULL handling)
    2. NULL semantics drift — MSSQL vs PostgreSQL NULL comparison defaults
    3. Aggregation stability — SUM/AVG/COUNT behaviour across dialects
"""

from __future__ import annotations

from app.api.sql_diagnostics.extractor import (
    ExtractedObjects,
    extract_objects,
    FunctionRef,
    JoinRef,
    TableRef,
)

from .schemas import (
    DriftLevel,
    QueryBehavior,
    RiskLevel,
    RowLevelDiff,
    TableDrift,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_drift(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> RowLevelDiff:
    """Analyse expected data drift between source and target execution.

    Args:
        original_objects: Extracted objects from original SQL.
        rewritten_objects: Extracted objects from rewritten SQL.
        source_db: Source database type.
        target_db: Target database type.

    Returns:
        RowLevelDiff with per-table drift assessments.
    """
    table_drifts: list[TableDrift] = []
    affected_tables: list[str] = []

    # Collect all unique tables
    all_tables: dict[str, TableRef] = {}
    for t in original_objects.tables:
        all_tables.setdefault(t.name.lower(), t)
    for t in rewritten_objects.tables:
        all_tables.setdefault(t.name.lower(), t)

    for table_name, table_ref in all_tables.items():
        drift = _assess_table_drift(
            table_name,
            original_objects,
            rewritten_objects,
            source_db,
            target_db,
        )
        table_drifts.append(drift)
        if drift.drift != DriftLevel.STABLE:
            affected_tables.append(table_name)

    # Overall variance
    overall_variance = _compute_overall_variance(table_drifts)
    description = _describe_overall_drift(table_drifts, source_db, target_db)

    return RowLevelDiff(
        expected_variance=overall_variance,
        affected_tables=affected_tables,
        table_drifts=table_drifts,
        description=description,
    )


def analyze_query_behavior(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> QueryBehavior:
    """Analyse how query execution behaviour may change after migration.

    Checks:
        - JOIN cardinality shifts
        - NULL semantics changes
        - Aggregation stability
        - Ordering stability
        - Type coercion changes
    """
    # JOIN cardinality shift
    join_shift = _assess_join_cardinality_shift(
        original_objects, rewritten_objects
    )

    # NULL semantics (MSSQL default ANSI_NULLS ON vs PG standard)
    null_change = _assess_null_semantics(source_db, target_db, original_objects)

    # Aggregation stability
    agg_stability = _assess_aggregation_stability(
        original_objects, rewritten_objects, source_db, target_db
    )

    # Ordering stability
    ordering_stability = _assess_ordering_stability(
        original_objects, rewritten_objects
    )

    # Type coercion changes
    type_changes = _detect_type_coercion_changes(
        original_objects, rewritten_objects, source_db, target_db
    )

    return QueryBehavior(
        join_cardinality_shift=join_shift,
        null_semantics_change=null_change,
        aggregation_stability=agg_stability,
        ordering_stability=ordering_stability,
        type_coercion_changes=type_changes,
    )


# ---------------------------------------------------------------------------
# Table drift assessment
# ---------------------------------------------------------------------------


def _assess_table_drift(
    table_name: str,
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> TableDrift:
    """Assess drift likelihood for a single table."""
    reasons: list[str] = []

    # Check if table appears in both original and rewritten
    orig_table_names = {t.name.lower() for t in original_objects.tables}
    rewritten_table_names = {t.name.lower() for t in rewritten_objects.tables}

    in_original = table_name in orig_table_names
    in_rewritten = table_name in rewritten_table_names

    # Check if this table is in a JOIN — JOIN multiplicity changes cause drift
    orig_joins_for_table = [
        j for j in original_objects.joins
        if j.table.lower() == table_name
    ]
    rewritten_joins_for_table = [
        j for j in rewritten_objects.joins
        if j.table.lower() == table_name
    ]

    # FULL JOIN or CROSS JOIN → higher drift risk
    has_full_join = any(
        j.join_type.upper() == "FULL" for j in orig_joins_for_table
    )
    has_cross_join = any(
        j.join_type.upper() == "CROSS" for j in orig_joins_for_table
    )
    has_left_join = any(
        j.join_type.upper() == "LEFT" for j in orig_joins_for_table
    )

    if has_full_join:
        reasons.append("FULL JOIN 在目标数据库可能产生不同行数")
    if has_cross_join:
        reasons.append("CROSS JOIN 基数依赖于优化器行为")
    if has_left_join:
        reasons.append("LEFT JOIN NULL 处理在跨库间可能不同")

    # NULL-related functions on columns from this table
    null_funcs = ("ISNULL", "COALESCE", "NVL", "NULLIF")
    has_null_funcs = any(
        f.name.upper() in null_funcs for f in original_objects.functions
    )
    if has_null_funcs and table_name in orig_table_names:
        reasons.append("NULL 处理函数在不同数据库间语义可能不同")

    # Determine drift level
    if has_full_join:
        drift = DriftLevel.MODERATE_DRIFT
        variance = "1-5%"
    elif has_cross_join or (has_left_join and has_null_funcs):
        drift = DriftLevel.LOW_DRIFT
        variance = "<1%"
    elif has_left_join:
        drift = DriftLevel.LOW_DRIFT
        variance = "<0.5%"
    else:
        drift = DriftLevel.STABLE
        variance = "0%"

    return TableDrift(
        table=table_name,
        drift=drift,
        expected_variance=variance,
        reason="; ".join(reasons) if reasons else "无预期数据漂移",
    )


def _compute_overall_variance(table_drifts: list[TableDrift]) -> str:
    """Compute the overall expected variance across all tables."""
    if not table_drifts:
        return "0%"

    moderate = sum(1 for t in table_drifts if t.drift == DriftLevel.MODERATE_DRIFT)
    low = sum(1 for t in table_drifts if t.drift == DriftLevel.LOW_DRIFT)
    high = sum(1 for t in table_drifts if t.drift == DriftLevel.HIGH_DRIFT)

    if high > 0:
        return ">5%"
    if moderate >= 2:
        return "3-5%"
    if moderate == 1:
        return "1-3%"
    if low > 0:
        return "<1%"
    return "0%"


def _describe_overall_drift(
    table_drifts: list[TableDrift],
    source_db: str,
    target_db: str,
) -> str:
    """Generate a human-readable summary of overall data drift."""
    stable = sum(1 for t in table_drifts if t.drift == DriftLevel.STABLE)
    drifted = sum(1 for t in table_drifts if t.drift != DriftLevel.STABLE)

    if drifted == 0:
        return (
            f"从 {source_db.upper()} 迁移到 {target_db.upper()} 后，"
            f"所有 {len(table_drifts)} 张表的数据预期保持稳定，无明显漂移"
        )

    drift_tables = [t.table for t in table_drifts if t.drift != DriftLevel.STABLE]
    return (
        f"从 {source_db.upper()} 迁移到 {target_db.upper()} 后，"
        f"{drifted}/{len(table_drifts)} 张表可能有数据漂移：{', '.join(drift_tables)}。"
        f"{stable} 张表预期稳定"
    )


# ---------------------------------------------------------------------------
# Query behaviour assessment
# ---------------------------------------------------------------------------


def _assess_join_cardinality_shift(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
) -> str | None:
    """Estimate JOIN cardinality shift between original and rewritten SQL."""
    orig_join_count = len(original_objects.joins)
    rewritten_join_count = len(rewritten_objects.joins)

    if orig_join_count == 0:
        return None

    # Check for JOIN type changes
    orig_join_types = {j.join_type.upper() for j in original_objects.joins}
    rewritten_join_types = {j.join_type.upper() for j in rewritten_objects.joins}

    if orig_join_types != rewritten_join_types:
        # JOIN type was changed during rewrite (unlikely with current rules)
        return "JOIN 类型变更，基数可能不同"

    # Estimate based on LEFT JOIN presence
    left_joins = sum(
        1 for j in original_objects.joins if j.join_type.upper() == "LEFT"
    )
    if left_joins > 0:
        # LEFT JOINs are sensitive to NULL handling differences
        return f"+{left_joins * 1.5:.1f}%"

    return "+0.0%"


def _assess_null_semantics(
    source_db: str,
    target_db: str,
    original_objects: ExtractedObjects,
) -> bool:
    """Determine if NULL semantics change between source and target.

    MSSQL uses ANSI_NULLS (configurable per session), while PostgreSQL
    and DM8 always use standard SQL NULL semantics. If the source SQL
    uses NULL comparison patterns, this is flagged.
    """
    if source_db == target_db:
        return False

    # NULL semantics differ when crossing between MSSQL and PG-family databases
    if source_db == "mssql" and target_db in ("kingbasees", "dm8"):
        # Check for NULL comparison patterns
        null_sensitive_funcs = {"ISNULL", "NULLIF", "COALESCE"}
        has_null_funcs = any(
            f.name.upper() in null_sensitive_funcs
            for f in original_objects.functions
        )
        if has_null_funcs:
            return True

        # Check for WHERE col = NULL patterns (invalid in standard SQL)
        # We can't detect this from extracted objects alone easily,
        # so we flag if ISNULL is present (common MSSQL pattern)
        has_isnull = any(
            f.name.upper() == "ISNULL" for f in original_objects.functions
        )
        if has_isnull:
            return True

    return False


def _assess_aggregation_stability(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> str:
    """Assess whether aggregation functions (SUM, AVG, COUNT) produce
    stable results across databases."""
    agg_funcs = {"SUM", "AVG", "COUNT", "MIN", "MAX", "STRING_AGG", "ARRAY_AGG"}

    orig_agg = [f for f in original_objects.functions if f.name.upper() in agg_funcs]
    rewritten_agg = [f for f in rewritten_objects.functions if f.name.upper() in agg_funcs]

    if not orig_agg:
        return "HIGH"  # No aggregations = no aggregation risk

    # Check if all original aggregations have rewritten counterparts
    orig_agg_names = {f.name.upper() for f in orig_agg}
    rewritten_agg_names = {f.name.upper() for f in rewritten_agg}

    missing = orig_agg_names - rewritten_agg_names
    if missing:
        # Some aggregations may have been inlined or transformed
        # This is acceptable if common aggregates
        standard_missing = missing - {"STRING_AGG", "ARRAY_AGG"}
        if standard_missing:
            return "LOW"
        return "MEDIUM"

    # Check for STRING_AGG (different ordering semantics across DBs)
    has_string_agg = any(
        f.name.upper() == "STRING_AGG" for f in orig_agg
    )
    if has_string_agg:
        return "MEDIUM"  # STRING_AGG ordering varies

    # Different DBs handle NULL in aggregates differently for some functions
    if source_db != target_db:
        # SUM/AVG of empty set: MSSQL returns NULL, PG returns NULL — compatible
        # COUNT of NULLs: all consistent
        return "HIGH"

    return "HIGH"


def _assess_ordering_stability(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
) -> str:
    """Assess whether ORDER BY results are stable across databases.

    Key differences:
        - NULLS FIRST vs NULLS LAST default
        - Collation differences
        - String comparison differences
    """
    # Without actually parsing ORDER BY clauses from extracted objects,
    # we use heuristics based on functions present

    # Functions that produce ordered results
    ordering_funcs = {"ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD"}

    has_ordering = any(
        f.name.upper() in ordering_funcs for f in original_objects.functions
    )

    if has_ordering:
        # Window functions can produce different results with different NULL ordering
        return "MEDIUM"

    # String functions that are collation-sensitive
    string_funcs = {"UPPER", "LOWER", "SUBSTRING", "REPLACE", "CONCAT"}
    has_string = any(
        f.name.upper() in string_funcs for f in original_objects.functions
    )

    if has_string:
        return "HIGH"  # Collation may differ but typically consistent for basic ops
    return "HIGH"


def _detect_type_coercion_changes(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[str]:
    """Detect potential type coercion changes between source and target."""
    changes: list[str] = []

    # BOOLEAN type handling differs: MSSQL has no native BOOLEAN (uses BIT),
    # PG has native BOOLEAN, DM8 has BIT
    if source_db == "mssql" and target_db == "kingbasees":
        changes.append("BIT → BOOLEAN: MSSQL 的 BIT 类型在 KingbaseES 中映射为 BOOLEAN")
    elif source_db == "mssql" and target_db == "dm8":
        changes.append("BIT → BIT: DM8 支持 BIT 类型，兼容较好")

    # DATETIME precision: MSSQL DATETIME has 3.33ms precision, PG has microsecond
    date_funcs = {"GETDATE", "GETUTCDATE", "NOW", "CURRENT_TIMESTAMP", "SYSDATE"}
    has_date_func = any(
        f.name.upper() in date_funcs for f in original_objects.functions
    )
    if has_date_func and source_db != target_db:
        changes.append(
            f"时间精度变化: {source_db.upper()} 和 {target_db.upper()} 的"
            f" DATETIME/TIMESTAMP 精度不同"
        )

    return changes
