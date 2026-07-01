"""
Tooling 层 — 实验性工具，不参与业务链路。

包含:
    migration/  — DualDbExecutor, 迁移 schemas
    kernel/     — SQLKernel, 语义上下文, 决策引擎

约束:
    - 只引用 architecture.core/ 和自身
    - 不允许引用 app/service/ 或 app/repository/
    - 业务 Service 不应 import tooling（Phase 7 切断）
"""

from __future__ import annotations

from typing import Any, Callable


def tooling_only(fn: Callable = None, *, reason: str = ""):
    """标记为 tooling-only 函数/端点，不参与业务链路。

    Usage:
        @tooling_only(reason="仅用于迁移验证")
        def compare_sql(...): ...
    """
    def decorator(func: Callable) -> Callable:
        func._tooling_only = True  # type: ignore[attr-defined]
        func._tooling_reason = reason  # type: ignore[attr-defined]
        return func

    if fn is not None:
        return decorator(fn)
    return decorator
