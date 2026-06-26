-- =============================================================================
-- procedure.sql — Stored Procedures (SQL Server)
-- =============================================================================
-- Covers: 输入参数, 输出参数, 事务, TRY...CATCH, 动态SQL, 返回值
--
-- ⚠️  CreateOrder 过程内自行管理库存扣减 + 日志写入，是 trigger 模式的替代方案。
--   若已启用 trg_OrderItem_AfterInsert，请先 DISABLE 该触发器，避免库存双扣。
--   详见 trigger.sql 头部说明。
-- =============================================================================

-- =============================================================================
-- 1. CreateOrder — 创建订单存储过程
-- =============================================================================
-- 功能：创建订单并扣减库存，使用事务保证一致性
-- 参数：
--   @p_customer_id    IN  客户ID
--   @p_shipping_addr  IN  收货地址
--   @p_remark         IN  备注
--   @p_items          IN  订单项 JSON 或 TVP
--   @p_order_id       OUT 新订单ID
--   @p_order_no       OUT 新订单号
--   @p_error_msg      OUT 错误信息
-- 返回：0=成功, 1=客户不存在, 2=库存不足, 3=其他错误
-- =============================================================================

-- 先创建订单项表类型（Table-Valued Parameter）
IF TYPE_ID('dbo.OrderItemType') IS NOT NULL
    DROP TYPE dbo.OrderItemType;
GO

CREATE TYPE dbo.OrderItemType AS TABLE (
    product_id  INT           NOT NULL,
    quantity    INT           NOT NULL,
    unit_price  DECIMAL(10,2) NOT NULL,
    discount    DECIMAL(5,2)  NOT NULL DEFAULT 0
);
GO

CREATE OR ALTER PROCEDURE dbo.CreateOrder
    @p_customer_id    INT,
    @p_shipping_addr  NVARCHAR(300),
    @p_remark         NVARCHAR(500)  = NULL,
    @p_items          dbo.OrderItemType READONLY,
    @p_order_id       INT             OUTPUT,
    @p_order_no       NVARCHAR(30)    OUTPUT,
    @p_error_msg      NVARCHAR(500)   OUTPUT
AS
BEGIN
    SET NOCOUNT ON;

    -- 初始化输出参数
    SET @p_order_id  = NULL;
    SET @p_order_no  = NULL;
    SET @p_error_msg = NULL;

    -- 参数校验
    IF @p_customer_id IS NULL OR @p_customer_id <= 0
    BEGIN
        SET @p_error_msg = N'无效的客户ID';
        RETURN 4;
    END

    IF NOT EXISTS (SELECT 1 FROM dbo.Customer WHERE customer_id = @p_customer_id)
    BEGIN
        SET @p_error_msg = N'客户不存在';
        RETURN 1;
    END

    IF NOT EXISTS (SELECT 1 FROM @p_items)
    BEGIN
        SET @p_error_msg = N'订单项不能为空';
        RETURN 4;
    END

    BEGIN TRY
        BEGIN TRANSACTION;

            -- 生成订单号
            SET @p_order_no = 'ORD-' + FORMAT(SYSDATETIME(), 'yyyyMMdd') + '-'
                            + RIGHT('0000' + CAST(NEXT VALUE FOR dbo.OrderSeq AS NVARCHAR(5)), 5);

            -- 计算订单总额（从订单项汇总）
            DECLARE @total_amount    DECIMAL(12,2);
            DECLARE @discount_amount DECIMAL(12,2) = 0;

            SELECT
                @total_amount    = SUM(quantity * unit_price),
                @discount_amount = SUM(quantity * unit_price * discount / 100.0)
            FROM @p_items;

            -- 创建订单
            INSERT INTO dbo.[Order] (
                order_no, customer_id, order_date, status,
                total_amount, discount_amount, actual_amount,
                shipping_addr, remark
            )
            VALUES (
                @p_order_no, @p_customer_id, SYSDATETIME(), N'待付款',
                @total_amount, @discount_amount, @total_amount - @discount_amount,
                @p_shipping_addr, @p_remark
            );

            -- 获取新订单ID
            SET @p_order_id = SCOPE_IDENTITY();

            -- 插入订单项（同时验证库存）
            INSERT INTO dbo.OrderItem (order_id, product_id, quantity, unit_price, discount)
            SELECT @p_order_id, i.product_id, i.quantity, i.unit_price, i.discount
            FROM @p_items i;

            -- 扣减库存（逐行检查）
            DECLARE @product_id INT, @quantity INT;
            DECLARE item_cursor CURSOR FOR
                SELECT product_id, quantity FROM @p_items;

            OPEN item_cursor;
            FETCH NEXT FROM item_cursor INTO @product_id, @quantity;

            WHILE @@FETCH_STATUS = 0
            BEGIN
                DECLARE @old_stock INT;

                UPDATE dbo.Product
                SET @old_stock = stock_quantity,
                    stock_quantity = stock_quantity - @quantity,
                    updated_at = SYSDATETIME()
                WHERE product_id = @product_id
                  AND stock_quantity >= @quantity;

                IF @@ROWCOUNT = 0
                BEGIN
                    -- 库存不足
                    DECLARE @prod_name NVARCHAR(200);
                    SELECT @prod_name = product_name FROM dbo.Product WHERE product_id = @product_id;

                    SET @p_error_msg = N'库存不足: ' + ISNULL(@prod_name, N'未知产品')
                                     + N' (产品ID=' + CAST(@product_id AS NVARCHAR(10)) + N')';

                    -- 抛出异常触发 CATCH
                    THROW 50001, @p_error_msg, 1;
                END

                -- 记录库存变更日志
                INSERT INTO dbo.InventoryLog (
                    product_id, order_id, change_type,
                    quantity_change, before_stock, after_stock
                )
                VALUES (
                    @product_id, @p_order_id, N'出库',
                    -@quantity, @old_stock, @old_stock - @quantity
                );

                FETCH NEXT FROM item_cursor INTO @product_id, @quantity;
            END

            CLOSE item_cursor;
            DEALLOCATE item_cursor;

        COMMIT TRANSACTION;

        RETURN 0; -- 成功
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        IF @p_error_msg IS NULL
            SET @p_error_msg = ERROR_MESSAGE();

        SET @p_order_id = NULL;
        SET @p_order_no = NULL;

        RETURN 3; -- 系统错误
    END CATCH
