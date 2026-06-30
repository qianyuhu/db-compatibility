"""
Migration Risk Engine — main orchestrator for risk intelligence.

Sits on top of the Sandbox Test Harness to convert raw test results into
actionable risk intelligence:

Pipeline:
    Test Results → Risk Scorer → Coverage Analyzer → Confidence Scorer
    → Critical Issues → Risk Intelligence Report

Answers: "Can this database migration be safely executed in production?"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..reporter import FailureDrilldown, TestCaseResult, TestReport, generate_failure_drilldown
from ..test_case import MigrationTestCase, get_all_test_cases
from .confidence import ConfidenceScorer
from .coverage import CoverageAnalyzer
from .schemas import (
    CriticalIssue,
    RiskIntelligenceReport,
    RiskScore,
    classify_risk_level,
)
from .scorer import RiskScorer


# =========================================================================
# Migration Readiness Mapping
# =========================================================================

def _readiness_level(risk_score: float) -> str:
    """Map risk score to migration readiness label."""
    if risk_score <= 20:
        return "SAFE"
    elif risk_score <= 40:
        return "LOW_RISK"
    elif risk_score <= 60:
        return "MEDIUM_RISK"
    elif risk_score <= 80:
        return "HIGH_RISK"
    else:
        return "BLOCKER"


def _is_ready_for_production(risk_score: float, confidence: float) -> bool:
    """Determine if migration is production-ready."""
    return risk_score <= 40 and confidence >= 70


# =========================================================================
# MigrationRiskEngine
# =========================================================================


@dataclass
class RiskEngineResult:
    """Complete output from MigrationRiskEngine."""
    risk_report: RiskIntelligenceReport
    total_time_ms: float = 0.0


class MigrationRiskEngine:
    """DEPRECATED: Use CertificationEngine for new code.

    This engine now delegates to CertificationEngine internally and
    converts results to the old RiskIntelligenceReport format for
    backward compatibility.

    New code should use:
        from app.sandbox.certification.engine import CertificationEngine

    Usage (backward compat):
        engine = MigrationRiskEngine(source_db="mssql", target_db="kingbasees")
        result = engine.analyze(test_results, test_cases)
        # result.risk_report.to_dict() → old format
    """

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    def analyze(
        self,
        test_results: list[TestCaseResult],
        test_cases: list[MigrationTestCase] | None = None,
    ) -> RiskEngineResult:
        """Run risk analysis — delegates to CertificationEngine internally.

        Converts the new CertificationReport to the old RiskIntelligenceReport
        format for backward compatibility.
        """
        import time

        from app.sandbox.certification.engine import CertificationEngine
        from app.sandbox.certification.schemas import CertificationReport

        start = time.perf_counter()

        if test_cases is None:
            test_cases = get_all_test_cases()

        # Delegate to new CertificationEngine
        cert_engine = CertificationEngine(self.source_db, self.target_db)
        cert_report = cert_engine.certify(test_results, test_cases)

        # Convert to old format
        risk_report = _from_cert_report(cert_report, test_results)

        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return RiskEngineResult(
            risk_report=risk_report,
            total_time_ms=elapsed,
        )

    @staticmethod
    def _extract_critical_issues(
        test_results: list[TestCaseResult],
        test_cases: list[MigrationTestCase],
    ) -> list[CriticalIssue]:
        """Extract critical migration issues from test results."""
        issues: list[CriticalIssue] = []

        for result in test_results:
            if result.status in ("FAIL", "ERROR"):
                tc = next((t for t in test_cases if t.id == result.test_id), None)

                drilldown = generate_failure_drilldown(result)

                issues.append(CriticalIssue(
                    test_id=result.test_id,
                    test_name=result.test_name,
                    category=result.category,
                    severity=drilldown.severity,
                    description=result.diff_summary or result.error_message or "未知差异",
                    root_cause=drilldown.root_cause,
                    possible_fixes=list(drilldown.possible_fixes),
                ))

        # Sort by severity (BLOCKER first, then HIGH, etc.)
        severity_order = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        issues.sort(key=lambda i: severity_order.get(i.severity, 99))

        return issues

    @staticmethod
    def _extract_top_risks(
        risk_score: RiskScore,
        coverage_report: Any,
        test_results: list[TestCaseResult],
    ) -> list[str]:
        """Extract the top 5 migration risks."""
        risks: list[str] = []

        # Risk from highest dimension
        dims = sorted(risk_score.dimensions, key=lambda d: d.raw_score, reverse=True)
        if dims and dims[0].raw_score > 0:
            risks.append(f"{dims[0].name}: {dims[0].raw_score:.0f}/100 — {dims[0].risk_level}")

        # Coverage gaps
        for gap in coverage_report.critical_gaps[:2]:
            risks.append(gap)

        # Failed tests
        failed = [r for r in test_results if r.status == "FAIL"]
        if failed:
            risks.append(f"{len(failed)} 个测试用例失败 — 需要修复")

        # Error tests
        errors = [r for r in test_results if r.status == "ERROR"]
        if errors:
            risks.append(f"{len(errors)} 个测试执行错误 — 连接或语法问题")

        # Overall risk level
        if risk_score.risk_level in ("HIGH", "BLOCKER"):
            risks.append(f"总体风险等级: {risk_score.risk_level} — 不建议立即迁移")

        return risks[:5]


# =========================================================================
# Quick Analysis (no DB access needed — uses existing test metadata)
# =========================================================================


class RiskQuickAnalyzer:
    """Static risk analysis from test case definitions only (no execution needed).

    Useful for pre-migration assessment before running actual tests.
    """

    @staticmethod
    def preflight(
        test_cases: list[MigrationTestCase] | None = None,
        source_db: str = "mssql",
        target_db: str = "kingbasees",
    ) -> dict[str, Any]:
        """Pre-flight risk analysis based on test definitions only.

        Returns estimated risk levels before any execution.
        """
        if test_cases is None:
            test_cases = get_all_test_cases()

        # Coverage from definitions
        coverage = CoverageAnalyzer.analyze(test_cases)

        # Count known issues
        total_known_issues = sum(len(tc.known_issues) for tc in test_cases)

        # Count tests needing explicit rewrite
        rewrite_needed = sum(1 for tc in test_cases if tc.target_sql and tc.target_sql != tc.source_sql)

        # Estimated risk dimensions
        sql_risk_estimate = min(100, 20 + rewrite_needed * 10 + total_known_issues * 5)

        return {
            "source_db": source_db,
            "target_db": target_db,
            "total_test_cases": len(test_cases),
            "estimated_sql_risk": sql_risk_estimate,
            "rewrite_required_count": rewrite_needed,
            "known_issue_count": total_known_issues,
            "coverage": coverage.to_dict(),
            "estimated_readiness": _readiness_level(sql_risk_estimate),
        }


# =========================================================================
# Certification → Risk Report Conversion (backward compatibility)
# =========================================================================


def _from_cert_report(
    cert_report: Any,  # CertificationReport
    test_results: list[TestCaseResult],
) -> RiskIntelligenceReport:
    """Convert new CertificationReport to old RiskIntelligenceReport format.

    This ensures all existing consumers of RiskIntelligenceReport continue
    to work without changes, even though the internal scoring model has
    been completely replaced.
    """
    from .schemas import (
        ConfidenceScore,
        CoverageDimension as OldCovDim,
        CoverageReport,
        CriticalIssue,
        RiskScore,
        classify_confidence,
        classify_risk_level,
    )

    # Map risk from actual failures only
    risk_score = RiskScore(
        total_score=cert_report.risk_score,
        dimensions=[],
        risk_level=classify_risk_level(cert_report.risk_score),
        risk_tags=["failures_based"] if cert_report.failure_rate > 0 else [],
        summary=(
            f"实际失败率: {cert_report.failure_rate*100:.0f}% — 仅来自实际失败"
            if cert_report.failure_rate > 0
            else "无实际失败 — 风险仅限于已验证区域"
        ),
    )

    # Map confidence
    level, recommendation = classify_confidence(cert_report.confidence_score)
    confidence_score = ConfidenceScore(
        total_score=cert_report.confidence_score,
        pass_rate_score=cert_report.pass_rate_component,
        coverage_score=cert_report.coverage_quality_component,
        risk_penalty=0.0,
        level=level,
        recommendation=recommendation,
        blockers=[f.description for f in cert_report.failure_details[:3]],
    )

    # Map coverage (3 dims in old format, business_flow omitted)
    cert_cov = cert_report.coverage_report
    coverage_report = CoverageReport(
        sql_coverage=OldCovDim(
            name=cert_cov.sql_coverage.name,
            tested=cert_cov.sql_coverage.tested,
            total=cert_cov.sql_coverage.total,
            percentage=cert_cov.sql_coverage.percentage,
            covered_items=cert_cov.sql_coverage.covered_items,
            missing_items=cert_cov.sql_coverage.missing_items,
        ),
        api_coverage=OldCovDim(
            name=cert_cov.api_coverage.name,
            tested=cert_cov.api_coverage.tested,
            total=cert_cov.api_coverage.total,
            percentage=cert_cov.api_coverage.percentage,
            covered_items=cert_cov.api_coverage.covered_items,
            missing_items=cert_cov.api_coverage.missing_items,
        ),
        orm_coverage=OldCovDim(
            name=cert_cov.orm_coverage.name,
            tested=cert_cov.orm_coverage.tested,
            total=cert_cov.orm_coverage.total,
            percentage=cert_cov.orm_coverage.percentage,
            covered_items=cert_cov.orm_coverage.covered_items,
            missing_items=cert_cov.orm_coverage.missing_items,
        ),
        overall_coverage=cert_cov.overall_coverage,
        critical_gaps=cert_cov.critical_gaps,
    )

    # Map failures to CriticalIssue
    critical_issues = [
        CriticalIssue(
            test_id=f.test_id,
            test_name=f.test_name,
            category=f.category,
            severity=f.severity,
            description=f.description,
            root_cause=f.root_cause,
            possible_fixes=f.possible_fixes,
        )
        for f in cert_report.failure_details
    ]

    # Map status
    readiness_map = {
        "READY": "SAFE",
        "REVIEW_REQUIRED": "MEDIUM_RISK",
        "NOT_READY": "HIGH_RISK",
    }
    readiness = readiness_map.get(cert_report.migration_status, "MEDIUM_RISK")
    production_ready = cert_report.migration_status == "READY"

    # Build top risks (actual failures + uncertainty areas)
    top_risks: list[str] = []
    for f in cert_report.failure_details[:3]:
        top_risks.append(f"[{f.test_id}] {f.severity}: {f.description}")
    for ua in cert_cov.uncertainty_areas[:2]:
        top_risks.append(f"⚠ 覆盖盲区 (不确定性): {ua}")

    return RiskIntelligenceReport(
        source_db=cert_report.source_db,
        target_db=cert_report.target_db,
        total_tests=cert_report.total_tests,
        passed=cert_report.passed,
        failed=cert_report.failed,
        errors=cert_report.errors,
        success_rate=round(
            (cert_report.passed / cert_report.total_tests * 100)
            if cert_report.total_tests > 0 else 0, 1
        ),
        risk_score=risk_score,
        confidence_score=confidence_score,
        coverage_report=coverage_report,
        migration_readiness=readiness,
        ready_for_production=production_ready,
        critical_issues=critical_issues,
        top_risks=top_risks[:5],
    )
