"""
MSSQLDialect — Microsoft SQL Server 方言实现。

特性:
    - SELECT TOP N 分页（无 LIMIT/OFFSET）
    - MERGE INTO 做 UPSERT
    - GETDATE() 时间函数
    - [identifier] 方括号引用
    - ? 参数占位符（pyodbc）
"""

from __future__ import annotations

import re

from .base import BaseDialect


class MSSQLDialect(BaseDialect):
    """MSSQL 方言实现。"""

    @property
    def name(self) -> str:
        return "mssql"

    @property
    def param_placeholder(self) -> str:
        return "?"

    # ------------------------------------------------------------------
    # 分页: LIMIT/OFFSET → SELECT TOP N
    # ------------------------------------------------------------------

    def rewrite_limit_offset(self, sql: str) -> str:
        """LIMIT N OFFSET M → SELECT TOP N ... (简单场景)

        对于带 OFFSET 的场景需要 ROW_NUMBER 子查询（Phase 2 简化版暂不支持）。
        """
        # LIMIT + OFFSET → TOP（取 LIMIT+OFFSET 行，丢弃前 OFFSET 行 — 简化版暂不支持）
        # 仅支持 LIMIT（无 OFFSET）的常见场景
        match = re.search(r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\s*$", sql, re.IGNORECASE)
        if match:
            limit = int(match.group(1))
            offset = int(match.group(2))
            cleaned = re.sub(
                r"\s+LIMIT\s+\d+\s+OFFSET\s+\d+\s*$", "", sql, flags=re.IGNORECASE
            ).strip()
            # 使用 OFFSET...FETCH (SQL Server 2012+)
            if "ORDER BY" in cleaned.upper():
                return f"{cleaned} OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            # 无 ORDER BY 时添加 ORDER BY (SELECT NULL) 占位
            return (
                f"{cleaned} ORDER BY (SELECT NULL) "
                f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            )

        # 仅 LIMIT（无 OFFSET）→ SELECT TOP N
        match = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if match:
            n = match.group(1)
            cleaned = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql, flags=re.IGNORECASE).strip()
            # 已有 TOP 则不再添加
            if re.search(r"\bSELECT\s+TOP\s+", cleaned, re.IGNORECASE):
                return cleaned
            return re.sub(r"\bSELECT\b", f"SELECT TOP {n}", cleaned, count=1, flags=re.IGNORECASE)

        return sql

    # ------------------------------------------------------------------
    # UPSERT: INSERT ... ON CONFLICT → MERGE INTO
    # ------------------------------------------------------------------

    def rewrite_upsert(self, sql: str) -> str:
        """INSERT ... ON CONFLICT → MERGE INTO（MSSQL 风格）。

        目前仅标记为需要手动处理（复杂 UPSERT 无法自动转换）。
        简单 INSERT 保持不变。
        """
        if re.search(r"\bON\s+CONFLICT\b", sql, re.IGNORECASE):
            return (
                "-- WARNING: ON CONFLICT 语法需手动改写为 MERGE INTO\n"
                + sql
            )
        return sql

    # ------------------------------------------------------------------
    # 时间函数: NOW() → GETDATE(), SYSDATE → GETDATE()
    # ------------------------------------------------------------------

    def map_datetime_func(self, sql: str) -> str:
        """将标准/其他方言时间函数映射为 MSSQL。"""
        result = sql
        result = re.sub(r"\bNOW\s*\(\s*\)", "GETDATE()", result, flags=re.IGNORECASE)
        result = re.sub(r"\bSYSDATE\b", "GETDATE()", result, flags=re.IGNORECASE)
        # CURRENT_TIMESTAMP 在 MSSQL 中也支持，保持不变
        return result

    # ------------------------------------------------------------------
    # 标识符引用: [name]
    # ------------------------------------------------------------------

    def quote_identifier(self, name: str) -> str:
        """MSSQL 使用方括号引用。"""
        return f"[{name}]"

    # MSSQL 原生就是方括号，不需要转换
    def normalize_identifiers(self, sql: str) -> str:
        return sql

    # ------------------------------------------------------------------
    # 参数: %s → ?
    # ------------------------------------------------------------------

    def normalize_params(self, sql: str) -> str:
        """将 %s 占位符转为 ?（pyodbc 风格）。"""
        return sql.replace("%s", "?")
