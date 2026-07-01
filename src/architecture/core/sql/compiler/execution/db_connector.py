"""
Database connector for CFG Workbench execution engine.

Provides independent database connections for compiling and executing
stored procedures across MSSQL, KingbaseES, and DM8 — without depending
on the sql_demo service layer.
"""

from __future__ import annotations

from typing import Any


def get_connection(db_type: str) -> Any:
    """Get a raw database connection for the specified database type.

    Uses the project's Settings configuration to obtain connection parameters.
    Each call creates a new connection — callers are responsible for closing it.

    Args:
        db_type: One of "mssql", "kingbasees", "dm8".

    Returns:
        A PEP-249 compatible database connection.
    """
    from app.core.config import Settings

    s = Settings()
    s.active_db = db_type  # ensure correct connection params
    kwargs = s.raw_connection_kwargs

    if db_type == "mssql":
        import pyodbc
        return pyodbc.connect(kwargs["connection_string"])

    elif db_type == "kingbasees":
        import psycopg2
        conn = psycopg2.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
            options=kwargs.get("options", ""),
            connect_timeout=kwargs.get("connect_timeout", 10),
        )
        conn.autocommit = True
        return conn

    elif db_type == "dm8":
        import dmPython
        return dmPython.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    raise ValueError(f"Unsupported db_type: {db_type}")
