"""
SQL Rewrite Pipeline — dialect-aware 执行适配层。

与现有 rewrite_sql() 互补:
    - rewrite_sql(): 面向跨库迁移场景（source_db → target_db 完整改写）
    - rewrite():     面向单库执行适配场景（将标准化 SQL 改写为本地方言）

Pipeline 步骤:
    1. normalize_params    — 参数占位符归一化
    2. rewrite_limit_offset — 分页语法改写
    3. rewrite_upsert       — UPSERT 语法改写
    4. map_datetime_func    — 时间函数映射
    5. normalize_identifiers — 标识符引用归一化

Usage:
    from architecture.core.sql.rewrite.pipeline import rewrite
    from architecture.core.sql.dialect import get_dialect

    dialect = get_dialect("mssql")
    adapted_sql = rewrite("SELECT * FROM t LIMIT 10", dialect)
    # → "SELECT TOP 10 * FROM t"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from architecture.core.sql.dialect.base import BaseDialect


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Pipeline 执行结果。"""

    original_sql: str
    rewritten_sql: str
    dialect: str
    steps_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

# 默认执行顺序
_DEFAULT_STEPS = [
    "normalize_params",
    "rewrite_limit_offset",
    "rewrite_upsert",
    "map_datetime_func",
    "normalize_identifiers",
]


def rewrite(
    sql: str,
    dialect: BaseDialect,
    *,
    steps: list[str] | None = None,
) -> str:
    """将标准化 SQL 通过 dialect 改写为本地可执行形式。

    按顺序执行 pipeline 步骤，每步调用 dialect 对应方法。

    Args:
        sql: 标准化 SQL（使用 %s 占位符，标准 LIMIT/OFFSET 语法）
        dialect: 目标方言实例
        steps: 要执行的步骤（默认全部）

    Returns:
        改写后的 SQL 字符串
    """
    result = rewrite_with_detail(sql, dialect, steps=steps)
    return result.rewritten_sql


def rewrite_with_detail(
    sql: str,
    dialect: BaseDialect,
    *,
    steps: list[str] | None = None,
) -> PipelineResult:
    """将标准化 SQL 通过 dialect 改写，返回详细结果。

    Args:
        sql: 标准化 SQL
        dialect: 目标方言实例
        steps: 要执行的步骤列表（默认全部）

    Returns:
        PipelineResult 包含改写后 SQL 及元数据
    """
    current_sql = sql.strip()
    steps_to_run = steps or _DEFAULT_STEPS
    applied: list[str] = []
    warnings: list[str] = []

    for step_name in steps_to_run:
        method = getattr(dialect, step_name, None)
        if method is None:
            warnings.append(f"Step '{step_name}' not found on dialect '{dialect.name}' — skipped")
            continue

        try:
            new_sql = method(current_sql)
        except Exception as exc:
            warnings.append(f"Step '{step_name}' failed: {exc} — keeping previous SQL")
            continue

        if new_sql != current_sql:
            applied.append(step_name)
            current_sql = new_sql

    # 检查是否包含 WARNING 注释
    if current_sql.startswith("-- WARNING:"):
        lines = current_sql.split("\n")
        warnings.append(lines[0].lstrip("- ").strip())

    return PipelineResult(
        original_sql=sql.strip(),
        rewritten_sql=current_sql.strip(),
        dialect=dialect.name,
        steps_applied=applied,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Preprocessing pipeline (compile step for gateway)
# ---------------------------------------------------------------------------


def compile_sql(
    sql: str,
    dialect: BaseDialect,
    params: tuple | None = None,
) -> tuple[str, tuple | None]:
    """编译 SQL：改写 + 参数绑定预处理。

    供 DBGateway.compile() 调用。执行 dialect-aware 改写，
    但不修改 params（参数由 DBAPI 层处理）。

    Args:
        sql: 原始 SQL
        dialect: 目标方言
        params: 查询参数（透传，不修改）

    Returns:
        (compiled_sql, params)
    """
    compiled = rewrite(sql, dialect)
    return compiled, params
