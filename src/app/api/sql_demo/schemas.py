"""
Pydantic schemas for SQL Demo API.

Request/Response models for the unified SQL execution endpoint.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """SQL 执行请求 — 指定目标数据库和 SQL 语句。"""

    db_type: str = Field(
        ...,
        pattern=r"^(mssql|kingbasees|dm8)$",
        description="目标数据库: mssql | kingbasees | dm8",
    )
    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要执行的 SQL 语句",
    )
    params: Optional[dict[str, Any]] = Field(
        default=None,
        description="可选的查询参数（预留，当前版本不使用）",
    )


class ExecuteResponse(BaseModel):
    """SQL 执行结果 — 统一格式，跨三库一致。"""

    success: bool = Field(..., description="执行是否成功")
    columns: list[str] = Field(default_factory=list, description="列名列表")
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    row_count: int = Field(default=0, description="返回行数")
    db_type: str = Field(default="", description="实际执行的数据库类型")
    execution_time_ms: float = Field(default=0.0, description="执行耗时（毫秒）")
    error: Optional[str] = Field(default=None, description="错误信息")
    suggestion: Optional[str] = Field(default=None, description="修复建议")
