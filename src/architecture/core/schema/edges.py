"""
Schema Edge Definitions — schema 节点之间的关系建模。

边类型:
    DEPENDS_ON   — 依赖关系（View → Table, SP → Table）
    REFERENCES   — 字段引用（FK: Column → Column）
    CALLS        — 存储过程调用（SP → SP）
    TRANSFORMS   — 视图转换关系（View 对源表列的映射/转换）

Design:
    - SchemaEdge 采用 frozen dataclass，不可变
    - source_id / target_id 指向 BaseNode.id
    - edge_type 枚举用于过滤和序列化
    - metadata 存放边级属性（如 FK 映射、转换表达式等）

Usage:
    from architecture.core.schema.edges import SchemaEdge, SchemaEdgeType

    edge = SchemaEdge(
        source_id="dbo.view_order_summary",
        target_id="dbo.orders",
        edge_type=SchemaEdgeType.DEPENDS_ON,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ---------------------------------------------------------------------------
# Edge type enum
# ---------------------------------------------------------------------------


class SchemaEdgeType(Enum):
    """边类型枚举 — schema 节点间的四种关系。"""

    DEPENDS_ON = auto()
    """依赖关系: 视图/SP 依赖某张表才能运行。
    
    典型场景:
        - View → Table（视图定义中 FROM/JOIN 了某表）
        - SP → Table（存储过程中 SELECT/INSERT/UPDATE/DELETE 了某表）
    
    迁移语义:
        target 必须先于 source 迁移。拓扑排序基于此边确定迁移顺序。
    """

    REFERENCES = auto()
    """字段引用: FK 约束建立的列级引用。
    
    典型场景:
        - FK Column → PK Column（orders.customer_id → customers.customer_id）
    
    迁移语义:
        被引用的表必须先迁移。REFERENCES 隐含 DEPENDS_ON 语义。
    """

    CALLS = auto()
    """过程调用: 存储过程之间的调用关系。
    
    典型场景:
        - SP A 中 EXEC SP B
    
    迁移语义:
        被调用的 SP 必须先迁移/编译。影响链分析的核心输入。
    """

    TRANSFORMS = auto()
    """视图转换: 视图对源表列的映射/转换关系。
    
    典型场景:
        - View 的 amount 列 = SUM(orders.amount)（聚合转换）
        - View 的 full_name = first_name + ' ' + last_name（拼接转换）
    
    迁移语义:
        标记列级血缘关系。当源表列类型变更时，可沿 TRANSFORMS 边追溯影响。
    """


# ---------------------------------------------------------------------------
# Edge dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchemaEdge:
    """Schema 图中的一条有向边。

    方向约定: source → target
    - DEPENDS_ON:  source (View/SP) depends on target (Table)
    - REFERENCES:  source (FK column) references target (PK column)
    - CALLS:       source (SP) calls target (SP)
    - TRANSFORMS:  source (View column) transforms target (Table column)

    Attributes:
        source_id: 源节点 id（必须对应某个 BaseNode.id）。
        target_id: 目标节点 id（必须对应某个 BaseNode.id）。
        edge_type: 边类型枚举。
        metadata: 扩展属性字典，可存放:
                  - REFERENCES: {"mapping": "orders.customer_id -> customers.customer_id"}
                  - TRANSFORMS: {"expression": "SUM(amount)", "aggregation": True}
                  - CALLS: {"call_site_line": 42}
    """
    source_id: str
    target_id: str
    edge_type: SchemaEdgeType
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.source_id, self.target_id, self.edge_type))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SchemaEdge):
            return NotImplemented
        return (
            self.source_id == other.source_id
            and self.target_id == other.target_id
            and self.edge_type == other.edge_type
        )

    @property
    def is_dependency(self) -> bool:
        """是否为依赖类边（影响迁移排序）。

        DEPENDS_ON 和 REFERENCES 均隐含迁移顺序约束。
        CALLS 也隐含 SP 间的迁移顺序。
        TRANSFORMS 仅用于血缘追踪，不影响排序。
        """
        return self.edge_type in (
            SchemaEdgeType.DEPENDS_ON,
            SchemaEdgeType.REFERENCES,
            SchemaEdgeType.CALLS,
        )
