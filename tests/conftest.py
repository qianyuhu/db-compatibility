"""
测试基础设施 — 三库 parametrize 共享 fixtures。

Phase 1 约束:
- 不做 Mock：所有测试连接真实数据库
- 不做兼容层：差异直接暴露在测试结果中
- 环境变量 KINGBASEES_AVAILABLE / DM8_AVAILABLE 控制额外数据库
"""

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.base import Base
from app.models.product import Product  # noqa: F401 — 确保模型注册


# ============================================================
# 可用数据库检测
# ============================================================

def _get_available_dbs() -> list[str]:
    """返回当前可用的数据库列表。

    MSSQL 始终可用（基准数据库）。
    其他数据库需要环境变量声明可用。
    """
    dbs = ["mssql"]  # 基准数据库 — 始终存在
    if os.environ.get("KINGBASEES_AVAILABLE"):
        dbs.append("kingbasees")
    if os.environ.get("DM8_AVAILABLE"):
        dbs.append("dm8")
    return dbs


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(
    params=_get_available_dbs(),
    ids=lambda db: db,
)
def db_name(request) -> str:
    """Parametrize: 对每个可用数据库运行一次测试。"""
    return request.param


@pytest.fixture
def db_session(db_name: str):
    """创建独立 engine + session，测试后清理所有数据。

    隔离策略:
    - 每个测试创建独立 engine（不共享连接池）
    - 测试前 create_all 确保表存在
    - 测试后 DELETE 所有行 + dispose engine
    """
    s = Settings()
    s.active_db = db_name

    engine = create_engine(s.database_url, echo=False)

    # 确保表存在（等同 alembic upgrade head 的效果）
    Base.metadata.create_all(bind=engine)

    session = Session(engine)

    try:
        yield session
    finally:
        session.close()

        # 清理：逆序删除所有表数据（尊重外键约束）
        clean_session = Session(engine)
        try:
            for table in reversed(Base.metadata.sorted_tables):
                clean_session.execute(table.delete())
            clean_session.commit()
        finally:
            clean_session.close()

        engine.dispose()


@pytest.fixture
def product_repo(db_session):
    """快捷 fixture：直接获取 ProductRepository 实例。"""
    from app.repositories.product import ProductRepository
    return ProductRepository(db_session)


# ============================================================
# 连接可用性探测（用于跳过不可用的数据库）
# ============================================================

def _can_connect(db_name: str) -> bool:
    """探测指定数据库是否可达。"""
    try:
        s = Settings()
        s.active_db = db_name
        engine = create_engine(s.database_url, echo=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False
