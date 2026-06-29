"""
DualDbExecutor — 在源库和目标库上并行执行 SQL。

用途:
    Business Service 生成 SQL → DualDbExecutor 并行执行
    → 返回 DualDbResult 供对比

线程安全:
    每个执行器独立创建连接，不共享 session。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any

from app.api.sql_demo.service import execute_sql
from app.core.sql_kernel.kernel import SQLKernel

from .schemas import DualDbResult

logger = logging.getLogger(__name__)

# 单次数据库执行超时（秒）
# MSSQL/DM8: 30秒（本地数据库）
# KingbaseES: 3秒（远程数据库，快速失败）
_EXECUTE_TIMEOUT = 30
_KINGBASEES_TIMEOUT = 3


class DualDbExecutor:
    """在源数据库和目标数据库上并行执行 SQL。"""

    @staticmethod
    def execute_on_both(
        sql: str,
        source_db: str,
        target_db: str,
        *,
        params: tuple | None = None,
        skip_validation: bool = False,
        analyze_kernel: bool = True,
        timeout: int = _EXECUTE_TIMEOUT,
    ) -> tuple[DualDbResult, Any | None]:
        """在源库和目标库上并行执行同一 SQL。

        如果 analyze_kernel=True，先通过 SQLKernel 获取兼容性分析和重写 SQL，
        然后在目标库上执行重写后的 SQL。

        Args:
            sql: SQL 语句（使用 %s 占位符）
            params: 参数化查询参数
            timeout: 单次执行超时秒数

        Returns:
            (DualDbResult, KernelResult | None)
        """
        # --- Kernel 分析（可选）---
        kernel_result = None
        target_sql = sql

        if analyze_kernel:
            try:
                kernel_result = SQLKernel.analyze(
                    sql=sql,
                    source_db=source_db,
                    target_db=target_db,
                    engines=["diagnostics", "rewrite"],
                )
                if kernel_result.rewritten_sql:
                    target_sql = kernel_result.rewritten_sql
            except Exception:
                # Kernel 分析失败不影响执行
                pass

        # --- 并行执行 ---
        start = time.perf_counter()
        source_result: dict[str, Any] = {}
        target_result: dict[str, Any] = {}
        source_time_ms = 0.0
        target_time_ms = 0.0

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_source = pool.submit(
                _timed_execute, source_db, sql, skip_validation, params
            )
            future_target = pool.submit(
                _timed_execute, target_db, target_sql, skip_validation, params
            )

            for future in as_completed([future_source, future_target]):
                # 根据数据库类型选择不同的超时时间
                try:
                    db_type = future_source if future == future_source else future_target
                    # 获取future对应的数据库类型
                    if future == future_source:
                        db_name = source_db
                        current_timeout = timeout
                    else:
                        db_name = target_db
                        # KingbaseES使用更短的超时时间（远程服务器）
                        current_timeout = _KINGBASEES_TIMEOUT if db_name == "kingbasees" else timeout
                    
                    db, result, elapsed, error_msg = future.result(timeout=current_timeout)
                except TimeoutError:
                    # 超时的 future 对应的 DB 标记为超时
                    logger.error(
                        "DB execution timed out after %ss for %s", 
                        current_timeout, db_name
                    )
                    # 找到是哪个 future 超时并标记
                    if future == future_source:
                        source_result = _timeout_result(source_db, current_timeout)
                    else:
                        target_result = _timeout_result(target_db, current_timeout)
                    continue

                if db == source_db:
                    source_result = result
                    source_time_ms = elapsed
                else:
                    target_result = result
                    target_time_ms = elapsed

        total_ms = round((time.perf_counter() - start) * 1000, 1)

        dual_result = DualDbResult(
            source_db=source_db,
            target_db=target_db,
            source_result=source_result,
            target_result=target_result,
            source_time_ms=round(source_time_ms, 1),
            target_time_ms=round(target_time_ms, 1),
            total_time_ms=total_ms,
        )

        return dual_result, kernel_result


def _timed_execute(
    db_type: str,
    sql: str,
    skip_validation: bool,
    params: tuple | None = None,
) -> tuple[str, dict[str, Any], float, str | None]:
    """执行 SQL 并计时。返回 (db_type, result, elapsed_ms, error_msg)。"""
    start = time.perf_counter()
    try:
        result = execute_sql(
            db_type, sql, skip_validation=skip_validation, params=params
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        error_msg = f"{type(exc).__name__}: {exc}"
        return db_type, {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "db_type": db_type,
            "execution_time_ms": round(elapsed, 1),
            "error": error_msg,
            "suggestion": None,
        }, elapsed, error_msg

    elapsed = (time.perf_counter() - start) * 1000
    return db_type, result, elapsed, None


def _timeout_result(db_type: str, timeout: int) -> dict[str, Any]:
    return {
        "success": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "db_type": db_type,
        "execution_time_ms": timeout * 1000,
        "error": f"TimeoutError: 数据库执行超时 ({timeout}s)",
        "suggestion": "检查数据库连接是否正常，或减小查询范围",
    }
