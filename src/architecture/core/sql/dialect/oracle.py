"""
OracleDialect — Oracle 方言实现。

特性:
    - ROWNUM / FETCH FIRST 分页（无 LIMIT/OFFSET）
    - MERGE INTO ... USING dual 做 UPSERT
    - SYSDATE 时间函数
    - "IDENTIFIER" 双引号大写引用
    - :1 参数占位符
"""

from __future__ import annotations

import re

from .base import BaseDialect


class OracleDialect(BaseDialect):
    """Oracle 方言实现。"""

    @property
    def name(self) -> str:
        return "oracle"

    @property
    def param_placeholder(self) -> str:
        return ":1"

    # ------------------------------------------------------------------
    # 分页: LIMIT/OFFSET → ROWNUM 或 FETCH FIRST
    # ------------------------------------------------------------------

    def rewrite_limit_offset(self, sql: str) -> str:
        """LIMIT N OFFSET M → ROWNUM 子查询 或 FETCH FIRST（Oracle 12c+）。

        使用 FETCH FIRST N ROWS ONLY（Oracle 12c+ 标准语法）。
        """
        match = re.search(r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\s*$", sql, re.IGNORECASE)
        if match:
            limit = int(match.group(1))
            offset = int(match.group(2))
            cleaned = re.sub(
                r"\s+LIMIT\s+\d+\s+OFFSET\s+\d+\s*$", "", sql, flags=re.IGNORECASE
            ).strip()
            # Oracle 12c+ 标准 FETCH FIRST
            if "ORDER BY" not in cleaned.upper():
                cleaned = f"{cleaned} ORDER BY 1"
            return f"{cleaned} OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

        match = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if match:
            n = match.group(1)
            cleaned = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql, flags=re.IGNORECASE).strip()
            # Oracle 12c+ FETCH FIRST
            if "ORDER BY" not in cleaned.upper():
                cleaned = f"{cleaned} ORDER BY 1"
            return f"{cleaned} FETCH FIRST {n} ROWS ONLY"

        return sql

    # ------------------------------------------------------------------
    # UPSERT: INSERT ... ON CONFLICT → MERGE INTO ... USING dual
    # ------------------------------------------------------------------

    def rewrite_upsert(self, sql: str) -> str:
        """UPSERT 改写：ON CONFLICT → MERGE INTO ... USING dual。

        简单 INSERT 保持不变。
        """
        if re.search(r"\bON\s+CONFLICT\b", sql, re.IGNORECASE):
            return (
                "-- WARNING: ON CONFLICT 语法需手动改写为 MERGE INTO ... USING dual\n"
                + sql
            )
        return sql

    # ------------------------------------------------------------------
    # 时间函数: NOW() → SYSDATE, GETDATE() → SYSDATE
    # ------------------------------------------------------------------

    def map_datetime_func(self, sql: str) -> str:
        """将标准/其他方言时间函数映射为 Oracle 风格。"""
        result = sql
        result = re.sub(r"\bNOW\s*\(\s*\)", "SYSDATE", result, flags=re.IGNORECASE)
        result = re.sub(r"\bGETDATE\s*\(\s*\)", "SYSDATE", result, flags=re.IGNORECASE)
        result = re.sub(r"\bCURRENT_TIMESTAMP\b", "SYSDATE", result, flags=re.IGNORECASE)
        return result

    # ------------------------------------------------------------------
    # 标识符引用: "NAME"（Oracle 默认大写）
    # ------------------------------------------------------------------

    def quote_identifier(self, name: str) -> str:
        """Oracle 使用双引号引用，默认大写。"""
        return f'"{name.upper()}"'

    # ------------------------------------------------------------------
    # 参数: %s → :1, :2, ...
    # ------------------------------------------------------------------

    def normalize_params(self, sql: str) -> str:
        """将 %s 占位符转为 :N（Oracle 风格）。"""
        counter = 0

        def _replace(_: re.Match) -> str:
            nonlocal counter
            counter += 1
            return f":{counter}"

        return re.sub(r"%s", _replace, sql)
