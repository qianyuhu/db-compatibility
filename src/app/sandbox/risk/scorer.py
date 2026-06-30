"""
Risk Scorer — multi-dimensional risk scoring engine.

Evaluates migration risk across 5 dimensions:
    1. SQL Risk (25%) — dialect features, complexity, rewrite requirements
    2. Schema Risk (25%) — type mismatches, nullability, defaults, identity
    3. Data Risk (20%) — precision loss, datetime truncation, NULL divergence
    4. API Risk (15%) — response shape, missing fields, ordering
    5. Behavioral Risk (15%) — ORM divergence, service-layer consistency

Each dimension scored 0-100 (higher = more risk), then weighted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..diff_engine import DeterministicDiff, FieldDiff
from ..reporter import TestCaseResult
from ..test_case import MigrationTestCase, get_all_test_cases
from .schemas import DimensionRisk, RiskScore, classify_risk_level


# =========================================================================
# Risk Dimension Weights
# =========================================================================

DIMENSION_WEIGHTS = {
    "sql": 0.25,
    "schema": 0.25,
    "data": 0.20,
    "api": 0.15,
    "behavioral": 0.15,
}

# =========================================================================
# SQL Risk — features complexity and dialect gaps
# =========================================================================

# SQL patterns that indicate migration risk
SQL_RISK_PATTERNS: dict[str, int] = {
    # High risk: features that differ significantly across dialects
    "LIMIT_TOP": 25,       # TOP in MSSQL vs LIMIT in others
    "MERGE_UPSERT": 35,    # MERGE syntax differs
    "WINDOW_FUNCTION": 20,  # Window functions vary
    "DATE_FUNCTIONS": 25,   # GETDATE() vs NOW() vs SYSDATE
    "SUBQUERY": 10,         # Subquery optimization differs
    "CTE": 15,              # WITH clause recursion
    "UNION": 10,            # UNION/UNION ALL
    "AGGREGATION": 10,      # GROUP BY behavior
    "JOIN": 15,             # JOIN syntax variations
    "PAGINATION": 20,       # OFFSET/FETCH vs LIMIT
    "ORDER_BY": 5,          # NULLS FIRST/LAST
    "GROUP_BY": 10,         # GROUP BY restrictions
    "BOOLEAN": 20,          # Boolean literal differences
    "NULL_HANDLING": 20,    # NULL comparison behavior
    "STRING_FUNCTION": 15,  # LEN vs LENGTH, SUBSTRING
}

# Tag to SQL risk mapping
TAG_TO_SQL_RISK: dict[str, int] = {
    "pagination": 20,
    "group-by": 10,
    "aggregation": 10,
    "join": 15,
    "left-join": 15,
    "multi-table": 25,
    "boolean": 20,
    "null-handling": 20,
    "datetime": 25,
    "numeric-precision": 15,
    "collation": 15,
    "edge": 15,
    "crud": 5,
}


def _score_sql_dimension(test_cases: list[MigrationTestCase], results: list[TestCaseResult]) -> DimensionRisk:
    """Score SQL migration risk based on test case features and results."""
    deductions: list[str] = []
    total_risk = 0.0
    max_possible = 0.0

    for tc in test_cases:
        result = next((r for r in results if r.test_id == tc.id), None)
        tc_risk = 0

        # Risk from tags
        for tag in tc.tags:
            tag_risk = TAG_TO_SQL_RISK.get(tag, 0)
            tc_risk += tag_risk

        # Risk from known issues (pre-existing dialect gaps)
        if tc.known_issues:
            tc_risk += 10 * len(tc.known_issues)

        # Risk from target_sql (explicit rewrite needed)
        if tc.target_sql and tc.target_sql != tc.source_sql:
            tc_risk += 15
            deductions.append(f"[{tc.id}] 需要显式 SQL 重写")

        # Risk from actual failure
        if result and result.status == "FAIL":
            tc_risk *= 1.5  # Amplify risk of actual failures
            if result.diff_detail:
                categories = set(d.get("category", "") for d in result.diff_detail)
                if "precision" in categories:
                    deductions.append(f"[{tc.id}] 数值精度差异")
                if "type_mapping" in categories:
                    deductions.append(f"[{tc.id}] 数据类型映射差异")

        max_possible += max(tc_risk, 10)  # Floor at 10 per test
        total_risk += tc_risk

    raw_score = min(100, round((total_risk / max(max_possible, 1)) * 100, 1))
    weighted = round(raw_score * DIMENSION_WEIGHTS["sql"], 1)

    return DimensionRisk(
        name="SQL Risk",
        raw_score=raw_score,
        weight=DIMENSION_WEIGHTS["sql"],
        weighted_score=weighted,
        deductions=deductions[:8],
        risk_level=classify_risk_level(raw_score),
    )


# =========================================================================
# Schema Risk — type mismatches, nullability, defaults, identity
# =========================================================================

SCHEMA_RISK_TAGS: dict[str, int] = {
    "schema": 15,
    "edge": 10,
    "datetime": 25,
    "boolean": 20,
    "null-handling": 25,
    "numeric-precision": 20,
    "collation": 15,
}


def _score_schema_dimension(test_cases: list[MigrationTestCase], results: list[TestCaseResult]) -> DimensionRisk:
    """Score schema migration risk."""
    deductions: list[str] = []
    total_risk = 0.0
    max_possible = 0.0

    for tc in test_cases:
        result = next((r for r in results if r.test_id == tc.id), None)
        tc_risk = 0

        for tag in tc.tags:
            tc_risk += SCHEMA_RISK_TAGS.get(tag, 0)

        # Column mismatch is a strong schema risk signal
        if result and result.column_match is False:
            tc_risk += 30
            deductions.append(f"[{tc.id}] 列结构不匹配")

        # Row count mismatch often indicates schema-level issues
        if result and result.row_count_match is False:
            tc_risk += 20
            deductions.append(f"[{tc.id}] 行数不匹配（可能是默认值/NULL 处理差异）")

        # Known issues often relate to schema
        if tc.known_issues:
            tc_risk += 5 * len(tc.known_issues)

        max_possible += max(tc_risk, 5)
        total_risk += tc_risk

    raw_score = min(100, round((total_risk / max(max_possible, 1)) * 100, 1))
    weighted = round(raw_score * DIMENSION_WEIGHTS["schema"], 1)

    return DimensionRisk(
        name="Schema Risk",
        raw_score=raw_score,
        weight=DIMENSION_WEIGHTS["schema"],
        weighted_score=weighted,
        deductions=deductions[:8],
        risk_level=classify_risk_level(raw_score),
    )


# =========================================================================
# Data Risk — precision loss, datetime truncation, NULL divergence
# =========================================================================

def _score_data_dimension(test_cases: list[MigrationTestCase], results: list[TestCaseResult]) -> DimensionRisk:
    """Score data-level migration risk based on diff patterns."""
    deductions: list[str] = []
    total_risk = 0.0
    max_possible = 0.0

    for tc in test_cases:
        result = next((r for r in results if r.test_id == tc.id), None)
        tc_risk = 0

        if result and result.status == "FAIL" and result.diff_detail:
            categories = set(d.get("category", "") for d in result.diff_detail)

            if "precision" in categories:
                tc_risk += 25
                deductions.append(f"[{tc.id}] 数值精度损失")
            if "type_mapping" in categories:
                tc_risk += 20
                deductions.append(f"[{tc.id}] 类型映射导致数据差异")
            if "nullability" in categories:
                tc_risk += 25
                deductions.append(f"[{tc.id}] NULL 值处理差异")
            if "boolean" in categories:
                tc_risk += 15
                deductions.append(f"[{tc.id}] 布尔值表示差异")
            if "collation" in categories:
                tc_risk += 15
                deductions.append(f"[{tc.id}] 字符集/排序规则差异")

        # Any diff_detail means data-level issues exist
        if result and result.diff_detail:
            tc_risk += 5 * len(result.diff_detail)

        # Known issues about data
        if tc.known_issues:
            tc_risk += 5 * len(tc.known_issues)

        max_possible += max(tc_risk, 5)
        total_risk += tc_risk

    raw_score = min(100, round((total_risk / max(max_possible, 1)) * 100, 1))
    weighted = round(raw_score * DIMENSION_WEIGHTS["data"], 1)

    return DimensionRisk(
        name="Data Risk",
        raw_score=raw_score,
        weight=DIMENSION_WEIGHTS["data"],
        weighted_score=weighted,
        deductions=deductions[:8],
        risk_level=classify_risk_level(raw_score),
    )


# =========================================================================
# API Risk — response shape, missing fields, ordering
# =========================================================================

def _score_api_dimension(test_cases: list[MigrationTestCase], results: list[TestCaseResult]) -> DimensionRisk:
    """Score API-level migration risk."""
    deductions: list[str] = []
    total_risk = 0.0
    max_possible = 0.0

    api_tests = [tc for tc in test_cases if tc.api_endpoint]
    for tc in api_tests:
        result = next((r for r in results if r.test_id == tc.id), None)
        tc_risk = 0

        # API test that failed is serious
        if result and result.status != "PASS":
            tc_risk += 30
            deductions.append(f"[{tc.id}] API 端点行为不一致")

        max_possible += max(tc_risk, 10)
        total_risk += tc_risk

    # If no API tests at all, that's a coverage risk
    if not api_tests:
        total_risk = 50  # Unknown API behavior
        max_possible = 100
        deductions.append("未发现 API 级别测试用例")

    raw_score = min(100, round((total_risk / max(max_possible, 1)) * 100, 1))
    weighted = round(raw_score * DIMENSION_WEIGHTS["api"], 1)

    return DimensionRisk(
        name="API Risk",
        raw_score=raw_score,
        weight=DIMENSION_WEIGHTS["api"],
        weighted_score=weighted,
        deductions=deductions[:8],
        risk_level=classify_risk_level(raw_score),
    )


# =========================================================================
# Behavioral Risk — ORM divergence, service-layer consistency
# =========================================================================

def _score_behavioral_dimension(test_cases: list[MigrationTestCase], results: list[TestCaseResult]) -> DimensionRisk:
    """Score behavioral migration risk (ORM + service layer)."""
    deductions: list[str] = []
    total_risk = 0.0
    max_possible = 0.0

    for tc in test_cases:
        result = next((r for r in results if r.test_id == tc.id), None)
        tc_risk = 0

        # Multi-table joins have higher behavioral risk
        if "multi-table" in tc.tags:
            tc_risk += 20
        if "join" in tc.tags:
            tc_risk += 10

        # Aggregate queries can behave differently
        if "aggregation" in tc.tags:
            tc_risk += 10

        # Pagination behavior differs
        if "pagination" in tc.tags:
            tc_risk += 20

        # Failed tests indicate behavioral divergence
        if result and result.status == "FAIL":
            tc_risk += 20
            deductions.append(f"[{tc.id}] 跨库行为不一致")

        # Known issues are behavioral
        if tc.known_issues:
            tc_risk += 10 * len(tc.known_issues)

        max_possible += max(tc_risk, 5)
        total_risk += tc_risk

    raw_score = min(100, round((total_risk / max(max_possible, 1)) * 100, 1))
    weighted = round(raw_score * DIMENSION_WEIGHTS["behavioral"], 1)

    return DimensionRisk(
        name="Behavioral Risk",
        raw_score=raw_score,
        weight=DIMENSION_WEIGHTS["behavioral"],
        weighted_score=weighted,
        deductions=deductions[:8],
        risk_level=classify_risk_level(raw_score),
    )


# =========================================================================
# Risk Scorer
# =========================================================================


class RiskScorer:
    """Multi-dimensional migration risk scorer.

    Computes risk scores from test case definitions and execution results.
    """

    @staticmethod
    def score(
        test_cases: list[MigrationTestCase],
        results: list[TestCaseResult],
    ) -> RiskScore:
        """Compute the full multi-dimensional risk score.

        Args:
            test_cases: Test case definitions
            results: Execution results (must align with test_cases)

        Returns:
            RiskScore with all 5 dimensions and total.
        """
        dims = [
            _score_sql_dimension(test_cases, results),
            _score_schema_dimension(test_cases, results),
            _score_data_dimension(test_cases, results),
            _score_api_dimension(test_cases, results),
            _score_behavioral_dimension(test_cases, results),
        ]

        total = round(sum(d.weighted_score for d in dims), 1)
        level = classify_risk_level(total)

        # Collect risk tags
        risk_tags: list[str] = []
        if any(d.risk_level in ("HIGH", "BLOCKER") for d in dims):
            risk_tags.append("high_risk_dimension")
        if total >= 60:
            risk_tags.append("requires_attention")
        if total >= 80:
            risk_tags.append("production_blocker")

        # Build summary
        top_dims = sorted(dims, key=lambda d: d.raw_score, reverse=True)
        summary_parts = [f"最高风险维度: {top_dims[0].name} ({top_dims[0].raw_score:.0f}/100)"]
        if top_dims[0].deductions:
            summary_parts.append(f"主要问题: {top_dims[0].deductions[0]}")

        return RiskScore(
            total_score=total,
            dimensions=dims,
            risk_level=level,
            risk_tags=risk_tags,
            summary="; ".join(summary_parts),
        )
