"""
Schema Node Definitions — 统一 schema 语义模型中的节点类型。

所有节点继承自 BaseNode 抽象基类，采用 frozen dataclass 保证不可变性。

Node types:
    TableNode       — 数据库表
    ColumnNode      — 表列 / 视图列
    ViewNode        — 数据库视图
    ProcedureNode   — 存储过程 / 函数
    ConstraintNode  — 约束（PK / FK / UNIQUE / CHECK / DEFAULT）
    IndexNode       — 索引

Design:
    - BaseNode 定义所有节点共享的 (id, name, schema, metadata) 四元组
    - 各子类通过 frozen dataclass 添加领域属性
    - node_type 枚举用于 pattern matching 和序列化
    - 所有节点均 hashable（基于 id），可存入 set / dict

Usage:
    from architecture.core.schema.nodes import TableNode, ColumnNode

    tbl = TableNode(id="dbo.orders", name="orders", schema="dbo",
                    columns=("order_id", "amount"), primary_key="order_id")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SchemaNodeType(Enum):
    """节点类型枚举 — 用于序列化和 pattern matching。"""
    TABLE = auto()
    COLUMN = auto()
    VIEW = auto()
    PROCEDURE = auto()
    CONSTRAINT = auto()
    INDEX = auto()


class ConstraintType(Enum):
    """约束子类型。"""
    PRIMARY_KEY = auto()
    FOREIGN_KEY = auto()
    UNIQUE = auto()
    CHECK = auto()
    DEFAULT = auto()


class IndexType(Enum):
    """索引子类型。"""
    BTREE = auto()
    HASH = auto()
    CLUSTERED = auto()
    NONCLUSTERED = auto()
    UNIQUE = auto()
    FULLTEXT = auto()


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class BaseNode(ABC):
    """所有 Schema 节点的抽象基类。

    Attributes:
        id: 全局唯一标识，格式为 "{schema}.{name}" 或 "{table}.{column}"。
        name: 节点名称（不含 schema 前缀）。
        schema: 所属 schema（默认 "dbo"）。
        metadata: 扩展属性字典（存放 dialect-specific 信息等）。
    """
    id: str
    name: str
    schema: str = "dbo"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    @abstractmethod
    def node_type(self) -> SchemaNodeType:
        """返回节点类型枚举值。"""
        ...

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseNode):
            return NotImplemented
        return self.id == other.id


# ---------------------------------------------------------------------------
# Concrete node types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class TableNode(BaseNode):
    """数据库表节点。

    Attributes:
        columns: 列名有序元组（仅名称，完整信息由 ColumnNode 承载）。
        primary_key: 主键列名（复合主键取第一列，完整 PK 由 ConstraintNode 描述）。
        row_count_estimate: 行数估计值（用于迁移容量评估，-1 表示未知）。
    """
    columns: tuple[str, ...] = field(default_factory=tuple)
    primary_key: str | None = None
    row_count_estimate: int = -1

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.TABLE


@dataclass(frozen=True, eq=False)
class ColumnNode(BaseNode):
    """列节点 — 隶属于 TableNode 或 ViewNode。

    Attributes:
        data_type: SQL 数据类型字符串，如 "INT", "DECIMAL(10,2)", "NVARCHAR(100)"。
        nullable: 是否允许 NULL。
        default_value: DEFAULT 约束表达式（None 表示无默认值）。
        is_identity: 是否为自增列（IDENTITY / SERIAL）。
        ordinal_position: 列在表中的位置（1-based）。
        parent_table: 所属表 / 视图的 id。
    """
    data_type: str = ""
    nullable: bool = True
    default_value: str | None = None
    is_identity: bool = False
    ordinal_position: int = 0
    parent_table: str = ""

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.COLUMN


@dataclass(frozen=True, eq=False)
class ViewNode(BaseNode):
    """视图节点。

    Attributes:
        definition_sql: 视图定义的完整 SQL（CREATE VIEW ... AS SELECT ...）。
        source_tables: 视图依赖的源表 id 元组。
        columns: 视图输出列名元组。
        is_materialized: 是否为物化视图。
    """
    definition_sql: str = ""
    source_tables: tuple[str, ...] = field(default_factory=tuple)
    columns: tuple[str, ...] = field(default_factory=tuple)
    is_materialized: bool = False

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.VIEW


@dataclass(frozen=True, eq=False)
class ProcedureNode(BaseNode):
    """存储过程 / 函数节点。

    Attributes:
        parameters: 参数列表，每个元素为 dict:
                    {"name": str, "data_type": str, "mode": "IN"|"OUT"|"INOUT"}
        return_type: 函数返回类型（存储过程为 None）。
        body_hash: 过程体哈希（用于变更检测）。
        called_procedures: 被此过程调用的其他过程 id 元组。
        referenced_tables: 此过程引用的表 id 元组。
        language: 过程语言标识（"tsql", "plpgsql", "plsql"）。
    """
    parameters: tuple[dict[str, str], ...] = field(default_factory=tuple)
    return_type: str | None = None
    body_hash: str = ""
    called_procedures: tuple[str, ...] = field(default_factory=tuple)
    referenced_tables: tuple[str, ...] = field(default_factory=tuple)
    language: str = "tsql"

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.PROCEDURE


@dataclass(frozen=True, eq=False)
class ConstraintNode(BaseNode):
    """约束节点 — 隶属于 TableNode。

    Attributes:
        constraint_type: 约束类型（PK / FK / UNIQUE / CHECK / DEFAULT）。
        columns: 约束涉及的列名元组。
        definition: 约束定义 SQL 片段。
        referenced_table: FK 引用的目标表 id（仅 FK 有值）。
        referenced_columns: FK 引用的目标列名元组（仅 FK 有值）。
        parent_table: 所属表的 id。
    """
    constraint_type: ConstraintType = ConstraintType.PRIMARY_KEY
    columns: tuple[str, ...] = field(default_factory=tuple)
    definition: str = ""
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = field(default_factory=tuple)
    parent_table: str = ""

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.CONSTRAINT


@dataclass(frozen=True, eq=False)
class IndexNode(BaseNode):
    """索引节点 — 隶属于 TableNode。

    Attributes:
        index_type: 索引类型。
        columns: 索引列名元组（有序，首列为 leading column）。
        is_unique: 是否唯一索引。
        is_clustered: 是否聚簇索引。
        definition: 索引定义 SQL 片段。
        parent_table: 所属表的 id。
    """
    index_type: IndexType = IndexType.BTREE
    columns: tuple[str, ...] = field(default_factory=tuple)
    is_unique: bool = False
    is_clustered: bool = False
    definition: str = ""
    parent_table: str = ""

    @property
    def node_type(self) -> SchemaNodeType:
        return SchemaNodeType.INDEX


# ---------------------------------------------------------------------------
# Union type — 便于类型缩窄
# ---------------------------------------------------------------------------

SchemaNode = (
    TableNode
    | ColumnNode
    | ViewNode
    | ProcedureNode
    | ConstraintNode
    | IndexNode
)
