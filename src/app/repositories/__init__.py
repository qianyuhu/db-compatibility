"""Re-export shim — canonical location: app.repository"""
from app.repository import (  # noqa: F401
    Repository,
    ProductRepository,
    CustomerRepository,
    OrderRepository,
    InventoryRepository,
)

__all__ = [
    "Repository",
    "ProductRepository",
    "CustomerRepository",
    "OrderRepository",
    "InventoryRepository",
]
