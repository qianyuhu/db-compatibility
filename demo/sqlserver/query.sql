-- =============================================================================
-- query.sql — Comprehensive Query Examples (SQL Server)
-- =============================================================================
-- Covers: JOINs, GROUP BY/HAVING, DISTINCT, UNION, EXISTS, IN, BETWEEN,
--         LIKE, CASE WHEN, Subqueries, CTE, Window Functions, Pagination
-- =============================================================================

-- =============================================================================
-- 1. JOIN Operations — 连接操作
-- =============================================================================

-- 1.1 INNER JOIN — 查询订单及客户信息
SELECT
    o.order_id,
    o.order_no,
    c.full_name  AS customer_name,
    c.region,
    o.status,
    o.actual_amount
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.order_date >= '2024-06-01'
ORDER BY o.order_date DESC;

-- 1.2 LEFT JOIN — 所有客户及其订单情况（含未下单客户）
SELECT
    c.customer_code,
    c.full_name,
    c.region,
    COUNT(o.order_id)  AS order_count,
    ISNULL(SUM(o.actual_amount), 0) AS total_spent
FROM dbo.Customer c
LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                       AND o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.customer_code, c.full_name, c.region
ORDER BY total_spent DESC;

-- 1.3 RIGHT JOIN — 所有订单及其产品明细
SELECT
    p.product_code,
    p.product_name,
    p.category,
    ISNULL(SUM(oi.quantity), 0) AS total_ordered
FROM dbo.OrderItem oi
RIGHT JOIN dbo.Product p ON oi.product_id = p.product_id
GROUP BY p.product_code, p.product_name, p.category
ORDER BY total_ordered DESC;

-- 1.4 多表 JOIN — 订单-订单项-产品三表连接
SELECT
    o.order_no,
    o.order_date,
    c.full_name,
    p.product_name,
    oi.quantity,
    oi.unit_price,
    oi.subtotal,
    oi.discount
FROM dbo.[Order] o
INNER JOIN dbo.Customer c  ON o.customer_id = c.customer_id
INNER JOIN dbo.OrderItem oi ON o.order_id = oi.order_id
INNER JOIN dbo.Product p   ON oi.product_id = p.product_id
WHERE o.order_date >= '2024-10-01'
ORDER BY o.order_date DESC, oi.item_id;

-- =============================================================================
-- 2. GROUP BY and HAVING — 分组与过滤
-- =============================================================================

-- 2.1 GROUP BY — 按地区和等级统计客户
SELECT
    region,
    tier,
    COUNT(*)        AS customer_count,
    AVG(credit_limit) AS avg_credit_limit,
    SUM(credit_limit) AS total_credit
FROM dbo.Customer
GROUP BY region, tier
ORDER BY region, tier;

-- 2.2 HAVING — 筛选高消费客户
SELECT
    c.customer_id,
    c.full_name,
    c.region,
    COUNT(o.order_id)   AS order_count,
    SUM(o.actual_amount) AS total_spent
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.customer_id, c.full_name, c.region
HAVING SUM(o.actual_amount) > 100000
ORDER BY total_spent DESC;

-- 2.3 HAVING with COUNT — 高频客户
SELECT
    c.customer_id,
    c.full_name,
    COUNT(o.order_id) AS order_count
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.full_name
HAVING COUNT(o.order_id) >= 5
ORDER BY order_count DESC;

-- 2.4 GROUP BY ROLLUP — 多维汇总
SELECT
    ISNULL(c.region, N'合计') AS region,
    ISNULL(p.category, N'小计') AS category,
    SUM(oi.quantity * oi.unit_price) AS sales_amount
FROM dbo.[Order] o
INNER JOIN dbo.Customer c   ON o.customer_id = c.customer_id
INNER JOIN dbo.OrderItem oi ON o.order_id = oi.order_id
INNER JOIN dbo.Product p    ON oi.product_id = p.product_id
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY ROLLUP (c.region, p.category)
ORDER BY region, category;

-- =============================================================================
-- 3. DISTINCT — 去重
-- =============================================================================

-- 3.1 简单去重
SELECT DISTINCT region FROM dbo.Customer ORDER BY region;

-- 3.2 多列去重
SELECT DISTINCT category, is_active FROM dbo.Product ORDER BY category, is_active;

-- 3.3 DISTINCT with COUNT
SELECT
    COUNT(DISTINCT customer_id) AS unique_customers,
    COUNT(DISTINCT region)      AS unique_regions
FROM dbo.Customer;

-- =============================================================================
-- 4. UNION and UNION ALL — 结果集合并
-- =============================================================================

