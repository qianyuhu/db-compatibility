"""
Migration Difficulties Adaptation Test

Runs representative SQL from each of the 25 difficulty categories through:
1. SQL Classifier (diagnostics) — what features are detected?
2. SQL Rewrite Engine (mssql → kingbasees) — what can be auto-rewritten?

Reports: detection rate, rewrite coverage, confidence scores, and gaps.
"""

import sys
import os
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.core.sql_compatibility_engine.classifier import classify_sql, SqlCategory
from architecture.core.sql.rewrite.engine import rewrite_sql


# ===========================================================================
# Representative SQL from each difficulty category
# ===========================================================================

DIFFICULTY_CASES: list[dict] = [
    # --- Category 1: UPDATE FROM with JOIN [HARD] ---
    {
        "id": "1.1",
        "category": "UPDATE FROM with JOIN",
        "difficulty": "HARD",
        "sql": """UPDATE o SET o.discount_amount = o.total_amount * 0.05
FROM dbo.[Order] o INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE c.tier = 'A' AND o.status = N'待付款'""",
    },
    {
        "id": "1.3",
        "category": "UPDATE FROM + OUTPUT + JOIN",
        "difficulty": "BLOCKER",
        "sql": """UPDATE o SET o.status = N'已发货', o.updated_at = SYSDATETIME()
OUTPUT o.order_id, deleted.status AS old_status, inserted.status AS new_status
FROM dbo.[Order] o INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.status = N'已付款'""",
    },
    # --- Category 2: DELETE with JOIN [HARD] ---
    {
        "id": "2.1",
        "category": "DELETE with JOIN",
        "difficulty": "HARD",
        "sql": """DELETE oi FROM dbo.OrderItem oi
INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
WHERE o.status = N'已取消'""",
    },
    # --- Category 3: GROUP BY WITH ROLLUP/CUBE [MEDIUM] ---
    {
        "id": "3.1",
        "category": "WITH ROLLUP",
        "difficulty": "MEDIUM",
        "sql": """SELECT c.region, c.tier, COUNT(*) AS cnt, SUM(o.actual_amount) AS total
FROM dbo.Customer c INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
GROUP BY c.region, c.tier WITH ROLLUP""",
    },
    {
        "id": "3.3",
        "category": "GROUPING SETS",
        "difficulty": "MEDIUM",
        "sql": """SELECT c.region, p.category, SUM(oi.subtotal) AS revenue,
GROUPING(c.region) AS is_region_agg
FROM dbo.Customer c INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
INNER JOIN dbo.OrderItem oi ON o.order_id = oi.order_id
INNER JOIN dbo.Product p ON oi.product_id = p.product_id
GROUP BY GROUPING SETS ((c.region, p.category), (c.region), ())""",
    },
    # --- Category 4: Window Function Advanced [MEDIUM] ---
    {
        "id": "4.1",
        "category": "ROWS BETWEEN frame",
        "difficulty": "MEDIUM",
        "sql": """SELECT o.order_id, o.actual_amount,
SUM(o.actual_amount) OVER (ORDER BY o.order_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS moving_avg
FROM dbo.[Order] o WHERE o.status NOT IN (N'已取消')""",
    },
    {
        "id": "4.3",
        "category": "PERCENTILE_CONT WITHIN GROUP",
        "difficulty": "MEDIUM",
        "sql": """SELECT DISTINCT c.region,
PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.actual_amount)
OVER (PARTITION BY c.region) AS median_amount
FROM dbo.Customer c INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id""",
    },
    # --- Category 5: Multi-level CTE [EASY] ---
    {
        "id": "5.1",
        "category": "3-layer CTE chain",
        "difficulty": "EASY",
        "sql": """WITH MonthlySales AS (
    SELECT FORMAT(o.order_date, 'yyyy-MM') AS month, SUM(o.actual_amount) AS rev
    FROM dbo.[Order] o GROUP BY FORMAT(o.order_date, 'yyyy-MM')
), RegionAvg AS (
    SELECT AVG(rev) AS avg_rev FROM MonthlySales
)
SELECT ms.month, ms.rev FROM MonthlySales ms
INNER JOIN RegionAvg ra ON ms.rev > ra.avg_rev * 1.2""",
    },
    {
        "id": "5.2",
        "category": "Recursive CTE multi-anchor",
        "difficulty": "HARD",
        "sql": """WITH CategoryTree AS (
    SELECT product_id, category, CAST(category AS NVARCHAR(500)) AS path, 0 AS depth
    FROM dbo.Product WHERE category = N'电子产品'
    UNION ALL
    SELECT product_id, category, CAST(category AS NVARCHAR(500)), 0
    FROM dbo.Product WHERE category = N'家居用品'
    UNION ALL
    SELECT p.product_id, p.category, CAST(ct.path + N' > ' + p.category AS NVARCHAR(500)), ct.depth + 1
    FROM dbo.Product p INNER JOIN CategoryTree ct ON p.product_id = ct.product_id + 1
    WHERE ct.depth < 3
)
SELECT * FROM CategoryTree OPTION (MAXRECURSION 50)""",
    },
    # --- Category 6: INSERT...EXEC [BLOCKER] ---
    {
        "id": "6.1",
        "category": "INSERT INTO EXEC",
        "difficulty": "BLOCKER",
        "sql": """INSERT INTO #OrderReport (order_id, order_no, status, total_amount)
EXEC dbo.GetCustomerOrders @p_customer_id = 1, @p_page = 1, @p_page_size = 100, @p_total_count = NULL""",
    },
    # --- Category 7: @@ERROR / @@ROWCOUNT [MEDIUM] ---
    {
        "id": "7.1",
        "category": "@@ERROR + @@ROWCOUNT",
        "difficulty": "MEDIUM",
        "sql": """UPDATE dbo.Product SET unit_price = unit_price * 1.05 WHERE category = N'电子产品';
SELECT @err_code = @@ERROR, @row_cnt = @@ROWCOUNT""",
    },
    # --- Category 8: SET options [MEDIUM] ---
    {
        "id": "8.1",
        "category": "SET XACT_ABORT",
        "difficulty": "MEDIUM",
        "sql": "SET XACT_ABORT ON;\nBEGIN TRANSACTION;\nUPDATE dbo.Product SET unit_price = -1 WHERE product_id = 99999;\nCOMMIT TRANSACTION;",
    },
    # --- Category 9: Cursor SCROLL [HARD] ---
    {
        "id": "9.1",
        "category": "CURSOR SCROLL",
        "difficulty": "HARD",
        "sql": """DECLARE scroll_cur CURSOR SCROLL FOR SELECT product_id, product_name FROM dbo.Product;
OPEN scroll_cur;
FETCH FIRST FROM scroll_cur;
FETCH ABSOLUTE 5 FROM scroll_cur;
CLOSE scroll_cur;
DEALLOCATE scroll_cur""",
    },
    # --- Category 10: MERGE complex [HARD] ---
    {
        "id": "10.1",
        "category": "MERGE multiple WHEN MATCHED",
        "difficulty": "HARD",
        "sql": """MERGE INTO dbo.Product AS target
USING (VALUES (N'ELEC-001', N'蓝牙耳机', N'电子产品', 299.00))
AS source (code, name, cat, price)
ON target.product_code = source.code
WHEN MATCHED AND target.unit_price <> source.price THEN
    UPDATE SET target.unit_price = source.price
WHEN MATCHED AND target.unit_price = source.price THEN
    UPDATE SET target.stock_quantity = target.stock_quantity + 100
WHEN NOT MATCHED BY TARGET THEN
    INSERT (product_code, product_name, category, unit_price) VALUES (source.code, source.name, source.cat, source.price)
WHEN NOT MATCHED BY SOURCE AND target.category = N'电子产品' THEN
    UPDATE SET target.is_active = 0
OUTPUT $action, inserted.product_id, deleted.unit_price, inserted.unit_price""",
    },
    # --- Category 11: OUTPUT INTO @table_var [HARD] ---
    {
        "id": "11.1",
        "category": "OUTPUT INTO @table_var",
        "difficulty": "HARD",
        "sql": """DECLARE @UpdatedProducts TABLE (product_id INT, old_price DECIMAL(10,2), new_price DECIMAL(10,2));
UPDATE dbo.Product SET unit_price = unit_price * 1.08
OUTPUT inserted.product_id, deleted.unit_price, inserted.unit_price INTO @UpdatedProducts
WHERE category = N'电子产品'""",
    },
    # --- Category 12: COLLATE [MEDIUM] ---
    {
        "id": "12.1",
        "category": "COLLATE clause",
        "difficulty": "MEDIUM",
        "sql": "SELECT customer_code, full_name FROM dbo.Customer WHERE full_name COLLATE Latin1_General_CI_AI LIKE N'%张%'",
    },
    # --- Category 13: System Functions [HARD] ---
    {
        "id": "13.1",
        "category": "OBJECT_ID / DB_NAME",
        "difficulty": "HARD",
        "sql": "SELECT OBJECT_ID('dbo.Customer') AS obj_id, DB_NAME() AS db, SCHEMA_NAME(1) AS schema_name",
    },
    {
        "id": "13.3",
        "category": "sys.tables / sys.columns",
        "difficulty": "HARD",
        "sql": """SELECT t.name, c.name, tp.name FROM sys.tables t
INNER JOIN sys.columns c ON t.object_id = c.object_id
INNER JOIN sys.types tp ON c.user_type_id = tp.user_type_id""",
    },
    # --- Category 14: Temporal Table [BLOCKER] ---
    {
        "id": "14.1",
        "category": "SYSTEM_VERSIONING temporal",
        "difficulty": "BLOCKER",
        "sql": """SELECT * FROM dbo.ProductHistory FOR SYSTEM_TIME AS OF '2024-06-01'""",
    },
    {
        "id": "14.2",
        "category": "FOR SYSTEM_TIME BETWEEN",
        "difficulty": "BLOCKER",
        "sql": "SELECT * FROM dbo.ProductHistory FOR SYSTEM_TIME BETWEEN '2024-01-01' AND '2024-12-31' ORDER BY valid_from",
    },
    # --- Category 15: PARTITION [HARD] ---
    {
        "id": "15.3",
        "category": "$PARTITION function",
        "difficulty": "HARD",
        "sql": """SELECT $PARTITION.pf_OrderDate(order_date) AS pn, COUNT(*) AS cnt
FROM dbo.OrderPartitioned GROUP BY $PARTITION.pf_OrderDate(order_date)""",
    },
    # --- Category 16: HierarchyID [BLOCKER] ---
    {
        "id": "16.1",
        "category": "HierarchyID type",
        "difficulty": "BLOCKER",
        "sql": """SELECT node_path.ToString() AS path_text, node_name, node_path.GetLevel() AS level
FROM dbo.OrgNode WHERE node_path.IsDescendantOf(hierarchyid::GetRoot()) = 1""",
    },
    # --- Category 17: Computed Column with UDF [HARD] ---
    {
        "id": "17.1",
        "category": "Computed column + UDF",
        "difficulty": "HARD",
        "sql": "ALTER TABLE dbo.[Order] ADD status_label AS (dbo.fn_GetOrderStatusName(status))",
    },
    # --- Category 18: Dynamic PIVOT [BLOCKER] ---
    {
        "id": "18.1",
        "category": "Dynamic PIVOT",
        "difficulty": "BLOCKER",
        "sql": """DECLARE @cols NVARCHAR(MAX);
SELECT @cols = STRING_AGG(QUOTENAME(region), ', ') FROM (SELECT DISTINCT region FROM dbo.Customer) t;
DECLARE @sql NVARCHAR(MAX) = N'SELECT * FROM src PIVOT (SUM(amount) FOR region IN (' + @cols + N')) pvt';
EXEC sp_executesql @sql""",
    },
    # --- Category 19: CROSS APPLY chain [HARD] ---
    {
        "id": "19.1",
        "category": "Multi CROSS APPLY chain",
        "difficulty": "HARD",
        "sql": """SELECT c.full_name, orders.order_no, level_calc.level_name, discount_calc.disc
FROM dbo.Customer c
CROSS APPLY dbo.fn_GetCustomerOrders(c.customer_id) orders
CROSS APPLY (SELECT CASE WHEN orders.actual_amount > 10000 THEN N'大额' ELSE N'普通' END AS level_name) level_calc
CROSS APPLY (SELECT dbo.fn_GetDiscount(orders.actual_amount) AS disc) discount_calc
WHERE c.tier = 'A'""",
    },
    # --- Category 20: Implicit Conversion [MEDIUM] ---
    {
        "id": "20.1",
        "category": "NVARCHAR vs VARCHAR implicit",
        "difficulty": "MEDIUM",
        "sql": "SELECT * FROM dbo.Customer WHERE customer_code = N'CUST-001'",
    },
    # --- Category 21: SELECT INTO [MEDIUM] ---
    {
        "id": "21.1",
        "category": "SELECT INTO new table",
        "difficulty": "MEDIUM",
        "sql": """SELECT c.customer_id, c.full_name, COUNT(o.order_id) AS cnt
INTO dbo.CustomerAnalytics
FROM dbo.Customer c LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.full_name""",
    },
    # --- Category 22: ERROR_* functions [MEDIUM] ---
    {
        "id": "22.1",
        "category": "ERROR_NUMBER/MESSAGE/LINE",
        "difficulty": "MEDIUM",
        "sql": """BEGIN TRY
    DECLARE @r DECIMAL(10,2) = 100.0 / 0;
END TRY BEGIN CATCH
    SELECT ERROR_NUMBER() AS err, ERROR_MESSAGE() AS msg, ERROR_LINE() AS line;
    THROW;
END CATCH""",
    },
    # --- Category 23: TVP [HARD] ---
    {
        "id": "23.1",
        "category": "Table-Valued Parameter",
        "difficulty": "HARD",
        "sql": "CREATE TYPE dbo.OrderItemType AS TABLE (product_id INT NOT NULL, quantity INT NOT NULL, unit_price DECIMAL(10,2) NOT NULL)",
    },
    # --- Category 24: Sequence [EASY] ---
    {
        "id": "24.1",
        "category": "NEXT VALUE FOR",
        "difficulty": "EASY",
        "sql": "SELECT NEXT VALUE FOR dbo.OrderSeq AS next_num",
    },
    # --- Category 25: RAISERROR / FORMAT [MEDIUM] ---
    {
        "id": "25.1",
        "category": "RAISERROR with args",
        "difficulty": "MEDIUM",
        "sql": "RAISERROR(N'产品 %s 库存不足，当前库存: %d', 16, 1, N'P001', 5)",
    },
    {
        "id": "25.2",
        "category": "FORMAT() date/number",
        "difficulty": "MEDIUM",
        "sql": "SELECT FORMAT(GETDATE(), 'yyyy-MM-dd HH:mm:ss') AS dt, FORMAT(1234567.89, 'N2') AS num",
    },
    # --- Additional: well-known patterns already covered ---
    {
        "id": "ref.1",
        "category": "TOP N (baseline)",
        "difficulty": "EASY",
        "sql": "SELECT TOP 10 * FROM dbo.[Order] ORDER BY order_date DESC",
    },
    {
        "id": "ref.2",
        "category": "GETDATE + ISNULL + LEN (baseline)",
        "difficulty": "EASY",
        "sql": "SELECT ISNULL(full_name, 'N/A'), LEN(full_name), GETDATE() FROM dbo.Customer",
    },
    {
        "id": "ref.3",
        "category": "DATEADD + DATEDIFF (baseline)",
        "difficulty": "EASY",
        "sql": "SELECT DATEADD(DAY, 30, GETDATE()) AS d30, DATEDIFF(DAY, '2024-01-01', GETDATE()) AS diff",
    },
]


