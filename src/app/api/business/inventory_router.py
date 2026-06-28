"""Inventory API Router — 库存查询/调整端点。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.services.inventory_service import InventoryService

from .schemas import (
    BusinessOperationResponse,
    SingleResult,
    StockAdjustRequest,
    StockQueryRequest,
)

router = APIRouter(prefix="/api/business", tags=["business-inventory"])


def _require_session(session: Optional[Session]) -> Session:
    """确保 session 可用，否则返回 400 错误。"""
    if session is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "当前配置的数据库不支持 ORM Session。"
                "请将 APP_ACTIVE_DB 设为 mssql 或 dm8。"
            ),
        )
    return session


@router.post(
    "/inventory/query",
    response_model=BusinessOperationResponse,
    summary="查询产品库存",
    description="按产品编码查询库存，在源库和目标库执行并对比。",
)
def query_stock(
    request: StockQueryRequest,
    session: Optional[Session] = Depends(get_session),
) -> BusinessOperationResponse:
    session = _require_session(session)
    """查询产品库存，双库对比。"""
    svc = InventoryService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    result = svc.check_stock(
        session=session,
        product_code=request.product_code,
    )

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
    "/inventory/adjust",
    response_model=BusinessOperationResponse,
    summary="调整库存",
    description="调整产品库存数量，生成 UPDATE SQL 并在双库执行对比。",
)
def adjust_stock(
    request: StockAdjustRequest,
    session: Optional[Session] = Depends(get_session),
) -> BusinessOperationResponse:
    session = _require_session(session)
    """调整库存，双库对比。"""
    svc = InventoryService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    result = svc.adjust_stock(
        session=session,
        product_code=request.product_code,
        delta=request.delta,
        reason=request.reason,
    )

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
