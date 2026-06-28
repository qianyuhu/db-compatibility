"""
SQL Decision Synthesis Layer — converts multi-engine Kernel output into a
single, actionable migration decision.

Pipeline:
    KernelResult → RiskAggregator → ConfidenceModel → RecommendationEngine → KernelDecision

Modules:
  - risk_aggregator.py      — collect & rank risks from all 5 engines
  - confidence_model.py     — weighted confidence across engine outputs
  - recommendation_engine.py — rule-based decision (SAFE / REVIEW / BLOCK)
  - synthesizer.py          — orchestrator, produces final KernelDecision
"""

from .synthesizer import synthesize_decision
from .synthesizer import KernelDecision, Recommendation, MigrationPath

__all__ = [
    "synthesize_decision",
    "KernelDecision",
    "Recommendation",
    "MigrationPath",
]
