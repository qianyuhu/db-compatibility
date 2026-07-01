"""
SQL 能力层 — 统一接口。

提供两大核心能力:
    compile()  — 编译时重写（跨数据库 SQL 转换）
    rewrite()  — 运行时重写（动态 SQL 适配）

子模块:
    compiler/  — SP Compiler（存储过程编译）
    rewrite/   — SQL 重写引擎
    compat/    — 兼容性评估
    scoring/   — 评分引擎
    diagnostics/ — SQL 诊断
    builder/   — SQL 构建器
"""

from __future__ import annotations

from typing import Any


def compile(
    sql: str,
    source_dialect: str,
    target_dialect: str,
) -> dict[str, Any]:
    """编译时重写 — 用于业务 SQL 预转换。

    Args:
        sql: 源 SQL 语句
        source_dialect: 源方言 (mssql / kingbasees / dm8)
        target_dialect: 目标方言

    Returns:
        编译结果 dict
    """
    from architecture.core.sql.compiler.engine import compile_sp

    result = compile_sp(sql, source_dialect, target_dialect)
    return {
        "success": True,
        "compiled_sql": result.target_sql if hasattr(result, "target_sql") else str(result),
        "source_dialect": source_dialect,
        "target_dialect": target_dialect,
    }


def rewrite(
    sql: str,
    source_dialect: str = "mssql",
    target_dialect: str = "kingbasees",
    mode: str = "runtime",
) -> dict[str, Any]:
    """运行时重写 — 用于动态 SQL。

    Args:
        sql: 源 SQL 语句
        source_dialect: 源方言
        target_dialect: 目标方言
        mode: 重写模式

    Returns:
        重写结果 dict
    """
    from architecture.core.sql.rewrite.engine import rewrite_sql

    result = rewrite_sql(sql, source_dialect, target_dialect)
    return {
        "success": True,
        "rewritten_sql": result.rewritten_sql if hasattr(result, "rewritten_sql") else str(result),
        "rules_applied": result.rules_applied if hasattr(result, "rules_applied") else [],
        "source_dialect": source_dialect,
        "target_dialect": target_dialect,
    }
