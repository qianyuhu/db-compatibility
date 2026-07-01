"""
Schema Graph 核心功能测试。

覆盖:
    1. Node 创建与类型判定
    2. Edge 创建与 is_dependency 语义
    3. SchemaGraph 增删查
    4. 拓扑排序（正确顺序 + 循环检测）
    5. 影响链分析（impact_chain）
    6. 子图提取（subgraph）
    7. JSON 序列化/反序列化
    8. 架构约束（architecture_guard 规则）
"""

import json

import pytest

from architecture.core.schema import (
    BaseNode,
    ColumnNode,
    ConstraintNode,
    ConstraintType,
    CyclicDependencyError,
    ImpactPath,
    ImpactReport,
    IndexNode,
    IndexType,
    NodeNotFoundError,
    ProcedureNode,
    SchemaEdge,
    SchemaEdgeType,
    SchemaGraph,
    SchemaGraphError,
    SchemaNodeType,
    TableNode,
    ViewNode,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sample_graph() -> SchemaGraph:
    """构建一个典型的迁移场景图:

    customers (独立表)
    orders (依赖 customers: FK)
    products (独立表)
    order_items (依赖 orders + products: FK)
    view_order_summary (依赖 orders + customers)
    sp_calc_revenue (依赖 orders + order_items, 调用 sp_get_price)
    sp_get_price (依赖 products)
    """
    g = SchemaGraph()

    # Tables
    g.add_node(TableNode(
        id="dbo.customers", name="customers", schema="dbo",
        columns=("customer_id", "name", "email"),
        primary_key="customer_id",
    ))
    g.add_node(TableNode(
        id="dbo.orders", name="orders", schema="dbo",
        columns=("order_id", "customer_id", "amount", "order_date"),
        primary_key="order_id",
    ))
    g.add_node(TableNode(
        id="dbo.products", name="products", schema="dbo",
        columns=("product_id", "name", "price"),
        primary_key="product_id",
    ))
    g.add_node(TableNode(
        id="dbo.order_items", name="order_items", schema="dbo",
        columns=("item_id", "order_id", "product_id", "quantity"),
        primary_key="item_id",
    ))

    # View
    g.add_node(ViewNode(
        id="dbo.view_order_summary", name="view_order_summary", schema="dbo",
        source_tables=("dbo.orders", "dbo.customers"),
        columns=("order_id", "customer_name", "total_amount"),
    ))

    # Procedures
    g.add_node(ProcedureNode(
        id="dbo.sp_get_price", name="sp_get_price", schema="dbo",
        referenced_tables=("dbo.products",),
    ))
    g.add_node(ProcedureNode(
        id="dbo.sp_calc_revenue", name="sp_calc_revenue", schema="dbo",
        referenced_tables=("dbo.orders", "dbo.order_items"),
        called_procedures=("dbo.sp_get_price",),
    ))

    # Edges: FK dependencies
    g.add_edge(SchemaEdge(
        "dbo.orders", "dbo.customers", SchemaEdgeType.REFERENCES,
        metadata={"mapping": "orders.customer_id -> customers.customer_id"},
    ))
    g.add_edge(SchemaEdge(
        "dbo.order_items", "dbo.orders", SchemaEdgeType.REFERENCES,
    ))
    g.add_edge(SchemaEdge(
        "dbo.order_items", "dbo.products", SchemaEdgeType.REFERENCES,
    ))

    # Edges: View dependencies
    g.add_edge(SchemaEdge(
        "dbo.view_order_summary", "dbo.orders", SchemaEdgeType.DEPENDS_ON,
    ))
    g.add_edge(SchemaEdge(
        "dbo.view_order_summary", "dbo.customers", SchemaEdgeType.DEPENDS_ON,
    ))

    # Edges: SP dependencies
    g.add_edge(SchemaEdge(
        "dbo.sp_calc_revenue", "dbo.orders", SchemaEdgeType.DEPENDS_ON,
    ))
    g.add_edge(SchemaEdge(
        "dbo.sp_calc_revenue", "dbo.order_items", SchemaEdgeType.DEPENDS_ON,
    ))
    g.add_edge(SchemaEdge(
        "dbo.sp_calc_revenue", "dbo.sp_get_price", SchemaEdgeType.CALLS,
    ))
    g.add_edge(SchemaEdge(
        "dbo.sp_get_price", "dbo.products", SchemaEdgeType.DEPENDS_ON,
    ))

    return g


# =========================================================================
# Node tests
# =========================================================================


class TestNodes:
    def test_table_node_type(self):
        n = TableNode(id="t1", name="t1")
        assert n.node_type == SchemaNodeType.TABLE

    def test_column_node_type(self):
        n = ColumnNode(id="t1.c1", name="c1", data_type="INT", parent_table="t1")
        assert n.node_type == SchemaNodeType.COLUMN
        assert n.nullable is True

    def test_view_node_type(self):
        n = ViewNode(id="v1", name="v1")
        assert n.node_type == SchemaNodeType.VIEW

    def test_procedure_node_type(self):
        n = ProcedureNode(id="sp1", name="sp1")
        assert n.node_type == SchemaNodeType.PROCEDURE

    def test_constraint_node_type(self):
        n = ConstraintNode(
            id="pk_t1", name="pk_t1",
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=("id",),
            parent_table="t1",
        )
        assert n.node_type == SchemaNodeType.CONSTRAINT
        assert n.constraint_type == ConstraintType.PRIMARY_KEY

    def test_index_node_type(self):
        n = IndexNode(
            id="idx_t1_name", name="idx_t1_name",
            index_type=IndexType.BTREE,
            columns=("name",),
            parent_table="t1",
        )
        assert n.node_type == SchemaNodeType.INDEX

    def test_node_hash_and_equality(self):
        n1 = TableNode(id="t1", name="t1")
        n2 = TableNode(id="t1", name="t1", columns=("a", "b"))
        # Same id → same node (equality by id)
        assert n1 == n2
        assert hash(n1) == hash(n2)

    def test_node_immutable(self):
        n = TableNode(id="t1", name="t1")
        with pytest.raises(AttributeError):
            n.name = "t2"  # type: ignore


# =========================================================================
# Edge tests
# =========================================================================


class TestEdges:
    def test_depends_on_is_dependency(self):
        e = SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON)
        assert e.is_dependency is True

    def test_references_is_dependency(self):
        e = SchemaEdge("a", "b", SchemaEdgeType.REFERENCES)
        assert e.is_dependency is True

    def test_calls_is_dependency(self):
        e = SchemaEdge("a", "b", SchemaEdgeType.CALLS)
        assert e.is_dependency is True

    def test_transforms_not_dependency(self):
        e = SchemaEdge("a", "b", SchemaEdgeType.TRANSFORMS)
        assert e.is_dependency is False

    def test_edge_equality(self):
        e1 = SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON)
        e2 = SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON)
        assert e1 == e2
        assert hash(e1) == hash(e2)

    def test_edge_immutable(self):
        e = SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON)
        with pytest.raises(AttributeError):
            e.source_id = "c"  # type: ignore


