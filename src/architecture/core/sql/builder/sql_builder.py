"""
SQLBuilder — 方言安全的 SQL 构建器。

生成参数化的 CRUD SQL，适配不同数据库方言。

Usage:
    builder = SQLBuilder("mssql")
    sql, params = builder.select("customers", ["id", "code", "name"], where={"code": "C001"})
    # sql: "SELECT id, code, name FROM customers WHERE code = %s"
    # params: ("C001",)
"""

from __future__ import annotations

from typing import Any

from architecture.core.db.dialect import get_dialect


class SQLBuilder:
    """SQL 构建器 — 生成方言安全的参数化 SQL。"""

    def __init__(self, db_type: str = "mssql"):
        self._dialect = get_dialect(db_type)
        self._db_type = db_type

    def select(
        self,
        table: str,
        columns: list[str] | None = None,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[str, tuple]:
        """构建 SELECT 语句。

        Returns:
            (sql, params)
        """
        cols = ", ".join(columns) if columns else "*"
        sql = f"SELECT {cols} FROM {table}"
        params: list[Any] = []

        if where:
            conditions = []
            for key, value in where.items():
                if value is None:
                    conditions.append(f"{key} IS NULL")
                else:
                    conditions.append(f"{key} = %s")
                    params.append(value)
            sql += " WHERE " + " AND ".join(conditions)

        if order_by:
            sql += f" ORDER BY {order_by}"

        # 分页处理
        if limit is not None:
            if self._dialect.uses_top:
                # MSSQL: SELECT TOP N ...
                sql = sql.replace("SELECT", f"SELECT TOP {limit}", 1)
            elif self._dialect.supports_limit:
                sql += f" LIMIT {limit}"

        if offset is not None and self._dialect.supports_offset:
            sql += f" OFFSET {offset}"

        return sql, tuple(params)

    def insert(
        self,
        table: str,
        values: dict[str, Any],
    ) -> tuple[str, tuple]:
        """构建 INSERT 语句。

        Returns:
            (sql, params)
        """
        columns = list(values.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        cols_str = ", ".join(columns)
        sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
        params = tuple(values[k] for k in columns)
        return sql, params

    def update(
        self,
        table: str,
        values: dict[str, Any],
        where: dict[str, Any],
    ) -> tuple[str, tuple]:
        """构建 UPDATE 语句。

        Returns:
            (sql, params)
        """
        set_parts = []
        params: list[Any] = []

        for key, value in values.items():
            set_parts.append(f"{key} = %s")
            params.append(value)

        sql = f"UPDATE {table} SET {', '.join(set_parts)}"

        if where:
            conditions = []
            for key, value in where.items():
                if value is None:
                    conditions.append(f"{key} IS NULL")
                else:
                    conditions.append(f"{key} = %s")
                    params.append(value)
            sql += " WHERE " + " AND ".join(conditions)

        return sql, tuple(params)

    def delete(
        self,
        table: str,
        where: dict[str, Any] | None = None,
    ) -> tuple[str, tuple]:
        """构建 DELETE 语句。

        Returns:
            (sql, params)
        """
        sql = f"DELETE FROM {table}"
        params: list[Any] = []

        if where:
            conditions = []
            for key, value in where.items():
                if value is None:
                    conditions.append(f"{key} IS NULL")
                else:
                    conditions.append(f"{key} = %s")
                    params.append(value)
            sql += " WHERE " + " AND ".join(conditions)

        return sql, tuple(params)

    def count(
        self,
        table: str,
        where: dict[str, Any] | None = None,
    ) -> tuple[str, tuple]:
        """构建 COUNT 查询。

        Returns:
            (sql, params)
        """
        sql = f"SELECT COUNT(*) FROM {table}"
        params: list[Any] = []

        if where:
            conditions = []
            for key, value in where.items():
                if value is None:
                    conditions.append(f"{key} IS NULL")
                else:
                    conditions.append(f"{key} = %s")
                    params.append(value)
            sql += " WHERE " + " AND ".join(conditions)

        return sql, tuple(params)
