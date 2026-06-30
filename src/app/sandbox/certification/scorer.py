"""
Risk Scorer v2 — risk from actual failures ONLY.

Critical design principle:
  RISK = ACTUAL FAILURES + INCOMPATIBILITIES + RUNTIME ERRORS
  RISK ≠ coverage gaps (those are uncertainty, not risk)

Coverage gaps NEVER contribute to risk score. They are reported
separately as uncertainty_areas in the coverage report.

NOTE: This RiskScorer (in certification/) is distinct from the old
RiskScorer in sandbox/risk/scorer.py. The old scorer used 5-dimensional
risk with coverage-based penalties. This one uses failure-only scoring.
Import as: from app.sandbox.certification.scorer import RiskScorer
"""

from __future__ import annotations

from ..reporter import TestCaseResult
from .schemas import FailureDetail


class RiskScorer:
    """Score migration risk from actual test failures only.

    Coverage gaps are NOT risk. Zero coverage with zero failures = zero risk.
    """

    # Severity → numeric score
    SEVERITY_SCORES = {
        "LOW": 20,
        "MEDIUM": 50,
        "HIGH": 80,
        "BLOCKER": 100,
    }

    @staticmethod
    def score(
        test_results: list[TestCaseResult],
    ) -> tuple[float, list[FailureDetail]]:
        """Score risk from actual failures only.

        Args:
            test_results: Individual test case execution results

        Returns:
            (risk_score: 0-100, failure_details: list[FailureDetail])

        Risk scoring:
          - ERROR status → HIGH severity, score 80 per test
          - FAIL status → classified by diff type:
            * column mismatch → BLOCKER (100)
            * row count mismatch → HIGH (80)
            * precision/type mapping → MEDIUM (50)
            * other data mismatch → LOW (20)
          - PASS + known issues → tracked as LOW (20)
          - Risk = sum(scores) / total_tests, clamped to 100
        """
        total = len(test_results)
        if total == 0:
            return 0.0, []

        details: list[FailureDetail] = []
        risk_sum = 0.0

        for r in test_results:
            if r.status == "ERROR":
                severity = "HIGH"
                score = 80.0
                risk_sum += score
                details.append(FailureDetail(
                    test_id=r.test_id,
                    test_name=r.test_name,
                    category=r.category,
                    severity=severity,
                    description=r.error_message or "Runtime execution error",
                    root_cause="数据库连接或SQL执行错误",
                    possible_fixes=[
                        "检查数据库连接状态",
                        "确认SQL语法兼容性",
                        "查看数据库错误日志",
                    ],
                    is_runtime_error=True,
                ))

            elif r.status == "FAIL":
                severity = RiskScorer._classify_failure_severity(r)
                score = RiskScorer.SEVERITY_SCORES.get(severity, 50)
                risk_sum += score

                detail = FailureDetail(
                    test_id=r.test_id,
                    test_name=r.test_name,
                    category=r.category,
                    severity=severity,
                    description=r.diff_summary or "结果不匹配",
                )

                # Categorize the failure
                if r.column_match is False:
                    detail = FailureDetail(
                        test_id=r.test_id,
                        test_name=r.test_name,
                        category=r.category,
                        severity=severity,
                        description=r.diff_summary or "列结构不匹配",
                        root_cause="源库和目标库列结构不一致",
                        possible_fixes=[
                            "检查列名大小写映射",
                            "确认SELECT中的列别名",
                            "检查INFORMATION_SCHEMA方言差异",
                        ],
                        is_schema_mismatch=True,
                    )
                elif r.row_count_match is False:
                    detail = FailureDetail(
                        test_id=r.test_id,
                        test_name=r.test_name,
                        category=r.category,
                        severity=severity,
                        description=r.diff_summary or "行数不匹配",
                        root_cause="源库和目标库返回行数不一致",
                        possible_fixes=[
                            "检查WHERE子句的NULL处理逻辑",
                            "确认JOIN行为差异",
                            "检查默认字符集对字符串比较的影响",
                        ],
                        is_sql_incompatibility=True,
                    )
                elif r.known_issues:
                    detail = FailureDetail(
                        test_id=r.test_id,
                        test_name=r.test_name,
                        category=r.category,
                        severity=severity,
                        description=r.diff_summary or "已知差异导致失败",
                        root_cause="; ".join(r.known_issues),
                        possible_fixes=[],
                        is_sql_incompatibility=True,
                    )
                elif r.diff_detail:
                    categories = set(d.get("category", "") for d in r.diff_detail)
                    if "precision" in categories or "type_mapping" in categories:
                        detail = FailureDetail(
                            test_id=r.test_id,
                            test_name=r.test_name,
                            category=r.category,
                            severity=severity,
                            description=r.diff_summary or "数值精度/类型映射差异",
                            root_cause="数据类型映射不匹配",
                            possible_fixes=[
                                "确认NUMERIC精度在各库一致",
                                "使用ROUND()标准化精度",
                            ],
                            is_sql_incompatibility=True,
                        )

                details.append(detail)

            # PASS + known_issues: NOT a failure. Known issues are tracked as
            # uncertainty in the coverage report, not as risk. They reduce
            # deterministic consistency in the confidence scorer instead.
            # Risk ONLY comes from actual ERROR and FAIL statuses.

        risk_score = min(100.0, round(risk_sum / total, 1))

        return risk_score, details

    # =========================================================================
    # Failure severity classification
    # =========================================================================

    @staticmethod
    def _classify_failure_severity(result: TestCaseResult) -> str:
        """Classify failure severity based on diff pattern."""
        if result.column_match is False:
            return "BLOCKER"
        if result.row_count_match is False:
            return "HIGH"
        if result.diff_detail:
            categories = set(d.get("category", "") for d in result.diff_detail)
            if "type_mapping" in categories:
                return "HIGH"
            if "precision" in categories:
                return "MEDIUM"
            if "nullability" in categories:
                return "MEDIUM"
            if "boolean" in categories:
                return "LOW"
        return "MEDIUM"