# ===========================================================================
# Test Runner
# ===========================================================================

@dataclass
class CaseResult:
    case_id: str
    category: str
    difficulty: str
    # Classifier results
    detected_categories: list[str] = field(default_factory=list)
    detected_features: list[str] = field(default_factory=list)
    complexity: str = ""
    # Rewrite results
    rules_applied: list[str] = field(default_factory=list)
    rewrite_confidence: float = 0.0
    rewrite_warnings: list[str] = field(default_factory=list)
    sql_changed: bool = False
    # Assessment
    detection_ok: bool = False
    rewrite_ok: bool = False


def run_test(case: dict) -> CaseResult:
    """Run classifier + rewrite on a single SQL case."""
    sql = case["sql"]
    result = CaseResult(
        case_id=case["id"],
        category=case["category"],
        difficulty=case["difficulty"],
    )

    # --- Classifier ---
    try:
        classification = classify_sql(sql)
        result.detected_categories = [c.value for c in classification.categories]
        result.detected_features = [
            f"{f.category.value}: {f.details}" for f in classification.features
        ]
        result.complexity = classification.complexity
        result.detection_ok = len(classification.categories) > 0
    except Exception as e:
        result.detected_categories = [f"ERROR: {e}"]
        result.detection_ok = False

    # --- Rewrite ---
    try:
        rw = rewrite_sql(sql, "mssql", "kingbasees")
        result.rules_applied = [
            f"{r.name} ({r.description})" for r in rw.rules_applied
        ]
        result.rewrite_confidence = rw.confidence
        result.rewrite_warnings = rw.warnings
        result.sql_changed = rw.rewritten_sql.strip() != sql.strip()
        result.rewrite_ok = len(rw.rules_applied) > 0 or result.sql_changed
    except Exception as e:
        result.rules_applied = [f"ERROR: {e}"]
        result.rewrite_ok = False

    return result


