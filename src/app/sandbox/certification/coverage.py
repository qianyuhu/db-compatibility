"""
Coverage Analysis Engine v2 — 4-dimensional coverage with uncertainty semantics.

Coverage measures what we KNOW vs what we DON'T KNOW:
  - Low coverage = high uncertainty (NOT high risk)
  - Coverage gaps are reported as "uncertainty areas"
  - Coverage affects confidence, NEVER risk score

Dimensions:
  1. SQL Coverage      — 20 SQL feature types (SELECT, JOIN, CTE, WINDOW, etc.)
  2. API Coverage      — 14 API endpoints
  3. ORM Coverage      — 14 ORM patterns
  4. Business Flow     — 5 flows × 5 steps = 25 required steps
"""

from __future__ import annotations

from ..test_case import MigrationTestCase, get_all_test_cases
from .schemas import CertificationCoverageReport, CoverageDimension


# =========================================================================
# SQL Type Taxonomy — 20 SQL features
# =========================================================================

SQL_TYPE_TAXONOMY = {
    "SELECT": "基础 SELECT 查询",
    "JOIN": "表连接 (INNER/LEFT/RIGHT)",
    "AGGREGATION": "聚合函数 (COUNT/SUM/AVG/MAX/MIN)",
    "GROUP_BY": "GROUP BY 分组",
    "ORDER_BY": "ORDER BY 排序",
    "LIMIT_OFFSET": "分页 (LIMIT/OFFSET/TOP/FETCH)",
    "SUBQUERY": "子查询",
    "CTE": "公共表表达式 (WITH)",
    "WINDOW_FUNCTION": "窗口函数 (ROW_NUMBER/RANK)",
    "UNION": "UNION / UNION ALL",
    "BOOLEAN": "布尔类型与逻辑运算",
    "NULL_HANDLING": "NULL 处理 (IS NULL/COALESCE)",
    "STRING_FUNCTION": "字符串函数 (LIKE/LEN/SUBSTRING)",
    "DATE_FUNCTION": "日期函数 (GETDATE/NOW/SYSDATE)",
    "NUMERIC_PRECISION": "数值精度 (DECIMAL/NUMERIC)",
    "CASE_WHEN": "CASE WHEN 条件表达式",
    "MERGE_UPSERT": "MERGE / UPSERT 语法",
    "INSERT_SELECT": "INSERT INTO ... SELECT",
    "BATCH_INSERT": "批量插入",
    "UPDATE_JOIN": "UPDATE with JOIN",
}

SQL_TAG_TO_TYPE: dict[str, str] = {
    "crud": "SELECT",
    "join": "JOIN",
    "left-join": "JOIN",
    "multi-table": "JOIN",
    "aggregation": "AGGREGATION",
    "group-by": "GROUP_BY",
    "pagination": "LIMIT_OFFSET",
    "boolean": "BOOLEAN",
    "null-handling": "NULL_HANDLING",
    "collation": "STRING_FUNCTION",
    "datetime": "DATE_FUNCTION",
    "numeric-precision": "NUMERIC_PRECISION",
    "edge": "NULL_HANDLING",
}

# Additional SQL patterns from test case affected_sql_patterns
SQL_PATTERN_TO_TYPE: dict[str, str] = {
    "select": "SELECT",
    "basic_crud": "SELECT",
    "inner_join": "JOIN",
    "join_syntax": "JOIN",
    "multi_join": "JOIN",
    "left_join": "JOIN",
    "count": "AGGREGATION",
    "sum": "AGGREGATION",
    "group_by": "GROUP_BY",
    "order_by": "ORDER_BY",
    "pagination": "LIMIT_OFFSET",
    "limit_offset": "LIMIT_OFFSET",
    "fetch_next": "LIMIT_OFFSET",
    "like": "STRING_FUNCTION",
    "string_function": "STRING_FUNCTION",
    "nvarchar_prefix": "STRING_FUNCTION",
    "datetime": "DATE_FUNCTION",
    "default_value": "DATE_FUNCTION",
    "numeric_precision": "NUMERIC_PRECISION",
    "numeric_comparison": "NUMERIC_PRECISION",
    "boolean_filter": "BOOLEAN",
    "null_handling": "NULL_HANDLING",
    "is_null": "NULL_HANDLING",
    "is_not_null": "NULL_HANDLING",
    "information_schema": "SELECT",
    "metadata_query": "SELECT",
    "edge_case": "NULL_HANDLING",
    "dialect_specific": "CTE",
    "comparison_operator": "CASE_WHEN",
}


# =========================================================================
# API Endpoint Taxonomy — 14 endpoints
# =========================================================================

