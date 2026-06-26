-- =============================================================================
-- schema.sql — Order Management System Schema (SQL Server)
-- =============================================================================
-- Covers: PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, DEFAULT, IDENTITY, INDEX
-- Tables: Customer, Product, [Order], OrderItem
-- =============================================================================

-- -------------------------------------------------------------------------
-- Customer Table
-- -------------------------------------------------------------------------
CREATE TABLE Customer (
    customer_id     INT IDENTITY(1,1) PRIMARY KEY,
    customer_code   VARCHAR(20)  NOT NULL,
    full_name       NVARCHAR(100) NOT NULL,
    email           NVARCHAR(200) NOT NULL,
    phone           VARCHAR(30)  NULL,
    region          NVARCHAR(50)  NOT NULL DEFAULT N'华东',
    tier            CHAR(1)      NOT NULL DEFAULT 'C'
                        CHECK (tier IN ('A','B','C','D')),
    credit_limit    DECIMAL(12,2) NOT NULL DEFAULT 50000.00
                        CHECK (credit_limit >= 0),
    is_vip          BIT          NOT NULL DEFAULT 0,
    registered_at   DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    remark          NVARCHAR(500) NULL,

    -- Constraints
    CONSTRAINT uq_customer_code UNIQUE (customer_code),
    CONSTRAINT uq_customer_email UNIQUE (email),
    CONSTRAINT ck_customer_phone CHECK (
        phone IS NULL OR LEN(phone) >= 7
    )
);

-- -------------------------------------------------------------------------
-- Product Table
-- -------------------------------------------------------------------------
CREATE TABLE Product (
    product_id      INT IDENTITY(1000,1) PRIMARY KEY,
    product_code    VARCHAR(30)  NOT NULL,
    product_name    NVARCHAR(200) NOT NULL,
    category        NVARCHAR(50)  NOT NULL,
    unit_price      DECIMAL(10,2) NOT NULL
                        CHECK (unit_price > 0),
    cost_price      DECIMAL(10,2) NOT NULL
                        CHECK (cost_price >= 0),
    stock_quantity  INT          NOT NULL DEFAULT 0
                        CHECK (stock_quantity >= 0),
    min_stock       INT          NOT NULL DEFAULT 10
                        CHECK (min_stock >= 0),
    is_active       BIT          NOT NULL DEFAULT 1,
    weight_kg       DECIMAL(8,3) NULL
                        CHECK (weight_kg IS NULL OR weight_kg > 0),
    created_at      DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    updated_at      DATETIME2    NULL,

    -- Constraints
    CONSTRAINT uq_product_code UNIQUE (product_code),
    CONSTRAINT ck_product_price CHECK (unit_price >= cost_price)
);

-- -------------------------------------------------------------------------
-- Order Table
-- -------------------------------------------------------------------------
CREATE TABLE [Order] (
    order_id        INT IDENTITY(1,1) PRIMARY KEY,
    order_no        VARCHAR(30)  NOT NULL,
    customer_id     INT          NOT NULL,
    order_date      DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    status          NVARCHAR(20) NOT NULL DEFAULT N'待付款'
                        CHECK (status IN (
                            N'待付款', N'已付款', N'已发货',
                            N'已完成', N'已取消', N'已退款'
                        )),
    total_amount    DECIMAL(12,2) NOT NULL DEFAULT 0
                        CHECK (total_amount >= 0),
    discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0
                        CHECK (discount_amount >= 0),
    actual_amount   DECIMAL(12,2) NOT NULL DEFAULT 0
                        CHECK (actual_amount >= 0),
    shipping_addr   NVARCHAR(300) NULL,
    remark          NVARCHAR(500) NULL,
    created_at      DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    updated_at      DATETIME2    NULL,

    -- Constraints
    CONSTRAINT uq_order_no UNIQUE (order_no),
    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id)
        REFERENCES Customer(customer_id),
    CONSTRAINT ck_order_amount CHECK (actual_amount = total_amount - discount_amount)
);

-- -------------------------------------------------------------------------
-- OrderItem Table
-- -------------------------------------------------------------------------
CREATE TABLE OrderItem (
    item_id         INT IDENTITY(1,1) PRIMARY KEY,
    order_id        INT          NOT NULL,
    product_id      INT          NOT NULL,
    quantity        INT          NOT NULL
                        CHECK (quantity > 0),
    unit_price      DECIMAL(10,2) NOT NULL
                        CHECK (unit_price >= 0),
    subtotal        AS (quantity * unit_price) PERSISTED,
    discount        DECIMAL(5,2) NOT NULL DEFAULT 0
                        CHECK (discount >= 0 AND discount <= 100),
    created_at      DATETIME2    NOT NULL DEFAULT SYSDATETIME(),

    -- Constraints
    CONSTRAINT fk_orderitem_order FOREIGN KEY (order_id)
        REFERENCES [Order](order_id),
    CONSTRAINT fk_orderitem_product FOREIGN KEY (product_id)
        REFERENCES Product(product_id),
    CONSTRAINT ck_orderitem_quantity CHECK (quantity <= 9999)
);

-- -------------------------------------------------------------------------
-- InventoryLog Table (for trigger demo)
-- -------------------------------------------------------------------------
CREATE TABLE InventoryLog (
    log_id          INT IDENTITY(1,1) PRIMARY KEY,
    product_id      INT          NOT NULL,
    order_id        INT          NULL,
    change_type     NVARCHAR(20) NOT NULL
                        CHECK (change_type IN (N'入库', N'出库', N'订单取消', N'盘点调整')),
    quantity_change INT          NOT NULL,
    before_stock    INT          NOT NULL,
    after_stock     INT          NOT NULL,
    created_at      DATETIME2    NOT NULL DEFAULT SYSDATETIME(),
    remark          NVARCHAR(200) NULL,

    -- Constraints
    CONSTRAINT fk_invlog_product FOREIGN KEY (product_id)
        REFERENCES Product(product_id)
);

-- -------------------------------------------------------------------------
-- Sequence (for order number generation)
-- -------------------------------------------------------------------------
CREATE SEQUENCE dbo.OrderSeq
    AS INT
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 99999
    CYCLE;

-- =============================================================================
-- Schema Coverage Summary
-- =============================================================================
-- PRIMARY KEY        : All tables
-- FOREIGN KEY        : [Order] → Customer, OrderItem → [Order], OrderItem → Product,
--                       InventoryLog → Product
-- UNIQUE             : Customer(customer_code, email), Product(product_code),
--                       [Order](order_no)
-- CHECK              : Customer(tier, credit_limit, phone), Product(unit_price,
--                       cost_price, stock_quantity, min_stock, weight_kg),
--                       [Order](status, total_amount, discount_amount, actual_amount),
--                       OrderItem(quantity, discount)
-- DEFAULT            : Customer(region, tier, credit_limit, is_vip, registered_at),
--                       Product(stock_quantity, min_stock, is_active, created_at),
--                       [Order](order_date, status, total_amount, discount_amount,
--                       actual_amount, created_at), OrderItem(discount, created_at)
-- IDENTITY           : All PK columns
-- COMPUTED COLUMN    : OrderItem.subtotal (PERSISTED)
-- =============================================================================
