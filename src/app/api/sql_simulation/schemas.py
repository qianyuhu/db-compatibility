"""
Pydantic schemas for SQL Migration Simulation API — POST /api/sql/migrate/simulate
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SimulationVerdict(str, Enum):
    """Final verdict after simulating migration execution."""

    SAFE_TO_EXECUTE = "SAFE_TO_EXECUTE"
    SAFE_TO_EXECUTE_WITH_MONITORING = "SAFE_TO_EXECUTE_WITH_MONITORING"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    HIGH_RISK_DO_NOT_EXECUTE = "HIGH_RISK_DO_NOT_EXECUTE"


class RiskLevel(str, Enum):
    """Risk classification (shared with migration module)."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FailureType(str, Enum):
    """Categorised failure modes detected during simulation."""

    NULL_COMPARISON = "NULL_COMPARISON"
    PAGINATION_SHIFT = "PAGINATION_SHIFT"
    TIMEZONE_DRIFT = "TIMEZONE_DRIFT"
    JOIN_MULTIPLICITY_CHANGE = "JOIN_MULTIPLICITY_CHANGE"
    FUNCTION_SEMANTIC_CHANGE = "FUNCTION_SEMANTIC_CHANGE"
    TYPE_CAST_ISSUE = "TYPE_CAST_ISSUE"
    COLLATION_MISMATCH = "COLLATION_MISMATCH"
    AGGREGATION_INSTABILITY = "AGGREGATION_INSTABILITY"


class DriftLevel(str, Enum):
    """Severity of data drift for a table or column."""

    STABLE = "STABLE"           # No expected drift
    LOW_DRIFT = "LOW_DRIFT"     # < 1% variance
    MODERATE_DRIFT = "MODERATE_DRIFT"  # 1-5% variance
    HIGH_DRIFT = "HIGH_DRIFT"   # > 5% variance


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class SimulationRequest(BaseModel):
    """SQL 迁移仿真请求。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="原始 SQL（源数据库方言）",
    )
    source_db: str = Field(
        ...,
        pattern=r"^(mssql|kingbasees|dm8)$",
        description="源数据库类型",
    )
    target_db: str = Field(
        ...,
        pattern=r"^(mssql|kingbasees|dm8)$",
        description="目标数据库类型",
    )
    rewritten_sql: Optional[str] = Field(
        default=None,
        description="改写后的 SQL（如已从 /migrate/plan 获取）",
    )


# ---------------------------------------------------------------------------
# Execution Model
# ---------------------------------------------------------------------------


class EquivalenceDetail(BaseModel):
    """Detailed equivalence check between original and rewritten SQL."""

    ast_match: bool = Field(default=True, description="AST 结构是否等价")
    function_mapping_consistent: bool = Field(
        default=True, description="函数映射是否一致"
    )
    column_mapping_preserved: bool = Field(
        default=True, description="列映射是否保留"
    )
    issues: list[str] = Field(default_factory=list)


class CardinalityEstimate(BaseModel):
    """Estimated row count impact of the rewrite."""

    original_estimated_rows: int = Field(default=0)
    rewritten_estimated_rows: int = Field(default=0)
    variance_pct: float = Field(default=0.0, description="行数变化百分比")
    join_graph_tables: list[str] = Field(default_factory=list)
    description: str = Field(default="")


class ExecutionModel(BaseModel):
    """Execution-level simulation model."""

    equivalence: EquivalenceDetail = Field(default_factory=EquivalenceDetail)
    cardinality: CardinalityEstimate = Field(default_factory=CardinalityEstimate)


# ---------------------------------------------------------------------------
# Drift Analysis
# ---------------------------------------------------------------------------


class TableDrift(BaseModel):
    """Per-table data drift assessment."""

    table: str = Field(..., description="表名")
    drift: DriftLevel = Field(default=DriftLevel.STABLE)
    expected_variance: str = Field(default="0%", description="预期方差，如 '2.1%'")
    reason: str = Field(default="")


class RowLevelDiff(BaseModel):
    """Row-level data difference summary."""

    expected_variance: str = Field(
        default="0%", description="整体预期行数方差"
    )
    affected_tables: list[str] = Field(default_factory=list)
    table_drifts: list[TableDrift] = Field(default_factory=list)
    description: str = Field(default="")


# ---------------------------------------------------------------------------
# Query Behavior
# ---------------------------------------------------------------------------


class QueryBehavior(BaseModel):
    """Predicted query behavior changes after migration."""

    join_cardinality_shift: Optional[str] = Field(
        default=None, description="JOIN 基数变化，如 '+3.2%'"
    )
    null_semantics_change: bool = Field(
        default=False, description="NULL 语义是否发生变化"
    )
    aggregation_stability: str = Field(
        default="HIGH", description="聚合稳定性: HIGH / MEDIUM / LOW"
    )
    ordering_stability: str = Field(
        default="HIGH", description="排序稳定性: HIGH / MEDIUM / LOW"
    )
    type_coercion_changes: list[str] = Field(
        default_factory=list, description="类型转换变化列表"
    )


# ---------------------------------------------------------------------------
# Failure Points
# ---------------------------------------------------------------------------


class FailurePoint(BaseModel):
    """A single predicted failure point."""

    type: FailureType = Field(..., description="失败类型")
    location: str = Field(..., description="失败位置，如 'users.created_at'")
    severity: RiskLevel = Field(..., description="严重程度")
    description: str = Field(..., description="失败描述")
    mitigation: Optional[str] = Field(default=None, description="缓解建议")


# ---------------------------------------------------------------------------
# Simulation Result
# ---------------------------------------------------------------------------


class SimulationResult(BaseModel):
    """Structured simulation findings."""

    row_level_diff: RowLevelDiff = Field(default_factory=RowLevelDiff)
    query_behavior: QueryBehavior = Field(default_factory=QueryBehavior)
    failure_points: list[FailurePoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class SimulationResponse(BaseModel):
    """SQL 迁移仿真完整响应。"""

    # Scores
    equivalence_score: float = Field(
        default=1.0, ge=0.0, le=1.0, description="等价性评分 0.0-1.0"
    )
    risk_level: RiskLevel = Field(default=RiskLevel.NONE)

    # Details
    simulation: SimulationResult = Field(default_factory=SimulationResult)

    # Execution model details
    execution_model: ExecutionModel = Field(default_factory=ExecutionModel)

    # Verdict
    recommendation: SimulationVerdict = Field(
        default=SimulationVerdict.SAFE_TO_EXECUTE
    )

    # Metadata
    source_db: str = Field(default="")
    target_db: str = Field(default="")
    original_sql: str = Field(default="")
    rewritten_sql: Optional[str] = Field(default=None)

    warnings: list[str] = Field(default_factory=list)
