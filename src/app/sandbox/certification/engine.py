"""
Certification Engine — main orchestrator for confidence-driven migration certification.

Pipeline:
    1. Coverage Analysis  → measures what we know vs don't know (uncertainty)
    2. Risk Scoring        → measures actual failures (NOT coverage gaps)
    3. Confidence Scoring  → PassRate × 0.4 + CoverageQuality × 0.4 + Consistency × 0.2
    4. Decision Engine     → READY / NOT_READY / REVIEW_REQUIRED
    5. Build Report        → CertificationReport

Replaces the old MigrationRiskEngine which conflated coverage with risk.
"""

from __future__ import annotations

import time

from ..reporter import TestCaseResult
from ..test_case import MigrationTestCase, get_all_test_cases
from .confidence import ConfidenceScorer
from .coverage import CoverageAnalyzer
from .decision import MigrationDecisionEngine
from .schemas import CertificationReport
from .scorer import RiskScorer


class CertificationEngine:
    """Main certification orchestrator — produces CertificationReport.

    Usage:
        engine = CertificationEngine(source_db="mssql", target_db="kingbasees")
        report = engine.certify(test_results, test_cases)
        # report.to_dict() → JSON-serializable
    """

    def __init__(self, source_db: str, target_db: str):
        """
        Args:
            source_db: Source database type (mssql / kingbasees / dm8)
            target_db: Target database type (mssql / kingbasees / dm8)
        """
        self.source_db = source_db
        self.target_db = target_db

    def certify(
        self,
        test_results: list[TestCaseResult],
        test_cases: list[MigrationTestCase] | None = None,
    ) -> CertificationReport:
        """Run the complete certification pipeline.

        Args:
            test_results: Results from test execution (from MigrationTestRunner)
            test_cases: Original test case definitions (defaults to all)

        Returns:
            CertificationReport with confidence, risk, coverage, and decision.
        """
        start = time.perf_counter()

        if test_cases is None:
            test_cases = get_all_test_cases()

        # ---- Executive summary ----
        total = len(test_results)
        passed = sum(1 for r in test_results if r.status == "PASS")
        failed = sum(1 for r in test_results if r.status == "FAIL")
        errors = sum(1 for r in test_results if r.status == "ERROR")
        failures_count = failed + errors
        failure_rate = round(failures_count / total, 4) if total > 0 else 0.0

        # ---- Step 1: Coverage Analysis (uncertainty measurement) ----
        coverage_report = CoverageAnalyzer.analyze(test_cases)

        # ---- Step 2: Risk Scoring (actual failures only, NO coverage penalty) ----
        risk_score, failure_details = RiskScorer.score(test_results)

        # ---- Step 3: Confidence Scoring (new additive formula) ----
        total_confidence, pass_component, coverage_quality, consistency = (
            ConfidenceScorer.score(test_results, coverage_report)
        )

        # ---- Step 4: Migration Decision ----
        decision = MigrationDecisionEngine.decide(
            failure_rate=failure_rate,
            confidence_score=total_confidence,
            failure_details=failure_details,
        )

        # ---- Build Report ----
        elapsed = round((time.perf_counter() - start) * 1000, 1)

        db_pair = _format_db_pair(self.source_db, self.target_db)

        return CertificationReport(
            confidence_score=total_confidence,
            risk_score=risk_score,
            migration_status=decision.status,
            db_pair=db_pair,
            coverage_report=coverage_report,
            pass_rate_component=pass_component,
            coverage_quality_component=coverage_quality,
            deterministic_consistency=consistency,
            failure_details=failure_details,
            failure_rate=failure_rate,
            source_db=self.source_db,
            target_db=self.target_db,
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            total_time_ms=elapsed,
        )


# =========================================================================
# Utilities
# =========================================================================


def _format_db_pair(source_db: str, target_db: str) -> str:
    """Format a db_pair label consistently.

    Examples:
        ("mssql", "kingbasees") → "MSSQL→KingbaseES"
        ("mssql", "dm8") → "MSSQL→DM"
    """
    _LABELS = {
        "mssql": "MSSQL",
        "kingbasees": "KingbaseES",
        "dm8": "DM",
    }
    src_label = _LABELS.get(source_db, source_db.upper())
    tgt_label = _LABELS.get(target_db, target_db.upper())
    return f"{src_label}→{tgt_label}"
