"""
Dialect — 方言适配层，屏蔽不同数据库的 SQL 语法差异。

提供:
    - 分页语法 (TOP / LIMIT / OFFSET)
    - 参数占位符 (%s / :1 / ?)
    - 当前时间函数 (GETDATE() / NOW() / SYSDATE)
    - 字符串函数差异
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialectSpec:
    """数据库方言规格。"""

    db_type: str  # mssql | kingbasees | dm8

    # 分页
    supports_limit: bool = True
    supports_offset: bool = True
    uses_top: bool = False  # MSSQL uses SELECT TOP N

    # 参数占位符
    param_placeholder: str = "%s"  # %s (psycopg2/pyodbc) or :1 (Oracle)

    # 当前时间
    current_timestamp: str = "CURRENT_TIMESTAMP"

    # 自增列
    auto_increment: str = "IDENTITY(1,1)"

    # 字符串拼接
    concat_operator: str = "+"  # MSSQL uses +, PG uses ||

    # LIKE 转义
    like_escape: str = ""

    # 事务
    supports_transaction: bool = True


# 方言注册表
_DIALECT_REGISTRY: dict[str, DialectSpec] = {
    "mssql": DialectSpec(
        db_type="mssql",
        uses_top=True,
        supports_limit=False,
        supports_offset=False,
        current_timestamp="GETDATE()",
        auto_increment="IDENTITY(1,1)",
        concat_operator="+",
    ),
    "kingbasees": DialectSpec(
        db_type="kingbasees",
        supports_limit=True,
        supports_offset=True,
        uses_top=False,
        current_timestamp="NOW()",
        auto_increment="SERIAL",
        concat_operator="||",
    ),
    "dm8": DialectSpec(
        db_type="dm8",
        supports_limit=True,
        supports_offset=True,
        uses_top=False,
        current_timestamp="SYSDATE",
        auto_increment="IDENTITY(1,1)",
        concat_operator="||",
    ),
}


def get_dialect(db_type: str) -> DialectSpec:
    """获取指定数据库的方言规格。"""
    if db_type not in _DIALECT_REGISTRY:
        raise ValueError(f"Unknown db_type: {db_type}. Supported: {list(_DIALECT_REGISTRY.keys())}")
    return _DIALECT_REGISTRY[db_type]


def adapt_pagination(sql: str, source_db: str, target_db: str) -> str:
    """将 SQL 中的分页语法从源方言转换为目标方言。

    目前仅处理 LIMIT ↔ TOP 的基本转换。
    """
    if source_db == target_db:
        return sql

    source = get_dialect(source_db)
    target = get_dialect(target_db)

    # LIMIT → TOP (target is MSSQL)
    if target.uses_top and not source.uses_top:
        import re
        match = re.search(r'\bLIMIT\s+(\d+)\s*$', sql, re.IGNORECASE)
        if match:
            n = match.group(1)
            sql = re.sub(r'\bLIMIT\s+\d+\s*$', '', sql, flags=re.IGNORECASE).strip()
            sql = sql.replace("SELECT", f"SELECT TOP {n}", 1)

    # TOP → LIMIT (source is MSSQL, target supports LIMIT)
    if source.uses_top and not target.uses_top:
        import re
        match = re.search(r'\bSELECT\s+TOP\s+(\d+)\s+', sql, re.IGNORECASE)
        if match:
            n = match.group(1)
            sql = re.sub(r'\bSELECT\s+TOP\s+\d+\s+', 'SELECT ', sql, flags=re.IGNORECASE)
            sql = f"{sql} LIMIT {n}"

    return sql
