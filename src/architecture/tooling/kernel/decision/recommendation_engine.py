"""
Recommendation Engine — rule-based decision logic.

Converts risk profile + confidence + engine outputs into a single
actionable recommendation.

Decision rules:
  - SAFE   : score > 85 AND no blocking risks AND confidence ≥ 0.80
  - REVIEW : score 70–85 OR confidence 0.50–0.80 OR ≤2 HIGH risks
  - BLOCK  : score < 70 OR has blocking risks OR confidence < 0.50

Migration path:
  - DIRECT       : no dialect features, no rewrite needed
  - AUTO_REWRITE : rewrite produced valid SQL with high confidence
  - PARTIAL      : some rules applied but manual review needed
  - MANUAL       : no or insufficient rewrite coverage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Recommendation(str, Enum):
    """Final migration recommendation."""
    SAFE = "SAFE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class MigrationPath(str, Enum):
    """Recommended migration approach."""
    DIRECT = "DIRECT"             # no changes needed
    AUTO_REWRITE = "AUTO_REWRITE" # fully automatic
    PARTIAL = "PARTIAL"           # auto + manual review
    MANUAL = "MANUAL"             # full manual migration


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class DecisionResult:
    """Output of the recommendation engine."""

    recommendation: Recommendation = Recommendation.REVIEW
    migration_path: MigrationPath = MigrationPath.MANUAL
    explanation: str = ""
    decision_factors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

SCORE_SAFE_THRESHOLD = 85.0      # score ≥ this → SAFE candidate
SCORE_REVIEW_THRESHOLD = 70.0    # score ≥ this → REVIEW candidate
CONFIDENCE_SAFE_THRESHOLD = 0.80
CONFIDENCE_REVIEW_THRESHOLD = 0.50
REWRITE_CONFIDENCE_HIGH = 0.85   # rewrite confidence ≥ this → AUTO viable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_recommendation(
    risk_profile,
    confidence_breakdown,
    migration,
    rewrite,
    simulation,
    source_db: str,
    target_db: str,
) -> DecisionResult:
    """Produce a single migration recommendation from all inputs.

    Args:
        risk_profile: RiskProfile from risk_aggregator.
        confidence_breakdown: ConfidenceBreakdown from confidence_model.
        migration: MigrationPlanResponse or None.
        rewrite: RewriteResult or None.
        simulation: SimulationResponse or None.
        source_db: Source database type.
        target_db: Target database type.

    Returns:
        DecisionResult with recommendation, path, and explanation.
    """
    factors: list[str] = []

    # --- Extract key signals ---
    score = _extract_score(migration, simulation)
    has_blocking = len(risk_profile.blocking_issues) > 0
    has_critical = risk_profile.critical_count > 0
    has_high = risk_profile.high_count > 0
    rewrite_conf = getattr(rewrite, "confidence", 1.0) if rewrite else 1.0
    rewrite_rules = len(getattr(rewrite, "rules_applied", [])) if rewrite else 0
    sim_verdict = _get_enum_value(simulation, "recommendation", "SAFE_TO_EXECUTE")

    # --- Determine recommendation ---
    recommendation = _determine_recommendation(
        score, has_blocking, has_critical, has_high,
        confidence_breakdown.overall, sim_verdict, factors,
    )

    # --- Determine migration path ---
    migration_path = _determine_path(
        source_db, target_db, rewrite_rules, rewrite_conf,
        has_critical, has_high, recommendation, factors,
    )

    # --- Build explanation ---
    explanation = _build_explanation(
        recommendation, migration_path, score, confidence_breakdown.overall,
        risk_profile, source_db, target_db,
    )

    return DecisionResult(
        recommendation=recommendation,
        migration_path=migration_path,
        explanation=explanation,
        decision_factors=factors,
    )


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def _determine_recommendation(
    score: float,
    has_blocking: bool,
    has_critical: bool,
    has_high: bool,
    confidence: float,
    sim_verdict: str,
    factors: list[str],
) -> Recommendation:
    """Apply decision rules to determine recommendation level."""

    # --- BLOCK conditions ---
    if has_blocking or has_critical:
        factors.append(f"存在阻塞性问题 ({'CRITICAL' if has_critical else 'blocking'})，阻止自动迁移")
        return Recommendation.BLOCK

    if score < SCORE_REVIEW_THRESHOLD:
        factors.append(f"兼容性评分 {score:.0f}/100 低于阈值 {SCORE_REVIEW_THRESHOLD}")
        return Recommendation.BLOCK

    if confidence < CONFIDENCE_REVIEW_THRESHOLD:
        factors.append(f"综合置信度 {confidence:.0%} 低于阈值 {CONFIDENCE_REVIEW_THRESHOLD:.0%}")
        return Recommendation.BLOCK

    if sim_verdict == "HIGH_RISK_DO_NOT_EXECUTE":
        factors.append("仿真裁决为 HIGH_RISK_DO_NOT_EXECUTE")
        return Recommendation.BLOCK

    # --- REVIEW conditions ---
    review_reasons: list[str] = []

    if score < SCORE_SAFE_THRESHOLD:
        review_reasons.append(f"评分 {score:.0f}/100 < {SCORE_SAFE_THRESHOLD}")

    if confidence < CONFIDENCE_SAFE_THRESHOLD:
        review_reasons.append(f"置信度 {confidence:.0%} < {CONFIDENCE_SAFE_THRESHOLD:.0%}")

    if has_high:
        review_reasons.append(f"存在 HIGH 级别风险")

    if sim_verdict == "NEEDS_MANUAL_REVIEW":
        review_reasons.append("仿真建议人工审查")

    if review_reasons:
        factors.append("; ".join(review_reasons))
        return Recommendation.REVIEW

    # --- SAFE conditions ---
    factors.append(f"评分 {score:.0f}/100 ≥ {SCORE_SAFE_THRESHOLD}，无阻塞风险，置信度 {confidence:.0%}")
    return Recommendation.SAFE


def _determine_path(
    source_db: str,
    target_db: str,
    rewrite_rules: int,
    rewrite_conf: float,
    has_critical: bool,
    has_high: bool,
    recommendation: Recommendation,
    factors: list[str],
) -> MigrationPath:
    """Determine the recommended migration path."""

    # Same database → no migration needed
    if source_db == target_db:
        factors.append("源和目标数据库相同，无需迁移")
        return MigrationPath.DIRECT

    # No rewrite rules applied → needs manual
    if rewrite_rules == 0:
        # Check if there were NO dialect features at all (direct compat)
        if not has_critical and not has_high:
            factors.append("SQL 无方言特征，可直接在目标数据库执行")
            return MigrationPath.DIRECT
        else:
            factors.append("无可用的自动改写规则，需要手动迁移")
            return MigrationPath.MANUAL

    # Rules applied with high confidence → auto
    if rewrite_conf >= REWRITE_CONFIDENCE_HIGH and recommendation == Recommendation.SAFE:
        factors.append(f"改写置信度高 ({rewrite_conf:.0%})，{rewrite_rules} 条规则自动应用")
        return MigrationPath.AUTO_REWRITE

    # Rules applied but needs review → partial
    factors.append(
        f"部分改写可用 ({rewrite_rules} 条规则, 置信度 {rewrite_conf:.0%})，建议人工审查"
    )
    return MigrationPath.PARTIAL


def _build_explanation(
    recommendation: Recommendation,
    migration_path: MigrationPath,
    score: float,
    confidence: float,
    risk_profile,
    source_db: str,
    target_db: str,
) -> str:
    """Build a human-readable explanation of the decision."""

    rec_label = {
        Recommendation.SAFE: "✅ 可以安全迁移",
        Recommendation.REVIEW: "⚠️ 建议审查后迁移",
        Recommendation.BLOCK: "🚫 暂不建议迁移",
    }.get(recommendation, "❓ 无法确定")

    path_label = {
        MigrationPath.DIRECT: "SQL 可直接执行",
        MigrationPath.AUTO_REWRITE: "自动改写后执行",
        MigrationPath.PARTIAL: "部分自动改写 + 人工审查",
        MigrationPath.MANUAL: "需要完整手动迁移",
    }.get(migration_path, "需进一步分析")

    parts = [
        f"{rec_label} — {path_label}",
        f"源: {source_db} → 目标: {target_db}",
        f"综合评分: {score:.0f}/100 | 置信度: {confidence:.0%}",
    ]

    if risk_profile.blocking_issues:
        parts.append(f"阻塞问题: {len(risk_profile.blocking_issues)} 个")
    if risk_profile.primary_risks:
        top_risks = risk_profile.primary_risks[:3]
        parts.append(f"主要风险: {'; '.join(top_risks)}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_score(migration, simulation) -> float:
    """Extract the best available migration score.

    Priority: migration.estimated_score, then simulation.equivalence_score × 100.
    """
    if migration is not None:
        score = getattr(migration, "estimated_score", None)
        if score is not None and score > 0:
            return float(score)

    if simulation is not None:
        eq = getattr(simulation, "equivalence_score", 1.0)
        return float(eq) * 100.0

    return 100.0


def _get_enum_value(obj, attr: str, default: str) -> str:
    """Safely extract an enum value."""
    if obj is None:
        return default
    val = getattr(obj, attr, None)
    if val is None:
        return default
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)
