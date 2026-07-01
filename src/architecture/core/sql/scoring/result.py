"""
Result Consistency Score (weight: 25%).

Evaluates whether results are consistent across databases.
Based on the DiffResult from compare_service.compute_diff().

Three dimensions:
    1. Row count consistency — all DBs return same row count
    2. Column consistency — all DBs return same column names
    3. Value consistency — individual cell values match

Scoring rules:
    - Starts at 100
    - Row count diff: -30
    - Column diff: -30
    - Value diff: -0.5 per item, max -40
    - Cap at 0
"""

from __future__ import annotations

from typing import Any

from app.api.sql_demo.compare_schemas import DiffResult

from ..score_schemas import Finding


# Maximum value diffs to report in findings
_MAX_VALUE_FINDINGS = 10


def result_score(
    diff: DiffResult,
    results: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, list[Finding]]:
    """Calculate result consistency score.

    Args:
        diff: DiffResult from compute_diff().
        results: Optional execution results to check if comparison is meaningful.

    Returns:
        (score 0-100, list of findings)
    """
    findings: list[Finding] = []

    # Guard: if fewer than 2 DBs have results, consistency comparison is meaningless
    if results is not None:
        successful_dbs = sum(1 for r in results.values() if r.get("success"))
        if successful_dbs < 2:
            return 0.0, [
                Finding(
                    type="result",
                    db="all",
                    issue="无法比较结果一致性: 成功执行的数据库不足 2 个",
                    severity="high",
                    detail=f"仅 {successful_dbs} 个数据库成功执行，无法进行一致性对比",
                )
            ]

    score = 100.0

    # -- Row count diff --
    if diff.row_count_diff:
        score -= 30
        details = _format_row_count_details(diff.row_count_details)
        for db_type, count in diff.row_count_details.items():
            findings.append(
                Finding(
                    type="result",
                    db=db_type,
                    issue=f"行数不一致: {details}",
                    severity="high",
                    detail=f"{db_type} 返回 {count} 行",
                )
            )

    # -- Column diff --
    if diff.column_diff:
        score -= 30
        for col_detail in diff.column_details:
            if col_detail.missing_from_others:
                findings.append(
                    Finding(
                        type="result",
                        db=col_detail.db_type,
                        issue=(
                            f"列名差异: {col_detail.db_type} "
                            f"缺失列 [{', '.join(col_detail.missing_from_others)}]"
                        ),
                        severity="high",
                        detail=(
                            f"{col_detail.db_type} 列: [{', '.join(col_detail.columns)}]"
                        ),
                    )
                )

    # -- Value diff --
    value_diff_count = len(diff.value_diff)
    if value_diff_count > 0:
        value_penalty = min(value_diff_count * 0.5, 40.0)
        score -= value_penalty

        # Report up to _MAX_VALUE_FINDINGS items
        for item in diff.value_diff[:_MAX_VALUE_FINDINGS]:
            values_str = ", ".join(
                f"{db}={repr(val)[:50]}" for db, val in item.values.items()
            )
            findings.append(
                Finding(
                    type="result",
                    db="all",
                    issue=(
                        f"值差异: 第 {item.row_index} 行, "
                        f"列 [{item.column}]: {values_str}"
                    ),
                    severity="medium",
                    detail="不同数据库返回了不同的值",
                )
            )

        if value_diff_count > _MAX_VALUE_FINDINGS:
            findings.append(
                Finding(
                    type="result",
                    db="all",
                    issue=(
                        f"还有 {value_diff_count - _MAX_VALUE_FINDINGS} "
                        "处值差异未显示"
                    ),
                    severity="low",
                    detail="查看完整 Diff 面板获取详细差异",
                )
            )

    return round(max(score, 0.0), 1), findings


def _format_row_count_details(details: dict[str, int]) -> str:
    """Format row count details as human-readable string."""
    parts = [f"{db}={count}" for db, count in sorted(details.items())]
    return ", ".join(parts)
