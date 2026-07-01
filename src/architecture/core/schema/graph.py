"""
SchemaGraph — 统一 schema 语义图，生产级迁移排序与影响链分析的核心数据结构。

核心能力:
    1. add_node() / add_edge()     — 图构建
    2. get_dependencies(node)      — 获取上游依赖（必须先迁移的节点）
    3. get_dependents(node)        — 获取下游被依赖者（受影响的节点）
    4. topological_sort()          — 迁移顺序计算（Kahn 算法）
    5. subgraph(node_type)         — 按节点类型提取子图
    6. impact_chain(node)          — 递归影响链分析
    7. to_json() / from_json()     — 快照序列化（审计 + 增量 Diff）

Design:
    - 内部使用邻接表（dict[str, set[SchemaEdge]]）存储
    - 节点以 id 为 key 索引，O(1) 查找
    - 所有公开方法返回 tuple / frozenset（不可变视图）
    - 拓扑排序仅考虑 dependency 类边（DEPENDS_ON / REFERENCES / CALLS）
    - 序列化采用纯标准库（json），不引入额外依赖

Usage:
    from architecture.core.schema.graph import SchemaGraph
    from architecture.core.schema.nodes import TableNode
    from architecture.core.schema.edges import SchemaEdge, SchemaEdgeType

    g = SchemaGraph()
    g.add_node(TableNode(id="dbo.orders", name="orders"))
    g.add_edge(SchemaEdge("dbo.view_orders", "dbo.orders", SchemaEdgeType.DEPENDS_ON))

    order = g.topological_sort()  # 迁移顺序
    chain = g.impact_chain("dbo.orders")  # 影响链
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .edges import SchemaEdge, SchemaEdgeType
from .nodes import (
    BaseNode,
    ColumnNode,
    ConstraintNode,
    IndexNode,
    ProcedureNode,
    SchemaNode,
    SchemaNodeType,
    TableNode,
    ViewNode,
)

logger = logging.getLogger(__name__)


# =========================================================================
# Deep analysis result types
# =========================================================================


@dataclass(frozen=True)
class ImpactPath:
    """一条影响传播路径。

    Attributes:
        node_id: 受影响的节点 id。
        path: 从源到目标的完整路径，每个元素为 (node_id, edge_type)。
        depth: 传播深度（跳数）。
        edge_types: 路径上经过的边类型集合。
    """
    node_id: str
    path: tuple[tuple[str, str], ...]  # ((node_id, edge_type_name), ...)
    depth: int
    edge_types: frozenset[str]

    @property
    def risk_level(self) -> str:
        """基于路径特征的风险等级。

        - CRITICAL: 路径包含 REFERENCES（FK 硬依赖）
        - HIGH: 路径包含 DEPENDS_ON 且深度 ≤ 2
        - MEDIUM: 路径仅包含 CALLS 或深度 > 2
        - LOW: 仅 TRANSFORMS 边
        """
        types = self.edge_types
        if "REFERENCES" in types:
            return "CRITICAL"
        if "DEPENDS_ON" in types and self.depth <= 2:
            return "HIGH"
        if "DEPENDS_ON" in types or "CALLS" in types:
            return "MEDIUM"
        return "LOW"


@dataclass(frozen=True)
class ImpactReport:
    """深度影响分析报告。

    Attributes:
        source_node_id: 起始节点 id。
        total_affected: 受影响节点总数。
        max_depth: 最大传播深度。
        affected_by_edge_type: 按边类型分类的受影响节点数。
        affected_by_risk: 按风险等级分类的节点数。
        paths: 所有影响路径（按深度排序）。
        critical_path_ids: CRITICAL 风险路径的目标节点 id。
    """
    source_node_id: str
    total_affected: int
    max_depth: int
    affected_by_edge_type: dict[str, int]
    affected_by_risk: dict[str, int]
    paths: tuple[ImpactPath, ...]
    critical_path_ids: tuple[str, ...]


# =========================================================================
# Exceptions
# =========================================================================


class SchemaGraphError(Exception):
    """SchemaGraph 操作异常基类。"""


class NodeNotFoundError(SchemaGraphError):
    """引用了不存在的节点。"""


class CyclicDependencyError(SchemaGraphError):
    """检测到循环依赖，无法拓扑排序。"""


# =========================================================================
# SchemaGraph
# =========================================================================


@dataclass
class SchemaGraph:
    """统一 Schema 语义图。

    内部数据结构:
        _nodes: dict[str, BaseNode]           — id → node 映射
        _outgoing: dict[str, set[SchemaEdge]]  — source_id → 出边集合
        _incoming: dict[str, set[SchemaEdge]]  — target_id → 入边集合
    """

    _nodes: dict[str, BaseNode] = field(default_factory=dict)
    _outgoing: dict[str, set[SchemaEdge]] = field(default_factory=lambda: defaultdict(set))
    _incoming: dict[str, set[SchemaEdge]] = field(default_factory=lambda: defaultdict(set))

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: BaseNode) -> None:
        """添加节点。重复添加同一 id 会覆盖（支持 schema evolution 更新）。

        Args:
            node: 要添加的节点。

        Raises:
            SchemaGraphError: node 参数不是 BaseNode 实例。
        """
        if not isinstance(node, BaseNode):
            raise SchemaGraphError(f"Expected BaseNode, got {type(node).__name__}")
        self._nodes[node.id] = node
        logger.debug("add_node: %s (%s)", node.id, node.node_type.name)

    def add_edge(self, edge: SchemaEdge) -> None:
        """添加有向边。

        不强制要求 source/target 节点已存在（支持增量构建），
        但 topological_sort / impact_chain 会忽略悬空边。

        Args:
            edge: 要添加的边。

        Raises:
            SchemaGraphError: edge 参数不是 SchemaEdge 实例。
        """
        if not isinstance(edge, SchemaEdge):
            raise SchemaGraphError(f"Expected SchemaEdge, got {type(edge).__name__}")
        self._outgoing[edge.source_id].add(edge)
        self._incoming[edge.target_id].add(edge)
        logger.debug(
            "add_edge: %s -[%s]-> %s",
            edge.source_id, edge.edge_type.name, edge.target_id,
        )

    # ------------------------------------------------------------------
    # Node queries
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> BaseNode:
        """按 id 获取节点。

        Raises:
            NodeNotFoundError: 节点不存在。
        """
        if node_id not in self._nodes:
            raise NodeNotFoundError(f"Node not found: {node_id}")
        return self._nodes[node_id]

    def has_node(self, node_id: str) -> bool:
        """检查节点是否存在。"""
        return node_id in self._nodes

    @property
    def nodes(self) -> tuple[BaseNode, ...]:
        """所有节点的不可变视图。"""
        return tuple(self._nodes.values())

    @property
    def node_count(self) -> int:
        """节点总数。"""
        return len(self._nodes)

    def nodes_by_type(self, node_type: SchemaNodeType) -> tuple[BaseNode, ...]:
        """按类型过滤节点。"""
        return tuple(n for n in self._nodes.values() if n.node_type == node_type)

    # ------------------------------------------------------------------
    # Edge queries
    # ------------------------------------------------------------------

    @property
    def edges(self) -> tuple[SchemaEdge, ...]:
        """所有边的不可变视图（去重）。"""
        seen: set[SchemaEdge] = set()
        for edge_set in self._outgoing.values():
            seen.update(edge_set)
        return tuple(seen)

    @property
    def edge_count(self) -> int:
        """边总数。"""
        return sum(len(s) for s in self._outgoing.values())

    # ------------------------------------------------------------------
    # Dependency analysis
    # ------------------------------------------------------------------

    def get_dependencies(self, node_id: str) -> tuple[BaseNode, ...]:
        """获取某节点的直接上游依赖（必须先迁移的节点）。

        沿入边方向遍历，返回所有 dependency 类边的 source 节点。

        Args:
            node_id: 节点 id。

        Returns:
            上游依赖节点元组。
        """
        deps: list[BaseNode] = []
        for edge in self._incoming.get(node_id, set()):
            if edge.is_dependency and edge.source_id in self._nodes:
                deps.append(self._nodes[edge.source_id])
        # 同时也要看出边：node 的出边 target 也是 node 的依赖
        for edge in self._outgoing.get(node_id, set()):
            if edge.is_dependency and edge.target_id in self._nodes:
                deps.append(self._nodes[edge.target_id])
        return tuple(deps)

    def get_dependents(self, node_id: str) -> tuple[BaseNode, ...]:
        """获取某节点的直接下游被依赖者（受此节点影响的节点）。

        沿入边方向遍历：如果有边 A → node_id，则 A 是 node_id 的被依赖者。

        Args:
            node_id: 节点 id。

        Returns:
            下游被依赖节点元组。
        """
        depnts: list[BaseNode] = []
        # 入边：edge.target_id == node_id，edge.source_id 依赖了 node_id
        for edge in self._incoming.get(node_id, set()):
            if edge.is_dependency and edge.source_id in self._nodes:
                depnts.append(self._nodes[edge.source_id])
        return tuple(depnts)

    def impact_chain(self, node_id: str) -> tuple[str, ...]:
        """递归影响链分析 — 从某节点出发，找出所有受其影响的下游节点。

        使用 BFS 沿"被依赖"方向遍历，返回所有直接/间接被影响的节点 id。
        这是迁移风险评估的核心输入。

        Args:
            node_id: 起始节点 id。

        Returns:
            受影响的节点 id 有序元组（按距离排序，近 → 远）。

        Example:
            impact_chain("dbo.orders") → ("dbo.view_order_summary", "sp_calc_revenue")
        """
        visited: list[str] = []
        seen: set[str] = {node_id}
        queue: deque[str] = deque()

        # 初始：找出直接依赖 node_id 的节点
        for edge in self._incoming.get(node_id, set()):
            if edge.is_dependency and edge.source_id not in seen:
                seen.add(edge.source_id)
                queue.append(edge.source_id)
                visited.append(edge.source_id)

        # BFS 扩展
        while queue:
            current = queue.popleft()
            for edge in self._incoming.get(current, set()):
                if edge.is_dependency and edge.source_id not in seen:
                    seen.add(edge.source_id)
                    queue.append(edge.source_id)
                    visited.append(edge.source_id)

        return tuple(visited)

    # ------------------------------------------------------------------
    # Deep impact analysis
    # ------------------------------------------------------------------

    def impact_paths(self, node_id: str) -> tuple[ImpactPath, ...]:
        """深度影响路径分析 — 追踪影响传播的完整路径。

        与 impact_chain 的区别:
            - impact_chain: 只返回受影响节点 ID（扁平列表）
            - impact_paths: 返回每条传播路径 + 边类型 + 深度

        使用 BFS 沿"被依赖"方向遍历，同时记录路径。

        Args:
            node_id: 起始节点 id。

        Returns:
            ImpactPath 元组，按深度排序（近 → 远）。

        Example:
            impact_paths("dbo.orders") → (
                ImpactPath(node_id="view_order_summary",
                           path=(("dbo.orders", "DEPENDS_ON"),
                                 ("dbo.view_order_summary", "")),
                           depth=1, ...),
                ImpactPath(node_id="sp_calc_revenue",
                           path=(("dbo.orders", "REFERENCES"),
                                 ("dbo.order_items", "DEPENDS_ON"),
                                 ("dbo.sp_calc_revenue", "")),
                           depth=2, ...),
            )
        """
        results: list[ImpactPath] = []
        seen: set[str] = {node_id}
        # BFS queue: (current_id, path_so_far)
        initial_path: tuple[tuple[str, str], ...] = ((node_id, ""),)
        queue: deque[tuple[str, tuple[tuple[str, str], ...]]] = deque()

        # 初始层：直接依赖 node_id 的节点
        for edge in self._incoming.get(node_id, set()):
            if edge.is_dependency and edge.source_id not in seen:
                seen.add(edge.source_id)
                step = (edge.source_id, edge.edge_type.name)
                path = initial_path + (step,)
                queue.append((edge.source_id, path))
                edge_types = frozenset(edge.edge_type.name for _, et in path if et)
                results.append(ImpactPath(
                    node_id=edge.source_id,
                    path=path,
                    depth=1,
                    edge_types=edge_types,
                ))

        # BFS 扩展
        while queue:
            current_id, current_path = queue.popleft()
            for edge in self._incoming.get(current_id, set()):
                if edge.is_dependency and edge.source_id not in seen:
                    seen.add(edge.source_id)
                    step = (edge.source_id, edge.edge_type.name)
                    path = current_path + (step,)
                    queue.append((edge.source_id, path))
                    depth = len(path) - 1  # 减去起始节点
                    edge_types = frozenset(et for _, et in path if et)
                    results.append(ImpactPath(
                        node_id=edge.source_id,
                        path=path,
                        depth=depth,
                        edge_types=edge_types,
                    ))

        return tuple(results)

    def impact_report(self, node_id: str) -> ImpactReport:
        """生成深度影响分析报告 — 量化评估迁移风险。

        整合 impact_paths 结果，按边类型和风险等级分类统计。

        Args:
            node_id: 起始节点 id（即将被迁移/变更的节点）。

        Returns:
            ImpactReport 包含完整的影响分析数据。
        """
        paths = self.impact_paths(node_id)

        by_edge: dict[str, int] = defaultdict(int)
        by_risk: dict[str, int] = defaultdict(int)
        critical_ids: list[str] = []
        max_depth = 0

        for p in paths:
            # 按边类型统计（每条路径按主导边类型归类）
            for et in p.edge_types:
                by_edge[et] += 1
            # 按风险等级统计
            risk = p.risk_level
            by_risk[risk] += 1
            if risk == "CRITICAL":
                critical_ids.append(p.node_id)
            if p.depth > max_depth:
                max_depth = p.depth

        return ImpactReport(
            source_node_id=node_id,
            total_affected=len(paths),
            max_depth=max_depth,
            affected_by_edge_type=dict(by_edge),
            affected_by_risk=dict(by_risk),
            paths=paths,
            critical_path_ids=tuple(critical_ids),
        )

    def get_transitive_dependencies(self, node_id: str) -> tuple[str, ...]:
        """递归获取所有上游传递依赖 — 必须先于本节点迁移的全部节点。

        与 get_dependencies（仅 1-hop）的区别：
            - get_dependencies: 只返回直接依赖
            - get_transitive_dependencies: 递归到根，返回完整传递闭包

        Args:
            node_id: 起始节点 id。

        Returns:
            所有上游依赖节点 id 元组（BFS 顺序，近 → 远）。

        Example:
            get_transitive_dependencies("sp_calc_revenue") →
                ("dbo.orders", "dbo.order_items", "dbo.sp_get_price",
                 "dbo.customers", "dbo.products")
        """
        visited: list[str] = []
        seen: set[str] = {node_id}
        queue: deque[str] = deque()

        # 初始层：直接依赖
        for edge in self._outgoing.get(node_id, set()):
            if edge.is_dependency and edge.target_id not in seen and edge.target_id in self._nodes:
                seen.add(edge.target_id)
                queue.append(edge.target_id)
                visited.append(edge.target_id)

        # BFS 向上扩展
        while queue:
            current = queue.popleft()
            for edge in self._outgoing.get(current, set()):
                if edge.is_dependency and edge.target_id not in seen and edge.target_id in self._nodes:
                    seen.add(edge.target_id)
                    queue.append(edge.target_id)
                    visited.append(edge.target_id)

        return tuple(visited)

    def column_impact_chain(self, table_id: str, column_name: str) -> tuple[dict[str, Any], ...]:
        """列级血缘追踪 — 追踪某列变更的影响传播路径。

        沿 TRANSFORMS 边追踪列级血缘，同时沿 DEPENDS_ON/REFERENCES
        追踪节点级影响，两者交叉得到完整影响图。

        Args:
            table_id: 列所属的表/视图节点 id。
            column_name: 要追踪的列名。

        Returns:
            影响记录列表，每条包含:
            - node_id: 受影响节点
            - column: 受影响的列名（如可确定）
            - via_edge_type: 传播边类型
            - depth: 传播深度
            - expression: 转换表达式（如 TRANSFORMS 边携带）
        """
        results: list[dict[str, Any]] = []
        # 初始列标识
        col_key = f"{table_id}.{column_name}"
        seen: set[str] = {col_key}
        # BFS: (current_node_id, current_col_name, depth)
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((table_id, column_name, 0))

        while queue:
            cur_node, cur_col, depth = queue.popleft()

            # 1) 沿 TRANSFORMS 边追踪列级血缘
            for edge in self._outgoing.get(cur_node, set()):
                if edge.edge_type != SchemaEdgeType.TRANSFORMS:
                    continue
                target_col = edge.metadata.get("target_column", "")
                target_node = edge.target_id
                col_key = f"{target_node}.{target_col}"
                if col_key in seen:
                    continue
                seen.add(col_key)
                results.append({
                    "node_id": target_node,
                    "column": target_col,
                    "via_edge_type": "TRANSFORMS",
                    "depth": depth + 1,
                    "expression": edge.metadata.get("expression", ""),
                })
                queue.append((target_node, target_col, depth + 1))

            # 2) 沿 TRANSFORMS 入边反向追踪
            for edge in self._incoming.get(cur_node, set()):
                if edge.edge_type != SchemaEdgeType.TRANSFORMS:
                    continue
                source_col = edge.metadata.get("source_column", "")
                source_node = edge.source_id
                col_key = f"{source_node}.{source_col}"
                if col_key in seen:
                    continue
                seen.add(col_key)
                results.append({
                    "node_id": source_node,
                    "column": source_col,
                    "via_edge_type": "TRANSFORMS",
                    "depth": depth + 1,
                    "expression": edge.metadata.get("expression", ""),
                })
                queue.append((source_node, source_col, depth + 1))

            # 3) 沿 DEPENDS_ON/REFERENCES 入边传播（节点级）
            if depth == 0:
                for edge in self._incoming.get(cur_node, set()):
                    if not edge.is_dependency:
                        continue
                    source_id = edge.source_id
                    node_key = f"{source_id}.*"
                    if node_key in seen:
                        continue
                    seen.add(node_key)
                    results.append({
                        "node_id": source_id,
                        "column": "*",
                        "via_edge_type": edge.edge_type.name,
                        "depth": depth + 1,
                        "expression": "",
                    })

        return tuple(results)

    def migration_waves(self) -> tuple[tuple[str, ...], ...]:
        """迁移波次规划 — 将节点分组为可并行迁移的批次。

        基于拓扑排序的层级分解:
            - Wave 0: 无依赖的节点（可立即迁移）
            - Wave 1: 仅依赖 Wave 0 的节点
            - Wave N: 依赖 Wave 0..N-1 的节点

        同一 Wave 内的节点互不依赖，可并行迁移。

        Returns:
            元组的元组，每个内部元组为一个波次的节点 id。

        Raises:
            CyclicDependencyError: 图中存在循环依赖。
        """
        # 构建仅含 dependency 边的入度表
        adj: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {nid: 0 for nid in self._nodes}

        for source_id, edges in self._outgoing.items():
            if source_id not in self._nodes:
                continue
            dep_count = 0
            for edge in edges:
                if not edge.is_dependency:
                    continue
                if edge.target_id not in self._nodes:
                    continue
                adj[edge.target_id].append(source_id)
                dep_count += 1
            in_deg[source_id] = dep_count

        # BFS 按层（wave）分组
        current_wave = [nid for nid, deg in in_deg.items() if deg == 0]
        waves: list[tuple[str, ...]] = []
        processed = 0

        while current_wave:
            waves.append(tuple(sorted(current_wave)))
            processed += len(current_wave)
            next_wave: list[str] = []
            for nid in current_wave:
                for successor in adj.get(nid, []):
                    in_deg[successor] -= 1
                    if in_deg[successor] == 0:
                        next_wave.append(successor)
            current_wave = next_wave

        if processed != len(self._nodes):
            in_cycle = [nid for nid, deg in in_deg.items() if deg > 0]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among {len(in_cycle)} nodes: "
                f"{in_cycle[:10]}{'...' if len(in_cycle) > 10 else ''}"
            )

        return tuple(waves)

    # ------------------------------------------------------------------
    # Topological sort (migration order)
    # ------------------------------------------------------------------

    def topological_sort(self) -> tuple[str, ...]:
        """拓扑排序 — 计算合法迁移顺序（Kahn 算法）。

        仅考虑 dependency 类边（DEPENDS_ON / REFERENCES / CALLS）。
        返回的序列保证：如果 A 依赖 B，则 B 在 A 之前。

        Returns:
            按迁移顺序排列的节点 id 元组。

        Raises:
            CyclicDependencyError: 图中存在循环依赖。
        """
        # 构建仅含 dependency 边的邻接表
        # edge 方向: source→target 表示 source 依赖 target
        # 拓扑排序要求: target 在 source 之前
        # → 反转: target 是 source 的前驱, adj[target].append(source)
        adj: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {nid: 0 for nid in self._nodes}

        for source_id, edges in self._outgoing.items():
            if source_id not in self._nodes:
                continue
            dep_count = 0
            for edge in edges:
                if not edge.is_dependency:
                    continue
                if edge.target_id not in self._nodes:
                    continue
                # source depends on target → target 必须先
                # 在拓扑图中：target → source（target 是 source 的前驱）
                adj[edge.target_id].append(source_id)
                dep_count += 1
            in_deg[source_id] = dep_count

        # Kahn: 从入度为 0 的节点开始
        queue: deque[str] = deque(
            nid for nid, deg in in_deg.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            # 稳定排序：同入度时按 node_id 字典序
            node_id = queue.popleft()
            result.append(node_id)

            for successor in sorted(adj.get(node_id, [])):
                in_deg[successor] -= 1
                if in_deg[successor] == 0:
                    queue.append(successor)

        if len(result) != len(self._nodes):
            # 找出环中的节点（便于诊断）
            in_cycle = [nid for nid, deg in in_deg.items() if deg > 0]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among {len(in_cycle)} nodes: "
                f"{in_cycle[:10]}{'...' if len(in_cycle) > 10 else ''}"
            )

        return tuple(result)

    # ------------------------------------------------------------------
    # Subgraph extraction
    # ------------------------------------------------------------------

    def subgraph(
        self,
        node_type: SchemaNodeType | None = None,
        node_ids: set[str] | None = None,
    ) -> SchemaGraph:
        """提取子图。

        支持两种模式:
            1. 按 node_type 过滤（如只取 TABLE 节点及其相关边）
            2. 按 node_ids 集合过滤

        Args:
            node_type: 要保留的节点类型（None 表示不过滤）。
            node_ids: 要保留的节点 id 集合（None 表示不过滤）。

        Returns:
            新的 SchemaGraph 实例。
        """
        sub = SchemaGraph()

        if node_ids is not None:
            keep_ids = node_ids & set(self._nodes.keys())
        elif node_type is not None:
            keep_ids = {
                n.id for n in self._nodes.values()
                if n.node_type == node_type
            }
        else:
            keep_ids = set(self._nodes.keys())

        for nid in keep_ids:
            sub.add_node(self._nodes[nid])

        # 保留两端都在 keep_ids 中的边
        for source_id, edges in self._outgoing.items():
            if source_id not in keep_ids:
                continue
            for edge in edges:
                if edge.target_id in keep_ids:
                    sub.add_edge(edge)

        return sub

    # ------------------------------------------------------------------
    # Serialization (snapshot / audit / incremental diff)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """序列化为 JSON 字符串（schema 快照）。

        用途:
            - 迁移前保存 source schema snapshot
            - 迁移后保存 target schema snapshot
            - 作为 Schema Diff Engine 的输入

        Returns:
            格式化 JSON 字符串。
        """
        data = {
            "version": "1.0",
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "nodes": [self._serialize_node(n) for n in self._nodes.values()],
            "edges": [self._serialize_edge(e) for e in self.edges],
        }
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> SchemaGraph:
        """从 JSON 字符串反序列化恢复 SchemaGraph。

        Args:
            json_str: to_json() 产出的 JSON 字符串。

        Returns:
            恢复的 SchemaGraph 实例。
        """
        data = json.loads(json_str)
        graph = cls()

        node_type_map: dict[str, type] = {
            "TABLE": TableNode,
            "COLUMN": ColumnNode,
            "VIEW": ViewNode,
            "PROCEDURE": ProcedureNode,
            "CONSTRAINT": ConstraintNode,
            "INDEX": IndexNode,
        }

        for nd in data.get("nodes", []):
            ntype = nd.pop("node_type", "TABLE")
            klass = node_type_map.get(ntype, TableNode)
            # metadata 需要恢复为 dict
            nd.setdefault("metadata", {})
            # tuple 字段恢复
            for tuple_field in (
                "columns", "source_tables", "called_procedures",
                "referenced_tables", "parameters", "referenced_columns",
            ):
                if tuple_field in nd and isinstance(nd[tuple_field], list):
                    nd[tuple_field] = tuple(nd[tuple_field])
            # ConstraintType / IndexType 恢复
            if "constraint_type" in nd and isinstance(nd["constraint_type"], str):
                from .nodes import ConstraintType
                nd["constraint_type"] = ConstraintType[nd["constraint_type"]]
            if "index_type" in nd and isinstance(nd["index_type"], str):
                from .nodes import IndexType
                nd["index_type"] = IndexType[nd["index_type"]]
            try:
                node = klass(**nd)
                graph.add_node(node)
            except Exception as exc:
                logger.warning("Skip node %s: %s", nd.get("id", "?"), exc)

        edge_type_map = {et.name: et for et in SchemaEdgeType}
        for ed in data.get("edges", []):
            etype_str = ed.get("edge_type", "DEPENDS_ON")
            etype = edge_type_map.get(etype_str, SchemaEdgeType.DEPENDS_ON)
            edge = SchemaEdge(
                source_id=ed["source_id"],
                target_id=ed["target_id"],
                edge_type=etype,
                metadata=ed.get("metadata", {}),
            )
            graph.add_edge(edge)

        return graph

    # ------------------------------------------------------------------
    # Statistics / diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """图的统计摘要 — 用于调试和报告。"""
        type_counts: dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            type_counts[n.node_type.name] += 1

        edge_counts: dict[str, int] = defaultdict(int)
        for edges in self._outgoing.values():
            for e in edges:
                edge_counts[e.edge_type.name] += 1

        return {
            "total_nodes": self.node_count,
            "total_edges": self.edge_count,
            "node_type_counts": dict(type_counts),
            "edge_type_counts": dict(edge_counts),
            "tables": len(self.nodes_by_type(SchemaNodeType.TABLE)),
            "views": len(self.nodes_by_type(SchemaNodeType.VIEW)),
            "procedures": len(self.nodes_by_type(SchemaNodeType.PROCEDURE)),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_node(node: BaseNode) -> dict[str, Any]:
        """序列化单个节点为 dict。"""
        from dataclasses import asdict
        d = asdict(node)
        d["node_type"] = node.node_type.name
        # 枚举字段转为字符串
        if hasattr(node, "constraint_type") and node.constraint_type is not None:
            d["constraint_type"] = node.constraint_type.name
        if hasattr(node, "index_type") and node.index_type is not None:
            d["index_type"] = node.index_type.name
        return d

    @staticmethod
    def _serialize_edge(edge: SchemaEdge) -> dict[str, Any]:
        """序列化单条边为 dict。"""
        return {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "edge_type": edge.edge_type.name,
            "metadata": edge.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"SchemaGraph(nodes={self.node_count}, edges={self.edge_count})"
        )
