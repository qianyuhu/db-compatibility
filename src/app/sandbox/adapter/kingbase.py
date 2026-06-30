"""
KingbaseES Adapter — KingbaseES via psycopg2 (PG wire-protocol).

Implements the DBAdapter protocol for KingbaseES MSSQL Compatible Edition.
Uses PostgreSQL wire protocol on port 54321.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.config import Settings

from ..data import (
    SANDBOX_CUSTOMERS,
    SANDBOX_INVENTORY,
    SANDBOX_ORDER_ITEMS,
    SANDBOX_ORDERS,
    SANDBOX_PRODUCTS,
    SandboxDataset,
)
from ..seeder import SeedResult
from .protocol import ExecuteResult, SchemaReport

_FIXED_NOW_STR = "2025-01-15 10:30:00"
_TABLE_ORDER = ["inventory", "order_items", "orders", "products", "customers"]


class KingbaseAdapter:
    """KingbaseES adapter via psycopg2 (PG wire-protocol compatible)."""

    def __init__(self):
        self._conn = None
        self._cur = None
        self._db_type = "kingbasees"

    # =========================================================================
    # Connection management
    # =========================================================================

    def _ensure_connected(self):
        """Lazy-connect on first use."""
        if self._conn is not None:
            return
        import psycopg2

        s = self._make_settings()
        kwargs = s.raw_connection_kwargs
        self._conn = psycopg2.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
            options=kwargs.get("options", ""),
            connect_timeout=kwargs.get("connect_timeout", 5),
        )
        self._conn.autocommit = True
        self._cur = self._conn.cursor()

    @staticmethod
    def _make_settings() -> Settings:
        s = Settings()
        s.active_db = "kingbasees"
        return s

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release connection resources."""
        if self._cur is not None:
            try:
                self._cur.close()
            except Exception:
                pass
            self._cur = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def get_db_type(self) -> str:
        return self._db_type

    # =========================================================================
    # SQL Execution
    # =========================================================================

    def execute_sql(
        self,
        sql: str,
        *,
        params: tuple[Any, ...] | None = None,
        timeout: int = 30,
    ) -> ExecuteResult:
        """Execute SQL on KingbaseES via psycopg2."""
        start = time.perf_counter()
        try:
            self._ensure_connected()
            if params:
                self._cur.execute(sql, params)
            else:
                self._cur.execute(sql)

            columns: list[str] = []
            rows: list[list[Any]] = []
            try:
                columns = [d[0] for d in self._cur.description] if self._cur.description else []
                rows = [list(row) for row in self._cur.fetchall()]
            except Exception:
                pass  # Non-SELECT statements

            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return ExecuteResult(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                db_type=self._db_type,
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return ExecuteResult(
                success=False,
                db_type=self._db_type,
                execution_time_ms=elapsed,
                error=f"{type(exc).__name__}: {exc}",
                suggestion="Check psycopg2 and KingbaseES connectivity on port 54321",
            )

    # =========================================================================
    # Schema Validation
    # =========================================================================

    def validate_schema(self) -> SchemaReport:
        """Query INFORMATION_SCHEMA for table structure.

        Note: KingbaseES uses sys_* catalogs internally but supports
        INFORMATION_SCHEMA views.
        """
        try:
            self._ensure_connected()
            self._cur.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = 'public' ORDER BY TABLE_NAME"
            )
            tables = [row[0] for row in self._cur.fetchall()]

            col_count = 0
            for table in tables:
                try:
                    self._cur.execute(
                        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME = %s",
                        (table,),
                    )
                    count_row = self._cur.fetchone()
                    if count_row:
                        col_count += count_row[0]
                except Exception:
                    pass

            # KingbaseES supports sequences (not IDENTITY)
            return SchemaReport(
                tables=tables,
                column_count=col_count,
                has_identity=False,
            )
        except Exception as exc:
            return SchemaReport(errors=[f"{type(exc).__name__}: {exc}"])

    # =========================================================================
    # Seed Data
    # =========================================================================

    def seed_data(self, dataset: SandboxDataset | None = None) -> SeedResult:
        """Truncate and reseed with deterministic dataset."""
        start = time.perf_counter()
        try:
            self._ensure_connected()

            if dataset is not None:
                customers = dataset.customers
                products = dataset.products
                orders = dataset.orders
                order_items = dataset.order_items
                inventory = dataset.inventory
            else:
                customers = SANDBOX_CUSTOMERS
                products = SANDBOX_PRODUCTS
                orders = SANDBOX_ORDERS
                order_items = SANDBOX_ORDER_ITEMS
                inventory = SANDBOX_INVENTORY

            # Truncate in FK-safe order
            for table in _TABLE_ORDER:
                try:
                    self._cur.execute(f"DELETE FROM {table}")
                except Exception:
                    pass

            # Reset sequences
            for table in ("customers", "products", "orders", "order_items", "inventory"):
                try:
                    self._cur.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1")
                except Exception:
                    pass

            tables_seeded: dict[str, int] = {}

            # Seed customers
            for c in customers:
                self._cur.execute(
                    "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (c.id, c.code, c.name, c.contact, c.phone, c.email, c.is_active, _FIXED_NOW_STR),
                )
            tables_seeded["customers"] = len(customers)

            # Seed products
            for p in products:
                self._cur.execute(
                    "INSERT INTO products (id, code, name, price, is_active, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (p.id, p.code, p.name, p.price, p.is_active, _FIXED_NOW_STR),
                )
            tables_seeded["products"] = len(products)

            # Seed orders
            for o in orders:
                self._cur.execute(
                    "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (o.id, o.order_no, o.customer_id, o.status, o.total_amount, o.item_count, o.notes, _FIXED_NOW_STR, _FIXED_NOW_STR),
                )
            tables_seeded["orders"] = len(orders)

            # Seed order_items
            for oi in order_items:
                self._cur.execute(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (oi.id, oi.order_id, oi.product_id, oi.quantity, oi.unit_price, oi.subtotal),
                )
            tables_seeded["order_items"] = len(order_items)

            # Seed inventory
            for inv in inventory:
                self._cur.execute(
                    "INSERT INTO inventory (id, product_id, warehouse, quantity, min_quantity, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (inv.id, inv.product_id, inv.warehouse, inv.quantity, inv.min_quantity, _FIXED_NOW_STR),
                )
            tables_seeded["inventory"] = len(inventory)

            # Update sequences to max id + 1
            for table in ("customers", "products", "orders", "order_items", "inventory"):
                try:
                    cnt = tables_seeded.get(table, 0)
                    if cnt > 0:
                        self._cur.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH {cnt + 1}")
                except Exception:
                    pass

            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return SeedResult(
                db_type=self._db_type,
                success=True,
                tables_seeded=tables_seeded,
                elapsed_ms=elapsed,
            )

        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return SeedResult(
                db_type=self._db_type,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=elapsed,
            )
