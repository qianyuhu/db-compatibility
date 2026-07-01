"""
SQL Rewrite Router — POST /api/sql/rewrite

Cross-database SQL transformation endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from .engine import rewrite_sql
from .rewrite_schemas import RewriteRequest, RewriteResponse

router = APIRouter(prefix="/api/sql", tags=["sql-rewrite"])


@router.post(
    "/rewrite",
    response_model=RewriteResponse,
    summary="SQL 跨库改写",
    description=(
        "将一个数据库方言的 SQL 改写为另一个数据库方言。"
        "支持 MSSQL → KingbaseES / DM8 / 反向改写。"
        "返回改写后的 SQL、应用的规则列表及置信度评分。"
    ),
)
def sql_rewrite(request: RewriteRequest) -> RewriteResponse:
    """执行 SQL 跨数据库改写。

    流程:
        1. AST 归一化 — 解析源 SQL 为统一 AST
        2. 规则匹配 — 根据 (source_db, target_db) 匹配改写规则
        3. 改写 — 应用匹配的规则逐条转换
        4. 验证 — 检查改写后的 SQL 结构完整性

    返回:
        RewriteResponse: 原始 SQL + 改写 SQL + 规则列表 + 置信度
    """
    result = rewrite_sql(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
    )

    return RewriteResponse(
        original_sql=result.original_sql,
        rewritten_sql=result.rewritten_sql,
        source_db=result.source_db,
        target_db=result.target_db,
        rules_applied=[
            {
                "name": r.name,
                "description": r.description,
                "confidence": r.confidence,
            }
            for r in result.rules_applied
        ],
        confidence=result.confidence,
        warnings=result.warnings,
    )
