# SQL Compatibility Demo — 数据库兼容性测试基准

## 概述

本项目是一个**订单管理系统**的 SQL Demo，作为 `db-compatibility-demo` 项目所有阶段（Phase1/Phase2/Phase3）的统一测试基准。

**核心目标**：尽可能覆盖数据库迁移中最常见的 SQL 特性，而非业务复杂度。

当前实现：**SQL Server** 方言。

## 业务模型

```
Customer  ──1:N──>  Order  ──1:N──>  OrderItem  ──N:1──>  Product
                                                              │
                                                              │
                                                        InventoryLog
```

| 表 | 说明 | 关键字段 |
|---|------|---------|
| **Customer** | 客户 | customer_code (UK), email (UK), tier (CHECK), credit_limit, is_vip |
| **Product** | 产品 | product_code (UK), category, unit_price, stock_quantity, weight_kg |
| **Order** | 订单 | order_no (UK), status (CHECK), total_amount, discount_amount, actual_amount |
| **OrderItem** | 订单项 | quantity, unit_price, discount, subtotal (计算列 PERSISTED) |
| **InventoryLog** | 库存日志 | change_type (CHECK), quantity_change, before_stock, after_stock |

### 种子数据规模

| 表 | 行数 |
|---|------|
| Customer | 25 |
| Product | 55（8 个品类） |
| Order | 110（分布 2024-01 ~ 2024-11） |
| OrderItem | ~330（每订单约 3 项） |

## 目录结构

```
demo/
├── README.md                  # 本文件
└── sqlserver/
    ├── schema.sql             # DDL：表结构、约束、序列
    ├── data.sql               # DML：种子数据
    ├── crud.sql               # INSERT / UPDATE / DELETE / SELECT / MERGE
    ├── query.sql              # 综合查询（JOIN、子查询、CTE、窗口函数、分页）
    ├── transaction.sql        # 事务管理（TRAN / SAVEPOINT / TRY-CATCH）
    ├── procedure.sql          # 存储过程（CreateOrder / CancelOrder）
    ├── trigger.sql            # 触发器（库存扣减/恢复/审计）
    ├── function.sql           # 函数（标量 / 内联表值 / 多语句表值）
    ├── view.sql               # 视图（汇总 / 统计 / 索引视图）
    ├── index.sql              # 索引（单列 / 组合 / 唯一 / 过滤 / 覆盖 / 全文）
    └── advanced.sql           # SQL Server 方言特性（最重要）
```

## 各文件能力覆盖

### schema.sql

| 特性 | 覆盖 |
|------|------|
| PRIMARY KEY | ✓ 全部表 |
| FOREIGN KEY | ✓ Order→Customer, OrderItem→Order, OrderItem→Product, InventoryLog→Product |
| UNIQUE | ✓ Customer(customer_code, email), Product(product_code), Order(order_no) |
| CHECK | ✓ Customer(tier, credit_limit, phone), Product(unit_price, cost_price, stock_quantity, weight), Order(total/actual_amount, status), OrderItem(quantity, discount) |
| DEFAULT | ✓ region, tier, credit_limit, is_vip, stock_quantity, min_stock, status, created_at 等 |
| IDENTITY | ✓ 全部表主键 |
| COMPUTED COLUMN | ✓ OrderItem.subtotal (PERSISTED) |
| SEQUENCE | ✓ OrderSeq (CYCLE) |

### data.sql

| 特性 | 说明 |
|------|------|
| 批量 INSERT | VALUES 多行 |
| INSERT SELECT | 基于 JOIN 的批量订单项插入 |
| 中文数据 | 全部使用中文测试数据 |
| 数据分布 | 多地区、多品类、多状态、跨年度 |

### crud.sql

| 特性 | 覆盖 |
|------|------|
| INSERT | 单行、多行、INSERT SELECT、OUTPUT、DEFAULT VALUES |
| SELECT | 简单查询、TOP、别名、ISNULL/COALESCE、计算列 |
| UPDATE | 标准、JOIN、OUTPUT、CASE |
| DELETE | 标准、JOIN、OUTPUT、TRUNCATE（注释） |
| MERGE | INSERT+UPDATE (UPSERT)、$action |

### query.sql

