"""
SQL Simulation Router — POST /api/sql/migrate/simulate

Migration execution simulation endpoint. Runs the full simulation pipeline
through the SQLKernel for shared context:
equivalence check → cardinality estimation → drift analysis → failure
prediction → verdict.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.sql_kernel.kernel import SQLKernel

from .schemas import SimulationRequest, SimulationResponse

router = APIRouter(prefix="/api/sql/migrate", tags=["sql-simulation"])


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    summary="SQL 迁移执行仿真",
    description=(
        "在不实际连接数据库的情况下，仿真 SQL 从源数据库迁移到目标数据库后的"
        "执行行为。评估等价性、数据漂移、查询行为变化和潜在失败点。"
    ),
)
def simulate(request: SimulationRequest) -> SimulationResponse:
    """仿真 SQL 迁移的执行行为。

    流程:
        1. SQLKernel 构建统一语义上下文
        2. 获取改写后的 SQL（如未提供则自动调用 rewrite 引擎）
        3. 提取原始和改写后 SQL 的对象引用
        4. 构建执行模型（等价性检查 + 基数估算）
        5. 分析数据漂移（表级行数差异、NULL 语义变化）
        6. 分析查询行为变化（JOIN 基数、聚合稳定性、排序稳定性）
        7. 预测失败点（NULL / 分页 / 时区 / JOIN / 函数语义 / 类型转换）
        8. 计算等价性评分 → 风险等级 → 最终裁决

    请求体示例:
        {
            "sql": "SELECT TOP 10 id, GETDATE() FROM [users] WHERE ISNULL(status, 0) = 1",
            "source_db": "mssql",
            "target_db": "kingbasees"
        }

    返回:
        SimulationResponse: 等价性评分 + 风险等级 + 仿真细节 + 裁决
    """
    result = SQLKernel.analyze(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
        engines=["simulation"],
        rewritten_sql=request.rewritten_sql,
    )
    return result.simulation