-- 4.1 UNION ALL — 保留重复行
SELECT product_code AS code, product_name AS name, N'产品' AS source
FROM dbo.Product
WHERE category = N'电子元器件'
UNION ALL
SELECT customer_code, full_name, N'客户'
FROM dbo.Customer
WHERE region = N'华南';

-- 4.2 UNION — 去除重复行
SELECT region AS location, N'A级客户' AS label
FROM dbo.Customer WHERE tier = 'A'
UNION
SELECT region, N'VIP客户'
FROM dbo.Customer WHERE is_vip = 1
ORDER BY location;

-- =============================================================================
-- 5. EXISTS and NOT EXISTS — 存在性检查
-- =============================================================================

-- 5.1 EXISTS — 有订单的客户
SELECT c.customer_code, c.full_name, c.region
FROM dbo.Customer c
WHERE EXISTS (
    SELECT 1 FROM dbo.[Order] o
    WHERE o.customer_id = c.customer_id
      AND o.actual_amount > 50000
);

-- 5.2 NOT EXISTS — 从未下过订单的客户
SELECT c.customer_code, c.full_name, c.region
FROM dbo.Customer c
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.[Order] o
    WHERE o.customer_id = c.customer_id
);

-- 5.3 NOT EXISTS — 从未被购买的产品
SELECT p.product_code, p.product_name, p.stock_quantity
FROM dbo.Product p
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.OrderItem oi
    INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
    WHERE oi.product_id = p.product_id
      AND o.status NOT IN (N'已取消', N'已退款')
);

-- =============================================================================
-- 6. IN / BETWEEN / LIKE — 条件过滤
-- =============================================================================

-- 6.1 IN — 多个值匹配
SELECT * FROM dbo.Customer
WHERE region IN (N'华东', N'华南', N'华北')
  AND tier IN ('A', 'B');

-- 6.2 NOT IN
SELECT * FROM dbo.Product
WHERE category NOT IN (N'软件', N'办公设备');

-- 6.3 BETWEEN — 范围查询
SELECT order_no, order_date, actual_amount
FROM dbo.[Order]
WHERE order_date BETWEEN '2024-06-01' AND '2024-09-30'
  AND actual_amount BETWEEN 10000 AND 100000
ORDER BY actual_amount DESC;

-- 6.4 LIKE — 模糊匹配
SELECT customer_code, full_name
FROM dbo.Customer
WHERE full_name LIKE N'%科技%';

SELECT product_code, product_name
FROM dbo.Product
WHERE product_code LIKE 'PROD-0[1-5]%';  -- 01-05 开头

SELECT product_name
FROM dbo.Product
WHERE product_name LIKE N'%服务%';

-- 6.5 NOT LIKE
SELECT * FROM dbo.Customer WHERE email NOT LIKE '%@example.com';

-- =============================================================================
-- 7. CASE WHEN — 条件表达式
-- =============================================================================

-- 7.1 简单 CASE
SELECT
    order_id,
    order_no,
    status,
    CASE status
        WHEN N'待付款' THEN N'⏳ 等待付款'
        WHEN N'已付款' THEN N'✅ 已付款'
        WHEN N'已发货' THEN N'📦 已发货'
        WHEN N'已完成' THEN N'✔ 已完成'
        WHEN N'已取消' THEN N'❌ 已取消'
        WHEN N'已退款' THEN N'↩ 已退款'
        ELSE N'❓ 未知'
    END AS status_label
FROM dbo.[Order];

-- 7.2 搜索 CASE
SELECT
    product_code,
    product_name,
    unit_price,
    CASE
        WHEN unit_price < 100    THEN N'低价'
        WHEN unit_price < 1000   THEN N'中价'
        WHEN unit_price < 10000  THEN N'高价'
        ELSE N'超高价'
    END AS price_level
FROM dbo.Product;

-- 7.3 CASE in aggregate
SELECT
    region,
    SUM(CASE WHEN tier = 'A' THEN credit_limit ELSE 0 END) AS A级总额度,
    SUM(CASE WHEN tier = 'B' THEN credit_limit ELSE 0 END) AS B级总额度,
    SUM(CASE WHEN tier = 'C' THEN credit_limit ELSE 0 END) AS C级总额度
FROM dbo.Customer
GROUP BY region;

-- =============================================================================
-- 8. Subqueries — 子查询
-- =============================================================================

-- 8.1 标量子查询
SELECT
    order_no,
    actual_amount,
    (SELECT AVG(actual_amount) FROM dbo.[Order]
     WHERE status NOT IN (N'已取消', N'已退款')) AS avg_amount,
    actual_amount - (SELECT AVG(actual_amount) FROM dbo.[Order]
     WHERE status NOT IN (N'已取消', N'已退款')) AS diff_from_avg
FROM dbo.[Order]
WHERE order_date >= '2024-06-01';

