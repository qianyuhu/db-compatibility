"""
Confidence Scorer v2 — confidence-driven certification model.

Formula:
    Confidence = PassRate × 0.40 + CoverageQuality × 0.40 + DeterministicConsistency × 0.20

Key difference from v1:
    - Coverage is CoverageQuality (uncertainty measurement), NOT risk
    - No risk penalty term (coverage gaps are NOT subtracted)
    - Consistency is a separate positive signal
    - All components are additive (higher = better)
"""

from __future__ import annotations

from ..reporter import TestCaseResult
from .schemas import CertificationCoverageReport


class ConfidenceScorer:
    """Compute migration confidence using evidence-positive scoring.

    All components are additive. Nothing is subtracted. Higher = better.
    Coverage contributes positively (as quality, not as risk penalty).
    """

    PASS_RATE_WEIGHT = 0.40
    COVERAGE_QUALITY_WEIGHT = 0.40
    CONSISTENCY_WEIGHT = 0.20

    MAX_PASS_RATE = 40    # 0.40 × 100
    MAX_COVERAGE = 40     # 0.40 × 100
    MAX_CONSISTENCY = 20  # 0.20 × 100

    @classmethod
    def score(
        cls,
        test_results: list[TestCaseResult],
        coverage_report: CertificationCoverageReport,
    ) -> tuple[float, float, float, float]:
        """Compute confidence score.

        Args:
            test_results: Individual test case execution results
            coverage_report: 4-dimension coverage analysis

        Returns:
            (total_confidence, pass_rate_component, coverage_quality_component, consistency_component)
            All values 0-100.
        """
        pass_component = cls._pass_rate_component(test_results)
        coverage_component = cls._coverage_quality_component(coverage_report)
        consistency_component = cls._deterministic_consistency(test_results)

        total = min(100.0, pass_component + coverage_component + consistency_component)

        return (
            round(total, 1),
            round(pass_component, 1),
            round(coverage_component, 1),
            round(consistency_component, 1),
        )

    # =========================================================================
    # Pass Rate Component (max 40)
    # =========================================================================

    @classmethod
    def _pass_rate_component(cls, results: list[TestCaseResult]) -> float:
        """Compute pass rate contribution.

        PassRate = passed / total × 40
        """
        total = len(results)
        if total == 0:
            return 0.0
        passed = sum(1 for r in results if r.status == "PASS")
        pass_rate = (passed / total) * 100
        return round(pass_rate * cls.PASS_RATE_WEIGHT, 1)

    # =========================================================================
    # Coverage Quality Component (max 40)
    # =========================================================================

    @classmethod
    def _coverage_quality_component(cls, coverage_report: CertificationCoverageReport) -> float:
        """Compute coverage quality contribution.

        CoverageQuality = overall_coverage% × 40

        Coverage here is a measure of how thoroughly we've tested — it's
        about the breadth of evidence, NOT risk.
        """
        quality = coverage_report.overall_coverage
        return round(quality * cls.COVERAGE_QUALITY_WEIGHT, 1)

    # =========================================================================
    # Deterministic Consistency Component (max 20)
    # =========================================================================

    @classmethod
    def _deterministic_consistency(cls, results: list[TestCaseResult]) -> float:
        """Measure how consistently results match across source and target.

        Per-test consistency scoring:
          - PASS with 0 risk, no known issues:  100 (fully deterministic)
          - PASS with known_issues:              85  (minor known divergence)
          - PASS but has risk_score:             70  (some divergence)
          - CONDITIONAL:                         60  (moderate divergence)
          - ERROR:                               20  (runtime failure)
          - FAIL:                                 0  (non-deterministic)

        Overall consistency = average per-test score × 0.20
        """
        if not results:
            return 0.0

        scores: list[float] = []
        for r in results:
            if r.status == "PASS":
                if r.known_issues:
                    scores.append(85.0)
                elif r.risk_score > 0:
                    scores.append(70.0)
                else:
                    scores.append(100.0)
            elif r.status == "CONDITIONAL":
                scores.append(60.0)
            elif r.status == "ERROR":
                scores.append(20.0)
            else:  # FAIL
                scores.append(0.0)

        avg = sum(scores) / len(scores)
        # avg is 0-100, CONSISTENCY_WEIGHT is 0.20, result is 0-20
        return round(avg * cls.CONSISTENCY_WEIGHT, 1)
