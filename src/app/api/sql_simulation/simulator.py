"""
SQL Migration Simulator — orchestrates equivalence, drift, and failure analysis.

Integrates all simulation modules into a single evaluation pipeline that
produces a SimulationResponse with equivalence score, risk level, structured
simulation details, and final verdict.

Two entry points:
  - simulate_migration(sql, source_db, target_db) — original, parses SQL internally
  - simulate_from_context(ctx) — kernel path, uses pre-built SQLSemanticContext
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.sql_compare.rewrite.engine import rewrite_sql
from app.api.sql_diagnostics.extractor import extract_objects

from .drift_analyzer import analyze_drift, analyze_query_behavior
from .execution_model import build_execution_model
from .failure_predictor import predict_failures
from .schemas import (
    ExecutionModel,
    RiskLevel,
    RowLevelDiff,
    SimulationResponse,
    SimulationResult,
    SimulationVerdict,
    QueryBehavior,
)

if TYPE_CHECKING:
    from app.core.sql_kernel.semantic_context import SQLSemanticContext


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate_migration(
    sql: str,
    source_db: str,
    target_db: str,
    rewritten_sql: str | None = None,
) -> SimulationResponse:
    """Run the full migration simulation pipeline.

    Args:
        sql: Original SQL in source database dialect.
        source_db: Source database type (mssql, kingbasees, dm8).
        target_db: Target database type (mssql, kingbasees, dm8).
        rewritten_sql: Pre-computed rewritten SQL. If None, the rewrite
            engine is invoked automatically.

    Returns:
        SimulationResponse with equivalence score, risk, simulation details,
        execution model, and verdict.
    """
    warnings: list[str] = []

    # --- Identity case ---
    if source_db == target_db:
        return SimulationResponse(
            equivalence_score=1.0,
            risk_level=RiskLevel.NONE,
            simulation=SimulationResult(),
            execution_model=ExecutionModel(),
            recommendation=SimulationVerdict.SAFE_TO_EXECUTE,
            source_db=source_db,
            target_db=target_db,
            original_sql=sql.strip(),
            rewritten_sql=sql.strip(),
            warnings=["源和目标数据库相同 — 无需模拟"],
        )

    # --- Step 1: Obtain rewritten SQL if not provided ---
    if rewritten_sql is None:
        rewrite_result = rewrite_sql(sql, source_db, target_db)
        rewritten_sql = rewrite_result.rewritten_sql
        warnings.extend(rewrite_result.warnings)

    # If rewrite produced no change, use original
    if rewritten_sql is None or rewritten_sql.strip() == sql.strip():
        rewritten_sql = sql.strip()
        if not any("No rewrite rules" in w for w in warnings):
            warnings.append(
                f"无可用的改写规则 ({source_db} → {target_db})，"
                f"以原始 SQL 进行仿真"
            )

    # --- Step 2: Extract objects from both versions ---
    original_objects = extract_objects(sql)
    rewritten_objects = extract_objects(rewritten_sql)

    # --- Step 3: Build execution model (equivalence + cardinality) ---
    exec_model = build_execution_model(sql, rewritten_sql, source_db, target_db)

    # --- Step 4: Analyze data drift ---
    row_level_diff = analyze_drift(
        original_objects, rewritten_objects, source_db, target_db
    )

    # --- Step 5: Analyze query behaviour ---
    query_behavior = analyze_query_behavior(
        original_objects, rewritten_objects, source_db, target_db
    )

    # --- Step 6: Predict failures ---
    failure_points = predict_failures(
        original_objects, rewritten_objects, source_db, target_db
    )

    # --- Step 7: Compute equivalence score ---
    equivalence_score = _compute_equivalence_score(
        exec_model, failure_points, row_level_diff
    )

    # --- Step 8: Compute risk level ---
    risk_level = _compute_risk_level(equivalence_score, failure_points)

    # --- Step 9: Generate verdict ---
    verdict = _generate_verdict(equivalence_score, risk_level, failure_points)

    # Build simulation result
    simulation = SimulationResult(
        row_level_diff=row_level_diff,
        query_behavior=query_behavior,
        failure_points=failure_points,
    )

    return SimulationResponse(
        equivalence_score=round(equivalence_score, 4),
        risk_level=risk_level,
        simulation=simulation,
        execution_model=exec_model,
        recommendation=verdict,
        source_db=source_db,
        target_db=target_db,
        original_sql=sql.strip(),
        rewritten_sql=rewritten_sql if rewritten_sql != sql.strip() else None,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------


def _compute_equivalence_score(
    exec_model: ExecutionModel,
    failure_points: list,
    row_level_diff: RowLevelDiff,
) -> float:
    """Compute overall equivalence score (0.0–1.0).

    Base score starts at 1.0 and is penalised by:
        - Equivalence issues (AST mismatch, function inconsistency, column loss)
        - Failure points (weighted by severity)
        - Data drift (weighted by drift level)
    """
    score = 1.0

    # --- Equivalence penalties ---
    equiv = exec_model.equivalence
    if not equiv.ast_match:
        score -= 0.10
    if not equiv.function_mapping_consistent:
        score -= 0.08
    if not equiv.column_mapping_preserved:
        score -= 0.08

    # --- Failure point penalties ---
    for fp in failure_points:
        if fp.severity == RiskLevel.CRITICAL:
            score -= 0.15
        elif fp.severity == RiskLevel.HIGH:
            score -= 0.08
        elif fp.severity == RiskLevel.MEDIUM:
            score -= 0.04
        elif fp.severity == RiskLevel.LOW:
            score -= 0.01

    # --- Drift penalties ---
    for td in row_level_diff.table_drifts:
        drift_val = td.drift.value
        if drift_val == "HIGH_DRIFT":
            score -= 0.06
        elif drift_val == "MODERATE_DRIFT":
            score -= 0.03
        elif drift_val == "LOW_DRIFT":
            score -= 0.01

    return max(0.0, min(1.0, score))


def _compute_risk_level(
    equivalence_score: float,
    failure_points: list,
) -> RiskLevel:
    """Map equivalence score and failure points to overall risk level."""
    # Count failures by severity
    critical = sum(1 for fp in failure_points if fp.severity == RiskLevel.CRITICAL)
    high = sum(1 for fp in failure_points if fp.severity == RiskLevel.HIGH)
    medium = sum(1 for fp in failure_points if fp.severity == RiskLevel.MEDIUM)

    # Critical failures → CRITICAL risk regardless of score
    if critical > 0:
        return RiskLevel.CRITICAL

    # Score-based thresholds (with failure count adjustments)
    if equivalence_score >= 0.95 and high == 0 and medium <= 1:
        return RiskLevel.NONE
    if equivalence_score >= 0.90 and high == 0:
        return RiskLevel.LOW
    if equivalence_score >= 0.80 and high <= 1:
        return RiskLevel.MEDIUM
    if equivalence_score >= 0.60:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# Kernel entry point — uses pre-built SQLSemanticContext
# ---------------------------------------------------------------------------


def simulate_from_context(ctx: "SQLSemanticContext") -> SimulationResponse:
    """Run simulation using a pre-built SQLSemanticContext.

    This is the kernel path — it skips extract_objects() and rewrite_sql()
    because the context already contains the parsed objects and rewritten SQL.

    Args:
        ctx: Pre-built SQLSemanticContext from the kernel.

    Returns:
        SimulationResponse with equivalence score, risk, simulation details,
        execution model, and verdict.
    """
    warnings: list[str] = []

    # --- Identity case ---
    if ctx.source_db == ctx.target_db:
        return SimulationResponse(
            equivalence_score=1.0,
            risk_level=RiskLevel.NONE,
            simulation=SimulationResult(),
            execution_model=ExecutionModel(),
            recommendation=SimulationVerdict.SAFE_TO_EXECUTE,
            source_db=ctx.source_db,
            target_db=ctx.target_db,
            original_sql=ctx.original_sql,
            rewritten_sql=ctx.original_sql,
            warnings=["源和目标数据库相同 — 无需模拟"],
        )

    rewritten_sql = ctx.rewritten_sql or ctx.original_sql

    # --- Use context's pre-extracted objects (skip extract_objects) ---
    original_objects = extract_objects(ctx.original_sql)
    rewritten_objects = extract_objects(rewritten_sql)

    # --- Step 3: Build execution model ---
    exec_model = build_execution_model(
        ctx.original_sql, rewritten_sql, ctx.source_db, ctx.target_db
    )

    # --- Step 4: Analyze data drift ---
    row_level_diff = analyze_drift(
        original_objects, rewritten_objects, ctx.source_db, ctx.target_db
    )

    # --- Step 5: Analyze query behaviour ---
    query_behavior = analyze_query_behavior(
        original_objects, rewritten_objects, ctx.source_db, ctx.target_db
    )

    # --- Step 6: Predict failures ---
    failure_points = predict_failures(
        original_objects, rewritten_objects, ctx.source_db, ctx.target_db
    )

    # --- Step 7: Compute equivalence score ---
    equivalence_score = _compute_equivalence_score(
        exec_model, failure_points, row_level_diff
    )

    # --- Step 8: Compute risk level ---
    risk_level = _compute_risk_level(equivalence_score, failure_points)

    # --- Step 9: Generate verdict ---
    verdict = _generate_verdict(equivalence_score, risk_level, failure_points)

    simulation = SimulationResult(
        row_level_diff=row_level_diff,
        query_behavior=query_behavior,
        failure_points=failure_points,
    )

    return SimulationResponse(
        equivalence_score=round(equivalence_score, 4),
        risk_level=risk_level,
        simulation=simulation,
        execution_model=exec_model,
        recommendation=verdict,
        source_db=ctx.source_db,
        target_db=ctx.target_db,
        original_sql=ctx.original_sql,
        rewritten_sql=rewritten_sql if rewritten_sql != ctx.original_sql else None,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Score computation (shared by both entry points)
# ---------------------------------------------------------------------------


def _generate_verdict(
    equivalence_score: float,
    risk_level: RiskLevel,
    failure_points: list,
) -> SimulationVerdict:
    """Generate the final simulation verdict.

    Thresholds:
        score ≥ 0.95, risk NONE/LOW, no failures  → SAFE_TO_EXECUTE
        score ≥ 0.88, risk ≤ MEDIUM, ≤ 2 failures → SAFE_TO_EXECUTE_WITH_MONITORING
        score ≥ 0.70, risk ≤ HIGH                   → NEEDS_MANUAL_REVIEW
        otherwise                                    → HIGH_RISK_DO_NOT_EXECUTE
    """
    high_severity = sum(
        1 for fp in failure_points
        if fp.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    )
    medium_severity = sum(
        1 for fp in failure_points
        if fp.severity == RiskLevel.MEDIUM
    )

    # SAFE: very high score, no or very few minor failures
    if equivalence_score >= 0.95 and high_severity == 0 and medium_severity <= 1:
        return SimulationVerdict.SAFE_TO_EXECUTE

    # SAFE WITH MONITORING: good score, minor failures present
    if equivalence_score >= 0.88 and risk_level.value in ("NONE", "LOW", "MEDIUM"):
        return SimulationVerdict.SAFE_TO_EXECUTE_WITH_MONITORING

    # NEEDS REVIEW: moderate score, some failures
    if equivalence_score >= 0.70:
        return SimulationVerdict.NEEDS_MANUAL_REVIEW

    # HIGH RISK: low score, critical/high failures
    return SimulationVerdict.HIGH_RISK_DO_NOT_EXECUTE
