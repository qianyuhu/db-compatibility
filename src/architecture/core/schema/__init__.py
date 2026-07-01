"""
core.schema — 统一 Schema 语义层（Phase 3）。

为 Table / View / Stored Procedure 提供统一的 schema 图模型，
支持依赖分析、迁移排序和影响链追踪。

核心组件:
    - SchemaNode (7 种节点): TableNode, ColumnNode, ViewNode,
                             ProcedureNode, ConstraintNode, IndexNode
    - SchemaEdge (4 种边):   DEPENDS_ON, REFERENCES, CALLS, TRANSFORMS
    - SchemaGraph:           图结构 + 拓扑排序 + 序列化 + 影响链分析
    - Builders:              TableBuilder（SQLAlchemy → Graph）, SPBuilder（IR → Graph）
    - Diff Engine:           SchemaDiffEngine（Graph 对比 + 结构化输出）

Usage:
    from architecture.core.schema import (
        SchemaGraph, TableNode, ViewNode, ProcedureNode,
        SchemaEdge, SchemaEdgeType, SchemaNodeType,
    )
    from architecture.core.schema.builder import TableBuilder, SPBuilder
    from architecture.core.schema.diff import SchemaDiffEngine
"""

from .edges import SchemaEdge, SchemaEdgeType
from .graph import (
    CyclicDependencyError,
    ImpactPath,
    ImpactReport,
    NodeNotFoundError,
    SchemaGraph,
    SchemaGraphError,
)
from .nodes import (
    BaseNode,
    ColumnNode,
    ConstraintNode,
    ConstraintType,
    IndexNode,
    IndexType,
    ProcedureNode,
    SchemaNode,
    SchemaNodeType,
    TableNode,
    ViewNode,
)

__all__ = [
    # Graph
    "SchemaGraph",
    "SchemaGraphError",
    "NodeNotFoundError",
    "CyclicDependencyError",
    "ImpactPath",
    "ImpactReport",
    # Nodes
    "BaseNode",
    "SchemaNode",
    "SchemaNodeType",
    "TableNode",
    "ColumnNode",
    "ViewNode",
    "ProcedureNode",
    "ConstraintNode",
    "ConstraintType",
    "IndexNode",
    "IndexType",
    # Edges
    "SchemaEdge",
    "SchemaEdgeType",
]
