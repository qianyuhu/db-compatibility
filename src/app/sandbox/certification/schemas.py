"""
Certification Engine Data Schemas — typed structures for confidence-driven
migration certification.

Key philosophical difference from the old risk model:
  - Coverage = uncertainty (affects confidence, NOT risk)
  - Risk = actual failures only (runtime errors, schema mismatches, SQL incompatibilities)
  - Confidence is derived independently: PassRate + CoverageQuality + Consistency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# Coverage Types
# =========================================================================


@dataclass(frozen=True)
class CoverageDimension:
    """Coverage for a single dimension (SQL, API, ORM, Business Flow).

    Coverage low = uncertainty, NOT risk. Missing coverage means
    we don't know the answer — it doesn't mean the answer is wrong.
    """
    name: str
    tested: int
    total: int
    percentage: float
    covered_items: list[str] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tested": self.tested,
            "total": self.total,
            "percentage": self.percentage,
            "covered_items": self.covered_items,
            "missing_items": self.missing_items,
        }


@dataclass(frozen=True)
class CertificationCoverageReport:
    """4-dimension coverage report.

    Dimensions:
      1. SQL Coverage      — SQL feature/type coverage
      2. API Coverage      — API endpoint coverage
      3. ORM Coverage      — ORM pattern coverage
      4. Business Flow     — end-to-end flow coverage
    """
    sql_coverage: CoverageDimension
    api_coverage: CoverageDimension
    orm_coverage: CoverageDimension
    business_flow_coverage: CoverageDimension
    overall_coverage: float
    critical_gaps: list[str] = field(default_factory=list)
    # Uncertainty areas: what we DON'T know (not risk!)
    uncertainty_areas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql_coverage.percentage,
            "api": self.api_coverage.percentage,
            "orm": self.orm_coverage.percentage,
            "business_flow": self.business_flow_coverage.percentage,
        }


# =========================================================================
# Failure Types (actual problems, not coverage gaps)
# =========================================================================


@dataclass(frozen=True)
class FailureDetail:
    """A migration incompatibility found during actual test execution.

    Critical distinction: this is a REAL failure, not a coverage gap.
    Coverage gaps are reported separately in coverage_report.uncertainty_areas.
    """
    test_id: str
    test_name: str
    category: str
    severity: str  # LOW / MEDIUM / HIGH / BLOCKER
    description: str
    root_cause: str = ""
    possible_fixes: list[str] = field(default_factory=list)
    # Categorization flags
    is_schema_mismatch: bool = False
    is_runtime_error: bool = False
    is_sql_incompatibility: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "root_cause": self.root_cause,
            "possible_fixes": self.possible_fixes,
            "is_schema_mismatch": self.is_schema_mismatch,
            "is_runtime_error": self.is_runtime_error,
            "is_sql_incompatibility": self.is_sql_incompatibility,
        }


# =========================================================================
# Decision Types
# =========================================================================

# Valid migration statuses
MIGRATION_READY = "READY"
MIGRATION_NOT_READY = "NOT_READY"
MIGRATION_REVIEW_REQUIRED = "REVIEW_REQUIRED"

MIGRATION_STATUSES = frozenset({
    MIGRATION_READY,
    MIGRATION_NOT_READY,
    MIGRATION_REVIEW_REQUIRED,
})


@dataclass(frozen=True)
class MigrationDecision:
    """Decision output with reasoning trace.

    Produced by MigrationDecisionEngine based on confidence_score,
    failure_rate, and blocker presence.
    """
    status: str  # READY / NOT_READY / REVIEW_REQUIRED
    confidence_score: float
    failure_rate: float
    reasoning: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence_score": self.confidence_score,
            "failure_rate": self.failure_rate,
            "reasoning": self.reasoning,
            "recommended_actions": self.recommended_actions,
        }


# =========================================================================
# Certification Report (main output)
# =========================================================================


@dataclass(frozen=True)
class CertificationReport:
    """Complete migration certification report.

    This is the primary output of the Certification Engine. It replaces
    the old RiskIntelligenceReport with a proper separation of:
      - confidence (derived from evidence)
      - risk (only from actual failures)
      - coverage (uncertainty measurement)

    Target output shape:
    {
      "confidence_score": 85.2,
      "risk_score": 12.5,
      "migration_status": "READY",
      "db_pair": "MSSQL→KingbaseES",
      "coverage": {"sql": 75, "api": 60, "orm": 55, "business_flow": 40},
      "pass_rate_component": 38.0,
      "coverage_quality_component": 23.0,
      "deterministic_consistency": 18.0,
      "failure_rate": 0.0,
      "failure_details": [...]
    }
    """
    # Decision-level scores
    confidence_score: float            # 0-100, higher = more confidence
    risk_score: float                  # 0-100, higher = more dangerous (failures only)
    migration_status: str              # READY / NOT_READY / REVIEW_REQUIRED
    db_pair: str                       # "MSSQL→KingbaseES"

    # Coverage (independent from risk — this is uncertainty, not risk)
    coverage_report: CertificationCoverageReport

    # Confidence decomposition
    pass_rate_component: float         # 0-40 (PassRate × 0.40)
    coverage_quality_component: float  # 0-40 (CoverageQuality × 0.40)
    deterministic_consistency: float   # 0-20 (Consistency × 0.20)

    # Risk details (only from actual failures — never from coverage)
    failure_details: list[FailureDetail] = field(default_factory=list)
    failure_rate: float = 0.0

    # Meta
    source_db: str = ""
    target_db: str = ""
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    total_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "confidence_score": self.confidence_score,
            "risk_score": self.risk_score,
            "migration_status": self.migration_status,
            "db_pair": self.db_pair,
            "coverage": self.coverage_report.to_dict(),
            "pass_rate_component": self.pass_rate_component,
            "coverage_quality_component": self.coverage_quality_component,
            "deterministic_consistency": self.deterministic_consistency,
            "failure_rate": self.failure_rate,
            "failure_details": [f.to_dict() for f in self.failure_details],
            "executive_summary": {
                "source_db": self.source_db,
                "target_db": self.target_db,
                "total_tests": self.total_tests,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "total_time_ms": self.total_time_ms,
            },
            "decision": MigrationDecision(
                status=self.migration_status,
                confidence_score=self.confidence_score,
                failure_rate=self.failure_rate,
                reasoning=[
                    f"Confidence: {self.confidence_score}/100",
                    f"Risk (failures only): {self.risk_score}/100",
                    f"Pass rate component: {self.pass_rate_component}/40",
                    f"Coverage quality: {self.coverage_quality_component}/40",
                    f"Deterministic consistency: {self.deterministic_consistency}/20",
                ],
                recommended_actions=(
                    ["Proceed with migration"]
                    if self.migration_status == MIGRATION_READY
                    else (
                        ["Review failures and retest"]
                        if self.migration_status == MIGRATION_REVIEW_REQUIRED
                        else ["Resolve critical failures before migration"]
                    )
                ),
            ).to_dict(),
        }
