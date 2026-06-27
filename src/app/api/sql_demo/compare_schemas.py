"""
Pydantic schemas for SQL Compare API.

Request/Response models for the multi-database SQL comparison endpoint.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    """SQL 对比请求 — 同一 SQL 在多个数据库上执行。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要执行的 SQL 语句",
    )
    db_types: list[str] = Field(
        ...,
        min_length=2,
        max_length=3,
        description="目标数据库列表，至少 2 个: mssql / kingbasees / dm8",
    )


class SingleResult(BaseModel):
    """单个数据库的执行结果。"""

    success: bool = Field(..., description="执行是否成功")
    columns: list[str] = Field(default_factory=list, description="列名列表")
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    row_count: int = Field(default=0, description="返回行数")
    execution_time_ms: float = Field(default=0.0, description="执行耗时（毫秒）")
    error: Optional[str] = Field(default=None, description="错误信息")
    suggestion: Optional[str] = Field(default=None, description="修复建议")


class ColumnDiff(BaseModel):
    """列差异详情。"""

    db_type: str = Field(..., description="数据库类型")
    columns: list[str] = Field(default_factory=list, description="该库的列名列表")
    missing_from_others: list[str] = Field(
        default_factory=list,
        description="该库有但其他库缺失的列",
    )


class ValueDiffItem(BaseModel):
    """单个值的差异。"""

    row_index: int = Field(..., description="行索引（从 0 开始）")
    column: str = Field(..., description="列名")
    values: dict[str, Any] = Field(
        default_factory=dict,
        description="各数据库在该位置的值: {db_type: value}",
    )


class SqlRewrite(BaseModel):
    """SQL 改写建议。"""

    original: str = Field(..., description="原始 SQL")
    db_type: str = Field(..., description="目标数据库类型")
    suggested: str = Field(..., description="改写后的 SQL")
    reason: str = Field(..., description="改写原因（中文）")


class DiffResult(BaseModel):
    """差异分析结果。"""

    row_count_diff: bool = Field(
        default=False,
        description="行数是否存在差异",
    )
    row_count_details: dict[str, int] = Field(
        default_factory=dict,
        description="各数据库的行数: {db_type: row_count}",
    )
    column_diff: bool = Field(
        default=False,
        description="列名是否存在差异",
    )
    column_details: list[ColumnDiff] = Field(
        default_factory=list,
        description="各数据库的列差异详情",
    )
    value_diff: list[ValueDiffItem] = Field(
        default_factory=list,
        description="值差异列表（按行列对齐）",
    )


class CompareResponse(BaseModel):
    """SQL 对比结果。"""

    results: dict[str, SingleResult] = Field(
        default_factory=dict,
        description="各数据库执行结果: {db_type: SingleResult}",
    )
    diff: DiffResult = Field(
        default_factory=DiffResult,
        description="差异分析结果",
    )
    rewrites: list[SqlRewrite] = Field(
        default_factory=list,
        description="SQL 方言改写建议",
    )
