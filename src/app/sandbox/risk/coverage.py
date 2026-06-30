"""
Coverage Analysis Engine — identifies what's tested and what's missing.

Computes coverage across 3 dimensions:
    1. SQL Coverage — % of SQL types tested (SELECT, JOIN, AGG, WINDOW, CTE, etc.)
    2. API Coverage — % of endpoints tested, business flows covered
    3. ORM Coverage — which ORM patterns are tested, which are missing

Output identifies critical coverage gaps for migration risk assessment.
"""

from __future__ import annotations

from ..test_case import MigrationTestCase, get_all_test_cases
from .schemas import CoverageDimension, CoverageReport


# =========================================================================
# SQL Type Taxonomy — all SQL features that should be tested
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
    "edge": "NULL_HANDLING",  # Default mapping
}


# =========================================================================
# API Endpoint Taxonomy
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


# =========================================================================
# ORM Pattern Taxonomy
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


# =========================================================================
# Coverage Analyzer
# =========================================================================


class CoverageAnalyzer:
    """Analyze migration test coverage across SQL, API, and ORM dimensions.

    Identifies gaps where migration risks are unknown due to missing test coverage.
    """

    @staticmethod
    def analyze(
        test_cases: list[MigrationTestCase] | None = None,
    ) -> CoverageReport:
        """Compute complete coverage analysis.

        Args:
            test_cases: Test cases to analyze (defaults to all predefined)

        Returns:
            CoverageReport with SQL, API, ORM coverage and critical gaps.
        """
        if test_cases is None:
            test_cases = get_all_test_cases()

        sql_coverage = CoverageAnalyzer._sql_coverage(test_cases)
        api_coverage = CoverageAnalyzer._api_coverage(test_cases)
        orm_coverage = CoverageAnalyzer._orm_coverage(test_cases)

        overall = round(
            (sql_coverage.percentage + api_coverage.percentage + orm_coverage.percentage) / 3,
            1,
        )

        # Critical gaps: types with 0% coverage
        critical_gaps: list[str] = []
        for dim_name, dim in [
            ("SQL", sql_coverage),
            ("API", api_coverage),
            ("ORM", orm_coverage),
        ]:
            if dim.percentage < 60:
                missing_summary = ", ".join(dim.missing_items[:3])
                critical_gaps.append(
                    f"{dim_name} 覆盖率不足 ({dim.percentage:.0f}%): 缺失 {missing_summary}"
                )

        return CoverageReport(
            sql_coverage=sql_coverage,
            api_coverage=api_coverage,
            orm_coverage=orm_coverage,
            overall_coverage=overall,
            critical_gaps=critical_gaps,
        )

    @staticmethod
    def _sql_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute SQL type coverage."""
        # Map test tags to SQL types
        covered_types: set[str] = set()
        for tc in test_cases:
            for tag in tc.tags:
                sql_type = SQL_TAG_TO_TYPE.get(tag)
                if sql_type:
                    covered_types.add(sql_type)

            # Category-based coverage
            if tc.category == "sql_join":
                covered_types.add("JOIN")
            elif tc.category == "sql_aggregation":
                covered_types.add("AGGREGATION")
                covered_types.add("GROUP_BY")
            elif tc.category == "sql_crud":
                covered_types.add("SELECT")
            elif tc.category == "schema":
                covered_types.add("SELECT")

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

    @staticmethod
    def _api_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute API endpoint coverage."""
        api_test_endpoints: set[str] = set()
        for tc in test_cases:
            if tc.api_endpoint:
                api_test_endpoints.add(tc.api_endpoint)

        all_endpoints = set(API_TAXONOMY.keys())
        covered = sorted(api_test_endpoints & all_endpoints)
        missing = sorted(all_endpoints - api_test_endpoints)

        total = len(all_endpoints)
        tested = len(covered)
        # API coverage is inherently lower since most tests are SQL-based
        # We rate it based on the 4 most critical endpoints
        critical_endpoints = {
            "/api/business/orders",
            "/api/business/inventory/query",
            "/api/business/customers/list",
            "/api/business/migrate/verify",
        }
        critical_tested = len(api_test_endpoints & critical_endpoints)

        percentage = round(critical_tested / max(len(critical_endpoints), 1) * 100, 1)

        return CoverageDimension(
            name="API Coverage",
            tested=tested,
            total=total,
            percentage=percentage,
            covered_items=[f"{ep} ({API_TAXONOMY.get(ep, ep)})" for ep in covered],
            missing_items=[f"{ep} ({API_TAXONOMY.get(ep, ep)})" for ep in missing],
        )

    @staticmethod
    def _orm_coverage(test_cases: list[MigrationTestCase]) -> CoverageDimension:
        """Compute ORM pattern coverage."""
        covered_patterns: set[str] = set()

        for tc in test_cases:
            cat = tc.category
            tags = tc.tags

            if cat in ("sql_crud", "schema"):
                covered_patterns.add("simple_select")
            if "join" in tags:
                covered_patterns.add("join_select")
            if "left-join" in tags:
                covered_patterns.add("left_join")
            if "aggregation" in tags:
                covered_patterns.add("aggregate_select")
            if "pagination" in tags:
                covered_patterns.add("pagination")
            if "crud" in tags:
                covered_patterns.add("raw_sql")

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
