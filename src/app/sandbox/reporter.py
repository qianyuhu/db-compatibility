"""
Test Report System — generates structured migration test reports.

Output:
- Summary statistics (total, passed, failed, success rate)
- Per-test-case results with diff details
- Failure drilldown with root cause analysis
- Risk-based reporting with confidence scoring
- JSON-serializable format for API and frontend consumption
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .risk.schemas import (
    ConfidenceScore,
    CoverageReport,
    CriticalIssue,
    RiskScore,
)


# =========================================================================
# Report Types
# =========================================================================


@dataclass(frozen=True)
class TestCaseResult:
    """Result of a single test case execution."""
    test_id: str
    test_name: str
    category: str
    status: str  # PASS / FAIL / ERROR / SKIPPED
    source_db: str
    target_db: str
    source_execution_time_ms: float = 0.0
    target_execution_time_ms: float = 0.0
    total_time_ms: float = 0.0
    row_count_match: bool | None = None
    data_match: bool | None = None
    column_match: bool | None = None
    diff_summary: str = ""
    error_message: str | None = None
    known_issues: list[str] = field(default_factory=list)
    diff_detail: list[dict[str, Any]] = field(default_factory=list)
    enhanced_diff: dict[str, Any] | None = None
    risk_score: float = 0.0  # Individual test risk score (0-100)


@dataclass(frozen=True)
class TestReport:
    """Complete test run report with optional risk intelligence and certification."""
    source_db: str
    target_db: str
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    success_rate: float
    total_time_ms: float
    results: list[TestCaseResult] = field(default_factory=list)
    seed_results: dict[str, Any] = field(default_factory=dict)
    summary_by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    # Risk Intelligence fields (populated when risk engine runs — backward compat)
    risk_score: RiskScore | None = None
    confidence_score: ConfidenceScore | None = None
    coverage_report: CoverageReport | None = None
    critical_issues: list[CriticalIssue] = field(default_factory=list)
    migration_readiness: str = "UNKNOWN"
    top_risks: list[str] = field(default_factory=list)
    # Certification Report (from new CertificationEngine — primary for new consumers)
    certification_report: Any | None = None  # CertificationReport

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict including risk intelligence."""
        result = {
            "source_db": self.source_db,
            "target_db": self.target_db,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "success_rate": self.success_rate,
            "total_time_ms": self.total_time_ms,
            "seed_results": self.seed_results,
            "summary_by_category": self.summary_by_category,
            "migration_readiness": self.migration_readiness,
            "top_risks": self.top_risks,
            "results": [
                {
                    "test_id": r.test_id,
                    "test_name": r.test_name,
                    "category": r.category,
                    "status": r.status,
                    "source_db": r.source_db,
                    "target_db": r.target_db,
                    "source_execution_time_ms": r.source_execution_time_ms,
                    "target_execution_time_ms": r.target_execution_time_ms,
                    "total_time_ms": r.total_time_ms,
                    "row_count_match": r.row_count_match,
                    "data_match": r.data_match,
                    "column_match": r.column_match,
                    "diff_summary": r.diff_summary,
                    "error_message": r.error_message,
                    "known_issues": r.known_issues,
                    "diff_detail": r.diff_detail,
                    "enhanced_diff": r.enhanced_diff,
                    "risk_score": r.risk_score,
                }
                for r in self.results
            ],
        }

        # Add risk intelligence if available
        if self.risk_score:
            result["risk_score"] = self.risk_score.to_dict()
        if self.confidence_score:
            result["confidence_score"] = self.confidence_score.to_dict()
        if self.coverage_report:
            result["coverage_report"] = self.coverage_report.to_dict()
        if self.critical_issues:
            result["critical_issues"] = [
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
            ]

        # Add certification data if available (from new CertificationEngine)
        if self.certification_report:
            try:
                result["certification"] = self.certification_report.to_dict()
            except Exception:
                pass  # Best-effort — don't break serialization

        return result


# =========================================================================
# Report Builder
# =========================================================================


