"""
Test Case Definition Layer — structured, typed migration test cases.

Each test case defines:
- What to test (API, SQL, ORM, schema)
- Expected behavior (row counts, data match, status)
- Expected known differences (if any)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MigrationTestCase:
    """A single migration validation test case.

    Fields:
        id: Unique test identifier (e.g. "create_order")
        name: Human-readable name
        category: Test category — "api", "sql", "orm", "schema", "aggregation"
        description: What this test validates
        source_sql: SQL to execute on source DB (None for API tests)
        target_sql: SQL to execute on target DB (None = same as source)
        api_endpoint: API endpoint path (None for SQL tests)
        api_method: HTTP method for API tests
        api_body: Request body for API tests
        expected_status: "PASS" | "FAIL" | "CONDITIONAL"
        expected_row_match: Whether row counts should match
        expected_data_match: Whether data should match exactly
        tolerance: Field-level numeric tolerance for comparison
        ignore_fields: Fields to exclude from diff
        check_fields: Only check these fields (None = check all)
        known_issues: List of expected differences with explanations
        tags: Labels for filtering (e.g. ["smoke", "regression"])
        risk_tags: Labels for risk analysis
        affected_tables: Tables this test queries (for dependency-based re-execution)
        affected_sql_patterns: SQL patterns used (LIMIT, JOIN, GROUP BY, etc.)
        affected_api: API endpoints called (for API tests)
        affected_orm: ORM patterns used (for ORM tests)
    """
    id: str
    name: str
    category: str
    description: str
    source_sql: str | None = None
    target_sql: str | None = None
    api_endpoint: str | None = None
    api_method: str = "POST"
    api_body: dict[str, Any] | None = None
    expected_status: str = "PASS"  # PASS / FAIL / CONDITIONAL
    expected_row_match: bool = True
    expected_data_match: bool = True
    tolerance: dict[str, float] = field(default_factory=dict)
    ignore_fields: list[str] = field(default_factory=list)
    check_fields: list[str] | None = None
    known_issues: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    affected_tables: list[str] = field(default_factory=list)
    affected_sql_patterns: list[str] = field(default_factory=list)
    affected_api: list[str] = field(default_factory=list)
    affected_orm: list[str] = field(default_factory=list)


# =========================================================================
# Test Case Registry
# =========================================================================


def get_all_test_cases() -> list[MigrationTestCase]:
    """Return all predefined migration test cases.

    Categories:
    - schema: Table structure validation
    - sql_crud: Basic CRUD operations
    - sql_aggregation: GROUP BY, COUNT, SUM
    - sql_join: Multi-table JOIN queries
    - sql_edge: Edge cases (NULL handling, boolean, datetime)
    - api_order: Order creation via API
    - api_inventory: Inventory queries via API
    """
    return [
        # ===== Schema Tests =====
        MigrationTestCase(
            id="schema_table_exists",
            name="所有表存在性验证",
            category="schema",
            description="验证 customers, products, orders, order_items, inventory 五张表均存在",
            source_sql=(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_NAME IN ('customers','products','orders','order_items','inventory') "
                "ORDER BY TABLE_NAME"
            ),
            expected_status="PASS",
            tags=["smoke", "schema"],
            risk_tags=['schema_validation'],
            affected_tables=['customers', 'products', 'orders', 'order_items', 'inventory'],
            affected_sql_patterns=['information_schema', 'metadata_query'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="schema_row_counts",
            name="固定数据集行数验证",
            category="schema",
            description="验证所有表的行数与固定数据集一致",
            source_sql=(
                "SELECT 'customers' AS tbl, COUNT(*) AS cnt FROM customers UNION ALL "
                "SELECT 'products', COUNT(*) FROM products UNION ALL "
                "SELECT 'orders', COUNT(*) FROM orders UNION ALL "
                "SELECT 'order_items', COUNT(*) FROM order_items UNION ALL "
                "SELECT 'inventory', COUNT(*) FROM inventory ORDER BY tbl"
            ),
            expected_status="PASS",
            tags=["smoke", "schema"],
            risk_tags=['schema_validation', 'data_integrity'],
            affected_tables=['customers', 'products', 'orders', 'order_items', 'inventory'],
            affected_sql_patterns=['count', 'union_all', 'aggregation'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== SQL CRUD Tests =====
        MigrationTestCase(
            id="sql_select_all_customers",
            name="查询所有客户",
            category="sql_crud",
            description="验证 SELECT * FROM customers 返回 10 行且数据一致",
            source_sql="SELECT id, code, name, contact, phone, email, is_active FROM customers ORDER BY id",
            expected_status="PASS",
            check_fields=["id", "code", "name", "is_active"],
            tags=["smoke", "crud"],
            risk_tags=['basic_crud', 'datatype_string', 'datatype_boolean'],
            affected_tables=['customers'],
            affected_sql_patterns=['select', 'order_by', 'basic_crud'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_select_all_products",
            name="查询所有产品",
            category="sql_crud",
            description="验证 SELECT * FROM products 返回 10 行且价格精度一致",
            source_sql="SELECT id, code, name, price, is_active FROM products ORDER BY id",
            expected_status="PASS",
            tolerance={"price": 0.01},
            check_fields=["id", "code", "name", "price"],
            tags=["smoke", "crud"],
            risk_tags=['basic_crud', 'datatype_precision', 'numeric_accuracy'],
            affected_tables=['products'],
            affected_sql_patterns=['select', 'order_by', 'numeric_precision'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_select_all_orders",
            name="查询所有订单",
            category="sql_crud",
            description="验证 SELECT * FROM orders 返回 20 行，金额精度一致",
            source_sql="SELECT id, order_no, customer_id, status, total_amount, item_count, notes FROM orders ORDER BY id",
            expected_status="PASS",
            tolerance={"total_amount": 0.01},
            check_fields=["id", "order_no", "customer_id", "status", "item_count"],
            tags=["crud"],
            risk_tags=['basic_crud', 'datatype_precision', 'null_handling'],
            affected_tables=['orders'],
            affected_sql_patterns=['select', 'order_by', 'numeric_precision', 'null_handling'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_select_with_null",
            name="NULL 值处理验证",
            category="sql_edge",
            description="验证 NULL contact/phone/email 在各数据库中一致",
            source_sql=(
                "SELECT id, code, contact, phone, email FROM customers "
                "WHERE contact IS NULL OR phone IS NULL OR email IS NULL ORDER BY id"
            ),
            expected_status="PASS",
            tags=["edge", "null-handling"],
            risk_tags=['null_handling', 'edge_case', 'datatype_string'],
            affected_tables=['customers'],
            affected_sql_patterns=['select', 'null_handling', 'is_null'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_select_null_notes",
            name="NULL notes 字段验证",
            category="sql_edge",
            description="验证 orders.notes 中 NULL 值的处理一致性",
            source_sql=(
                "SELECT id, order_no, notes FROM orders "
                "WHERE notes IS NULL ORDER BY id"
            ),
            expected_status="PASS",
            tags=["edge", "null-handling"],
            risk_tags=['null_handling', 'edge_case', 'datatype_string'],
            affected_tables=['orders'],
            affected_sql_patterns=['select', 'null_handling', 'is_null'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_boolean_filter",
            name="布尔字段过滤",
            category="sql_edge",
            description="验证 is_active 布尔过滤在各数据库中的行为",
            source_sql="SELECT COUNT(*) AS active_count FROM customers WHERE is_active = 1",
            expected_status="PASS",
            known_issues=[
                "KingbaseES may use 't'/'f' for boolean representation",
                "DM8 may use 1/0 or Y/N for boolean representation",
            ],
            tags=["edge", "boolean"],
            risk_tags=['datatype_boolean', 'edge_case', 'dialect_specific'],
            affected_tables=['customers'],
            affected_sql_patterns=['select', 'count', 'boolean_filter', 'dialect_specific'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_string_filter",
            name="字符串 LIKE 模糊匹配",
            category="sql_crud",
            description="验证 LIKE 模糊查询在各数据库中的一致性",
            source_sql=(
                "SELECT id, code, name FROM customers "
                "WHERE name LIKE '%科技%' ORDER BY id"
            ),
            expected_status="CONDITIONAL",
            known_issues=[
                "MSSQL NVARCHAR 列 LIKE 需要 N 前缀才能匹配 Unicode 字符",
                "KingbaseES 无需 N 前缀即可匹配",
            ],
            tags=["crud", "collation"],
            risk_tags=['collation', 'string_function', 'like_pattern', 'nvarchar_prefix'],
            affected_tables=['customers'],
            affected_sql_patterns=['select', 'like', 'collation', 'string_function', 'nvarchar_prefix'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== Aggregation Tests =====
        MigrationTestCase(
            id="sql_count_by_status",
            name="按状态分组计数",
            category="sql_aggregation",
            description="验证 GROUP BY + COUNT 聚合结果一致性",
            source_sql=(
                "SELECT status, COUNT(*) AS cnt FROM orders "
                "GROUP BY status ORDER BY status"
            ),
            expected_status="PASS",
            tags=["aggregation", "group-by"],
            risk_tags=['aggregation', 'group_by', 'sql_complexity'],
            affected_tables=['orders'],
            affected_sql_patterns=['group_by', 'count', 'aggregation'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_sum_order_totals",
            name="订单金额汇总",
            category="sql_aggregation",
            description="验证 SUM() 数值聚合精度一致性",
            source_sql=(
                "SELECT customer_id, COUNT(*) AS order_count, "
                "SUM(total_amount) AS total_spent "
                "FROM orders GROUP BY customer_id ORDER BY customer_id"
            ),
            expected_status="PASS",
            tolerance={"total_spent": 0.02},
            tags=["aggregation", "numeric-precision"],
            risk_tags=['aggregation', 'group_by', 'numeric_accuracy', 'sql_complexity'],
            affected_tables=['orders'],
            affected_sql_patterns=['group_by', 'sum', 'aggregation', 'numeric_precision'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_order_by_customer",
            name="按客户统计订单数",
            category="sql_aggregation",
            description="验证分组后的排序一致性",
            source_sql=(
                "SELECT c.id, c.code, c.name, COUNT(o.id) AS order_count "
                "FROM customers c LEFT JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.id, c.code, c.name ORDER BY order_count DESC, c.id"
            ),
            expected_status="PASS",
            tags=["aggregation", "join"],
            risk_tags=['aggregation', 'join_syntax', 'group_by', 'sql_complexity'],
            affected_tables=['customers', 'orders'],
            affected_sql_patterns=['left_join', 'group_by', 'count', 'order_by', 'join_syntax'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== JOIN Tests =====
        MigrationTestCase(
            id="sql_join_orders_items",
            name="订单-明细关联查询",
            category="sql_join",
            description="验证 INNER JOIN orders + order_items 数据一致性",
            source_sql=(
                "SELECT o.id AS order_id, o.order_no, COUNT(oi.id) AS item_count, "
                "SUM(oi.subtotal) AS calc_total "
                "FROM orders o JOIN order_items oi ON o.id = oi.order_id "
                "GROUP BY o.id, o.order_no ORDER BY o.id"
            ),
            expected_status="PASS",
            tolerance={"calc_total": 0.02},
            tags=["join", "aggregation"],
            risk_tags=['join_syntax', 'aggregation', 'multi_table', 'sql_complexity'],
            affected_tables=['orders', 'order_items'],
            affected_sql_patterns=['inner_join', 'group_by', 'sum', 'aggregation', 'join_syntax'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_join_customer_orders",
            name="客户订单左连接",
            category="sql_join",
            description="验证 LEFT JOIN customers + orders（含无订单客户）",
            source_sql=(
                "SELECT c.id, c.code, c.name, COUNT(o.id) AS order_count "
                "FROM customers c LEFT JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.id, c.code, c.name ORDER BY c.id"
            ),
            expected_status="PASS",
            tags=["join", "left-join"],
            risk_tags=['join_syntax', 'left_join', 'null_handling', 'aggregation'],
            affected_tables=['customers', 'orders'],
            affected_sql_patterns=['left_join', 'group_by', 'count', 'join_syntax'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_three_way_join",
            name="三表关联查询（客户-订单-产品）",
            category="sql_join",
            description="验证 customers + orders + order_items + products 四表 JOIN",
            source_sql=(
                "SELECT c.name AS customer_name, o.order_no, p.name AS product_name, "
                "oi.quantity, oi.unit_price, oi.subtotal "
                "FROM customers c "
                "JOIN orders o ON c.id = o.customer_id "
                "JOIN order_items oi ON o.id = oi.order_id "
                "JOIN products p ON oi.product_id = p.id "
                "ORDER BY o.id, oi.id"
            ),
            expected_status="PASS",
            tags=["join", "multi-table"],
            risk_tags=['join_syntax', 'multi_table', 'sql_complexity', 'join_heavy'],
            affected_tables=['customers', 'orders', 'order_items', 'products'],
            affected_sql_patterns=['inner_join', 'multi_join', 'join_syntax', 'order_by'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== Inventory Tests =====
        MigrationTestCase(
            id="sql_inventory_all",
            name="全部库存查询",
            category="sql_crud",
            description="验证库存表查询结果一致性",
            source_sql=(
                "SELECT inv.id, p.code AS product_code, p.name AS product_name, "
                "inv.warehouse, inv.quantity, inv.min_quantity "
                "FROM inventory inv JOIN products p ON inv.product_id = p.id "
                "ORDER BY inv.id"
            ),
            expected_status="PASS",
            tags=["inventory"],
            risk_tags=['basic_crud', 'join_syntax', 'datatype_integer'],
            affected_tables=['inventory', 'products'],
            affected_sql_patterns=['select', 'inner_join', 'order_by'],
            affected_api=[],
            affected_orm=[],
        ),

        MigrationTestCase(
            id="sql_low_stock",
            name="低库存告警查询",
            category="sql_edge",
            description="验证 quantity < min_quantity 的库存告警查询",
            source_sql=(
                "SELECT p.code, p.name, inv.warehouse, inv.quantity, inv.min_quantity "
                "FROM inventory inv JOIN products p ON inv.product_id = p.id "
                "WHERE inv.quantity < inv.min_quantity ORDER BY inv.id"
            ),
            expected_status="PASS",
            tags=["inventory", "edge"],
            risk_tags=['edge_case', 'numeric_comparison', 'comparison_operator'],
            affected_tables=['inventory', 'products'],
            affected_sql_patterns=['select', 'inner_join', 'numeric_comparison', 'edge_case'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== Date/Time Tests =====
        MigrationTestCase(
            id="sql_datetime_default",
            name="DateTime 默认值验证",
            category="sql_edge",
            description="验证 created_at 的 server_default 行为",
            source_sql=(
                "SELECT id, code, created_at FROM customers "
                "WHERE created_at IS NOT NULL ORDER BY id"
            ),
            expected_status="PASS",
            # created_at uses server_default=func.now() so exact values will differ
            ignore_fields=["created_at"],
            tags=["edge", "datetime"],
            risk_tags=['datatype_datetime', 'default_value', 'edge_case'],
            affected_tables=['customers'],
            affected_sql_patterns=['select', 'datetime', 'default_value', 'is_not_null'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== Price/Decimal Tests =====
        MigrationTestCase(
            id="sql_expensive_products",
            name="高价产品过滤",
            category="sql_edge",
            description="验证 Numeric 类型的 > 比较精度一致性",
            source_sql=(
                "SELECT id, code, name, price FROM products "
                "WHERE price > 50000 ORDER BY price DESC"
            ),
            expected_status="PASS",
            tolerance={"price": 0.01},
            tags=["numeric-precision"],
            risk_tags=['numeric_comparison', 'datatype_precision', 'edge_case'],
            affected_tables=['products'],
            affected_sql_patterns=['select', 'numeric_comparison', 'order_by', 'edge_case'],
            affected_api=[],
            affected_orm=[],
        ),

        # ===== Pagination Tests =====
        MigrationTestCase(
            id="sql_pagination_orders",
            name="订单分页查询",
            category="sql_crud",
            description="验证 LIMIT/OFFSET 分页行为一致性",
            source_sql="SELECT id, order_no, status FROM orders ORDER BY id OFFSET 5 ROWS FETCH NEXT 5 ROWS ONLY",
            target_sql="SELECT id, order_no, status FROM orders ORDER BY id OFFSET 5 LIMIT 5",
            expected_status="PASS",
            tags=["pagination"],
            risk_tags=['pagination', 'dialect_specific', 'limit_offset'],
            affected_tables=['orders'],
            affected_sql_patterns=['select', 'order_by', 'pagination', 'limit_offset', 'fetch_next', 'dialect_specific'],
            affected_api=[],
            affected_orm=[],
        ),

        # =====================================================================
        # Business Flow Tests — 端到端业务流验证
        # =====================================================================
        # Each flow covers the full chain: API → ORM → SQL → DB → Reverse Verify
        # These feed the business_flow dimension in CertificationCoverageReport.

        MigrationTestCase(
            id="bf_customer_create",
            name="客户创建流程 (API→ORM→SQL→验证)",
            category="business_flow",
            description="端到端客户创建: API创建→ORM持久化→SQL查询验证→反向验证",
            source_sql=(
                "SELECT id, code, name, contact, phone, email, is_active "
                "FROM customers WHERE code = 'C901' ORDER BY id"
            ),
            expected_status="CONDITIONAL",
            known_issues=[
                "需要在sandbox中预先创建C901客户以验证完整流程",
            ],
            tags=["business_flow", "create-flow"],
            risk_tags=["business_flow", "create_flow"],
            affected_tables=["customers"],
            affected_api=["/api/business/customers/create"],
            affected_orm=["CustomerRepository.create"],
            affected_sql_patterns=["select", "insert"],
        ),

        MigrationTestCase(
            id="bf_product_create",
            name="产品创建流程 (API→ORM→SQL→验证)",
            category="business_flow",
            description="端到端产品创建: API创建→ORM持久化→SQL查询验证→反向验证",
            source_sql=(
                "SELECT id, code, name, price, is_active "
                "FROM products WHERE code = 'P901' ORDER BY id"
            ),
            expected_status="CONDITIONAL",
            known_issues=[
                "需要在sandbox中预先创建P901产品以验证完整流程",
            ],
            tags=["business_flow", "create-flow"],
            risk_tags=["business_flow", "create_flow"],
            affected_tables=["products"],
            affected_api=["/api/business/products/create"],
            affected_orm=["ProductRepository.create"],
            affected_sql_patterns=["select", "insert"],
        ),

        MigrationTestCase(
            id="bf_order_create_full",
            name="订单创建完整流程 (多表JOIN验证)",
            category="business_flow",
            description="完整订单创建链: API创建→ORM写入订单+明细→SQL多表JOIN→反向验证",
            source_sql=(
                "SELECT o.order_no, c.name AS customer_name, p.code AS product_code, "
                "oi.quantity, oi.unit_price, oi.subtotal, o.total_amount "
                "FROM orders o "
                "JOIN customers c ON o.customer_id = c.id "
                "JOIN order_items oi ON o.id = oi.order_id "
                "JOIN products p ON oi.product_id = p.id "
                "WHERE o.order_no = 'ORD-2025-0901' ORDER BY oi.id"
            ),
            expected_status="CONDITIONAL",
            tolerance={"subtotal": 0.02, "total_amount": 0.02},
            known_issues=[
                "需要在sandbox中预先创建测试订单以验证完整JOIN链路",
                "MSSQL中金额Numeric精度可能与KingbaseES/DM不同",
            ],
            tags=["business_flow", "order-flow", "multi-table", "join"],
            risk_tags=["business_flow", "order_flow", "multi_table_join"],
            affected_tables=["customers", "orders", "order_items", "products"],
            affected_api=["/api/business/orders"],
            affected_orm=["OrderRepository.create", "OrderItemRepository.create"],
            affected_sql_patterns=["select", "inner_join", "multi_join", "join_syntax"],
        ),

        MigrationTestCase(
            id="bf_order_update",
            name="订单更新流程 (API→ORM→UPDATE→验证)",
            category="business_flow",
            description="订单状态更新链: API更新→ORM持久化→SQL查询验证→反向验证",
            source_sql=(
                "SELECT id, order_no, status, total_amount "
                "FROM orders WHERE order_no = 'ORD-2025-0001' ORDER BY id"
            ),
            expected_status="PASS",
            tags=["business_flow", "update-flow"],
            risk_tags=["business_flow", "update_flow"],
            affected_tables=["orders"],
            affected_api=["/api/business/orders"],
            affected_orm=["OrderRepository.update"],
            affected_sql_patterns=["select", "update"],
        ),

        MigrationTestCase(
            id="bf_inventory_query",
            name="库存查询流程 (API→ORM→SELECT→告警验证)",
            category="business_flow",
            description="库存管理链: API查询→ORM查询→SQL查询→低库存告警→反向验证",
            source_sql=(
                "SELECT p.code AS product_code, p.name AS product_name, "
                "inv.warehouse, inv.quantity, inv.min_quantity "
                "FROM inventory inv "
                "JOIN products p ON inv.product_id = p.id "
                "WHERE inv.quantity < inv.min_quantity ORDER BY inv.id"
            ),
            expected_status="PASS",
            tags=["business_flow", "inventory-flow"],
            risk_tags=["business_flow", "inventory_flow", "low_stock_alert"],
            affected_tables=["inventory", "products"],
            affected_api=["/api/business/inventory/query"],
            affected_orm=["InventoryRepository.find_by_product"],
            affected_sql_patterns=["select", "inner_join", "numeric_comparison"],
        ),

        MigrationTestCase(
            id="bf_customer_orders_report",
            name="客户订单报表 (跨流JOIN验证)",
            category="business_flow",
            description="跨业务流验证: 客户→订单→明细→产品四表关联+聚合",
            source_sql=(
                "SELECT c.code AS customer_code, c.name AS customer_name, "
                "COUNT(o.id) AS order_count, "
                "COALESCE(SUM(o.total_amount), 0) AS total_spent "
                "FROM customers c "
                "LEFT JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.code, c.name ORDER BY total_spent DESC, c.code"
            ),
            expected_status="PASS",
            tolerance={"total_spent": 0.05},
            tags=["business_flow", "order-flow", "left-join", "aggregation"],
            risk_tags=["business_flow", "cross_flow", "aggregation", "left_join"],
            affected_tables=["customers", "orders"],
            affected_api=["/api/business/reports/customer-orders"],
            affected_orm=[
                "CustomerRepository.get",
                "OrderRepository.find_by_customer",
            ],
            affected_sql_patterns=[
                "select", "left_join", "group_by", "count", "sum",
                "aggregation", "order_by",
            ],
        ),
    ]
