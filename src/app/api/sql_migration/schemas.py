"""
Pydantic schemas for SQL Migration Decision API — POST /api/sql/migrate/plan
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Recommendation(str, Enum):
    """Migration recommendation level."""

    SAFE_AUTO_MIGRATION = "SAFE_AUTO_MIGRATION"
    NEED_REVIEW = "NEED_REVIEW"
    HIGH_RISK = "HIGH_RISK"


class RiskLevel(str, Enum):
    """Migration risk level."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StepAction(str, Enum):
    """Types of actions in a migration plan step."""

    REWRITE_SQL = "rewrite_sql"
    VALIDATE_EXECUTION = "validate_execution"
    MANUAL_REVIEW = "manual_review"
    TEST_RECOMMENDED = "test_recommended"
    UPDATE_SCHEMA = "update_schema"
    VERIFY_RESULTS = "verify_results"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class MigrationPlanRequest(BaseModel):
    """SQL 迁移计划请求。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要迁移的 SQL 语句",
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


# ---------------------------------------------------------------------------
# Impact Analysis
# ---------------------------------------------------------------------------


class JoinChainRisk(BaseModel):
    """Risk assessment for a chain of JOINed tables."""

    chain: list[str] = Field(..., description="JOIN 链中的表名列表")
    risk_level: RiskLevel = Field(default=RiskLevel.NONE)
    description: str = Field(default="")


class ImpactAnalysis(BaseModel):
    """Migration impact assessment across all object types."""

    tables: list[str] = Field(default_factory=list, description="所有涉及的表")
    critical_tables: list[str] = Field(
        default_factory=list, description="存在高风险的 critical 表"
    )
    functions: list[str] = Field(default_factory=list, description="受影响的函数列表")
    risk_hotspots: list[str] = Field(
        default_factory=list,
        description="风险热点，格式 'table.column' 或 'function_name'",
    )
    join_chains: list[JoinChainRisk] = Field(default_factory=list)
    total_objects: int = Field(default=0)
    high_risk_count: int = Field(default=0)
    medium_risk_count: int = Field(default=0)


# ---------------------------------------------------------------------------
# Migration Plan
# ---------------------------------------------------------------------------


class MigrationStep(BaseModel):
    """Single step in the migration plan."""

    step: int = Field(..., description="步骤编号")
    action: StepAction = Field(..., description="动作类型")
    description: str = Field(..., description="步骤描述")
    detail: Optional[str] = Field(default=None, description="详细说明 / 改写前后对比")
    automatic: bool = Field(default=True, description="是否可自动执行")


class MigrationPlan(BaseModel):
    """Ordered migration plan with steps and effort estimate."""

    steps: list[MigrationStep] = Field(default_factory=list)
    estimated_effort: str = Field(default="LOW", description="预估工作量: LOW / MEDIUM / HIGH")
    total_steps: int = Field(default=0)
    automatic_steps: int = Field(default=0)
    manual_steps: int = Field(default=0)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class MigrationPlanResponse(BaseModel):
    """SQL 迁移计划完整响应。"""

    # Decision
    migration_feasible: bool = Field(..., description="迁移是否可行")
    risk_level: RiskLevel = Field(..., description="整体风险等级")
    confidence: float = Field(..., description="置信度 0.0-1.0")
    recommendation: Recommendation = Field(..., description="推荐操作")
    estimated_score: float = Field(default=100.0, ge=0.0, le=100.0, description="预估兼容性评分 0-100")

    # Source / target info
    source_db: str = Field(..., description="源数据库")
    target_db: str = Field(..., description="目标数据库")
    original_sql: str = Field(..., description="原始 SQL")
    rewritten_sql: Optional[str] = Field(default=None, description="改写后的 SQL（如适用）")

    # Analysis
    impact: ImpactAnalysis = Field(default_factory=ImpactAnalysis)

    # Plan
    plan: MigrationPlan = Field(default_factory=MigrationPlan)

    # Warnings
    warnings: list[str] = Field(default_factory=list)
