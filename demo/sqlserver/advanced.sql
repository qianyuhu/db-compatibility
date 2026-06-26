-- =============================================================================
-- advanced.sql — SQL Server Dialect Features (Advanced)
-- =============================================================================
-- Covers: SQL Server 专有/方言特性
-- TOP, OUTPUT, MERGE, IDENTITY functions, Date/String functions,
-- CROSS APPLY, OUTER APPLY, WITH (NOLOCK), PIVOT, UNPIVOT,
-- FOR XML, FOR JSON, Temp Tables, Table Variables, CTE,
-- Recursive CTE, Dynamic SQL, EXEC, sp_executesql
-- =============================================================================

-- =============================================================================
-- 1. TOP — 限制返回行数（SQL Server 专有语法）
-- =============================================================================

-- 1.1 TOP with constant
SELECT TOP 5 * FROM dbo.[Order] ORDER BY actual_amount DESC;

-- 1.2 TOP with PERCENT
SELECT TOP 20 PERCENT * FROM dbo.Customer ORDER BY credit_limit DESC;

-- 1.3 TOP with TIES
SELECT TOP 5 WITH TIES product_name, unit_price
FROM dbo.Product
ORDER BY unit_price DESC;

-- 1.4 TOP with variable
DECLARE @top_n INT = 10;
SELECT TOP (@top_n) * FROM dbo.[Order] ORDER BY order_date DESC;

-- =============================================================================
-- 2. OUTPUT Clause — 返回 DML 影响的行（SQL Server 专有）
-- =============================================================================

-- 2.1 INSERT OUTPUT
INSERT INTO dbo.[Order] (order_no, customer_id, status, total_amount, discount_amount, actual_amount)
OUTPUT inserted.order_id, inserted.order_no, inserted.created_at
VALUES (N'ORD-ADV-001', 1, N'待付款', 5000.00, 0, 5000.00);

-- 2.2 DELETE OUTPUT
DELETE FROM dbo.InventoryLog
OUTPUT deleted.log_id, deleted.product_id, deleted.created_at
WHERE created_at < '2023-01-01';

-- 2.3 UPDATE OUTPUT — 同时获取旧值和新值
UPDATE dbo.Product
SET unit_price = unit_price * 1.10,
    updated_at = SYSDATETIME()
OUTPUT
    inserted.product_id,
    deleted.unit_price  AS old_price,
    inserted.unit_price AS new_price
WHERE category = N'电子元器件';

-- 2.4 MERGE OUTPUT
-- (See crud.sql MERGE example with $action)

-- =============================================================================
-- 3. IDENTITY Functions — 标识值函数
-- =============================================================================

-- 3.1 SCOPE_IDENTITY() — 当前作用域最后插入的标识值（推荐）
INSERT INTO dbo.[Order] (order_no, customer_id, status, total_amount, discount_amount, actual_amount)
VALUES (N'ORD-ADV-002', 2, N'待付款', 8000.00, 0, 8000.00);
SELECT SCOPE_IDENTITY() AS last_order_id;

-- 3.2 @@IDENTITY — 当前会话最后插入的标识值（可能被触发器影响）
SELECT @@IDENTITY AS session_last_identity;

-- 3.3 IDENT_CURRENT() — 指定表的最后标识值（不受作用域限制）
SELECT IDENT_CURRENT('dbo.[Order]') AS order_last_identity;

-- 3.4 IDENTITY_INSERT — 手动设置标识值
-- SET IDENTITY_INSERT dbo.[Order] ON;
-- INSERT INTO dbo.[Order] (order_id, order_no, customer_id, status, total_amount, discount_amount, actual_amount)
-- VALUES (9999, N'ORD-MANUAL-001', 1, N'待付款', 1000.00, 0, 1000.00);
-- SET IDENTITY_INSERT dbo.[Order] OFF;

