"""
core.db — 统一数据库访问层。

核心组件:
    - DBGateway: 统一数据库入口（含 dialect-aware 执行）
    - DialectSpec: 方言规格（元数据）
    - TransactionContext: 事务管理
    - ExecuteResult / QueryResult: 结果类型
"""

from architecture.core.db.gateway import DBGateway, ExecuteResult, QueryResult
from architecture.core.db.dialect import DialectSpec, get_dialect
from architecture.core.db.transaction import TransactionContext, NullTransaction

__all__ = [
    "DBGateway",
    "ExecuteResult",
    "QueryResult",
    "DialectSpec",
    "get_dialect",
    "TransactionContext",
    "NullTransaction",
]
