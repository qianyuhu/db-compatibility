"""
SQL Demo Router — POST /api/sql/execute

统一 SQL 执行端点，支持 MSSQL / KingbaseES / DM8 三库。
"""

from fastapi import APIRouter

from .schemas import ExecuteRequest, ExecuteResponse
from .service import SQLSecurityError, execute_sql

router = APIRouter(prefix="/api/sql", tags=["sql-demo"])


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="执行 SQL 查询",
    description=(
        "在指定数据库上执行 SQL 查询，返回统一格式的结果。"
        "支持 MSSQL、KingbaseES MSSQL Compatible、DM8 三种数据库。"
        "仅允许只读操作（SELECT / SHOW / EXPLAIN / DESCRIBE / WITH）。"
    ),
)
def sql_execute(request: ExecuteRequest) -> ExecuteResponse:
    """执行 SQL 查询并返回标准化结果。"""
    try:
        result = execute_sql(request.db_type, request.sql)
    except SQLSecurityError as exc:
        result = {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "db_type": request.db_type,
            "execution_time_ms": 0,
            "error": str(exc),
            "suggestion": exc.suggestion,
        }
    return ExecuteResponse(**result)
