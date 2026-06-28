"""服务层 — 业务操作的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# 执行结果
# =========================================================================


@dataclass(frozen=True)
class DualDbResult:
    """双数据库并行执行的结果。"""

    source_db: str
    target_db: str
    source_result: dict[str, Any]
    target_result: dict[str, Any]
    source_time_ms: float
    target_time_ms: float
    total_time_ms: float

    @property
    def both_succeeded(self) -> bool:
        return self.source_result.get("success") and self.target_result.get("success")

    @property
    def equal(self) -> bool:
        """对比执行结果：成功状态、列名、行数、数据值均一致。"""
        if not self.both_succeeded:
            return False
        src = self.source_result
        tgt = self.target_result
        if src.get("row_count") != tgt.get("row_count"):
            return False
        if src.get("columns") != tgt.get("columns"):
            return False
        if src.get("rows") != tgt.get("rows"):
            return False
        return True


# =========================================================================
# 业务操作结果
# =========================================================================


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
    kernel_analysis: Any | None  # KernelResult (避免循环导入)
    equal: bool
    diff_detail: list[dict[str, Any]] = field(default_factory=list)
    execution_time_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.source_result.get("success") and self.target_result.get("success")


# =========================================================================
# 迁移流水线结果
# =========================================================================


@dataclass(frozen=True)
class MigrationPhaseResult:
    """单个迁移阶段的结果。"""

    name: str
    status: str  # "success" | "partial" | "failed" | "pending"
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
