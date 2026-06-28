"""
InventoryService — 库存业务服务。

核心流程:
    1. 通过 Repository 在源库操作库存
    2. 生成等效 SQL（参数化，防注入）
    3. 通过 SQLKernel.execute_on_both() 在源库和目标库执行
    4. 对比结果 → 验证跨数据库行为一致性
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.sql_kernel.kernel import SQLKernel
from app.repositories.inventory import InventoryRepository

from .schemas import BusinessOperationResult


class InventoryService:
    """库存业务服务 — 源库 ORM 持久化 + 双库 SQL 执行对比。"""

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    def check_stock(
        self,
        session: Session,
        product_code: str,
    ) -> BusinessOperationResult:
        """查询产品库存。

        1. 通过 Repository 查找产品 ID
        2. 生成参数化查询库存的 SELECT SQL
        3. 通过 SQLKernel 在双库执行并对比

        Args:
            session: 源库 SQLAlchemy Session
            product_code: 产品编码
        """
        start = time.perf_counter()

        # 1. 查找产品 ID
        from app.repositories.product import ProductRepository

        prod_repo = ProductRepository(session)
        product = None
        all_prods, _ = prod_repo.list(limit=1000)
        for p in all_prods:
            if p.code == product_code:
                product = p
                break

        if product is None:
            raise ValueError(f"Product not found: {product_code}")

        # 2. 生成参数化查询 SQL
        sql = (
            "SELECT i.id, i.product_id, i.warehouse, i.quantity, "
            "i.min_quantity, i.updated_at "
            "FROM inventory i "
            "WHERE i.product_id = %s"
        )
        params = (product.id,)

        # 3. 通过 SQLKernel 在双库执行
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
            operation="check_stock",
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

    def adjust_stock(
        self,
        session: Session,
        product_code: str,
        delta: int,
        reason: str = "",
    ) -> BusinessOperationResult:
        """调整库存数量。

        1. 通过 Repository 在源库调整库存
        2. 生成参数化 UPDATE SQL
        3. 通过 SQLKernel 在双库执行并对比

        Args:
            session: 源库 SQLAlchemy Session
            product_code: 产品编码
            delta: 库存变动量（正=入库，负=出库）
            reason: 调整原因
        """
        start = time.perf_counter()

        # 1. 查找产品
        from app.repositories.product import ProductRepository

        prod_repo = ProductRepository(session)
        product = None
        all_prods, _ = prod_repo.list(limit=1000)
        for p in all_prods:
            if p.code == product_code:
                product = p
                break

        if product is None:
            raise ValueError(f"Product not found: {product_code}")

        # 2. ORM 调整库存（源库）
        inv_repo = InventoryRepository(session)
        inv = inv_repo.ensure_inventory(product.id)

        # 3. 生成参数化 UPDATE SQL
        update_sql = (
            "UPDATE inventory "
            "SET quantity = quantity + %s, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE product_id = %s"
        )
        update_params = (delta, product.id)

        verify_sql = (
            "SELECT id, product_id, warehouse, quantity, "
            "min_quantity, updated_at "
            "FROM inventory "
            "WHERE product_id = %s"
        )
        verify_params = (product.id,)

        # 4. 通过 SQLKernel 在双库执行 UPDATE
        exec_result = SQLKernel.execute_on_both(
            sql=update_sql,
            source_db=self.source_db,
            target_db=self.target_db,
            params=update_params,
            skip_validation=True,
            analyze_kernel=True,
        )

        # 5. 查询更新后的值进行对比
        verify_result = SQLKernel.execute_on_both(
            sql=verify_sql,
            source_db=self.source_db,
            target_db=self.target_db,
            params=verify_params,
            skip_validation=True,
            analyze_kernel=False,
        )

        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return BusinessOperationResult(
            operation="adjust_stock",
            source_db=self.source_db,
            target_db=self.target_db,
            generated_sql_source=update_sql,
            generated_sql_target=exec_result.rewritten_sql,
            source_result=verify_result.source_result or {},
            target_result=verify_result.target_result or {},
            kernel_analysis=exec_result.kernel,
            equal=verify_result.equal,
            diff_detail=verify_result.diff,
            execution_time_ms=elapsed,
        )
