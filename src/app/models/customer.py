"""
Customer 模型 — ERP 客户实体。

字段覆盖:
- 基础类型: Integer, String, Boolean, DateTime
- 全部使用 SQLAlchemy 原生泛型
- 使用中文字段时使用 Unicode 类型（MSSQL NVARCHAR）
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Unicode, func

from .base import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(Unicode(200), nullable=False)  # NVARCHAR 支持中文
    contact = Column(Unicode(100), nullable=True)  # NVARCHAR 支持中文
    phone = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
