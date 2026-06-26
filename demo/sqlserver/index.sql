-- =============================================================================
-- index.sql — Index Management (SQL Server)
-- =============================================================================
-- Covers: CLUSTERED, NONCLUSTERED, UNIQUE, COMPOSITE, FILTERED,
--         COVERING (INCLUDE), FULLTEXT, XML, COLUMNSTORE
-- =============================================================================

-- =============================================================================
-- 1. Non-Clustered Indexes — 单列索引
-- =============================================================================

-- Customer 表上的非聚集索引
CREATE NONCLUSTERED INDEX IX_Customer_Region
ON dbo.Customer (region);

CREATE NONCLUSTERED INDEX IX_Customer_Tier
ON dbo.Customer (tier)
WHERE tier IN ('A', 'B');  -- 过滤索引 (Filtered Index)

CREATE NONCLUSTERED INDEX IX_Customer_RegisteredAt
ON dbo.Customer (registered_at DESC);

-- Product 表上的非聚集索引
CREATE NONCLUSTERED INDEX IX_Product_Category
ON dbo.Product (category);

CREATE NONCLUSTERED INDEX IX_Product_IsActive
ON dbo.Product (is_active)
INCLUDE (product_code, product_name, unit_price, stock_quantity);
-- 覆盖索引：查询无需回表

-- Order 表上的非聚集索引
CREATE NONCLUSTERED INDEX IX_Order_CustomerId
ON dbo.[Order] (customer_id)
INCLUDE (order_date, status, total_amount, actual_amount);

CREATE NONCLUSTERED INDEX IX_Order_Status
ON dbo.[Order] (status)
WHERE status IN (N'待付款', N'已付款', N'已发货');
-- 过滤索引：仅索引处理中的订单

CREATE NONCLUSTERED INDEX IX_Order_OrderDate
ON dbo.[Order] (order_date DESC);

-- OrderItem 表上的非聚集索引
CREATE NONCLUSTERED INDEX IX_OrderItem_ProductId
ON dbo.OrderItem (product_id);

CREATE NONCLUSTERED INDEX IX_OrderItem_OrderId
ON dbo.OrderItem (order_id)
INCLUDE (product_id, quantity, unit_price, subtotal);

-- =============================================================================
-- 2. Composite Indexes — 组合索引
-- =============================================================================

-- Customer 多条件查询优化
CREATE NONCLUSTERED INDEX IX_Customer_Region_Tier
ON dbo.Customer (region, tier)
INCLUDE (full_name, credit_limit);

-- Product 分类+状态组合查询
CREATE NONCLUSTERED INDEX IX_Product_Category_IsActive
ON dbo.Product (category, is_active)
INCLUDE (product_code, product_name, unit_price, stock_quantity);

-- Order 客户+日期组合查询
CREATE NONCLUSTERED INDEX IX_Order_CustomerId_OrderDate
ON dbo.[Order] (customer_id, order_date DESC)
INCLUDE (status, actual_amount);

-- Order 状态+日期组合查询
CREATE NONCLUSTERED INDEX IX_Order_Status_OrderDate
ON dbo.[Order] (status, order_date DESC)
WHERE status IN (N'待付款', N'已付款');
-- 组合过滤索引

-- OrderItem 订单+产品组合查询（唯一组合，防止重复）
CREATE UNIQUE NONCLUSTERED INDEX IX_OrderItem_OrderId_ProductId
ON dbo.OrderItem (order_id, product_id);

-- =============================================================================
-- 3. Unique Indexes — 唯一索引
-- =============================================================================

-- 注意：schema.sql 中已通过 CONSTRAINT 创建了 UNIQUE 约束（自动创建唯一索引）
-- 以下展示额外的唯一索引场景

CREATE UNIQUE NONCLUSTERED INDEX IX_InventoryLog_Unique
ON dbo.InventoryLog (product_id, order_id, change_type, created_at)
WHERE order_id IS NOT NULL;
-- 条件唯一索引

-- =============================================================================
-- 4. Covering Indexes — 覆盖索引 (INCLUDE)
-- =============================================================================

-- 覆盖常用查询的所有列，避免 Key Lookup
CREATE NONCLUSTERED INDEX IX_Product_Covering
ON dbo.Product (category, is_active)
INCLUDE (
    product_code, product_name, unit_price,
    cost_price, stock_quantity, min_stock
);

-- =============================================================================
-- 5. Filtered Indexes — 过滤索引
-- =============================================================================

