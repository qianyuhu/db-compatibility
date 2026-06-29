"""
Product 模型 — Phase 1 唯一业务模型。

字段选择策略:
- 覆盖基础 SQL 类型: Integer, String, Numeric, Boolean, DateTime
- 全部使用 SQLAlchemy 原生泛型
- 不使用 with_variant / TypeDecorator / 自定义类型
- 中文字段使用 Unicode 类型（MSSQL NVARCHAR）

这就是我们要测试的东西。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Unicode,
    func,
)

from .base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(Unicode(200), nullable=False)  # NVARCHAR 支持中文
    price = Column(Numeric(10, 2), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
