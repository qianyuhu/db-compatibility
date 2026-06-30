"""
DB Adapter Layer — unified database execution interface.

Provides a Protocol-based abstraction over MSSQL, KingbaseES, and DM8
so that the certification engine and test harness can work with any
database through the same interface.

Usage:
    from app.sandbox.adapter.factory import create_adapter

    adapter = create_adapter("mssql")
    result = adapter.execute_sql("SELECT * FROM customers")
    adapter.close()
"""
