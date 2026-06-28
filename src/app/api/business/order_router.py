"""Order API Router — 订单业务操作端点。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.services.order_service import OrderService

from .schemas import (
    BusinessOperationResponse,
    CreateOrderRequest,
    OrderListRequest,
    SingleResult,
)

router = APIRouter(prefix="/api/business", tags=["business-orders"])


@router.post(
    "/orders",
    response_model=BusinessOperationResponse,
    summary="创建订单",
    description=(
        "通过表单数据创建订单。系统自动查找客户、计算总额，"
        "生成 INSERT SQL 并在源库和目标库执行，返回对比结果。"
    ),
)
def create_order(
    request: CreateOrderRequest,
    session: Optional[Session] = Depends(get_session),
) -> BusinessOperationResponse:
    """创建订单并在双库执行对比。"""
    if session is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "当前配置的数据库不支持 ORM Session。"
                "请将 APP_ACTIVE_DB 设为 mssql 或 dm8，"
                "或通过 /api/sql/execute 直接执行 SQL。"
            ),
        )

    svc = OrderService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    items = [
        {
            "product_code": item.product_code,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
        }
        for item in request.items
    ]

    result = svc.create_order(
        session=session,
        customer_code=request.customer_code,
        items=items,
        notes=request.notes,
    )

    # 转换 source_result / target_result 为 Pydantic 模型
    src = SingleResult(**result.source_result) if result.source_result else SingleResult()
    tgt = SingleResult(**result.target_result) if result.target_result else SingleResult()

    kernel_dict = None
    if result.kernel_analysis is not None:
        try:
            from dataclasses import asdict

            kernel_dict = asdict(result.kernel_analysis)
        except Exception:
            kernel_dict = None

    return BusinessOperationResponse(
        operation=result.operation,
        source_db=result.source_db,
        target_db=result.target_db,
        generated_sql_source=result.generated_sql_source,
        generated_sql_target=result.generated_sql_target,
        source_result=src,
        target_result=tgt,
        kernel_analysis=kernel_dict,
        equal=result.equal,
        diff_detail=result.diff_detail,
        execution_time_ms=result.execution_time_ms,
    )


@router.post(
    "/orders/list",
    response_model=BusinessOperationResponse,
    summary="查询客户订单",
    description="生成 SELECT 查询并在双库执行对比。",
)
def list_customer_orders(
    request: OrderListRequest,
) -> BusinessOperationResponse:
    """查询客户订单列表，双库对比。"""
    svc = OrderService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    result = svc.query_orders_by_customer(
        customer_id=request.customer_id,
    )

    src = SingleResult(**result.source_result) if result.source_result else SingleResult()
    tgt = SingleResult(**result.target_result) if result.target_result else SingleResult()

    return BusinessOperationResponse(
        operation=result.operation,
        source_db=result.source_db,
        target_db=result.target_db,
        generated_sql_source=result.generated_sql_source,
        generated_sql_target=result.generated_sql_target,
        source_result=src,
        target_result=tgt,
        kernel_analysis=None,
        equal=result.equal,
        diff_detail=result.diff_detail,
        execution_time_ms=result.execution_time_ms,
    )
