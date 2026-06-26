-- =============================================================================
-- view.sql — Views (SQL Server)
-- =============================================================================
-- Covers: Standard View, Joined View, Aggregated View, Indexed View (schema-bound)
-- =============================================================================

-- =============================================================================
-- 1. v_OrderSummary — 订单汇总视图
-- =============================================================================
-- 展示每个订单的核心信息、客户信息和订单项数量

CREATE OR ALTER VIEW dbo.v_OrderSummary
AS
SELECT
    o.order_id,
    o.order_no,
    o.order_date,
    o.status,
    dbo.fn_GetOrderStatusName(o.status) AS status_desc,
    c.customer_code,
    c.full_name                     AS customer_name,
    c.region                        AS customer_region,
    c.tier                          AS customer_tier,
    o.total_amount,
    o.discount_amount,
    o.actual_amount,
    o.shipping_addr,
    o.remark,
    o.created_at,
    o.updated_at,
    (SELECT COUNT(*) FROM dbo.OrderItem oi WHERE oi.order_id = o.order_id) AS item_count,
    (SELECT ISNULL(SUM(quantity), 0) FROM dbo.OrderItem oi WHERE oi.order_id = o.order_id) AS total_quantity
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id;
GO

-- =============================================================================
-- 2. v_SalesByRegion — 按地区销售统计视图
-- =============================================================================

CREATE OR ALTER VIEW dbo.v_SalesByRegion
AS
SELECT
    c.region                                                AS 地区,
    COUNT(DISTINCT o.order_id)                              AS 订单数,
    COUNT(DISTINCT o.customer_id)                           AS 客户数,
    SUM(o.total_amount)                                     AS 订单总金额,
    SUM(o.discount_amount)                                  AS 折扣总额,
    SUM(o.actual_amount)                                    AS 实收金额,
    CAST(AVG(o.actual_amount) AS DECIMAL(12,2))             AS 平均订单金额,
    MIN(o.order_date)                                       AS 最早订单,
    MAX(o.order_date)                                       AS 最近订单
FROM dbo.[Order] o
INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY c.region;
GO

-- =============================================================================
-- 3. v_ProductSales — 产品销售统计视图
-- =============================================================================

CREATE OR ALTER VIEW dbo.v_ProductSales
AS
SELECT
    p.product_id,
    p.product_code,
    p.product_name,
    p.category,
    p.unit_price                                     AS 当前单价,
    p.cost_price                                     AS 成本价,
    p.stock_quantity                                 AS 当前库存,
    p.min_stock                                      AS 最低库存,
    ISNULL(SUM(oi.quantity), 0)                      AS 累计销量,
    ISNULL(SUM(oi.subtotal), 0)                      AS 累计销售额,
    ISNULL(SUM(oi.subtotal * oi.discount / 100), 0)  AS 累计折扣,
    CAST(
        CASE WHEN SUM(oi.quantity) > 0
        THEN SUM(oi.subtotal * (1 - oi.discount / 100)) / SUM(oi.quantity)
        ELSE p.unit_price
        END AS DECIMAL(10,2)
    )                                                AS 平均售价,
    CASE WHEN p.stock_quantity < p.min_stock
         THEN N'⚠ 库存不足'
         ELSE N'✓ 库存正常'
    END                                              AS 库存状态
FROM dbo.Product p
LEFT JOIN dbo.OrderItem oi ON p.product_id = oi.product_id
LEFT JOIN dbo.[Order] o   ON oi.order_id = o.order_id
                         AND o.status NOT IN (N'已取消', N'已退款')
GROUP BY
    p.product_id, p.product_code, p.product_name, p.category,
    p.unit_price, p.cost_price, p.stock_quantity, p.min_stock;
GO

-- =============================================================================
-- 4. v_CustomerSummary — 客户统计视图
-- =============================================================================

CREATE OR ALTER VIEW dbo.v_CustomerSummary
AS
SELECT
    c.customer_id,
    c.customer_code,
    c.full_name,
    c.region,
    c.tier,
    CASE c.is_vip WHEN 1 THEN N'是' ELSE N'否' END AS 是否VIP,
    c.credit_limit,
    c.registered_at,
    COUNT(DISTINCT o.order_id)                       AS 总订单数,
    ISNULL(SUM(o.actual_amount), 0)                  AS 累计消费,
    ISNULL(MAX(o.order_date), c.registered_at)       AS 最近购买日期,
    DATEDIFF(DAY, ISNULL(MAX(o.order_date), c.registered_at), SYSDATETIME()) AS 距上次购买天数