def print_report(results: list[CaseResult]):
    """Print a structured adaptation report."""
    print("=" * 80)
    print("MIGRATION DIFFICULTIES — ADAPTATION TEST REPORT")
    print("=" * 80)

    # Summary counts
    total = len(results)
    detected = sum(1 for r in results if r.detection_ok)
    rewritten = sum(1 for r in results if r.rewrite_ok)
    changed = sum(1 for r in results if r.sql_changed)

    by_difficulty = {}
    for r in results:
        d = r.difficulty
        if d not in by_difficulty:
            by_difficulty[d] = {"total": 0, "detected": 0, "rewritten": 0}
        by_difficulty[d]["total"] += 1
        if r.detection_ok:
            by_difficulty[d]["detected"] += 1
        if r.rewrite_ok:
            by_difficulty[d]["rewritten"] += 1

    print(f"\n{'Summary':^80}")
    print("-" * 80)
    print(f"  Total cases:          {total}")
    print(f"  Detected (classifier): {detected}/{total} ({100*detected/total:.0f}%)")
    print(f"  Rewritten (engine):    {rewritten}/{total} ({100*rewritten/total:.0f}%)")
    print(f"  SQL actually changed:  {changed}/{total} ({100*changed/total:.0f}%)")

    print(f"\n{'By Difficulty Level':^80}")
    print("-" * 80)
    for level in ["EASY", "MEDIUM", "HARD", "BLOCKER"]:
        if level in by_difficulty:
            d = by_difficulty[level]
            print(f"  {level:10s}: {d['detected']}/{d['total']} detected, {d['rewritten']}/{d['total']} rewritten")

    # Detailed results
    print(f"\n{'Detailed Results':^80}")
    print("=" * 80)

    for r in results:
        icon_d = "✅" if r.detection_ok else "❌"
        icon_r = "✅" if r.rewrite_ok else "❌"
        icon_c = "🔄" if r.sql_changed else "➖"

        print(f"\n[{r.case_id}] {r.category} [{r.difficulty}]")
        print(f"  Classifier {icon_d}: categories={r.detected_categories}")
        if r.detected_features:
            for f in r.detected_features:
                print(f"    feature: {f}")
        print(f"  Complexity: {r.complexity}")
        print(f"  Rewrite    {icon_r} {icon_c}: confidence={r.rewrite_confidence:.2f}")
        if r.rules_applied:
            for rule in r.rules_applied:
                print(f"    rule: {rule}")
        if r.rewrite_warnings:
            for w in r.rewrite_warnings:
                print(f"    ⚠️  {w}")

    # Gap Analysis
    print(f"\n{'Gap Analysis — Undetected or Unrewritten':^80}")
    print("=" * 80)
    gaps = [r for r in results if not r.detection_ok or not r.rewrite_ok]
    for r in gaps:
        issues = []
        if not r.detection_ok:
            issues.append("NOT DETECTED by classifier")
        if not r.rewrite_ok:
            issues.append("NOT REWRITTEN by engine")
        if r.rewrite_ok and not r.sql_changed:
            issues.append("SQL unchanged (no rules matched)")
        print(f"  [{r.case_id}] {r.category} [{r.difficulty}]: {'; '.join(issues)}")


if __name__ == "__main__":
    results = []
    for case in DIFFICULTY_CASES:
        results.append(run_test(case))
    print_report(results)
