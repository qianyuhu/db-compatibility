"""
Pydantic schemas for SQL Compatibility Score API.

Request/Response models for the /api/sql/score endpoint.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class ScoreRequest(BaseModel):
    """SQL 兼容性评分请求。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要评估的 SQL 语句",
    )
    db_types: list[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="目标数据库列表: mssql / kingbasees / dm8",
    )


# ---------------------------------------------------------------------------
# Scoring sub-models
# ---------------------------------------------------------------------------


class ScoreBreakdown(BaseModel):
    """四维度评分明细。"""

    syntax: float = Field(default=100.0, ge=0, le=100, description="语法兼容性得分")
    execution: float = Field(default=100.0, ge=0, le=100, description="执行成功得分")
    result: float = Field(default=100.0, ge=0, le=100, description="结果一致性得分")
    risk: float = Field(default=100.0, ge=0, le=100, description="风险评估得分")


class Finding(BaseModel):
    """单个兼容性发现。"""

    type: str = Field(
        ...,
        description="发现类型: syntax | execution | result | risk",
    )
    db: str = Field(
        ...,
        description="涉及的数据库: mssql | kingbasees | dm8",
    )
    issue: str = Field(..., description="问题描述")
    severity: str = Field(
        ...,
        description="严重程度: low | medium | high | critical",
    )
    detail: Optional[str] = Field(
        default=None,
        description="补充细节",
    )


class ScoreResponse(BaseModel):
    """SQL 兼容性评分结果。"""

    score: float = Field(
        ...,
        ge=0,
        le=100,
        description="综合兼容性得分 (0-100)",
    )
    level: str = Field(
        ...,
        description="兼容性等级: LOW | MEDIUM | HIGH | CRITICAL",
    )
    breakdown: ScoreBreakdown = Field(
        default_factory=ScoreBreakdown,
        description="四维度评分明细",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="兼容性问题发现列表",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="改写建议",
    )
    db_count: int = Field(
        default=0,
        description="评估涉及的数据库数量",
    )
    execution_time_ms: float = Field(
        default=0.0,
        description="评分总耗时（毫秒）",
    )
