-- =============================================================================
-- function.sql — User-Defined Functions (SQL Server)
-- =============================================================================
-- Covers: Scalar Function, Inline Table-Valued Function,
--         Multi-Statement Table-Valued Function
-- =============================================================================

-- =============================================================================
-- 1. Scalar Functions — 标量函数
-- =============================================================================

-- 1.1 fn_GetOrderStatusName — 获取订单状态的中文名称
CREATE OR ALTER FUNCTION dbo.fn_GetOrderStatusName(@status NVARCHAR(20))
RETURNS NVARCHAR(50)
AS
BEGIN
    DECLARE @result NVARCHAR(50);

    SET @result = CASE @status
        WHEN N'待付款' THEN N'等待买家付款'
        WHEN N'已付款' THEN N'买家已付款'
        WHEN N'已发货' THEN N'卖家已发货'
        WHEN N'已完成' THEN N'交易完成'
        WHEN N'已取消' THEN N'交易已取消'
        WHEN N'已退款' THEN N'已退款处理'
        ELSE N'未知状态'
    END;

    RETURN @result;
END;
GO

-- 1.2 fn_CalcCustomerLevel — 根据订单总额计算客户等级
CREATE OR ALTER FUNCTION dbo.fn_CalcCustomerLevel(@customer_id INT)
RETURNS CHAR(1)
AS
BEGIN
    DECLARE @total DECIMAL(14,2);
    DECLARE @level CHAR(1);

    SELECT @total = ISNULL(SUM(actual_amount), 0)
    FROM dbo.[Order]
    WHERE customer_id = @customer_id
      AND status NOT IN (N'已取消', N'已退款');

    SET @level = CASE
        WHEN @total >= 500000 THEN 'A'
        WHEN @total >= 200000 THEN 'B'
        WHEN @total >= 50000  THEN 'C'
        ELSE 'D'
    END;

    RETURN @level;
END;
GO

-- 1.3 fn_GetDiscount — 根据订单总额计算折扣率
CREATE OR ALTER FUNCTION dbo.fn_GetDiscount(@order_amount DECIMAL(12,2))
RETURNS DECIMAL(5,2)
AS
BEGIN
    DECLARE @discount DECIMAL(5,2) = 0;

    IF @order_amount >= 100000
        SET @discount = 10.00;
    ELSE IF @order_amount >= 50000
        SET @discount = 5.00;
    ELSE IF @order_amount >= 10000
        SET @discount = 2.00;
    ELSE
        SET @discount = 0;

    RETURN @discount;
END;
GO

-- =============================================================================
-- 2. Inline Table-Valued Functions — 内联表值函数
-- =============================================================================

-- 2.1 fn_GetCustomerOrders — 获取客户所有订单
CREATE OR ALTER FUNCTION dbo.fn_GetCustomerOrders(@customer_id INT)
RETURNS TABLE
AS
RETURN (
    SELECT
        o.order_id,
        o.order_no,
        o.order_date,
        o.status,
        dbo.fn_GetOrderStatusName(o.status) AS status_desc,
        o.total_amount,
        o.discount_amount,
        o.actual_amount,
        o.created_at
    FROM dbo.[Order] o
    WHERE o.customer_id = @customer_id
);
GO

-- 2.2 fn_GetProductSales — 获取产品销售统计
CREATE OR ALTER FUNCTION dbo.fn_GetProductSales(@category NVARCHAR(50) = NULL)
RETURNS TABLE
AS
RETURN (
    SELECT
        p.product_id,
        p.product_code,
        p.product_name,
        p.category,
        p.unit_price,
        ISNULL(SUM(oi.quantity), 0)                       AS total_sold,
        ISNULL(SUM(oi.subtotal * (1 - oi.discount / 100)), 0) AS total_revenue
    FROM dbo.Product p
    LEFT JOIN dbo.OrderItem oi ON p.product_id = oi.product_id
    LEFT JOIN dbo.[Order] o ON oi.order_id = o.order_id
                           AND o.status NOT IN (N'已取消', N'已退款')
    WHERE @category IS NULL OR p.category = @category
    GROUP BY p.product_id, p.product_code, p.product_name, p.category, p.unit_price
);
GO

-- 2.3 fn_TopCustomers — 获取 Top N 客户
CREATE OR ALTER FUNCTION dbo.fn_TopCustomers(@top_n INT, @region NVARCHAR(50) = NULL)
RETURNS TABLE
AS
RETURN (
    SELECT TOP (@top_n)
        c.customer_id,
        c.customer_code,
        c.full_name,
        c.region,
        c.tier,
        COUNT(DISTINCT o.order_id) AS total_orders,
        ISNULL(SUM(o.actual_amount), 0) AS total_spent
    FROM dbo.Customer c
    INNER JOIN dbo.[Order] o ON c.customer_id = o.customer_id
                            AND o.status NOT IN (N'已取消', N'已退款')
    WHERE @region IS NULL OR c.region = @region
    GROUP BY c.customer_id, c.customer_code, c.full_name, c.region, c.tier
    ORDER BY total_spent DESC
);
GO