| 特性 | 覆盖 |
|------|------|
| JOIN | INNER JOIN, LEFT JOIN, RIGHT JOIN, CROSS JOIN, 多表 JOIN |
| 分组 | GROUP BY, HAVING, ROLLUP |
| 去重 | DISTINCT, COUNT(DISTINCT) |
| 集合 | UNION, UNION ALL, INTERSECT, EXCEPT |
| 子查询 | 标量、行、表（派生表）、相关子查询 |
| 条件 | EXISTS, NOT EXISTS, IN, NOT IN, BETWEEN, LIKE |
| CASE | 简单 CASE, 搜索 CASE, 聚合 CASE |
| CTE | 简单 CTE, 链式多 CTE |
| 窗口函数 | ROW_NUMBER, RANK, DENSE_RANK, NTILE, LAG, LEAD, SUM/AVG OVER, FIRST_VALUE, LAST_VALUE |
| 分页 | TOP, OFFSET FETCH |

### transaction.sql

| 特性 | 覆盖 |
|------|------|
| 事务控制 | BEGIN TRAN, COMMIT, ROLLBACK |
| 保存点 | SAVE TRANSACTION |
| 异常处理 | TRY...CATCH, THROW |
| 嵌套事务 | @@TRANCOUNT 行为 |
| 隔离级别 | READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE |
| 系统函数 | ERROR_MESSAGE(), ERROR_SEVERITY(), ERROR_STATE(), ERROR_LINE(), ERROR_PROCEDURE() |
| 表提示 | WITH (NOLOCK) |

### procedure.sql

| 特性 | 覆盖 |
|------|------|
| 存储过程 | CREATE/ALTER PROCEDURE |
| 输入参数 | @p_customer_id, @p_items 等 |
| 输出参数 | @p_order_id OUTPUT, @p_error_msg OUTPUT |
| 返回值 | RETURN 0/1/2/3/4 |
| 表值参数 | dbo.OrderItemType (READONLY) |
| 游标 | CURSOR 逐行处理库存 |
| 事务 | TRY...CATCH + TRAN |
| 序列 | NEXT VALUE FOR |

### trigger.sql

| 特性 | 覆盖 |
|------|------|
| AFTER INSERT | 订单项新增自动扣减库存 |
| AFTER DELETE | 订单删除自动恢复库存 |
| AFTER UPDATE | 订单状态变更审计 |
| INSTEAD OF DELETE | 产品软删除 |
| 条件触发器 | 库存预警（仅首次低于阈值） |
| INSERTED/DELETED | 虚拟表 |
| UPDATE() | 检查列更新 |

### function.sql

| 特性 | 覆盖 |
|------|------|
| 标量函数 | fn_GetOrderStatusName, fn_CalcCustomerLevel, fn_GetDiscount |
| 内联表值函数 | fn_GetCustomerOrders, fn_GetProductSales, fn_TopCustomers |
| 多语句表值函数 | fn_GetMonthlySalesReport |
| 默认参数 | @category = NULL, @region = NULL |
| CROSS APPLY | 与函数结合使用 |

### view.sql

| 特性 | 覆盖 |
|------|------|
| 标准视图 | v_OrderSummary |
| 聚合视图 | v_SalesByRegion, v_DailySales |
| 多表视图 | v_ProductSales（3 表 JOIN） |
| 中文别名 | 多视图使用 |
| SCHEMABINDING | v_InventoryStatus（用于索引视图） |
| OUTER APPLY | v_DailySales |

### index.sql

| 特性 | 覆盖 |
|------|------|
| 非聚集单列 | IX_Customer_Region, IX_Product_Category |
| 组合索引 | IX_Customer_Region_Tier, IX_Order_CustomerId_OrderDate |
| 唯一索引 | IX_OrderItem_OrderId_ProductId |
| 覆盖索引 | INCLUDE 多列 |
| 过滤索引 | WHERE is_active = 1, WHERE status IN (...), WHERE order_date >= '...' |
| DESC 索引 | IX_Order_OrderDate DESC |
| 全文索引 | 注释示例（FULLTEXT） |
| 列存储索引 | 注释示例（COLUMNSTORE） |
| XML 索引 | 注释示例（PRIMARY XML + 辅助） |
| 索引维护 | REORGANIZE, REBUILD, UPDATE STATISTICS, DISABLE |

### advanced.sql ⭐

这是最重要的文件，集中展示 **SQL Server 方言特性**：