# =========================================================================
# SchemaGraph tests
# =========================================================================


class TestSchemaGraph:
    def test_add_and_get_node(self):
        g = SchemaGraph()
        n = TableNode(id="t1", name="t1")
        g.add_node(n)
        assert g.has_node("t1")
        assert g.get_node("t1") is n
        assert g.node_count == 1

    def test_get_nonexistent_node_raises(self):
        g = SchemaGraph()
        with pytest.raises(NodeNotFoundError):
            g.get_node("no_such")

    def test_add_invalid_node_raises(self):
        g = SchemaGraph()
        with pytest.raises(SchemaGraphError):
            g.add_node("not_a_node")  # type: ignore

    def test_add_edge(self):
        g = SchemaGraph()
        g.add_node(TableNode(id="a", name="a"))
        g.add_node(TableNode(id="b", name="b"))
        g.add_edge(SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON))
        assert g.edge_count == 1

    def test_nodes_by_type(self, sample_graph: SchemaGraph):
        tables = sample_graph.nodes_by_type(SchemaNodeType.TABLE)
        assert len(tables) == 4
        views = sample_graph.nodes_by_type(SchemaNodeType.VIEW)
        assert len(views) == 1
        procs = sample_graph.nodes_by_type(SchemaNodeType.PROCEDURE)
        assert len(procs) == 2

    def test_summary(self, sample_graph: SchemaGraph):
        s = sample_graph.summary()
        assert s["total_nodes"] == 7
        assert s["tables"] == 4
        assert s["views"] == 1
        assert s["procedures"] == 2
        assert s["total_edges"] == 9


# =========================================================================
# Topological sort tests
# =========================================================================


