"""add business models: customers, orders, order_items, inventory

Revision ID: 002
Revises: 001
Create Date: 2026-06-28

FK dependency order (for data migration):
  customers → products → orders → order_items → inventory
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.Unicode(200), nullable=False),
        sa.Column("contact", sa.Unicode(100), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("email", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_customers_code"), "customers", ["code"])

    # --- orders ---
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_no", sa.String(50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default=sa.text("'PENDING'")),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
    )
    op.create_index(op.f("ix_orders_order_no"), "orders", ["order_no"])

    # --- order_items ---
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
    )

    # --- inventory ---
    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse", sa.String(50), nullable=False,
                  server_default=sa.text("'MAIN'")),
        sa.Column("quantity", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("min_quantity", sa.Integer(), nullable=False,
                  server_default=sa.text("10")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
    )


def downgrade() -> None:
    op.drop_table("inventory")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("customers")
