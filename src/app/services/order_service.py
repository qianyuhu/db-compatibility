"""
OrderService — 订单业务服务。

核心流程:
    1. 通过 Repository 在源库（MSSQL）持久化
    2. 生成等效 SQL（参数化，防注入）
    3. 通过 SQLKernel.execute_on_both() 在源库和目标库执行
    4. 对比结果 → 验证跨数据库行为一致性
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.sql_kernel.kernel import SQLKernel
from app.repositories.customer import CustomerRepository
from app.repositories.order import OrderRepository

from .schemas import BusinessOperationResult


class OrderService:
    """订单业务服务 — 源库 ORM 持久化 + 双库 SQL 执行对比。"""

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    def create_order(
        self,
        session: Session,
        customer_code: str,
        items: list[dict[str, Any]],
        notes: str | None = None,
    ) -> BusinessOperationResult:
        """创建订单。

        1. 查找客户 → 计算总额
        2. ORM 创建订单（源库）
        3. 生成等效 INSERT SQL（参数化）
        4. 通过 SQLKernel 在双库执行并对比

        Args:
            session: 源库 SQLAlchemy Session
            customer_code: 客户编码
            items: [{product_code, quantity, unit_price}, ...]
            notes: 备注
        """
        start = time.perf_counter()

        # 1. 查找客户
        cust_repo = CustomerRepository(session)
        customer = cust_repo.find_by_code(customer_code)
        if customer is None:
            raise ValueError(f"Customer not found: {customer_code}")

        # 2. 计算总额
        total_amount = sum(
            item["quantity"] * item["unit_price"] for item in items
        )
        item_count = len(items)

        # 3. ORM 创建订单（源库持久化）
        order_repo = OrderRepository(session)
        order_data = {
            "order_no": "",
            "customer_id": customer.id,
            "status": "PENDING",
            "total_amount": total_amount,
            "item_count": item_count,
            "notes": notes,
        }
        order = order_repo.create(order_data)
        order_no = f"ORD-{order.id:06d}"
        order_repo.update(order.id, {"order_no": order_no})

        # 4. 生成参数化 INSERT SQL
        sql, params = self._build_insert_order_sql(
            order_no=order_no,
            customer_id=customer.id,
            total_amount=total_amount,
            item_count=item_count,
            notes=notes,
        )

        # 5. 通过 SQLKernel 在双库执行（参数化）
        exec_result = SQLKernel.execute_on_both(
            sql=sql,
            source_db=self.source_db,
            target_db=self.target_db,
            params=params,
            skip_validation=True,
            analyze_kernel=True,
        )

        # 6. 构建结果对比
        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return BusinessOperationResult(
            operation="create_order",
            source_db=self.source_db,
            target_db=self.target_db,
            generated_sql_source=sql,
            generated_sql_target=exec_result.rewritten_sql,
            source_result=exec_result.source_result or {},
            target_result=exec_result.target_result or {},
            kernel_analysis=exec_result.kernel,
            equal=exec_result.equal,
            diff_detail=exec_result.diff,
            execution_time_ms=elapsed,
        )

    def query_orders_by_customer(
        self,
        customer_id: int,
    ) -> BusinessOperationResult:
        """查询客户的所有订单 — 生成参数化 SELECT 并通过双库执行对比。"""
        start = time.perf_counter()

        sql = (
            "SELECT id, order_no, customer_id, status, total_amount, "
            "item_count, notes, created_at, updated_at "
            "FROM orders "
            "WHERE customer_id = %s "
            "ORDER BY created_at DESC"
        )
        params = (customer_id,)

        exec_result = SQLKernel.execute_on_both(
            sql=sql,
            source_db=self.source_db,
            target_db=self.target_db,
            params=params,
            skip_validation=True,
            analyze_kernel=True,
        )

        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return BusinessOperationResult(
            operation="query_orders_by_customer",
            source_db=self.source_db,
            target_db=self.target_db,
            generated_sql_source=sql,
            generated_sql_target=exec_result.rewritten_sql,
            source_result=exec_result.source_result or {},
            target_result=exec_result.target_result or {},
            kernel_analysis=exec_result.kernel,
            equal=exec_result.equal,
            diff_detail=exec_result.diff,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # SQL 生成（使用 %s 占位符，返回 (sql, params)）
    # ------------------------------------------------------------------

    @staticmethod
    def _build_insert_order_sql(
        order_no: str,
        customer_id: int,
        total_amount: float,
        item_count: int,
        notes: str | None = None,
    ) -> tuple[str, tuple]:
        """生成参数化的 INSERT INTO orders。

        Returns:
            (sql, params) — sql 使用 %s 占位符，params 为值元组
        """
        sql = (
            "INSERT INTO orders (order_no, customer_id, status, "
            "total_amount, item_count, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )
        params = (
            order_no,
            customer_id,
            "PENDING",
            total_amount,
            item_count,
            notes,
        )
        return sql, params
