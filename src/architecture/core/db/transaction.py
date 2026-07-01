"""
Transaction — 事务上下文管理器。

提供统一的事务接口，屏蔽不同数据库的事务差异。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


class TransactionContext:
    """事务上下文管理器。

    Usage:
        with gateway.transaction() as txn:
            txn.execute("INSERT INTO ...")
            txn.execute("UPDATE ...")
            # auto-commit on success, auto-rollback on exception
    """

    def __init__(self, conn: Any, db_type: str, autocommit: bool = True):
        self._conn = conn
        self._db_type = db_type
        self._autocommit = autocommit
        self._cursor = None
        self._committed = False

    def execute(self, sql: str, params: tuple | None = None) -> Any:
        """在事务中执行 SQL。"""
        if self._cursor is None:
            self._cursor = self._conn.cursor()

        if params:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)

        return self._cursor

    def fetchall(self) -> list:
        """获取所有结果行。"""
        if self._cursor is None:
            return []
        try:
            return self._cursor.fetchall()
        except Exception:
            return []

    def fetchone(self) -> Any:
        """获取单行结果。"""
        if self._cursor is None:
            return None
        try:
            return self._cursor.fetchone()
        except Exception:
            return None

    @property
    def description(self) -> list | None:
        """获取游标列描述。"""
        if self._cursor is None:
            return None
        return self._cursor.description

    def commit(self):
        """手动提交。"""
        if not self._committed:
            if self._db_type in ("mssql", "dm8"):
                # pyodbc / dmPython: conn.commit()
                self._conn.commit()
            # kingbasees: autocommit mode, no explicit commit needed
            self._committed = True

    def rollback(self):
        """手动回滚。"""
        if not self._committed:
            try:
                if self._db_type in ("mssql", "dm8"):
                    self._conn.rollback()
            except Exception:
                pass

    def close(self):
        """关闭游标。"""
        if self._cursor is not None:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None


class NullTransaction:
    """空事务 — 用于 autocommit 模式下的 KingbaseES。"""

    def __init__(self, conn: Any, db_type: str):
        self._conn = conn
        self._db_type = db_type
        self._cursor = None

    def execute(self, sql: str, params: tuple | None = None) -> Any:
        if self._cursor is None:
            self._cursor = self._conn.cursor()
        if params:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
        return self._cursor

    def fetchall(self) -> list:
        if self._cursor is None:
            return []
        try:
            return self._cursor.fetchall()
        except Exception:
            return []

    def fetchone(self) -> Any:
        if self._cursor is None:
            return None
        try:
            return self._cursor.fetchone()
        except Exception:
            return None

    @property
    def description(self) -> list | None:
        if self._cursor is None:
            return None
        return self._cursor.description

    def commit(self):
        pass  # autocommit mode

    def rollback(self):
        pass  # autocommit mode

    def close(self):
        if self._cursor is not None:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None
