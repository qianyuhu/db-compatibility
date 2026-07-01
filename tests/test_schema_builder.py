"""
Schema Builder 单元测试。

覆盖:
    1. TableBuilder.from_metadata — 从 SQLAlchemy MetaData 构建
    2. TableBuilder.from_inspector — 模拟 Inspector 构建
    3. SPBuilder.from_ir — 从 IRProcedure 构建
    4. SPBuilder.from_ir_list — 多 SP 间 CALLS 边
    5. 端到端: TableBuilder + SPBuilder 合并图 + 拓扑排序
"""

from unittest.mock import MagicMock

import pytest

from architecture.core.schema import (
    ColumnNode,
    ConstraintNode,
    ConstraintType,
    IndexNode,
    ProcedureNode,
    SchemaEdge,
    SchemaEdgeType,
    SchemaGraph,
    SchemaNodeType,
    TableNode,
)
from architecture.core.schema.builder import SPBuilder, TableBuilder


# =========================================================================
# TableBuilder tests
# =========================================================================


class TestTableBuilderFromMetadata:
    """使用项目真实的 SQLAlchemy MetaData 测试。"""

    def test_builds_from_project_models(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        # 应有 5 张表
        tables = graph.nodes_by_type(SchemaNodeType.TABLE)
        table_names = {t.name for t in tables}
        assert "products" in table_names
        assert "customers" in table_names
        assert "orders" in table_names
        assert "order_items" in table_names
        assert "inventory" in table_names

    def test_columns_extracted(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        # orders 表应有列节点
        order_cols = [
            n for n in graph.nodes_by_type(SchemaNodeType.COLUMN)
            if isinstance(n, ColumnNode) and n.parent_table == "dbo.orders"
        ]
        col_names = {c.name for c in order_cols}
        assert "id" in col_names
        assert "order_no" in col_names
        assert "customer_id" in col_names
        assert "total_amount" in col_names

    def test_pk_constraints(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        pks = [
            n for n in graph.nodes_by_type(SchemaNodeType.CONSTRAINT)
            if isinstance(n, ConstraintNode) and n.constraint_type == ConstraintType.PRIMARY_KEY
        ]
        # 每张表至少一个 PK
        assert len(pks) >= 5

    def test_fk_constraints(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        fks = [
            n for n in graph.nodes_by_type(SchemaNodeType.CONSTRAINT)
            if isinstance(n, ConstraintNode) and n.constraint_type == ConstraintType.FOREIGN_KEY
        ]
        # orders.customer_id → customers.id
        # order_items.order_id → orders.id
        # order_items.product_id → products.id
        assert len(fks) >= 3

    def test_fk_edges(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        ref_edges = [
            e for e in graph.edges
            if e.edge_type == SchemaEdgeType.REFERENCES
        ]
        # 至少 3 条 FK 边
        assert len(ref_edges) >= 3

        # orders → customers
        has_orders_customers = any(
            e.source_id == "dbo.orders" and e.target_id == "dbo.customers"
            for e in ref_edges
        )
        assert has_orders_customers

    def test_topological_sort_valid(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")
        order = graph.topological_sort()

        # customers 应在 orders 之前
        idx_customers = order.index("dbo.customers")
        idx_orders = order.index("dbo.orders")
        assert idx_customers < idx_orders

    def test_migration_waves(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")
        waves = graph.migration_waves()

        # Wave 0 应包含无 FK 依赖的表（products, customers, inventory）
        wave0 = set(waves[0])
        assert "dbo.products" in wave0
        assert "dbo.customers" in wave0

    def test_summary(self):
        from architecture.domain.models import Base
        graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")
        s = graph.summary()

        assert s["tables"] == 5
        assert s["total_nodes"] > 10  # tables + columns + constraints + indexes


class TestTableBuilderFromInspector:
    """使用 mock Inspector 测试。"""

    def test_builds_from_mock_inspector(self):
        inspector = MagicMock()
        inspector.default_schema_name = "dbo"
        inspector.get_table_names.return_value = ["users", "posts"]
        inspector.get_columns.side_effect = lambda t, schema=None: {
            "users": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "name", "type": "VARCHAR(100)", "nullable": False, "default": None},
                {"name": "email", "type": "VARCHAR(200)", "nullable": True, "default": None},
            ],
            "posts": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "user_id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "title", "type": "VARCHAR(200)", "nullable": False, "default": None},
            ],
        }[t]
        inspector.get_pk_constraint.side_effect = lambda t, schema=None: {
            "users": {"constrained_columns": ["id"], "name": "pk_users"},
            "posts": {"constrained_columns": ["id"], "name": "pk_posts"},
        }[t]
        inspector.get_foreign_keys.side_effect = lambda t, schema=None: {
            "users": [],
            "posts": [{
                "name": "fk_posts_user",
                "constrained_columns": ["user_id"],
                "referred_table": "users",
                "referred_schema": "dbo",
                "referred_columns": ["id"],
            }],
        }[t]
        inspector.get_unique_constraints.return_value = []
        inspector.get_indexes.return_value = []

        graph = TableBuilder.from_inspector(inspector)

        assert graph.has_node("dbo.users")
        assert graph.has_node("dbo.posts")
        assert graph.has_node("dbo.users.id")
        assert graph.has_node("dbo.posts.user_id")

        # FK edge
        ref_edges = [e for e in graph.edges if e.edge_type == SchemaEdgeType.REFERENCES]
        assert len(ref_edges) == 1
        assert ref_edges[0].source_id == "dbo.posts"
        assert ref_edges[0].target_id == "dbo.users"


# =========================================================================
# SPBuilder tests
# =========================================================================


class TestSPBuilder:
    def test_from_ir_basic(self):
        from architecture.core.sql.compiler.ir import (
            IRProcedure,
            IRSQL,
            IRVariable,
            VariableScope,
        )

        ir = IRProcedure(
            name="sp_get_product",
            parameters=(
                IRVariable(name="product_id", data_type="INT", scope=VariableScope.PARAMETER),
            ),
            body=(
                IRSQL(sql_text="SELECT * FROM products WHERE id = @product_id"),
            ),
            original_source="CREATE PROCEDURE sp_get_product @product_id INT AS SELECT * FROM products WHERE id = @product_id",
        )

        graph = SPBuilder.from_ir(ir, schema="dbo")

        assert graph.has_node("dbo.sp_get_product")
        node = graph.get_node("dbo.sp_get_product")
        assert isinstance(node, ProcedureNode)
        assert node.language == "tsql"
        assert len(node.parameters) == 1
        assert node.parameters[0]["name"] == "product_id"

    def test_from_ir_with_table_deps(self):
        from architecture.core.sql.compiler.ir import IRProcedure, IRSQL

        ir = IRProcedure(
            name="sp_calc",
            body=(
                IRSQL(sql_text="SELECT total FROM orders WHERE id = 1"),
                IRSQL(sql_text="UPDATE order_items SET qty = 0"),
            ),
        )

        graph = SPBuilder.from_ir(ir, schema="dbo")

        # 应提取到 orders 和 order_items 表依赖
        node = graph.get_node("dbo.sp_calc")
        assert isinstance(node, ProcedureNode)
        assert "orders" in node.referenced_tables or "order_items" in node.referenced_tables

    def test_from_ir_with_exec_calls(self):
        from architecture.core.sql.compiler.ir import IRExec, IRProcedure, IRSQL

        ir_a = IRProcedure(
            name="sp_a",
            body=(
                IRSQL(sql_text="SELECT 1"),
                IRExec(procedure_name="sp_b"),
            ),
        )
        ir_b = IRProcedure(
            name="sp_b",
            body=(
                IRSQL(sql_text="SELECT * FROM products"),
            ),
        )

        graph = SPBuilder.from_ir_list([ir_a, ir_b], schema="dbo")

        # CALLS 边
        calls_edges = [e for e in graph.edges if e.edge_type == SchemaEdgeType.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].source_id == "dbo.sp_a"
        assert calls_edges[0].target_id == "dbo.sp_b"

    def test_from_ir_list_topo_sort(self):
        from architecture.core.sql.compiler.ir import IRExec, IRProcedure, IRSQL

        ir_a = IRProcedure(
            name="sp_a",
            body=(IRExec(procedure_name="sp_b"),),
        )
        ir_b = IRProcedure(
            name="sp_b",
            body=(IRExec(procedure_name="sp_c"),),
        )
        ir_c = IRProcedure(
            name="sp_c",
            body=(IRSQL(sql_text="SELECT 1"),),
        )

        graph = SPBuilder.from_ir_list([ir_a, ir_b, ir_c], schema="dbo")
        order = graph.topological_sort()

        idx_b = order.index("dbo.sp_b")
        idx_a = order.index("dbo.sp_a")
        idx_c = order.index("dbo.sp_c")

        # sp_c 应在 sp_b 之前, sp_b 应在 sp_a 之前
        assert idx_c < idx_b
        assert idx_b < idx_a


# =========================================================================
# End-to-end: TableBuilder + SPBuilder merged graph
# =========================================================================


class TestMergedGraph:
    def test_table_and_sp_combined(self):
        """构建 Table 子图 + SP 子图，合并后做全局分析。"""
        from architecture.core.sql.compiler.ir import IRProcedure, IRSQL
        from architecture.domain.models import Base

        # Table 子图
        table_graph = TableBuilder.from_metadata(Base.metadata, schema="dbo")

        # SP 子图
        ir = IRProcedure(
            name="sp_list_orders",
            body=(
                IRSQL(sql_text="SELECT * FROM orders WHERE status = 'ACTIVE'"),
            ),
        )
        sp_graph = SPBuilder.from_ir(
            ir, schema="dbo",
            known_tables={"orders", "customers", "products", "order_items", "inventory"},
        )

        # 合并
        merged = SchemaGraph()
        for node in table_graph.nodes:
            merged.add_node(node)
        for edge in table_graph.edges:
            merged.add_edge(edge)
        for node in sp_graph.nodes:
            merged.add_node(node)
        for edge in sp_graph.edges:
            merged.add_edge(edge)

        # SP 应在拓扑排序的最后
        order = merged.topological_sort()
        assert "dbo.sp_list_orders" in order

        # impact_report: 如果 orders 表变更，SP 应受影响
        report = merged.impact_report("dbo.orders")
        affected = {p.node_id for p in report.paths}
        assert "dbo.sp_list_orders" in affected
