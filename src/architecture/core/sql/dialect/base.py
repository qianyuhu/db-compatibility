"""
BaseDialect — SQL 方言抽象基类。

定义所有数据库方言必须实现的 SQL 改写能力:
    - limit/offset rewrite
    - upsert rewrite
    - datetime function mapping
    - identifier quoting
    - parameter normalization

Usage:
    dialect = MSSQLDialect()
    sql = dialect.rewrite_limit_offset("SELECT * FROM t LIMIT 10")
    # → "SELECT TOP 10 * FROM t"
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseDialect(ABC):
    """SQL 方言抽象基类。

    每个具体方言实现一组改写方法，供 Rewrite Pipeline 和 DBGateway 调用。
    所有方法必须幂等：对已改写的 SQL 再次调用不应产生副作用。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """方言名称 (mssql / kingbase_mssql / oracle)。"""
        ...

    @property
    @abstractmethod
    def param_placeholder(self) -> str:
        """参数占位符 (%s / :1 / ?)。"""
        ...

    # ------------------------------------------------------------------
    # 分页改写
    # ------------------------------------------------------------------

    @abstractmethod
    def rewrite_limit_offset(self, sql: str) -> str:
        """将标准 LIMIT/OFFSET 语法改写为本地方言。

        输入: "SELECT * FROM t LIMIT 10 OFFSET 5"
        输出: 方言等价形式（如 MSSQL 用 SELECT TOP + ROW_NUMBER）
        """
        ...

    # ------------------------------------------------------------------
    # UPSERT 改写
    # ------------------------------------------------------------------

    @abstractmethod
    def rewrite_upsert(self, sql: str) -> str:
        """将通用 UPSERT 模式改写为方言语法。

        MSSQL:   MERGE INTO ... WHEN MATCHED/NOT MATCHED
        Oracle:  MERGE INTO ... USING dual
        Kingbase: INSERT ... ON CONFLICT DO UPDATE
        """
        ...

    # ------------------------------------------------------------------
    # 时间函数映射
    # ------------------------------------------------------------------

    @abstractmethod
    def map_datetime_func(self, sql: str) -> str:
        """将标准时间函数映射为方言等价函数。

        CURRENT_TIMESTAMP → GETDATE() / NOW() / SYSDATE
        """
        ...

    # ------------------------------------------------------------------
    # 标识符引用
    # ------------------------------------------------------------------

    @abstractmethod
    def quote_identifier(self, name: str) -> str:
        """对标识符加引用。

        MSSQL:   [name]
        PG/KB:   "name"
        Oracle:  "NAME" (大写)
        """
        ...

    def normalize_identifiers(self, sql: str) -> str:
        """将 SQL 中的方括号标识符 [x] 转换为本地引用风格。

        默认实现：逐对替换 [ident] → quote_identifier(ident)。
        子类可覆盖以提供更高效实现。
        """
        import re
        def _replace(m: re.Match) -> str:
            return self.quote_identifier(m.group(1))
        return re.sub(r"\[([^\]]+)\]", _replace, sql)

    # ------------------------------------------------------------------
    # 参数归一化
    # ------------------------------------------------------------------

    @abstractmethod
    def normalize_params(self, sql: str) -> str:
        """将参数占位符归一化为方言风格。

        输入统一使用 %s，输出为方言占位符。
        """
        ...
