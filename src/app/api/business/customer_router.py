"""Customer API Router — 客户主数据管理端点。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.sql_kernel.kernel import SQLKernel
from app.repositories.customer import CustomerRepository

from .schemas import (
    BusinessOperationResponse,
    CustomerCreateRequest,
    CustomerListRequest,
    SingleResult,
)

router = APIRouter(prefix="/api/business", tags=["business-customers"])


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
    "/customers/list",
    response_model=BusinessOperationResponse,
    summary="查询客户列表",
    description="按编码或名称查询客户，生成 SELECT SQL 并在双库执行对比。",
)
def list_customers(
    request: CustomerListRequest,
    session: Optional[Session] = Depends(get_session),
) -> BusinessOperationResponse:
    """查询客户列表，双库对比。"""
    session = _require_session(session)

    # 构建参数化 SELECT
    conditions: list[str] = []
    params: list = []

    if request.code:
        conditions.append("code = %s")
        params.append(request.code)
    if request.name:
        conditions.append("name LIKE %s")
        params.append(f"%{request.name}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = (
        "SELECT id, code, name, contact, phone, email, is_active, created_at "
        "FROM customers "
        f"WHERE {where_clause} "
        "ORDER BY code"
    )

    exec_result = SQLKernel.execute_on_both(
        sql=sql,
        source_db=request.source_db,
        target_db=request.target_db,
        params=tuple(params) if params else None,
        skip_validation=True,
        analyze_kernel=True,
    )

    src_data = exec_result.source_result or {}
    tgt_data = exec_result.target_result or {}
    src = SingleResult(**src_data)
    tgt = SingleResult(**tgt_data)

    return BusinessOperationResponse(
        operation="list_customers",
        source_db=request.source_db,
        target_db=request.target_db,
        generated_sql_source=sql,
        generated_sql_target=exec_result.rewritten_sql,
        source_result=src,
        target_result=tgt,
        kernel_analysis=None,
        equal=exec_result.equal,
        diff_detail=exec_result.diff,
        execution_time_ms=exec_result.execution_time_ms,
    )


@router.post(
    "/customers/create",
    response_model=BusinessOperationResponse,
    summary="创建客户",
    description="创建客户记录，ORM 持久化到源库，生成 INSERT SQL 并在双库执行对比。",
)
def create_customer(
    request: CustomerCreateRequest,
    session: Optional[Session] = Depends(get_session),
) -> BusinessOperationResponse:
    """创建客户，双库对比。"""
    session = _require_session(session)

    # 1. ORM 持久化到源库
    repo = CustomerRepository(session)
    customer = repo.create({
        "code": request.code,
        "name": request.name,
        "contact": request.contact,
        "phone": request.phone,
        "email": request.email,
        "is_active": request.is_active,
    })

    # 2. 生成参数化 INSERT SQL（用于目标库执行对比）
    insert_sql = (
        "INSERT INTO customers (id, code, name, contact, phone, email, is_active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    insert_params = (
        customer.id, request.code, request.name,
        request.contact, request.phone, request.email, request.is_active,
    )

    # 3. 双库执行对比
    exec_result = SQLKernel.execute_on_both(
        sql=insert_sql,
        source_db=request.source_db,
        target_db=request.target_db,
        params=insert_params,
        skip_validation=True,
        analyze_kernel=True,
    )

    src_data = exec_result.source_result or {}
    tgt_data = exec_result.target_result or {}
    src = SingleResult(**src_data)
    tgt = SingleResult(**tgt_data)

    return BusinessOperationResponse(
        operation="create_customer",
        source_db=request.source_db,
        target_db=request.target_db,
        generated_sql_source=insert_sql,
        generated_sql_target=exec_result.rewritten_sql,
        source_result=src,
        target_result=tgt,
        kernel_analysis=None,
        equal=exec_result.equal,
        diff_detail=exec_result.diff,
        execution_time_ms=exec_result.execution_time_ms,
    )
