"""OrderRepository — 扩展泛型基类，增加按客户/状态查询。"""

from typing import Optional, Sequence

from sqlalchemy import select

from app.models.order import Order
from .base import Repository


class OrderRepository(Repository[Order]):
    model = Order

    def find_by_customer(
        self,
        customer_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Order], int]:
        """按客户 ID 分页查询订单。"""
        from sqlalchemy import func

        total = self.session.scalar(
            select(func.count()).select_from(Order).where(
                Order.customer_id == customer_id
            )
        )
        stmt = (
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = self.session.scalars(stmt).all()
        return rows, total

    def find_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Order], int]:
        """按订单状态分页查询。"""
        from sqlalchemy import func

        total = self.session.scalar(
            select(func.count()).select_from(Order).where(Order.status == status)
        )
        stmt = (
            select(Order)
            .where(Order.status == status)
            .order_by(Order.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = self.session.scalars(stmt).all()
        return rows, total

    def find_by_order_no(self, order_no: str) -> Optional[Order]:
        """按订单号精确查询。"""
        stmt = select(Order).where(Order.order_no == order_no)
        return self.session.scalar(stmt)
