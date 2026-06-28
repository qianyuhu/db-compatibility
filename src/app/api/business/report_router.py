"""Report API Router — 复杂报表查询端点。

实现 JOIN + GROUP BY + 聚合查询，验证跨数据库复杂 SQL 兼容性。
"""

from fastapi import APIRouter

from app.core.sql_kernel.kernel import SQLKernel

from .schemas import (
    BusinessOperationResponse,
    CustomerOrderReportRequest,
    InventoryReportRequest,
    SalesReportRequest,
    SingleResult,
)

router = APIRouter(prefix="/api/business", tags=["business-reports"])


def _build_response(
    operation: str,
    source_db: str,
    target_db: str,
    sql: str,
    result: "BusinessExecutionResult",
) -> BusinessOperationResponse:
    """构建统一的 BusinessOperationResponse。"""
    from app.core.sql_kernel.semantic_context import BusinessExecutionResult  # noqa: F811

    src_data = result.source_result or {}
    tgt_data = result.target_result or {}
    return BusinessOperationResponse(
        operation=operation,
        source_db=source_db,
        target_db=target_db,
        generated_sql_source=sql,
        generated_sql_target=result.rewritten_sql,
        source_result=SingleResult(**src_data),
        target_result=SingleResult(**tgt_data),
        kernel_analysis=None,
        equal=result.equal,
        diff_detail=result.diff,
        execution_time_ms=result.execution_time_ms,
    )


# =========================================================================
# 1. Sales Aggregation Report — JOIN + GROUP BY + SUM
# =========================================================================


@router.post(
    "/reports/sales",
    response_model=BusinessOperationResponse,
    summary="销售聚合报表",
    description=(
        "按产品聚合订单金额：JOIN orders + order_items + products，"
        "GROUP BY 产品，SUM 销售额。验证复杂聚合查询的跨库兼容性。"
    ),
)
def sales_aggregation_report(
    request: SalesReportRequest,
) -> BusinessOperationResponse:
    """销售聚合报表: JOIN + GROUP BY + SUM。"""
    conditions = ["o.status != 'CANCELLED'"]
    params_list: list = []

    if request.date_from:
        conditions.append("o.created_at >= %s")
        params_list.append(request.date_from)
    if request.date_to:
        conditions.append("o.created_at <= %s")
        params_list.append(request.date_to)

    where_clause = " AND ".join(conditions)
    sql = (
        "SELECT p.code AS product_code, p.name AS product_name, "
        "COUNT(DISTINCT o.id) AS order_count, "
        "SUM(oi.quantity) AS total_quantity, "
        "SUM(oi.quantity * oi.unit_price) AS total_sales "
        "FROM order_items oi "
        "JOIN orders o ON oi.order_id = o.id "
        "JOIN products p ON oi.product_id = p.id "
        f"WHERE {where_clause} "
        "GROUP BY p.code, p.name "
        "ORDER BY total_sales DESC"
    )

    exec_result = SQLKernel.execute_on_both(
        sql=sql,
        source_db=request.source_db,
        target_db=request.target_db,
        params=tuple(params_list) if params_list else None,
        skip_validation=True,
        analyze_kernel=True,
    )

    return _build_response(
        "sales_aggregation_report",
        request.source_db,
        request.target_db,
        sql,
        exec_result,
    )


# =========================================================================
# 2. Inventory Summary Report — GROUP BY + aggregation
# =========================================================================


@router.post(
    "/reports/inventory",
    response_model=BusinessOperationResponse,
    summary="库存汇总报表",
    description=(
        "按仓库汇总库存：JOIN inventory + products，"
        "GROUP BY 仓库，统计库存数量。验证 GROUP BY 聚合的跨库兼容性。"
    ),
)
def inventory_summary_report(
    request: InventoryReportRequest,
) -> BusinessOperationResponse:
    """库存汇总报表: GROUP BY + 聚合。"""
    conditions: list[str] = []
    params_list: list = []

    if request.warehouse:
        conditions.append("i.warehouse = %s")
        params_list.append(request.warehouse)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = (
        "SELECT i.warehouse, "
        "COUNT(DISTINCT i.product_id) AS product_count, "
        "SUM(i.quantity) AS total_stock, "
        "AVG(i.quantity) AS avg_stock, "
        "MIN(i.quantity) AS min_stock, "
        "MAX(i.quantity) AS max_stock "
        "FROM inventory i "
        f"WHERE {where_clause} "
        "GROUP BY i.warehouse "
        "ORDER BY i.warehouse"
    )

    exec_result = SQLKernel.execute_on_both(
        sql=sql,
        source_db=request.source_db,
        target_db=request.target_db,
        params=tuple(params_list) if params_list else None,
        skip_validation=True,
        analyze_kernel=True,
    )

    return _build_response(
        "inventory_summary_report",
        request.source_db,
        request.target_db,
        sql,
        exec_result,
    )


# =========================================================================
# 3. Customer Order Summary — multi-table JOIN + aggregation
# =========================================================================


@router.post(
    "/reports/customer-orders",
    response_model=BusinessOperationResponse,
    summary="客户订单汇总报表",
    description=(
        "按客户汇总订单：JOIN customers + orders + order_items + products，"
        "GROUP BY 客户，统计订单数和金额。验证多表 JOIN 的跨库兼容性。"
    ),
)
def customer_order_report(
    request: CustomerOrderReportRequest,
) -> BusinessOperationResponse:
    """客户订单汇总: 多表 JOIN + 聚合。"""
    conditions: list[str] = []
    params_list: list = []

    if request.customer_code:
        conditions.append("c.code = %s")
        params_list.append(request.customer_code)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = (
        "SELECT c.code AS customer_code, c.name AS customer_name, "
        "COUNT(DISTINCT o.id) AS order_count, "
        "COALESCE(SUM(o.total_amount), 0) AS total_spent, "
        "COALESCE(AVG(o.total_amount), 0) AS avg_order_value, "
        "COALESCE(SUM(o.item_count), 0) AS total_items "
        "FROM customers c "
        "LEFT JOIN orders o ON c.id = o.customer_id "
        f"WHERE {where_clause} "
        "GROUP BY c.code, c.name "
        "ORDER BY total_spent DESC"
    )

    exec_result = SQLKernel.execute_on_both(
        sql=sql,
        source_db=request.source_db,
        target_db=request.target_db,
        params=tuple(params_list) if params_list else None,
        skip_validation=True,
        analyze_kernel=True,
    )

    return _build_response(
        "customer_order_report",
        request.source_db,
        request.target_db,
        sql,
        exec_result,
    )
