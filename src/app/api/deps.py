"""
deps.py — FastAPI 依赖注入。

提供统一的依赖工厂函数:
    - get_db_gateway: 获取 DBGateway 实例
    - get_service: 获取 Service 实例
"""

from __future__ import annotations

from typing import Generator

from architecture.core.db.gateway import DBGateway


def get_db_gateway() -> DBGateway:
    """获取当前激活数据库的 DBGateway 实例。"""
    return DBGateway()
