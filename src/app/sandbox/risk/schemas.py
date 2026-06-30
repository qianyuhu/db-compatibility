"""
Risk Intelligence Data Schemas — typed structures for risk analysis output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# Risk Score Types
# =========================================================================


@dataclass(frozen=True)
class DimensionRisk:
    """Risk score for a single dimension (SQL, Schema, Data, API, Behavioral)."""
    name: str
    raw_score: float  # 0-100, higher = more risk
    weight: float
    weighted_score: float
    deductions: list[str] = field(default_factory=list)
    risk_level: str = "NONE"  # NONE / LOW / MEDIUM / HIGH / BLOCKER


@dataclass(frozen=True)
class RiskScore:
    """Aggregated multi-dimensional risk score.

    Score range: 0-100 (higher = more risk)
    """
    total_score: float  # 0-100
    dimensions: list[DimensionRisk]
    risk_level: str  # SAFE / LOW / MEDIUM / HIGH / BLOCKER
    risk_tags: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "risk_level": self.risk_level,
            "risk_tags": self.risk_tags,
            "summary": self.summary,
            "dimensions": [
                {
                    "name": d.name,
                    "raw_score": d.raw_score,
                    "weight": d.weight,
                    "weighted_score": d.weighted_score,
                    "deductions": d.deductions,
                    "risk_level": d.risk_level,
                }
                for d in self.dimensions
            ],
        }


# =========================================================================
# Coverage Types
# =========================================================================


@dataclass(frozen=True)
class CoverageDimension:
    """Coverage for a single dimension."""
    name: str
    tested: int
    total: int
    percentage: float
    covered_items: list[str] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CoverageReport:
    """Aggregated coverage analysis."""
    sql_coverage: CoverageDimension
    api_coverage: CoverageDimension
    orm_coverage: CoverageDimension
    overall_coverage: float
    critical_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql_coverage": {
                "name": self.sql_coverage.name,
                "tested": self.sql_coverage.tested,
                "total": self.sql_coverage.total,
                "percentage": self.sql_coverage.percentage,
                "covered_items": self.sql_coverage.covered_items,
                "missing_items": self.sql_coverage.missing_items,
            },
            "api_coverage": {
                "name": self.api_coverage.name,
                "tested": self.api_coverage.tested,
                "total": self.api_coverage.total,
                "percentage": self.api_coverage.percentage,
                "covered_items": self.api_coverage.covered_items,
                "missing_items": self.api_coverage.missing_items,
            },
            "orm_coverage": {
                "name": self.orm_coverage.name,
                "tested": self.orm_coverage.tested,
                "total": self.orm_coverage.total,
                "percentage": self.orm_coverage.percentage,
                "covered_items": self.orm_coverage.covered_items,
                "missing_items": self.orm_coverage.missing_items,
            },
            "overall_coverage": self.overall_coverage,
            "critical_gaps": self.critical_gaps,
        }


# =========================================================================
# Confidence Types
# =========================================================================


@dataclass(frozen=True)
class ConfidenceScore:
    """System-level migration confidence score.

    Score range: 0-100 (higher = more confidence)
    Formula: Test Pass Rate + Coverage Score - Risk Score
    """
    total_score: float  # 0-100
    pass_rate_score: float  # 0-100
    coverage_score: float  # 0-100
    risk_penalty: float  # 0-100 (subtracted)
    level: str  # HIGH / MEDIUM / LOW / INSUFFICIENT
    recommendation: str = ""
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "pass_rate_score": self.pass_rate_score,
            "coverage_score": self.coverage_score,
            "risk_penalty": self.risk_penalty,
            "level": self.level,
            "recommendation": self.recommendation,
            "blockers": self.blockers,
        }


# =========================================================================
# Risk Report Types
# =========================================================================


@dataclass(frozen=True)
class CriticalIssue:
    """A critical migration blocker or risk."""
    test_id: str
    test_name: str
    category: str
    severity: str  # LOW / MEDIUM / HIGH / BLOCKER
    description: str
    root_cause: str = ""
    possible_fixes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskIntelligenceReport:
    """Complete risk intelligence analysis report.

    Replaces simple pass/fail reporting with quantified risk assessment.
    """
    # Executive Summary
    source_db: str
    target_db: str
    total_tests: int
    passed: int
    failed: int
    errors: int
    success_rate: float

    # Risk Assessment
    risk_score: RiskScore
    confidence_score: ConfidenceScore
    coverage_report: CoverageReport

    # Migration Readiness
    migration_readiness: str  # SAFE / LOW_RISK / MEDIUM_RISK / HIGH_RISK / BLOCKER
    ready_for_production: bool

    # Critical Issues
    critical_issues: list[CriticalIssue] = field(default_factory=list)
    top_risks: list[str] = field(default_factory=list)

    # Meta
    total_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "executive_summary": {
                "source_db": self.source_db,
                "target_db": self.target_db,
                "total_tests": self.total_tests,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "success_rate": self.success_rate,
                "migration_readiness": self.migration_readiness,
                "ready_for_production": self.ready_for_production,
            },
            "risk_score": self.risk_score.to_dict(),
            "confidence_score": self.confidence_score.to_dict(),
            "coverage_report": self.coverage_report.to_dict(),
            "critical_issues": [
                {
                    "test_id": ci.test_id,
                    "test_name": ci.test_name,
                    "category": ci.category,
                    "severity": ci.severity,
                    "description": ci.description,
                    "root_cause": ci.root_cause,
                    "possible_fixes": ci.possible_fixes,
                }
                for ci in self.critical_issues
            ],
            "top_risks": self.top_risks,
            "total_time_ms": self.total_time_ms,
        }


# =========================================================================
# Risk Level Enum-like constants
# =========================================================================

RISK_LEVELS = {
    (0, 20): "SAFE",
    (21, 40): "LOW",
    (41, 60): "MEDIUM",
    (61, 80): "HIGH",
    (81, 100): "BLOCKER",
}


def classify_risk_level(score: float) -> str:
    """Classify a 0-100 risk score into a risk level."""
    for (low, high), level in RISK_LEVELS.items():
        if low <= score <= high:
            return level
    return "BLOCKER" if score > 80 else "SAFE"


CONFIDENCE_LEVELS = {
    (80, 100): ("HIGH", "迁移风险可控，建议按计划执行。"),
    (60, 79): ("MEDIUM", "存在中等风险，建议完成关键修复后再迁移。"),
    (40, 59): ("LOW", "风险较高，需要在迁移前解决多个问题。"),
    (0, 39): ("INSUFFICIENT", "风险过高，不建议当前执行生产迁移。"),
}


def classify_confidence(score: float) -> tuple[str, str]:
    """Classify confidence score into level + recommendation."""
    for (low, high), (level, rec) in CONFIDENCE_LEVELS.items():
        if low <= score <= high:
            return level, rec
    return "INSUFFICIENT", "数据不足以评估迁移风险。"
