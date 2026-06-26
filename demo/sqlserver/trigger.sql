-- =============================================================================
-- trigger.sql — DML Triggers (SQL Server)
-- =============================================================================
-- Covers: AFTER INSERT/UPDATE/DELETE, INSTEAD OF, INSERTED/DELETED tables
-- =============================================================================

-- =============================================================================
-- 1. trg_Order_AfterInsert — 订单新增后自动扣减库存
-- =============================================================================

CREATE OR ALTER TRIGGER dbo.trg_OrderItem_AfterInsert
ON dbo.OrderItem
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    -- 游标遍历 INSERTED 表（触发器虚拟表，包含新插入的行）
    DECLARE @order_id   INT,
            @product_id INT,
            @quantity   INT,
            @old_stock  INT;

    DECLARE cur CURSOR FOR
        SELECT order_id, product_id, quantity
        FROM inserted;

    OPEN cur;
    FETCH NEXT FROM cur INTO @order_id, @product_id, @quantity;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- 扣减库存
        UPDATE dbo.Product
        SET @old_stock = stock_quantity,
            stock_quantity = stock_quantity - @quantity,
            updated_at = SYSDATETIME()
        WHERE product_id = @product_id;

        -- 记录库存变更
        INSERT INTO dbo.InventoryLog (
            product_id, order_id, change_type,
            quantity_change, before_stock, after_stock
        )
        VALUES (
            @product_id, @order_id, N'出库',
            -@quantity, @old_stock, @old_stock - @quantity
        );

        FETCH NEXT FROM cur INTO @order_id, @product_id, @quantity;
    END

    CLOSE cur;
    DEALLOCATE cur;

    PRINT N'触发器: 已处理 ' + CAST(@@ROWCOUNT AS NVARCHAR(10)) + N' 行库存扣减';
END;
GO

-- =============================================================================
-- 2. trg_Order_AfterDelete — 订单删除后自动恢复库存
-- =============================================================================

CREATE OR ALTER TRIGGER dbo.trg_Order_AfterDelete
ON dbo.[Order]
AFTER DELETE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @order_id   INT,
            @product_id INT,
            @quantity   INT,
            @old_stock  INT;

    DECLARE cur CURSOR FOR
        SELECT oi.order_id, oi.product_id, oi.quantity
        FROM dbo.OrderItem oi
        INNER JOIN deleted d ON oi.order_id = d.order_id;

    OPEN cur;
    FETCH NEXT FROM cur INTO @order_id, @product_id, @quantity;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- 恢复库存
        UPDATE dbo.Product
        SET @old_stock = stock_quantity,
            stock_quantity = stock_quantity + @quantity,
            updated_at = SYSDATETIME()
        WHERE product_id = @product_id;

        -- 记录库存恢复
        INSERT INTO dbo.InventoryLog (
            product_id, order_id, change_type,
            quantity_change, before_stock, after_stock
        )
        VALUES (
            @product_id, @order_id, N'订单删除',
            @quantity, @old_stock, @old_stock + @quantity
        );

        FETCH NEXT FROM cur INTO @order_id, @product_id, @quantity;
    END

    CLOSE cur;
    DEALLOCATE cur;

    PRINT N'触发器: 订单删除库存已恢复';
END;
GO

-- =============================================================================
-- 3. trg_Order_AfterUpdate — 订单状态变更审计
-- =============================================================================

CREATE OR ALTER TRIGGER dbo.trg_Order_AfterUpdate
ON dbo.[Order]
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- 仅记录状态变更
    IF UPDATE(status)
    BEGIN
        INSERT INTO dbo.InventoryLog (
            product_id, order_id, change_type,
            quantity_change, before_stock, after_stock, remark
        )
        SELECT
            NULL,
            i.order_id,
            N'状态变更',
            0, 0, 0,
            N'状态从 ' + d.status + N' 变为 ' + i.status
        FROM inserted i
        INNER JOIN deleted d ON i.order_id = d.order_id
        WHERE i.status <> d.status;
    END

    -- 自动记录更新时间
    IF NOT UPDATE(updated_at)
    BEGIN
        -- 这个检查避免递归触发
        -- SQL Server 默认触发器是 AFTER 触发，不会递归到自身
        -- 但通过 UPDATE() 函数可以区分列更新
        PRINT N'触发器: 订单状态变更已记录';
    END
