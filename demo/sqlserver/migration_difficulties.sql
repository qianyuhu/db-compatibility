-- =============================================================================
-- migration_difficulties.sql — 已知迁移困难场景测试
-- =============================================================================
-- 目标：覆盖 MSSQL→KingbaseES/DM8/PostgreSQL 迁移中最常见的 20+ 困难特性
-- 用于测试系统的诊断识别能力和改写引擎适应情况
--
-- 难度分级：
--   [EASY]   — 有明确对应语法，改写引擎应能自动处理
--   [MEDIUM] — 有对应语法但语义差异大，需人工审查
--   [HARD]   — 无直接对应语法，需要架构级改造
--   [BLOCKER]— 无对应功能，需要重新设计方案
-- =============================================================================

-- =============================================================================
-- 1. UPDATE FROM with JOIN — MSSQL 专有 UPDATE 语法 [HARD]
-- =============================================================================
-- 困难点：标准 SQL 和 PG/KB 不支持 UPDATE ... FROM ... JOIN 语法
-- 需要改写为 UPDATE ... SET ... FROM (subquery) 或 MERGE

-- 1.1 简单 UPDATE JOIN — 根据客户等级批量调整订单折扣
UPDATE o
SET o.discount_amount = o.total_amount * 0.05,
    o.actual_amount   = o.total_amount - o.total_amount * 0.05,
    o.updated_at      = SYSDATETIME()
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE c.tier = 'A'
  AND o.status = N'待付款';

-- 1.2 复杂 UPDATE JOIN — 多表关联更新库存
UPDATE p
SET p.stock_quantity = p.stock_quantity - agg.total_sold,
    p.updated_at = SYSDATETIME()
FROM dbo.Product p
INNER JOIN (
    SELECT oi.product_id, SUM(oi.quantity) AS total_sold
    FROM dbo.OrderItem oi
    INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
    WHERE o.status = N'已付款'
      AND o.order_date >= '2024-10-01'
    GROUP BY oi.product_id
) agg ON p.product_id = agg.product_id
WHERE p.stock_quantity >= agg.total_sold;

-- 1.3 UPDATE with OUTPUT and JOIN — 同时获取更新前后值 [BLOCKER]
UPDATE o
SET o.status = N'已发货',
    o.updated_at = SYSDATETIME()
OUTPUT
    o.order_id,
    o.order_no,
    deleted.status AS old_status,
    inserted.status AS new_status,
    c.full_name AS customer_name
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.status = N'已付款'
  AND o.order_date >= '2024-11-01';

-- =============================================================================
-- 2. DELETE with JOIN — MSSQL 专有 DELETE 语法 [HARD]
-- =============================================================================

-- 2.1 简单 DELETE JOIN — 删除已取消订单的明细
DELETE oi
FROM dbo.OrderItem oi
INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
WHERE o.status = N'已取消'
  AND o.order_date < '2024-01-01';

-- 2.2 DELETE with OUTPUT and JOIN [BLOCKER]
DELETE il
OUTPUT deleted.log_id, deleted.product_id, deleted.change_type, deleted.created_at
FROM dbo.InventoryLog il
INNER JOIN dbo.Product p ON il.product_id = p.product_id
WHERE p.is_active = 0
  AND il.created_at < '2023-06-01';

-- =============================================================================
-- 3. GROUP BY WITH ROLLUP / CUBE / GROUPING SETS [MEDIUM]
-- =============================================================================
-- 困难点：PG/KB 支持 GROUPING SETS 但不支持 WITH ROLLUP/CUBE 后缀

-- 3.1 WITH ROLLUP — 自动产生小计行
SELECT
    c.region,
    c.tier,
    COUNT(*) AS customer_count,
    SUM(o.actual_amount) AS total_spent
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.region, c.tier WITH ROLLUP;

-- 3.2 WITH CUBE — 所有维度组合的交叉小计
SELECT
    p.category,
    YEAR(o.order_date) AS order_year,
    COUNT(oi.item_id) AS item_count,
    SUM(oi.subtotal) AS revenue
FROM dbo.Product p
INNER JOIN dbo.OrderItem oi ON p.product_id = oi.product_id
INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
GROUP BY p.category, YEAR(o.order_date) WITH CUBE;

