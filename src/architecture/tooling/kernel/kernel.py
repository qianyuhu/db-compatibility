"""
SQL Kernel — single orchestrator for all SQL intelligence engines.

Usage:
    from architecture.tooling.kernel import SQLKernel

    result = SQLKernel.analyze(
        sql="SELECT TOP 10 * FROM users WHERE GETDATE() > created_at",
        source_db="mssql",
        target_db="kingbasees",
    )
    # result.diagnostics  → ObjectAnalysis
    # result.rewrite      → RewriteResult
    # result.migration    → MigrationPlanResponse
    # result.simulation   → SimulationResponse
"""

from __future__ import annotations

import time

from architecture.core.sql.rewrite.engine import rewrite_from_context
from architecture.core.sql.diagnostics.analyzer import analyze_objects_from_context
from app.api.sql_migration.decision_engine import evaluate_migration_from_context
from app.api.sql_simulation.simulator import simulate_from_context

from .context_builder import build_context
from .decision.synthesizer import synthesize_decision
from .semantic_context import BusinessExecutionResult, KernelResult, SQLSemanticContext


# ---------------------------------------------------------------------------
# Engine name constants
# ---------------------------------------------------------------------------

ENGINE_DIAGNOSTICS = "diagnostics"
ENGINE_REWRITE = "rewrite"
ENGINE_SCORE = "score"
ENGINE_MIGRATION = "migration"
ENGINE_SIMULATION = "simulation"

ALL_ENGINES = [
    ENGINE_DIAGNOSTICS,
    ENGINE_REWRITE,
    ENGINE_SCORE,
    ENGINE_MIGRATION,
    ENGINE_SIMULATION,
]

# Engines that do NOT require a live database connection
STATELESS_ENGINES = [
    ENGINE_DIAGNOSTICS,
    ENGINE_REWRITE,
    ENGINE_MIGRATION,
    ENGINE_SIMULATION,
]


# ---------------------------------------------------------------------------
# SQLKernel
# ---------------------------------------------------------------------------


