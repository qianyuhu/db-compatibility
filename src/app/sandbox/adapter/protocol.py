"""
DB Adapter Protocol — unified interface for database operations.

All adapters implement this protocol so the certification engine,
test runner, and seeder can work with any database through the same
interface without knowing which database is underneath.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..data import SandboxDataset
from ..seeder import SeedResult


@dataclass
class SchemaReport:
    """Result of schema validation."""
    tables: list[str] = field(default_factory=list)
    column_count: int = 0
    has_identity: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class ExecuteResult:
    """Structured result from adapter.execute_sql()."""
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    db_type: str = ""
    execution_time_ms: float = 0.0
    error: str | None = None
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by existing consumers."""
        return {
            "success": self.success,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "db_type": self.db_type,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
            "suggestion": self.suggestion,
        }


class DBAdapter(Protocol):
    """Unified database execution interface.

    All database implementations (MSSQL, KingbaseES, DM8) conform
    to this protocol so that callers don't need per-DB branching.

    Usage:
        adapter = create_adapter("mssql")
        result = adapter.execute_sql("SELECT * FROM customers")
        schema = adapter.validate_schema()
        seed = adapter.seed_data(dataset)
        adapter.close()
    """

    def execute_sql(
        self,
        sql: str,
        *,
        params: tuple[Any, ...] | None = None,
        timeout: int = 30,
    ) -> ExecuteResult:
        """Execute SQL and return structured result.

        Args:
            sql: SQL statement to execute
            params: Optional query parameters
            timeout: Execution timeout in seconds

        Returns:
            ExecuteResult with columns, rows, timing, and error info.
        """
        ...

    def validate_schema(self) -> SchemaReport:
        """Query INFORMATION_SCHEMA to validate table/column structure.

        Returns:
            SchemaReport listing tables, column count, identity support.
        """
        ...

    def seed_data(
        self,
        dataset: SandboxDataset | None = None,
    ) -> SeedResult:
        """Truncate all tables and reseed with deterministic dataset.

        Args:
            dataset: SandboxDataset to seed (defaults to the built-in dataset)

        Returns:
            SeedResult with per-table row counts and error info.
        """
        ...

    def get_db_type(self) -> str:
        """Return the database type identifier.

        Returns:
            One of: "mssql", "kingbasees", "dm8"
        """
        ...

    def close(self) -> None:
        """Release connection resources."""
        ...

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit — auto-closes connection."""
        self.close()
