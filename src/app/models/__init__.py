"""Re-export shim — canonical location: architecture.domain.models"""
from architecture.domain.models import (  # noqa: F401
    Base,
    Customer,
    Inventory,
    Order,
    OrderItem,
    Product,
)

__all__ = ["Base", "Product", "Customer", "Order", "OrderItem", "Inventory"]
