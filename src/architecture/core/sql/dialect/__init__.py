"""
SQL Dialect — 方言抽象层，提供 SQL 改写能力。

组件:
    - BaseDialect: 方言抽象基类
    - MSSQLDialect: MSSQL 方言
    - KingbaseMSSQLDialect: KingbaseES MSSQL Compatible 模式
    - OracleDialect: Oracle 方言

Usage:
    from architecture.core.sql.dialect import get_dialect, MSSQLDialect

    dialect = get_dialect("mssql")
    sql = dialect.rewrite_limit_offset("SELECT * FROM t LIMIT 10")
"""

from __future__ import annotations

from .base import BaseDialect
from .mssql import MSSQLDialect
from .kingbase_mssql import KingbaseMSSQLDialect
from .oracle import OracleDialect

__all__ = [
    "BaseDialect",
    "MSSQLDialect",
    "KingbaseMSSQLDialect",
    "OracleDialect",
    "get_dialect",
]

# 方言注册表
_DIALECT_REGISTRY: dict[str, BaseDialect] = {
    "mssql": MSSQLDialect(),
    "kingbasees": KingbaseMSSQLDialect(),
    "kingbase_mssql": KingbaseMSSQLDialect(),
    "oracle": OracleDialect(),
    "dm8": OracleDialect(),  # DM8 高度兼容 Oracle 语法
}


def get_dialect(db_type: str) -> BaseDialect:
    """获取指定数据库的方言实例。

    Args:
        db_type: 数据库类型 (mssql / kingbasees / oracle / dm8)

    Returns:
        BaseDialect 实例

    Raises:
        ValueError: 不支持的 db_type
    """
    if db_type not in _DIALECT_REGISTRY:
        raise ValueError(
            f"Unknown db_type: {db_type}. "
            f"Supported: {list(_DIALECT_REGISTRY.keys())}"
        )
    return _DIALECT_REGISTRY[db_type]
