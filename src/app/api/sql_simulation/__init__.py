"""
SQL Migration Simulation Engine — Phase 3 Step 2.

Simulates execution-level migration behavior after the decision engine
has produced a migration plan. Answers: "What actually happens at runtime?"

Pipeline:
    1. Equivalence Check — AST diff + function mapping consistency
    2. Cardinality Estimation — rule-based join graph + table size heuristics
    3. Data Drift Analysis — row-level variance, NULL semantics, aggregation
    4. Failure Prediction — NULL / pagination / timezone / JOIN failure rules
    5. Verdict — SAFE_TO_EXECUTE / SAFE_WITH_MONITORING / NEEDS_REVIEW / HIGH_RISK

Modules:
    schemas.py           — Pydantic request/response models
    execution_model.py   — equivalence check + cardinality estimation
    drift_analyzer.py    — row/column-level data drift analysis
    failure_predictor.py — rule-based failure prediction
    simulator.py         — orchestrator integrating all modules
    simulation_router.py — POST /api/sql/migrate/simulate
"""
