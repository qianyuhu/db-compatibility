"""
Pool — 连接池管理。

提供统一的连接池抽象，封装不同数据库的连接池策略。
"""

from __future__ import annotations

import logging
from typing import Any

from architecture.core.config import settings

logger = logging.getLogger(__name__)

# 全局连接池实例（单例模式）
_sa_engine = None
_sa_session_factory = None


def get_engine():
    """获取 SQLAlchemy Engine（仅 MSSQL / DM8）。

    KingbaseES 返回 None — 使用 get_raw_connection()。
    """
    global _sa_engine
    from architecture.database import get_engine as _get_engine
    return _get_engine()


def get_session_factory():
    """获取 SQLAlchemy sessionmaker（仅 MSSQL / DM8）。"""
    global _sa_session_factory
    from architecture.database import get_session_local as _get_session_local
    return _get_session_local()


def get_raw_connection(db_name: str | None = None):
    """获取原生 DBAPI 连接。"""
    from architecture.database import get_raw_connection as _get_raw
    return _get_raw(db_name)
