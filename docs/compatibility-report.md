# 数据库兼容性研究报告

> Phase 0 输出文档 · 2026-06-25
> 目标数据库：SQL Server 2019+ · KingbaseES · DM8
> 技术栈：Python 3.12 · SQLAlchemy 2.x · Alembic · FastAPI

---

## 目录

1. [驱动与方言兼容性总览](#1-驱动与方言兼容性总览)
2. [SQL 特性兼容性矩阵](#2-sql-特性兼容性矩阵)
3. [类型系统差异](#3-类型系统差异)
4. [锁机制差异](#4-锁机制差异)
5. [事务机制差异](#5-事务机制差异)
6. [Schema 对象差异](#6-schema-对象差异)
7. [Alembic 兼容性评估](#7-alembic-兼容性评估)
8. [各库详细评估](#8-各库详细评估)

---

## 1. 驱动与方言兼容性总览

### 1.1 推荐驱动栈

| 数据库 | 推荐驱动 | 方言名称 | 连接字符串前缀 | 成熟度 |
|--------|----------|----------|---------------|--------|
| SQL Server | pyodbc 5.x + ODBC Driver 18 | SQLAlchemy 内建 `mssql+pyodbc` | `mssql+pyodbc://` | ✅ 生产就绪 |
| KingbaseES | psycopg2 | 社区 `kingbase`（PG子类）或直接 `postgresql+psycopg2` | `kingbase+psycopg2://` | ⚠️ 社区Alpha |
| DM8 | dmPython 2.5.32 | 官方 `dm+dmPython`（dmSQLAlchemy 2.0.12） | `dm+dmPython://` | ✅ 生产就绪 |

### 1.2 关键发现

**SQL Server** — 最成熟的生态。SQLAlchemy 内建 MSSQL 方言维护超过 15 年，覆盖几乎所有企业特性。pyodbc 驱动稳定，Python 3.12 完全支持。

**DM8 (达梦)** — 意外的好消息。达梦官方维护了完整的 SQLAlchemy 2.0 方言（`dmSQLAlchemy`），版本迭代活跃（平均每月一个版本），支持完整反射、JSON/JSONB、两阶段 XA 事务、异步、四种兼容模式（DM/Oracle/MySQL/TSQL）。这是三库中唯一有官方支持的国产数据库。

**KingbaseES (人大金仓)** — 最大的风险点。人大金仓官方只提供 JDBC/ODBC/.NET 驱动，**没有官方 Python 驱动或 SQLAlchemy 方言**。社区项目 `sqlalchemy-kingbase` 仅 5 星、v0.0.1、单一维护者。KingbaseES 自身兼容 PostgreSQL 9.3 线协议，但系统表从 `pg_*` 重命名为 `sys_*`，导致 SQLAlchemy 的 `PGDialect` 无法直接反射 Schema。

### 1.3 方言实现质量对比

| 能力维度 | SQL Server (内建) | KingbaseES (社区) | DM8 (官方) |
|----------|-------------------|-------------------|------------|
| Schema 反射 | ✅ 完整 | ⚠️ 需sys_*适配 | ✅ 完整（15+反射方法） |
| 异步支持 | ✅ (aioodbc) | ❌ 未验证 | ✅ v2.0.7+ |
| 类型映射 | ✅ 完整 colspecs | ⚠️ 继承PG，可能有偏差 | ✅ 完整 colspecs |
| DDL 编译 | ✅ 完整 | ⚠️ 继承PG | ✅ 完整 DMDDLCompiler |
| 保留字处理 | ✅ | ✅ 继承PG | ✅ 200+保留字自动引用 |
| 连接断线检测 | ✅ | ✅ 继承PG | ✅ 4个错误码检测 |
| Python 3.12 | ✅ | ❌ 钉死psycopg2 2.8.4 | ✅ |

---

## 2. SQL 特性兼容性矩阵

### 2.1 核心 DML 特性

| 特性 | SQL Server 2019+ | KingbaseES | DM8 | 说明 |
|------|-----------------|------------|-----|------|
| **LIMIT / OFFSET** | ⚠️ `OFFSET n ROWS FETCH NEXT n ROWS ONLY`（需 ORDER BY） | ✅ `LIMIT n OFFSET m` | ✅ ANSI: `OFFSET n ROWS FETCH FIRST n ROWS ONLY`（默认）；Oracle 模式：`ROWNUM` | SQLAlchemy `select().limit().offset()` 自动适配 |
| **FETCH FIRST** | ✅ SQL Server 2012+ | ✅ | ✅ | ANSI SQL:2008 |
| **FOR UPDATE** | ⚠️ `WITH (UPDLOCK, ROWLOCK)` 表提示 | ✅ `FOR UPDATE` | ✅ `FOR UPDATE` | SQL Server 使用表提示语法，非标准子句 |
| **FOR UPDATE NOWAIT** | ⚠️ `WITH (UPDLOCK, ROWLOCK, NOWAIT)` | ✅ | ✅ | |
| **FOR UPDATE SKIP LOCKED** | ⚠️ `WITH (UPDLOCK, ROWLOCK, READPAST)` | ✅ (V8R3+) | ✅ | |
| **FOR UPDATE OF** | ❌ 无直接等价 | ✅ `FOR UPDATE OF col` | ✅ `FOR UPDATE OF col` | SQL Server 无列级锁定 OF 语法 |
| **RETURNING / OUTPUT** | ⚠️ `OUTPUT INSERTED.*` | ✅ `RETURNING *` | ✅ `RETURNING ... INTO :param` | SQLAlchemy 自动适配三种语法 |
| **INSERT ... DEFAULT VALUES** | ✅ | ✅ | ❌ | DM8 不支持默认值插入 |
| **INSERT 多值** | ✅ | ✅ | ✅ | `INSERT INTO t VALUES (1),(2),(3)` |
| **MERGE / UPSERT** | ✅ MERGE | ✅ `ON CONFLICT DO UPDATE` | ✅ MERGE INTO | PG 语法与 MSSQL/DM 不同 |
| **DELETE JOIN** | ✅ `DELETE t FROM t JOIN ...` | ✅ `DELETE FROM t USING ...` | ✅ Oracle 风格 | |

### 2.2 查询特性

| 特性 | SQL Server 2019+ | KingbaseES | DM8 | 说明 |
|------|-----------------|------------|-----|------|
| **CTE / WITH** | ✅ | ✅ | ✅ | |
| **递归 CTE** | ✅ 无 RECURSIVE 关键字 | ✅ `WITH RECURSIVE` | ✅ | |
| **窗口函数** | ✅ 全面支持 | ✅ | ✅ | ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD 等 |
| **DISTINCT ON** | ❌ | ✅ (PG扩展) | ❌ | PG 特有语法 |
| **INTERSECT / EXCEPT** | ✅ | ✅ | ✅ (MINUS 别名) | |
| **LATERAL JOIN** | ✅ APPLY | ✅ LATERAL | ❌ | DM8 明确不支持 |
| **PIVOT / UNPIVOT** | ✅ | ❌ (需 crosstab) | ❌ (需 CASE) | 三库差异最大 |
| **STRING_AGG** | ✅ (2017+) | ✅ `string_agg()` | ⚠️ `LISTAGG()` | 函数名不同 |
| **JSON 查询** | ⚠️ `JSON_VALUE`, `OPENJSON` | ✅ `->` / `->>` / `@>` | ✅ `$.` 路径运算符 | 原生 JSON 支持仅 PG/DM |

### 2.3 DDL 特性

| 特性 | SQL Server 2019+ | KingbaseES | DM8 |
|------|-----------------|------------|-----|
| **IDENTITY 列** | ✅ `IDENTITY(1,1)` | ✅ `GENERATED AS IDENTITY` (V8R6+) | ✅ `IDENTITY(1,1)` |
| **SEQUENCE** | ✅ (2012+) | ✅ | ✅ |
| **SERIAL 类型** | ❌ | ✅ `SERIAL` / `BIGSERIAL` | ❌ 使用 IDENTITY 或 SEQUENCE |
| **计算列** | ✅ | ✅ `GENERATED ALWAYS AS` | ✅ |
| **临时表** | ✅ `#temp` / `##global` | ✅ `CREATE TEMP TABLE` | ✅ `CREATE GLOBAL TEMPORARY TABLE` |
| **表分区** | ✅ | ✅ RANGE/LIST/HASH | ✅ |
| **ALTER COLUMN** | ⚠️ 需 batch 模式 | ✅ | ✅ |
| **DROP COLUMN** | ⚠️ 需 batch 模式 | ✅ | ✅ |
| **事务性 DDL** | ⚠️ 部分DDL自动提交 | ✅ | ✅ |

---

## 3. 类型系统差异

### 3.1 基础类型映射

| Python / 概念 | SQLAlchemy 泛型 | SQL Server | KingbaseES | DM8 | 风险等级 |
|--------------|----------------|------------|------------|-----|---------|
| 整数主键 | `Integer` | `INT IDENTITY(1,1)` | `SERIAL` / `INTEGER` | `INTEGER IDENTITY(1,1)` | 🟢 低 |
| 长整数 | `BigInteger` | `BIGINT` | `BIGINT` / `BIGSERIAL` | `BIGINT` | 🟢 低 |
| 布尔值 | `Boolean` | `BIT` (0/1/NULL) | `BOOLEAN` (true/false) | `SMALLINT` (0/非0) | 🟡 中 — 需 `with_variant` |
| 定长字符串 | `String(n)` | `NVARCHAR(n)` ⚠️ | `VARCHAR(n)` | `VARCHAR2(n)` | 🟡 中 — MSSQL 默认 Unicode |
| 变长文本 | `Text` | `NVARCHAR(MAX)` | `TEXT` | `CLOB` | 🟢 低（泛型自动适配） |
| Unicode文本 | `UnicodeText` | `NVARCHAR(MAX)` | `TEXT` (UTF-8) | `NCLOB` | 🟢 低 |
| 浮点数 | `Float` | `FLOAT(53)` | `FLOAT` / `DOUBLE PRECISION` | `FLOAT` | 🟢 低 |
| 定点数 | `Numeric(p,s)` | `DECIMAL(p,s)` | `NUMERIC(p,s)` | `NUMBER(p,s)` | 🟢 低 |
| 日期时间 | `DateTime` | `DATETIME2` (100ns) | `TIMESTAMP` (微秒) | `DATE` (含时间) ⚠️ | 🟡 中 — DM8 DATE 含时间 |
| 带时区时间 | `DateTime(tz=True)` | `DATETIMEOFFSET` | `TIMESTAMPTZ` | `TIMESTAMP WITH TIME ZONE` | 🟡 中 — 时区语义有细微差异 |
| 日期 | `Date` | `DATE` | `DATE` | `DATE` | 🟢 低 |
| 时间 | `Time` | `TIME` | `TIME` | `TIME` | 🟢 低 |
| 二进制 | `LargeBinary` | `VARBINARY(MAX)` | `BYTEA` | `BLOB` | 🟢 低 |
| UUID | `Uuid` | `UNIQUEIDENTIFIER` | `UUID` | `VARCHAR2(36)` | 🟡 中 — DM8 无原生 UUID |
| JSON | `JSON` | ❌ (存 NVARCHAR(MAX)) | `JSON` / `JSONB` | `JSON` / `JSONB` | 🔴 高 — MSSQL 需原生SQL |
| 数组 | `ARRAY` | ❌ | ✅ | ⚠️ 序列化为 CLOB | 🔴 高 — 避免使用 |
| 枚举 | `Enum` | ❌ (存 VARCHAR + CHECK) | ✅ 原生 ENUM | ❌ (存 VARCHAR + CHECK) | 🟡 中 |

### 3.2 高风险类型详解

#### 3.2.1 Boolean 类型

三库的 Boolean 实现完全不一致：

```python
# 推荐的兼容写法
from sqlalchemy import Boolean, SmallInteger, Column

Column(
    "is_active",
    Boolean().with_variant(SmallInteger(), "mssql")   # SQL Server: BIT → Python int → bool
            .with_variant(SmallInteger(), "dm"),       # DM8: SMALLINT
    nullable=False,
    default=True,
)
```

- **SQL Server**: `BIT` 类型，Python `True`/`False` -> `1`/`0`，ORM 自动转换
- **KingbaseES**: 原生 `BOOLEAN`，完全 Python-native
- **DM8**: `SMALLINT`，通过 `_DMBoolean` 类转换（0=False，其他=True）

#### 3.2.2 JSON 类型

这是三库差异最大的类型：

| 操作 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 存储类型 | `NVARCHAR(MAX)` | `JSONB` | `JSONB` (BLOB内部) |
| 索引 | ❌ | ✅ GIN | ✅ |
| 路径查询 | `JSON_VALUE(col, '$.key')` | `col->>'key'` | `col.$.key` |
| 包含查询 | `OPENJSON` 展开 | `col @> '{"key":"val"}'` | ⚠️ 实现方式不同 |

**建议**: 在业务代码中避免直接对 JSON 列做查询条件。如果需要查询 JSON 内部字段，使用原生 SQL 或提取到独立列。

#### 3.2.3 DateTime / 时间精度

- **SQL Server `DATETIME2`**: 100纳秒精度，范围 0001-9999。`DATETIME`（旧）仅 3.33ms，应避免。
- **KingbaseES `TIMESTAMP`**: 微秒精度。
- **DM8 `DATE`**: ⚠️ **包含时间组件**（类似 Oracle DATE），精度到秒。需要更高精度用 `TIMESTAMP`。

```python
# 统一使用 DateTime（泛型），由方言决定渲染
# 必要时用 with_variant 调整精度
Column(
    "created_at",
    DateTime(timezone=False).with_variant(
        # SQL Server: 使用 DATETIME2 获得更高精度
        DATETIME2(), "mssql"
    ),
    server_default=func.now(),
)
```

#### 3.2.4 String / Unicode 差异

- **SQL Server**: `String(n)` → `NVARCHAR(n)`（默认 Unicode）。这是合理默认，但索引空间翻倍。
- **KingbaseES**: `String(n)` → `VARCHAR(n)`（UTF-8 编码）。
- **DM8**: `String(n)` → `VARCHAR2(n)`，`Unicode` → `NVARCHAR2(n)`。

**建议**: 统一使用 `String` 泛型，SQLAlchemy 自动处理 Unicode。ERP 系统必须处理中文，所以 NVARCHAR 或 UTF-8 VARCHAR 均可，但需注意 SQL Server 的索引大小影响。

---

## 4. 锁机制差异

### 4.1 悲观锁

| 操作 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 行级共享锁 | `WITH (HOLDLOCK)` | `FOR SHARE` | ❓ 需验证 |
| 行级排他锁 | `WITH (UPDLOCK, ROWLOCK)` | `FOR UPDATE` | `FOR UPDATE` |
| 不等待 | `SET LOCK_TIMEOUT 0` + hint | `FOR UPDATE NOWAIT` | `FOR UPDATE NOWAIT` |
| 跳过已锁 | `WITH (READPAST)` | `FOR UPDATE SKIP LOCKED` | `FOR UPDATE SKIP LOCKED` |
| 表级锁 | `WITH (TABLOCKX)` | `LOCK TABLE IN EXCLUSIVE MODE` | `LOCK TABLE IN EXCLUSIVE MODE` |
| 应用级锁 | `sp_getapplock` | Advisory Lock (`pg_advisory_lock`) | ❓ 需验证 |

**SQLAlchemy 统一接口**:

```python
# 乐观锁：三库通用模式
from sqlalchemy.orm import with_for_update

stmt = select(Order).where(Order.id == 42).with_for_update(nowait=True)
# SQL Server  → WITH (UPDLOCK, ROWLOCK, NOWAIT)
# KingbaseES  → FOR UPDATE NOWAIT
# DM8         → FOR UPDATE NOWAIT
```

### 4.2 乐观锁

**推荐三库统一方案：版本号模式**

```python
from sqlalchemy import Integer, Column

class BaseModel(Base):
    __abstract__ = True
    version_id = Column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version_id}
```

- SQLAlchemy 在 UPDATE 时自动添加 `WHERE version_id = :current_version`
- 如果影响行数为 0，抛出 `StaleDataError`
- **三库完全一致** — 这是纯 SQLAlchemy ORM 能力，与方言无关

**SQL Server 专用替代**：`ROWVERSION` 列

```python
# SQL Server 原生的乐观锁（更新时自动递增）
row_version = Column(LargeBinary(8))
__mapper_args__ = {"version_id_col": row_version, "version_id_generator": False}
```

但如果要兼容三库，使用 Integer 版本号更统一。

### 4.3 锁策略风险矩阵

| 场景 | 推荐方案 | SQL Server 风险 | KingbaseES 风险 | DM8 风险 |
|------|---------|----------------|----------------|---------|
| 库存扣减 | 悲观锁 `FOR UPDATE` | 🟡 UPDLOCK hint 语义有细微差异 | 🟢 | 🟢 |
| 单据并发编辑 | 乐观锁（版本号） | 🟢 | 🟢 | 🟢 |
| 分布式互斥 | 各自专用机制 | ✅ sp_getapplock | ✅ Advisory Lock | ❓ 需验证 |
| 死锁处理 | 重试 + 指数退避 | ✅ DEADLOCK_PRIORITY | ✅ deadlock_timeout | ✅ 错误码 -70025/-70028 |

---

## 5. 事务机制差异

### 5.1 隔离级别

| 隔离级别 | SQL Server | KingbaseES | DM8 |
|---------|-----------|------------|-----|
| READ UNCOMMITTED | ✅ | ✅ | ✅ |
| READ COMMITTED | ✅ (默认，基于锁) | ✅ (默认，MVCC) | ✅ (默认) |
| READ COMMITTED SNAPSHOT | ✅ ⚠️ 需数据库级开启 | N/A (PG 本身就是 MVCC) | N/A |
| REPEATABLE READ | ✅ | ✅ | ✅ |
| SNAPSHOT | ✅ ⚠️ 需数据库级开启 | N/A | N/A |
| SERIALIZABLE | ✅ (范围锁) | ✅ (SSI) | ✅ |

**关键差异**: SQL Server 默认的 `READ COMMITTED` 基于锁（非 MVCC），可能导致高并发 ERP 场景下的读写阻塞。**强烈建议**在生产环境开启 `READ_COMMITTED_SNAPSHOT`：

```sql
ALTER DATABASE MyERP SET READ_COMMITTED_SNAPSHOT ON;
```

### 5.2 SAVEPOINT

| 操作 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 创建保存点 | `SAVE TRANSACTION name` | `SAVEPOINT name` | `SAVEPOINT name` |
| 回滚到保存点 | `ROLLBACK TRANSACTION name` | `ROLLBACK TO name` | `ROLLBACK TO name` |
| 释放保存点 | ❌ 不支持 | `RELEASE name` | ❌ (pass no-op) |

SQLAlchemy 通过 `session.begin_nested()` 统一封装，三库均可使用。

### 5.3 统一事务架构

```
┌─────────────────────────────────────────────┐
│              FastAPI Request                  │
│  SessionDep = Annotated[Session, Depends]    │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────▼──────────────┐
    │     Unit of Work Pattern    │
    │  ┌──────────────────────┐   │
    │  │  Service Layer        │   │
    │  │  - validate           │   │
    │  │  - business logic     │   │
    │  │  - domain events      │   │
    │  └──────────┬───────────┘   │
    │             │               │
    │  ┌──────────▼───────────┐   │
    │  │  Repository Layer    │   │
    │  │  - CRUD operations   │   │
    │  │  - query composition │   │
    │  └──────────┬───────────┘   │
    │             │               │
    │  ┌──────────▼───────────┐   │
    │  │  SQLAlchemy Session  │   │
    │  │  (single transaction)│   │
    │  └──────────────────────┘   │
    └─────────────────────────────┘
                   │
    ┌──────────────▼──────────────┐
    │  Transaction Boundary       │
    │  - begin() / commit()       │
    │  - rollback() on exception  │
    │  - nested() for savepoint   │
    └─────────────────────────────┘
```

**单据事务一致性保证**（主表 + 明细 + 库存 + 日志）：

```python
async def create_order_with_items(
    session: AsyncSession,
    order_data: OrderCreate,
    items_data: list[OrderItemCreate],
) -> Order:
    # 单一事务边界 — 全部成功或全部回滚
    async with session.begin():
        # 1. 主表
        order = Order(**order_data.model_dump())
        session.add(order)
        await session.flush()  # 获取 order.id

        # 2. 明细
        for item_data in items_data:
            item = OrderItem(order_id=order.id, **item_data.model_dump())
            session.add(item)

        # 3. 库存（悲观锁防止超卖）
        for item_data in items_data:
            inventory = await session.execute(
                select(Inventory)
                .where(Inventory.product_id == item_data.product_id)
                .with_for_update()
            )
            inv = inventory.scalar_one()
            inv.quantity -= item_data.quantity
            if inv.quantity < 0:
                raise InsufficientStockError(...)

        # 4. 日志
        log = StockLog(
            order_id=order.id,
            action="reserve",
            details=items_data,
        )
        session.add(log)

    # session.begin() 退出时自动 commit
    # 任何异常触发 rollback（包括 savepoint 回滚）
    await session.refresh(order)
    return order
```

---

## 6. Schema 对象差异

### 6.1 View（视图）

| 特性 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 普通视图 | ✅ | ✅ | ✅ |
| 物化视图 | ❌ (用索引视图代替) | ✅ | ✅ |
| 可更新视图 | ✅ (INSTEAD OF 触发器) | ✅ (自动可更新简单视图) | ✅ |
| 视图索引 | ✅ 索引视图 | ✅ 物化视图索引 | ✅ |
| ORM 映射 | ✅ 像表一样映射 | ✅ | ✅ |
| DDL 获取 | ✅ | ✅ `pg_get_viewdef()` | ✅ `DBMS_METADATA.GET_DDL` |

### 6.2 存储过程 / 函数

| 特性 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 存储过程 | ✅ T-SQL | ✅ PL/pgSQL | ✅ PL/SQL (Oracle 兼容) |
| 标量函数 | ✅ | ✅ | ✅ |
| 表值函数 | ✅ 内联/多语句 | ✅ | ❓ |
| 输出参数 | ✅ | ✅ | ✅ |
| 包 (Package) | ❌ | ❌ | ✅ (Oracle 兼容) |

### 6.3 其他对象

| 对象 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 触发器 | ✅ AFTER/INSTEAD OF | ✅ BEFORE/AFTER/INSTEAD OF | ✅ |
| 同义词 | ✅ | ❌ (用视图替代) | ✅ |
| 数据库链接 | ✅ Linked Server | ✅ FDW | ✅ |
| 全文索引 | ✅ 全文目录 | ⚠️ 不同API | ⚠️ 不同API |

---

## 7. Alembic 兼容性评估

### 7.1 综合评估

| 能力 | SQL Server | KingbaseES | DM8 |
|------|-----------|------------|-----|
| 基本迁移 (DDL) | ✅ | ✅ (通过PG方言) | ✅ (通过DM方言) |
| 自动生成 (autogenerate) | ✅ | ⚠️ 需 sys_* 反射适配 | ✅ (完整反射) |
| 批量操作 (batch mode) | ✅ 需要 | ✅ | ✅ |
| 离线 SQL 生成 | ✅ | ✅ | ⚠️ 需验证 |
| 事务性迁移 | ⚠️ 部分DDL自动提交 | ✅ | ✅ |

### 7.2 推荐迁移策略

针对三库差异，推荐**独立迁移目录 + 共享 DDL 抽象层**：

```
alembic/
├── mssql/
│   ├── env.py          # SQL Server 专用 env
│   └── versions/       # SQL Server 迁移链
├── kingbasees/
│   ├── env.py          # KingbaseES 专用 env
│   └── versions/       # KingbaseES 迁移链
├── dm8/
│   ├── env.py          # DM8 专用 env
│   └── versions/       # DM8 迁移链
└── _shared/
    └── ddl_backend.py  # 共享 DDL 抽象层
```

```python
# _shared/ddl_backend.py — 共享 DDL 逻辑
class DDLBackend:
    """DDL 方言抽象层，每个数据库提供自己的实现"""

    def __init__(self, dialect_name: str):
        self.dialect = dialect_name

    def json_column_type(self):
        if self.dialect == "postgresql" or "kingbase" in self.dialect:
            return sa.dialects.postgresql.JSONB()
        elif self.dialect == "mssql":
            return sa.Text()  # NVARCHAR(MAX)
        elif self.dialect == "dm":
            return sa.Text()  # CLOB（或使用 JSON 类型）
        return sa.Text()

    def boolean_column_type(self):
        return sa.Boolean().with_variant(sa.SmallInteger(), "mssql") \
                          .with_variant(sa.SmallInteger(), "dm")
```

---

## 8. 各库详细评估

### 8.1 SQL Server 2019+

**总体评估**: 🟢 成熟可靠，是三个目标中最完善的生态。

**优势**:
- SQLAlchemy 内建方言，15 年维护历史
- pyodbc 驱动稳定，企业级验证
- Alembic 完全支持（需开启 batch mode）
- 丰富的数据类型和锁机制
- 企业特性完整（Always On, Query Store, 自动调优）

**需要关注的问题**:
1. **不是 MVCC 默认**: 必须开启 `READ_COMMITTED_SNAPSHOT`
2. **DDL 隐式提交**: 部分 DDL 操作在 SQL Server 中自动提交事务，DML+DDL 混合迁移需拆分
3. **Boolean = BIT**: 与 Python bool 的语义差异
4. **String = NVARCHAR**: 默认 Unicode，索引空间双倍
5. **FOR UPDATE 语法**: 使用表提示而非 ANSI SQL 标准
6. **JSON 无原生支持**: JSON 列必须用 `NVARCHAR(MAX)` + 原始 SQL
7. **参数嗅探**: ORM 生成的参数化查询可能因参数嗅探导致性能不稳定

### 8.2 KingbaseES

**总体评估**: 🟡 功能可用但生态薄弱，需自行维护方言。

**优势**:
- PostgreSQL 线协议兼容，功能覆盖面广
- 丰富的 SQL 特性（CTE、窗口函数、UPSERT）
- MVCC 默认，高并发友好
- 优秀的中文编码支持（UTF-8/GBK/GB18030）
- 原生 JSON/JSONB、ARRAY、UUID 类型

**需要关注的问题**:
1. **没有官方 Python 支持**: 人大金仓不维护 Python 驱动或 SQLAlchemy 方言
2. **社区方言 Alpha 质量**: `sqlalchemy-kingbase` v0.0.1，仅 5 星，维护者 1 人
3. **系统表重命名**: `pg_*` → `sys_*`，需要完整的反射适配
4. **PG 版本基线低**: 目标 PG 9.3 兼容（缺少 PG 10+ 的 IDENTITY、PG 11+ 的 PROCEDURE）
5. **方言需自行维护**: 任何 SQLAlchemy/Alembic 升级都可能破坏兼容性
6. **psycopg2 版本锁定**: 社区方言钉死在 2.8.4（无 Python 3.12 wheel）
7. **端口非标准**: 默认 54321（非 5432）
8. **扩展不兼容**: PostgreSQL 扩展（PostGIS、pg_stat_statements）不可用

**缓解措施**:
- Fork `sqlalchemy-kingbase` 并自行维护
- 升级 psycopg2 依赖到 2.9.x+
- 测试并修复 SQLAlchemy 2.x 兼容性
- 实现完整的 `sys_*` 反射方法
- 建立回归测试套件

### 8.3 DM8 (达梦)

**总体评估**: 🟢 意外的好 — 官方支持完善，三库中最令人放心的国产库。

**优势**:
- **官方 SQLAlchemy 2.0 方言**: 版本 2.0.12，活跃维护（月均一个版本）
- **完整 Schema 反射**: 15+ 反射方法全部实现
- **Oracle 兼容**: SQL 语法与 Oracle 高度一致，迁移经验丰富
- **原生 JSON/JSONB**: 通过 BLOB 内部实现
- **XA 两阶段事务**: 完整支持
- **四种兼容模式**: DM/Oracle/MySQL/TSQL
- **异步支持**: v2.0.7+ 支持 async
- **dmPython 驱动成熟**: v2.5.32，Python 3.12 兼容
- **丰富的类型体系**: INTERVAL, VECTOR 等特色类型

**需要关注的问题**:
1. **Boolean 无原生类型**: 使用 SMALLINT 模拟
2. **DATE 含时间**: 类似 Oracle，与 Python `datetime.date` 语义可能冲突
3. **UUID 无原生类型**: 存储为 VARCHAR2(36)
4. **不支持 LATERAL JOIN**: 涉及 LATERAL 的查询需改写
5. **不支持 INSERT ... DEFAULT VALUES**: 空插入需特殊处理
6. **Alembic 测试不充分**: 官方未专门测试 Alembic 兼容性，需自行验证
7. **保留字多**: 200+ 保留字（如 LIMIT, ROWNUM, TOP），列名冲突时会自动引用
8. **社区资源少**: 中英文技术资料远少于 PG/MSSQL

---

## 附录 A：兼容性矩阵速查表（汇总）

| 功能 | SQL Server | KingbaseES | DM8 | 统一方案 |
|------|-----------|------------|-----|---------|
| 分页 | OFFSET/FETCH | LIMIT/OFFSET | OFFSET/FETCH 或 ROWNUM | `select().limit().offset()` |
| 行锁 | UPDLOCK hint | FOR UPDATE | FOR UPDATE | `.with_for_update()` |
| 跳锁 | READPAST hint | SKIP LOCKED | SKIP LOCKED | `.with_for_update(skip_locked=True)` |
| 返回插入值 | OUTPUT | RETURNING | RETURNING INTO | ORM 自动处理 |
| 布尔值 | BIT/SMALLINT | BOOLEAN | SMALLINT | `Boolean().with_variant(SmallInteger(), ...)` |
| 自增主键 | IDENTITY | SERIAL/IDENTITY | IDENTITY | `Integer` + `autoincrement=True` |
| JSON | NVARCHAR(MAX) | JSONB | JSON/JSONB | 避免直接查询 JSON 列 |
| 乐观锁 | 版本号 / ROWVERSION | 版本号 | 版本号 | `version_id_col` |
| 保存点 | SAVE TRANS | SAVEPOINT | SAVEPOINT | `.begin_nested()` |
| Schema 反射 | ✅ | ⚠️ | ✅ | — |
| Alembic 迁移 | ✅ | ⚠️ | ⚠️ | 独立迁移目录 |
| 异步 ORM | ✅ (aioodbc) | ⚠️ | ✅ | — |

---

## 附录 B：关键技术决策建议

1. **类型安全**: 对所有三库不一致的类型（Boolean、JSON、DateTime），使用 `with_variant` 在模型层统一
2. **锁策略**: 乐观锁用整数版本号（三库统一），悲观锁用 `with_for_update()`（自动适配）
3. **事务**: SQL Server 必须开启 `READ_COMMITTED_SNAPSHOT`，避免读写互斥
4. **JSON**: 尽量避免在 WHERE 条件中查询 JSON 内部字段，必要时用原生 SQL
5. **分页**: 始终指定显式 `order_by()`，确保三库分页行为一致
6. **Alembic**: 三库各自独立迁移目录，共享 DDL 抽象层
7. **方言维护**: KingbaseES 方言需要自行 fork 维护；DM8 和 SQL Server 可用官方版本