-- 3.3 GROUPING SETS — 显式指定聚合组合
SELECT
    c.region,
    p.category,
    YEAR(o.order_date) AS order_year,
    SUM(oi.subtotal) AS revenue,
    GROUPING(c.region) AS is_region_agg,
    GROUPING(p.category) AS is_category_agg,
    GROUPING(YEAR(o.order_date)) AS is_year_agg
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
INNER JOIN dbo.OrderItem oi ON o.order_id = oi.order_id
INNER JOIN dbo.Product p ON oi.product_id = p.product_id
GROUP BY GROUPING SETS (
    (c.region, p.category, YEAR(o.order_date)),
    (c.region, p.category),
    (c.region),
    (p.category),
    ()
);

-- =============================================================================
-- 4. Window Function Advanced — 高级窗口函数 [MEDIUM]
-- =============================================================================

-- 4.1 ROWS BETWEEN frame — 滑动窗口聚合
SELECT
    o.order_id,
    o.order_date,
    o.actual_amount,
    SUM(o.actual_amount) OVER (
        ORDER BY o.order_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS moving_avg_7days,
    AVG(o.actual_amount) OVER (
        ORDER BY o.order_date
        ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
    ) AS centered_avg_5rows
FROM dbo.[Order] o
WHERE o.status NOT IN (N'已取消', N'已退款');

-- 4.2 RANGE BETWEEN frame — 值域窗口（日期范围）
SELECT
    o.order_date,
    SUM(o.actual_amount) OVER (
        ORDER BY CAST(o.order_date AS DATE)
        RANGE BETWEEN INTERVAL '30' DAY PRECEDING AND CURRENT ROW
    ) AS rolling_30day_sum
FROM dbo.[Order] o
WHERE o.status NOT IN (N'已取消', N'已退款');

-- 4.3 PERCENTILE_CONT / PERCENTILE_DISC — 百分位计算
SELECT DISTINCT
    c.region,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.actual_amount)
        OVER (PARTITION BY c.region) AS median_amount,
    PERCENTILE_DISC(0.75) WITHIN GROUP (ORDER BY o.actual_amount)
        OVER (PARTITION BY c.region) AS p75_amount
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款');

-- 4.4 CUME_DIST / NTILE / PERCENT_RANK
SELECT
    c.full_name,
    c.region,
    SUM(o.actual_amount) AS total_spent,
    NTILE(4) OVER (ORDER BY SUM(o.actual_amount) DESC) AS quartile,
    CUME_DIST() OVER (ORDER BY SUM(o.actual_amount)) AS cumulative_dist,
    PERCENT_RANK() OVER (ORDER BY SUM(o.actual_amount)) AS percent_rank
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.customer_id, c.full_name, c.region;

-- =============================================================================
-- 5. Multi-level CTE (CTE Chaining) — CTE 链式引用 [EASY]
-- =============================================================================
-- 困难点：大部分数据库支持，但语义复杂度增加改写风险

-- 5.1 三层 CTE 链
WITH
MonthlySales AS (
    SELECT
        FORMAT(o.order_date, 'yyyy-MM') AS sales_month,
        c.region,
        SUM(o.actual_amount) AS revenue
    FROM dbo.[Order] o
    INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
    WHERE o.status NOT IN (N'已取消', N'已退款')
    GROUP BY FORMAT(o.order_date, 'yyyy-MM'), c.region
),
RegionAvg AS (
    SELECT
        region,
        AVG(revenue) AS avg_monthly_revenue
    FROM MonthlySales
    GROUP BY region
),
TopMonths AS (
    SELECT
        ms.sales_month,
        ms.region,
        ms.revenue,
        ra.avg_monthly_revenue,
        ms.revenue - ra.avg_monthly_revenue AS deviation
    FROM MonthlySales ms
    INNER JOIN RegionAvg ra ON ms.region = ra.region
    WHERE ms.revenue > ra.avg_monthly_revenue * 1.2
)
SELECT * FROM TopMonths ORDER BY deviation DESC;

