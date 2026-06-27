"""
SQL Compare Router — POST /api/sql/compare

统一 SQL 对比端点，同一 SQL 在多个数据库上执行并对比差异。
"""

from fastapi import APIRouter

from .compare_schemas import CompareRequest, CompareResponse
from .compare_service import compute_diff, execute_compare
from .service import SQLSecurityError

router = APIRouter(prefix="/api/sql", tags=["sql-compare"])


def _wrap_single_error(
    db_type: str,
    error: str,
    suggestion: str = "",
) -> dict:
    """构造单个数据库的错误结果。"""
    return {
        "success": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time_ms": 0,
        "error": error,
        "suggestion": suggestion,
    }


@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="多库 SQL 对比执行",
    description=(
        "在多个数据库上执行同一 SQL 语句，返回各库结果及差异分析。"
        "支持 MSSQL、KingbaseES MSSQL Compatible、DM8 三种数据库。"
        "自动检测 SQL 方言并提供改写建议。"
    ),
)
def sql_compare(request: CompareRequest) -> CompareResponse:
    """并行执行 SQL 到多个数据库，对比差异。"""
    try:
        results, rewrites = execute_compare(request.sql, request.db_types)
    except SQLSecurityError as exc:
        # 安全校验失败 — 所有 DB 均标记为失败
        results = {
            db: _wrap_single_error(
                db,
                str(exc),
                exc.suggestion,
            )
            for db in request.db_types
        }
        rewrites = []

    # 计算差异
    diff = compute_diff(results)

    return CompareResponse(
        results={
            db: {
                "success": r["success"],
                "columns": r.get("columns", []),
                "rows": r.get("rows", []),
                "row_count": r.get("row_count", 0),
                "execution_time_ms": r.get("execution_time_ms", 0),
                "error": r.get("error"),
                "suggestion": r.get("suggestion"),
            }
            for db, r in results.items()
        },
        diff=diff,
        rewrites=rewrites,
    )
