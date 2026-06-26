-- =============================================================================
-- transaction.sql — Transaction Management (SQL Server)
-- =============================================================================
-- Covers: BEGIN TRAN, COMMIT, ROLLBACK, SAVEPOINT (SAVE TRAN), TRY...CATCH
-- =============================================================================

-- =============================================================================
-- 1. 基本事务 — BEGIN TRAN / COMMIT / ROLLBACK
-- =============================================================================

-- 1.1 简单事务 — 全部成功提交
BEGIN TRANSACTION;

    INSERT INTO [Order] (order_no, customer_id, order_date, status, total_amount, discount_amount, actual_amount, shipping_addr)
    VALUES (N'ORD-TXN-001', 1, SYSDATETIME(), N'待付款', 10000.00, 0, 10000.00, N'深圳市南山区科技园南路1号');

    DECLARE @new_order_id INT = SCOPE_IDENTITY();

    INSERT INTO OrderItem (order_id, product_id, quantity, unit_price, discount)
    VALUES (@new_order_id, 1, 10, 68.00, 0);

    INSERT INTO OrderItem (order_id, product_id, quantity, unit_price, discount)
    VALUES (@new_order_id, 2, 20, 25.00, 0);

COMMIT TRANSACTION;
PRINT N'事务 1 提交成功，订单ID: ' + CAST(@new_order_id AS NVARCHAR(10));

-- 1.2 事务回滚 — 显式 ROLLBACK
BEGIN TRANSACTION;

    INSERT INTO [Order] (order_no, customer_id, order_date, status, total_amount, discount_amount, actual_amount, shipping_addr)
    VALUES (N'ORD-TXN-002', 2, SYSDATETIME(), N'待付款', 25000.00, 0, 25000.00, N'北京市海淀区中关村大街1号');

    SET @new_order_id = SCOPE_IDENTITY();

    INSERT INTO OrderItem (order_id, product_id, quantity, unit_price, discount)
    VALUES (@new_order_id, 8, 2, 8500.00, 0);

    -- 模拟业务校验失败：超过了客户信用额度
    IF EXISTS (
        SELECT 1 FROM Customer WHERE customer_id = 2 AND credit_limit < 25000.00 + (
            SELECT ISNULL(SUM(actual_amount), 0) FROM [Order]
            WHERE customer_id = 2 AND status NOT IN (N'已取消', N'已退款')
        )
    )
    BEGIN
        ROLLBACK TRANSACTION;
        PRINT N'事务 2 回滚：超出客户信用额度';
        -- 提前退出
        RETURN;
    END

COMMIT TRANSACTION;
PRINT N'事务 2 提交成功';

-- =============================================================================
-- 2. SAVE TRANSACTION — 保存点（部分回滚）
-- =============================================================================

BEGIN TRANSACTION;

    -- 操作 A：创建订单
    INSERT INTO [Order] (order_no, customer_id, order_date, status, total_amount, discount_amount, actual_amount, shipping_addr)
    VALUES (N'ORD-TXN-003', 3, SYSDATETIME(), N'待付款', 8000.00, 0, 8000.00, N'上海市浦东新区张江路888号');

    SET @new_order_id = SCOPE_IDENTITY();
    PRINT N'订单创建成功，ID: ' + CAST(@new_order_id AS NVARCHAR(10));

    -- 设置保存点
    SAVE TRANSACTION OrderCreated;

    -- 操作 B：添加订单项（尝试扣减库存）
    BEGIN TRY
        INSERT INTO OrderItem (order_id, product_id, quantity, unit_price, discount)
        VALUES (@new_order_id, 3, 50, 380.00, 0);

        -- 模拟库存更新
        UPDATE Product
        SET stock_quantity = stock_quantity - 50,
            updated_at = SYSDATETIME()
        WHERE product_id = 3 AND stock_quantity >= 50;

        IF @@ROWCOUNT = 0
            THROW 50001, N'库存不足', 1;
    END TRY
    BEGIN CATCH
        -- 回滚到保存点，保留订单（操作 A）
        ROLLBACK TRANSACTION OrderCreated;
        PRINT N'操作B失败，回滚到保存点。错误: ' + ERROR_MESSAGE();
    END CATCH

COMMIT TRANSACTION;
PRINT N'事务 3 完成（订单保留，订单项可能已回滚）';

-- =============================================================================
-- 3. TRY...CATCH — 结构化异常处理
-- =============================================================================

