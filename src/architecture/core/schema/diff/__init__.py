"""
core.schema.diff — Schema Graph 差异分析引擎。

对比两个 SchemaGraph（源库 vs 目标库），输出结构化差异报告。
"""

from .engine import (
    DiffResult,
    DiffRisk,
    SchemaDiffEngine,
    SchemaDiffItem,
    SchemaDiffType,
)

__all__ = [
    "SchemaDiffEngine",
    "SchemaDiffItem",
    "SchemaDiffType",
    "DiffResult",
    "DiffRisk",
]
