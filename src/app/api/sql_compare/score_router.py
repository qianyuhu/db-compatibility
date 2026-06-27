"""
SQL Score Router — POST /api/sql/score

Evaluates SQL compatibility across databases and returns a 0-100 score
with dimensional breakdown, findings, and actionable suggestions.

Reuses compare_service for execution — no duplicate SQL execution.
"""

from fastapi import APIRouter

from app.api.sql_demo.service import validate_sql

from .score_schemas import ScoreRequest, ScoreResponse
from .score_service import calculate_score

router = APIRouter(prefix="/api/sql", tags=["sql-score"])


@router.post(
    "/score",
    response_model=ScoreResponse,
    summary="SQL 兼容性评分",
    description=(
        "评估 SQL 语句在多个数据库（MSSQL / KingbaseES / DM8）之间的兼容性，"
        "返回 0-100 的综合评分及四维度（语法 / 执行 / 结果 / 风险）明细。"
        "同时提供兼容性问题发现列表和改写建议。"
    ),
)
def sql_score(request: ScoreRequest) -> ScoreResponse:
    """计算 SQL 兼容性评分。

    流程:
        1. 安全校验 SQL
        2. 并行执行到各目标数据库
        3. 对比执行结果差异
        4. 四维度评分（语法 / 执行 / 结果 / 风险）
        5. 加权计算最终得分

    返回:
        ScoreResponse: 综合得分 + 维度明细 + 发现列表 + 建议
    """
    # 安全校验
    validate_sql(request.sql)

    # 调用评分引擎
    return calculate_score(request.sql, request.db_types)
