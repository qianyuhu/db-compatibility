"""
Pydantic schemas for SQL Diagnostics API — POST /api/sql/diagnose
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Risk level enum
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Object-level risk classification for cross-DB compatibility."""

    NONE = "NONE"        # Fully compatible — no changes needed
    LOW = "LOW"          # Compatible with minor syntax changes (has rewrite rule ≥0.9)
    MEDIUM = "MEDIUM"    # Needs manual review or partial rewrite (has rewrite rule <0.9)
    HIGH = "HIGH"        # Incompatible — requires significant rewrite (no known rule)
    CRITICAL = "CRITICAL"  # Cannot be migrated — fundamental incompatibility


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class DiagnoseRequest(BaseModel):
    """SQL 对象级诊断请求。"""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="要诊断的 SQL 语句",
    )
    db_types: list[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="目标数据库类型列表，如 ['mssql', 'kingbasees', 'dm8']",
        examples=[["mssql", "kingbasees"]],
    )


# ---------------------------------------------------------------------------
# Response sub-models — objects
# ---------------------------------------------------------------------------


class DbCompatibility(BaseModel):
    """Per-database compatibility status for a single object."""

    db_type: str = Field(..., description="数据库类型")
    compatible: bool = Field(..., description="该对象在此数据库中是否兼容")
    issue: Optional[str] = Field(default=None, description="不兼容的具体原因")


class TableDiagnostic(BaseModel):
    """Table-level diagnostic result."""

    name: str = Field(..., description="表名")
    alias: Optional[str] = Field(default=None, description="别名")
    risk: RiskLevel = Field(..., description="最高风险等级")
    issues: list[str] = Field(default_factory=list, description="该表相关的所有问题")
    db_compatibility: dict[str, bool] = Field(
        default_factory=dict,
        description="各数据库兼容性 {db_type: is_compatible}",
    )


class ColumnDiagnostic(BaseModel):
    """Column-level diagnostic result."""

    name: str = Field(..., description="列全名，如 'users.id'")
    column: str = Field(..., description="列名（不含表前缀）")
    table_ref: Optional[str] = Field(default=None, description="所属表名或别名")
    risk: RiskLevel = Field(..., description="风险等级")
    issues: list[str] = Field(default_factory=list)
    db_compatibility: dict[str, bool] = Field(default_factory=dict)


class FunctionDiagnostic(BaseModel):
    """Function-level diagnostic result."""

    name: str = Field(..., description="函数名，如 'GETDATE'")
    raw: str = Field(..., description="原始调用文本，如 'GETDATE()'")
    risk: RiskLevel = Field(..., description="风险等级")
    issues: list[str] = Field(default_factory=list)
    db_compatibility: dict[str, bool] = Field(default_factory=dict)
    has_rewrite_rule: bool = Field(
        default=False,
        description="是否存在自动改写规则",
    )


class JoinDiagnostic(BaseModel):
    """Join-level diagnostic result."""

    join_type: str = Field(..., description="JOIN 类型: INNER / LEFT / RIGHT / FULL / CROSS")
    table: str = Field(..., description="被 JOIN 的表名")
    alias: Optional[str] = Field(default=None)
    condition: Optional[str] = Field(default=None, description="ON 条件")
    risk: RiskLevel = Field(..., description="风险等级")
    issues: list[str] = Field(default_factory=list)
    db_compatibility: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response sub-models — summary
# ---------------------------------------------------------------------------


class RiskSummary(BaseModel):
    """按风险等级统计的对象数量。"""

    none: int = Field(default=0, alias="NONE")
    low: int = Field(default=0, alias="LOW")
    medium: int = Field(default=0, alias="MEDIUM")
    high: int = Field(default=0, alias="HIGH")
    critical: int = Field(default=0, alias="CRITICAL")

    model_config = ConfigDict(populate_by_name=True)


class DiagnoseSummary(BaseModel):
    """诊断结果汇总。"""

    total_objects: int = Field(default=0)
    tables: RiskSummary = Field(default_factory=RiskSummary)
    columns: RiskSummary = Field(default_factory=RiskSummary)
    functions: RiskSummary = Field(default_factory=RiskSummary)
    joins: RiskSummary = Field(default_factory=RiskSummary)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class DiagnoseResponse(BaseModel):
    """SQL 对象级诊断完整结果。"""

    sql: str = Field(..., description="原始 SQL")
    db_types: list[str] = Field(..., description="诊断的目标数据库类型")
    tables: list[TableDiagnostic] = Field(default_factory=list)
    columns: list[ColumnDiagnostic] = Field(default_factory=list)
    functions: list[FunctionDiagnostic] = Field(default_factory=list)
    joins: list[JoinDiagnostic] = Field(default_factory=list)
    summary: DiagnoseSummary = Field(default_factory=DiagnoseSummary)