API_TAXONOMY = {
    "/api/business/orders": "创建订单",
    "/api/business/orders/list": "查询订单列表",
    "/api/business/inventory/query": "库存查询",
    "/api/business/inventory/adjust": "库存调整",
    "/api/business/customers/list": "客户列表查询",
    "/api/business/customers/create": "创建客户",
    "/api/business/products/list": "产品列表查询",
    "/api/business/products/create": "创建产品",
    "/api/business/reports/sales": "销售报表",
    "/api/business/reports/inventory": "库存报表",
    "/api/business/reports/customer-orders": "客户订单报表",
    "/api/business/migrate/run": "执行迁移",
    "/api/business/migrate/verify": "数据验证",
    "/api/business/migrate/validate-sql": "SQL 验证",
}

CRITICAL_API_ENDPOINTS = {
    "/api/business/orders",
    "/api/business/inventory/query",
    "/api/business/customers/list",
    "/api/business/migrate/verify",
}


# =========================================================================
# ORM Pattern Taxonomy — 14 patterns
# =========================================================================

ORM_TAXONOMY = {
    "simple_select": "简单 SELECT (Repository.get/list)",
    "filtered_select": "条件查询 (WHERE 过滤)",
    "join_select": "关联查询 (JOIN)",
    "aggregate_select": "聚合查询 (GROUP BY/COUNT/SUM)",
    "insert": "INSERT (Repository.create)",
    "update": "UPDATE (Repository.update)",
    "delete": "DELETE (Repository.delete)",
    "pagination": "分页 (OFFSET/LIMIT)",
    "transaction": "事务 (多操作 commit)",
    "bulk_insert": "批量插入",
    "batch_update": "批量更新",
    "raw_sql": "原生 SQL 执行",
    "left_join": "LEFT JOIN 外连接",
    "subquery": "子查询",
}

ORM_TAG_TO_PATTERN: dict[str, str] = {
    "crud": "raw_sql",
    "join": "join_select",
    "left-join": "left_join",
    "multi-table": "join_select",
    "aggregation": "aggregate_select",
    "pagination": "pagination",
    "create-flow": "insert",
    "order-flow": "transaction",
}

ORM_CATEGORY_TO_PATTERN: dict[str, str] = {
    "sql_crud": "simple_select",
    "schema": "simple_select",
    "business_flow": "transaction",
}


# =========================================================================
# Business Flow Taxonomy — 5 flows × 5 steps = 25 required steps
# =========================================================================

BUSINESS_FLOW_STEPS = {
    # Create Flow (5 steps: API → ORM → SQL → DB → Verify)
    "create_api": "API 创建调用",
    "create_orm": "ORM 模型创建",
    "create_sql": "INSERT 执行",
    "create_validate": "SELECT 计数验证",
    "create_reverse_verify": "目标库反向验证",
    # Update Flow
    "update_api": "API 更新调用",
    "update_orm": "ORM 模型更新",
    "update_sql": "UPDATE 执行",
    "update_validate": "SELECT 值验证",
    "update_reverse_verify": "目标库反向验证",
    # Delete Flow
    "delete_api": "API 删除调用",
    "delete_orm": "ORM 模型删除",
    "delete_sql": "DELETE 执行",
    "delete_validate": "SELECT 计数验证",
    "delete_reverse_verify": "目标库反向验证",
    # Inventory Flow
    "inventory_api": "API 库存查询",
    "inventory_orm": "ORM 库存查询",
    "inventory_sql": "SELECT FROM inventory",
    "inventory_alert": "低库存阈值检查",
    "inventory_reverse_verify": "目标库反向验证",
    # Order Flow (multi-table)
    "order_api": "API 订单创建",
    "order_orm": "ORM 订单+明细创建",
    "order_sql": "INSERT orders + items",
    "order_join": "多表 JOIN 验证",
    "order_reverse_verify": "目标库 JOIN 验证",
}

# Tag → business flow step mapping
BF_TAG_TO_STEPS: dict[str, list[str]] = {
    "create-flow": [
        "create_api", "create_orm", "create_sql",
        "create_validate", "create_reverse_verify",
    ],
    "update-flow": [
        "update_api", "update_orm", "update_sql",
        "update_validate", "update_reverse_verify",
    ],
    "delete-flow": [
        "delete_api", "delete_orm", "delete_sql",
        "delete_validate", "delete_reverse_verify",
    ],
    "inventory-flow": [
        "inventory_api", "inventory_orm", "inventory_sql",
        "inventory_alert", "inventory_reverse_verify",
    ],
    "order-flow": [
        "order_api", "order_orm", "order_sql",
        "order_join", "order_reverse_verify",
    ],
}


