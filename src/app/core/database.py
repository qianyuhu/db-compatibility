"""
数据库引擎 & Session 工厂 — 同步模式。

Phase 1 约束:
- 不使用异步 (asyncpg / aioodbc)
- 不做连接池多库抽象
- 每个数据库提供独立的 engine / raw connection

KingbaseES MSSQL Compatible 模式:
- SQLAlchemy PG Dialect 与 T-SQL 语法冲突（两个阻断问题）
- Phase 1 使用原生 psycopg2（autocommit 模式）
- 通过 get_raw_connection() 获取
- 详见 docs/kingbase-mssql-driver-investigation.md
"""

from contextlib import contextmanager
from typing import Optional

import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


# =========================================================================
# MSSQL / DM8 — 标准 SQLAlchemy Engine
# =========================================================================

_mssql_dm8_engine = None
_mssql_dm8_session_local = None


def _build_standard_engine():
    """为 MSSQL / DM8 创建标准 SQLAlchemy engine。"""
    return create_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def get_engine():
    """返回当前激活数据库的 SQLAlchemy Engine。

    KingbaseES 不支持 — 返回 None（请使用 get_raw_connection()）。
    """
    global _mssql_dm8_engine
    if settings.active_db == "kingbasees":
        return None
    if _mssql_dm8_engine is None:
        _mssql_dm8_engine = _build_standard_engine()
    return _mssql_dm8_engine


def get_session_local():
    """返回当前激活数据库的 sessionmaker。

    KingbaseES 不支持 — 返回 None。
    """
    global _mssql_dm8_session_local
    if settings.active_db == "kingbasees":
        return None
    if _mssql_dm8_session_local is None:
        _mssql_dm8_session_local = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _mssql_dm8_session_local


# =========================================================================
# KingbaseES — 原生 psycopg2 连接（绕过 SQLAlchemy PG Dialect）
# =========================================================================

def get_raw_connection(db_name: Optional[str] = None):
    """返回原生 DBAPI 连接（自动适配 active_db）。

    - MSSQL:   返回 pyodbc 连接
    - KingbaseES: 返回 psycopg2 连接（autocommit 模式）
    - DM8:     返回 dmPython 连接

    KingbaseES 必须使用此方法，因为 SQLAlchemy PG Dialect:
      1. 发送 BEGIN (PG) 但 KingbaseES MSSQL 模式只认 BEGIN TRANSACTION
      2. 版本字符串 'KingbaseES V009R...' 无法被 PG 方言解析
    """
    if settings.active_db == "mssql":
        import pyodbc
        kwargs = settings.raw_connection_kwargs
        return pyodbc.connect(kwargs["connection_string"])

    elif settings.active_db == "kingbasees":
        kwargs = settings.raw_connection_kwargs
        conn = psycopg2.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=db_name or kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
            options=kwargs.get("options", ""),
            connect_timeout=kwargs.get("connect_timeout", 10),
        )
        conn.autocommit = True
        return conn

    elif settings.active_db == "dm8":
        import dmPython
        kwargs = settings.raw_connection_kwargs
        # dmPython API: 使用 server 而非 host，无 database 参数
        return dmPython.connect(
            user=kwargs["user"],
            password=kwargs["password"],
            server=kwargs["host"],
            port=kwargs["port"],
        )

    raise ValueError(f"Unsupported active_db: {settings.active_db}")


# =========================================================================
# 便利函数
# =========================================================================

@contextmanager
def get_db():
    """上下文管理器：返回当前数据库的连接。

    - MSSQL / DM8: 返回 SQLAlchemy Session
    - KingbaseES: 返回原生 psycopg2 cursor

    用法:
        with get_db() as db:
            # MSSQL/DM8: db.execute(select(...))
            # KingbaseES: db.execute("SELECT ...")
            ...
    """
    if settings.active_db in ("mssql", "dm8"):
        session = get_session_local()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    else:
        # KingbaseES: raw psycopg2
        conn = get_raw_connection()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
            conn.close()


def get_session() -> Session:
    """返回一个新的同步 SQLAlchemy Session（仅 MSSQL / DM8）。"""
    factory = get_session_local()
    if factory is None:
        raise RuntimeError(
            "KingbaseES 不支持 SQLAlchemy Session。请使用 get_db() 或 get_raw_connection()。"
        )
    return factory()
