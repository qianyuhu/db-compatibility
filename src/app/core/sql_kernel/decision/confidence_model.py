"""
Confidence Model — weighted combination of confidence signals from all engines.

Produces a single confidence score (0.0–1.0) that quantifies how reliable
the migration decision is.  Higher confidence = more engines agree, fewer
risks, higher individual confidences.

Weights (normalised to 1.0):
  - diagnostics_factor : 0.20  — based on HIGH/CRITICAL object counts
  - rewrite_confidence : 0.25  — from RewriteResult.confidence
  - migration_confidence: 0.25  — from MigrationPlanResponse.confidence
  - simulation_score   : 0.30  — from SimulationResponse.equivalence_score
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Confidence breakdown
# ---------------------------------------------------------------------------


@dataclass
class ConfidenceBreakdown:
    """Detailed confidence calculation with per-engine contributions."""

    overall: float = 1.0                # final weighted confidence (0.0–1.0)

    # Per-engine signals (0.0–1.0 each)
    diagnostics_factor: float = 1.0
    rewrite_confidence: float = 1.0
    migration_confidence: float = 1.0
    simulation_score: float = 1.0

    # Weights used
    weight_diagnostics: float = 0.20
    weight_rewrite: float = 0.25
    weight_migration: float = 0.25
    weight_simulation: float = 0.30

    # Metadata
    engines_available: list[str] = field(default_factory=list)
    engines_missing: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_confidence(
    diagnostics: object | None,
    rewrite: object | None,
    migration: object | None,
    simulation: object | None,
) -> ConfidenceBreakdown:
    """Compute overall decision confidence from all available engines.

    Missing engines are excluded and their weight is redistributed
    proportionally across available engines.

    Args:
        diagnostics: ObjectAnalysis from diagnostics engine.
        rewrite: RewriteResult from rewrite engine.
        migration: MigrationPlanResponse from migration engine.
        simulation: SimulationResponse from simulation engine.

    Returns:
        ConfidenceBreakdown with overall score and per-engine details.
    """
    # --- Base weights ---
    w_diag = 0.20
    w_rewrite = 0.25
    w_mig = 0.25
    w_sim = 0.30

    # --- Per-engine signals ---
    available: list[str] = []
    missing: list[str] = []

    # Diagnostics factor: 1.0 - penalty for high-risk objects
    diag_factor = 1.0
    if diagnostics is not None:
        diag_factor = _compute_diagnostics_factor(diagnostics)
        available.append("diagnostics")
    else:
        missing.append("diagnostics")
        w_diag = 0.0

    # Rewrite confidence: from RewriteResult
    rewrite_conf = 1.0
    if rewrite is not None:
        rewrite_conf = getattr(rewrite, "confidence", 1.0)
        available.append("rewrite")
    else:
        missing.append("rewrite")
        w_rewrite = 0.0

    # Migration confidence: from MigrationPlanResponse
    mig_conf = 1.0
    if migration is not None:
        mig_conf = getattr(migration, "confidence", 1.0)
        available.append("migration")
    else:
        missing.append("migration")
        w_mig = 0.0

    # Simulation score: equivalence_score from SimulationResponse
    sim_score = 1.0
    if simulation is not None:
        sim_score = getattr(simulation, "equivalence_score", 1.0)
        available.append("simulation")
    else:
        missing.append("simulation")
        w_sim = 0.0

    # --- Redistribute missing weights proportionally ---
    total_weight = w_diag + w_rewrite + w_mig + w_sim
    if total_weight > 0:
        w_diag /= total_weight
        w_rewrite /= total_weight
        w_mig /= total_weight
        w_sim /= total_weight

    # --- Weighted overall confidence ---
    overall = (
        w_diag * diag_factor
        + w_rewrite * rewrite_conf
        + w_mig * mig_conf
        + w_sim * sim_score
    )

    # Clamp to [0, 1]
    overall = max(0.0, min(1.0, overall))

    return ConfidenceBreakdown(
        overall=round(overall, 4),
        diagnostics_factor=round(diag_factor, 4),
        rewrite_confidence=round(rewrite_conf, 4),
        migration_confidence=round(mig_conf, 4),
        simulation_score=round(sim_score, 4),
        weight_diagnostics=round(w_diag, 4),
        weight_rewrite=round(w_rewrite, 4),
        weight_migration=round(w_mig, 4),
        weight_simulation=round(w_sim, 4),
        engines_available=available,
        engines_missing=missing,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_diagnostics_factor(diagnostics) -> float:
    """Compute a confidence factor from diagnostic risk counts.

    Formula:
        factor = 1.0 - (0.05 × HIGH_count) - (0.15 × CRITICAL_count)
        Clamped to [0.0, 1.0].
    """
    summary = getattr(diagnostics, "summary", None)
    if summary is None:
        return 1.0

    high_count = 0
    critical_count = 0

    # Sum across all object categories
    for category in ("tables", "columns", "functions", "joins"):
        cat_summary = getattr(summary, category, None)
        if cat_summary is not None:
            high_count += getattr(cat_summary, "HIGH", 0)
            critical_count += getattr(cat_summary, "CRITICAL", 0)

    factor = 1.0 - (0.05 * high_count) - (0.15 * critical_count)
    return max(0.0, min(1.0, factor))
