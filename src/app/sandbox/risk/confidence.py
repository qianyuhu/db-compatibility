"""
Confidence Scoring — system-level migration confidence assessment.

Formula:
    Confidence Score = Pass Rate Component + Coverage Component - Risk Penalty

    Pass Rate Component:   success_rate * 0.40  (max 40 points)
    Coverage Component:    overall_coverage * 0.35  (max 35 points)
    Risk Penalty:          risk_score * 0.25  (max 25 points subtracted)

Output:
    Confidence Score: 0-100 (higher = more confidence)
    Level: HIGH / MEDIUM / LOW / INSUFFICIENT
    Recommendation: Human-readable migration decision guidance
"""

from __future__ import annotations

from ..reporter import TestCaseResult
from ..test_case import MigrationTestCase
from .coverage import CoverageReport
from .schemas import ConfidenceScore, RiskScore, classify_confidence


class ConfidenceScorer:
    """Compute system-level migration confidence score.

    Integrates pass rate, coverage, and risk into a single decision score.
    """

    # Component weights
    PASS_RATE_WEIGHT = 0.40
    COVERAGE_WEIGHT = 0.35
    RISK_PENALTY_WEIGHT = 0.25

    @staticmethod
    def score(
        test_results: list[TestCaseResult],
        risk_score: RiskScore,
        coverage_report: CoverageReport,
    ) -> ConfidenceScore:
        """Compute the migration confidence score.

        Args:
            test_results: Individual test case execution results
            risk_score: Multi-dimensional risk score
            coverage_report: Coverage analysis report

        Returns:
            ConfidenceScore with total, components, level, and recommendation.
        """
        # --- Pass Rate Component (max 40) ---
        total = len(test_results)
        passed = sum(1 for r in test_results if r.status == "PASS")
        success_rate = (passed / total * 100) if total > 0 else 0
        pass_rate_score = round(success_rate * ConfidenceScorer.PASS_RATE_WEIGHT / 100 * 100, 1)

        # --- Coverage Component (max 35) ---
        coverage_score = round(
            coverage_report.overall_coverage * ConfidenceScorer.COVERAGE_WEIGHT / 100 * 100,
            1,
        )

        # --- Risk Penalty (max 25 subtracted) ---
        risk_penalty = round(risk_score.total_score * ConfidenceScorer.RISK_PENALTY_WEIGHT / 100 * 100, 1)

        # --- Total Confidence ---
        total_score = max(0, min(100, round(pass_rate_score + coverage_score - risk_penalty, 1)))

        # --- Level + Recommendation ---
        level, recommendation = classify_confidence(total_score)

        # --- Blockers ---
        blockers: list[str] = []
        if risk_score.risk_level in ("HIGH", "BLOCKER"):
            blockers.append(f"风险等级 '{risk_score.risk_level}' — 存在高风险维度")
        if coverage_report.overall_coverage < 60:
            blockers.append(f"总体覆盖率过低 ({coverage_report.overall_coverage:.0f}%)")
        if success_rate < 80:
            blockers.append(f"测试通过率不足 ({success_rate:.0f}%)")
        for gap in coverage_report.critical_gaps[:2]:
            blockers.append(gap)

        # --- Custom recommendation ---
        if not recommendation:
            if level == "HIGH":
                recommendation = "迁移风险可控。建议完成覆盖盲区的补充测试后，按计划执行迁移。"
            elif level == "MEDIUM":
                recommendation = "存在中等风险。建议解决关键问题后重新评估，必要时分批迁移。"
            elif level == "LOW":
                recommendation = "风险较高。需要先解决所有 BLOCKER 级别的问题，补充充分测试后再评估。"
            else:
                recommendation = "风险过高。不建议当前执行生产迁移。需要大量补充测试和兼容性修复。"

        return ConfidenceScore(
            total_score=total_score,
            pass_rate_score=pass_rate_score,
            coverage_score=coverage_score,
            risk_penalty=risk_penalty,
            level=level,
            recommendation=recommendation,
            blockers=blockers,
        )
