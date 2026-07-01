"""
Inventory 模型 — ERP 库存实体。

字段覆盖:
- 基础类型: Integer, String, DateTime
- 外键: product_id → products (unique 约束)
- 全部使用 SQLAlchemy 原生泛型
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from .base import Base


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(
        Integer, ForeignKey("products.id"), unique=True, nullable=False
    )
    warehouse = Column(String(50), default="MAIN", nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    min_quantity = Column(Integer, default=10, nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