-- 5.2 Recursive CTE with multiple anchor members — 多锚点递归 [HARD]
WITH CategoryTree AS (
    -- Anchor 1: 电子产品根节点
    SELECT product_id, product_name, category,
           CAST(category AS NVARCHAR(500)) AS full_path, 0 AS depth
    FROM dbo.Product WHERE category = N'电子产品'
    UNION ALL
    -- Anchor 2: 家居用品根节点
    SELECT product_id, product_name, category,
           CAST(category AS NVARCHAR(500)), 0
    FROM dbo.Product WHERE category = N'家居用品'
    UNION ALL
    -- Recursive member: 按 product_id + 1 模拟层级
    SELECT p.product_id, p.product_name, p.category,
           CAST(ct.full_path + N' > ' + p.category AS NVARCHAR(500)),
           ct.depth + 1
    FROM dbo.Product p
    INNER JOIN CategoryTree ct ON p.product_id = ct.product_id + 1
    WHERE ct.depth < 3
)
SELECT * FROM CategoryTree
ORDER BY full_path, product_id
OPTION (MAXRECURSION 50);

-- =============================================================================
-- 6. INSERT...EXEC — 将存储过程结果集插入表 [BLOCKER]
-- =============================================================================
-- 困难点：PG/KB/DM8 均不支持 INSERT INTO ... EXEC proc

-- 6.1 将 SP 结果插入临时表
CREATE TABLE #OrderReport (
    order_id      INT,
    order_no      NVARCHAR(30),
    status        NVARCHAR(20),
    total_amount  DECIMAL(12,2)
);

INSERT INTO #OrderReport (order_id, order_no, status, total_amount)
EXEC dbo.GetCustomerOrders @p_customer_id = 1, @p_page = 1, @p_page_size = 100, @p_total_count = NULL;

SELECT * FROM #OrderReport;
DROP TABLE #OrderReport;

-- =============================================================================
-- 7. @@ERROR / @@ROWCOUNT 组合模式 — 旧式错误处理 [MEDIUM]
-- =============================================================================
-- 困难点：PG/KB 使用 EXCEPTION 块，DM8 使用 SQLCODE/SQLSTATE

DECLARE @err_code INT;
DECLARE @row_cnt  INT;

UPDATE dbo.Product
SET unit_price = unit_price * 1.05,
    updated_at = SYSDATETIME()
WHERE category = N'电子元器件';

SELECT @err_code = @@ERROR, @row_cnt = @@ROWCOUNT;

IF @err_code <> 0
BEGIN
    PRINT N'更新失败，错误代码: ' + CAST(@err_code AS NVARCHAR(10));
END
ELSE
BEGIN
    PRINT N'成功更新 ' + CAST(@row_cnt AS NVARCHAR(10)) + N' 行';
END

-- =============================================================================
-- 8. SET 会话选项 — 影响行为的隐式设置 [MEDIUM]
-- =============================================================================

-- 8.1 SET XACT_ABORT ON — 运行时错误自动回滚事务
SET XACT_ABORT ON;
BEGIN TRANSACTION;
    -- 如果此处发生运行时错误，事务自动回滚
    UPDATE dbo.Product SET unit_price = -1 WHERE product_id = 99999;
    UPDATE dbo.Customer SET credit_limit = -1 WHERE customer_id = 99999;
COMMIT TRANSACTION;
SET XACT_ABORT OFF;

-- 8.2 SET ANSI_NULLS ON/OFF — 影响 NULL 比较行为
SET ANSI_NULLS ON;
SELECT * FROM dbo.Customer WHERE region = NULL;     -- 永远返回 0 行
SELECT * FROM dbo.Customer WHERE region IS NULL;    -- 正确方式

-- 8.3 SET QUOTED_IDENTIFIER — 影响双引号行为
SET QUOTED_IDENTIFIER ON;
-- "Order" 被识别为标识符 [Order]
SET QUOTED_IDENTIFIER OFF;
-- "Order" 被识别为字符串字面量 'Order'

-- =============================================================================
-- 9. Cursor with SCROLL / LOCAL / KEYSET — 高级游标选项 [HARD]
-- =============================================================================

-- 9.1 SCROLL cursor — 支持前后滚动
DECLARE scroll_cur CURSOR SCROLL FOR
    SELECT product_id, product_name, unit_price
    FROM dbo.Product
    ORDER BY unit_price DESC;