| 类别 | 特性 |
|------|------|
| **行限制** | TOP, TOP PERCENT, TOP WITH TIES, TOP (@var) |
| **OUTPUT** | INSERT/UPDATE/DELETE OUTPUT, MERGE $action |
| **标识** | SCOPE_IDENTITY(), @@IDENTITY, IDENT_CURRENT(), IDENTITY_INSERT |
| **日期** | GETDATE(), SYSDATETIME(), GETUTCDATE(), SYSUTCDATETIME(), DATEPART, DATENAME, EOMONTH, DATEADD, DATEDIFF, DATEDIFF_BIG |
| **格式化** | FORMAT(date), FORMAT(number), CONVERT styles |
| **字符串** | ISNULL(), TRY_CONVERT(), TRY_CAST(), NEWID(), STRING_AGG, STRING_SPLIT, CONCAT, CONCAT_WS |
| **APPLY** | CROSS APPLY, OUTER APPLY, CROSS APPLY with TOP |
| **表提示** | WITH (NOLOCK), READUNCOMMITTED |
| **行列转换** | PIVOT, UNPIVOT |
| **格式输出** | FOR XML RAW, FOR XML AUTO, FOR XML PATH, FOR JSON AUTO, FOR JSON PATH |
| **临时对象** | 本地临时表 (#), 全局临时表 (##), 表变量 (@), SELECT INTO |
| **递归** | 递归 CTE, MAXRECURSION |
| **动态SQL** | EXEC(), sp_executesql, QUOTENAME() |
| **其他** | GOTO, WAITFOR, IIF, CHOOSE, RAISERROR |

## SQL Server 专有语法清单

以下语法是 SQL Server 特有的，其他数据库有不同的等价实现：

| SQL Server 语法 | MySQL 等价 | PostgreSQL 等价 | Oracle 等价 |
|----------------|-----------|----------------|------------|
| `TOP n` | `LIMIT n` | `LIMIT n` / `FETCH FIRST n ROWS` | `FETCH FIRST n ROWS` / `ROWNUM` |
| `OUTPUT inserted.*` | 无直接等价 | `RETURNING *` | `RETURNING INTO` |
| `MERGE` | `INSERT ... ON DUPLICATE KEY` / `REPLACE` | `INSERT ... ON CONFLICT` | `MERGE` |
| `IDENTITY(1,1)` | `AUTO_INCREMENT` | `SERIAL` / `GENERATED AS IDENTITY` | `GENERATED AS IDENTITY` / `SEQUENCE` |
| `SCOPE_IDENTITY()` | `LAST_INSERT_ID()` | `LASTVAL()` / `CURRVAL()` | `sequence.CURRVAL` |
| `GETDATE()` | `NOW()` | `NOW()` / `CURRENT_TIMESTAMP` | `SYSDATE` |
| `NEWID()` | `UUID()` | `gen_random_uuid()` | `SYS_GUID()` |
| `ISNULL(x, y)` | `IFNULL(x, y)` | `COALESCE(x, y)` | `NVL(x, y)` |
| `TRY_CONVERT()` | 无直接等价 | `CAST(... AS ...)` (不同错误处理) | `CAST(... AS ... DEFAULT NULL ON CONVERSION ERROR)` |
| `CROSS APPLY` | `INNER JOIN LATERAL` | `INNER JOIN LATERAL` | `CROSS APPLY` |
| `WITH (NOLOCK)` | 无（MVCC 默认非阻塞读） | 无（MVCC 默认非阻塞读） | 无直接等价 |
| `PIVOT` | 无直接等价（CASE + GROUP BY） | `CROSSTAB()` / `FILTER()` | `PIVOT` |
| `FOR XML` | 无直接等价（应用层处理） | `XMLELEMENT`, `XMLAGG` 等 | `XMLAGG` 等 |
| `FOR JSON` | `JSON_OBJECT()` | `JSON_BUILD_OBJECT()`, `JSON_AGG()` | `JSON_OBJECT()` |
| `[方括号]` 引用 | `` `反引号` `` | `"双引号"` | `"双引号"` |
| `NVARCHAR` | `VARCHAR` (utf8mb4) | `VARCHAR` (UTF-8) | `NVARCHAR2` |
| 临时表 `#temp` | `CREATE TEMPORARY TABLE` | `CREATE TEMP TABLE` | `GLOBAL TEMPORARY TABLE` |
| `sp_executesql` | `PREPARE` + `EXECUTE` | `PREPARE` + `EXECUTE` / `EXECUTE ... USING` | `EXECUTE IMMEDIATE ... USING` |

## 后续扩展示例

### MySQL

```text
demo/mysql/
├── schema.sql          # AUTO_INCREMENT, ENGINE=InnoDB, VARCHAR utf8mb4
├── data.sql            # 复用 SQL Server 数据，注意 N'' 前缀需移除
├── crud.sql            # REPLACE INTO, INSERT IGNORE, ON DUPLICATE KEY UPDATE
├── query.sql           # LIMIT 分页, GROUP_CONCAT
├── transaction.sql     # START TRANSACTION, InnoDB 特性
├── procedure.sql       # DELIMITER, IN/OUT/INOUT
├── trigger.sql         # FOR EACH ROW
├── function.sql        # DETERMINISTIC, READS SQL DATA
├── view.sql            # 标准 SQL
├── index.sql           # BTREE/HASH, FULLTEXT with ngram
└── advanced.sql        # 窗口函数 (8.0+), CTE (8.0+), JSON_TABLE
```

### PostgreSQL

```text
demo/postgres/
├── schema.sql          # SERIAL, GENERATED AS IDENTITY, TEXT, JSONB, ARRAY
├── data.sql            # 注意 DEFAULT 与 SQL Server 差异
├── crud.sql            # INSERT ... ON CONFLICT, RETURNING
├── query.sql           # DISTINCT ON, FILTER, LATERAL
├── transaction.sql     # SAVEPOINT, 隔离级别
├── procedure.sql       # PL/pgSQL, RETURNS SETOF
├── trigger.sql         # FUNCTION + TRIGGER 分离
├── function.sql        # $$ 语法, LANGUAGE SQL/plpgsql
├── view.sql            # MATERIALIZED VIEW
├── index.sql           # GIN, GiST, BRIN, 部分索引, 表达式索引
└── advanced.sql        # CTE (WITH RECURSIVE), 窗口函数, JSONB 操作符
```

## 使用方式

### 在 SQL Server 中执行

```bash
# 使用 sqlcmd
sqlcmd -S localhost -U sa -P 'YourPassword' -i demo/sqlserver/schema.sql
sqlcmd -S localhost -U sa -P 'YourPassword' -i demo/sqlserver/data.sql
# ...依次执行其他文件

# 或使用 Python (SQLAlchemy)
python -c "
from sqlalchemy import create_engine, text
engine = create_engine('mssql+pyodbc://sa:pass@localhost/db?driver=ODBC+Driver+18')
with open('demo/sqlserver/schema.sql') as f:
    for stmt in f.read().split('GO'):
        if stmt.strip():
            engine.execute(text(stmt))
"
```

### 作为 Phase1 兼容性分析输入

```bash
# Phase1 将扫描 demo/sqlserver/ 目录
pytest tests/ -v -k "sqlserver"

# 未来多数据库对比
pytest tests/ -v -k "sqlserver or mysql"
```

## 文件大小统计

| 文件 | 行数（约） | 大小（约） |
|------|----------|----------|
| schema.sql | 144 | 6.7 KB |
| data.sql | 273 | 17 KB |
| crud.sql | 168 | 6.3 KB |
| query.sql | 372 | 12 KB |
| transaction.sql | 215 | 7.6 KB |
| procedure.sql | 287 | 9.7 KB |
| trigger.sql | 196 | 6.3 KB |
| function.sql | 197 | 6.8 KB |
| view.sql | 162 | 5.8 KB |
| index.sql | 190 | 7.1 KB |
| advanced.sql | 476 | 16 KB |
| **合计** | **~2,680** | **~101 KB** |

## 设计原则

1. **SQL 保持规范、可读** — 每条 SQL 可独立运行理解
2. **每个文件尽量独立** — 覆盖率总结在每个文件末尾
3. **必要注释** — 所有 SQL 包含双语注释（中文场景 + 英文关键字）
4. **不优化性能** — 重点覆盖 SQL 特性，非生产调优
5. **直接作为扫描输入** — Phase1 可直接解析这些 SQL 文件
6. **保持扩展性** — 目录结构可接入 MySQL, PostgreSQL, Oracle 等

---

*本 Demo 为 db-compatibility-demo 项目的统一测试基准。Phase1 将扫描此目录进行数据库兼容性分析。*
