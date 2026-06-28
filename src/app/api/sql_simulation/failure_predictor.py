"""
Failure Predictor — rule-based prediction of execution failures.

Predicts specific failure modes that may occur when executing rewritten SQL
on the target database. Each rule inspects a different risk dimension.

Failure categories:
    1. NULL_COMPARISON      — NULL handling differences (ANSI_NULLS vs standard)
    2. PAGINATION_SHIFT     — TOP→LIMIT pagination consistency
    3. TIMEZONE_DRIFT       — GETDATE()→NOW() timezone behaviour
    4. JOIN_MULTIPLICITY    — JOIN cardinality changes
    5. FUNCTION_SEMANTIC    — Function semantics change (e.g. ISNULL→COALESCE)
    6. TYPE_CAST_ISSUE      — Implicit type casting differences
    7. COLLATION_MISMATCH   — String comparison collation differences
    8. AGGREGATION_INSTABILITY — Aggregation result differences
"""

from __future__ import annotations

from app.api.sql_diagnostics.extractor import (
    ExtractedObjects,
    FunctionRef,
    JoinRef,
)

from .schemas import (
    FailurePoint,
    FailureType,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def predict_failures(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Run all failure prediction rules against the migrated SQL.

    Args:
        original_objects: Extracted objects from original SQL.
        rewritten_objects: Extracted objects from rewritten SQL.
        source_db: Source database type.
        target_db: Target database type.

    Returns:
        List of predicted FailurePoints (empty if no failures predicted).
    """
    if source_db == target_db:
        return []

    failures: list[FailurePoint] = []

    # Run each prediction rule
    failures.extend(_predict_null_comparison(original_objects, source_db, target_db))
    failures.extend(_predict_pagination_shift(original_objects, rewritten_objects, source_db, target_db))
    failures.extend(_predict_timezone_drift(original_objects, rewritten_objects, source_db, target_db))
    failures.extend(_predict_join_multiplicity(original_objects, rewritten_objects, source_db, target_db))
    failures.extend(_predict_function_semantic(original_objects, rewritten_objects, source_db, target_db))
    failures.extend(_predict_type_cast(original_objects, rewritten_objects, source_db, target_db))
    failures.extend(_predict_aggregation_instability(original_objects, rewritten_objects, source_db, target_db))

    return failures


# ---------------------------------------------------------------------------
# Rule 1: NULL comparison
# ---------------------------------------------------------------------------


def _predict_null_comparison(
    original_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from NULL handling differences.

    MSSQL: ANSI_NULLS setting controls = NULL behaviour.
    PG/DM8: Standard SQL — = NULL is always UNKNOWN.
    """
    failures: list[FailurePoint] = []

    if source_db != "mssql":
        return failures

    # ISNULL is the most common MSSQL-specific NULL handling function
    isnull_funcs = [f for f in original_objects.functions if f.name.upper() == "ISNULL"]

    # Find tables/columns that ISNULL operates on
    for func in isnull_funcs:
        if func.args:
            first_arg = func.args[0].strip()

            # Determine severity based on target
            if target_db == "kingbasees":
                severity = RiskLevel.LOW  # COALESCE is a safe replacement
                mitigation = "ISNULL → COALESCE 在 KingbaseES 中是安全的替换"
            elif target_db == "dm8":
                severity = RiskLevel.LOW  # NVL is similar
                mitigation = "ISNULL → NVL 在 DM8 中是安全替换"
            else:
                severity = RiskLevel.MEDIUM
                mitigation = "建议在目标数据库测试 NULL 比较行为"

            failures.append(FailurePoint(
                type=FailureType.NULL_COMPARISON,
                location=first_arg if "." in first_arg else f"<expression>.{first_arg}",
                severity=severity,
                description=(
                    f"ISNULL({func.raw}) 在不同数据库中 NULL 处理语义不同。"
                    f"源库 MSSQL 的 ISNULL 返回第一个非 NULL 参数的类型，"
                    f"而替换函数可能有不同的类型推断规则。"
                ),
                mitigation=mitigation,
            ))

    return failures


# ---------------------------------------------------------------------------
# Rule 2: Pagination shift
# ---------------------------------------------------------------------------


def _predict_pagination_shift(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from TOP → LIMIT pagination differences.

    MSSQL TOP N with no ORDER BY → non-deterministic.
    PG LIMIT N with no ORDER BY → also non-deterministic, but may differ.
    Additionally, TOP N PERCENT has no direct LIMIT equivalent.
    """
    failures: list[FailurePoint] = []

    orig_func_names = {f.name.upper() for f in original_objects.functions}
    rewritten_func_names = {f.name.upper() for f in rewritten_objects.functions}

    # TOP was rewritten to LIMIT
    if "TOP" in orig_func_names and "TOP" not in rewritten_func_names:
        has_order_by = _has_ordering(original_objects)

        if not has_order_by:
            failures.append(FailurePoint(
                type=FailureType.PAGINATION_SHIFT,
                location="SELECT TOP → LIMIT",
                severity=RiskLevel.MEDIUM,
                description=(
                    "TOP 无 ORDER BY 转换为 LIMIT 无 ORDER BY。"
                    "两种数据库的默认行顺序可能不同，导致分页结果不一致。"
                ),
                mitigation="添加 ORDER BY 子句确保分页结果的可重复性",
            ))

    return failures


def _has_ordering(objects: ExtractedObjects) -> bool:
    """Check if the SQL likely has an ORDER BY clause."""
    # We check for window functions that imply ordering (ROW_NUMBER, RANK)
    ordering_funcs = {"ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD"}
    return any(f.name.upper() in ordering_funcs for f in objects.functions)


# ---------------------------------------------------------------------------
# Rule 3: Timezone drift
# ---------------------------------------------------------------------------


def _predict_timezone_drift(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from date/time function timezone differences.

    GETDATE() returns server local time in MSSQL.
    NOW() returns transaction start time in PG (session timezone).
    SYSDATE returns server date/time in DM8.
    """
    failures: list[FailurePoint] = []

    orig_func_names = {f.name.upper() for f in original_objects.functions}

    date_funcs_present = orig_func_names & {"GETDATE", "GETUTCDATE", "NOW", "SYSDATE", "CURRENT_TIMESTAMP"}

    for func in original_objects.functions:
        if func.name.upper() not in date_funcs_present:
            continue

        if func.name.upper() == "GETDATE" and target_db in ("kingbasees", "dm8"):
            severity = RiskLevel.LOW
            desc = (
                f"GETDATE() → {'NOW()' if target_db == 'kingbasees' else 'SYSDATE'}："
                f"源库 MSSQL GETDATE() 返回服务器本地时间，"
                f"目标库返回{'事务开始时间' if target_db == 'kingbasees' else '数据库服务器时间'}。"
                f"在跨时区部署时可能产生偏差。"
            )
            mitigation = (
                "如果应用依赖特定时区，建议使用 "
                + ("CURRENT_TIMESTAMP AT TIME ZONE" if target_db == "kingbasees" else "SYSTIMESTAMP")
                + " 并明确指定时区"
            )

            failures.append(FailurePoint(
                type=FailureType.TIMEZONE_DRIFT,
                location=func.raw,
                severity=severity,
                description=desc,
                mitigation=mitigation,
            ))

        elif func.name.upper() == "GETUTCDATE" and target_db in ("kingbasees", "dm8"):
            failures.append(FailurePoint(
                type=FailureType.TIMEZONE_DRIFT,
                location=func.raw,
                severity=RiskLevel.LOW,
                description=(
                    f"GETUTCDATE() 在目标数据库中映射为 "
                    f"{'CURRENT_TIMESTAMP' if target_db == 'kingbasees' else 'SYSTIMESTAMP'}，"
                    f"需要验证 UTC 语义是否保留。"
                ),
                mitigation="在目标库中使用 AT TIME ZONE 'UTC' 明确 UTC 语义",
            ))

    return failures


# ---------------------------------------------------------------------------
# Rule 4: JOIN multiplicity change
# ---------------------------------------------------------------------------


def _predict_join_multiplicity(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from JOIN behaviour differences.

    Different databases optimise JOINs differently, which can cause:
        - Different row ordering in result sets
        - Different NULL handling in OUTER JOINs
        - Different duplicate row handling
    """
    failures: list[FailurePoint] = []

    for join in original_objects.joins:
        join_type = join.join_type.upper()

        # FULL JOIN — known to have different optimization across databases
        if join_type == "FULL":
            failures.append(FailurePoint(
                type=FailureType.JOIN_MULTIPLICITY_CHANGE,
                location=f"JOIN {join.table}",
                severity=RiskLevel.MEDIUM,
                description=(
                    f"FULL JOIN on {join.table}: 不同数据库的 FULL JOIN "
                    f"优化策略不同，可能导致结果集行数差异。"
                ),
                mitigation="验证 FULL JOIN 在目标数据库的结果集行数与源库一致",
            ))

        # CROSS JOIN — may be optimized differently
        elif join_type == "CROSS":
            failures.append(FailurePoint(
                type=FailureType.JOIN_MULTIPLICITY_CHANGE,
                location=f"JOIN {join.table}",
                severity=RiskLevel.LOW,
                description=(
                    f"CROSS JOIN on {join.table}: 虽然没有 ON 条件差异，"
                    f"但不同数据库的优化器可能产生不同的行顺序。"
                ),
                mitigation="如有 ORDER BY，通常可保持一致性",
            ))

        # LEFT JOIN with condition on right table → could behave differently
        elif join_type == "LEFT" and join.condition:
            failures.append(FailurePoint(
                type=FailureType.JOIN_MULTIPLICITY_CHANGE,
                location=f"JOIN {join.table}",
                severity=RiskLevel.LOW,
                description=(
                    f"LEFT JOIN on {join.table}: NULL 行处理在不同数据库中"
                    f"可能产生细微差异，尤其在 WHERE 子句引用右表列时。"
                ),
                mitigation="确认 WHERE 条件中没有对 LEFT JOIN 右表列的过滤（会导致 LEFT JOIN 退化为 INNER JOIN）",
            ))

    return failures


# ---------------------------------------------------------------------------
# Rule 5: Function semantic change
# ---------------------------------------------------------------------------


def _predict_function_semantic(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from function semantic differences.

    Some function mappings are NOT perfectly semantically equivalent:
        - ISNULL(a, b) vs COALESCE(a, b): COALESCE evaluates all args, ISNULL is short-circuit
        - LEN(s) vs LENGTH(s): LEN ignores trailing spaces in MSSQL, LENGTH does not
        - CHARINDEX vs POSITION: argument order is reversed
    """
    failures: list[FailurePoint] = []

    orig_func_names = {f.name.upper() for f in original_objects.functions}

    # ISNULL → COALESCE: evaluation semantics differ
    if "ISNULL" in orig_func_names and target_db == "kingbasees":
        isnull_funcs = [f for f in original_objects.functions if f.name.upper() == "ISNULL"]
        for func in isnull_funcs:
            failures.append(FailurePoint(
                type=FailureType.FUNCTION_SEMANTIC_CHANGE,
                location=func.raw,
                severity=RiskLevel.LOW,
                description=(
                    f"ISNULL → COALESCE: ISNULL 使用第一个参数的类型确定返回类型，"
                    f"COALESCE 返回所有参数中优先级最高的类型。"
                    f"ISNULL 只接受 2 个参数而 COALESCE 可接受多个。"
                ),
                mitigation="如果依赖 ISNULL 的返回类型，需要在 COALESCE 中显式 CAST",
            ))

    # LEN → LENGTH: trailing space handling differs
    if "LEN" in orig_func_names:
        len_funcs = [f for f in original_objects.functions if f.name.upper() == "LEN"]
        for func in len_funcs:
            failures.append(FailurePoint(
                type=FailureType.FUNCTION_SEMANTIC_CHANGE,
                location=func.raw,
                severity=RiskLevel.LOW,
                description=(
                    f"LEN → LENGTH: MSSQL LEN() 忽略尾部空格，"
                    f"{'LENGTH()' if target_db == 'kingbasees' else 'LENGTH()'} 计算所有字符（包括尾部空格）。"
                ),
                mitigation="如果依赖 LEN 的尾部空格行为，使用 RTRIM 后再计算长度",
            ))

    return failures


# ---------------------------------------------------------------------------
# Rule 6: Type cast issues
# ---------------------------------------------------------------------------


def _predict_type_cast(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from implicit type casting differences.

    MSSQL, KingbaseES, and DM8 have different implicit type conversion rules.
    """
    failures: list[FailurePoint] = []

    # Check for CAST/CONVERT usage
    cast_funcs = {"CAST", "CONVERT"}
    orig_cast = [f for f in original_objects.functions if f.name.upper() in cast_funcs]

    if orig_cast and source_db != target_db:
        for func in orig_cast:
            failures.append(FailurePoint(
                type=FailureType.TYPE_CAST_ISSUE,
                location=func.raw,
                severity=RiskLevel.LOW,
                description=(
                    f"CAST/CONVERT: {source_db.upper()} 和 {target_db.upper()} "
                    f"的类型转换规则存在差异，尤其对于 DATETIME ↔ STRING 转换。"
                ),
                mitigation="验证目标数据库支持源 SQL 中使用的所有类型转换",
            ))

    return failures


# ---------------------------------------------------------------------------
# Rule 7: Aggregation instability
# ---------------------------------------------------------------------------


def _predict_aggregation_instability(
    original_objects: ExtractedObjects,
    rewritten_objects: ExtractedObjects,
    source_db: str,
    target_db: str,
) -> list[FailurePoint]:
    """Predict failures from aggregation function differences.

    Different databases handle:
        - SUM/AVG of empty set differently
        - STRING_AGG ordering (MSSQL WITHIN GROUP vs PG ORDER BY)
        - NULL handling in aggregate functions
    """
    failures: list[FailurePoint] = []

    agg_funcs = {"STRING_AGG", "ARRAY_AGG", "LISTAGG", "GROUP_CONCAT"}
    orig_agg = [f for f in original_objects.functions if f.name.upper() in agg_funcs]

    for func in orig_agg:
        if func.name.upper() == "STRING_AGG":
            failures.append(FailurePoint(
                type=FailureType.AGGREGATION_INSTABILITY,
                location=func.raw,
                severity=RiskLevel.MEDIUM,
                description=(
                    f"STRING_AGG: MSSQL 的 STRING_AGG 使用 WITHIN GROUP (ORDER BY ...) "
                    f"进行排序，而 PostgreSQL 使用 ORDER BY 在聚合函数内部。"
                    f"迁移后排序可能不一致。"
                ),
                mitigation="确认 STRING_AGG 的 ORDER BY 子句已正确转换",
            ))
        else:
            failures.append(FailurePoint(
                type=FailureType.AGGREGATION_INSTABILITY,
                location=func.raw,
                severity=RiskLevel.LOW,
                description=(
                    f"{func.name.upper()}: 聚合函数 {func.name} 在目标数据库中"
                    f"可能需要不同的语法或不存在直接等价函数。"
                ),
                mitigation=f"验证 {func.name} 在目标数据库中的等价函数",
            ))

    return failures