-- 8.2 行子查询
SELECT customer_code, full_name
FROM dbo.Customer
WHERE (region, tier) IN (
    SELECT region, MAX(tier) FROM dbo.Customer GROUP BY region
);

-- 8.3 表子查询 (Derived Table)
SELECT sub.region, sub.tier, AVG(sub.total_spent) AS avg_tier_spent
FROM (
    SELECT c.region, c.tier, ISNULL(SUM(o.actual_amount), 0) AS total_spent
    FROM dbo.Customer c
    INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
    WHERE o.status NOT IN (N'已取消', N'已退款')
    GROUP BY c.customer_id, c.region, c.tier
) sub
GROUP BY sub.region, sub.tier
ORDER BY sub.region;

-- 8.4 相关子查询
SELECT
    p.product_code,
    p.product_name,
    p.unit_price,
    (SELECT COUNT(*) FROM dbo.OrderItem oi
     INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
     WHERE oi.product_id = p.product_id
       AND o.status NOT IN (N'已取消', N'已退款')
    ) AS order_count
FROM dbo.Product p
WHERE p.is_active = 1
ORDER BY order_count DESC;

-- =============================================================================
-- 9. CTE (Common Table Expression) — 公用表表达式
-- =============================================================================

-- 9.1 简单 CTE
WITH CustomerSpending AS (
    SELECT
        c.customer_id,
        c.full_name,
        c.region,
        ISNULL(SUM(o.actual_amount), 0) AS total_spent
    FROM dbo.Customer c
    LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                           AND o.status NOT IN (N'已取消', N'已退款')
    GROUP BY c.customer_id, c.full_name, c.region
)
SELECT * FROM CustomerSpending
WHERE total_spent > 50000
ORDER BY total_spent DESC;

-- 9.2 多个 CTE 链式使用
WITH
OrderStats AS (
    SELECT
        product_id,
        SUM(quantity) AS total_quantity,
        SUM(subtotal) AS total_revenue
    FROM dbo.OrderItem
    GROUP BY product_id
),
ProductWithStats AS (
    SELECT
        p.product_code,
        p.product_name,
        p.category,
        p.stock_quantity,
        ISNULL(os.total_quantity, 0) AS sold,
        ISNULL(os.total_revenue, 0)  AS revenue
    FROM dbo.Product p
    LEFT JOIN OrderStats os ON p.product_id = os.product_id
)
SELECT *,
    CASE WHEN stock_quantity = 0 AND sold > 0 THEN N'热销缺货'
         WHEN stock_quantity = 0 THEN N'已下架'
         WHEN sold = 0 THEN N'滞销'
         ELSE N'正常'
    END AS sales_status
FROM ProductWithStats
ORDER BY revenue DESC;

-- =============================================================================
-- 10. Window Functions — 窗口函数
-- =============================================================================

-- 10.1 ROW_NUMBER — 行号
SELECT
    ROW_NUMBER() OVER (ORDER BY total_spent DESC) AS rank_no,
    full_name,
    region,
    total_spent
FROM (
    SELECT c.full_name, c.region, SUM(o.actual_amount) AS total_spent
    FROM dbo.Customer c
    INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
    WHERE o.status NOT IN (N'已取消', N'已退款')
    GROUP BY c.customer_id, c.full_name, c.region
) sub
WHERE total_spent > 0;

-- 10.2 RANK and DENSE_RANK
SELECT
    category,
    product_name,
    unit_price,
    RANK()       OVER (PARTITION BY category ORDER BY unit_price DESC) AS price_rank,
    DENSE_RANK() OVER (PARTITION BY category ORDER BY unit_price DESC) AS price_dense_rank
FROM dbo.Product
WHERE is_active = 1
ORDER BY category, price_rank;

-- 10.3 NTILE — 分桶
SELECT
    product_name,
    unit_price,
    NTILE(4) OVER (ORDER BY unit_price DESC) AS price_quartile
FROM dbo.Product
WHERE is_active = 1;

-- 10.4 LAG / LEAD — 前后行访问
SELECT
    order_date,
    actual_amount,
    LAG(actual_amount, 1, 0)  OVER (ORDER BY order_date) AS prev_amount,
    LEAD(actual_amount, 1, 0) OVER (ORDER BY order_date) AS next_amount,
    actual_amount - LAG(actual_amount, 1, 0) OVER (ORDER BY order_date) AS amount_change
FROM dbo.[Order]
WHERE customer_id = 1
  AND status NOT IN (N'已取消', N'已退款')
ORDER BY order_date;