-- 3.5 IDENTITY() function in SELECT INTO
-- SELECT
--     IDENTITY(INT, 1, 1) AS row_id,
--     product_code,
--     product_name
-- INTO #TempProduct
-- FROM dbo.Product;

-- =============================================================================
-- 4. Date/Time Functions — 日期时间函数
-- =============================================================================

-- 4.1 Current datetime
SELECT
    GETDATE()          AS getdate_value,      -- DATETIME
    SYSDATETIME()      AS sysdatetime_value,  -- DATETIME2
    GETUTCDATE()       AS getutcdate_value,
    SYSUTCDATETIME()   AS sysutcdatetime_value,
    SYSDATETIMEOFFSET() AS sysdatetimeoffset_value;

-- 4.2 Date parts
SELECT
    YEAR(order_date)   AS 年份,
    MONTH(order_date)  AS 月份,
    DAY(order_date)    AS 日,
    DATEPART(QUARTER, order_date) AS 季度,
    DATEPART(WEEKDAY, order_date) AS 星期几,
    DATENAME(WEEKDAY, order_date) AS 星期名称,
    EOMONTH(order_date) AS 月末日期
FROM dbo.[Order]
WHERE order_id = 1;

-- 4.3 Date arithmetic
SELECT
    DATEADD(DAY,   30, GETDATE()) AS 三十天后,
    DATEADD(MONTH, -1, GETDATE()) AS 一个月前,
    DATEDIFF(DAY, '2024-01-01', GETDATE()) AS 今年已过天数,
    DATEDIFF_BIG(MILLISECOND, '2000-01-01', GETDATE()) AS ms_since_2000;

-- 4.4 FORMAT (SQL Server 2012+)
SELECT
    FORMAT(GETDATE(), 'yyyy-MM-dd HH:mm:ss') AS formatted_date,
    FORMAT(GETDATE(), N'yyyy年MM月dd日 dddd', 'zh-CN') AS chinese_date,
    FORMAT(1234567.89, 'N2') AS formatted_number,
    FORMAT(1234567.89, 'C', 'zh-CN') AS chinese_currency;

-- =============================================================================
-- 5. String / Conversion Functions — 字符串与转换函数
-- =============================================================================

-- 5.1 ISNULL (SQL Server 专有) vs COALESCE (SQL Standard)
SELECT
    ISNULL(NULL, N'默认值')                    AS isnull_result,
    COALESCE(NULL, NULL, N'第一个非空')          AS coalesce_result;

-- 5.2 TRY_CONVERT / TRY_CAST (SQL Server 2012+)
SELECT
    TRY_CAST('12345' AS INT)            AS valid_cast,
    TRY_CAST('abc' AS INT)              AS invalid_cast,     -- 返回 NULL
    TRY_CONVERT(DATE, '2024-02-29')     AS valid_date,
    TRY_CONVERT(DATE, '2023-02-29')     AS invalid_date;     -- 返回 NULL

-- 5.3 CONVERT (SQL Server 专用风格)
SELECT
    CONVERT(VARCHAR, GETDATE(), 101) AS us_format,        -- MM/DD/YYYY
    CONVERT(VARCHAR, GETDATE(), 103) AS uk_format,        -- DD/MM/YYYY
    CONVERT(VARCHAR, GETDATE(), 112) AS iso_format,       -- YYYYMMDD
    CONVERT(VARCHAR, GETDATE(), 120) AS odbc_format;      -- YYYY-MM-DD HH:MI:SS

-- 5.4 NEWID() / NEWSEQUENTIALID() — UUID 生成
SELECT
    NEWID() AS random_uuid,
    CHECKSUM(NEWID()) AS uuid_checksum;

-- 5.5 STRING_AGG (SQL Server 2017+)
SELECT
    region,
    STRING_AGG(customer_code, ', ') WITHIN GROUP (ORDER BY customer_code) AS customer_list
FROM dbo.Customer
GROUP BY region;