-- 3.1 完整 TRY...CATCH 事务模式
BEGIN TRY
    BEGIN TRANSACTION;

        -- 检查客户是否存在
        IF NOT EXISTS (SELECT 1 FROM Customer WHERE customer_id = 999)
            THROW 50002, N'客户不存在', 1;

        INSERT INTO [Order] (order_no, customer_id, status, total_amount, discount_amount, actual_amount)
        VALUES (N'ORD-TXN-004', 999, N'待付款', 5000.00, 0, 5000.00);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    -- 检查事务是否仍打开
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;

    -- 记录错误信息
    DECLARE @ErrorMessage  NVARCHAR(4000) = ERROR_MESSAGE();
    DECLARE @ErrorSeverity INT            = ERROR_SEVERITY();
    DECLARE @ErrorState    INT            = ERROR_STATE();
    DECLARE @ErrorLine     INT            = ERROR_LINE();
    DECLARE @ErrorProc     NVARCHAR(200)  = ERROR_PROCEDURE();

    PRINT N'错误: ' + @ErrorMessage;
    PRINT N'严重级别: ' + CAST(@ErrorSeverity AS NVARCHAR(5));
    PRINT N'行号: ' + CAST(@ErrorLine AS NVARCHAR(10));
    PRINT N'存储过程: ' + ISNULL(@ErrorProc, N'无');

    -- 可以记录到错误日志表
    -- INSERT INTO ErrorLog (message, severity, state, line, procedure_name, created_at)
    -- VALUES (@ErrorMessage, @ErrorSeverity, @ErrorState, @ErrorLine, @ErrorProc, SYSDATETIME());
END CATCH;

-- =============================================================================
-- 4. 嵌套事务 — @@TRANCOUNT 行为
-- =============================================================================

-- 4.1 SQL Server 不支持真正的嵌套事务，COMMIT 仅减少 @@TRANCOUNT
-- 只有最外层的 COMMIT 才真正提交
BEGIN TRANSACTION outer_tran;
    PRINT N'@@TRANCOUNT after outer: ' + CAST(@@TRANCOUNT AS NVARCHAR(5));

    INSERT INTO [Order] (order_no, customer_id, status, total_amount, discount_amount, actual_amount)
    VALUES (N'ORD-TXN-005', 1, N'待付款', 3000.00, 0, 3000.00);

    BEGIN TRANSACTION inner_tran;
        PRINT N'@@TRANCOUNT after inner: ' + CAST(@@TRANCOUNT AS NVARCHAR(5));

        INSERT INTO OrderItem (order_id, product_id, quantity, unit_price, discount)
        VALUES (SCOPE_IDENTITY(), 4, 100, 1.50, 0);

    -- 内层 COMMIT 只减少 @@TRANCOUNT，不真正提交
    COMMIT TRANSACTION inner_tran;
    PRINT N'@@TRANCOUNT after inner commit: ' + CAST(@@TRANCOUNT AS NVARCHAR(5));

-- 外层 ROLLBACK 回滚全部
ROLLBACK TRANSACTION outer_tran;
PRINT N'@@TRANCOUNT after outer rollback: ' + CAST(@@TRANCOUNT AS NVARCHAR(5));

-- =============================================================================
-- 5. 事务隔离级别示例
-- =============================================================================

-- 5.1 READ UNCOMMITTED（脏读）
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
SELECT COUNT(*) AS 脏读订单数 FROM [Order] WITH (NOLOCK);
-- 注意：生产环境中慎用

-- 5.2 READ COMMITTED（默认）
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
SELECT COUNT(*) AS 已提交订单数 FROM [Order];

-- 5.3 REPEATABLE READ
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
BEGIN TRANSACTION;
    SELECT total_amount FROM [Order] WHERE order_id = 1;
    -- 在同一事务中再次读取，保证值不变
    SELECT total_amount FROM [Order] WHERE order_id = 1;
COMMIT TRANSACTION;

-- 5.4 SERIALIZABLE
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
BEGIN TRANSACTION;
    SELECT COUNT(*) FROM [Order] WHERE customer_id = 1;
    -- 其他事务无法插入满足此条件的行
COMMIT TRANSACTION;

-- 恢复默认
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- =============================================================================
-- 6. 分布式事务（需要 MSDTC 服务）
-- =============================================================================
-- BEGIN DISTRIBUTED TRANSACTION;
--     -- 跨数据库操作
--     UPDATE [LinkedServer].[RemoteDB].[dbo].[RemoteTable] SET col = 1;
--     UPDATE LocalTable SET col = 1;
-- COMMIT TRANSACTION;

-- =============================================================================
-- Transaction Coverage Summary
-- =============================================================================
-- BEGIN TRANSACTION    : 显式事务开始
-- COMMIT TRANSACTION   : 提交事务
-- ROLLBACK TRANSACTION : 回滚事务
-- SAVE TRANSACTION     : 保存点（部分回滚）
-- TRY...CATCH          : 结构化异常处理
-- THROW                : 抛出异常
-- @@TRANCOUNT          : 事务嵌套级别
-- @@ROWCOUNT           : 受影响行数
-- ERROR_MESSAGE()      : 错误信息
-- ERROR_SEVERITY()     : 错误严重级别
-- ERROR_STATE()        : 错误状态
-- ERROR_LINE()         : 错误行号
-- ERROR_PROCEDURE()    : 错误所在存储过程
-- SET TRANSACTION ISOLATION LEVEL : 隔离级别
-- =============================================================================