class TestTopologicalSort:
    def test_basic_order(self, sample_graph: SchemaGraph):
        order = sample_graph.topological_sort()

        # customers 和 products 无依赖，应排在前面
        idx_customers = order.index("dbo.customers")
        idx_products = order.index("dbo.products")
        idx_orders = order.index("dbo.orders")
        idx_items = order.index("dbo.order_items")
        idx_view = order.index("dbo.view_order_summary")
        idx_sp_price = order.index("dbo.sp_get_price")
        idx_sp_rev = order.index("dbo.sp_calc_revenue")

        # orders depends on customers
        assert idx_customers < idx_orders
        # order_items depends on orders + products
        assert idx_orders < idx_items
        assert idx_products < idx_items
        # view depends on orders + customers
        assert idx_orders < idx_view
        assert idx_customers < idx_view
        # sp_get_price depends on products
        assert idx_products < idx_sp_price
        # sp_calc_revenue depends on orders, order_items, sp_get_price
        assert idx_orders < idx_sp_rev
        assert idx_items < idx_sp_rev
        assert idx_sp_price < idx_sp_rev

    def test_empty_graph(self):
        g = SchemaGraph()
        assert g.topological_sort() == ()

    def test_single_node(self):
        g = SchemaGraph()
        g.add_node(TableNode(id="t1", name="t1"))
        assert g.topological_sort() == ("t1",)

    def test_cyclic_dependency_raises(self):
        g = SchemaGraph()
        g.add_node(TableNode(id="a", name="a"))
        g.add_node(TableNode(id="b", name="b"))
        g.add_edge(SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON))
        g.add_edge(SchemaEdge("b", "a", SchemaEdgeType.DEPENDS_ON))
        with pytest.raises(CyclicDependencyError):
            g.topological_sort()

    def test_transforms_ignored_in_sort(self):
        """TRANSFORMS 边不参与拓扑排序。"""
        g = SchemaGraph()
        g.add_node(TableNode(id="t1", name="t1"))
        g.add_node(ViewNode(id="v1", name="v1"))
        # 只加 TRANSFORMS 边（不是 dependency）
        g.add_edge(SchemaEdge("v1", "t1", SchemaEdgeType.TRANSFORMS))
        order = g.topological_sort()
        # 两个节点都出现，但没有先后约束
        assert set(order) == {"t1", "v1"}


# =========================================================================
# Dependency analysis tests
# =========================================================================


class TestDependencyAnalysis:
    def test_get_dependencies(self, sample_graph: SchemaGraph):
        deps = sample_graph.get_dependencies("dbo.orders")
        dep_ids = {d.id for d in deps}
        assert "dbo.customers" in dep_ids

    def test_get_dependents(self, sample_graph: SchemaGraph):
        depnts = sample_graph.get_dependents("dbo.customers")
        depnt_ids = {d.id for d in depnts}
        # orders 和 view_order_summary 依赖 customers
        assert "dbo.orders" in depnt_ids
        assert "dbo.view_order_summary" in depnt_ids

    def test_impact_chain(self, sample_graph: SchemaGraph):
        chain = sample_graph.impact_chain("dbo.customers")
        # customers 被 orders, view_order_summary 依赖
        # orders 被 order_items, view_order_summary, sp_calc_revenue 依赖
        # order_items 被 sp_calc_revenue 依赖
        # sp_calc_revenue 无下游
        assert "dbo.orders" in chain
        assert "dbo.view_order_summary" in chain
        assert "dbo.order_items" in chain
        assert "dbo.sp_calc_revenue" in chain
        # products 不依赖 customers，不应出现
        assert "dbo.products" not in chain

    def test_impact_chain_leaf_node(self, sample_graph: SchemaGraph):
        """叶子节点（无被依赖者）影响链为空。"""
        chain = sample_graph.impact_chain("dbo.sp_calc_revenue")
        assert chain == ()


# =========================================================================
# Subgraph tests
# =========================================================================


class TestSubgraph:
    def test_subgraph_by_type(self, sample_graph: SchemaGraph):
        sub = sample_graph.subgraph(node_type=SchemaNodeType.TABLE)
        assert sub.node_count == 4
        # 表之间的 REFERENCES 边应保留
        assert sub.edge_count > 0

    def test_subgraph_by_ids(self, sample_graph: SchemaGraph):
        sub = sample_graph.subgraph(node_ids={"dbo.customers", "dbo.orders"})
        assert sub.node_count == 2
        # orders→customers 的 REFERENCES 边应保留
        assert sub.edge_count == 1


# =========================================================================
# Serialization tests
# =========================================================================