-- 5.6 STRING_SPLIT (SQL Server 2016+)
-- SELECT value FROM STRING_SPLIT(N'Apple,Banana,Cherry', ',');

-- 5.7 CONCAT / CONCAT_WS (SQL Server 2017+)
SELECT
    CONCAT(customer_code, ' - ', full_name) AS concat_name,
    CONCAT_WS(' | ', customer_code, full_name, region, tier) AS concat_ws_name
FROM dbo.Customer
WHERE customer_id <= 5;

-- =============================================================================
-- 6. CROSS APPLY / OUTER APPLY — 交叉/外部应用（SQL Server 专有）
-- =============================================================================

-- 6.1 CROSS APPLY — 等价于 INNER JOIN 表值函数
SELECT
    c.customer_code,
    c.full_name,
    co.order_no,
    co.actual_amount
FROM dbo.Customer c
CROSS APPLY dbo.fn_GetCustomerOrders(c.customer_id) co
WHERE c.tier = 'A'
ORDER BY co.actual_amount DESC;

-- 6.2 CROSS APPLY with TOP — 每个客户的最近3个订单
SELECT
    c.full_name,
    recent.order_no,
    recent.order_date,
    recent.actual_amount
FROM dbo.Customer c
CROSS APPLY (
    SELECT TOP 3 o.order_no, o.order_date, o.actual_amount
    FROM dbo.[Order] o
    WHERE o.customer_id = c.customer_id
      AND o.status NOT IN (N'已取消', N'已退款')
    ORDER BY o.order_date DESC
) recent
WHERE c.tier IN ('A', 'B')
ORDER BY c.full_name, recent.order_date DESC;

-- 6.3 OUTER APPLY — 等价于 LEFT JOIN 表值函数
SELECT
    c.full_name,
    ISNULL(stats.total_orders, 0)   AS total_orders,
    ISNULL(stats.total_spent, 0)    AS total_spent
FROM dbo.Customer c
OUTER APPLY (
    SELECT
        COUNT(*)          AS total_orders,
        SUM(actual_amount) AS total_spent
    FROM dbo.[Order] o
    WHERE o.customer_id = c.customer_id
      AND o.status NOT IN (N'已取消', N'已退款')
) stats
ORDER BY total_spent DESC;

-- 6.4 CROSS APPLY — 拆分字符串
-- SELECT c.customer_code, s.value as tag
-- FROM dbo.Customer c
-- CROSS APPLY STRING_SPLIT(c.remark, ';') s
-- WHERE c.remark IS NOT NULL;

-- =============================================================================
-- 7. WITH (NOLOCK) — Table Hint（SQL Server 专有）
-- =============================================================================

-- 7.1 NOLOCK — 不申请共享锁（脏读可能）
SELECT order_id, order_no, status, actual_amount
FROM dbo.[Order] WITH (NOLOCK)
WHERE order_date >= '2024-10-01';

-- 7.2 READUNCOMMITTED — 等价于 NOLOCK
SELECT product_id, product_name, stock_quantity
FROM dbo.Product WITH (READUNCOMMITTED)
WHERE stock_quantity < min_stock;

-- 7.3 其他常用表提示
-- SELECT * FROM dbo.[Order] WITH (TABLOCK)     -- 表锁
-- SELECT * FROM dbo.[Order] WITH (ROWLOCK)     -- 行锁
-- SELECT * FROM dbo.[Order] WITH (UPDLOCK)     -- 更新锁
-- SELECT * FROM dbo.[Order] WITH (XLOCK)       -- 排他锁
-- SELECT * FROM dbo.[Order] WITH (READPAST)    -- 跳过锁定行

-- 设置事务隔离级别为 READ UNCOMMITTED（等价于全局 NOLOCK）
-- SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

-- =============================================================================
-- 8. PIVOT / UNPIVOT — 行列转换（SQL Server 专有）
-- =============================================================================

