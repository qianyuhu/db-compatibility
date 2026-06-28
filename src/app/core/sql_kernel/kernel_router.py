"""
SQL Kernel Router — unified API endpoints for all SQL intelligence engines.

POST /api/sql/kernel/analyze  — run selected engines against a SQL statement.
POST /api/sql/kernel/decision — synthesise a single actionable migration decision.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .decision.synthesizer import synthesize_decision
from .kernel import ALL_ENGINES, STATELESS_ENGINES, SQLKernel


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class KernelRequest(BaseModel):
    """Request for the unified kernel analysis endpoint."""

    sql: str = Field(..., description="Source SQL in the source database dialect")
    source_db: str = Field(..., description="Source database type", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(..., description="Target database type", pattern=r"^(mssql|kingbasees|dm8)$")
    engines: Optional[list[str]] = Field(
        default=None,
        description="Engines to run. Default: all stateless engines (diagnostics, rewrite, migration, simulation).",
    )
    rewritten_sql: Optional[str] = Field(
        default=None,
        description="Pre-computed rewritten SQL (skips auto-rewrite if provided)",
    )


class KernelResponse(BaseModel):
    """Aggregated response from the kernel analysis."""

    source_db: str
    target_db: str
    original_sql: str
    rewritten_sql: Optional[str] = None

    # Engine outputs (dict form of each engine's result)
    diagnostics: Optional[object] = None
    rewrite: Optional[object] = None
    score: Optional[object] = None
    migration: Optional[object] = None
    simulation: Optional[object] = None

    # Decision synthesis
    decision: Optional[object] = None

    engines_run: list[str] = []
    total_time_ms: float = 0.0
    warnings: list[str] = []

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/sql/kernel", tags=["sql-kernel"])


@router.post("/analyze", response_model=KernelResponse)
def analyze(request: KernelRequest) -> KernelResponse:
    """Run SQL intelligence engines against a single SQL statement.

    All engines share a single SQLSemanticContext built once from the raw SQL.
    No engine parses SQL independently.

    Available engines:
      - diagnostics  — object-level risk analysis (stateless)
      - rewrite      — automatic SQL dialect transformation (stateless)
      - score        — execution-based compatibility scoring (requires live DB)
      - migration    — migration feasibility + step-by-step plan (stateless)
      - simulation   — execution prediction + failure analysis (stateless)

    Default engines: diagnostics, rewrite, migration, simulation (all stateless).
    Add 'score' to run execution-based scoring against live databases.
    """
    engines = request.engines

    # Validate engine names
    if engines is not None:
        invalid = set(engines) - set(ALL_ENGINES)
        if invalid:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Unknown engines: {invalid}. Available: {ALL_ENGINES}",
            )

    result = SQLKernel.analyze(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
        engines=engines,
        rewritten_sql=request.rewritten_sql,
    )

    # Convert dataclass to dict for Pydantic response
    return KernelResponse(
        source_db=result.source_db,
        target_db=result.target_db,
        original_sql=result.original_sql,
        rewritten_sql=result.rewritten_sql,
        diagnostics=_serialize(result.diagnostics),
        rewrite=_serialize(result.rewrite),
        score=_serialize(result.score),
        migration=_serialize(result.migration),
        simulation=_serialize(result.simulation),
        decision=_serialize(result.decision),
        engines_run=result.engines_run,
        total_time_ms=result.total_time_ms,
        warnings=result.warnings,
    )


# ---------------------------------------------------------------------------
# Decision endpoint
# ---------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    """Request for the decision synthesis endpoint."""

    sql: str = Field(..., description="Source SQL in the source database dialect")
    source_db: str = Field(..., pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(..., pattern=r"^(mssql|kingbasees|dm8)$")
    engines: Optional[list[str]] = Field(
        default=None,
        description="Engines to run before synthesis. Default: all stateless.",
    )
    rewritten_sql: Optional[str] = Field(default=None)


class DecisionResponse(BaseModel):
    """Single actionable migration decision."""

    recommendation: str         # SAFE / REVIEW / BLOCK
    confidence: float           # 0.0–1.0
    migration_path: str         # DIRECT / AUTO_REWRITE / PARTIAL / MANUAL

    primary_risks: list[str]
    blocking_issues: list[str]
    aggregated_severity: str
    risk_counts: dict[str, int]

    execution_strategy: str
    explanation: str

    # Evidence
    score: float
    rewrite_confidence: float
    rewrite_rules_applied: int
    simulation_verdict: str

    # Metadata
    source_db: str
    target_db: str
    original_sql: str
    rewritten_sql: Optional[str] = None
    engines_consulted: list[str]
    warnings: list[str]


@router.post("/decision", response_model=DecisionResponse)
def decide(request: DecisionRequest) -> DecisionResponse:
    """Synthesise a single actionable migration decision from all engines.

    Runs the full kernel analysis (all stateless engines by default), then
    synthesises the outputs into one decision:
      - SAFE   — can migrate with auto-rewrite, high confidence
      - REVIEW — needs human review before migration
      - BLOCK  — has blocking issues, do not migrate yet

    Returns a KernelDecision with recommendation, confidence, migration path,
    risks, execution strategy, and supporting evidence.
    """
    engines = request.engines

    if engines is not None:
        invalid = set(engines) - set(ALL_ENGINES)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown engines: {invalid}. Available: {ALL_ENGINES}",
            )

    # Run kernel analysis
    kernel_result = SQLKernel.analyze(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
        engines=engines,
        rewritten_sql=request.rewritten_sql,
    )

    # Synthesise decision
    decision = synthesize_decision(kernel_result)

    return DecisionResponse(
        recommendation=decision.recommendation,
        confidence=decision.confidence,
        migration_path=decision.migration_path,
        primary_risks=decision.primary_risks,
        blocking_issues=decision.blocking_issues,
        aggregated_severity=decision.aggregated_severity,
        risk_counts=decision.risk_counts,
        execution_strategy=decision.execution_strategy,
        explanation=decision.explanation,
        score=decision.score,
        rewrite_confidence=decision.rewrite_confidence,
        rewrite_rules_applied=decision.rewrite_rules_applied,
        simulation_verdict=decision.simulation_verdict,
        source_db=decision.source_db,
        target_db=decision.target_db,
        original_sql=decision.original_sql,
        rewritten_sql=decision.rewritten_sql,
        engines_consulted=decision.engines_consulted,
        warnings=decision.warnings,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize(obj: object | None) -> object | None:
    """Convert dataclass instances to plain dicts for JSON serialization."""
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    return obj