-- =============================================================================
-- 3. Multi-Statement Table-Valued Function — 多语句表值函数
-- =============================================================================

-- 3.1 fn_GetMonthlySalesReport — 月度销售报表
CREATE OR ALTER FUNCTION dbo.fn_GetMonthlySalesReport(
    @start_date DATE,
    @end_date   DATE
)
RETURNS @ReportTable TABLE (
    report_month    CHAR(7),
    region          NVARCHAR(50),
    order_count     INT,
    total_amount    DECIMAL(14,2),
    discount_sum    DECIMAL(14,2),
    actual_amount   DECIMAL(14,2),
    avg_order       DECIMAL(12,2),
    customer_count  INT
)
AS
BEGIN
    INSERT INTO @ReportTable
    SELECT
        FORMAT(o.order_date, 'yyyy-MM')  AS report_month,
        c.region,
        COUNT(DISTINCT o.order_id)        AS order_count,
        SUM(o.total_amount)               AS total_amount,
        SUM(o.discount_amount)            AS discount_sum,
        SUM(o.actual_amount)              AS actual_amount,
        AVG(o.actual_amount)              AS avg_order,
        COUNT(DISTINCT o.customer_id)     AS customer_count
    FROM dbo.[Order] o
    INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
    WHERE o.order_date BETWEEN @start_date AND @end_date
      AND o.status NOT IN (N'已取消', N'已退款')
    GROUP BY FORMAT(o.order_date, 'yyyy-MM'), c.region
    ORDER BY report_month, region;

    RETURN;
END;
GO

-- =============================================================================
-- 4. 函数调用示例
-- =============================================================================

-- 4.1 Scalar function
-- SELECT dbo.fn_GetOrderStatusName(N'已付款') AS status_name;
-- SELECT dbo.fn_CalcCustomerLevel(1) AS customer_level;
-- SELECT dbo.fn_GetDiscount(75000.00) AS discount_rate;

-- 4.2 Inline table-valued function
-- SELECT * FROM dbo.fn_GetCustomerOrders(1);
-- SELECT * FROM dbo.fn_GetProductSales(N'电子元器件');
-- SELECT * FROM dbo.fn_TopCustomers(10, DEFAULT);
-- SELECT * FROM dbo.fn_TopCustomers(5, N'华东');

-- 4.3 Multi-statement table-valued function
-- SELECT * FROM dbo.fn_GetMonthlySalesReport('2024-01-01', '2024-12-31');

-- 4.4 CROSS APPLY with function
-- SELECT c.customer_code, c.full_name, co.*
-- FROM dbo.Customer c
-- CROSS APPLY dbo.fn_GetCustomerOrders(c.customer_id) co
-- WHERE c.tier = 'A';

-- 4.5 Scalar function in SELECT
-- SELECT
--     order_id,
--     order_no,
--     total_amount,
--     dbo.fn_GetDiscount(total_amount) AS suggested_discount
-- FROM dbo.[Order]
-- WHERE status = N'待付款';

-- =============================================================================
-- 5. 函数管理
-- =============================================================================

-- 查看函数
-- SELECT name, type_desc FROM sys.objects WHERE type IN ('FN', 'IF', 'TF');

-- 删除函数
-- DROP FUNCTION IF EXISTS dbo.fn_GetOrderStatusName;

-- 修改函数
-- ALTER FUNCTION dbo.fn_GetDiscount ...

-- =============================================================================
-- Function Coverage Summary
-- =============================================================================
-- Scalar Function                     : fn_GetOrderStatusName, fn_CalcCustomerLevel, fn_GetDiscount
-- Inline Table-Valued Function         : fn_GetCustomerOrders, fn_GetProductSales, fn_TopCustomers
-- Multi-Statement Table-Valued Function: fn_GetMonthlySalesReport
-- RETURNS TABLE                        : 内联表值函数
-- RETURNS @table_variable TABLE        : 多语句表值函数
-- DEFAULT parameters                   : @category = NULL, @region = NULL
-- TOP in function                      : TOP (@top_n) with parameter
-- CROSS APPLY with function           : 示例
-- Scalar function in SELECT           : 示例
-- CASE in function                    : 复杂条件逻辑
-- Schema-binding (not used)           : WITH SCHEMABINDING 可选
-- =============================================================================