class TestSerialization:
    def test_roundtrip(self, sample_graph: SchemaGraph):
        json_str = sample_graph.to_json()
        data = json.loads(json_str)

        assert data["version"] == "1.0"
        assert data["node_count"] == 7
        assert data["edge_count"] == 9

        # 反序列化
        restored = SchemaGraph.from_json(json_str)
        assert restored.node_count == 7
        assert restored.edge_count == 9

        # 验证关键节点
        assert restored.has_node("dbo.customers")
        assert restored.has_node("dbo.view_order_summary")

        # 验证拓扑排序仍然有效
        order = restored.topological_sort()
        idx_customers = order.index("dbo.customers")
        idx_orders = order.index("dbo.orders")
        assert idx_customers < idx_orders

    def test_empty_graph_roundtrip(self):
        g = SchemaGraph()
        json_str = g.to_json()
        restored = SchemaGraph.from_json(json_str)
        assert restored.node_count == 0
        assert restored.edge_count == 0

    def test_constraint_type_preserved(self):
        g = SchemaGraph()
        g.add_node(ConstraintNode(
            id="pk1", name="pk1",
            constraint_type=ConstraintType.FOREIGN_KEY,
            columns=("customer_id",),
            referenced_table="dbo.customers",
            referenced_columns=("customer_id",),
            parent_table="dbo.orders",
        ))
        json_str = g.to_json()
        restored = SchemaGraph.from_json(json_str)
        node = restored.get_node("pk1")
        assert isinstance(node, ConstraintNode)
        assert node.constraint_type == ConstraintType.FOREIGN_KEY

    def test_index_type_preserved(self):
        g = SchemaGraph()
        g.add_node(IndexNode(
            id="idx1", name="idx1",
            index_type=IndexType.CLUSTERED,
            columns=("id",),
            is_unique=True,
            parent_table="t1",
        ))
        json_str = g.to_json()
        restored = SchemaGraph.from_json(json_str)
        node = restored.get_node("idx1")
        assert isinstance(node, IndexNode)
        assert node.index_type == IndexType.CLUSTERED
        assert node.is_unique is True


# =========================================================================
# Deep impact analysis tests
# =========================================================================


class TestImpactPaths:
    def test_basic_paths(self, sample_graph: SchemaGraph):
        paths = sample_graph.impact_paths("dbo.customers")
        node_ids = {p.node_id for p in paths}
        # customers 被 orders, view_order_summary 直接依赖
        # orders 被 order_items, view_order_summary, sp_calc_revenue 依赖
        assert "dbo.orders" in node_ids
        assert "dbo.view_order_summary" in node_ids

    def test_path_depth(self, sample_graph: SchemaGraph):
        paths = sample_graph.impact_paths("dbo.products")
        path_map = {p.node_id: p for p in paths}
        # products 直接依赖: order_items, sp_get_price (depth=1)
        assert path_map["dbo.order_items"].depth == 1
        assert path_map["dbo.sp_get_price"].depth == 1
        # sp_calc_revenue 通过 order_items 或 sp_get_price (depth=2)
        assert path_map["dbo.sp_calc_revenue"].depth == 2

    def test_path_edge_types(self, sample_graph: SchemaGraph):
        paths = sample_graph.impact_paths("dbo.customers")
        path_map = {p.node_id: p for p in paths}
        # orders 通过 REFERENCES 依赖 customers
        assert "REFERENCES" in path_map["dbo.orders"].edge_types

    def test_risk_level(self, sample_graph: SchemaGraph):
        paths = sample_graph.impact_paths("dbo.customers")
        path_map = {p.node_id: p for p in paths}
        # orders 通过 REFERENCES 边，应为 CRITICAL
        assert path_map["dbo.orders"].risk_level == "CRITICAL"

    def test_empty_impact(self, sample_graph: SchemaGraph):
        """叶子节点无下游影响。"""
        paths = sample_graph.impact_paths("dbo.sp_calc_revenue")
        assert paths == ()


class TestImpactReport:
    def test_report_structure(self, sample_graph: SchemaGraph):
        report = sample_graph.impact_report("dbo.customers")
        assert isinstance(report, ImpactReport)
        assert report.source_node_id == "dbo.customers"
        assert report.total_affected > 0
        assert report.max_depth >= 1
        assert isinstance(report.affected_by_edge_type, dict)
        assert isinstance(report.affected_by_risk, dict)
        assert isinstance(report.paths, tuple)

    def test_report_critical_paths(self, sample_graph: SchemaGraph):
        report = sample_graph.impact_report("dbo.customers")
        # orders 通过 REFERENCES 依赖 customers，应产生 CRITICAL 路径
        assert len(report.critical_path_ids) > 0
        assert "dbo.orders" in report.critical_path_ids

    def test_report_edge_type_stats(self, sample_graph: SchemaGraph):
        report = sample_graph.impact_report("dbo.products")
        # products 有 REFERENCES 边（order_items）和 DEPENDS_ON 边（sp_get_price）
        assert "REFERENCES" in report.affected_by_edge_type or "DEPENDS_ON" in report.affected_by_edge_type


