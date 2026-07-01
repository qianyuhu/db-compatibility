"""
ExecutionRouter — 统一 SQL 执行入口（替代 SQLKernel 直连调用）。

所有 service 层 SQL 执行必须通过 ExecutionRouter，不允许直接调用 gateway。

支持模式:
    - single_db:        单库执行（dialect-aware）
    - dual_db_shadow:   双库影子模式（源库原 SQL + 目标库改写 SQL + 对比）
    - migration_verify: 迁移验证模式（执行 + 结构对比）

Usage:
    from app.service._executor import ExecutionRouter

    router = ExecutionRouter()
    result = router.execute_single(sql, params, db_type="mssql")
    shadow = router.execute_shadow(sql, params, source_db="mssql", target_db="kingbasees")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from architecture.core.db.gateway import DBGateway, ExecuteResult, QueryResult
from architecture.core.sql.dialect import get_dialect as get_sql_dialect
from architecture.core.sql.rewrite.pipeline import rewrite as pipeline_rewrite


# =========================================================================
# 执行模式
# =========================================================================


class ExecMode(str, Enum):
    """执行模式枚举。"""

    SINGLE_DB = "single_db"
    DUAL_DB_SHADOW = "dual_db_shadow"
    MIGRATION_VERIFY = "migration_verify"


# =========================================================================
# 结果类型
# =========================================================================


@dataclass
class ExecResult:
    """单库执行结果。"""

    mode: ExecMode = ExecMode.SINGLE_DB
    db_type: str = ""
    sql_executed: str = ""
    success: bool = True
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    rows_affected: int = 0
    error: str | None = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "db_type": self.db_type,
            "sql_executed": self.sql_executed,
            "success": self.success,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "rows_affected": self.rows_affected,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class ShadowResult:
    """双库影子执行结果。"""

    mode: ExecMode = ExecMode.DUAL_DB_SHADOW
    source_db: str = ""
    target_db: str = ""
    source_sql: str = ""
    target_sql: str = ""
    source_result: ExecResult = field(default_factory=ExecResult)
    target_result: ExecResult = field(default_factory=ExecResult)
    equal: bool = True
    diff: list[dict[str, Any]] = field(default_factory=list)
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "source_db": self.source_db,
            "target_db": self.target_db,
            "source_sql": self.source_sql,
            "target_sql": self.target_sql,
            "source_result": self.source_result.to_dict(),
            "target_result": self.target_result.to_dict(),
            "equal": self.equal,
            "diff": self.diff,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class VerifyResult:
    """迁移验证结果。"""

    mode: ExecMode = ExecMode.MIGRATION_VERIFY
    source_db: str = ""
    target_db: str = ""
    source_sql: str = ""
    target_sql: str = ""
    source_result: ExecResult = field(default_factory=ExecResult)
    target_result: ExecResult = field(default_factory=ExecResult)
    structure_match: bool = True
    data_match: bool = True
    issues: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "source_db": self.source_db,
            "target_db": self.target_db,
            "source_sql": self.source_sql,
            "target_sql": self.target_sql,
            "source_result": self.source_result.to_dict(),
            "target_result": self.target_result.to_dict(),
            "structure_match": self.structure_match,
            "data_match": self.data_match,
            "issues": self.issues,
            "execution_time_ms": self.execution_time_ms,
        }


# =========================================================================
# Execution Router
# =========================================================================


class ExecutionRouter:
    """统一 SQL 执行入口。

    Service 层必须通过 ExecutionRouter 执行 SQL，不允许直接调用 DBGateway。
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 单库执行
    # ------------------------------------------------------------------

    def execute_single(
        self,
        sql: str,
        params: tuple | None = None,
        db_type: str = "mssql",
        *,
        use_dialect: bool = True,
    ) -> ExecResult:
        """单库执行 SQL（dialect-aware）。

        Args:
            sql: SQL 语句
            params: 参数
            db_type: 目标数据库类型
            use_dialect: 是否启用 dialect 改写（默认 True）

        Returns:
            ExecResult
        """
        start = time.perf_counter()
        gw = DBGateway(db_type)

        if use_dialect:
            result = self._run_dialect(gw, sql, params, db_type)
        else:
            result = self._run_raw(gw, sql, params, db_type)

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        result.execution_time_ms = elapsed
        result.mode = ExecMode.SINGLE_DB
        return result

    # ------------------------------------------------------------------
    # 双库影子模式
    # ------------------------------------------------------------------

    def execute_shadow(
        self,
        sql: str,
        params: tuple | None = None,
        source_db: str = "mssql",
        target_db: str = "kingbasees",
    ) -> ShadowResult:
        """双库影子执行：源库原 SQL + 目标库改写 SQL + 对比。

        Args:
            sql: 标准化 SQL（面向源库方言）
            params: 参数
            source_db: 源库类型
            target_db: 目标库类型

        Returns:
            ShadowResult
        """
        start = time.perf_counter()

        # 源库执行原 SQL
        source_gw = DBGateway(source_db)
        source_result = self._run_raw(source_gw, sql, params, source_db)

        # 目标库执行改写后的 SQL
        target_gw = DBGateway(target_db)
        target_sql = pipeline_rewrite(sql, get_sql_dialect(target_db))
        target_result = self._run_raw(target_gw, target_sql, params, target_db)

        # 对比结果
        equal, diff = self._compare(source_result, target_result)

        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return ShadowResult(
            mode=ExecMode.DUAL_DB_SHADOW,
            source_db=source_db,
            target_db=target_db,
            source_sql=sql,
            target_sql=target_sql,
            source_result=source_result,
            target_result=target_result,
            equal=equal,
            diff=diff,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # 迁移验证模式
    # ------------------------------------------------------------------

    def execute_verify(
        self,
        sql: str,
        params: tuple | None = None,
        source_db: str = "mssql",
        target_db: str = "kingbasees",
    ) -> VerifyResult:
        """迁移验证：执行 + 结构/数据对比。

        Args:
            sql: 标准化 SQL
            params: 参数
            source_db: 源库类型
            target_db: 目标库类型

        Returns:
            VerifyResult
        """
        start = time.perf_counter()

        shadow = self.execute_shadow(sql, params, source_db, target_db)

        # 结构对比（列名匹配）
        structure_match = shadow.source_result.columns == shadow.target_result.columns
        issues: list[str] = []
        if not structure_match:
            issues.append(
                f"Column mismatch: source={shadow.source_result.columns}, "
                f"target={shadow.target_result.columns}"
            )

        # 数据对比（行数 + 内容）
        data_match = shadow.equal
        if shadow.source_result.row_count != shadow.target_result.row_count:
            issues.append(
                f"Row count mismatch: source={shadow.source_result.row_count}, "
                f"target={shadow.target_result.row_count}"
            )

        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return VerifyResult(
            mode=ExecMode.MIGRATION_VERIFY,
            source_db=source_db,
            target_db=target_db,
            source_sql=shadow.source_sql,
            target_sql=shadow.target_sql,
            source_result=shadow.source_result,
            target_result=shadow.target_result,
            structure_match=structure_match,
            data_match=data_match,
            issues=issues,
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _run_dialect(
        gw: DBGateway,
        sql: str,
        params: tuple | None,
        db_type: str,
    ) -> ExecResult:
        """使用 dialect-aware 执行。"""
        sql_upper = sql.strip().upper()
        is_query = sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")

        try:
            if is_query:
                qr: QueryResult = gw.query_dialect(sql, params)
                return ExecResult(
                    db_type=db_type,
                    sql_executed=sql,
                    success=qr.success,
                    columns=qr.columns,
                    rows=[list(r) for r in qr.rows],
                    row_count=qr.row_count,
                    error=qr.error,
                )
            else:
                er: ExecuteResult = gw.execute_dialect(sql, params)
                return ExecResult(
                    db_type=db_type,
                    sql_executed=sql,
                    success=er.success,
                    rows_affected=er.rows_affected,
                    error=er.error,
                )
        except Exception as exc:
            return ExecResult(
                db_type=db_type,
                sql_executed=sql,
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _run_raw(
        gw: DBGateway,
        sql: str,
        params: tuple | None,
        db_type: str,
    ) -> ExecResult:
        """不使用 dialect 改写的原始执行。"""
        sql_upper = sql.strip().upper()
        is_query = sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")

        try:
            if is_query:
                qr: QueryResult = gw.query(sql, params)
                return ExecResult(
                    db_type=db_type,
                    sql_executed=sql,
                    success=qr.success,
                    columns=qr.columns,
                    rows=[list(r) for r in qr.rows],
                    row_count=qr.row_count,
                    error=qr.error,
                )
            else:
                er: ExecuteResult = gw.execute(sql, params)
                return ExecResult(
                    db_type=db_type,
                    sql_executed=sql,
                    success=er.success,
                    rows_affected=er.rows_affected,
                    error=er.error,
                )
        except Exception as exc:
            return ExecResult(
                db_type=db_type,
                sql_executed=sql,
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _compare(
        source: ExecResult,
        target: ExecResult,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """对比两个执行结果。"""
        diff: list[dict[str, Any]] = []

        if not source.success or not target.success:
            if source.success != target.success:
                diff.append({
                    "type": "execution_failure",
                    "detail": f"source_ok={source.success}, target_ok={target.success}",
                })
            return False, diff

        if source.columns != target.columns:
            diff.append({
                "type": "column_mismatch",
                "source_columns": source.columns,
                "target_columns": target.columns,
            })

        if source.row_count != target.row_count:
            diff.append({
                "type": "row_count_mismatch",
                "source_count": source.row_count,
                "target_count": target.row_count,
            })

        if source.rows != target.rows:
            diff.append({
                "type": "data_mismatch",
                "sample_source": source.rows[:5],
                "sample_target": target.rows[:5],
            })

        equal = len(diff) == 0
        return equal, diff


# =========================================================================
# 模块级便捷函数（向后兼容 _dual_exec）
# =========================================================================

_router = ExecutionRouter()


def execute_single(
    sql: str,
    params: tuple | None = None,
    db_type: str = "mssql",
    *,
    use_dialect: bool = True,
) -> ExecResult:
    """模块级便捷函数：单库执行。"""
    return _router.execute_single(sql, params, db_type, use_dialect=use_dialect)


def execute_shadow(
    sql: str,
    params: tuple | None = None,
    source_db: str = "mssql",
    target_db: str = "kingbasees",
) -> ShadowResult:
    """模块级便捷函数：双库影子执行。"""
    return _router.execute_shadow(sql, params, source_db, target_db)


def execute_verify(
    sql: str,
    params: tuple | None = None,
    source_db: str = "mssql",
    target_db: str = "kingbasees",
) -> VerifyResult:
    """模块级便捷函数：迁移验证。"""
    return _router.execute_verify(sql, params, source_db, target_db)