END;
GO

-- =============================================================================
-- 2. CancelOrder — 取消订单存储过程
-- =============================================================================
-- 功能：取消订单，恢复库存，记录日志
-- 参数：
--   @p_order_id    IN  订单ID
--   @p_reason      IN  取消原因
--   @p_result      OUT 操作结果描述
-- 返回：0=成功, 1=订单不存在, 2=订单状态不允许取消, 3=系统错误
-- =============================================================================

CREATE OR ALTER PROCEDURE dbo.CancelOrder
    @p_order_id  INT,
    @p_reason    NVARCHAR(200)  = NULL,
    @p_result    NVARCHAR(500)  OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @p_result = NULL;

    BEGIN TRY
        -- 检查订单是否存在
        IF NOT EXISTS (SELECT 1 FROM dbo.[Order] WHERE order_id = @p_order_id)
        BEGIN
            SET @p_result = N'订单不存在';
            RETURN 1;
        END

        -- 检查订单状态
        DECLARE @current_status NVARCHAR(20);
        SELECT @current_status = status FROM dbo.[Order] WHERE order_id = @p_order_id;

        IF @current_status IN (N'已取消', N'已退款')
        BEGIN
            SET @p_result = N'订单已处于' + @current_status + N'状态，无法再次取消';
            RETURN 2;
        END

        IF @current_status = N'已完成'
        BEGIN
            SET @p_result = N'已完成订单不可取消，请走退货流程';
            RETURN 2;
        END

        BEGIN TRANSACTION;

            -- 更新订单状态
            UPDATE dbo.[Order]
            SET status = N'已取消',
                updated_at = SYSDATETIME(),
                remark = ISNULL(remark + N'; ', N'') + N'取消原因: ' + ISNULL(@p_reason, N'未提供')
            WHERE order_id = @p_order_id;

            -- 恢复库存（逐项恢复）
            DECLARE @product_id INT, @quantity INT;
            DECLARE item_restore_cursor CURSOR FOR
                SELECT product_id, quantity
                FROM dbo.OrderItem
                WHERE order_id = @p_order_id;

            OPEN item_restore_cursor;
            FETCH NEXT FROM item_restore_cursor INTO @product_id, @quantity;

            WHILE @@FETCH_STATUS = 0
            BEGIN
                DECLARE @stock_before INT;

                UPDATE dbo.Product
                SET @stock_before = stock_quantity,
                    stock_quantity = stock_quantity + @quantity,
                    updated_at = SYSDATETIME()
                WHERE product_id = @product_id;

                -- 记录库存恢复日志
                INSERT INTO dbo.InventoryLog (
                    product_id, order_id, change_type,
                    quantity_change, before_stock, after_stock
                )
                VALUES (
                    @product_id, @p_order_id, N'订单取消',
                    @quantity, @stock_before, @stock_before + @quantity
                );

                FETCH NEXT FROM item_restore_cursor INTO @product_id, @quantity;
            END

            CLOSE item_restore_cursor;
            DEALLOCATE item_restore_cursor;

        COMMIT TRANSACTION;

        SET @p_result = N'订单 ' + CAST(@p_order_id AS NVARCHAR(10)) + N' 已成功取消';
        RETURN 0;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        SET @p_result = N'取消订单失败: ' + ERROR_MESSAGE();
        RETURN 3;
    END CATCH
