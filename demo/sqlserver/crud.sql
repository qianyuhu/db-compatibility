-- =============================================================================
-- crud.sql — CRUD Operations + MERGE (SQL Server)
-- =============================================================================
-- Covers: INSERT, UPDATE, DELETE, SELECT, MERGE (UPSERT equivalent)
-- =============================================================================

-- =============================================================================
-- 1. INSERT — 多种插入方式
-- =============================================================================

-- 1.1 标准单行 INSERT
INSERT INTO Customer (customer_code, full_name, email, phone, region, tier, credit_limit, is_vip)
VALUES (N'CUST-026', N'南宁东盟商务区管委会', N'nnasean@example.com', '0771-66668001', N'华南', 'C', 60000.00, 0);

-- 1.2 多行 INSERT
INSERT INTO Product (product_code, product_name, category, unit_price, cost_price, stock_quantity, min_stock, weight_kg)
VALUES
(N'PROD-056', N'联想 ThinkSystem SR650 服务器',  N'服务器',  42000.00, 32000.00, 5, 2, 19.000),
(N'PROD-057', N'华为 MateBook X Pro 笔记本',     N'办公设备', 8999.00,  6800.00,  30, 5, 1.300),
(N'PROD-058', N'小米 AX6000 WiFi6 路由器',       N'网络设备', 499.00,   320.00,   200, 30, 0.800);

-- 1.3 INSERT SELECT — 从已有数据复制
INSERT INTO InventoryLog (product_id, order_id, change_type, quantity_change, before_stock, after_stock, remark)
SELECT product_id, NULL, N'盘点调整', 0, stock_quantity, stock_quantity, N'初始化库存日志'
FROM Product
WHERE stock_quantity > 0;

-- 1.4 INSERT with OUTPUT — 返回插入的数据（SQL Server 专有）
INSERT INTO [Order] (order_no, customer_id, order_date, status, total_amount, discount_amount, actual_amount, shipping_addr)
OUTPUT inserted.order_id, inserted.order_no, inserted.created_at
VALUES (N'ORD-2024-0111', 1, SYSDATETIME(), N'待付款', 15000.00, 0, 15000.00, N'深圳市南山区科技园南路1号');

-- 1.5 INSERT with explicit IDENTITY_INSERT (SQL Server)
-- SET IDENTITY_INSERT Product ON;
-- INSERT INTO Product (product_id, product_code, product_name, category, unit_price, cost_price)
-- VALUES (999, N'PROD-999', N'手动ID产品', N'其他', 100.00, 50.00);
-- SET IDENTITY_INSERT Product OFF;

-- =============================================================================
-- 2. SELECT — 多种查询方式
-- =============================================================================

-- 2.1 简单 SELECT
SELECT * FROM Customer WHERE tier = 'A';

-- 2.2 SELECT with TOP (SQL Server)
SELECT TOP 10 * FROM [Order] ORDER BY total_amount DESC;

-- 2.3 SELECT 指定列
SELECT customer_id, customer_code, full_name, region, tier FROM Customer WHERE is_vip = 1;

-- 2.4 SELECT with computed column
SELECT item_id, order_id, product_id, quantity, unit_price, subtotal, discount
FROM OrderItem
WHERE subtotal > 5000;

-- 2.5 SELECT with alias
SELECT
    c.customer_code  AS 客户编码,
    c.full_name      AS 客户名称,
    c.region         AS 地区,
    c.tier           AS 等级,
    c.credit_limit   AS 信用额度
FROM Customer c
WHERE c.credit_limit >= 100000;

-- 2.6 SELECT with ISNULL / COALESCE
SELECT
    product_code,
    product_name,
    ISNULL(CAST(weight_kg AS NVARCHAR(20)), N'无重量数据') AS 重量信息,
    COALESCE(remark, N'无备注') AS 备注
FROM Product;

-- =============================================================================
-- 3. UPDATE — 多种更新方式
-- =============================================================================

-- 3.1 标准 UPDATE
UPDATE Customer
SET credit_limit = 250000.00, tier = 'A', is_vip = 1
WHERE customer_code = 'CUST-013';

-- 3.2 UPDATE with JOIN
UPDATE p
SET p.unit_price = p.unit_price * 1.05,
    p.updated_at = SYSDATETIME()
FROM Product p
INNER JOIN (
    SELECT DISTINCT oi.product_id
    FROM OrderItem oi
    INNER JOIN [Order] o ON oi.order_id = o.order_id
    WHERE o.order_date >= '2024-06-01'
) hot ON p.product_id = hot.product_id;

