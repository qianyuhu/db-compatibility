"""
业务数据结构 — Service 层共享 schemas。

从 tooling.migration.schemas 中抽取业务层需要的类型，
使 Service 不再直接依赖 tooling。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BusinessOperationResult:
    """业务操作在双数据库上执行的结果。"""

    operation: str
    source_db: str
    target_db: str
    generated_sql_source: str
    generated_sql_target: str | None
    source_result: dict[str, Any]
    target_result: dict[str, Any]
    kernel_analysis: Any | None = None
    equal: bool = True
    diff_detail: list[dict[str, Any]] = field(default_factory=list)
    execution_time_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.source_result.get("success") and self.target_result.get("success")


@dataclass(frozen=True)
class MigrationPhaseResult:
    """单个迁移阶段的结果。"""

    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class MigrationPipelineResult:
    """完整迁移流水线的结果。"""

    source_db: str
    target_db: str
    phases: list[MigrationPhaseResult] = field(default_factory=list)
    overall_status: str = "pending"
    total_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
