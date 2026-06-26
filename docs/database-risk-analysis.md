# 数据库兼容性风险分析

> Phase 0 输出文档 · 2026-06-25
> 基于 compatibility-report.md 和 architecture-design.md

---

## 目录

1. [风险等级定义](#1-风险等级定义)
2. [总体风险概览](#2-总体风险概览)
3. [驱动与方言风险](#3-驱动与方言风险)
4. [SQL 兼容性风险](#4-sql-兼容性风险)
5. [类型系统风险](#5-类型系统风险)
6. [锁与并发风险](#6-锁与并发风险)
7. [事务风险](#7-事务风险)
8. [迁移与部署风险](#8-迁移与部署风险)
9. [性能风险](#9-性能风险)
10. [运营风险](#10-运营风险)
11. [风险缓解路线图](#11-风险缓解路线图)

---

## 1. 风险等级定义

| 等级 | 符号 | 含义 | 响应 |
|------|------|------|------|
| **CRITICAL** | 🔴 | 可能导致功能不可用或数据不一致，阻塞发布 | **必须**在 Phase 1 解决 |
| **HIGH** | 🟠 | 需要显著额外开发工作，可能影响项目时间线 | **必须**在 Phase 2 Demo 中验证 |
| **MEDIUM** | 🟡 | 需要条件分支或替代方案，但不阻塞核心功能 | 在 Demo 中覆盖 |
| **LOW** | 🟢 | 已有成熟解决方案，风险可控 | 常规关注 |

---

## 2. 总体风险概览

### 2.1 按风险矩阵

```
                  影响程度
              低        中        高       严重

  几乎确定    🟢 基础CRUD  🟡 日期类型  🟠 JSON查询   🔴 —
  很可能      🟢 分页      🟡 Boolean   🟠 存储过程  🔴 KingbaseES方言
  可能        🟢 UUID      🟡 LATERAL   🟠 悲观锁    🔴 三库DDL差异
  不太可能    🟢 连接池    🟢 Schema   🟡 索引      🟠 DM8性能
  罕见        🟢 配置      🟢 日志     🟢 保留字    🟡 中文编码
```

### 2.2 按数据库分

| 风险项 | SQL Server | KingbaseES | DM8 |
|--------|-----------|------------|-----|
| **方言成熟度** | 🟢 内建15年 | 🔴 社区Alpha v0.0.1 | 🟢 官方v2.0.12 |
| **ORM 兼容性** | 🟢 | 🟡 | 🟢 |
| **Core 兼容性** | 🟢 | 🟢 | 🟢 |
| **Alembic 支持** | 🟢（需batch_mode） | 🟠（需自行适配） | 🟡（官方未测试） |
| **类型系统** | 🟡（Boolean/JSON） | 🟢 | 🟡（DATE含时间） |
| **锁机制** | 🟡（UPDLOCK语法差异） | 🟢 | 🟢 |
| **MVCC** | 🟠（需开启RCSI） | 🟢（默认） | 🟢（默认） |
| **异步支持** | 🟡（aioodbc） | 🟡（asyncpg适配） | 🟢（dmAsync v2.0.7+） |
| **中文编码** | 🟢（NVARCHAR默认） | 🟢（需设UTF8） | 🟢（UTF-8/GBK） |

### 2.3 按功能域分

| 功能域 | 风险等级 | 关键风险 |
|--------|---------|---------|
| 基础 CRUD | 🟢 低 | ORM 抽象覆盖所有三库 |
| 分页查询 | 🟢 低 | `limit().offset()` 三库均支持 |
| 复杂关联查询 | 🟡 中 | LATERAL (DM8不支持), 窗口函数细微差异 |
| JSON 操作 | 🔴 高 | MSSQL 无原生 JSON, 查询语法三库完全不同 |
| 批量操作 | 🟡 中 | 批量插入语法有差异, DM8 不支持 default_values |
| 存储过程 | 🟠 高 | 三种 PL 方言, 调用语法不同 |
| 乐观锁 | 🟢 低 | version_id_col 纯 ORM 实现 |
| 悲观锁 | 🟡 中 | FOR UPDATE 语义小差异, 应用级锁不统一 |
| 分布式事务 | 🔴 高 | 三库 XA 实现差异大, 不建议在应用层使用 |
| Schema 迁移 | 🟠 高 | KingbaseES 缺少官方 Alembic 支持 |

---

## 3. 驱动与方言风险

### 🔴 CRITICAL — KingbaseES 方言不可用风险

**风险描述**: 人大金仓没有官方 SQLAlchemy 方言。社区项目 `sqlalchemy-kingbase`（GitHub: LFunTech/sqlalchemy-kingbase）仅 5 星、v0.0.1、单一维护者，且钉死在 psycopg2 2.8.4（不兼容 Python 3.12 wheel）。

**影响**:
- 无法自动反射 Schema（`sys_*` 系统表替代 `pg_*`）
- Alembic autogenerate 不可用
- 每个 SQLAlchemy 升级都需要回归测试
- 字符编码问题需手动配置 `client_encoding=utf8`

**缓解措施**:
1. **Fork + 升级**: Fork `sqlalchemy-kingbase`，升级 psycopg2 → 2.9.x+，适配 SQLAlchemy 2.x API
2. **完整实现 `sys_*` 反射**: 系统表映射从 `pg_*` 改为 `sys_*`
3. **回归测试套件**: 每个 SQLAlchemy 小版本升级后运行全量回归
4. **降级路径**: 如果方言无法维护，回到 `postgresql+psycopg2` + 手动 Schema 管理
5. **时间预算**: 预计 2-3 周的方言维护工作量

### 🟡 MEDIUM — DM8 方言版本锁定风险

**风险描述**: dmSQLAlchemy 由达梦官方维护，但版本更新频繁（月均一次）。如果项目锁定了特定版本，升级 DM8 数据库时方言可能不兼容。

**缓解措施**:
- 在 CI 中固定 dmSQLAlchemy 版本，与 DM8 数据库版本建立兼容性矩阵
- 每次升级前阅读 dmSQLAlchemy 的 CHANGELOG
- 建立版本兼容性表

### 🟢 LOW — SQL Server 驱动风险

**风险描述**: pyodbc 依赖系统级 ODBC 驱动。Linux 部署需安装 `msodbcsql18`，macOS 需 Homebrew。

**缓解措施**:
- Docker 镜像中预装 ODBC Driver 18
- `pool_pre_ping=True` + `pool_recycle=1800` 防连接断开
- 使用 `urllib.parse.quote_plus` 处理连接字符串

---

## 4. SQL 兼容性风险

### 🟠 HIGH — 分页语法差异

**风险描述**: 虽然 SQLAlchemy 自动适配三个数据库的分页语法，但在以下场景需要关注：

| 场景 | SQL Server | KingbaseES | DM8 | 风险 |
|------|-----------|------------|-----|------|
| 无 ORDER BY 分页 | ❌ 报错 | ✅ | ✅ (ROWNUM 模式) | MSSQL 报错 |
| 分页 + JOIN | 正常 | 正常 | ROWNUM 包装器可能改变语义 | DM8 使用 ROWNUM 时 |
| 超大 OFFSET | OFFSET FETCH 不如 keyset | OFFSET 扫描所有行 | ROWNUM 需子查询 | 三库都有性能问题 |

**缓解措施**:
- 强制所有分页查询使用显式 `order_by()`
- 对于超大分页，推荐 **Keyset Pagination**（`WHERE id > :last_id ORDER BY id LIMIT n`）

### 🟡 MEDIUM — FOR UPDATE 语法差异

**风险描述**: SQL Server 使用 `WITH (UPDLOCK, ROWLOCK)` 表提示，而非 ANSI `FOR UPDATE`。虽然 SQLAlchemy 的 `with_for_update()` 自动适配，但：

- `FOR UPDATE OF table.column` **SQL Server 不支持**
- `FOR UPDATE NOWAIT` 在 SQL Server 中需要组合 `UPDLOCK + NOWAIT` hint
- `FOR UPDATE SKIP LOCKED` 在 SQL Server 中用 `READPAST` hint

**影响**: 精细化行锁场景（如指定锁定特定表的特定列）无法跨库统一。

**缓解措施**: 在 Repository 层封装，不直接暴露 `with_for_update(of=...)` 的跨列锁定。

### 🟡 MEDIUM — MERGE/UPSERT 语法差异

| 数据库 | 语法 | 说明 |
|--------|------|------|
| SQL Server | `MERGE INTO target USING source ON ... WHEN ...` | 完整 MERGE |
| KingbaseES | `INSERT INTO ... ON CONFLICT ... DO UPDATE` | PG UPSERT |
| DM8 | `MERGE INTO target USING source ON ... WHEN ...` | Oracle 风格 MERGE |

**风险**: 三库使用了不同的 UPSERT 机制，SQLAlchemy 没有统一的 MERGE 支持。

**缓解措施**:
- 避免在业务代码中使用 UPSERT / MERGE
- 改为 "先查后决" 模式 (SELECT → INSERT or UPDATE)
- 如需性能优化，在 Repository 层使用方言特定的原生 SQL

---

## 5. 类型系统风险

### 🔴 HIGH — Boolean 类型三库不一致

| 数据库 | 实际存储 | Python 交互 | 查询行为 |
|--------|---------|------------|---------|
| SQL Server | BIT (0/1/NULL) | int → bool 自动转 | `WHERE col = 1` |
| KingbaseES | BOOLEAN | 原生 bool | `WHERE col = true` |
| DM8 | SMALLINT | int → bool（0=False） | `WHERE col = 1` |

**风险**: 使用原生 SQL 时，`is_active = True` 的查询条件可能在三库产生不同行为。

**缓解措施**:
- **强制使用 `with_variant`** 在模型层定义
- ORM 查询完全没问题（SQLAlchemy 自动适配）
- 原生 SQL 查询时使用参数化绑定 `:is_active` 而非字符串拼接

### 🟠 HIGH — JSON 类型不可跨库

**风险**: 这是三库差异**最大**的类型。SQL Server 没有原生 JSON 类型（只有 JSON 函数操作 NVARCHAR），三库的 JSON 查询语法完全不同：

```sql
-- MSSQL: JSON_VALUE(col, '$.key') = 'value'
-- KingbaseES: col->>'key' = 'value'
-- DM8: col.$.key = 'value'
```

无法用同一行代码对 JSON 列做查询。

**缓解措施**:
1. **避免 JSON 列做查询条件**: 将查询所需字段提取为独立列
2. **JSON 仅用于存储**: 对不需要查询的灵活结构数据使用 JSON 列
3. **或使用 EAV 模式**: 对于需要查询的动态属性，使用 `entity-attribute-value` 表

### 🟡 MEDIUM — DM8 DATE 含时间

**风险**: DM8 的 `DATE` 类型类似 Oracle，包含时间组件（精确到秒）。Python `datetime.date` 绑定可能发生截断。

**缓解措施**:
- 统一使用 `DateTime` 泛型，不用 `Date` 类型
- 如需纯日期，在应用层截断时间部分

### 🟡 MEDIUM — 字符编码不一致

| 数据库 | 默认行为 | 中文风险 |
|--------|---------|---------|
| SQL Server | `NCHAR`/`NVARCHAR` (UCS-2) | 🟢 默认支持 |
| KingbaseES | `VARCHAR` (UTF-8 或 GBK，取决于数据库创建参数) | 🟡 需显式设置 `client_encoding=utf8` |
| DM8 | UTF-8/GBK（连接参数 `local_code=1` 设 UTF-8） | 🟢 正确配置即可 |

**缓解措施**:
- 连接字符串中配置 UTF-8
- KingbaseES: `options=-c client_encoding=utf8`
- DM8: `local_code=1`
- 在 CI 中验证中文插入/查询的正确性

---

## 6. 锁与并发风险

### 🟠 HIGH — SQL Server 默认锁行为导致性能问题

**风险描述**: SQL Server 默认 `READ COMMITTED` 隔离级别使用**锁**（非 MVCC）。在高并发 ERP 场景（如 100+ 并发用户操作库存），SELECT 会阻塞 UPDATE，UPDATE 会阻塞 SELECT。

**影响**:
- 报表查询阻塞实时交易
- 锁升级可能导致死锁
- 这与 KingbaseES/DM8 的 MVCC 行为完全不同

**缓解措施**（必须）:
```sql
-- 在数据库级别开启
ALTER DATABASE MyERP SET READ_COMMITTED_SNAPSHOT ON;
ALTER DATABASE MyERP SET ALLOW_SNAPSHOT_ISOLATION ON;
```
- 在部署文档和运维文档中标注为 **必需配置**
- CI 测试中验证 RCSI 是否开启

### 🟡 MEDIUM — 应用级锁不存在跨库方案

**风险**: 需要跨服务实例的分布式互斥时：
- SQL Server: `sp_getapplock` ✅
- KingbaseES: `pg_advisory_lock` ✅
- DM8: ❓ 不确定是否有等价机制

**缓解措施**:
- 优先使用 Redis 分布式锁（应用层，与数据库无关）
- 如果必须在数据库层，使用专用锁表 + 悲观行锁模拟

---

## 7. 事务风险

### 🟡 MEDIUM — SQL Server DDL 隐式提交

**风险描述**: SQL Server 中，下列 DDL 操作会**自动提交当前事务**：

- `CREATE TABLE` / `ALTER TABLE` / `DROP TABLE`
- `CREATE INDEX` / `DROP INDEX`
- `CREATE SCHEMA`

这意味着如果在事务中混合 DML 和 DDL，DDL 会提前提交前面的 DML。

**影响**: 迁移脚本中 DML + DDL 混合时，部分 DML 可能被意外提交。

**缓解措施**:
- **分离 DML 和 DDL 到不同迁移文件**
- `001_add_column.py` (DDL)
- `002_backfill_data.py` (DML)
- 不在同一个事务中混合 DDL 和 DML

### 🟢 LOW — 两阶段事务

**风险**: XA 两阶段事务在三库的 API 不同（MSSQL=MSDTC, KingbaseES=PREPARE TRANSACTION, DM8=Oracle XA）。

**推荐方案**: **不使用分布式事务**。替代方案：
- Outbox Pattern (本地事务 + 消息队列)
- Saga Pattern (补偿事务)

---

## 8. 迁移与部署风险

### 🟠 HIGH — KingbaseES Schema 反射

**风险描述**: KingbaseES 将 PostgreSQL 的 `pg_*` 系统表重命名为 `sys_*`。社区方言需要完整覆盖：

- `pg_class` → `sys_class`
- `pg_namespace` → `sys_namespace`
- `pg_attribute` → `sys_attribute`
- `pg_get_viewdef()` → `sys_get_viewdef()`
- `pg_table_is_visible()` → `sys_table_is_visible()`
- 等 20+ 个系统函数

任何遗漏都会导致 `inspector.get_columns()`, `get_table_names()`, `autogenerate` 失败。

**缓解措施**:
- 从 community 分支开始，补齐所有 `sys_*` 映射
- 编写专门的反射测试用例
- 与 `postgresql` 的反射结果进行对比验证

### 🟡 MEDIUM — Alembic DM8 支持未充分测试

**风险描述**: DM8 官方维护了 SQLAlchemy 方言，但未专门测试 Alembic 兼容性。`DMDDLCompiler` 存在，但 Alembic 操作路径可能与直接使用 ORM 不同。

**需验证的功能**:
- `op.create_table()` — 表创建
- `op.add_column()` / `op.alter_column()` — 列变更
- `op.create_index()` / `op.create_unique_constraint()` — 约束
- `op.rename_table()` — 重命名
- `op.batch_alter_table()` — 批量模式
- `autogenerate` — 自动检测

**缓解措施**:
- 在 Demo 阶段优先验证 DM8 的 Alembic 操作
- 准备原生 SQL 降级方案（通过 `op.execute()`）

### 🟡 MEDIUM — SQL Server Batch Mode 必要性

**风险**: SQL Server 的部分 DDL 操作（如修改列类型）需要 "rebuild table" 方式。Alembic 的 `batch_mode=True` 自动处理，但生成的 SQL 包含：
1. 创建新表
2. 复制数据
3. 删除旧表
4. 重命名新表

这个过程**隐式提交**且**不可回滚**。如果中间步骤失败，数据可能处于不一致状态。

**缓解措施**:
- 关键表变更前先备份数据
- 在非生产环境充分测试
- 对于大表（>100万行），考虑手动分步迁移

---

## 9. 性能风险

### 🟠 HIGH — 大批量 INSERT 性能差异

| 数据库 | 批量插入机制 | 性能特征 |
|--------|------------|---------|
| SQL Server | `INSERT INTO ... VALUES (1),(2),...(N)` | 单批次最佳 ~500 行 |
| KingbaseES | 同上 + `COPY` | `COPY` 远快于 INSERT |
| DM8 | `INSERT ALL INTO ... SELECT ... FROM DUAL` | Oracle 风格 |

**风险**: 相同的 `bulk_insert_mappings()` 在不同数据库的性能差距可能达 5-10x。

**缓解措施**:
- 大批量导入（>1000 行）使用各库的原生批量机制
- 在 `compat/` 层封装数据库特定的批量导入
- 在 Demo 中测试 1000/10000/100000 行插入的性能

### 🟡 MEDIUM — SQL Server 参数嗅探

**风险**: SQL Server 缓存计划基于**首次执行的参数**。ORM 生成的参数化查询可能因首先遇到的参数分布特殊，导致后续查询使用次优计划。

**示例**: 首次查询 `WHERE status = 'draft'`（90% 数据），计划用全表扫描。后续 `WHERE status = 'confirmed'`（1% 数据）也全表扫描。

**缓解措施**:
- 在关键查询上使用 `WITH (OPTIMIZE FOR UNKNOWN)` hint
- 启用 SQL Server Query Store 监控
- DBA 定期 force 好的执行计划

### 🟡 MEDIUM — 分页性能退化（大 OFFSET）

所有三库在 `OFFSET + LIMIT` 分页中，OFFSET 越大性能越差（数据库仍需扫描前 N 行并丢弃）。对于 100万行表 + `OFFSET 900000`，三库都面临性能问题。

**缓解措施**: 使用 Keyset Pagination（游标分页）替代 OFFSET：
```python
# 替换: .offset(900000).limit(10)
# 使用: WHERE id > :last_seen_id ORDER BY id LIMIT 10
```

### 🟢 LOW — UUID 主键索引碎片

**风险**: 使用 UUID 作为聚簇索引主键时，随机插入导致页分裂和索引碎片（SQL Server 尤其明显，因为其默认主键 = 聚簇索引）。

**缓解措施**:
- 使用 UUIDv7（时间有序版本）
- SQL Server 中将聚簇索引放在 `seq`（自增辅助列）上，UUID 列用非聚簇唯一索引

---

## 10. 运营风险

### 🟡 MEDIUM — 数据库版本锁定

| 组件 | 版本依赖 | 风险 |
|------|---------|------|
| dmSQLAlchemy 2.0.12 | DM8 | 版本需匹配 |
| sqlalchemy-kingbase 0.0.1 | KingbaseES V8R3/R6 | 未充分测试 |
| pyodbc 5.x | ODBC Driver 17/18, SQL Server 2019+ | Windows/Linux 需系统级安装 |

### 🟡 MEDIUM — 中文排序差异

三库的排序规则（collation）不一致：
- SQL Server: `Chinese_PRC_CI_AS` (拼音排序)
- KingbaseES: 取决于 `lc_collate` 设置
- DM8: 取决于数据库字符集设置

**影响**: `ORDER BY name` 的中文排序结果可能不一致。

**缓解措施**: 在应用层做中文排序，或为中文检索专门建立拼音/笔画索引。

### 🟢 LOW — 连接池配置差异

三库的推荐连接池参数不同，但 `pool_size + max_overflow` 可统一配置。`pool_pre_ping=True` 在所有三库都推荐。

---

## 11. 风险缓解路线图

### Phase 1（Demo 前必须解决）🔴

| 风险 | 行动 | 验收标准 |
|------|------|---------|
| KingbaseES 方言 | Fork + 升级 + 补全 sys_* 反射 | Inspector 反射测试通过 |
| Boolean 类型 | `with_variant` 统一 | 三库 Boolean CRUD 测试通过 |
| JSON 策略 | 确定禁用或提取列原则 | 架构文档明确 JSON 使用规则 |
| SQL Server RCSI | 在 Docker 中预配置 | 并发测试无死锁 |

### Phase 2（Demo 中验证）🟠

| 风险 | 行动 | 验收标准 |
|------|------|---------|
| 悲观锁一致性 | 三库 `with_for_update()` 行为测试 | 并发扣减库存无超卖 |
| Alembic DM8 | 完整迁移操作测试 | create/add/drop/alter 全部通过 |
| 批量操作性能 | 1000/10000 行性能基准 | 差异在 2x 以内 |
| 中文编码 | 中文字段 CRUD + 搜索 | 无乱码、排序正确 |

### Phase 3（持续关注）🟡

| 风险 | 行动 | 验收标准 |
|------|------|---------|
| 参数嗅探 | Query Store 监控 | 无不稳定查询计划 |
| 方言版本升级 | 每次升级前全量回归 | CI 全部通过 |
| 分页性能 | Keyset 分页替代大 OFFSET | 100万行表分页 < 50ms |
