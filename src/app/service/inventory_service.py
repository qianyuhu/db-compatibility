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

from sqlalchemy.orm import Session  # deprecated: will be removed

from architecture.core.db.gateway import DBGateway
from app.repository.inventory import InventoryRepository

from app.api.schemas import BusinessOperationResult
from app.service._dual_exec import execute_on_both


class InventoryService:
    """库存业务服务 — 源库 ORM 持久化 + 双库 SQL 执行对比。"""

    def __init__(self, source_db: str, target_db: str, db: DBGateway | None = None):
        self.source_db = source_db
        self.target_db = target_db
        self.db = db  # Phase 4: 可选 DBGateway，过渡期使用

    def check_stock(
        self,
        session: Session,
        product_code: str | None = None,
        warehouse_id: str | None = None,
        stock_status: str | None = None,
        keyword: str | None = None,
    ) -> BusinessOperationResult:
        """查询产品库存 — 支持灵活可选筛选（ERP 风格）。

        用例:
            A. 无筛选 → SELECT * FROM inventory LIMIT 100
            B. 按 product_code → WHERE product_code = ?
            C. 混合筛选 → WHERE warehouse_id = ? AND stock_status = ?
            D. 关键词搜索 → JOIN products WHERE name/code LIKE ?

        Args:
            session: 源库 SQLAlchemy Session
            product_code: 产品编码（可选）
            warehouse_id: 仓库 ID（可选）
            stock_status: "low"=低于最低库存, "normal"=正常（可选）
            keyword: 关键词搜索产品名/编码（可选）
        """
        start = time.perf_counter()

        # ---- 构建动态 SQL ----
        has_filters = any([
            product_code is not None,
            warehouse_id is not None,
            stock_status is not None,
            keyword is not None,
        ])

        base_select = (
            "SELECT i.id, i.product_id, i.warehouse, i.quantity, "
            "i.min_quantity, i.updated_at "
            "FROM inventory i"
        )

        joins: list[str] = []
        conditions: list[str] = []
        params_list: list[Any] = []

        # 产品编码筛选
        if product_code is not None:
            joins.append("JOIN products p ON i.product_id = p.id")
            conditions.append("p.code = %s")
            params_list.append(product_code)

        # 仓库筛选
        if warehouse_id is not None:
            conditions.append("i.warehouse = %s")
            params_list.append(warehouse_id)

        # 库存状态筛选
        if stock_status == "low":
            conditions.append("i.quantity < i.min_quantity")
        elif stock_status == "normal":
            conditions.append("i.quantity >= i.min_quantity")
        # "all" or None → no status filter

        # 关键词搜索（产品名或编码）
        if keyword is not None:
            if "p" not in [j for j in joins if "products p" in j]:
                joins.append("JOIN products p ON i.product_id = p.id")
            conditions.append("(p.name LIKE %s OR p.code LIKE %s)")
            kw_pattern = f"%{keyword}%"
            params_list.append(kw_pattern)
            params_list.append(kw_pattern)

        # 组装 SQL
        sql_parts = [base_select]
        sql_parts.extend(joins)

        if conditions:
            sql_parts.append("WHERE " + " AND ".join(conditions))

        if not has_filters:
            if self.source_db == "mssql":
                # MSSQL 不支持 LIMIT，使用 SELECT TOP N
                sql_parts[0] = sql_parts[0].replace("SELECT", "SELECT TOP 100", 1)
            else:
                sql_parts.append("LIMIT 100")

        sql = " ".join(sql_parts)
        params = tuple(params_list) if params_list else None

        # 3. 通过双库执行
        exec_result = execute_on_both(
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
        from app.repository.product import ProductRepository

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

        # 4. 通过双库执行 UPDATE
        exec_result = execute_on_both(
            sql=update_sql,
            source_db=self.source_db,
            target_db=self.target_db,
            params=update_params,
            skip_validation=True,
            analyze_kernel=True,
        )

        # 5. 查询更新后的值进行对比
        verify_result = execute_on_both(
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
