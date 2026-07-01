"""
Schema Diff Engine — 对比两个 SchemaGraph 的结构差异。

核心能力:
    对比 source_graph（源库）和 target_graph（目标库），输出:
    - TABLE_MISSING        — 目标库缺少整张表
    - COLUMN_TYPE_MISMATCH — 同名列类型不一致
    - COLUMN_MISSING       — 目标表缺少某列
    - CONSTRAINT_LOSS      — 约束丢失（PK/FK/UNIQUE）
    - INDEX_MISSING        — 索引丢失
    - DEPENDENCY_BROKEN    — 依赖关系断裂

每条差异携带 impact_chain（从目标图的 SchemaGraph 计算受影响节点）。

Design:
    - 纯函数式: diff(source, target) → DiffResult
    - 不依赖数据库连接（纯图对比）
    - impact_chain 通过目标图计算，用于评估修复优先级

Usage:
    from architecture.core.schema.diff.engine import SchemaDiffEngine

    source = TableBuilder.from_inspector(source_inspector)
    target = TableBuilder.from_inspector(target_inspector)
    result = SchemaDiffEngine.diff(source, target)

    for item in result.items:
        print(f"{item.diff_type}: {item.node_id} ({item.risk})")
        if item.impact_chain:
            print(f"  → impacts: {item.impact_chain}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from architecture.core.schema.graph import SchemaGraph
from architecture.core.schema.nodes import (
    ColumnNode,
    ConstraintNode,
    IndexNode,
    SchemaNodeType,
    TableNode,
)

logger = logging.getLogger(__name__)


# =========================================================================
# Diff types
# =========================================================================


class SchemaDiffType(Enum):
    """Schema 差异类型。"""
    TABLE_MISSING = auto()
    COLUMN_MISSING = auto()
    COLUMN_TYPE_MISMATCH = auto()
    CONSTRAINT_LOSS = auto()
    INDEX_MISSING = auto()
    DEPENDENCY_BROKEN = auto()
    TABLE_EXTRA = auto()       # 目标库有额外表（非错误，但需关注）
    COLUMN_EXTRA = auto()      # 目标表有额外列


class DiffRisk(Enum):
    """差异风险等级。"""
    CRITICAL = auto()   # 迁移必定失败
    HIGH = auto()       # 数据可能丢失或截断
    MEDIUM = auto()     # 功能受影响但可规避
    LOW = auto()        # 信息性差异


# =========================================================================
# Diff item
# =========================================================================


@dataclass(frozen=True)
class SchemaDiffItem:
    """单条 Schema 差异。

    Attributes:
        diff_type: 差异类型。
        node_id: 涉及的节点 id（源图中的 id）。
        source_value: 源图中的值。
        target_value: 目标图中的值（None 表示缺失）。
        risk: 风险等级。
        impact_chain: 受此差异影响的下游节点 id 元组。
        detail: 补充说明。
    """
    diff_type: SchemaDiffType
    node_id: str
    source_value: str
    target_value: str | None = None
    risk: DiffRisk = DiffRisk.MEDIUM
    impact_chain: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 友好的字典。"""
        return {
            "type": self.diff_type.name,
            "node": self.node_id,
            "source": self.source_value,
            "target": self.target_value,
            "risk": self.risk.name,
            "impact_chain": list(self.impact_chain),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DiffResult:
    """Schema Diff 总结果。

    Attributes:
        items: 差异列表。
        source_node_count: 源图节点总数。
        target_node_count: 目标图节点总数。
    """
    items: tuple[SchemaDiffItem, ...]
    source_node_count: int = 0
    target_node_count: int = 0

    @property
    def total_diffs(self) -> int:
        return len(self.items)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.items if i.risk == DiffRisk.CRITICAL)

    @property
    def is_safe_to_migrate(self) -> bool:
        """无 CRITICAL 差异视为可安全迁移。"""
        return self.critical_count == 0

    @property
    def risk_summary(self) -> dict[str, int]:
        """按风险等级分类统计。"""
        summary: dict[str, int] = {}
        for item in self.items:
            key = item.risk.name
            summary[key] = summary.get(key, 0) + 1
        return summary

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 友好的字典。"""
        return {
            "total_diffs": self.total_diffs,
            "critical_count": self.critical_count,
            "is_safe_to_migrate": self.is_safe_to_migrate,
            "risk_summary": self.risk_summary,
            "source_node_count": self.source_node_count,
            "target_node_count": self.target_node_count,
            "items": [item.to_dict() for item in self.items],
        }


# =========================================================================
# Diff Engine
# =========================================================================


class SchemaDiffEngine:
    """Schema Graph 结构化对比引擎。"""

    @staticmethod
    def diff(
        source: SchemaGraph,
        target: SchemaGraph,
    ) -> DiffResult:
        """对比 source 和 target 两个 SchemaGraph。

        Args:
            source: 源库 SchemaGraph（基准）。
            target: 目标库 SchemaGraph（待验证）。

        Returns:
            DiffResult 包含所有差异项。
        """
        items: list[SchemaDiffItem] = []

        # 1. Table-level diff
        _diff_tables(source, target, items)

        # 2. Column-level diff (对共有的表)
        _diff_columns(source, target, items)

        # 3. Constraint diff
        _diff_constraints(source, target, items)

        # 4. Index diff
        _diff_indexes(source, target, items)

        # 5. Dependency diff (边级别)
        _diff_dependencies(source, target, items)

        # 为每条差异计算 impact_chain（基于 target 图）
        _enrich_impact_chains(target, items)

        logger.info(
            "SchemaDiffEngine.diff: %d differences found "
            "(%d critical, %d high)",
            len(items),
            sum(1 for i in items if i.risk == DiffRisk.CRITICAL),
            sum(1 for i in items if i.risk == DiffRisk.HIGH),
        )

        return DiffResult(
            items=tuple(items),
            source_node_count=source.node_count,
            target_node_count=target.node_count,
        )


# =========================================================================
# Internal diff functions
# =========================================================================


def _diff_tables(
    source: SchemaGraph,
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """对比表级别差异。"""
    source_tables = {
        n.id: n for n in source.nodes_by_type(SchemaNodeType.TABLE)
    }
    target_tables = {
        n.id: n for n in target.nodes_by_type(SchemaNodeType.TABLE)
    }

    # 源有目标无 → TABLE_MISSING
    for tbl_id in source_tables:
        if tbl_id not in target_tables:
            items.append(SchemaDiffItem(
                diff_type=SchemaDiffType.TABLE_MISSING,
                node_id=tbl_id,
                source_value=f"Table({source_tables[tbl_id].name})",
                target_value=None,
                risk=DiffRisk.CRITICAL,
                detail=f"Table {source_tables[tbl_id].name} missing in target",
            ))

    # 目标有源无 → TABLE_EXTRA
    for tbl_id in target_tables:
        if tbl_id not in source_tables:
            items.append(SchemaDiffItem(
                diff_type=SchemaDiffType.TABLE_EXTRA,
                node_id=tbl_id,
                source_value=None,
                target_value=f"Table({target_tables[tbl_id].name})",
                risk=DiffRisk.LOW,
                detail=f"Extra table {target_tables[tbl_id].name} in target",
            ))


def _diff_columns(
    source: SchemaGraph,
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """对比列级别差异（仅对共有的表）。"""
    source_cols = {
        n.id: n for n in source.nodes_by_type(SchemaNodeType.COLUMN)
    }
    target_cols = {
        n.id: n for n in target.nodes_by_type(SchemaNodeType.COLUMN)
    }

    for col_id, src_col in source_cols.items():
        if col_id not in target_cols:
            # 检查父表是否存在于目标
            parent = src_col.parent_table
            if target.has_node(parent):
                items.append(SchemaDiffItem(
                    diff_type=SchemaDiffType.COLUMN_MISSING,
                    node_id=col_id,
                    source_value=f"{src_col.data_type} (nullable={src_col.nullable})",
                    target_value=None,
                    risk=DiffRisk.HIGH,
                    detail=f"Column {src_col.name} missing in target table",
                ))
        else:
            tgt_col = target_cols[col_id]
            # 类型对比
            src_type = _normalize_type(src_col.data_type)
            tgt_type = _normalize_type(tgt_col.data_type)
            if src_type != tgt_type:
                items.append(SchemaDiffItem(
                    diff_type=SchemaDiffType.COLUMN_TYPE_MISMATCH,
                    node_id=col_id,
                    source_value=src_col.data_type,
                    target_value=tgt_col.data_type,
                    risk=DiffRisk.HIGH,
                    detail=f"Type mismatch: {src_col.data_type} → {tgt_col.data_type}",
                ))


def _diff_constraints(
    source: SchemaGraph,
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """对比约束差异。"""
    source_constraints = {
        n.id: n for n in source.nodes_by_type(SchemaNodeType.CONSTRAINT)
    }
    target_constraints = {
        n.id: n for n in target.nodes_by_type(SchemaNodeType.CONSTRAINT)
    }

    for c_id, src_c in source_constraints.items():
        if c_id not in target_constraints:
            # 检查父表是否存在于目标
            parent = src_c.parent_table
            if target.has_node(parent):
                risk = DiffRisk.HIGH if src_c.constraint_type.name in ("PRIMARY_KEY", "FOREIGN_KEY") else DiffRisk.MEDIUM
                items.append(SchemaDiffItem(
                    diff_type=SchemaDiffType.CONSTRAINT_LOSS,
                    node_id=c_id,
                    source_value=f"{src_c.constraint_type.name}({','.join(src_c.columns)})",
                    target_value=None,
                    risk=risk,
                    detail=f"{src_c.constraint_type.name} constraint lost on {src_c.parent_table}",
                ))


def _diff_indexes(
    source: SchemaGraph,
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """对比索引差异。"""
    source_idxs = {
        n.id: n for n in source.nodes_by_type(SchemaNodeType.INDEX)
    }
    target_idxs = {
        n.id: n for n in target.nodes_by_type(SchemaNodeType.INDEX)
    }

    for idx_id, src_idx in source_idxs.items():
        if idx_id not in target_idxs:
            parent = src_idx.parent_table
            if target.has_node(parent):
                items.append(SchemaDiffItem(
                    diff_type=SchemaDiffType.INDEX_MISSING,
                    node_id=idx_id,
                    source_value=f"Index({','.join(src_idx.columns)}, unique={src_idx.is_unique})",
                    target_value=None,
                    risk=DiffRisk.MEDIUM,
                    detail=f"Index missing on {src_idx.parent_table}",
                ))


def _diff_dependencies(
    source: SchemaGraph,
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """对比依赖边差异。"""
    source_dep_edges = {
        (e.source_id, e.target_id, e.edge_type.name)
        for e in source.edges
        if e.is_dependency
    }
    target_dep_edges = {
        (e.source_id, e.target_id, e.edge_type.name)
        for e in target.edges
        if e.is_dependency
    }

    for src_id, tgt_id, etype in source_dep_edges:
        if (src_id, tgt_id, etype) not in target_dep_edges:
            # 只有当 source 和 target 节点都在目标图中时才算 broken
            if target.has_node(src_id) and target.has_node(tgt_id):
                items.append(SchemaDiffItem(
                    diff_type=SchemaDiffType.DEPENDENCY_BROKEN,
                    node_id=f"{src_id} → {tgt_id}",
                    source_value=f"{etype} edge",
                    target_value=None,
                    risk=DiffRisk.HIGH,
                    detail=f"Dependency {etype} from {src_id} to {tgt_id} broken",
                ))


def _enrich_impact_chains(
    target: SchemaGraph,
    items: list[SchemaDiffItem],
) -> None:
    """为每条差异计算 impact_chain。"""
    # 提取所有 TableNode id 用于快速定位
    table_ids = {
        n.id for n in target.nodes_by_type(SchemaNodeType.TABLE)
    }

    enriched: list[SchemaDiffItem] = []
    for item in items:
        chain: tuple[str, ...] = ()
        # 找到差异涉及的"根节点"
        root_id = _extract_root_id(item)
        if root_id and target.has_node(root_id):
            chain = target.impact_chain(root_id)

        if chain != item.impact_chain:
            enriched.append(SchemaDiffItem(
                diff_type=item.diff_type,
                node_id=item.node_id,
                source_value=item.source_value,
                target_value=item.target_value,
                risk=item.risk,
                impact_chain=chain,
                detail=item.detail,
            ))
        else:
            enriched.append(item)

    items.clear()
    items.extend(enriched)


def _extract_root_id(item: SchemaDiffItem) -> str | None:
    """从 diff item 提取根节点 id（用于 impact_chain 计算）。"""
    node_id = item.node_id

    if item.diff_type == SchemaDiffType.TABLE_MISSING:
        return node_id  # 表 id
    elif item.diff_type in (SchemaDiffType.COLUMN_MISSING, SchemaDiffType.COLUMN_TYPE_MISMATCH):
        # 列 id 格式: schema.table.column → 取 schema.table
        parts = node_id.rsplit(".", 1)
        return parts[0] if len(parts) == 2 else None
    elif item.diff_type in (SchemaDiffType.CONSTRAINT_LOSS, SchemaDiffType.INDEX_MISSING):
        # 约束/索引的 parent_table
        parts = node_id.rsplit(".", 1)
        return parts[0] if len(parts) == 2 else None
    elif item.diff_type == SchemaDiffType.DEPENDENCY_BROKEN:
        # node_id 格式: "source → target"
        parts = node_id.split(" → ")
        return parts[0].strip() if parts else None
    return None


def _normalize_type(type_str: str) -> str:
    """标准化类型字符串用于对比（忽略大小写和空格）。"""
    return type_str.upper().strip().replace(" ", "")
