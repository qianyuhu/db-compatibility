"""
Migration Test Runner — core execution engine for the sandbox test harness.

Pipeline:
    1. Reset sandbox state (truncate + reseed)
    2. For each test case:
       a. Execute SQL on source DB
       b. Execute SQL on target DB (rewritten if needed)
       c. Run deterministic diff
       d. Generate enhanced 3-layer diff (via explanation_engine)
       e. Collect result
    3. Build report
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .data import SANDBOX_DATASET
from .diff_engine import DeterministicDiff, DiffEngine
from .reporter import ReportBuilder, TestCaseResult, TestReport
from .risk.engine import MigrationRiskEngine
from .seeder import SandboxSeeder, SeedResult
from .test_case import MigrationTestCase, get_all_test_cases


# =========================================================================
# Runner Result
# =========================================================================


@dataclass
class RunnerResult:
    """Complete result from a MigrationTestRunner run."""
    source_db: str
    target_db: str
    seed_results: dict[str, SeedResult] = field(default_factory=dict)
    test_results: list[TestCaseResult] = field(default_factory=list)
    report: TestReport | None = None
    total_time_ms: float = 0.0


# =========================================================================
# MigrationTestRunner
# =========================================================================


class MigrationTestRunner:
    """Execute migration test cases in a controlled sandbox environment.

    Usage:
        runner = MigrationTestRunner(source_db="mssql", target_db="kingbasees")
        result = runner.run_all()  # Run all predefined test cases
        result = runner.run_by_tags(["smoke"])  # Run smoke tests only
        result = runner.run_by_ids(["schema_row_counts", "sql_select_all_customers"])
    """

    def __init__(self, source_db: str, target_db: str):
        """
        Args:
            source_db: Source database type (mssql / kingbasees / dm8)
            target_db: Target database type (mssql / kingbasees / dm8)
        """
        self.source_db = source_db
        self.target_db = target_db

    # =========================================================================
    # Public API
    # =========================================================================

    def run_all(self, test_cases: list[MigrationTestCase] | None = None) -> RunnerResult:
        """Run all test cases.

        Args:
            test_cases: Test cases to run (defaults to all predefined cases)

        Returns:
            RunnerResult with seed results, test results, and report.
        """
        if test_cases is None:
            test_cases = get_all_test_cases()
        return self._run_pipeline(test_cases)

    def run_by_tags(self, tags: list[str]) -> RunnerResult:
        """Run test cases matching specified tags."""
        all_cases = get_all_test_cases()
        filtered = [
            tc for tc in all_cases
            if any(tag in tc.tags for tag in tags)
        ]
        return self._run_pipeline(filtered)

    def run_by_ids(self, test_ids: list[str]) -> RunnerResult:
        """Run specific test cases by ID."""
        all_cases = get_all_test_cases()
        id_set = set(test_ids)
        filtered = [tc for tc in all_cases if tc.id in id_set]
        return self._run_pipeline(filtered)

    def run_by_categories(self, categories: list[str]) -> RunnerResult:
        """Run test cases by category."""
        all_cases = get_all_test_cases()
        cat_set = set(categories)
        filtered = [tc for tc in all_cases if tc.category in cat_set]
        return self._run_pipeline(filtered)

    def reset_only(self) -> dict[str, SeedResult]:
        """Reset both databases without running tests."""
        return SandboxSeeder.reset_both(self.source_db, self.target_db)

    # =========================================================================
    # Pipeline
    # =========================================================================

    def _run_pipeline(self, test_cases: list[MigrationTestCase]) -> RunnerResult:
        """Execute the full test pipeline.

        1. Reset + Reseed both databases
        2. Execute each test case (SQL on source + target)
        3. Diff results
        4. Build report
        """
        overall_start = time.perf_counter()

        # ---- Step 1: Reset + Reseed ----
        seed_results = SandboxSeeder.reset_both(self.source_db, self.target_db)

        # Check if seeding succeeded
        source_seed = seed_results.get(self.source_db)
        target_seed = seed_results.get(self.target_db)

        if source_seed and not source_seed.success:
            # Source seed failed — mark all tests as ERROR
            test_results = [
                TestCaseResult(
                    test_id=tc.id,
                    test_name=tc.name,
                    category=tc.category,
                    status="ERROR",
                    source_db=self.source_db,
                    target_db=self.target_db,
                    error_message=f"Source seed failed: {source_seed.error}",
                )
                for tc in test_cases
            ]
            elapsed = round((time.perf_counter() - overall_start) * 1000, 1)
            report = ReportBuilder.build(test_results, self.source_db, self.target_db)
            return RunnerResult(
                source_db=self.source_db,
                target_db=self.target_db,
                seed_results={k: {"success": v.success, "error": v.error} for k, v in seed_results.items()},
                test_results=test_results,
                report=report,
                total_time_ms=elapsed,
            )

        if target_seed and not target_seed.success:
            test_results = [
                TestCaseResult(
                    test_id=tc.id,
                    test_name=tc.name,
                    category=tc.category,
                    status="ERROR",
                    source_db=self.source_db,
                    target_db=self.target_db,
                    error_message=f"Target seed failed: {target_seed.error}",
                )
                for tc in test_cases
            ]
            elapsed = round((time.perf_counter() - overall_start) * 1000, 1)
            report = ReportBuilder.build(test_results, self.source_db, self.target_db)
            return RunnerResult(
                source_db=self.source_db,
                target_db=self.target_db,
                seed_results={k: {"success": v.success, "error": v.error} for k, v in seed_results.items()},
                test_results=test_results,
                report=report,
                total_time_ms=elapsed,
            )

        # ---- Step 2 & 3: Execute + Diff each test case ----
        test_results: list[TestCaseResult] = []
        for tc in test_cases:
            result = self._execute_single_test(tc)
            test_results.append(result)

        # ---- Step 4: Build Report ----
        elapsed = round((time.perf_counter() - overall_start) * 1000, 1)
        seed_summary = {
            k: {
                "success": v.success,
                "tables_seeded": v.tables_seeded,
                "error": v.error,
                "elapsed_ms": v.elapsed_ms,
            }
            for k, v in seed_results.items()
        }

        report = ReportBuilder.build(
            test_results, self.source_db, self.target_db, seed_summary,
        )

        # ---- Step 5: Certification Analysis (replaces old Risk Intelligence) ----
        try:
            from app.sandbox.certification.engine import CertificationEngine
            from app.sandbox.risk.engine import _from_cert_report

            cert_engine = CertificationEngine(self.source_db, self.target_db)
            cert_report = cert_engine.certify(test_results, test_cases)

            # Convert to old RiskIntelligenceReport format (delegates to shared converter)
            risk_report = _from_cert_report(cert_report, test_results)

            # Enrich report with both old risk fields AND new certification
            report = TestReport(
                source_db=report.source_db,
                target_db=report.target_db,
                total_tests=report.total_tests,
                passed=report.passed,
                failed=report.failed,
                errors=report.errors,
                skipped=report.skipped,
                success_rate=report.success_rate,
                total_time_ms=report.total_time_ms,
                results=report.results,
                seed_results=report.seed_results,
                summary_by_category=report.summary_by_category,
                # Old risk fields (backward compat — from shared converter)
                risk_score=risk_report.risk_score,
                confidence_score=risk_report.confidence_score,
                coverage_report=risk_report.coverage_report,
                critical_issues=risk_report.critical_issues,
                migration_readiness=risk_report.migration_readiness,
                top_risks=risk_report.top_risks,
                # NEW certification report (primary for new consumers)
                certification_report=cert_report,
            )
        except Exception as exc:
            # Certification is best-effort; don't fail the pipeline
            import logging
            _log = logging.getLogger(__name__)
            _log.warning("Certification analysis skipped: %s: %s", type(exc).__name__, exc)

        return RunnerResult(
            source_db=self.source_db,
            target_db=self.target_db,
            seed_results=seed_summary,
            test_results=test_results,
            report=report,
            total_time_ms=elapsed,
        )

    def _execute_single_test(self, tc: MigrationTestCase) -> TestCaseResult:
        """Execute a single test case against both databases."""
        test_start = time.perf_counter()

        try:
            sql = tc.source_sql or ""
            target_sql = tc.target_sql or sql

            # Attempt to rewrite SQL for target DB
            rewritten_sql = target_sql
            rewrite_applied = False
            if self.source_db != self.target_db and not tc.target_sql:
                try:
                    from app.api.sql_compare.rewrite.engine import rewrite_sql as do_rewrite

                    rewrite_result = do_rewrite(
                        sql=sql,
                        source_db=self.source_db,
                        target_db=self.target_db,
                    )
                    if rewrite_result.rewritten_sql:
                        rewritten_sql = rewrite_result.rewritten_sql
                        rewrite_applied = True
                except Exception:
                    pass  # Rewrite is best-effort; fall back to original

            # Execute on source DB
            src_result = _execute_sql(self.source_db, sql)
            src_time = src_result.get("execution_time_ms", 0)

            # Execute on target DB
            tgt_result = _execute_sql(self.target_db, rewritten_sql)
            tgt_time = tgt_result.get("execution_time_ms", 0)

            # Deterministic diff
            diff = DiffEngine.compare(
                src_result,
                tgt_result,
                tolerance=tc.tolerance,
                ignore_fields=tc.ignore_fields,
                check_fields=tc.check_fields,
            )

            # Enhanced 3-layer diff (via existing explanation engine)
            enhanced_diff = None
            if diff.status != "MATCH":
                try:
                    from app.api.sql_demo.explanation_engine import compute_enhanced_diff

                    results_map = {
                        self.source_db: src_result,
                        self.target_db: tgt_result,
                    }
                    enhanced = compute_enhanced_diff(
                        results=results_map,
                        original_sql=sql,
                        rewritten_sql=rewritten_sql if rewrite_applied else "",
                    )
                    enhanced_diff = enhanced.get("three_layer_diff")
                except Exception:
                    pass

            # Determine test status
            if diff.status == "ERROR":
                status = "ERROR"
            elif diff.status == "MATCH":
                status = "PASS"
            elif tc.expected_status == "CONDITIONAL":
                status = "PASS"  # Known differences are acceptable
            elif tc.known_issues:
                status = "FAIL"  # Known issues, but still fail for visibility
                if diff.data_match and diff.column_match:
                    status = "PASS"  # Only row count differs, might be known
            else:
                status = "FAIL"

            # Compute individual test risk score (0-100)
            test_risk = 0.0
            if status == "ERROR":
                test_risk = 90.0
            elif status == "FAIL":
                if not diff.column_match or not diff.row_count_match:
                    test_risk = 70.0
                elif not diff.data_match:
                    # Risk proportional to number of diffs
                    diff_count = len(diff.field_diffs)
                    test_risk = min(80, 40 + diff_count * 5)
                else:
                    test_risk = 30.0
            elif status == "PASS" and tc.known_issues:
                test_risk = 20.0  # Passed but has known concerns
            # else: PASS with no issues = 0 risk

            elapsed = round((time.perf_counter() - test_start) * 1000, 1)

            # Build diff_detail for API compatibility
            diff_detail = []
            for fd in diff.field_diffs:
                diff_detail.append({
                    "field": fd.field_name,
                    "source": str(fd.source_value),
                    "target": str(fd.target_value),
                    "category": fd.category,
                })

            return TestCaseResult(
                test_id=tc.id,
                test_name=tc.name,
                category=tc.category,
                status=status,
                source_db=self.source_db,
                target_db=self.target_db,
                source_execution_time_ms=src_time,
                target_execution_time_ms=tgt_time,
                total_time_ms=elapsed,
                row_count_match=diff.row_count_match,
                data_match=diff.data_match,
                column_match=diff.column_match,
                diff_summary=diff.explanation,
                error_message=src_result.get("error") or tgt_result.get("error"),
                known_issues=list(tc.known_issues),
                diff_detail=diff_detail,
                enhanced_diff=enhanced_diff,
                risk_score=test_risk,
            )

        except Exception as exc:
            elapsed = round((time.perf_counter() - test_start) * 1000, 1)
            return TestCaseResult(
                test_id=tc.id,
                test_name=tc.name,
                category=tc.category,
                status="ERROR",
                source_db=self.source_db,
                target_db=self.target_db,
                total_time_ms=elapsed,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    # =========================================================================
    # SQL Execution Helpers
    # =========================================================================

    # (helpers below)


# =========================================================================
# Confidence helper functions (used by runner and certification engine)
# =========================================================================


def _classify_new_confidence(score: float) -> str:
    """Map new confidence score to old level labels for backward compat."""
    if score >= 80:
        return "HIGH"
    elif score >= 60:
        return "MEDIUM"
    elif score >= 40:
        return "LOW"
    else:
        return "INSUFFICIENT"


def _confidence_recommendation(status: str) -> str:
    """Generate a human-readable recommendation from migration status."""
    if status == "READY":
        return "迁移风险可控，建议按计划执行。"
    elif status == "REVIEW_REQUIRED":
        return "存在需关注的问题，建议审查失败详情后分批迁移。"
    else:
        return "风险过高，需要先解决关键问题后再评估。"


def _execute_sql(db_type: str, sql: str) -> dict[str, Any]:
    """Execute SQL on a specific database type.

    Uses the existing execute_sql function from the service layer,
    which handles security validation, driver selection, and timing.
    """
    try:
        from app.api.sql_demo.service import execute_sql

        return execute_sql(db_type=db_type, sql=sql, skip_validation=True)
    except Exception as exc:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "db_type": db_type,
            "execution_time_ms": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "suggestion": "检查数据库连接和 SQL 语法",
        }
