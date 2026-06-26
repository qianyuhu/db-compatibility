"""
测试基础设施 — 三库 parametrize 共享 fixtures。

Phase 1 约束:
- 不做 Mock：所有测试连接真实数据库
- 不做兼容层：差异直接暴露在测试结果中
- 不可达的数据库自动 pytest.skip()，提示缺少什么依赖
- 表结构优先通过 Alembic 迁移创建（失败时 fallback 到 create_all）
"""

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.base import Base
from app.models.product import Product  # noqa: F401 — 确保模型注册


# ============================================================
# 连接探测
# ============================================================

_CAN_CONNECT_CACHE: dict[str, bool | str] = {}


def _probe_database(db_name: str) -> bool | str:
    """探测数据库是否可达。返回 True 或错误信息字符串。"""
    if db_name in _CAN_CONNECT_CACHE:
        return _CAN_CONNECT_CACHE[db_name]

    try:
        s = Settings()
        s.active_db = db_name
        engine = create_engine(s.database_url, echo=False, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        _CAN_CONNECT_CACHE[db_name] = True
        return True
    except ImportError as e:
        msg = f"驱动程序未安装: {e}"
        _CAN_CONNECT_CACHE[db_name] = msg
        return msg
    except Exception as e:
        msg = f"连接失败: {type(e).__name__}: {e}"
        _CAN_CONNECT_CACHE[db_name] = msg
        return msg


def _get_available_dbs() -> list[str]:
    """返回当前可访问的数据库列表（全部探测）。

    MSSQL 需要: unixODBC + ODBC Driver 18 for SQL Server
    KingbaseES 需要: psycopg2 + 环境变量 KINGBASEES_AVAILABLE
    DM8 需要: dmPython + 环境变量 DM8_AVAILABLE
    """
    candidates = ["mssql"]
    if os.environ.get("KINGBASEES_AVAILABLE"):
        candidates.append("kingbasees")
    if os.environ.get("DM8_AVAILABLE"):
        candidates.append("dm8")
    return candidates


# ============================================================
# Alembic 辅助
# ============================================================

def _run_alembic_upgrade(db_name: str) -> Exception | None:
    """执行 alembic upgrade head。返回 None 表示成功，否则返回异常。"""
    from alembic.config import Config as AlembicConfig
    from alembic import command

    s = Settings()
    s.active_db = db_name

    # alembic.ini 在项目根目录
    project_root = os.path.dirname(os.path.dirname(__file__))
    ini_path = os.path.join(project_root, "alembic.ini")

    alembic_cfg = AlembicConfig(ini_path)
    # 使用 attributes 而非 set_main_option，避免 configparser 对 URL 中 % 的插值解析
    alembic_cfg.attributes["sqlalchemy.url"] = s.database_url

    try:
        command.upgrade(alembic_cfg, "head")
        return None
    except Exception as e:
        return e


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(
    params=_get_available_dbs(),
    ids=lambda db: db,
)
def db_name(request) -> str:
    """Parametrize: 对每个候选数据库运行一次测试。

    不可达的数据库在 db_session fixture 中 skip，不影响可达数据库的测试。
    """
    return request.param


@pytest.fixture
def db_session(db_name: str):
    """创建独立 engine + session，测试后清理所有数据。

    表结构策略:
    1. 优先运行 alembic upgrade head（真实迁移路径）
    2. 迁移失败时 fallback 到 create_all（允许在没有 alembic 版本表时测试）

    隔离策略:
    - 每个测试创建独立 engine
    - 测试后 DELETE 所有行 + dispose engine
    """
    # ---- 探测连接 ----
    probe = _probe_database(db_name)
    if probe is not True:
        pytest.skip(f"[{db_name}] {probe}")

    s = Settings()
    s.active_db = db_name
    engine = create_engine(s.database_url, echo=False)

    # ---- 建表：优先 Alembic ----
    alembic_error = _run_alembic_upgrade(db_name)
    if alembic_error is not None:
        # Fallback：Alembic 失败时用 create_all 保证测试可运行
        # 场景：首次运行没有 alembic 版本表、迁移脚本与数据库不兼容等
        Base.metadata.create_all(bind=engine)
        print(f"\n[{db_name}] ⚠️  Alembic 迁移失败，fallback 到 create_all: {alembic_error}")

    session = Session(engine)

    try:
        yield session
    finally:
        session.close()

        # 清理数据
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
