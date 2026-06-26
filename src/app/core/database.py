"""
数据库引擎 & Session 工厂 — 同步模式。

Phase 1 约束:
- 不使用异步 (asyncpg / aioodbc)
- 不做连接池多库抽象
- 仅提供 create_engine + sessionmaker + get_session
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    echo=False,            # 设为 True 可查看所有 SQL
    pool_size=5,
    pool_pre_ping=True,    # 连接前检查可用性
    pool_recycle=1800,     # 30 分钟回收
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_session() -> Session:
    """返回一个新的同步 Session。

    调用方负责 close()。
    """
    return SessionLocal()
