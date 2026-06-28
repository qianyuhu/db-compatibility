"""
MigrationService — ERP 迁移流水线服务。

四阶段流水线:
    Phase 1: Schema Migration  — DDL 生成 + 在目标库执行
    Phase 2: Data Migration    — 批量复制数据（源库 → 目标库）
    Phase 3: Business Validation — 代表性业务操作双库对比
    Phase 4: Compatibility Report — 汇总所有发现

FK 依赖顺序: customers → products → orders → order_items → inventory
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.api.sql_demo.service import execute_sql
from app.core.sql_kernel.kernel import SQLKernel
from app.models import Customer, Inventory, Order, OrderItem, Product

from .schemas import (
    MigrationPhaseResult,
    MigrationPipelineResult,
)

logger = logging.getLogger(__name__)

# 表迁移顺序（按 FK 依赖排序）
_TABLE_ORDER = ["customers", "products", "orders", "order_items", "inventory"]

# 模型映射
_MODEL_MAP: dict[str, Any] = {
    "customers": Customer,
    "products": Product,
    "orders": Order,
    "order_items": OrderItem,
    "inventory": Inventory,
}


class MigrationService:
    """ERP 迁移流水线 — 从源库到目标库的完整迁移流程。"""

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    def run_migration(self, phases: list[str] | None = None) -> MigrationPipelineResult:
        """执行迁移流水线。

        Args:
            phases: 要执行的阶段列表，默认全部。
                ["schema", "data", "validation", "report"]
        """
        if phases is None:
            phases = ["schema", "data", "validation", "report"]

        total_start = time.perf_counter()
        results: list[MigrationPhaseResult] = []
        warnings: list[str] = []

        phase_map = {
            "schema": ("Schema Migration", self._migrate_schema),
            "data": ("Data Migration", self._migrate_data),
            "validation": ("Business Validation", self._validate_business),
            "report": ("Compatibility Report", self._generate_report),
        }

        for key in phases:
            if key not in phase_map:
                warnings.append(f"Unknown phase: {key}")
                continue

            name, fn = phase_map[key]
            phase_start = time.perf_counter()
            try:
                detail = fn()
                elapsed = round((time.perf_counter() - phase_start) * 1000, 1)
                results.append(
                    MigrationPhaseResult(
                        name=name,
                        status="success",
                        detail=detail,
                        elapsed_ms=elapsed,
                    )
                )
            except Exception as exc:
                elapsed = round((time.perf_counter() - phase_start) * 1000, 1)
                results.append(
                    MigrationPhaseResult(
                        name=name,
                        status="failed",
                        detail={},
                        error=str(exc),
                        elapsed_ms=elapsed,
                    )
                )
                warnings.append(f"{name} failed: {exc}")
                break  # 流水线中断

        total_ms = round((time.perf_counter() - total_start) * 1000, 1)

        # 判定总体状态
        statuses = [r.status for r in results]
        if all(s == "success" for s in statuses):
            overall = "success"
        elif any(s == "success" for s in statuses):
            overall = "partial"
        else:
            overall = "failed"

        return MigrationPipelineResult(
            source_db=self.source_db,
            target_db=self.target_db,
            phases=results,
            overall_status=overall,
            total_time_ms=total_ms,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Phase 1: Schema Migration
    # ------------------------------------------------------------------

    def _migrate_schema(self) -> dict[str, Any]:
        """生成 DDL 并在目标库执行。

        从 SQLAlchemy metadata 读取模型定义，生成目标方言的 CREATE TABLE 语句。
        """
        tables_created: list[str] = []
        ddl_statements: list[str] = []

        for table_name in _TABLE_ORDER:
            model = _MODEL_MAP.get(table_name)
            if model is None:
                continue

            ddl = self._generate_create_table(model)
            ddl_statements.append(ddl)

            try:
                execute_sql(self.target_db, ddl, skip_validation=True)
                tables_created.append(table_name)
            except Exception as exc:
                # 表可能已存在 — 记录警告并继续
                error_msg = str(exc).lower()
                if "already exists" in error_msg or "exists" in error_msg:
                    tables_created.append(table_name)
                else:
                    raise

        return {
            "tables_created": tables_created,
            "ddl_statements": ddl_statements,
            "count": len(tables_created),
        }

    @staticmethod
    def _generate_create_table(model: Any) -> str:
        """从 SQLAlchemy 模型生成 CREATE TABLE DDL（含 UNIQUE、FK）。"""
        table = model.__table__
        table_name = table.name
        cols: list[str] = []

        for col in table.columns:
            col_def = _column_ddl(col)
            cols.append(f"    {col_def}")

            # UNIQUE 约束（单列）
            if col.unique and not col.primary_key:
                cols.append(f"    UNIQUE ({col.name})")

            # FOREIGN KEY
            if col.foreign_keys:
                for fk in col.foreign_keys:
                    ref_table = fk.column.table.name
                    ref_col = fk.column.name
                    cols.append(
                        f"    FOREIGN KEY ({col.name}) "
                        f"REFERENCES {ref_table}({ref_col})"
                    )

        # 主键
        pk_cols = [c.name for c in table.primary_key.columns]
        if pk_cols:
            cols.append(f"    PRIMARY KEY ({', '.join(pk_cols)})")

        return f"CREATE TABLE {table_name} (\n" + ",\n".join(cols) + "\n)"

    # ------------------------------------------------------------------
    # Phase 2: Data Migration
    # ------------------------------------------------------------------

    def _migrate_data(self) -> dict[str, Any]:
        """从源库批量复制数据到目标库。

        按 FK 依赖顺序逐表复制，保留原始 ID。
        """
        table_results: dict[str, dict[str, int]] = {}
        total_rows: int = 0

        for table_name in _TABLE_ORDER:
            # 从源库读取
            select_sql = f"SELECT * FROM {table_name}"
            src_result = execute_sql(
                self.source_db, select_sql, skip_validation=True
            )

            if not src_result.get("success"):
                raise RuntimeError(
                    f"Failed to read from source: {src_result.get('error')}"
                )

            rows = src_result.get("rows", [])
            columns = src_result.get("columns", [])
            row_count = len(rows)

            # 写入目标库（逐行 INSERT，参数化）
            inserted = 0
            failures = 0
            for row in rows:
                insert_sql, insert_params = _build_insert_sql(table_name, columns, row)
                try:
                    execute_sql(
                        self.target_db, insert_sql, skip_validation=True,
                        params=insert_params,
                    )
                    inserted += 1
                except Exception as exc:
                    failures += 1
                    if failures <= 3:
                        logger.warning(
                            "Insert failed for %s: %s (sql=%s)",
                            table_name, exc, insert_sql[:120],
                        )

            table_results[table_name] = {
                "source_rows": row_count,
                "inserted": inserted,
                "failures": failures,
            }
            total_rows += inserted

        return {
            "tables": table_results,
            "total_rows_copied": total_rows,
        }

    # ------------------------------------------------------------------
    # Phase 3: Business Validation
    # ------------------------------------------------------------------

    def _validate_business(self) -> dict[str, Any]:
        """执行代表性业务操作，验证双库行为一致性。"""
        from .inventory_service import InventoryService
        from .order_service import OrderService

        validation_results: list[dict[str, Any]] = []

        # --- 库存查询验证 ---
        inv_svc = InventoryService(self.source_db, self.target_db)

        # 查询产品 P001 的库存（如果存在）
        stock_sql = (
            "SELECT i.product_id, p.code, i.quantity, i.warehouse "
            "FROM inventory i "
            "JOIN products p ON i.product_id = p.id "
            "WHERE p.code = 'P001'"
        )

        exec_result = SQLKernel.execute_on_both(
            sql=stock_sql,
            source_db=self.source_db,
            target_db=self.target_db,
            skip_validation=True,
            analyze_kernel=True,
        )

        validation_results.append({
            "operation": "check_stock_P001",
            "equal": exec_result.equal,
            "source_success": exec_result.source_result.get("success") if exec_result.source_result else False,
            "target_success": exec_result.target_result.get("success") if exec_result.target_result else False,
            "diff": exec_result.diff,
        })

        # --- 订单查询验证 ---
        order_svc = OrderService(self.source_db, self.target_db)

        count_sql = "SELECT COUNT(*) AS cnt FROM orders"
        count_result = SQLKernel.execute_on_both(
            sql=count_sql,
            source_db=self.source_db,
            target_db=self.target_db,
            skip_validation=True,
            analyze_kernel=True,
        )

        validation_results.append({
            "operation": "count_orders",
            "equal": count_result.equal,
            "source_success": count_result.source_result.get("success") if count_result.source_result else False,
            "target_success": count_result.target_result.get("success") if count_result.target_result else False,
            "diff": count_result.diff,
        })

        all_equal = all(r.get("equal") for r in validation_results)

        return {
            "operations": validation_results,
            "total": len(validation_results),
            "passed": sum(1 for r in validation_results if r.get("equal")),
            "all_equal": all_equal,
        }

    # ------------------------------------------------------------------
    # Phase 4: Compatibility Report
    # ------------------------------------------------------------------

    def _generate_report(self) -> dict[str, Any]:
        """汇总所有阶段的发现，生成兼容性报告。"""
        # 对每个表运行 COUNT 对比
        table_counts: dict[str, dict[str, Any]] = {}

        for table_name in _TABLE_ORDER:
            sql = f"SELECT COUNT(*) AS cnt FROM {table_name}"
            result = SQLKernel.execute_on_both(
                sql=sql,
                source_db=self.source_db,
                target_db=self.target_db,
                skip_validation=True,
                analyze_kernel=False,
            )
            table_counts[table_name] = {
                "equal": result.equal,
                "diff": result.diff,
            }

        all_match = all(tc["equal"] for tc in table_counts.values())
        match_count = sum(1 for tc in table_counts.values() if tc["equal"])

        return {
            "table_counts": table_counts,
            "tables_compared": len(_TABLE_ORDER),
            "tables_matched": match_count,
            "all_match": all_match,
            "score": round(match_count / len(_TABLE_ORDER) * 100),
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _column_ddl(col: Any) -> str:
    """将 SA Column 转为 DDL 片段。"""
    name = col.name
    type_name = _type_to_sql(col.type)

    parts = [name, type_name]

    if not col.nullable:
        parts.append("NOT NULL")

    if col.primary_key:
        # handled separately
        pass

    if col.server_default is not None:
        from sqlalchemy import DefaultClause

        if isinstance(col.server_default, DefaultClause):
            arg = col.server_default.arg
            if hasattr(arg, "text"):
                parts.append(f"DEFAULT {arg.text}")
            else:
                parts.append(f"DEFAULT {arg}")

    return " ".join(parts)


def _type_to_sql(sa_type: Any) -> str:
    """将 SA 类型映射为 SQL 类型名。"""
    from sqlalchemy import (
        Boolean,
        DateTime,
        Integer,
        Numeric,
        String,
        Text,
    )

    type_map = {
        Integer: "INTEGER",
        String: lambda t: f"VARCHAR({t.length})" if t.length else "VARCHAR",
        Numeric: lambda t: f"NUMERIC({t.precision},{t.scale})" if t.precision else "NUMERIC",
        Boolean: "BOOLEAN",
        DateTime: "TIMESTAMP",
        Text: "TEXT",
    }

    for sa_cls, sql_name in type_map.items():
        if isinstance(sa_type, sa_cls):
            if callable(sql_name):
                return sql_name(sa_type)
            return sql_name

    return "TEXT"


def _build_insert_sql(
    table_name: str, columns: list[str], row: list[Any]
) -> tuple[str, tuple]:
    """从列名和行数据生成参数化 INSERT 语句。

    Returns:
        (sql, params) — sql 使用 %s 占位符，params 为非 NULL 值元组
    """
    non_null_cols: list[str] = []
    params: list[Any] = []
    placeholders: list[str] = []

    for col_name, val in zip(columns, row):
        if val is None:
            continue  # 跳过 NULL 列
        non_null_cols.append(col_name)
        params.append(val)
        placeholders.append("%s")

    cols_str = ", ".join(non_null_cols)
    placeholders_str = ", ".join(placeholders)
    sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders_str})"
    return sql, tuple(params)