-- 3.3 UPDATE with OUTPUT (SQL Server 专有)
UPDATE Product
SET stock_quantity = stock_quantity + 50,
    updated_at = SYSDATETIME()
OUTPUT inserted.product_id, deleted.stock_quantity AS old_stock, inserted.stock_quantity AS new_stock
WHERE stock_quantity < min_stock AND is_active = 1;

-- 3.4 UPDATE with CASE
UPDATE Customer
SET credit_limit = CASE
    WHEN tier = 'A' THEN credit_limit * 1.2
    WHEN tier = 'B' THEN credit_limit * 1.1
    WHEN tier = 'C' THEN credit_limit * 1.05
    ELSE credit_limit
END
WHERE is_vip = 1;

-- =============================================================================
-- 4. DELETE — 多种删除方式
-- =============================================================================

-- 4.1 标准 DELETE (有外键约束，实际业务中多为软删除)
DELETE FROM InventoryLog
WHERE created_at < '2023-01-01';

-- 4.2 DELETE with JOIN
DELETE oi
FROM OrderItem oi
INNER JOIN [Order] o ON oi.order_id = o.order_id
WHERE o.status = N'已取消'
  AND o.order_date < '2024-01-01';

-- 4.3 DELETE with OUTPUT (SQL Server 专有)
DELETE FROM InventoryLog
OUTPUT deleted.log_id, deleted.product_id, deleted.change_type, deleted.created_at
WHERE created_at < '2023-06-01';

-- 4.4 TRUNCATE (不能用于有 FK 引用的表，这里用于日志表)
-- TRUNCATE TABLE InventoryLog;  -- 业务中慎用，会忽略 DELETE 触发器

-- =============================================================================
-- 5. MERGE — UPSERT (SQL Server 专有，功能等价 INSERT ... ON CONFLICT)
-- =============================================================================

-- 5.1 MERGE: 根据 product_code 匹配，存在则更新，不存在则插入
MERGE INTO Product AS target
USING (VALUES
    (N'PROD-001', N'STM32F407VET6 微控制器 V2', N'电子元器件', 72.00, 44.00),
    (N'PROD-059', N'树莓派 5 8GB 开发板',          N'电子元器件', 480.00, 380.00)
) AS source (product_code, product_name, category, unit_price, cost_price)
ON target.product_code = source.product_code
WHEN MATCHED THEN
    UPDATE SET
        product_name = source.product_name,
        unit_price   = source.unit_price,
        cost_price   = source.cost_price,
        updated_at   = SYSDATETIME()
WHEN NOT MATCHED BY TARGET THEN
    INSERT (product_code, product_name, category, unit_price, cost_price, stock_quantity, min_stock)
    VALUES (source.product_code, source.product_name, source.category,
            source.unit_price, source.cost_price, 100, 20)
OUTPUT $action AS merge_action, inserted.product_id, inserted.product_code;

-- 5.2 MERGE with DELETE (清理不再需要的记录)
-- MERGE INTO Product AS target
-- USING source_table AS source
-- ON target.product_code = source.product_code
-- WHEN NOT MATCHED BY SOURCE THEN
--     DELETE;

-- =============================================================================
-- 6. Additional INSERT patterns
-- =============================================================================

-- 6.1 INSERT with DEFAULT VALUES
INSERT INTO InventoryLog (product_id, change_type, quantity_change, before_stock, after_stock)
VALUES (1, N'入库', 100, 100, 200);

-- 6.2 INSERT 忽略某些列（使用 DEFAULT）
INSERT INTO Customer (customer_code, full_name, email, region)
VALUES (N'CUST-027', N'银川经济技术开发区', N'yckf@example.com', N'西北');
-- credit_limit 使用 DEFAULT 50000, tier DEFAULT 'C', is_vip DEFAULT 0

-- =============================================================================
-- CRUD Coverage Summary
-- =============================================================================
-- INSERT              : 单行, 多行, INSERT SELECT, INSERT OUTPUT, DEFAULT VALUES
-- SELECT              : 简单查询, TOP, 别名, ISNULL/COALESCE, 计算列
-- UPDATE              : 标准, JOIN, OUTPUT, CASE
-- DELETE              : 标准, JOIN, OUTPUT
-- MERGE               : INSERT+UPDATE (UPSERT), $action
-- =============================================================================
