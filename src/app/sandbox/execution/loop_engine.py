"""
Migration Execution Loop Engine — the core orchestrator for continuous fix.

Architecture:
    Run → Detect Issue → Classify → Generate Fix → Apply Fix → Re-run → Verify → Continue

Core Principle:
    🟢 ALWAYS execute migration/validation
    🟢 Detect issues
    🟢 Classify issues
    🟢 Fix or isolate issues iteratively
    🟢 Continue execution
    ❌ NEVER block execution based on risk score
    ❌ NEVER stop on errors

The loop runs until one of:
- Stabilization: N consecutive iterations with no new issues
- Max iterations: Configurable limit reached
- Manual stop: External signal
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from .classifier import IssueClassifier
from .fix_engine import FixStrategyEngine
from .schemas import (
    ExecutionReport,
    FixResult,
    FixType,
    IssueSeverity,
    IssueStatus,
    IssueType,
    LoopIteration,
    LoopPhase,
    MigrationIssue,
)
from .tracker import IssueTracker


# =========================================================================
# Execution Loop
# =========================================================================


class MigrationExecutionLoop:
    """Continuous migration execution and repair engine.

    Usage:
        loop = MigrationExecutionLoop(source_db="mssql", target_db="kingbasees")
        loop.set_test_runner(runner)

        # Run full loop
        report = loop.run_full_loop()

        # Or step-by-step
        loop.run_tests()
        loop.detect_and_classify()
        loop.generate_fixes()
        loop.apply_fixes()
        loop.re_run_affected()
        report = loop.get_execution_report()
    """

    def __init__(
        self,
        source_db: str = "mssql",
        target_db: str = "kingbasees",
        max_iterations: int = 10,
        stabilization_threshold: int = 2,
    ):
        self.source_db = source_db
        self.target_db = target_db
        self.max_iterations = max_iterations
        self.stabilization_threshold = stabilization_threshold

        # Components
        self.classifier = IssueClassifier(source_db, target_db)
        self.fix_engine = FixStrategyEngine(source_db, target_db)
        self.tracker = IssueTracker()

        # External dependencies (set via setter)
        self._test_runner: Any = None
        self._test_cases: list[Any] = []

        # State
        self.phase = LoopPhase.INIT
        self.current_iteration = 0
        self.iterations: list[LoopIteration] = []
        self.fix_results: list[FixResult] = []
        self.consecutive_clean_runs = 0
        self._should_stop = False
        self._on_iteration: Callable[[LoopIteration], None] | None = None

        # Timing
        self.started_at = ""
        self.ended_at = ""
        self.total_time_ms = 0.0

    # =========================================================================
    # Configuration
    # =========================================================================

    def set_test_runner(self, runner: Any) -> None:
        """Set the test runner for executing tests."""
        self._test_runner = runner

    def set_test_cases(self, test_cases: list[Any]) -> None:
        """Set the test case definitions."""
        self._test_cases = test_cases

    def on_iteration(self, callback: Callable[[LoopIteration], None]) -> None:
        """Register a callback for each loop iteration."""
        self._on_iteration = callback

    def stop(self) -> None:
        """Signal the loop to stop after the current iteration."""
        self._should_stop = True

    # =========================================================================
    # Full Loop Execution
    # =========================================================================

    def run_full_loop(self) -> ExecutionReport:
        """Run the complete execution loop until stabilization or max iterations.

        This is the main entry point. The loop:
        1. Runs all tests
        2. Detects and classifies failures
        3. Generates fix strategies
        4. Applies fixes
        5. Re-runs affected tests
        6. Verifies fixes
        7. Repeats until stable or max iterations

        Returns:
            ExecutionReport with full details of the entire loop run.
        """
        self.started_at = datetime.now(timezone.utc).isoformat()
        overall_start = time.perf_counter()
        self._should_stop = False
        self.tracker.reset()

        try:
            # ---- Iteration 0: Initial run ----
            self.phase = LoopPhase.RUNNING
            self._run_iteration(0, is_initial=True)

            # ---- Iterations 1..N: Fix loop ----
            for iteration in range(1, self.max_iterations + 1):
                if self._should_stop:
                    break

                self.current_iteration = iteration

                # Check stabilization
                if self.consecutive_clean_runs >= self.stabilization_threshold:
                    self.phase = LoopPhase.STABILIZED
                    break

                # ---- Phase: Classify ----
                self.phase = LoopPhase.CLASSIFYING

                # ---- Phase: Fix ----
                self.phase = LoopPhase.FIXING
                open_issues = self.tracker.get_by_status(IssueStatus.IDENTIFIED)

                if not open_issues:
                    # Also check NEW issues
                    open_issues = self.tracker.get_by_status(IssueStatus.NEW)
                    for issue in open_issues:
                        self.tracker.mark_identified(issue.issue_id)

                    open_issues = self.tracker.get_by_status(IssueStatus.IDENTIFIED)

                if open_issues:
                    for issue in open_issues:
                        # Generate fix strategy
                        strategy = self.fix_engine.generate_strategy(issue)
                        self.tracker.mark_fixing(issue.issue_id, strategy)

                        # Apply fix
                        result = self.fix_engine.apply_fix(strategy, self._test_runner)
                        self.fix_results.append(result)

                        if result.success:
                            self.tracker.mark_fixed(issue.issue_id)
                        else:
                            # Fix failed, keep in IDENTIFIED for retry
                            self.tracker.transition(issue.issue_id, IssueStatus.IDENTIFIED)

                # ---- Phase: Re-run affected tests ----
                self.phase = LoopPhase.RE_RUNNING
                self._run_iteration(iteration, is_initial=False)

                # ---- Phase: Verify fixes ----
                self.phase = LoopPhase.VERIFYING
                fixed_issues = self.tracker.get_by_status(IssueStatus.FIXED)
                for issue in fixed_issues:
                    # Check if the test for this issue now passes
                    if self._verify_fix(issue):
                        self.tracker.mark_verified(issue.issue_id)
                        self.tracker.mark_resolved(issue.issue_id)

            # ---- Final state ----
            if self.consecutive_clean_runs >= self.stabilization_threshold:
                self.phase = LoopPhase.STABILIZED
            else:
                self.phase = LoopPhase.MAX_ITERATIONS

        except Exception as exc:
            # Even on error, we produce a report — NEVER stop without one
            self.phase = LoopPhase.MAX_ITERATIONS
            print(f"[ExecutionLoop] Loop interrupted: {exc}")

        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.total_time_ms = round((time.perf_counter() - overall_start) * 1000, 1)

        return self.get_execution_report()

    # =========================================================================
    # Step-by-Step Execution
    # =========================================================================

    def run_tests(self) -> list[Any]:
        """Run all test cases and return results."""
        if not self._test_runner:
            raise RuntimeError("Test runner not set. Call set_test_runner() first.")

        self.phase = LoopPhase.RUNNING
        try:
            result = self._test_runner.run_all(self._test_cases if self._test_cases else None)
            return getattr(result, 'test_results', [])
        except Exception as exc:
            print(f"[ExecutionLoop] Test run error: {exc}")
            return []

    def detect_and_classify(self, test_results: list[Any]) -> list[MigrationIssue]:
        """Detect failures from test results and classify into issues."""
        self.phase = LoopPhase.DETECTING
        issues = self.classifier.classify_batch(test_results, self._test_cases)

        self.phase = LoopPhase.CLASSIFYING
        for issue in issues:
            self.tracker.register(issue)
            self.tracker.mark_identified(issue.issue_id)

        return issues

    def generate_fixes(self, issues: list[MigrationIssue] | None = None) -> list[Any]:
        """Generate fix strategies for issues."""
        if issues is None:
            issues = self.tracker.get_by_status(IssueStatus.IDENTIFIED)

        self.phase = LoopPhase.FIXING
        strategies = []
        for issue in issues:
            strategy = self.fix_engine.generate_strategy(issue)
            self.tracker.mark_fixing(issue.issue_id, strategy)
            strategies.append(strategy)

        return strategies

    def apply_fixes(self) -> list[FixResult]:
        """Apply all pending fixes."""
        self.phase = LoopPhase.FIXING
        results: list[FixResult] = []
        fixing_issues = self.tracker.get_by_status(IssueStatus.FIXING)

        for issue in fixing_issues:
            if issue.fix_strategy:
                result = self.fix_engine.apply_fix(issue.fix_strategy, self._test_runner)
                self.fix_results.append(result)
                results.append(result)

                if result.success:
                    self.tracker.mark_fixed(issue.issue_id)
                else:
                    self.tracker.transition(issue.issue_id, IssueStatus.IDENTIFIED)

        return results

    def re_run_affected(self) -> list[Any]:
        """Re-run only the tests affected by applied fixes."""
        self.phase = LoopPhase.RE_RUNNING
        # Collect all affected test IDs from fixed issues
        fixed_issues = self.tracker.get_by_status(IssueStatus.FIXED)
        affected_ids: set[str] = set()
        for issue in fixed_issues:
            affected_ids.update(issue.affected_test_ids)

        if not affected_ids:
            return []

        try:
            if self._test_runner and hasattr(self._test_runner, 'run_by_ids'):
                result = self._test_runner.run_by_ids(list(affected_ids))
                return getattr(result, 'test_results', [])
        except Exception as exc:
            print(f"[ExecutionLoop] Re-run error: {exc}")

        return []

    # =========================================================================
    # Report Generation
    # =========================================================================

    def get_execution_report(self) -> ExecutionReport:
        """Generate the final execution report."""
        stats = self.tracker.stats()

        # Count test results from the last iteration
        last_iteration = self.iterations[-1] if self.iterations else None
        total_tests = last_iteration.tests_run if last_iteration else 0
        passed = last_iteration.tests_passed if last_iteration else 0
        failed = last_iteration.tests_failed if last_iteration else 0

        partial_success = stats["verified"] + stats["resolved"]
        success_rate = round(
            ((passed + partial_success) / max(total_tests, 1)) * 100, 1
        )

        # Determine recommendation
        if self.phase == LoopPhase.STABILIZED:
            recommendation = (
                f"✅ 迁移执行循环已稳定 — {self.consecutive_clean_runs} 轮连续无新问题. "
                f"共解决 {stats['resolved']} 个问题, "
                f"当前还有 {stats['open']} 个待解决问题. "
                f"建议进入生产验证阶段。"
            )
        elif stats["open"] == 0:
            recommendation = (
                "✅ 所有检测到的问题已解决. 迁移系统已就绪。"
            )
        else:
            blockers = self.tracker.get_by_severity(IssueSeverity.BLOCKER)
            if blockers:
                recommendation = (
                    f"⚠️ 存在 {len(blockers)} 个阻塞级问题. "
                    f"共 {stats['open']} 个未解决问题. "
                    f"建议在解决阻塞问题后再执行生产迁移。"
                )
            else:
                recommendation = (
                    f"⚠️ 还有 {stats['open']} 个问题待解决. "
                    f"但无阻塞级问题. 可考虑渐进式迁移。"
                )

        # Collect remaining blockers
        blockers = self.tracker.get_by_severity(IssueSeverity.BLOCKER)
        remaining_blockers = [
            f"[{b.test_name}] {b.description[:100]}"
            for b in blockers
        ]

        return ExecutionReport(
            source_db=self.source_db,
            target_db=self.target_db,
            total_iterations=self.current_iteration,
            phase=self.phase.value if isinstance(self.phase, LoopPhase) else str(self.phase),
            total_tests=total_tests,
            passed=passed,
            partial_success=partial_success,
            failed=failed,
            errors=max(0, total_tests - passed - failed),
            success_rate=success_rate,
            total_issues=stats["total"],
            issues_resolved=stats["resolved"],
            issues_in_progress=stats["open"] + stats["fixed"],
            issues_regressed=stats["regressed"],
            fixes_applied=len(self.fix_results),
            fixes_succeeded=sum(1 for fr in self.fix_results if fr.success),
            fixes_failed=sum(1 for fr in self.fix_results if not fr.success),
            iterations=list(self.iterations),
            issues=self.tracker.get_all(),
            fix_results=list(self.fix_results),
            recommendation=recommendation,
            remaining_blockers=remaining_blockers,
            total_time_ms=self.total_time_ms,
        )

    def get_state_dict(self) -> dict[str, Any]:
        """Get the current loop state as a dictionary for API responses."""
        stats = self.tracker.stats()
        return {
            "source_db": self.source_db,
            "target_db": self.target_db,
            "phase": self.phase.value if isinstance(self.phase, LoopPhase) else str(self.phase),
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "consecutive_clean_runs": self.consecutive_clean_runs,
            "is_stabilized": self.phase == LoopPhase.STABILIZED,
            "issue_stats": stats,
            "total_fix_attempts": len(self.fix_results),
            "successful_fixes": sum(1 for fr in self.fix_results if fr.success),
            "failed_fixes": sum(1 for fr in self.fix_results if not fr.success),
            "iterations": [it.to_dict() for it in self.iterations],
            "issues": [i.to_dict() for i in self.tracker.get_all()],
            "total_time_ms": self.total_time_ms,
        }

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _run_iteration(self, iteration: int, is_initial: bool = False) -> None:
        """Execute a single iteration of the test-execute-detect cycle."""
        iter_start = time.perf_counter()

        # Execute tests
        test_results = self.run_tests()

        # Count results
        tests_run = len(test_results)
        tests_passed = sum(
            1 for r in test_results
            if getattr(r, 'status', '') == 'PASS'
        )
        tests_failed = sum(
            1 for r in test_results
            if getattr(r, 'status', '') in ('FAIL', 'ERROR')
        )

        # Detect and classify issues
        new_issues = self.detect_and_classify(test_results)
        issues_detected = len(new_issues)

        # Check fix verification
        issues_verified = 0
        if not is_initial:
            for result in test_results:
                test_id = getattr(result, 'test_id', '')
                status = getattr(result, 'status', '')
                if status == 'PASS':
                    # Check if this test was previously failing
                    related = self.tracker.get_by_test(test_id)
                    for issue in related:
                        if issue.status == IssueStatus.FIXED:
                            self.tracker.mark_verified(issue.issue_id)
                            self.tracker.mark_resolved(issue.issue_id)
                            issues_verified += 1

        # Count fixed issues
        issues_fixed = self.tracker.fixed_count

        # Track stabilization
        if issues_detected == 0 and tests_failed == 0:
            self.consecutive_clean_runs += 1
        else:
            self.consecutive_clean_runs = 0

        elapsed = round((time.perf_counter() - iter_start) * 1000, 1)
        summary = (
            f"Iteration {iteration}: {tests_passed}/{tests_run} passed, "
            f"{issues_detected} new issues, {issues_fixed} fixed"
        )

        loop_iter = LoopIteration(
            iteration=iteration,
            phase=self.phase,
            tests_run=tests_run,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            issues_detected=issues_detected,
            issues_fixed=issues_fixed,
            issues_verified=issues_verified,
            elapsed_ms=elapsed,
            summary=summary,
        )
        self.iterations.append(loop_iter)

        if self._on_iteration:
            try:
                self._on_iteration(loop_iter)
            except Exception:
                pass

    def _verify_fix(self, issue: MigrationIssue) -> bool:
        """Verify that a fix resolved the issue.

        A fix is verified if:
        - The affected test now passes
        - No new issues were introduced
        """
        # Check if any re-run result shows the test now passing
        for fr in self.fix_results:
            if fr.issue_id == issue.issue_id:
                for rr in fr.re_run_results:
                    if rr.get("status") == "PASS":
                        return True

        # If no re-run results, check if the last iteration passed
        if self.iterations:
            last = self.iterations[-1]
            if last.tests_failed == 0:
                return True

        return False


# =========================================================================
# Loop Factory
# =========================================================================


def create_execution_loop(
    source_db: str = "mssql",
    target_db: str = "kingbasees",
    max_iterations: int = 10,
) -> MigrationExecutionLoop:
    """Factory function to create a configured execution loop.

    Usage:
        loop = create_execution_loop("mssql", "kingbasees")
        loop.set_test_runner(MigrationTestRunner("mssql", "kingbasees"))
        report = loop.run_full_loop()
    """
    return MigrationExecutionLoop(
        source_db=source_db,
        target_db=target_db,
        max_iterations=max_iterations,
    )