-- 10.5 SUM / AVG / COUNT window aggregates
SELECT
    order_date,
    actual_amount,
    SUM(actual_amount) OVER (PARTITION BY customer_id ORDER BY order_date) AS running_total,
    AVG(actual_amount) OVER (PARTITION BY customer_id) AS customer_avg,
    actual_amount - AVG(actual_amount) OVER (PARTITION BY customer_id) AS above_avg
FROM dbo.[Order]
WHERE status NOT IN (N'已取消', N'已退款')
ORDER BY customer_id, order_date;

-- 10.6 FIRST_VALUE / LAST_VALUE
SELECT
    region,
    full_name,
    total_spent,
    FIRST_VALUE(full_name) OVER (PARTITION BY region ORDER BY total_spent DESC) AS top_customer,
    LAST_VALUE(full_name)  OVER (
        PARTITION BY region ORDER BY total_spent
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS bottom_customer
FROM (
    SELECT c.region, c.full_name, SUM(o.actual_amount) AS total_spent
    FROM dbo.Customer c
    INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
    WHERE o.status NOT IN (N'已取消', N'已退款')
    GROUP BY c.region, c.full_name
) sub;

-- =============================================================================
-- 11. Pagination — 分页
-- =============================================================================

-- 11.1 TOP — SQL Server 传统分页
SELECT TOP 10 *
FROM dbo.[Order]
WHERE customer_id = 1
ORDER BY order_date DESC;

-- 11.2 OFFSET FETCH — SQL Server 2012+ 标准分页
SELECT order_id, order_no, order_date, status, actual_amount
FROM dbo.[Order]
WHERE status NOT IN (N'已取消', N'已退款')
ORDER BY order_date DESC
OFFSET 20 ROWS
FETCH NEXT 10 ROWS ONLY;

-- 11.3 动态分页（第 N 页）
DECLARE @PageNumber INT = 3;
DECLARE @PageSize   INT = 15;

SELECT order_id, order_no, order_date, status, actual_amount,
       COUNT(*) OVER () AS total_count  -- 总行数
FROM dbo.[Order]
WHERE status NOT IN (N'已取消', N'已退款')
ORDER BY order_date DESC
OFFSET (@PageNumber - 1) * @PageSize ROWS
FETCH NEXT @PageSize ROWS ONLY;

-- =============================================================================
-- 12. Additional Query Patterns
-- =============================================================================

-- 12.1 SELECT INTO — 从查询创建新表
-- SELECT o.order_id, o.order_no, c.full_name, o.actual_amount
-- INTO #TempHighValue
-- FROM dbo.[Order] o
-- INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
-- WHERE o.actual_amount > 50000;

-- 12.2 INTERSECT — 交集
SELECT customer_id FROM dbo.[Order] WHERE YEAR(order_date) = 2023
INTERSECT
SELECT customer_id FROM dbo.[Order] WHERE YEAR(order_date) = 2024;

-- 12.3 EXCEPT — 差集
SELECT customer_id FROM dbo.Customer
EXCEPT
SELECT customer_id FROM dbo.[Order];

-- 12.4 CROSS JOIN — 笛卡尔积
SELECT TOP 100
    c.customer_code,
    p.product_code
FROM dbo.Customer c
CROSS JOIN dbo.Product p
WHERE c.tier = 'A' AND p.category = N'电子元器件';

-- =============================================================================
-- Query Coverage Summary
-- =============================================================================
-- INNER JOIN              : 多表关联
-- LEFT JOIN               : 客户+订单（含空）
-- RIGHT JOIN              : 产品+订单项（含空）
-- GROUP BY                : 多维度分组
-- HAVING                  : 聚合结果过滤
-- ROLLUP                  : 多维汇总
-- DISTINCT                : 去重, COUNT(DISTINCT ...)
-- UNION ALL               : 合并+保留重复
-- UNION                   : 合并+去重
-- EXISTS / NOT EXISTS     : 存在性检查
-- IN / NOT IN             : 多值匹配
-- BETWEEN                 : 范围查询
-- LIKE                    : 模糊匹配 / 通配符
-- CASE WHEN               : 条件表达式 (简单 / 搜索 / 聚合)
-- Subquery                : 标量 / 行 / 表 / 相关
-- CTE                     : WITH 子句 (简单 / 链式)
-- ROW_NUMBER              : 行号
-- RANK / DENSE_RANK       : 排名
-- NTILE                   : 分桶
-- LAG / LEAD              : 前后行访问
-- Running Total           : SUM() OVER (PARTITION ... ORDER BY)
-- FIRST_VALUE / LAST_VALUE: 首尾值
-- TOP                     : 传统分页
-- OFFSET FETCH            : 标准分页 (SQL Server 2012+)
-- INTERSECT / EXCEPT      : 集合操作
-- CROSS JOIN              : 笛卡尔积
-- SELECT INTO             : 创建新表
-- =============================================================================