class TestTransitiveDependencies:
    def test_basic(self, sample_graph: SchemaGraph):
        deps = sample_graph.get_transitive_dependencies("dbo.sp_calc_revenue")
        # sp_calc_revenue depends on orders, order_items, sp_get_price
        # order_items depends on orders, products
        # sp_get_price depends on products
        # orders depends on customers
        dep_set = set(deps)
        assert "dbo.orders" in dep_set
        assert "dbo.order_items" in dep_set
        assert "dbo.sp_get_price" in dep_set
        assert "dbo.products" in dep_set
        assert "dbo.customers" in dep_set

    def test_leaf_has_no_deps(self, sample_graph: SchemaGraph):
        deps = sample_graph.get_transitive_dependencies("dbo.customers")
        assert deps == ()

    def test_single_hop(self, sample_graph: SchemaGraph):
        deps = sample_graph.get_transitive_dependencies("dbo.orders")
        # orders depends on customers only
        assert "dbo.customers" in deps


class TestColumnImpactChain:
    def test_column_with_transforms(self):
        """构建含 TRANSFORMS 边的图，验证列级血缘追踪。"""
        g = SchemaGraph()
        g.add_node(TableNode(
            id="dbo.orders", name="orders",
            columns=("order_id", "amount"),
        ))
        g.add_node(ViewNode(
            id="dbo.v_summary", name="v_summary",
            columns=("total_amount",),
        ))
        # View 的 total_amount 由 SUM(orders.amount) 转换而来
        g.add_edge(SchemaEdge(
            "dbo.v_summary", "dbo.orders", SchemaEdgeType.TRANSFORMS,
            metadata={
                "source_column": "amount",
                "target_column": "total_amount",
                "expression": "SUM(amount)",
            },
        ))

        results = g.column_impact_chain("dbo.orders", "amount")
        assert len(results) > 0
        # 应追踪到 v_summary.total_amount
        transform_hits = [r for r in results if r["via_edge_type"] == "TRANSFORMS"]
        assert any(r["node_id"] == "dbo.v_summary" for r in transform_hits)

    def test_column_no_transforms(self, sample_graph: SchemaGraph):
        """sample_graph 无 TRANSFORMS 边，列影响应仅包含节点级影响。"""
        results = sample_graph.column_impact_chain("dbo.customers", "name")
        # 只有节点级 DEPENDS_ON/REFERENCES 影响
        node_hits = [r for r in results if r["column"] == "*"]
        assert len(node_hits) > 0


class TestMigrationWaves:
    def test_basic_waves(self, sample_graph: SchemaGraph):
        waves = sample_graph.migration_waves()
        assert len(waves) >= 2  # 至少两波

        # Wave 0: 无依赖的节点 (customers, products)
        wave0 = set(waves[0])
        assert "dbo.customers" in wave0
        assert "dbo.products" in wave0

        # sp_calc_revenue 应在最后一波（依赖最多）
        all_waves_flat = []
        for w in waves:
            all_waves_flat.extend(w)
        idx_sp = all_waves_flat.index("dbo.sp_calc_revenue")
        idx_customers = all_waves_flat.index("dbo.customers")
        assert idx_customers < idx_sp

    def test_parallel_within_wave(self, sample_graph: SchemaGraph):
        waves = sample_graph.migration_waves()
        # Wave 0 中的节点互不依赖，可并行
        wave0 = waves[0]
        assert len(wave0) >= 2  # customers + products

    def test_empty_graph(self):
        g = SchemaGraph()
        assert g.migration_waves() == ()

    def test_cyclic_raises(self):
        g = SchemaGraph()
        g.add_node(TableNode(id="a", name="a"))
        g.add_node(TableNode(id="b", name="b"))
        g.add_edge(SchemaEdge("a", "b", SchemaEdgeType.DEPENDS_ON))
        g.add_edge(SchemaEdge("b", "a", SchemaEdgeType.DEPENDS_ON))
        with pytest.raises(CyclicDependencyError):
            g.migration_waves()

    def test_wave_coverage(self, sample_graph: SchemaGraph):
        """所有节点都应出现在某个 wave 中。"""
        waves = sample_graph.migration_waves()
        all_ids = set()
        for w in waves:
            all_ids.update(w)
        assert all_ids == {n.id for n in sample_graph.nodes}
