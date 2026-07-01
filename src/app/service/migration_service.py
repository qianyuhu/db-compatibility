"""
MigrationService — ERP 迁移流水线服务。

四阶段流水线:
    Phase 1: Schema Migration  — DDL 生成 + 在目标库执行
    Phase 2: Data Migration    — 批量复制数据（源库 → 目标库）
    Phase 3: Business Validation — 代表性业务操作双库对比
    Phase 4: Compatibility Report — 汇总所有发现

FK 依赖顺序: customers → products → orders → order_items → inventory

Verification:
    verify_table_counts()  — 并行验证所有业务表双库行数
    validate_sql()          — 在双库上执行 SQL 并对比结果
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.api.sql_demo.service import execute_sql
from architecture.core.db.gateway import DBGateway
from app.models import Customer, Inventory, Order, OrderItem, Product

from app.api.schemas import (
    MigrationPhaseResult,
    MigrationPipelineResult,
)
from app.service._dual_exec import execute_on_both

logger = logging.getLogger(__name__)

# 表迁移顺序（按 FK 依赖排序）
_TABLE_ORDER = ["customers", "products", "orders", "order_items", "inventory"]

# 允许验证的表白名单 — 唯一来源，杜绝 SQL 注入
_ALLOWED_TABLES: set[str] = set(_TABLE_ORDER)

# SQL 模板映射 — 仅使用预定义模板，绝不拼接用户输入
_SQL_MAP: dict[str, str] = {
    table: f"SELECT COUNT(*) AS cnt FROM {table}"
    for table in _TABLE_ORDER
}

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

    def __init__(self, source_db: str, target_db: str, db: DBGateway | None = None):
        self.source_db = source_db
        self.target_db = target_db
        self.db = db  # Phase 4: 可选 DBGateway，过渡期使用

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

        ddl = f"CREATE TABLE {table_name} (\n" + ",\n".join(cols) + "\n)"
        
        # KingbaseES MSSQL 兼容模式修复:
        # TIMESTAMP 在 SQL Server 中是 rowversion 类型，不支持 DEFAULT
        # 需要替换为 DATETIME2
        ddl = ddl.replace("TIMESTAMP", "DATETIME2")
        
        return ddl

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

        exec_result = execute_on_both(
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
        count_result = execute_on_both(
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
            result = execute_on_both(
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
    # Verification — 数据一致性验证
    # ------------------------------------------------------------------

    @staticmethod
    def get_allowed_tables() -> list[str]:
        """返回允许验证的表列表（按 FK 依赖顺序）。前端应从此端点获取。"""
        return list(_TABLE_ORDER)

    def verify_table_counts(
        self, tables: list[str] | None = None
    ) -> dict[str, Any]:
        """并行验证每个业务表的双库行数是否一致。

        使用 ThreadPoolExecutor 并行执行，避免串行 10-15s 延迟。

        Args:
            tables: 要验证的表列表，默认全部。仅接受 _ALLOWED_TABLES 中的值。

        Returns:
            {
                "tables": [...],
                "all_match": bool,
                "match_count": int,
                "total_tables": int,
                "verified": bool,
                "total_time_ms": float,
            }
        """
        total_start = time.perf_counter()

        # 验证并过滤表名（白名单检查 — 杜绝 SQL 注入）
        if tables is None:
            tables = list(_TABLE_ORDER)
        else:
            invalid = [t for t in tables if t not in _ALLOWED_TABLES]
            if invalid:
                raise ValueError(
                    f"Invalid table(s): {', '.join(invalid)}. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_TABLES))}"
                )

        results: list[dict[str, Any]] = []

        # 并行验证所有表
        with ThreadPoolExecutor(max_workers=min(len(tables), 5)) as executor:
            future_map = {
                executor.submit(
                    self._verify_single_table, table_name
                ): table_name
                for table_name in tables
            }
            for future in as_completed(future_map):
                table_name = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "table_name": table_name,
                        "status": "ERROR",
                        "source_error": str(exc),
                        "target_error": str(exc),
                    }
                results.append(result)

        # 按 _TABLE_ORDER 排序
        results.sort(key=lambda r: _TABLE_ORDER.index(r["table_name"]))

        match_count = sum(1 for r in results if r.get("status") == "PASS")
        all_match = match_count == len(results)
        total_ms = round((time.perf_counter() - total_start) * 1000, 1)

        return {
            "tables": results,
            "all_match": all_match,
            "match_count": match_count,
            "total_tables": len(results),
            "verified": all_match,
            "total_time_ms": total_ms,
        }

    def _verify_single_table(self, table_name: str) -> dict[str, Any]:
        """验证单张表的双库行数。"""
        sql = _SQL_MAP[table_name]  # 使用预定义模板，绝不拼接

        try:
            exec_result = execute_on_both(
                sql=sql,
                source_db=self.source_db,
                target_db=self.target_db,
                skip_validation=True,
                analyze_kernel=False,
            )

            source_count = _extract_count(exec_result.source_result)
            target_count = _extract_count(exec_result.target_result)
            source_error = _extract_error(exec_result.source_result)
            target_error = _extract_error(exec_result.target_result)
            source_time = _extract_time(exec_result.source_result)
            target_time = _extract_time(exec_result.target_result)

            # 判定状态
            if source_error and target_error:
                status = "ERROR"
            elif source_error or target_error:
                status = "ERROR"
            elif source_count == target_count:
                status = "PASS"
            else:
                status = "FAIL"

            return {
                "table_name": table_name,
                "source_count": source_count,
                "target_count": target_count,
                "source_error": source_error,
                "target_error": target_error,
                "status": status,
                "source_time_ms": source_time,
                "target_time_ms": target_time,
            }
        except Exception as exc:
            return {
                "table_name": table_name,
                "status": "ERROR",
                "source_error": str(exc),
                "target_error": str(exc),
            }

    def validate_sql(self, sql: str) -> dict[str, Any]:
        """在双库上执行 SQL 并对比结果 — 含 3 层增强差异分析。

        Args:
            sql: 要验证的 SQL 语句。

        Returns:
            {
                "sql": str,
                "source_result": dict,
                "target_result": dict,
                "equal": bool,
                "diff_detail": list[dict],
                "enhanced_diff": dict | None,  # 3-layer diff
                "execution_time_ms": float,
            }
        """
        exec_result = execute_on_both(
            sql=sql,
            source_db=self.source_db,
            target_db=self.target_db,
            skip_validation=True,
            analyze_kernel=True,  # Enable kernel for rewrite context
        )

        def _to_result_dict(raw: dict[str, Any] | None) -> dict[str, Any]:
            if raw is None:
                return {
                    "success": False,
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "db_type": "",
                    "execution_time_ms": 0,
                    "error": "No result",
                    "suggestion": None,
                }
            return {
                "success": raw.get("success", False),
                "columns": raw.get("columns", []),
                "rows": raw.get("rows", []),
                "row_count": raw.get("row_count", 0),
                "db_type": raw.get("db_type", ""),
                "execution_time_ms": raw.get("execution_time_ms", 0),
                "error": raw.get("error"),
                "suggestion": raw.get("suggestion"),
            }

        src_result = _to_result_dict(exec_result.source_result)
        tgt_result = _to_result_dict(exec_result.target_result)

        # Compute 3-layer enhanced diff
        enhanced_diff: dict[str, Any] | None = None
        if not exec_result.equal:
            try:
                from app.api.sql_demo.explanation_engine import compute_enhanced_diff

                results_map = {
                    self.source_db: src_result,
                    self.target_db: tgt_result,
                }
                rewritten_sql = exec_result.rewritten_sql or ""
                enhanced = compute_enhanced_diff(
                    results=results_map,
                    original_sql=sql,
                    rewritten_sql=rewritten_sql,
                )
                enhanced_diff = enhanced.get("three_layer_diff")
            except Exception:
                enhanced_diff = None

        return {
            "sql": sql,
            "source_result": src_result,
            "target_result": tgt_result,
            "equal": exec_result.equal,
            "diff_detail": exec_result.diff,
            "enhanced_diff": enhanced_diff,
            "execution_time_ms": exec_result.execution_time_ms,
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
    from datetime import datetime

    non_null_cols: list[str] = []
    params: list[Any] = []
    placeholders: list[str] = []

    for col_name, val in zip(columns, row):
        if val is None:
            continue  # 跳过 NULL 列
        
        # KingbaseES MSSQL 兼容模式修复:
        # datetime 对象需要转为字符串，避免被识别为 rowversion
        if isinstance(val, datetime):
            val = val.strftime('%Y-%m-%d %H:%M:%S')
        
        non_null_cols.append(col_name)
        params.append(val)
        placeholders.append("%s")

    cols_str = ", ".join(non_null_cols)
    placeholders_str = ", ".join(placeholders)
    sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders_str})"
    return sql, tuple(params)


def _extract_count(result: dict[str, Any] | None) -> int | None:
    """从执行结果中提取 COUNT 值。"""
    if result is None or not result.get("success"):
        return None
    rows = result.get("rows", [])
    if rows and rows[0]:
        return int(rows[0][0]) if isinstance(rows[0], list) else int(rows[0])
    return None


def _extract_error(result: dict[str, Any] | None) -> str | None:
    """从执行结果中提取错误信息。"""
    if result is None:
        return "No result"
    if not result.get("success"):
        return result.get("error", "Unknown error")
    return None


def _extract_time(result: dict[str, Any] | None) -> float:
    """从执行结果中提取执行耗时。"""
    if result is None:
        return 0.0
    return result.get("execution_time_ms", 0.0)