END;
GO

-- =============================================================================
-- 4. trg_Product_InsteadOfDelete — 替代删除，防止误删产品
-- =============================================================================

CREATE OR ALTER TRIGGER dbo.trg_Product_InsteadOfDelete
ON dbo.Product
INSTEAD OF DELETE
AS
BEGIN
    SET NOCOUNT ON;

    -- 检查是否有未完成订单引用此产品
    IF EXISTS (
        SELECT 1
        FROM dbo.OrderItem oi
        INNER JOIN deleted d ON oi.product_id = d.product_id
        INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id
        WHERE o.status IN (N'待付款', N'已付款', N'已发货')
    )
    BEGIN
        THROW 50003, N'产品存在处理中的订单，禁止删除。请先处理关联订单。', 1;
        RETURN;
    END

    -- 软删除：标记为非活跃
    UPDATE dbo.Product
    SET is_active = 0,
        updated_at = SYSDATETIME()
    FROM dbo.Product p
    INNER JOIN deleted d ON p.product_id = d.product_id;

    PRINT N'触发器: 产品已软删除（is_active = 0）';
END;
GO

-- =============================================================================
-- 5. trg_Product_StockAlert — 库存预警
-- =============================================================================

CREATE OR ALTER TRIGGER dbo.trg_Product_StockAlert
ON dbo.Product
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    -- 当库存低于最低库存时记录预警
    INSERT INTO dbo.InventoryLog (
        product_id, order_id, change_type,
        quantity_change, before_stock, after_stock, remark
    )
    SELECT
        i.product_id,
        NULL,
        N'库存预警',
        0,
        d.stock_quantity,
        i.stock_quantity,
        N'库存低于最低库存 ' + CAST(i.min_stock AS NVARCHAR(10))
    FROM inserted i
    INNER JOIN deleted d ON i.product_id = d.product_id
    WHERE i.stock_quantity < i.min_stock
      AND d.stock_quantity >= d.min_stock; -- 仅首次低于阈值时触发

    IF @@ROWCOUNT > 0
        PRINT N'触发器: 库存预警记录已生成';
END;
GO

-- =============================================================================
-- 6. DDL Trigger — 数据库级别（可选）
-- =============================================================================

-- CREATE OR ALTER TRIGGER trg_DDL_PreventDropTable
-- ON DATABASE
-- FOR DROP_TABLE, ALTER_TABLE
-- AS
-- BEGIN
--     PRINT N'DDL 触发器: 禁止 DROP TABLE / ALTER TABLE';
--     ROLLBACK;
-- END;
-- GO

-- =============================================================================
-- 7. 触发器控制
-- =============================================================================

-- 禁用触发器
-- DISABLE TRIGGER dbo.trg_OrderItem_AfterInsert ON dbo.OrderItem;

-- 启用触发器
-- ENABLE TRIGGER dbo.trg_OrderItem_AfterInsert ON dbo.OrderItem;

-- 查看触发器列表
-- SELECT name, object_id, parent_id, type_desc FROM sys.triggers;

-- =============================================================================
-- Trigger Coverage Summary
-- =============================================================================
-- AFTER INSERT           : trg_OrderItem_AfterInsert — 自动扣减库存
-- AFTER DELETE           : trg_Order_AfterDelete — 自动恢复库存
-- AFTER UPDATE           : trg_Order_AfterUpdate — 状态变更审计
-- INSTEAD OF DELETE      : trg_Product_InsteadOfDelete — 软删除
-- AFTER UPDATE (条件)     : trg_Product_StockAlert — 库存预警
-- INSERTED virtual table : 新插入/更新后的行
-- DELETED virtual table  : 删除/更新前的行
-- UPDATE() function      : 检查特定列是否被更新
-- CURSOR in trigger      : 逐行处理多行操作
-- DDL Trigger            : 数据库级触发器（注释示例）
-- Trigger control        : ENABLE/DISABLE TRIGGER
-- =============================================================================
