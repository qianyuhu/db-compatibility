"""
Migration Sandbox Test Harness API.

Endpoints:
    POST /api/migration/test/run    — Run test cases
    POST /api/migration/test/reset  — Reset sandbox data
    GET  /api/migration/test/report — Get latest report summary
    GET  /api/migration/test/cases  — List available test cases
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from app.sandbox.runner import MigrationTestRunner
from app.sandbox.seeder import SandboxSeeder
from app.sandbox.test_case import get_all_test_cases
from app.sandbox.risk.engine import MigrationRiskEngine, RiskQuickAnalyzer
from app.sandbox.risk.coverage import CoverageAnalyzer
from app.sandbox.execution.loop_engine import MigrationExecutionLoop, create_execution_loop
from app.sandbox.execution.fix_engine import FixStrategyEngine
from app.sandbox.execution.classifier import IssueClassifier
from app.sandbox.execution.tracker import IssueTracker

router = APIRouter(prefix="/api/migration/test", tags=["migration-test"])

# In-memory cache of the latest report (cleared on server restart)
_latest_report: Optional[dict[str, Any]] = None

# Execution loop instance (created on first use)
_execution_loop: Optional[MigrationExecutionLoop] = None
_fix_engine: Optional[FixStrategyEngine] = None
_issue_tracker: Optional[IssueTracker] = None


def _get_loop(source_db: str = "mssql", target_db: str = "kingbasees") -> MigrationExecutionLoop:
    """Get or create the execution loop instance."""
    global _execution_loop, _fix_engine, _issue_tracker
    if _execution_loop is None:
        _execution_loop = create_execution_loop(source_db, target_db)
        # Wire up the test runner
        runner = MigrationTestRunner(source_db=source_db, target_db=target_db)
        _execution_loop.set_test_runner(runner)
        _execution_loop.set_test_cases(get_all_test_cases())
    if _fix_engine is None:
        _fix_engine = FixStrategyEngine(source_db, target_db)
    if _issue_tracker is None:
        _issue_tracker = IssueTracker()
    return _execution_loop


# =========================================================================
# POST /run
# =========================================================================


@router.post("/run")
async def run_tests(
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
    test_ids: Optional[str] = Query(default=None, description="Comma-separated test IDs"),
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    categories: Optional[str] = Query(default=None, description="Comma-separated categories"),
):
    """Run migration sandbox tests.

    Query Parameters:
        source_db: Source database (default: mssql)
        target_db: Target database (default: kingbasees)
        test_ids: Comma-separated test IDs to run (e.g. "schema_row_counts,sql_select_all_customers")
        tags: Comma-separated tags filter (e.g. "smoke,crud")
        categories: Comma-separated category filter (e.g. "schema,sql_crud")

    Returns:
        Full test report with per-test results, diffs, and summary.
    """
    global _latest_report

    runner = MigrationTestRunner(source_db=source_db, target_db=target_db)

    # Determine which test cases to run
    if test_ids:
        ids_list = [tid.strip() for tid in test_ids.split(",") if tid.strip()]
        result = runner.run_by_ids(ids_list)
    elif tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        result = runner.run_by_tags(tags_list)
    elif categories:
        cats_list = [c.strip() for c in categories.split(",") if c.strip()]
        result = runner.run_by_categories(cats_list)
    else:
        result = runner.run_all()

    report_dict = result.report.to_dict() if result.report else {}

    response = {
        "source_db": result.source_db,
        "target_db": result.target_db,
        "seed_results": result.seed_results,
        "report": report_dict,
        "total_time_ms": result.total_time_ms,
    }

    # Cache for /report endpoint
    _latest_report = response

    return response


# =========================================================================
# POST /reset
# =========================================================================


@router.post("/reset")
async def reset_sandbox(
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
):
    """Reset and reseed sandbox data on both databases.

    Truncates all tables and inserts the fixed deterministic dataset.
    """
    seed_results = SandboxSeeder.reset_both(source_db, target_db)

    return {
        "source_db": source_db,
        "target_db": target_db,
        "seed_results": {
            db: {
                "success": r.success,
                "tables_seeded": r.tables_seeded,
                "error": r.error,
                "elapsed_ms": r.elapsed_ms,
            }
            for db, r in seed_results.items()
        },
    }


# =========================================================================
# GET /report
# =========================================================================


@router.get("/report")
async def get_report():
    """Get the latest test report (from in-memory cache).

    Returns None if no tests have been run yet.
    """
    global _latest_report
    if _latest_report is None:
        return {
            "available": False,
            "message": "尚未运行测试。请先调用 POST /api/migration/test/run",
        }
    return {"available": True, "report": _latest_report}


# =========================================================================
# GET /cases
# =========================================================================


@router.get("/cases")
async def list_test_cases():
    """List all available test cases with metadata."""
    cases = get_all_test_cases()
    return {
        "total": len(cases),
        "cases": [
            {
                "id": tc.id,
                "name": tc.name,
                "category": tc.category,
                "description": tc.description,
                "expected_status": tc.expected_status,
                "tags": tc.tags,
                "risk_tags": tc.risk_tags,
                "known_issues": tc.known_issues,
            }
            for tc in cases
        ],
    }


# =========================================================================
# Risk Intelligence Endpoints
# =========================================================================


@router.get("/risk/analyze")
async def analyze_risk(
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
):
    """Run risk intelligence analysis on the latest test results.

    If tests have been run, uses cached results. Otherwise, runs all tests
    and then performs risk analysis.
    """
    global _latest_report

    # Try to use cached results first
    if _latest_report and _latest_report.get("report"):
        report_data = _latest_report["report"]
        # Check if risk data is already present
        if report_data.get("risk_score") and report_data.get("confidence_score"):
            return {
                "source": "cache",
                "risk_score": report_data["risk_score"],
                "confidence_score": report_data["confidence_score"],
                "coverage_report": report_data.get("coverage_report"),
                "critical_issues": report_data.get("critical_issues"),
                "migration_readiness": report_data.get("migration_readiness"),
                "top_risks": report_data.get("top_risks"),
            }

    # Run tests + risk analysis
    runner = MigrationTestRunner(source_db=source_db, target_db=target_db)
    result = runner.run_all()

    report_dict = result.report.to_dict() if result.report else {}
    _latest_report = {
        "source_db": result.source_db,
        "target_db": result.target_db,
        "seed_results": result.seed_results,
        "report": report_dict,
        "total_time_ms": result.total_time_ms,
    }

    return {
        "source": "fresh_run",
        "risk_score": report_dict.get("risk_score"),
        "confidence_score": report_dict.get("confidence_score"),
        "coverage_report": report_dict.get("coverage_report"),
        "critical_issues": report_dict.get("critical_issues"),
        "migration_readiness": report_dict.get("migration_readiness"),
        "top_risks": report_dict.get("top_risks"),
        "total_time_ms": result.total_time_ms,
    }


@router.get("/risk/preflight")
async def preflight_risk(
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
):
    """Pre-flight risk analysis based on test definitions only (no DB access)."""
    result = RiskQuickAnalyzer.preflight(
        source_db=source_db,
        target_db=target_db,
    )
    return result


@router.get("/risk/coverage")
async def coverage_analysis():
    """Get coverage analysis for all test cases."""
    cases = get_all_test_cases()
    coverage = CoverageAnalyzer.analyze(cases)
    return coverage.to_dict()


# =========================================================================
# Execution Loop Endpoints (Phase 3)
# =========================================================================


@router.post("/exec/start")
async def start_execution_loop(
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
    max_iterations: int = Query(default=10, ge=1, le=50, description="最大循环迭代次数"),
):
    """Start the continuous execution & fix loop.

    The loop will:
    1. Run all tests
    2. Detect and classify failures
    3. Generate fix strategies for each issue
    4. Apply fixes
    5. Re-run affected tests
    6. Repeat until stable or max iterations reached

    This endpoint starts the loop asynchronously and returns immediately.
    Use GET /exec/state to monitor progress.
    """
    global _execution_loop, _fix_engine, _issue_tracker

    # Reset and create fresh loop
    _issue_tracker = IssueTracker()
    _execution_loop = create_execution_loop(source_db, target_db, max_iterations)
    _fix_engine = FixStrategyEngine(source_db, target_db)

    runner = MigrationTestRunner(source_db=source_db, target_db=target_db)
    _execution_loop.set_test_runner(runner)
    _execution_loop.set_test_cases(get_all_test_cases())

    # Run the full loop synchronously (for simplicity — could be background task)
    try:
        report = _execution_loop.run_full_loop()
        return {
            "success": True,
            "message": "执行循环完成",
            "report": report.to_dict(),
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"执行循环出错: {exc}",
            "state": _execution_loop.get_state_dict(),
        }


@router.get("/exec/state")
async def get_execution_state():
    """Get the current state of the execution loop.

    Returns:
        - Current phase (INIT / RUNNING / FIXING / STABILIZED, etc.)
        - Iteration count
        - Issue statistics (total, open, fixed, verified, resolved, regressed)
        - Latest iteration details
        - Fix attempt counts
    """
    global _execution_loop, _issue_tracker

    if _execution_loop is None:
        return {
            "available": False,
            "message": "执行循环尚未启动。请先调用 POST /api/migration/test/exec/start",
        }

    return {
        "available": True,
        "state": _execution_loop.get_state_dict(),
    }


@router.post("/exec/fix")
async def apply_single_fix(
    issue_id: str = Query(..., description="要修复的 issue ID"),
    source_db: str = Query(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$"),
    target_db: str = Query(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$"),
):
    """Manually apply a fix for a single issue.

    Useful for one-off fixes outside the full loop execution.
    Re-runs affected tests after applying the fix.
    """
    global _execution_loop, _fix_engine, _issue_tracker

    loop = _get_loop(source_db, target_db)

    # Find the issue
    issue = _issue_tracker.get(issue_id) if _issue_tracker else None
    if issue is None:
        return {
            "success": False,
            "message": f"Issue 未找到: {issue_id}",
        }

    # Transition to FIXING
    _issue_tracker.mark_identified(issue_id)

    # Generate and apply fix
    strategy = _fix_engine.generate_strategy(issue)
    _issue_tracker.mark_fixing(issue_id, strategy)

    result = _fix_engine.apply_fix(strategy, loop._test_runner)

    if result.success:
        _issue_tracker.mark_fixed(issue_id)
    else:
        _issue_tracker.transition(issue_id, "IDENTIFIED")

    return {
        "success": result.success,
        "message": result.message,
        "fix_result": result.to_dict(),
        "issue": _issue_tracker.get(issue_id).to_dict() if _issue_tracker.get(issue_id) else None,
    }


@router.get("/exec/report")
async def get_execution_report():
    """Get the full execution report from the last loop run.

    Includes:
        - Executive summary
        - Test results (with partial_success status)
        - Issue summary with lifecycle states
        - Fix summary (applied, succeeded, failed)
        - Per-iteration details
        - Recommendations and remaining blockers
    """
    global _execution_loop

    if _execution_loop is None or not _execution_loop.iterations:
        return {
            "available": False,
            "message": "尚未运行执行循环。请先调用 POST /api/migration/test/exec/start",
        }

    report = _execution_loop.get_execution_report()
    return {
        "available": True,
        "report": report.to_dict(),
    }


@router.post("/exec/reset")
async def reset_execution_loop():
    """Reset the execution loop state.

    Clears all tracked issues, fix results, and iteration history.
    """
    global _execution_loop, _fix_engine, _issue_tracker
    _execution_loop = None
    _fix_engine = None
    _issue_tracker = None
    return {
        "success": True,
        "message": "执行循环状态已重置",
    }