-- 仅对活跃产品建立索引（节省空间+提升性能）
CREATE NONCLUSTERED INDEX IX_Product_Active_Stock
ON dbo.Product (stock_quantity)
INCLUDE (product_code, product_name)
WHERE is_active = 1;

-- 仅对近3个月订单建立索引
CREATE NONCLUSTERED INDEX IX_Order_Recent
ON dbo.[Order] (order_date DESC, customer_id)
INCLUDE (status, actual_amount)
WHERE order_date >= '2024-10-01';

-- =============================================================================
-- 6. Full-Text Index — 全文索引
-- =============================================================================

-- 需要先创建全文目录
-- CREATE FULLTEXT CATALOG ftCatalog AS DEFAULT;

-- 在 Product 表上创建全文索引
-- CREATE FULLTEXT INDEX ON dbo.Product (
--     product_name LANGUAGE 2052,  -- 简体中文
--     remark      LANGUAGE 2052
-- )
-- KEY INDEX PK_Product
-- ON ftCatalog
-- WITH (CHANGE_TRACKING AUTO);

-- 全文搜索示例
-- SELECT product_id, product_name
-- FROM dbo.Product
-- WHERE CONTAINS(product_name, N'服务器');

-- SELECT product_id, product_name
-- FROM dbo.Product
-- WHERE FREETEXT(product_name, N'网络设备');

-- =============================================================================
-- 7. Columnstore Index — 列存储索引
-- =============================================================================

-- 适用于 OLAP / 分析查询
-- CREATE NONCLUSTERED COLUMNSTORE INDEX IX_OrderItem_Columnstore
-- ON dbo.OrderItem (order_id, product_id, quantity, unit_price, subtotal, discount);

-- =============================================================================
-- 8. XML Index — XML 索引
-- =============================================================================

-- 如果表中有 XML 列，可创建 XML 索引
-- 主 XML 索引
-- CREATE PRIMARY XML INDEX IX_Product_XmlPrimary
-- ON dbo.Product (xml_data_column);

-- 辅助 XML 索引 (VALUE/PATH/PROPERTY)
-- CREATE XML INDEX IX_Product_XmlValue
-- ON dbo.Product (xml_data_column)
-- USING XML INDEX IX_Product_XmlPrimary FOR VALUE;

-- =============================================================================
-- 9. Index Maintenance
-- =============================================================================

-- 查看索引信息
-- SELECT
--     i.name        AS index_name,
--     OBJECT_NAME(i.object_id) AS table_name,
--     i.type_desc   AS index_type,
--     i.is_unique   AS is_unique,
--     i.is_primary_key,
--     i.filter_definition
-- FROM sys.indexes i
-- WHERE OBJECT_NAME(i.object_id) IN ('Customer', 'Product', 'Order', 'OrderItem')
--   AND i.name IS NOT NULL
-- ORDER BY table_name, index_name;

-- 索引碎片整理
-- ALTER INDEX IX_Order_CustomerId_OrderDate ON dbo.[Order] REORGANIZE;
-- ALTER INDEX IX_Order_CustomerId_OrderDate ON dbo.[Order] REBUILD;

-- 更新统计信息
-- UPDATE STATISTICS dbo.[Order];
-- UPDATE STATISTICS dbo.[Order] IX_Order_CustomerId_OrderDate;

-- 删除索引
-- DROP INDEX IF EXISTS IX_Product_OldIndex ON dbo.Product;

-- 禁用/启用索引
-- ALTER INDEX IX_Order_Status ON dbo.[Order] DISABLE;
-- ALTER INDEX IX_Order_Status ON dbo.[Order] REBUILD;

-- =============================================================================
-- Index Coverage Summary
-- =============================================================================
-- CLUSTERED INDEX          : PK 创建时自动 (schema.sql)
-- NONCLUSTERED INDEX       : 多个单列索引
-- UNIQUE INDEX             : IX_OrderItem_OrderId_ProductId
-- COMPOSITE INDEX          : IX_Customer_Region_Tier, IX_Order_CustomerId_OrderDate
-- COVERING INDEX           : INCLUDE 列避免 Key Lookup
-- FILTERED INDEX           : WHERE 子句过滤（活跃产品、处理中订单、近期订单）
-- DESC INDEX               : IX_Order_OrderDate, IX_Order_CustomerId_OrderDate
-- FULLTEXT INDEX           : 注释示例（需全文目录）
-- COLUMNSTORE INDEX        : 注释示例（列存储）
-- XML INDEX                : 注释示例（主 XML 索引 + 辅助索引）
-- Index Maintenance        : REORGANIZE, REBUILD, UPDATE STATISTICS, DISABLE
-- =============================================================================