class ReportBuilder:
    """Build a TestReport from test case results."""

    @staticmethod
    def build(
        results: list[TestCaseResult],
        source_db: str,
        target_db: str,
        seed_results: dict[str, Any] | None = None,
    ) -> TestReport:
        """Build a structured test report from results.

        Args:
            results: List of individual test case results
            source_db: Source database type
            target_db: Target database type
            seed_results: Results from the seed/reset step

        Returns:
            TestReport with summary statistics and per-category breakdown
        """
        total = len(results)
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        errors = sum(1 for r in results if r.status == "ERROR")
        skipped = sum(1 for r in results if r.status == "SKIPPED")

        success_rate = round((passed / total * 100) if total > 0 else 0, 1)
        total_time = round(sum(r.total_time_ms for r in results), 1)

        # Category breakdown
        category_summary: dict[str, dict[str, int]] = {}
        for r in results:
            if r.category not in category_summary:
                category_summary[r.category] = {"total": 0, "passed": 0, "failed": 0, "errors": 0}
            category_summary[r.category]["total"] += 1
            if r.status == "PASS":
                category_summary[r.category]["passed"] += 1
            elif r.status == "FAIL":
                category_summary[r.category]["failed"] += 1
            elif r.status == "ERROR":
                category_summary[r.category]["errors"] += 1

        return TestReport(
            source_db=source_db,
            target_db=target_db,
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            success_rate=success_rate,
            total_time_ms=total_time,
            results=results,
            seed_results=seed_results or {},
            summary_by_category=category_summary,
        )


# =========================================================================
# Failure Drilldown
# =========================================================================


@dataclass(frozen=True)
class FailureDrilldown:
    """Detailed failure analysis for a single test case."""
    test_id: str
    test_name: str
    root_cause: str
    possible_fixes: list[str] = field(default_factory=list)
    severity: str = "MEDIUM"  # LOW / MEDIUM / HIGH / BLOCKER
    affected_tests: list[str] = field(default_factory=list)


def generate_failure_drilldown(result: TestCaseResult) -> FailureDrilldown:
    """Generate a detailed failure analysis for a failed test case.

    Uses heuristics based on the diff category to suggest root causes
    and possible remediation steps.
    """
    root_cause = "未知差异"
    possible_fixes: list[str] = []
    severity = "MEDIUM"

    if result.error_message:
        root_cause = f"执行错误: {result.error_message}"
        severity = "HIGH"
        possible_fixes = [
            "检查目标数据库连接状态",
            "确认 SQL 语法兼容性",
            "查看目标数据库错误日志",
        ]
    elif not result.row_count_match:
        root_cause = "源库和目标库返回行数不一致"
        severity = "HIGH"
        possible_fixes = [
            "检查 WHERE 子句的 NULL 处理逻辑",
            "确认 JOIN 行为差异（INNER vs OUTER）",
            "检查默认字符集/排序规则对字符串比较的影响",
        ]
    elif not result.column_match:
        root_cause = "源库和目标库返回的列结构不一致"
        severity = "MEDIUM"
        possible_fixes = [
            "检查列名大小写映射",
            "确认 SELECT 语句中的列别名",
            "检查 INFORMATION_SCHEMA 查询的方言差异",
        ]
    elif not result.data_match:
        root_cause = "数据值存在差异"
        # Try to be more specific based on diff detail
        if result.diff_detail:
            categories = set(
                d.get("category", "") for d in result.diff_detail
            )
            if "precision" in categories:
                root_cause = "数值精度差异（DECIMAL/NUMERIC 类型映射）"
                possible_fixes = [
                    "确认 NUMERIC 精度和小数位数在各数据库中一致",
                    "使用 ROUND() 函数标准化精度",
                ]
            elif "boolean" in categories:
                root_cause = "布尔值表示方式不同（1/0 vs t/f vs true/false）"
                possible_fixes = [
                    "在应用层统一布尔值表示",
                    "使用 CASE WHEN 标准化布尔输出",
                ]
            elif "nullability" in categories:
                root_cause = "NULL 值处理差异"
                possible_fixes = [
                    "使用 COALESCE() 统一 NULL 处理",
                    "检查 NOT NULL 约束在各数据库中的实现",
                ]
            elif "type_mapping" in categories:
                root_cause = "数据类型映射差异"
                possible_fixes = [
                    "检查 VARCHAR/NVARCHAR 映射",
                    "确认 DATETIME/TIMESTAMP 类型映射",
                ]
            else:
                possible_fixes = [
                    "逐一对比差异字段的值",
                    "检查数据类型的跨库映射",
                ]

    if result.known_issues:
        severity = "LOW"  # Known issues are expected

    return FailureDrilldown(
        test_id=result.test_id,
        test_name=result.test_name,
        root_cause=root_cause,
        possible_fixes=possible_fixes,
        severity=severity,
    )