class SQLKernel:
    """Single entry point for SQL intelligence analysis.

    Builds a SQLSemanticContext once, then runs all requested engines
    against that shared context.  No engine parses SQL independently.
    """

    @staticmethod
    def analyze(
        sql: str,
        source_db: str,
        target_db: str,
        *,
        engines: list[str] | None = None,
        rewritten_sql: str | None = None,
        synthesize: bool = True,
    ) -> KernelResult:
        """Run the full analysis pipeline.

        Args:
            sql: Source SQL in the source database dialect.
            source_db: Source database type (mssql, kingbasees, dm8).
            target_db: Target database type (mssql, kingbasees, dm8).
            engines: Subset of engines to run.  Default: all stateless engines
                (diagnostics, rewrite, migration, simulation).  Score requires
                a live DB connection and is excluded by default.
            rewritten_sql: Pre-computed rewritten SQL.
            synthesize: If True (default), synthesise a single KernelDecision
                from all engine outputs after they complete.

        Returns:
            KernelResult with all engine outputs and decision populated.
        """
        start = time.perf_counter()
        warnings: list[str] = []

        if engines is None:
            engines = list(STATELESS_ENGINES)

        # --- Build context once (single parse) ---
        ctx = build_context(
            sql, source_db, target_db,
            rewritten_sql=rewritten_sql,
            auto_rewrite=(ENGINE_REWRITE in engines),
        )

        # --- Run each requested engine ---
        diag = None
        rewrite = None
        score = None
        migration = None
        simulation = None

        if ENGINE_DIAGNOSTICS in engines:
            diag = _run_diagnostics(ctx)

        if ENGINE_REWRITE in engines:
            rewrite = _run_rewrite(ctx)

        if ENGINE_SCORE in engines:
            try:
                score = _run_score(ctx)
            except Exception as exc:
                warnings.append(f"Score engine failed: {exc}")

        if ENGINE_MIGRATION in engines:
            migration = _run_migration(ctx)

        if ENGINE_SIMULATION in engines:
            simulation = _run_simulation(ctx)

        elapsed = (time.perf_counter() - start) * 1000

        # --- Synthesise decision (runs after all engines complete) ---
        decision = None
        if synthesize:
            # Build a temporary KernelResult for the synthesizer
            temp = KernelResult(
                source_db=source_db,
                target_db=target_db,
                original_sql=ctx.original_sql,
                rewritten_sql=ctx.rewritten_sql,
                diagnostics=diag,
                rewrite=rewrite,
                score=score,
                migration=migration,
                simulation=simulation,
                engines_run=engines,
                total_time_ms=round(elapsed, 1),
                warnings=list(warnings),
            )
            decision = synthesize_decision(temp)

        return KernelResult(
            source_db=source_db,
            target_db=target_db,
            original_sql=ctx.original_sql,
            rewritten_sql=ctx.rewritten_sql,
            diagnostics=diag,
            rewrite=rewrite,
            score=score,
            migration=migration,
            simulation=simulation,
            decision=decision,
            engines_run=engines,
            total_time_ms=round(elapsed, 1),
            warnings=warnings,
        )

    @staticmethod
    def execute_on_both(
        sql: str,
        source_db: str,
        target_db: str,
        *,
        params: tuple | None = None,
        skip_validation: bool = False,
        analyze_kernel: bool = True,
    ) -> "BusinessExecutionResult":
        """Execute SQL on both source and target databases with kernel analysis.

        This is the primary execution middleware for business services.
        Routes through DualDbExecutor for parallel execution, and optionally
        runs kernel analysis for compatibility context.

        Args:
            sql: SQL to execute (use %s placeholders).
            source_db: Source database type.
            target_db: Target database type.
            params: Parameterized query parameters tuple.
            skip_validation: If True, bypass read-only security check.
            analyze_kernel: If True, run diagnostics + rewrite before execution.

        Returns:
            BusinessExecutionResult with both results + kernel analysis.
        """
        from architecture.tooling.migration.dual_db_executor import DualDbExecutor

        dual_result, kernel_result = DualDbExecutor.execute_on_both(
            sql=sql,
            source_db=source_db,
            target_db=target_db,
            params=params,
            skip_validation=skip_validation,
            analyze_kernel=analyze_kernel,
        )

        # Build diff detail if results differ
        diff: list[dict] = []
        if not dual_result.equal:
            diff = _compute_result_diff(
                dual_result.source_result, dual_result.target_result
            )

        return BusinessExecutionResult(
            source_db=source_db,
            target_db=target_db,
            sql=sql,
            rewritten_sql=kernel_result.rewritten_sql if kernel_result else None,
            source_result=dual_result.source_result,
            target_result=dual_result.target_result,
            kernel=kernel_result,
            equal=dual_result.equal,
            diff=diff,
            execution_time_ms=dual_result.total_time_ms,
        )

    @staticmethod
    def build_context(
        sql: str,
        source_db: str,
        target_db: str,
        *,
        rewritten_sql: str | None = None,
    ) -> SQLSemanticContext:
        """Build a semantic context without running engines.

        Useful when you only need the parsed representation, or want to
        pass it to engines manually.
        """
        return build_context(sql, source_db, target_db, rewritten_sql=rewritten_sql)


# ---------------------------------------------------------------------------
# Engine runners (internal)
# ---------------------------------------------------------------------------


def _run_diagnostics(ctx: SQLSemanticContext):
    """Run diagnostics engine using the pre-built context."""
    return analyze_objects_from_context(ctx)


def _run_rewrite(ctx: SQLSemanticContext):
    """Run rewrite engine using the pre-built context."""
    return rewrite_from_context(ctx)


def _run_migration(ctx: SQLSemanticContext):
    """Run migration engine using the pre-built context."""
    return evaluate_migration_from_context(ctx)


def _run_simulation(ctx: SQLSemanticContext):
    """Run simulation engine using the pre-built context."""
    return simulate_from_context(ctx)


def _run_score(ctx: SQLSemanticContext):
    """Run score engine against the context.

    NOTE: This requires live database connections.  It is excluded from
    default engine set and must be explicitly requested.
    """
    from architecture.core.sql.scoring.score_service import calculate_score_from_context

    return calculate_score_from_context(ctx)


def _compute_result_diff(
    source: dict, target: dict
) -> list[dict]:
    """Compute differences between source and target execution results."""
    diffs: list[dict] = []

    if source.get("success") != target.get("success"):
        diffs.append({
            "field": "success",
            "source": source.get("success"),
            "target": target.get("success"),
        })

    if source.get("row_count") != target.get("row_count"):
        diffs.append({
            "field": "row_count",
            "source": source.get("row_count"),
            "target": target.get("row_count"),
        })

    if source.get("columns") != target.get("columns"):
        diffs.append({
            "field": "columns",
            "source": source.get("columns"),
            "target": target.get("columns"),
        })

    if source.get("rows") != target.get("rows"):
        diffs.append({
            "field": "rows",
            "source": source.get("rows"),
            "target": target.get("rows"),
        })

    if source.get("error") or target.get("error"):
        diffs.append({
            "field": "error",
            "source": source.get("error"),
            "target": target.get("error"),
        })

    return diffs