OPEN scroll_cur;
FETCH FIRST FROM scroll_cur;        -- 第一行
FETCH NEXT FROM scroll_cur;         -- 下一行
FETCH LAST FROM scroll_cur;         -- 最后一行
FETCH PRIOR FROM scroll_cur;        -- 前一行
FETCH ABSOLUTE 5 FROM scroll_cur;   -- 第5行
FETCH RELATIVE -2 FROM scroll_cur;  -- 当前行前2行
CLOSE scroll_cur;
DEALLOCATE scroll_cur;

-- 9.2 KEYSET cursor — 键集驱动游标
DECLARE keyset_cur CURSOR KEYSET FOR
    SELECT order_id, status FROM dbo.[Order];

-- 9.3 DYNAMIC cursor — 动态游标（反映所有变更）
DECLARE dynamic_cur CURSOR DYNAMIC FOR
    SELECT product_id, stock_quantity FROM dbo.Product;

-- =============================================================================
-- 10. MERGE with Complex WHEN — 复杂 MERGE 条件 [HARD]
-- =============================================================================

-- 10.1 MERGE with multiple WHEN MATCHED conditions
MERGE INTO dbo.Product AS target
USING (
    VALUES
        (N'ELEC-NEW-001', N'新款蓝牙耳机', N'电子产品', 299.00, 150.00, 1000),
        (N'ELEC-002',     N'USB数据线',     N'电子产品', 29.00,  8.00,   5000),
        (N'HOME-001',     N'保温杯',        N'家居用品', 89.00,  30.00,  3000)
) AS source (product_code, product_name, category, unit_price, cost_price, stock)
ON target.product_code = source.product_code
WHEN MATCHED AND target.unit_price <> source.unit_price THEN
    UPDATE SET
        target.unit_price    = source.unit_price,
        target.cost_price    = source.cost_price,
        target.updated_at    = SYSDATETIME()
WHEN MATCHED AND target.unit_price = source.unit_price THEN
    -- 价格相同仅更新库存
    UPDATE SET
        target.stock_quantity = target.stock_quantity + source.stock,
        target.updated_at    = SYSDATETIME()
WHEN NOT MATCHED BY TARGET THEN
    INSERT (product_code, product_name, category, unit_price, cost_price, stock_quantity)
    VALUES (source.product_code, source.product_name, source.category,
            source.unit_price, source.cost_price, source.stock)
WHEN NOT MATCHED BY SOURCE AND target.category = N'电子产品' THEN
    UPDATE SET target.is_active = 0, target.updated_at = SYSDATETIME()
OUTPUT
    $action AS action_type,
    inserted.product_id,
    inserted.product_name,
    deleted.unit_price AS old_price,
    inserted.unit_price AS new_price;

-- =============================================================================
-- 11. OUTPUT INTO @table_variable — DML 输出到表变量 [HARD]
-- =============================================================================

DECLARE @UpdatedProducts TABLE (
    product_id   INT,
    product_name NVARCHAR(200),
    old_price    DECIMAL(10,2),
    new_price    DECIMAL(10,2)
);

UPDATE dbo.Product
SET unit_price = unit_price * 1.08,
    updated_at = SYSDATETIME()
OUTPUT inserted.product_id, inserted.product_name,
       deleted.unit_price, inserted.unit_price
INTO @UpdatedProducts
WHERE category = N'电子产品'
  AND is_active = 1;

SELECT * FROM @UpdatedProducts ORDER BY product_id;

-- =============================================================================
-- 12. COLLATE — 排序规则敏感查询 [MEDIUM]
-- =============================================================================

-- 12.1 忽略大小写排序
SELECT customer_code, full_name
FROM dbo.Customer
WHERE full_name COLLATE Latin1_General_CI_AI LIKE N'%张%'
ORDER BY full_name COLLATE Chinese_PRC_CI_AS;

-- 12.2 区分大小写的精确匹配
SELECT product_code, product_name
FROM dbo.Product
WHERE product_code COLLATE Latin1_General_CS_AS = 'ELEC-001';

-- =============================================================================
-- 13. System Functions — 系统元数据函数 [HARD]
-- =============================================================================

-- 13.1 OBJECT_ID / OBJECT_NAME / DB_ID / DB_NAME
SELECT
    OBJECT_ID('dbo.Customer') AS customer_obj_id,
    OBJECT_NAME(OBJECT_ID('dbo.Customer')) AS obj_name,
    DB_ID() AS current_db_id,
    DB_NAME() AS current_db_name,
    SCHEMA_ID('dbo') AS dbo_schema_id,
    SCHEMA_NAME(1) AS schema_name;