-- 8.1 PIVOT — 行转列：各地区各等级客户数
SELECT *
FROM (
    SELECT region, tier, customer_id
    FROM dbo.Customer
) src
PIVOT (
    COUNT(customer_id)
    FOR tier IN ([A], [B], [C], [D])
) pvt
ORDER BY region;

-- 8.2 PIVOT — 各月份各地区销售额
SELECT *
FROM (
    SELECT
        FORMAT(o.order_date, 'yyyy-MM') AS order_month,
        c.region,
        o.actual_amount
    FROM dbo.[Order] o
    INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
    WHERE o.status NOT IN (N'已取消', N'已退款')
      AND o.order_date >= '2024-01-01'
) src
PIVOT (
    SUM(actual_amount)
    FOR region IN ([华东], [华南], [华北], [华中], [西南], [西北], [东北])
) pvt
ORDER BY order_month;

-- 8.3 UNPIVOT — 列转行
-- 将 PIVOT 结果还原
SELECT product_id, category, sales_type, amount
FROM (
    SELECT
        p.product_id,
        p.category,
        ISNULL(SUM(CASE WHEN c.region = N'华东' THEN oi.subtotal END), 0) AS 华东,
        ISNULL(SUM(CASE WHEN c.region = N'华南' THEN oi.subtotal END), 0) AS 华南
    FROM dbo.Product p
    LEFT JOIN dbo.OrderItem oi ON p.product_id = oi.product_id
    LEFT JOIN dbo.[Order] o ON oi.order_id = o.order_id
    LEFT JOIN dbo.Customer c ON o.customer_id = c.customer_id
    WHERE p.product_id <= 10
    GROUP BY p.product_id, p.category
) src
UNPIVOT (
    amount FOR sales_type IN ([华东], [华南])
) unpvt
ORDER BY product_id;

-- =============================================================================
-- 9. FOR XML / FOR JSON — 数据格式转换（SQL Server 专有）
-- =============================================================================

-- 9.1 FOR XML RAW
SELECT
    customer_id,
    customer_code,
    full_name,
    region
FROM dbo.Customer
WHERE tier = 'A'
FOR XML RAW('Customer'), ROOT('Customers');

-- 9.2 FOR XML AUTO
SELECT
    o.order_id,
    o.order_no,
    c.full_name,
    o.actual_amount
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.order_id <= 5
FOR XML AUTO, ELEMENTS;

-- 9.3 FOR XML PATH — 自定义XML结构
SELECT
    customer_code AS '@Code',
    full_name     AS '@Name',
    region        AS 'Location/Region',
    tier          AS 'Location/Tier'
FROM dbo.Customer
WHERE customer_id <= 5
FOR XML PATH('Client'), ROOT('Data');

-- 9.4 FOR JSON AUTO (SQL Server 2016+)
SELECT TOP 3
    o.order_id,
    o.order_no,
    o.status,
    o.actual_amount
FROM dbo.[Order] o
FOR JSON AUTO;

-- 9.5 FOR JSON PATH — 自定义 JSON 结构
SELECT TOP 3
    c.customer_code AS 'customer.code',
    c.full_name     AS 'customer.name',
    c.region        AS 'customer.region',
    o.order_no      AS 'orders[0].order_no',
    o.actual_amount AS 'orders[0].amount'
FROM dbo.Customer c
INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
WHERE c.tier = 'A'
FOR JSON PATH;

-- 9.6 JSON_VALUE / JSON_QUERY / OPENJSON (SQL Server 2016+)
-- DECLARE @json NVARCHAR(MAX) = N'{"name":"测试","items":[{"id":1},{"id":2}]}';
-- SELECT JSON_VALUE(@json, '$.name') AS name;
-- SELECT * FROM OPENJSON(@json, '$.items') WITH (id INT);

-- =============================================================================
-- 10. Temp Tables — 临时表
-- =============================================================================

