"""
DB Adapter Factory — registry-based factory for creating database adapters.

Usage:
    from app.sandbox.adapter.factory import create_adapter

    adapter = create_adapter("mssql")
    # use adapter...
    adapter.close()
"""

from __future__ import annotations

from typing import Type

from .mssql import MSSQLAdapter
from .kingbase import KingbaseAdapter
from .dm import DMAdapter
from .protocol import DBAdapter

# =========================================================================
# Registry
# =========================================================================

_ADAPTER_REGISTRY: dict[str, Type[DBAdapter]] = {}


def register_adapter(db_type: str, adapter_cls: Type[DBAdapter]) -> None:
    """Register an adapter class for a database type.

    Args:
        db_type: Database type identifier (e.g., "mssql", "kingbasees", "dm8")
        adapter_cls: Class that implements the DBAdapter protocol.
    """
    _ADAPTER_REGISTRY[db_type] = adapter_cls


def create_adapter(db_type: str) -> DBAdapter:
    """Create a database adapter for the given type.

    Args:
        db_type: One of "mssql", "kingbasees", "dm8"

    Returns:
        A DBAdapter instance.

    Raises:
        ValueError: If no adapter is registered for the given db_type.
    """
    cls = _ADAPTER_REGISTRY.get(db_type)
    if cls is None:
        available = sorted(_ADAPTER_REGISTRY.keys())
        raise ValueError(
            f"No adapter registered for db_type='{db_type}'. "
            f"Available: {available}"
        )
    return cls()


def list_adapters() -> list[str]:
    """List all registered adapter types."""
    return sorted(_ADAPTER_REGISTRY.keys())


# =========================================================================
# Registration at module load
# =========================================================================

register_adapter("mssql", MSSQLAdapter)
register_adapter("kingbasees", KingbaseAdapter)
register_adapter("dm8", DMAdapter)
