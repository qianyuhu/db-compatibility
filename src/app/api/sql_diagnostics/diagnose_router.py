"""
SQL Diagnostics Router — POST /api/sql/diagnose

Object-level cross-DB compatibility diagnostics endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from .analyzer import analyze_objects
from .diagnose_schemas import DiagnoseRequest, DiagnoseResponse
from .extractor import extract_objects

router = APIRouter(prefix="/api/sql", tags=["sql-diagnostics"])


@router.post(
    "/diagnose",
    response_model=DiagnoseResponse,
    summary="SQL 对象级兼容性诊断",
    description=(
        "提取 SQL 中的表、列、函数、JOIN，分析各对象在目标数据库中的兼容性，"
        "返回风险等级和详细问题列表。"
    ),
)
def sql_diagnose(request: DiagnoseRequest) -> DiagnoseResponse:
    """执行 SQL 对象级诊断。

    流程:
        1. 对象提取 — 从 SQL 中提取 tables / columns / functions / joins
        2. 风险分析 — 对每个对象评估跨数据库兼容性
        3. 汇总 — 按风险等级统计对象数量

    返回:
        DiagnoseResponse: 各对象的诊断结果 + 兼容性映射 + 风险汇总
    """
    # Phase 1: Extract objects from SQL
    objects = extract_objects(request.sql)

    # Phase 2: Analyze objects against target DBs
    analysis = analyze_objects(objects, request.db_types)

    # Phase 3: Build response
    return DiagnoseResponse(
        sql=request.sql,
        db_types=request.db_types,
        tables=analysis.tables,
        columns=analysis.columns,
        functions=analysis.functions,
        joins=analysis.joins,
        summary=analysis.summary,
    )