-- 10.1 本地临时表 (#)
CREATE TABLE #TempCustomerSummary (
    customer_id   INT,
    full_name     NVARCHAR(100),
    region        NVARCHAR(50),
    order_count   INT,
    total_spent   DECIMAL(14,2)
);

INSERT INTO #TempCustomerSummary (customer_id, full_name, region, order_count, total_spent)
SELECT
    c.customer_id,
    c.full_name,
    c.region,
    COUNT(o.order_id),
    ISNULL(SUM(o.actual_amount), 0)
FROM dbo.Customer c
LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                       AND o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.customer_id, c.full_name, c.region;

-- 从临时表查询
SELECT * FROM #TempCustomerSummary WHERE order_count > 0 ORDER BY total_spent DESC;

-- 更新临时表
UPDATE #TempCustomerSummary
SET total_spent = total_spent * 1.1
WHERE region = N'华东';

DROP TABLE #TempCustomerSummary;

-- 10.2 SELECT INTO 临时表
SELECT
    p.product_id,
    p.product_name,
    p.category,
    ISNULL(SUM(oi.quantity), 0) AS total_sold,
    ISNULL(SUM(oi.subtotal), 0) AS total_revenue
INTO #ProductSales
FROM dbo.Product p
LEFT JOIN dbo.OrderItem oi ON p.product_id = oi.product_id
GROUP BY p.product_id, p.product_name, p.category;

SELECT TOP 10 * FROM #ProductSales ORDER BY total_sold DESC;
DROP TABLE #ProductSales;