-- 13.2 TYPE_ID / TYPE_NAME
SELECT
    TYPE_ID('dbo.OrderItemType') AS tvp_type_id,
    TYPE_NAME(56) AS type_name_56;  -- 56 = INT

-- 13.3 sys 系统视图查询
SELECT
    t.name AS table_name,
    c.name AS column_name,
    tp.name AS data_type,
    c.max_length,
    c.precision,
    c.scale,
    c.is_nullable,
    c.is_identity
FROM sys.tables t
INNER JOIN sys.columns c ON t.object_id = c.object_id
INNER JOIN sys.types tp ON c.user_type_id = tp.user_type_id
WHERE t.schema_id = SCHEMA_ID('dbo')
ORDER BY t.name, c.column_id;

-- =============================================================================
-- 14. Temporal Table — 时态表（系统版本化） [BLOCKER]
-- =============================================================================
-- 困难点：PG/KB 需要手动实现历史表 + 触发器，DM8 部分支持

-- 14.1 创建时态表
CREATE TABLE dbo.ProductHistory (
    product_id     INT NOT NULL,
    product_name   NVARCHAR(200) NOT NULL,
    unit_price     DECIMAL(10,2) NOT NULL,
    stock_quantity INT NOT NULL,
    valid_from     DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    valid_to       DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
)
WITH (SYSTEM_VERSIONING = ON (
    HISTORY_TABLE = dbo.ProductHistory_Archive,
    HISTORY_RETENTION_PERIOD = 2 YEARS
));

-- 14.2 查询时态数据
SELECT * FROM dbo.ProductHistory
FOR SYSTEM_TIME AS OF '2024-06-01';

SELECT * FROM dbo.ProductHistory
FOR SYSTEM_TIME BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY valid_from;

SELECT * FROM dbo.ProductHistory
FOR SYSTEM_TIME FROM '2024-01-01' TO '2024-07-01';

SELECT * FROM dbo.ProductHistory
FOR SYSTEM_TIME CONTAINED IN ('2024-03-01', '2024-06-30');

SELECT * FROM dbo.ProductHistory
FOR SYSTEM_TIME ALL;

-- =============================================================================
-- 15. PARTITION — 表分区 [HARD]
-- =============================================================================

-- 15.1 创建分区函数和分区方案
CREATE PARTITION FUNCTION pf_OrderDate (DATETIME2)
AS RANGE RIGHT FOR VALUES (
    '2023-01-01', '2023-04-01', '2023-07-01', '2023-10-01',
    '2024-01-01', '2024-04-01', '2024-07-01', '2024-10-01'
);

CREATE PARTITION SCHEME ps_OrderDate
AS PARTITION pf_OrderDate ALL TO ([PRIMARY]);

-- 15.2 分区表
CREATE TABLE dbo.OrderPartitioned (
    order_id   INT IDENTITY(1,1) PRIMARY KEY,
    order_date DATETIME2 NOT NULL,
    customer_id INT NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL
) ON ps_OrderDate(order_date);

-- 15.3 查询分区信息
SELECT
    $PARTITION.pf_OrderDate(order_date) AS partition_number,
    COUNT(*) AS row_count,
    MIN(order_date) AS min_date,
    MAX(order_date) AS max_date
FROM dbo.OrderPartitioned
GROUP BY $PARTITION.pf_OrderDate(order_date)
ORDER BY partition_number;

-- =============================================================================
-- 16. HierarchyID — 树形结构数据类型 [BLOCKER]
-- =============================================================================
-- 困难点：PG/KB/DM8 无 HierarchyID 类型，需用 ltree (PG) 或 path 列模拟

-- 16.1 含 HierarchyID 的表
CREATE TABLE dbo.OrgNode (
    node_id     INT IDENTITY(1,1) PRIMARY KEY,
    node_path   HIERARCHYID NOT NULL,
    node_name   NVARCHAR(100) NOT NULL,
    node_level  AS node_path.GetLevel()
);

-- 16.2 插入层级数据
INSERT INTO dbo.OrgNode (node_path, node_name) VALUES
    (hierarchyid::GetRoot(), N'总公司'),
    (hierarchyid::GetRoot().GetDescendant(NULL, NULL), N'研发部'),
    (hierarchyid::GetRoot().GetDescendant(NULL, NULL), N'市场部');

