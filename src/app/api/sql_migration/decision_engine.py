"""
SQL Migration Decision Engine — unified migration feasibility assessment.

Integrates diagnostics, rewrite, and scoring into a single migration decision.
Produces: feasibility verdict, risk level, confidence, impact analysis, and
step-by-step migration plan.

Decision thresholds:
    Estimated score > 85  → SAFE_AUTO_MIGRATION
    Estimated score 70-85 → NEED_REVIEW
    Estimated score < 70  → HIGH_RISK

Two entry points:
  - evaluate_migration(sql, source_db, target_db) — original, parses internally
  - evaluate_migration_from_context(ctx) — kernel path, uses pre-built context
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.sql_compare.rewrite.engine import rewrite_sql
from app.api.sql_diagnostics.analyzer import analyze_objects
from app.api.sql_diagnostics.extractor import extract_objects

from .impact_analyzer import analyze_impact
from .plan_generator import generate_plan
from .schemas import (
    ImpactAnalysis,
    MigrationPlan,
    MigrationPlanResponse,
    Recommendation,
    RiskLevel,
)

if TYPE_CHECKING:
    from app.core.sql_kernel.semantic_context import SQLSemanticContext


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_migration(
    sql: str,
    source_db: str,
    target_db: str,
) -> MigrationPlanResponse:
    """Evaluate migration feasibility for a SQL statement.

    Full pipeline:
        1. Diagnostics — extract objects, analyze cross-DB compatibility
        2. Rewrite — attempt automatic SQL transformation
        3. Impact Analysis — identify critical tables, hotspots, join chains
        4. Score Estimation — compute feasibility score from diagnostic data
        5. Plan Generation — produce ordered migration steps
        6. Decision — final recommendation based on thresholds

    Args:
        sql: Source SQL in the source database dialect.
        source_db: Source database type.
        target_db: Target database type.

    Returns:
        MigrationPlanResponse with full decision, impact, and plan.
    """
    warnings: list[str] = []

    # --- Identity case ---
    if source_db == target_db:
        return MigrationPlanResponse(
            migration_feasible=True,
            risk_level=RiskLevel.NONE,
            confidence=1.0,
            recommendation=Recommendation.SAFE_AUTO_MIGRATION,
            estimated_score=100.0,
            source_db=source_db,
            target_db=target_db,
            original_sql=sql.strip(),
            rewritten_sql=sql.strip(),
            impact=ImpactAnalysis(),
            plan=MigrationPlan(),
            warnings=["Source and target database are the same — no migration needed"],
        )

    # --- Phase 1: Diagnostics (extract + analyze objects) ---
    objects = extract_objects(sql)
    diagnostics = analyze_objects(objects, [target_db])

    # --- Phase 2: Rewrite (attempt automatic transformation) ---
    rewrite_result = rewrite_sql(sql, source_db, target_db)
    rewritten_sql = rewrite_result.rewritten_sql
    warnings.extend(rewrite_result.warnings)

    # --- Phase 3: Impact Analysis ---
    impact = analyze_impact(
        tables=diagnostics.tables,
        columns=diagnostics.columns,
        functions=diagnostics.functions,
        joins=diagnostics.joins,
    )

    # --- Phase 4: Score Estimation ---
    estimated_score = _estimate_score(diagnostics, rewrite_result)

    # --- Phase 5: Plan Generation ---
    has_critical = len(impact.critical_tables) > 0
    has_high_funcs = any(
        f.risk.value in ("HIGH", "CRITICAL") for f in diagnostics.functions
    )
    high_count = impact.high_risk_count
    med_count = impact.medium_risk_count

    plan = generate_plan(
        applied_rules=rewrite_result.rules_applied,
        has_critical_tables=has_critical,
        has_high_functions=has_high_funcs,
        high_risk_count=high_count,
        medium_risk_count=med_count,
        source_db=source_db,
        target_db=target_db,
    )

    # --- Phase 6: Decision ---
    risk_level = _score_to_risk(estimated_score)
    recommendation = _score_to_recommendation(estimated_score)
    feasible = recommendation != Recommendation.HIGH_RISK
    confidence = _compute_confidence(diagnostics, rewrite_result)

    return MigrationPlanResponse(
        migration_feasible=feasible,
        risk_level=risk_level,
        confidence=round(confidence, 4),
        recommendation=recommendation,
        estimated_score=estimated_score,
        source_db=source_db,
        target_db=target_db,
        original_sql=sql.strip(),
        rewritten_sql=rewritten_sql if rewritten_sql != sql.strip() else None,
        impact=impact,
        plan=plan,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Kernel entry point — uses pre-built SQLSemanticContext
# ---------------------------------------------------------------------------


def evaluate_migration_from_context(
    ctx: "SQLSemanticContext",
) -> MigrationPlanResponse:
    """Evaluate migration feasibility using a pre-built SQLSemanticContext.

    This is the kernel path — it skips extract_objects() and rewrite_sql()
    because the context already contains the parsed objects and rewritten SQL.

    Args:
        ctx: Pre-built SQLSemanticContext from the kernel.

    Returns:
        MigrationPlanResponse with full decision, impact, and plan.
    """
    warnings: list[str] = []

    # --- Identity case ---
    if ctx.source_db == ctx.target_db:
        return MigrationPlanResponse(
            migration_feasible=True,
            risk_level=RiskLevel.NONE,
            confidence=1.0,
            recommendation=Recommendation.SAFE_AUTO_MIGRATION,
            estimated_score=100.0,
            source_db=ctx.source_db,
            target_db=ctx.target_db,
            original_sql=ctx.original_sql,
            rewritten_sql=ctx.original_sql,
            impact=ImpactAnalysis(),
            plan=MigrationPlan(),
            warnings=["Source and target database are the same — no migration needed"],
        )

    # --- Phase 1: Diagnostics (reuse context's pre-extracted objects) ---
    objects = extract_objects(ctx.original_sql)
    diagnostics = analyze_objects(objects, [ctx.target_db])

    # --- Phase 2: Rewrite (use context's pre-computed rewrite) ---
    rewritten_sql = ctx.rewritten_sql
    if rewritten_sql is None:
        rewrite_result = rewrite_sql(ctx.original_sql, ctx.source_db, ctx.target_db)
        rewritten_sql = rewrite_result.rewritten_sql
        warnings.extend(rewrite_result.warnings)
        rules_applied = rewrite_result.rules_applied
        rewrite_confidence = rewrite_result.confidence
    else:
        # Rewrite was pre-computed; re-run to get rule metadata
        rewrite_result = rewrite_sql(ctx.original_sql, ctx.source_db, ctx.target_db)
        rules_applied = rewrite_result.rules_applied
        rewrite_confidence = rewrite_result.confidence
        warnings.extend(rewrite_result.warnings)

    # Use a lightweight wrapper for the _estimate_score helper
    class _RewriteProxy:
        def __init__(self, applied, confidence):
            self.rules_applied = applied
            self.confidence = confidence

    rewrite_proxy = _RewriteProxy(rules_applied, rewrite_confidence)

    # --- Phase 3: Impact Analysis ---
    impact = analyze_impact(
        tables=diagnostics.tables,
        columns=diagnostics.columns,
        functions=diagnostics.functions,
        joins=diagnostics.joins,
    )

    # --- Phase 4: Score Estimation ---
    estimated_score = _estimate_score(diagnostics, rewrite_proxy)

    # --- Phase 5: Plan Generation ---
    has_critical = len(impact.critical_tables) > 0
    has_high_funcs = any(
        f.risk.value in ("HIGH", "CRITICAL") for f in diagnostics.functions
    )
    high_count = impact.high_risk_count
    med_count = impact.medium_risk_count

    plan = generate_plan(
        applied_rules=rules_applied,
        has_critical_tables=has_critical,
        has_high_functions=has_high_funcs,
        high_risk_count=high_count,
        medium_risk_count=med_count,
        source_db=ctx.source_db,
        target_db=ctx.target_db,
    )

    # --- Phase 6: Decision ---
    risk_level = _score_to_risk(estimated_score)
    recommendation = _score_to_recommendation(estimated_score)
    feasible = recommendation != Recommendation.HIGH_RISK
    confidence = _compute_confidence(diagnostics, rewrite_proxy)

    return MigrationPlanResponse(
        migration_feasible=feasible,
        risk_level=risk_level,
        confidence=round(confidence, 4),
        recommendation=recommendation,
        estimated_score=estimated_score,
        source_db=ctx.source_db,
        target_db=ctx.target_db,
        original_sql=ctx.original_sql,
        rewritten_sql=rewritten_sql if rewritten_sql != ctx.original_sql else None,
        impact=impact,
        plan=plan,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Score estimation
# ---------------------------------------------------------------------------


def _estimate_score(diagnostics, rewrite_result) -> float:
    """Estimate a migration feasibility score (0-100).

    Factors:
      - Base score starts at 100
      - Each CRITICAL-risk object: -20
      - Each HIGH-risk object: -10
      - Each MEDIUM-risk object: -3
      - Apply rewrite confidence multiplier
      - Floor at 0, ceiling at 100
    """
    score = 100.0

    all_objects = (
        list(diagnostics.tables)
        + list(diagnostics.columns)
        + list(diagnostics.functions)
        + list(diagnostics.joins)
    )

    for obj in all_objects:
        risk_val = obj.risk.value
        if risk_val == "CRITICAL":
            score -= 20
        elif risk_val == "HIGH":
            score -= 10
        elif risk_val == "MEDIUM":
            score -= 3

    # Apply rewrite confidence as a multiplier (only if rewrites were applied)
    if rewrite_result.rules_applied:
        score = score * (0.5 + 0.5 * rewrite_result.confidence)

    return max(0.0, min(100.0, round(score, 1)))


def _compute_confidence(diagnostics, rewrite_result) -> float:
    """Compute overall confidence from diagnostic data and rewrite confidence.

    Confidence = rewrite_confidence * diagnostic_factor
      - diagnostic_factor = 1.0 - (0.05 * HIGH_count) - (0.15 * CRITICAL_count)
    """
    all_objects = (
        list(diagnostics.tables)
        + list(diagnostics.columns)
        + list(diagnostics.functions)
        + list(diagnostics.joins)
    )

    high_count = sum(1 for o in all_objects if o.risk.value == "HIGH")
    critical_count = sum(1 for o in all_objects if o.risk.value == "CRITICAL")

    diagnostic_factor = max(0.0, 1.0 - 0.05 * high_count - 0.15 * critical_count)

    # If rewrite was applied, use its confidence; otherwise rely on diagnostics
    if rewrite_result.rules_applied:
        return rewrite_result.confidence * diagnostic_factor
    else:
        return diagnostic_factor


# ---------------------------------------------------------------------------
# Decision thresholds
# ---------------------------------------------------------------------------


def _score_to_risk(score: float) -> RiskLevel:
    """Map estimated score to risk level."""
    if score >= 90:
        return RiskLevel.NONE
    if score >= 75:
        return RiskLevel.LOW
    if score >= 55:
        return RiskLevel.MEDIUM
    if score >= 35:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _score_to_recommendation(score: float) -> Recommendation:
    """Map estimated score to migration recommendation.

    Thresholds:
        > 85  → SAFE_AUTO_MIGRATION
        70-85 → NEED_REVIEW
        < 70  → HIGH_RISK
    """
    if score > 85:
        return Recommendation.SAFE_AUTO_MIGRATION
    if score >= 70:
        return Recommendation.NEED_REVIEW
    return Recommendation.HIGH_RISK