-- 10.3 全局临时表 (##) — 所有会话可见
-- CREATE TABLE ##GlobalTemp (id INT, data NVARCHAR(100));
-- INSERT INTO ##GlobalTemp VALUES (1, N'全局数据');
-- DROP TABLE ##GlobalTemp;

-- =============================================================================
-- 11. Table Variables — 表变量
-- =============================================================================

-- 11.1 声明和使用表变量
DECLARE @CustomerOrders TABLE (
    order_id       INT,
    order_no       NVARCHAR(30),
    customer_code  NVARCHAR(20),
    actual_amount  DECIMAL(12,2),
    order_date     DATETIME2
);

INSERT INTO @CustomerOrders
SELECT o.order_id, o.order_no, c.customer_code, o.actual_amount, o.order_date
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款')
  AND o.order_date >= '2024-10-01';

SELECT * FROM @CustomerOrders ORDER BY actual_amount DESC;

-- 11.2 表变量 vs 临时表对比
-- | 特性       | 临时表 (#)              | 表变量 (@)            |
-- |-----------|------------------------|-----------------------|
-- | 作用域     | 当前会话                | 当前批处理              |
-- | 事务       | 受事务影响，可回滚        | 不受事务影响            |
-- | 统计信息   | 有                      | 无                    |
-- | 索引       | 可创建                  | 仅PRIMARY KEY/UNIQUE   |
-- | 适用场景   | 大数据量，需索引          | 小数据量(<100行)，表值参数|

-- =============================================================================
-- 12. Recursive CTE — 递归公用表表达式
-- =============================================================================

-- 12.1 生成数字序列
WITH Numbers AS (
    SELECT 1 AS n
    UNION ALL
    SELECT n + 1 FROM Numbers WHERE n < 20
)
SELECT * FROM Numbers;

-- 12.2 生成日期序列
WITH DateRange AS (
    SELECT CAST('2024-01-01' AS DATE) AS dt
    UNION ALL
    SELECT DATEADD(DAY, 1, dt) FROM DateRange WHERE dt < '2024-01-31'
)
SELECT dt FROM DateRange;

-- 12.3 组织架构递归（假设有部门层级表）
-- WITH OrgHierarchy AS (
--     SELECT employee_id, manager_id, full_name, 0 AS level
--     FROM Employee WHERE manager_id IS NULL
--     UNION ALL
--     SELECT e.employee_id, e.manager_id, e.full_name, oh.level + 1
--     FROM Employee e
--     INNER JOIN OrgHierarchy oh ON e.manager_id = oh.employee_id
-- )
-- SELECT * FROM OrgHierarchy;

-- 12.4 递归 CTE with MAXRECURSION
WITH CategoryPath AS (
    SELECT
        product_id,
        product_name,
        category,
        CAST(category AS NVARCHAR(500)) AS path,
        0 AS depth
    FROM dbo.Product
    WHERE product_id = 1

    UNION ALL

    SELECT
        p.product_id,
        p.product_name,
        p.category,
        CAST(cp.path + ' > ' + p.category AS NVARCHAR(500)),
        cp.depth + 1
    FROM dbo.Product p
    INNER JOIN CategoryPath cp ON p.product_id = cp.product_id + 1
    WHERE cp.depth < 3
)
SELECT * FROM CategoryPath
OPTION (MAXRECURSION 10);

-- =============================================================================
-- 13. Dynamic SQL — 动态 SQL
-- =============================================================================

-- 13.1 EXEC() — 执行动态 SQL 字符串
DECLARE @table_name NVARCHAR(128) = 'Product';
DECLARE @sql        NVARCHAR(MAX);

SET @sql = N'SELECT COUNT(*) AS total_count FROM dbo.' + QUOTENAME(@table_name) + ';';
EXEC (@sql);

-- 13.2 sp_executesql — 参数化动态 SQL（推荐，防 SQL 注入）
DECLARE @sql2 NVARCHAR(MAX);
DECLARE @param_def NVARCHAR(500);

SET @sql2 = N'
    SELECT
        @total_count = COUNT(*),
        @avg_price   = AVG(unit_price)
    FROM dbo.Product
    WHERE category = @cat
      AND is_active = @active;
';

SET @param_def = N'
    @cat    NVARCHAR(50),
    @active BIT,
    @total_count INT OUTPUT,
    @avg_price   DECIMAL(10,2) OUTPUT
';

DECLARE @total INT, @avg DECIMAL(10,2);

EXEC sp_executesql @sql2,
     @param_def,
     @cat         = N'电子元器件',
     @active      = 1,
     @total_count = @total OUTPUT,
     @avg_price   = @avg OUTPUT;

SELECT @total AS product_count, @avg AS avg_price;

-- 13.3 动态拼接 WHERE 条件
DECLARE @where_clause NVARCHAR(MAX) = N'';
DECLARE @sql3 NVARCHAR(MAX);

-- 根据参数动态构建条件
-- IF @region IS NOT NULL
--     SET @where_clause = @where_clause + N' AND region = @region_param ';
-- IF @min_amount > 0
--     SET @where_clause = @where_clause + N' AND actual_amount >= @min_amount_param ';

-- 13.4 QUOTENAME — 安全引用对象名
SELECT
    QUOTENAME('Order')       AS safe_table,   -- [Order]
    QUOTENAME('customer_id') AS safe_column;  -- [customer_id]

-- =============================================================================
-- 14. Additional SQL Server Features
-- =============================================================================

-- 14.1 GOTO — 控制流（尽量少用）
DECLARE @counter INT = 0;
label_start:
    SET @counter = @counter + 1;
    IF @counter < 5 GOTO label_start;
PRINT N'Counter: ' + CAST(@counter AS NVARCHAR(5));

-- 14.2 WAITFOR — 延迟执行
-- WAITFOR DELAY '00:00:01';   -- 等待1秒
-- WAITFOR TIME '14:30:00';    -- 等到14:30

-- 14.3 RAISERROR — 抛出错误（旧式，推荐 THROW）
-- RAISERROR(N'这是一个自定义错误', 16, 1) WITH NOWAIT;

-- 14.4 IIF — 三元条件函数 (SQL Server 2012+)
SELECT
    product_name,
    unit_price,
    IIF(unit_price > 1000, N'高价', N'普通') AS price_label
FROM dbo.Product
WHERE product_id <= 10;

-- 14.5 CHOOSE — 索引选择 (SQL Server 2012+)
SELECT
    order_id,
    status,
    CHOOSE(
        CASE status
            WHEN N'待付款' THEN 1 WHEN N'已付款' THEN 2
            WHEN N'已发货' THEN 3 WHEN N'已完成' THEN 4
            ELSE 5
        END,
        N'⏳', N'💰', N'📦', N'✔', N'❓'
    ) AS icon
FROM dbo.[Order]
WHERE order_id <= 10;

-- 14.6 GREATEST / LEAST (SQL Server 2022+)
-- SELECT GREATEST(10, 20, 30) AS max_value;    -- 需要 SQL Server 2022
-- SELECT LEAST(10, 20, 30) AS min_value;       -- 需要 SQL Server 2022

-- 14.7 GENERATE_SERIES (SQL Server 2022+)
-- SELECT value FROM GENERATE_SERIES(1, 10);

-- 14.8 DATETRUNC (SQL Server 2022+)
-- SELECT DATETRUNC(MONTH, order_date) FROM dbo.[Order];

-- =============================================================================
-- 15. BULK INSERT / OPENROWSET — 批量数据导入
-- =============================================================================

-- BULK INSERT 从文件导入
-- BULK INSERT dbo.Customer
-- FROM 'C:\data\customers.csv'
-- WITH (
--     FIELDTERMINATOR = ',',
--     ROWTERMINATOR = '\n',
--     FIRSTROW = 2,
--     CODEPAGE = '65001'  -- UTF-8
-- );

-- OPENROWSET 查询外部数据
-- SELECT * FROM OPENROWSET(
--     'Microsoft.ACE.OLEDB.12.0',
--     'Excel 12.0;Database=C:\data\products.xlsx',
--     'SELECT * FROM [Sheet1$]'
-- );

-- =============================================================================
-- Advanced SQL Coverage Summary
-- =============================================================================
-- TOP                     : 行数限制 (WITH TIES, PERCENT, variable)
-- OUTPUT                  : DML OUTPUT (INSERTED/DELETED)
-- MERGE                   : UPSERT (crud.sql)
-- SCOPE_IDENTITY()        : 当前作用域标识值
-- @@IDENTITY              : 会话标识值
-- IDENT_CURRENT()         : 表级标识值
-- GETDATE()               : 当前日期时间
-- NEWID()                 : 随机UUID
-- ISNULL()                : 空值替换
-- TRY_CONVERT/TRY_CAST    : 安全类型转换
-- CONVERT() styles        : SQL Server 专用样式码
-- STRING_AGG              : 字符串聚合
-- STRING_SPLIT            : 字符串拆分
-- FORMAT()                : 格式化 (日期/数字)
-- CROSS APPLY             : 交叉应用 (INNER)
-- OUTER APPLY             : 外部应用 (LEFT)
-- WITH (NOLOCK)           : 脏读提示
-- PIVOT                   : 行转列
-- UNPIVOT                 : 列转行
-- FOR XML RAW/AUTO/PATH   : XML 格式输出
-- FOR JSON AUTO/PATH      : JSON 格式输出
-- Temp Table (#)          : 本地临时表
-- Global Temp (##)        : 全局临时表
-- Table Variable (@)      : 表变量
-- CTE (Recursive)         : 递归公用表表达式
-- MAXRECURSION            : 递归深度限制
-- EXEC()                  : 动态SQL
-- sp_executesql           : 参数化动态SQL
-- QUOTENAME()             : 安全引用名
-- GOTO                    : 控制流标签
-- IIF / CHOOSE            : 逻辑函数
-- RAISERROR               : 旧式错误抛出
-- BULK INSERT             : 批量导入
-- OPENROWSET              : 外部数据源
-- =============================================================================