-- 16.3 层级查询
SELECT
    node_path.ToString() AS path_text,
    node_name,
    node_path.GetLevel() AS level
FROM dbo.OrgNode
WHERE node_path.IsDescendantOf(hierarchyid::GetRoot()) = 1;

-- =============================================================================
-- 17. Computed Column with UDF — 计算列引用函数 [HARD]
-- =============================================================================
-- 困难点：计算列引用 UDF 导致跨对象依赖，PG 不支持持久化计算列 + UDF

-- 17.1 引用标量函数的计算列
ALTER TABLE dbo.[Order]
ADD status_label AS (dbo.fn_GetOrderStatusName(status));

-- 17.2 复杂表达式计算列
ALTER TABLE dbo.Product
ADD profit_margin AS (
    CASE WHEN cost_price > 0
         THEN CAST((unit_price - cost_price) / cost_price * 100 AS DECIMAL(5,2))
         ELSE NULL
    END
);

-- =============================================================================
-- 18. Dynamic Pivot — 动态行转列 [BLOCKER]
-- =============================================================================
-- 困难点：列名不固定，必须用动态 SQL，无法静态改写

DECLARE @cols NVARCHAR(MAX);
DECLARE @pivot_sql NVARCHAR(MAX);

-- 动态生成列名（所有地区）
SELECT @cols = STRING_AGG(QUOTENAME(region), ', ')
FROM (SELECT DISTINCT region FROM dbo.Customer) t;

-- 动态构建 PIVOT 查询
SET @pivot_sql = N'
SELECT * FROM (
    SELECT c.region, YEAR(o.order_date) AS order_year, o.actual_amount
    FROM dbo.[Order] o
    INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
    WHERE o.status NOT IN (N''已取消'', N''已退款'')
) src
PIVOT (
    SUM(actual_amount)
    FOR region IN (' + @cols + N')
) pvt
ORDER BY order_year';

EXEC sp_executesql @pivot_sql;

-- =============================================================================
-- 19. CROSS APPLY with Table-Valued Function Chain [HARD]
-- =============================================================================

-- 19.1 多个 CROSS APPLY 串联
SELECT
    c.full_name,
    orders.order_no,
    orders.actual_amount,
    level_calc.level_name,
    discount_calc.suggested_discount
FROM dbo.Customer c
CROSS APPLY dbo.fn_GetCustomerOrders(c.customer_id) orders
CROSS APPLY (
    SELECT CASE
        WHEN orders.actual_amount > 10000 THEN N'大额订单'
        WHEN orders.actual_amount > 1000  THEN N'普通订单'
        ELSE N'小额订单'
    END AS level_name
) level_calc
CROSS APPLY (
    SELECT dbo.fn_GetDiscount(orders.actual_amount) AS suggested_discount
) discount_calc
WHERE c.tier = 'A'
ORDER BY orders.actual_amount DESC;

-- =============================================================================
-- 20. Implicit Conversion Traps — 隐式转换陷阱 [MEDIUM]
-- =============================================================================
-- 困难点：不同数据库的隐式转换规则不同，导致查询结果或性能差异

-- 20.1 NVARCHAR vs VARCHAR 隐式转换 — 导致索引失效
SELECT * FROM dbo.Customer
WHERE customer_code = N'CUST-001';  -- NVARCHAR 字面量，若列是 VARCHAR 则全表扫描

-- 20.2 INT vs DECIMAL 隐式转换
SELECT * FROM dbo.Product
WHERE unit_price = 100;  -- INT 字面量，隐式转 DECIMAL

-- 20.3 DATETIME vs DATETIME2 混合比较
SELECT * FROM dbo.[Order]
WHERE order_date > '2024-01-01';  -- 字符串隐式转 DATETIME2

-- 20.4 BIT 与 INT 隐式转换
SELECT * FROM dbo.Product WHERE is_active = 1;   -- INT → BIT
SELECT * FROM dbo.Customer WHERE is_vip = 0;     -- INT → BIT

-- =============================================================================
-- 21. SELECT INTO — 创建并填充新表 [MEDIUM]
-- =============================================================================
-- 困难点：PG 用 CREATE TABLE AS，KB/DM8 各有差异

