"""
DBGateway — 统一数据库访问入口。

替代:
    - SQLAlchemy Session (ORM)
    - raw driver 直接调用 (pyodbc / psycopg2 / dmPython)

所有业务层通过 DBGateway 访问数据库，不再直接接触 driver。

Usage:
    gateway = DBGateway()  # 使用 settings.active_db
    rows = gateway.query("SELECT * FROM customers")
    gateway.execute("INSERT INTO customers (code, name) VALUES (%s, %s)", ("C001", "Test"))

    with gateway.transaction() as txn:
        txn.execute("INSERT INTO ...")
        txn.execute("UPDATE ...")
        # auto-commit / auto-rollback
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from architecture.core.config import settings
from architecture.core.db.dialect import DialectSpec, get_dialect
from architecture.core.db.transaction import NullTransaction, TransactionContext
from architecture.core.sql.dialect.base import BaseDialect as SqlDialect
from architecture.core.sql.rewrite.pipeline import compile_sql

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecuteResult:
    """执行结果。"""

    success: bool = True
    rows_affected: int = 0
    error: str | None = None


@dataclass
class QueryResult:
    """查询结果。"""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    success: bool = True
    error: str | None = None

    def to_dicts(self) -> list[dict[str, Any]]:
        """将结果转为 dict 列表。"""
        return [dict(zip(self.columns, row)) for row in self.rows]


class DBGateway:
    """统一数据库网关。

    封装 MSSQL / KingbaseES / DM8 三种数据库的连接和执行。
    内部复用 database.py 的底层连接管理。
    """

    def __init__(self, db_type: str | None = None):
        """初始化网关。

        Args:
            db_type: 数据库类型，默认使用 settings.active_db。
        """
        self._db_type = db_type or settings.active_db
        self._dialect = get_dialect(self._db_type)

    @property
    def db_type(self) -> str:
        return self._db_type

    @property
    def dialect(self) -> DialectSpec:
        return self._dialect

    def _get_connection(self, db_name: str | None = None):
        """获取底层数据库连接。"""
        from architecture.database import get_raw_connection
        return get_raw_connection(db_name)

    def _is_kingbasees(self) -> bool:
        return self._db_type == "kingbasees"

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple | None = None) -> ExecuteResult:
        """执行写操作 (INSERT / UPDATE / DELETE / DDL)。

        Args:
            sql: SQL 语句（使用 %s 占位符）。
            params: 参数化查询参数。

        Returns:
            ExecuteResult 包含成功状态和影响行数。
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            rows_affected = cursor.rowcount if cursor.rowcount >= 0 else 0

            # MSSQL/DM8 需要显式 commit
            if not self._is_kingbasees():
                conn.commit()

            return ExecuteResult(success=True, rows_affected=rows_affected)

        except Exception as exc:
            logger.error("DBGateway.execute failed: %s", exc)
            if conn and not self._is_kingbasees():
                try:
                    conn.rollback()
                except Exception:
                    pass
            return ExecuteResult(success=False, error=str(exc))

        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def query(self, sql: str, params: tuple | None = None) -> QueryResult:
        """执行读操作 (SELECT)。

        Args:
            sql: SQL 查询语句。
            params: 参数化查询参数。

        Returns:
            QueryResult 包含列名、行数据和行数。
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            # 提取列名
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
            else:
                columns = []

            rows = cursor.fetchall()
            # 将 Row 对象转为 list
            rows_list = [list(row) for row in rows]

            return QueryResult(
                columns=columns,
                rows=rows_list,
                row_count=len(rows_list),
                success=True,
            )

        except Exception as exc:
            logger.error("DBGateway.query failed: %s", exc)
            return QueryResult(success=False, error=str(exc))

        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @contextmanager
    def transaction(self) -> Iterator[TransactionContext | NullTransaction]:
        """事务上下文管理器。

        Usage:
            with gateway.transaction() as txn:
                txn.execute("INSERT INTO ...")
                txn.execute("UPDATE ...")
                # 成功自动 commit，异常自动 rollback
        """
        conn = None
        try:
            conn = self._get_connection()

            if self._is_kingbasees():
                # KingbaseES autocommit 模式
                txn = NullTransaction(conn, self._db_type)
                try:
                    yield txn
                finally:
                    txn.close()
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:
                # MSSQL / DM8 — 显式事务
                txn = TransactionContext(conn, self._db_type)
                try:
                    yield txn
                    txn.commit()
                except Exception:
                    txn.rollback()
                    raise
                finally:
                    txn.close()
                    try:
                        conn.close()
                    except Exception:
                        pass

        except Exception:
            # 连接获取失败
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            raise

    def get_raw_connection(self):
        """获取底层原始连接（过渡期兼容）。"""
        return self._get_connection()

    def scalar(self, sql: str, params: tuple | None = None) -> Any:
        """执行查询并返回第一行第一列的值。"""
        result = self.query(sql, params)
        if result.success and result.rows:
            return result.rows[0][0]
        return None

    # ------------------------------------------------------------------
    # Dialect-aware execution (Phase 2)
    # ------------------------------------------------------------------

    def compile(
        self,
        sql: str,
        params: tuple | None = None,
        dialect: SqlDialect | None = None,
    ) -> tuple[str, tuple | None]:
        """编译 SQL：dialect-aware rewrite + 参数预处理。

        在 execute/query 之前调用，将标准化 SQL 改写为目标方言。

        Args:
            sql: 原始 SQL
            params: 查询参数
            dialect: SQL 方言实例（默认使用当前 db_type 对应的方言）

        Returns:
            (compiled_sql, params)
        """
        if dialect is None:
            from architecture.core.sql.dialect import get_dialect as get_sql_dialect
            dialect = get_sql_dialect(self._db_type)
        return compile_sql(sql, dialect, params)

    def execute_dialect(
        self,
        sql: str,
        params: tuple | None = None,
        dialect: SqlDialect | None = None,
    ) -> ExecuteResult:
        """Dialect-aware 写操作：compile → execute。

        Args:
            sql: 标准化 SQL
            params: 查询参数
            dialect: SQL 方言（默认自动选择）

        Returns:
            ExecuteResult
        """
        compiled_sql, compiled_params = self.compile(sql, params, dialect)
        return self.execute(compiled_sql, compiled_params)

    def query_dialect(
        self,
        sql: str,
        params: tuple | None = None,
        dialect: SqlDialect | None = None,
    ) -> QueryResult:
        """Dialect-aware 读操作：compile → query。

        Args:
            sql: 标准化 SQL
            params: 查询参数
            dialect: SQL 方言（默认自动选择）

        Returns:
            QueryResult
        """
        compiled_sql, compiled_params = self.compile(sql, params, dialect)
        return self.query(compiled_sql, compiled_params)
