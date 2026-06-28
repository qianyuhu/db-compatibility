"""
SQL Migration Router — POST /api/sql/migrate/plan

Migration feasibility assessment and step-by-step plan generation endpoint.
Now routed through the SQLKernel for shared context.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.sql_kernel.kernel import SQLKernel

from .schemas import MigrationPlanRequest, MigrationPlanResponse

router = APIRouter(prefix="/api/sql/migrate", tags=["sql-migration"])


@router.post(
    "/plan",
    response_model=MigrationPlanResponse,
    summary="SQL 迁移计划评估",
    description=(
        "综合 diagnostics + rewrite + scoring 模块，评估 SQL 从源数据库到目标数据库"
        "的迁移可行性，生成影响分析和分步迁移计划。"
    ),
)
def migration_plan(request: MigrationPlanRequest) -> MigrationPlanResponse:
    """评估 SQL 迁移可行性并生成详细计划。

    流程:
        1. SQLKernel 构建统一语义上下文
        2. 对象诊断 — 提取 tables / columns / functions / joins
        3. SQL 改写 — 自动转换方言语法
        4. 影响分析 — 识别 critical 表、风险热点、JOIN 链
        5. 评分估算 — 基于诊断数据计算迁移可行性评分
        6. 计划生成 — 生成分步迁移步骤
        7. 决策 — 返回 SAFE_AUTO / NEED_REVIEW / HIGH_RISK 建议

    返回:
        MigrationPlanResponse: 可行性判定 + 风险等级 + 影响分析 + 迁移步骤
    """
    result = SQLKernel.analyze(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
        engines=["migration"],
    )
    return result.migration