FROM dbo.Customer c
LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                       AND o.status NOT IN (N'已取消', N'已退款')
GROUP BY
    c.customer_id, c.customer_code, c.full_name,
    c.region, c.tier, c.is_vip, c.credit_limit, c.registered_at;
GO

-- =============================================================================
-- 5. v_DailySales — 每日销售汇总视图
-- =============================================================================

CREATE OR ALTER VIEW dbo.v_DailySales
AS
SELECT
    CAST(o.order_date AS DATE) AS 订单日期,
    COUNT(DISTINCT o.order_id) AS 订单数,
    COUNT(DISTINCT o.customer_id) AS 下单客户数,
    SUM(o.total_amount)        AS 订单总额,
    SUM(o.discount_amount)     AS 折扣总额,
    SUM(o.actual_amount)       AS 实收金额,
    SUM(oi.total_quantity)     AS 商品总数
FROM dbo.[Order] o
OUTER APPLY (
    SELECT ISNULL(SUM(quantity), 0) AS total_quantity
    FROM dbo.OrderItem oi
    WHERE oi.order_id = o.order_id
) oi
WHERE o.status NOT IN (N'已取消', N'已退款')
GROUP BY CAST(o.order_date AS DATE);
GO

-- =============================================================================
-- 6. v_InventoryStatus — 库存状态视图
-- =============================================================================

CREATE OR ALTER VIEW dbo.v_InventoryStatus
WITH SCHEMABINDING  -- 用于创建索引视图
AS
SELECT
    p.product_id,
    p.product_code,
    p.product_name,
    p.category,
    p.stock_quantity,
    p.min_stock,
    p.stock_quantity - p.min_stock AS surplus,
    CASE
        WHEN p.stock_quantity = 0         THEN N'缺货'
        WHEN p.stock_quantity < p.min_stock THEN N'库存不足'
        WHEN p.stock_quantity < p.min_stock * 2 THEN N'库存偏低'
        ELSE N'库存正常'
    END AS stock_level,
    p.is_active
FROM dbo.Product p;
GO

-- =============================================================================
-- 7. 索引视图（Materialized View）
-- =============================================================================
-- 注: 仅企业版/开发版支持。标准版需要 WITH (NOEXPAND) 提示。

-- 先在视图上创建唯一聚集索引，使其成为索引视图
-- CREATE UNIQUE CLUSTERED INDEX IX_v_InventoryStatus_product_id
-- ON dbo.v_InventoryStatus (product_id);
-- GO

-- =============================================================================
-- 8. 调用示例
-- =============================================================================

-- SELECT * FROM dbo.v_OrderSummary WHERE customer_region = N'华东';
-- SELECT * FROM dbo.v_SalesByRegion ORDER BY 实收金额 DESC;
-- SELECT * FROM dbo.v_ProductSales WHERE 库存状态 = N'⚠ 库存不足';
-- SELECT * FROM dbo.v_CustomerSummary WHERE 距上次购买天数 > 30;
-- SELECT * FROM dbo.v_DailySales WHERE 订单日期 >= '2024-01-01' ORDER BY 订单日期;
-- SELECT * FROM dbo.v_InventoryStatus WHERE stock_level = N'缺货';

-- =============================================================================
-- View Coverage Summary
-- =============================================================================
-- Standard View              : v_OrderSummary, v_SalesByRegion, v_ProductSales
-- Aggregated View            : v_SalesByRegion, v_DailySales (GROUP BY)
-- Joined View                : v_OrderSummary (JOIN + subquery)
-- View with Function         : v_OrderSummary uses fn_GetOrderStatusName
-- View with CASE             : v_ProductSales (库存状态), v_InventoryStatus
-- CROSS/OUTER APPLY in View  : v_DailySales (OUTER APPLY)
-- SCHEMABINDING              : v_InventoryStatus (for indexed view)
-- Chinese Column Aliases     : 多视图使用中文别名
-- Indexed View               : 注释示例 (materialized view)
-- =============================================================================
