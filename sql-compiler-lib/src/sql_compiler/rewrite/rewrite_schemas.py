"""
Pydantic schemas for SQL Rewrite API.

Request/Response models for the POST /api/sql/rewrite endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class RewriteRequest(BaseModel):
    """SQL 跨数据库改写请求。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要改写的原始 SQL 语句",
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
# Response sub-models
# ---------------------------------------------------------------------------


class AppliedRule(BaseModel):
    """单条已应用的改写规则。"""

    name: str = Field(
        ...,
        description="规则名称，如 'TOP → LIMIT'",
    )
    description: str = Field(
        default="",
        description="规则说明（中文）",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="该规则的置信度 (0.0-1.0)",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class RewriteResponse(BaseModel):
    """SQL 改写结果。"""

    original_sql: str = Field(
        ...,
        description="原始 SQL",
    )
    rewritten_sql: str = Field(
        ...,
        description="改写后的 SQL",
    )
    source_db: str = Field(
        ...,
        description="源数据库类型",
    )
    target_db: str = Field(
        ...,
        description="目标数据库类型",
    )
    rules_applied: list[AppliedRule] = Field(
        default_factory=list,
        description="已应用的改写规则列表",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="整体改写置信度 (0.0-1.0)，为所有规则置信度的几何平均",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="改写过程中的警告信息",
    )
