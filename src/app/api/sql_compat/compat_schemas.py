"""
Pydantic schemas for SQL Compatibility Engine API.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class CompatibilityAnalysisRequest(BaseModel):
    """SQL 兼容性分析请求。"""

    sql: str = Field(..., min_length=1, max_length=10000, description="SQL 语句")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")
    execute: bool = Field(
        default=False,
        description="是否在双库上实际执行并对比结果",
    )


class FeatureDetectionResponse(BaseModel):
    """检测到的 SQL 特性。"""

    category: str = Field(..., description="特性类别")
    count: int = Field(default=1)
    details: list[str] = Field(default_factory=list)
    risk: str = Field(default="none")


class ClassificationResponse(BaseModel):
    """SQL 分类结果。"""

    categories: list[str] = Field(default_factory=list)
    features: list[FeatureDetectionResponse] = Field(default_factory=list)
    statement_type: str = "UNKNOWN"
    complexity: str = "simple"
    total_features: int = 0
    risk_summary: dict[str, int] = Field(default_factory=dict)


class DimensionScoreResponse(BaseModel):
    """评分维度详情。"""

    name: str
    raw_score: float
    max_score: float
    weight: float
    percentage: float
    deductions: list[str] = Field(default_factory=list)


class ScoreResponse(BaseModel):
    """兼容性评分结果。"""

    total_score: float
    dimensions: list[DimensionScoreResponse] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    overall_risk: str = "NONE"
    summary: str = ""
    supported_features: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    rewritten_features: list[str] = Field(default_factory=list)


class CompatibilityAnalysisResponse(BaseModel):
    """SQL 兼容性分析完整响应。"""

    original_sql: str
    source_db: str
    target_db: str
    rewritten_sql: Optional[str] = None
    classification: Optional[ClassificationResponse] = None
    score: Optional[ScoreResponse] = None
    execution_result: Optional[dict[str, Any]] = None
    enhanced_diff: Optional[dict[str, Any]] = None
    total_time_ms: float = 0.0
    warnings: list[str] = Field(default_factory=list)