END;
GO

-- =============================================================================
-- 3. GetCustomerOrders — 查询客户订单（分页）
-- =============================================================================

CREATE OR ALTER PROCEDURE dbo.GetCustomerOrders
    @p_customer_id  INT,
    @p_page         INT            = 1,
    @p_page_size    INT            = 20,
    @p_total_count  INT            OUTPUT
AS
BEGIN
    SET NOCOUNT ON;

    -- 计算总数
    SELECT @p_total_count = COUNT(*)
    FROM dbo.[Order]
    WHERE customer_id = @p_customer_id;

    -- 分页查询（OFFSET FETCH）
    SELECT
        o.order_id,
        o.order_no,
        o.order_date,
        o.status,
        o.total_amount,
        o.discount_amount,
        o.actual_amount,
        oi_count.item_count
    FROM dbo.[Order] o
    OUTER APPLY (
        SELECT COUNT(*) AS item_count
        FROM dbo.OrderItem oi
        WHERE oi.order_id = o.order_id
    ) oi_count
    WHERE o.customer_id = @p_customer_id
    ORDER BY o.order_date DESC
    OFFSET (@p_page - 1) * @p_page_size ROWS
    FETCH NEXT @p_page_size ROWS ONLY;
END;
GO

-- =============================================================================
-- 4. 调用示例（Execute Examples）
-- =============================================================================

-- 4.1 调用 CreateOrder
/*
DECLARE @items dbo.OrderItemType;
INSERT INTO @items (product_id, quantity, unit_price, discount) VALUES (1, 5, 68.00, 0);
INSERT INTO @items (product_id, quantity, unit_price, discount) VALUES (2, 10, 25.00, 5.0);

DECLARE @order_id INT, @order_no NVARCHAR(30), @error_msg NVARCHAR(500), @ret INT;

EXEC @ret = dbo.CreateOrder
    @p_customer_id   = 1,
    @p_shipping_addr = N'深圳市南山区科技园南路1号',
    @p_remark        = N'通过存储过程创建',
    @p_items         = @items,
    @p_order_id      = @order_id OUTPUT,
    @p_order_no      = @order_no OUTPUT,
    @p_error_msg     = @error_msg OUTPUT;

SELECT @ret AS return_code, @order_id AS new_order_id, @order_no AS order_no, @error_msg AS error_msg;
*/

-- 4.2 调用 CancelOrder
/*
DECLARE @result NVARCHAR(500), @cancel_ret INT;

EXEC @cancel_ret = dbo.CancelOrder
    @p_order_id = 1,
    @p_reason   = N'客户主动取消',
    @p_result   = @result OUTPUT;

SELECT @cancel_ret AS return_code, @result AS result_msg;
*/

-- 4.3 调用 GetCustomerOrders
/*
DECLARE @total INT;

EXEC dbo.GetCustomerOrders
    @p_customer_id = 1,
    @p_page        = 1,
    @p_page_size   = 10,
    @p_total_count = @total OUTPUT;

SELECT @total AS total_orders;
*/

-- =============================================================================
-- Stored Procedure Coverage Summary
-- =============================================================================
-- CREATE PROCEDURE      : 创建存储过程
-- ALTER PROCEDURE       : 修改存储过程
-- INPUT parameters      : @p_customer_id, @p_shipping_addr, @p_remark
-- OUTPUT parameters     : @p_order_id, @p_order_no, @p_error_msg, @p_result
-- DEFAULT values        : @p_remark = NULL
-- RETURN values         : 0/1/2/3/4 状态码
-- Table-Valued Param    : dbo.OrderItemType (READONLY)
-- TRY...CATCH           : 结构化错误处理
-- THROW                 : 抛出业务异常
-- CURSOR                : 逐行处理库存
-- SET NOCOUNT ON        : 抑制受影响行数
-- SCOPE_IDENTITY()      : 获取当前作用域标识值
-- FORMAT()              : 日期格式化
-- NEXT VALUE FOR        : Sequence 获取序列值
-- OFFSET FETCH          : 分页
-- OUTER APPLY           : 关联子查询
-- =============================================================================
