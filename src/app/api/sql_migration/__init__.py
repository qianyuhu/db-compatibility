"""
SQL Migration Decision Engine — unified migration feasibility assessment.

Integrates diagnostics, rewrite, score, and compare into a single
migration decision with impact analysis and step-by-step plan.

Pipeline:
    SQL → Diagnostics → Rewrite → Impact Analysis → Plan Generation → Decision

Submodules:
    schemas           — Pydantic request/response models
    impact_analyzer   — Critical table detection, function dependencies, join chain risk
    plan_generator    — Sequential migration step generation
    decision_engine   — Orchestrator integrating all modules
    migration_router  — POST /api/sql/migrate/plan endpoint
"""
