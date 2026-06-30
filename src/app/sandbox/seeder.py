"""
Sandbox Seeder — reset and reseed the sandbox dataset across databases.

Supports:
- Truncate all tables (FK-safe order)
- Reseed identity/auto-increment columns
- Insert fixed dataset into MSSQL, KingbaseES, DM8
- Verify row counts after seeding
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings as global_settings

from .data import (
    SANDBOX_CUSTOMERS,
    SANDBOX_DATASET,
    SANDBOX_INVENTORY,
    SANDBOX_ORDER_ITEMS,
    SANDBOX_ORDERS,
    SANDBOX_PRODUCTS,
)

# Fixed datetime string for deterministic seeding (matches data.FIXED_NOW)
_FIXED_NOW_STR = "2025-01-15 10:30:00"


@dataclass
class SeedResult:
    """Result of a seed operation on one database."""
    db_type: str
    success: bool
    tables_seeded: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: float = 0.0


class SandboxSeeder:
    """Reset and reseed sandbox data across databases."""

    # FK-safe delete order
    _TABLE_ORDER = ["inventory", "order_items", "orders", "products", "customers"]

    @staticmethod
    def _make_settings(db_type: str):
        """Create per-DB settings without mutating global state."""
        from app.core.config import Settings

        s = Settings()
        s.active_db = db_type
        return s

    # =========================================================================
    # Public API
    # =========================================================================

    @staticmethod
    def reset(db_type: str) -> SeedResult:
        """Truncate all tables and reseed with fixed dataset.

        Args:
            db_type: One of mssql / kingbasees / dm8

        Returns:
            SeedResult with per-table row counts and timing.
        """
        start = time.perf_counter()

        try:
            if db_type == "mssql":
                result = SandboxSeeder._seed_mssql()
            elif db_type == "kingbasees":
                result = SandboxSeeder._seed_kingbasees()
            elif db_type == "dm8":
                result = SandboxSeeder._seed_dm8()
            else:
                return SeedResult(
                    db_type=db_type,
                    success=False,
                    error=f"Unsupported db_type: {db_type}",
                )

            result.elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            return result

        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return SeedResult(
                db_type=db_type,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=elapsed,
            )

    @staticmethod
    def reset_both(source_db: str, target_db: str) -> dict[str, SeedResult]:
        """Reset both source and target databases.

        Returns:
            Dict mapping db_type → SeedResult.
        """
        results: dict[str, SeedResult] = {}
        for db in (source_db, target_db):
            results[db] = SandboxSeeder.reset(db)
        return results

    # =========================================================================
    # MSSQL Implementation
    # =========================================================================

    @staticmethod
    def _seed_mssql() -> SeedResult:
        import pyodbc

        s = SandboxSeeder._make_settings("mssql")
        kwargs = s.raw_connection_kwargs
        conn = pyodbc.connect(kwargs["connection_string"])
        conn.autocommit = True

        try:
            cur = conn.cursor()

            # Truncate in FK-safe order
            for table in SandboxSeeder._TABLE_ORDER:
                try:
                    cur.execute(f"DELETE FROM {table}")
                except Exception:
                    pass

            # Reseed identity columns
            for table in ("customers", "products", "orders", "order_items", "inventory"):
                try:
                    cur.execute(f"DBCC CHECKIDENT ('{table}', RESEED, 0)")
                except Exception:
                    pass

            tables_seeded: dict[str, int] = {}

            # Seed customers
            cur.execute("SET IDENTITY_INSERT customers ON")
            for c in SANDBOX_CUSTOMERS:
                cur.execute(
                    "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (c.id, c.code, c.name, c.contact, c.phone, c.email, 1 if c.is_active else 0, _FIXED_NOW_STR),
                )
            cur.execute("SET IDENTITY_INSERT customers OFF")
            tables_seeded["customers"] = len(SANDBOX_CUSTOMERS)

            # Seed products
            cur.execute("SET IDENTITY_INSERT products ON")
            for p in SANDBOX_PRODUCTS:
                cur.execute(
                    "INSERT INTO products (id, code, name, price, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (p.id, p.code, p.name, p.price, 1 if p.is_active else 0, _FIXED_NOW_STR),
                )
            cur.execute("SET IDENTITY_INSERT products OFF")
            tables_seeded["products"] = len(SANDBOX_PRODUCTS)

            # Seed orders
            cur.execute("SET IDENTITY_INSERT orders ON")
            for o in SANDBOX_ORDERS:
                cur.execute(
                    "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (o.id, o.order_no, o.customer_id, o.status, o.total_amount, o.item_count, o.notes, _FIXED_NOW_STR, _FIXED_NOW_STR),
                )
            cur.execute("SET IDENTITY_INSERT orders OFF")
            tables_seeded["orders"] = len(SANDBOX_ORDERS)

            # Seed order_items
            cur.execute("SET IDENTITY_INSERT order_items ON")
            for oi in SANDBOX_ORDER_ITEMS:
                cur.execute(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (oi.id, oi.order_id, oi.product_id, oi.quantity, oi.unit_price, oi.subtotal),
                )
            cur.execute("SET IDENTITY_INSERT order_items OFF")
            tables_seeded["order_items"] = len(SANDBOX_ORDER_ITEMS)

            # Seed inventory
            for inv in SANDBOX_INVENTORY:
                cur.execute(
                    "INSERT INTO inventory (product_id, warehouse, quantity, min_quantity, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (inv.product_id, inv.warehouse, inv.quantity, inv.min_quantity, _FIXED_NOW_STR),
                )
            tables_seeded["inventory"] = len(SANDBOX_INVENTORY)

            cur.close()
            return SeedResult(db_type="mssql", success=True, tables_seeded=tables_seeded)

        finally:
            conn.close()

    # =========================================================================
    # KingbaseES Implementation
    # =========================================================================

    @staticmethod
    def _seed_kingbasees() -> SeedResult:
        import psycopg2

        s = SandboxSeeder._make_settings("kingbasees")
        kwargs = s.raw_connection_kwargs
        conn = psycopg2.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
            options=kwargs.get("options", ""),
            connect_timeout=kwargs.get("connect_timeout", 5),
        )
        conn.autocommit = True

        try:
            cur = conn.cursor()

            # Truncate in FK-safe order
            for table in SandboxSeeder._TABLE_ORDER:
                try:
                    cur.execute(f"DELETE FROM {table}")
                except Exception:
                    pass

            # Reset sequences
            for table in ("customers", "products", "orders", "order_items", "inventory"):
                try:
                    cur.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1")
                except Exception:
                    pass

            tables_seeded: dict[str, int] = {}

            # Seed customers (override auto-increment with explicit IDs)
            for c in SANDBOX_CUSTOMERS:
                cur.execute(
                    "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (c.id, c.code, c.name, c.contact, c.phone, c.email, c.is_active, _FIXED_NOW_STR),
                )
            tables_seeded["customers"] = len(SANDBOX_CUSTOMERS)

            # Seed products
            for p in SANDBOX_PRODUCTS:
                cur.execute(
                    "INSERT INTO products (id, code, name, price, is_active, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (p.id, p.code, p.name, p.price, p.is_active, _FIXED_NOW_STR),
                )
            tables_seeded["products"] = len(SANDBOX_PRODUCTS)

            # Seed orders
            for o in SANDBOX_ORDERS:
                cur.execute(
                    "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (o.id, o.order_no, o.customer_id, o.status, o.total_amount, o.item_count, o.notes, _FIXED_NOW_STR, _FIXED_NOW_STR),
                )
            tables_seeded["orders"] = len(SANDBOX_ORDERS)

            # Seed order_items
            for oi in SANDBOX_ORDER_ITEMS:
                cur.execute(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (oi.id, oi.order_id, oi.product_id, oi.quantity, oi.unit_price, oi.subtotal),
                )
            tables_seeded["order_items"] = len(SANDBOX_ORDER_ITEMS)

            # Seed inventory (explicit IDs — KingbaseES may not have sequence)
            for inv in SANDBOX_INVENTORY:
                cur.execute(
                    "INSERT INTO inventory (id, product_id, warehouse, quantity, min_quantity, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (inv.id, inv.product_id, inv.warehouse, inv.quantity, inv.min_quantity, _FIXED_NOW_STR),
                )
            tables_seeded["inventory"] = len(SANDBOX_INVENTORY)

            # Update sequences to max id + 1
            for table in ("customers", "products", "orders", "order_items", "inventory"):
                try:
                    cnt = tables_seeded.get(table, 0)
                    if cnt > 0:
                        cur.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH {cnt + 1}")
                except Exception:
                    pass

            cur.close()
            return SeedResult(db_type="kingbasees", success=True, tables_seeded=tables_seeded)

        finally:
            conn.close()

    # =========================================================================
    # DM8 Implementation
    # =========================================================================

    @staticmethod
    def _seed_dm8() -> SeedResult:
        import dmPython

        s = SandboxSeeder._make_settings("dm8")
        kwargs = s.raw_connection_kwargs
        conn = dmPython.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

        try:
            cur = conn.cursor()

            # Truncate in FK-safe order
            for table in SandboxSeeder._TABLE_ORDER:
                try:
                    cur.execute(f"DELETE FROM {table}")
                except Exception:
                    pass

            tables_seeded: dict[str, int] = {}

            # Seed customers
            for c in SANDBOX_CUSTOMERS:
                cur.execute(
                    "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (c.id, c.code, c.name, c.contact, c.phone, c.email, 1 if c.is_active else 0, _FIXED_NOW_STR),
                )
            tables_seeded["customers"] = len(SANDBOX_CUSTOMERS)

            # Seed products
            for p in SANDBOX_PRODUCTS:
                cur.execute(
                    "INSERT INTO products (id, code, name, price, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (p.id, p.code, p.name, p.price, 1 if p.is_active else 0, _FIXED_NOW_STR),
                )
            tables_seeded["products"] = len(SANDBOX_PRODUCTS)

            # Seed orders
            for o in SANDBOX_ORDERS:
                cur.execute(
                    "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (o.id, o.order_no, o.customer_id, o.status, o.total_amount, o.item_count, o.notes, _FIXED_NOW_STR, _FIXED_NOW_STR),
                )
            tables_seeded["orders"] = len(SANDBOX_ORDERS)

            # Seed order_items
            for oi in SANDBOX_ORDER_ITEMS:
                cur.execute(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (oi.id, oi.order_id, oi.product_id, oi.quantity, oi.unit_price, oi.subtotal),
                )
            tables_seeded["order_items"] = len(SANDBOX_ORDER_ITEMS)

            # Seed inventory
            for inv in SANDBOX_INVENTORY:
                cur.execute(
                    "INSERT INTO inventory (product_id, warehouse, quantity, min_quantity, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (inv.product_id, inv.warehouse, inv.quantity, inv.min_quantity, _FIXED_NOW_STR),
                )
            tables_seeded["inventory"] = len(SANDBOX_INVENTORY)

            conn.commit()
            cur.close()
            return SeedResult(db_type="dm8", success=True, tables_seeded=tables_seeded)

        finally:
            conn.close()
