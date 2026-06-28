"""
Order / OrderItem 模型 — ERP 订单实体。

字段覆盖:
- 基础类型: Integer, String, Numeric, DateTime
- 外键: customer_id → customers, product_id → products
- 全部使用 SQLAlchemy 原生泛型

外键测试:
- 跨数据库外键支持是迁移兼容性的关键测试点
- MSSQL / KingbaseES / DM8 的 FK 语法和约束行为不同
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)

from .base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(50), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status = Column(String(20), default="PENDING", nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    item_count = Column(Integer, nullable=False)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    subtotal = Column(Numeric(12, 2), nullable=False)
