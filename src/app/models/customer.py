"""
Customer 模型 — ERP 客户实体。

字段覆盖:
- 基础类型: Integer, String, Boolean, DateTime
- 全部使用 SQLAlchemy 原生泛型
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from .base import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    contact = Column(String(100), nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
