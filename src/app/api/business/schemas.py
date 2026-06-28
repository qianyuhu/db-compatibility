"""Pydantic schemas for Business API — ERP 业务操作。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# =========================================================================
# Order
# =========================================================================


class OrderItemInput(BaseModel):
    """订单行项目输入。"""

    product_code: str = Field(..., description="产品编码")
    quantity: int = Field(..., gt=0, description="数量")
    unit_price: float = Field(..., gt=0, description="单价")


class CreateOrderRequest(BaseModel):
    """创建订单请求。"""

    customer_code: str = Field(..., description="客户编码")
    items: list[OrderItemInput] = Field(..., min_length=1, description="订单行项目")
    notes: Optional[str] = Field(default=None, description="备注")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class OrderListRequest(BaseModel):
    """订单列表查询请求。"""

    customer_id: int = Field(..., description="客户 ID")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


# =========================================================================
# Inventory
# =========================================================================


class StockQueryRequest(BaseModel):
    """库存查询请求。"""

    product_code: str = Field(..., description="产品编码")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class StockAdjustRequest(BaseModel):
    """库存调整请求。"""

    product_code: str = Field(..., description="产品编码")
    delta: int = Field(..., description="变动量（正=入库，负=出库）")
    reason: str = Field(default="", description="调整原因")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


# =========================================================================
# Migration
# =========================================================================


class MigrationRunRequest(BaseModel):
    """迁移流水线执行请求。"""

    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")
    phases: Optional[list[str]] = Field(
        default=None,
        description="要执行的阶段: schema, data, validation, report。默认全部。",
    )


# =========================================================================
# Customer (Master Data)
# =========================================================================


class CustomerCreateRequest(BaseModel):
    """创建客户请求。"""

    code: str = Field(..., description="客户编码")
    name: str = Field(..., description="客户名称")
    contact: Optional[str] = Field(default=None, description="联系人")
    phone: Optional[str] = Field(default=None, description="电话")
    email: Optional[str] = Field(default=None, description="邮箱")
    is_active: bool = Field(default=True, description="是否启用")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class CustomerListRequest(BaseModel):
    """客户列表查询请求。"""

    code: Optional[str] = Field(default=None, description="按编码筛选")
    name: Optional[str] = Field(default=None, description="按名称模糊搜索")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


# =========================================================================
# Product (Master Data)
# =========================================================================


class ProductCreateRequest(BaseModel):
    """创建产品请求。"""

    code: str = Field(..., description="产品编码")
    name: str = Field(..., description="产品名称")
    price: float = Field(..., gt=0, description="价格")
    is_active: bool = Field(default=True, description="是否启用")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class ProductListRequest(BaseModel):
    """产品列表查询请求。"""

    code: Optional[str] = Field(default=None, description="按编码筛选")
    name: Optional[str] = Field(default=None, description="按名称模糊搜索")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


# =========================================================================
# Complex Report Queries
# =========================================================================


class SalesReportRequest(BaseModel):
    """销售聚合报表请求。"""

    date_from: Optional[str] = Field(default=None, description="开始日期 (YYYY-MM-DD)")
    date_to: Optional[str] = Field(default=None, description="结束日期 (YYYY-MM-DD)")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class InventoryReportRequest(BaseModel):
    """库存汇总报表请求。"""

    warehouse: Optional[str] = Field(default=None, description="仓库筛选")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


class CustomerOrderReportRequest(BaseModel):
    """客户订单汇总报表请求。"""

    customer_code: Optional[str] = Field(default=None, description="客户编码")
    source_db: str = Field(default="mssql", pattern=r"^(mssql|kingbasees|dm8)$")
    target_db: str = Field(default="kingbasees", pattern=r"^(mssql|kingbasees|dm8)$")


# =========================================================================
# Response
# =========================================================================


class SingleResult(BaseModel):
    """单数据库执行结果。"""

    success: bool = False
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    db_type: str = ""
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    suggestion: Optional[str] = None


class BusinessOperationResponse(BaseModel):
    """业务操作响应 — 双库执行对比结果。"""

    operation: str
    source_db: str
    target_db: str
    generated_sql_source: str
    generated_sql_target: Optional[str] = None
    source_result: SingleResult
    target_result: SingleResult
    kernel_analysis: Optional[dict[str, Any]] = None
    equal: bool
    diff_detail: list[dict[str, Any]] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    success: bool = True


class MigrationPhaseSummary(BaseModel):
    """迁移阶段摘要。"""

    name: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    elapsed_ms: float = 0.0


class MigrationPipelineResponse(BaseModel):
    """迁移流水线响应。"""

    source_db: str
    target_db: str
    phases: list[MigrationPhaseSummary] = Field(default_factory=list)
    overall_status: str = "pending"
    total_time_ms: float = 0.0
    warnings: list[str] = Field(default_factory=list)
