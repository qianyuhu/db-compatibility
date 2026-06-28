"""
Alembic 迁移环境配置。

Phase 1 策略:
- 动态读取 APP_ACTIVE_DB 决定连接目标
- 使用 app.models.base.Base.metadata 作为 target_metadata
- 不做多数据库 DDL 适配（那是 Phase 2 的事）
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 src/ 在 sys.path 中（alembic 从项目根目录运行时需要）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from app.core.config import settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.customer import Customer  # noqa: F401
from app.models.inventory import Inventory  # noqa: F401
from app.models.order import Order, OrderItem  # noqa: F401
from app.models.product import Product  # noqa: F401

# Alembic Config 对象
config = context.config

# 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---- 动态 URL 注入 ----
# 绕过 alembic.ini 中硬编码的 sqlalchemy.url
# 使用 attributes 避免 configparser 对 URL 中 % 的插值解析
config.attributes["sqlalchemy.url"] = settings.database_url

# ---- MetaData ----
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式 — 生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式 — 连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=config.attributes.get("sqlalchemy.url"),
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