SELECT
    c.customer_id,
    c.full_name,
    c.region,
    COUNT(o.order_id) AS order_count,
    ISNULL(SUM(o.actual_amount), 0) AS total_spent,
    ISNULL(AVG(o.actual_amount), 0) AS avg_order_amount,
    MAX(o.order_date) AS last_order_date,
    DATEDIFF(DAY, MAX(o.order_date), SYSDATETIME()) AS days_since_last_order
INTO dbo.CustomerAnalytics
FROM dbo.Customer c
LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                       AND o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.customer_id, c.full_name, c.region;

-- =============================================================================
-- 22. Error Handling with ERROR_* Functions [MEDIUM]
-- =============================================================================

BEGIN TRY
    -- 除以零错误
    DECLARE @result DECIMAL(10,2);
    SET @result = 100.0 / 0;
END TRY
BEGIN CATCH
    SELECT
        ERROR_NUMBER()     AS error_number,
        ERROR_SEVERITY()   AS severity,
        ERROR_STATE()      AS error_state,
        ERROR_PROCEDURE()  AS procedure_name,
        ERROR_LINE()       AS error_line,
        ERROR_MESSAGE()    AS error_message;

    -- 重新抛出原始错误
    THROW;
END CATCH;

-- =============================================================================
-- 23. Table-Valued Parameters (TVP) in Practice [HARD]
-- =============================================================================
-- 困难点：PG/KB/DM8 无 TVP，需改为 JSON 参数或临时表

-- 23.1 自定义表类型（已在 procedure.sql 中定义 OrderItemType）
-- CREATE TYPE dbo.OrderItemType AS TABLE (...)

-- 23.2 在 SP 中使用 TVP（已在 procedure.sql CreateOrder 中展示）
-- @p_items dbo.OrderItemType READONLY

-- 23.3 从应用程序传递 TVP
-- C# 示例: DataTable → SqlParameter(SqlDbType.Structured)
-- Java 示例: 使用 SQLServerDataTable

-- =============================================================================
-- 24. Sequence with CYCLE and CACHE [EASY]
-- =============================================================================

-- 已创建: CREATE SEQUENCE dbo.OrderSeq AS INT ... CYCLE
-- 使用 NEXT VALUE FOR
SELECT NEXT VALUE FOR dbo.OrderSeq AS next_order_num;

-- 重置序列
ALTER SEQUENCE dbo.OrderSeq RESTART WITH 1;

-- =============================================================================
-- 25. WAITFOR / PRINT / RAISERROR — 流程控制函数 [MEDIUM]
-- =============================================================================

-- 25.1 PRINT with 格式化
PRINT N'处理开始时间: ' + CONVERT(NVARCHAR(30), SYSDATETIME(), 120);
PRINT N'当前数据库: ' + DB_NAME();

-- 25.2 RAISERROR with 参数
RAISERROR(N'产品 %s 库存不足，当前库存: %d', 16, 1, N'P001', 5);

-- 25.3 THROW (推荐)
-- THROW 50001, N'自定义错误消息', 1;

-- =============================================================================
-- Migration Difficulties Coverage Summary
-- =============================================================================
-- [EASY]    Sequence CYCLE/RESTART, Multi-level CTE (chaining)
-- [MEDIUM]  WITH ROLLUP/CUBE, GROUPING SETS, Window RANGE/ROWS frame,
--           @@ERROR/@@ROWCOUNT, SET options, COLLATE, SELECT INTO,
--           ERROR_* functions, WAITFOR/PRINT/RAISERROR,
--           Implicit conversion traps
-- [HARD]    UPDATE FROM with JOIN, DELETE with JOIN,
--           CURSOR SCROLL/KEYSET/DYNAMIC, MERGE with complex WHEN,
--           OUTPUT INTO @table_var, System functions (OBJECT_ID etc.),
--           PARTITION, Computed column with UDF,
--           CROSS APPLY chain, TVP, INSERT...EXEC
-- [BLOCKER] UPDATE FROM with OUTPUT + JOIN, DELETE with OUTPUT + JOIN,
--           Temporal table (SYSTEM_VERSIONING), HierarchyID,
--           Dynamic PIVOT, FOR XML/JSON (in advanced.sql)
-- =============================================================================