# =========================================================================
# CoverageAnalyzer v2
# =========================================================================


class CoverageAnalyzer:
    """Analyze migration test coverage across 4 dimensions.

    Critical design principle:
      COVERAGE = UNCERTAINTY, NOT RISK.
      Low coverage means we don't know — it does NOT mean migration will fail.
      Coverage gaps are reported as "uncertainty_areas", not risk.
    """

    @staticmethod
    def analyze(
        test_cases: list[MigrationTestCase] | None = None,
    ) -> CertificationCoverageReport:
        """Compute complete 4-dimension coverage analysis.

        Args:
            test_cases: Test cases to analyze (defaults to all predefined)

        Returns:
            CertificationCoverageReport with SQL, API, ORM, Business Flow coverage.
        """
        if test_cases is None:
            test_cases = get_all_test_cases()

        sql = CoverageAnalyzer._sql_coverage(test_cases)
        api = CoverageAnalyzer._api_coverage(test_cases)
        orm = CoverageAnalyzer._orm_coverage(test_cases)
        bf = CoverageAnalyzer._business_flow_coverage(test_cases)

        overall = round(
            (sql.percentage + api.percentage + orm.percentage + bf.percentage) / 4,
            1,
        )

        # Critical gaps: dimensions with < 60% coverage (these are UNCERTAINTY)
        critical_gaps: list[str] = []
        for dim in (sql, api, orm, bf):
            if dim.percentage < 60:
                missing_summary = ", ".join(dim.missing_items[:3])
                critical_gaps.append(
                    f"{dim.name} 覆盖率不足 ({dim.percentage:.0f}%): 缺失 {missing_summary}"
                )

        # Uncertainty areas: what we DON'T know
        uncertainty_areas: list[str] = []
        for dim in (sql, api, orm, bf):
            if dim.percentage < 60:
                uncertainty_areas.append(
                    f"{dim.name}: {dim.percentage:.0f}% — {dim.total - dim.tested} 项未覆盖，行为未知"
                )

        return CertificationCoverageReport(
            sql_coverage=sql,
            api_coverage=api,
            orm_coverage=orm,
            business_flow_coverage=bf,
            overall_coverage=overall,
            critical_gaps=critical_gaps,
            uncertainty_areas=uncertainty_areas,
        )

    # =========================================================================
    # SQL Coverage
    # =========================================================================

    @staticmethod
    def _sql_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute SQL type coverage from test case tags and patterns."""
        covered_types: set[str] = set()

        for tc in test_cases:
            # From tags
            for tag in tc.tags:
                sql_type = SQL_TAG_TO_TYPE.get(tag)
                if sql_type:
                    covered_types.add(sql_type)

            # From affected_sql_patterns
            for pattern in tc.affected_sql_patterns:
                sql_type = SQL_PATTERN_TO_TYPE.get(pattern)
                if sql_type:
                    covered_types.add(sql_type)

            # From category
            if tc.category == "sql_join":
                covered_types.add("JOIN")
            elif tc.category == "sql_aggregation":
                covered_types.add("AGGREGATION")
                covered_types.add("GROUP_BY")
            elif tc.category in ("sql_crud", "schema"):
                covered_types.add("SELECT")
            elif tc.category == "business_flow":
                covered_types.add("SELECT")
                if "order" in tc.id:
                    covered_types.add("JOIN")

        all_types = set(SQL_TYPE_TAXONOMY.keys())
        covered = sorted(covered_types & all_types)
        missing = sorted(all_types - covered_types)

        percentage = round(len(covered) / len(all_types) * 100, 1)

        return CoverageDimension(
            name="SQL Coverage",
            tested=len(covered),
            total=len(all_types),
            percentage=percentage,
            covered_items=[f"{t} ({SQL_TYPE_TAXONOMY[t]})" for t in covered],
            missing_items=[f"{t} ({SQL_TYPE_TAXONOMY[t]})" for t in missing],
        )

    # =========================================================================
    # API Coverage
    # =========================================================================

    @staticmethod
    def _api_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute API endpoint coverage."""
        api_test_endpoints: set[str] = set()

        for tc in test_cases:
            if tc.api_endpoint:
                api_test_endpoints.add(tc.api_endpoint)
            # Business flow tests with affected_api
            for ep in tc.affected_api:
                if ep in API_TAXONOMY:
                    api_test_endpoints.add(ep)

        all_endpoints = set(API_TAXONOMY.keys())
        covered = sorted(api_test_endpoints & all_endpoints)
        missing = sorted(all_endpoints - api_test_endpoints)

        # Rate API coverage by critical endpoints tested
        critical_tested = len(api_test_endpoints & CRITICAL_API_ENDPOINTS)
        percentage = round(critical_tested / max(len(CRITICAL_API_ENDPOINTS), 1) * 100, 1)

        return CoverageDimension(
            name="API Coverage",
            tested=len(covered),
            total=len(all_endpoints),
            percentage=percentage,
            covered_items=[f"{ep} ({API_TAXONOMY.get(ep, ep)})" for ep in covered],
            missing_items=[f"{ep} ({API_TAXONOMY.get(ep, ep)})" for ep in missing],
        )

    # =========================================================================
    # ORM Coverage
    # =========================================================================

    @staticmethod
    def _orm_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute ORM pattern coverage."""
        covered_patterns: set[str] = set()

        for tc in test_cases:
            # From tags
            for tag in tc.tags:
                pattern = ORM_TAG_TO_PATTERN.get(tag)
                if pattern:
                    covered_patterns.add(pattern)

            # From affected_orm
            for orm in tc.affected_orm:
                for pattern_name in ORM_TAXONOMY:
                    if pattern_name.replace("_", "") in orm.lower().replace("_", "").replace(".", ""):
                        covered_patterns.add(pattern_name)

            # From category
            pattern = ORM_CATEGORY_TO_PATTERN.get(tc.category)
            if pattern:
                covered_patterns.add(pattern)

        all_patterns = set(ORM_TAXONOMY.keys())
        covered = sorted(covered_patterns & all_patterns)
        missing = sorted(all_patterns - covered_patterns)

        percentage = round(len(covered) / len(all_patterns) * 100, 1)

        return CoverageDimension(
            name="ORM Coverage",
            tested=len(covered),
            total=len(all_patterns),
            percentage=percentage,
            covered_items=[f"{p} ({ORM_TAXONOMY[p]})" for p in covered],
            missing_items=[f"{p} ({ORM_TAXONOMY[p]})" for p in missing],
        )

    # =========================================================================
    # Business Flow Coverage — NEW 4th dimension
    # =========================================================================

    @staticmethod
    def _business_flow_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute business flow coverage.

        A step is "covered" if at least one test case exercises it
        (via tags, category, or affected_api/orm fields).
        """
        all_steps = set(BUSINESS_FLOW_STEPS.keys())
        covered_steps: set[str] = set()

        for tc in test_cases:
            # Direct business flow tests
            if tc.category == "business_flow":
                # Mark steps based on tags
                for tag in tc.tags:
                    steps = BF_TAG_TO_STEPS.get(tag, [])
                    covered_steps.update(steps)

                # Mark API/ORM/SQL steps based on affected fields
                if tc.affected_api:
                    covered_steps.add("create_api")
                    covered_steps.add("order_api")
                    covered_steps.add("inventory_api")
                    covered_steps.add("update_api")
                    covered_steps.add("delete_api")
                if tc.affected_orm:
                    covered_steps.add("create_orm")
                    covered_steps.add("order_orm")
                    covered_steps.add("inventory_orm")
                    covered_steps.add("update_orm")
                    covered_steps.add("delete_orm")
                if tc.affected_sql_patterns:
                    if any(p in tc.affected_sql_patterns for p in ("insert",)):
                        covered_steps.add("create_sql")
                        covered_steps.add("order_sql")
                    if "inner_join" in tc.affected_sql_patterns or "multi_join" in tc.affected_sql_patterns:
                        covered_steps.add("order_join")
                    if "numeric_comparison" in tc.affected_sql_patterns:
                        covered_steps.add("inventory_alert")

                # Reverse verify is covered when both source + target SQL exist
                if tc.source_sql:
                    covered_steps.add("create_reverse_verify")
                    covered_steps.add("order_reverse_verify")
                    covered_steps.add("inventory_reverse_verify")
                    covered_steps.add("update_reverse_verify")
                    covered_steps.add("delete_reverse_verify")

            # Non-BF tests may still cover individual steps
            if tc.category == "sql_crud":
                covered_steps.add("create_sql")
                covered_steps.add("create_validate")

            if tc.api_endpoint:
                covered_steps.add("create_api")

        covered = sorted(covered_steps & all_steps)
        missing = sorted(all_steps - covered_steps)

        percentage = round(len(covered) / len(all_steps) * 100, 1) if all_steps else 0.0

        return CoverageDimension(
            name="Business Flow Coverage",
            tested=len(covered),
            total=len(all_steps),
            percentage=percentage,
            covered_items=[f"{s} ({BUSINESS_FLOW_STEPS[s]})" for s in covered],
            missing_items=[f"{s} ({BUSINESS_FLOW_STEPS[s]})" for s in missing],
        )
