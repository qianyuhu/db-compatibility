"""
_dual_exec.py — 双库执行辅助工具（向后兼容层）。

内部委托给 ExecutionRouter，保持原有 API 不变。
Service 层推荐使用 _executor.ExecutionRouter 替代。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.service._executor import ExecutionRouter, ShadowResult as _ShadowResult


@dataclass
class DualExecResult:
    """双库执行结果。"""

    source_db: str
    target_db: str
    source_result: dict[str, Any] = field(default_factory=dict)
    target_result: dict[str, Any] = field(default_factory=dict)
    rewritten_sql: str | None = None
    equal: bool = True
    diff: list[dict[str, Any]] | None = None
    kernel: Any = None
    execution_time_ms: float = 0.0


# 模块级 router 实例
_router = ExecutionRouter()


def execute_on_both(
    sql: str,
    source_db: str,
    target_db: str,
    params: tuple | None = None,
    skip_validation: bool = False,
    analyze_kernel: bool = False,
) -> DualExecResult:
    """在源库和目标库执行 SQL 并对比结果。

    内部委托给 ExecutionRouter.execute_shadow()。
    保留 skip_validation/analyze_kernel 参数以向后兼容。

    Args:
        sql: SQL 语句
        source_db: 源库类型
        target_db: 目标库类型
        params: 参数化查询参数
        skip_validation: 保留参数（兼容）
        analyze_kernel: 保留参数（兼容）

    Returns:
        DualExecResult
    """
    shadow: _ShadowResult = _router.execute_shadow(
        sql=sql,
        params=params,
        source_db=source_db,
        target_db=target_db,
    )

    return DualExecResult(
        source_db=shadow.source_db,
        target_db=shadow.target_db,
        source_result=shadow.source_result.to_dict(),
        target_result=shadow.target_result.to_dict(),
        rewritten_sql=shadow.target_sql,
        equal=shadow.equal,
        diff=shadow.diff if not shadow.equal else [],
        kernel=None,
        execution_time_ms=shadow.execution_time_ms,
    )
