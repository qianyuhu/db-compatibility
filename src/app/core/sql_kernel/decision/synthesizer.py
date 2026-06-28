"""
Decision Synthesizer — orchestrates risk aggregation, confidence modelling,
and recommendation into a single KernelDecision.

Pipeline:
    KernelResult → RiskAggregator → ConfidenceModel → RecommendationEngine
                 ↓
            KernelDecision

This is the top-level entry point for the decision synthesis layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .confidence_model import compute_confidence
from .recommendation_engine import (
    DecisionResult,
    MigrationPath,
    Recommendation,
    make_recommendation,
)
from .risk_aggregator import RiskProfile, aggregate_risks


# ---------------------------------------------------------------------------
# Output schema — KernelDecision
# ---------------------------------------------------------------------------


# Re-export enums for external use
Recommendation = Recommendation
MigrationPath = MigrationPath


@dataclass
class KernelDecision:
    """Single actionable migration decision synthesised from all 5 engines.

    This is the final output of the decision synthesis layer — one decision
    per SQL input, backed by evidence from every available engine.
    """

    # === Primary decision ===
    recommendation: str = "REVIEW"       # SAFE / REVIEW / BLOCK
    confidence: float = 0.0              # overall confidence (0.0–1.0)
    migration_path: str = "MANUAL"       # DIRECT / AUTO_REWRITE / PARTIAL / MANUAL

    # === Risk summary ===
    primary_risks: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    aggregated_severity: str = "NONE"
    risk_counts: dict[str, int] = field(default_factory=dict)

    # === Strategy ===
    execution_strategy: str = ""
    explanation: str = ""

    # === Evidence (engine outputs used in decision) ===
    score: float = 100.0
    rewrite_confidence: float = 1.0
    rewrite_rules_applied: int = 0
    simulation_verdict: str = "N/A"

    # === Metadata ===
    source_db: str = ""
    target_db: str = ""
    original_sql: str = ""
    rewritten_sql: str | None = None
    engines_consulted: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_decision(
    kernel_result,   # KernelResult
) -> KernelDecision:
    """Synthesise a single migration decision from a KernelResult.

    Args:
        kernel_result: KernelResult from SQLKernel.analyze().

    Returns:
        KernelDecision with recommendation, confidence, risks, path, and strategy.
    """
    diag = kernel_result.diagnostics
    rewrite = kernel_result.rewrite
    migration = kernel_result.migration
    simulation = kernel_result.simulation

    # --- Step 1: Aggregate risks ---
    risk_profile = aggregate_risks(diag, rewrite, migration, simulation)

    # --- Step 2: Compute confidence ---
    confidence_breakdown = compute_confidence(diag, rewrite, migration, simulation)

    # --- Step 3: Make recommendation ---
    decision = make_recommendation(
        risk_profile, confidence_breakdown,
        migration, rewrite, simulation,
        kernel_result.source_db, kernel_result.target_db,
    )

    # --- Step 4: Build execution strategy ---
    strategy = _build_strategy(decision, risk_profile, rewrite)

    # --- Step 5: Extract evidence signals ---
    score = _extract_score(migration, simulation)
    rewrite_conf = getattr(rewrite, "confidence", 1.0) if rewrite else 1.0
    rewrite_rules = len(getattr(rewrite, "rules_applied", [])) if rewrite else 0
    sim_verdict = _get_sim_verdict(simulation)

    return KernelDecision(
        recommendation=decision.recommendation.value,
        confidence=confidence_breakdown.overall,
        migration_path=decision.migration_path.value,
        primary_risks=risk_profile.primary_risks,
        blocking_issues=risk_profile.blocking_issues,
        aggregated_severity=risk_profile.aggregated_severity,
        risk_counts={
            "CRITICAL": risk_profile.critical_count,
            "HIGH": risk_profile.high_count,
            "MEDIUM": risk_profile.medium_count,
            "LOW": risk_profile.low_count,
        },
        execution_strategy=strategy,
        explanation=decision.explanation,
        score=score,
        rewrite_confidence=rewrite_conf,
        rewrite_rules_applied=rewrite_rules,
        simulation_verdict=sim_verdict,
        source_db=kernel_result.source_db,
        target_db=kernel_result.target_db,
        original_sql=kernel_result.original_sql,
        rewritten_sql=kernel_result.rewritten_sql,
        engines_consulted=list(kernel_result.engines_run),
        warnings=list(kernel_result.warnings),
    )


# ---------------------------------------------------------------------------
# Strategy builder
# ---------------------------------------------------------------------------


def _build_strategy(
    decision: DecisionResult,
    risk_profile: RiskProfile,
    rewrite,
) -> str:
    """Build an execution strategy string based on the decision."""

    path = decision.migration_path
    recommendation = decision.recommendation

    if recommendation == Recommendation.BLOCK:
        return _block_strategy(risk_profile)

    if path == MigrationPath.DIRECT:
        return "SQL 语句无需修改，可直接在目标数据库执行。建议在测试环境先行验证。"

    if path == MigrationPath.AUTO_REWRITE:
        rules_count = len(getattr(rewrite, "rules_applied", [])) if rewrite else 0
        return (
            f"通过 {rules_count} 条自动改写规则完成 SQL 转换。"
            f"建议在目标数据库测试环境执行改写后的 SQL，"
            f"对比源数据库结果确认一致性后上线。"
        )

    if path == MigrationPath.PARTIAL:
        auto_steps = _count_auto_steps(rewrite)
        return (
            f"自动改写已完成 {auto_steps} 项变更，剩余项目需要人工审查。"
            f"建议: (1) 逐项确认改写规则是否正确; "
            f"(2) 在测试环境验证改写后 SQL; "
            f"(3) 确认高风险项已妥善处理后上线。"
        )

    # MANUAL
    return (
        f"无法自动改写，需要手动将 SQL 从源数据库方言转换为目标数据库方言。"
        f"建议: (1) 参考已知差异文档手动改写; "
        f"(2) 在目标数据库测试环境验证; "
        f"(3) 对比源/目标执行结果确保等价。"
    )


def _block_strategy(risk_profile: RiskProfile) -> str:
    """Build strategy for BLOCK recommendation."""
    parts = ["当前不建议直接迁移。请先解决以下阻塞问题:"]

    for issue in risk_profile.blocking_issues[:3]:
        parts.append(f"  • {issue}")

    parts.append(
        "解决阻塞问题后，重新运行分析以获取更新建议。"
        "如阻塞问题无法解决，建议评估是否接受迁移风险。"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_auto_steps(rewrite) -> int:
    """Count automatic steps from rewrite result."""
    if rewrite is None:
        return 0
    return len(getattr(rewrite, "rules_applied", []))


def _extract_score(migration, simulation) -> float:
    """Extract the best available score."""
    if migration is not None:
        s = getattr(migration, "estimated_score", None)
        if s is not None and s > 0:
            return float(s)
    if simulation is not None:
        eq = getattr(simulation, "equivalence_score", 1.0)
        return float(eq) * 100.0
    return 100.0


def _get_sim_verdict(simulation) -> str:
    """Extract simulation verdict string."""
    if simulation is None:
        return "N/A"
    v = getattr(simulation, "recommendation", None)
    if v is None:
        return "N/A"
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)
