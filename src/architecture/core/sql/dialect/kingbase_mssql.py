"""
KingbaseMSSQLDialect — KingbaseES MSSQL Compatible 模式方言实现。

特性:
    - LIMIT/OFFSET 标准语法（PG 风格）
    - INSERT ... ON CONFLICT 做 UPSERT
    - NOW() 时间函数
    - "identifier" 双引号引用
    - %s 参数占位符（psycopg2）
"""

from __future__ import annotations

import re

from .base import BaseDialect


class KingbaseMSSQLDialect(BaseDialect):
    """KingbaseES MSSQL Compatible 模式方言实现。"""

    @property
    def name(self) -> str:
        return "kingbase_mssql"

    @property
    def param_placeholder(self) -> str:
        return "%s"

    # ------------------------------------------------------------------
    # 分页: 支持 LIMIT/OFFSET；TOP N → LIMIT N
    # ------------------------------------------------------------------

    def rewrite_limit_offset(self, sql: str) -> str:
        """SELECT TOP N → SELECT ... LIMIT N。

        LIMIT/OFFSET 在 KingbaseES 中原生支持，保持不变。
        """
        # TOP N → LIMIT N（如果 SQL 带 TOP）
        match = re.search(r"\bSELECT\s+TOP\s+(\d+)\s+", sql, re.IGNORECASE)
        if match:
            n = match.group(1)
            cleaned = re.sub(
                r"\bSELECT\s+TOP\s+\d+\s+", "SELECT ", sql, count=1, flags=re.IGNORECASE
            )
            # 已有 LIMIT 则不追加
            if re.search(r"\bLIMIT\s+\d+", cleaned, re.IGNORECASE):
                return cleaned
            return f"{cleaned}\nLIMIT {n}"

        # OFFSET...FETCH → LIMIT/OFFSET（PG 风格）
        match = re.search(
            r"\bOFFSET\s+(\d+)\s+ROWS?\s+FETCH\s+NEXT\s+(\d+)\s+ROWS?\s+ONLY",
            sql,
            re.IGNORECASE,
        )
        if match:
            offset = match.group(1)
            limit = match.group(2)
            cleaned = re.sub(
                r"\s*OFFSET\s+\d+\s+ROWS?\s+FETCH\s+NEXT\s+\d+\s+ROWS?\s+ONLY",
                "",
                sql,
                flags=re.IGNORECASE,
            ).strip()
            return f"{cleaned}\nLIMIT {limit} OFFSET {offset}"

        # LIMIT/OFFSET 已存在 → 保持不变
        return sql

    # ------------------------------------------------------------------
    # UPSERT: INSERT ... ON CONFLICT
    # ------------------------------------------------------------------

    def rewrite_upsert(self, sql: str) -> str:
        """UPSERT 改写：MERGE INTO → INSERT ... ON CONFLICT DO UPDATE。

        简单 INSERT 保持不变。MERGE 语法复杂，仅做基本标记。
        """
        if re.search(r"\bMERGE\s+INTO\b", sql, re.IGNORECASE):
            return (
                "-- WARNING: MERGE INTO 语法需手动改写为 INSERT ... ON CONFLICT\n"
                + sql
            )
        return sql

    # ------------------------------------------------------------------
    # 时间函数: GETDATE() → NOW(), SYSDATE → NOW()
    # ------------------------------------------------------------------

    def map_datetime_func(self, sql: str) -> str:
        """将其他方言时间函数映射为 KingbaseES 风格。"""
        result = sql
        result = re.sub(r"\bGETDATE\s*\(\s*\)", "NOW()", result, flags=re.IGNORECASE)
        result = re.sub(r"\bSYSDATE\b", "NOW()", result, flags=re.IGNORECASE)
        return result

    # ------------------------------------------------------------------
    # 标识符引用: "name"
    # ------------------------------------------------------------------

    def quote_identifier(self, name: str) -> str:
        """PG/KB 使用双引号引用。"""
        return f'"{name}"'

    # ------------------------------------------------------------------
    # 参数: %s 保持不变（psycopg2 原生）
    # ------------------------------------------------------------------

    def normalize_params(self, sql: str) -> str:
        """%s 在 psycopg2 中是原生占位符，无需转换。"""
        return sql
