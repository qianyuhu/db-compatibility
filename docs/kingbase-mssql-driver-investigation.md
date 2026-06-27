# KingbaseES MSSQL 兼容模式 — Driver 调研报告

## 调研结论摘要

| 问题 | 结论 |
|------|------|
| SQLAlchemy 官方支持 | ❌ **无官方支持** — SQLAlchemy 标准生态不包含 KingbaseES dialect |
| 可用 Python 驱动 | **psycopg2**（标准 PG wire protocol 驱动，端口 54321） |
| ksycopg2（厂商 fork） | ⚠️ 存在，但属厂商扩展，非 SQLAlchemy 标准生态组件 |
| pyodbc / pymssql | ❌ **不支持** — KingbaseES 不使用 TDS 协议 |
| 专用 SQLAlchemy dialect | ❌ **无可靠方案** — PyPI 无发布；社区实现未经认证；企业交付版本非开源生态 |
| SQLAlchemy PG 方言直连 | ❌ **不可用** — dialect 初始化假设数据库为 PostgreSQL，设计假设冲突 |
| 推荐连接方式 | psycopg2 原生驱动 + `autocommit=True`，Driver-Level Execution |

## 一、KingbaseES MSSQL 兼容模式原理

KingbaseES 通过 `database_mode = 'sqlserver'` 配置参数切换到 SQL Server 兼容模式。验证结果：

```
-- V009R001C010 枚举值确认
SELECT enumvals FROM sys_settings WHERE name = 'database_mode';
-- ['pg', 'oracle', 'mysql', 'sqlserver', '0', '1', '2', '3']
```

**兼容模式不改变底层传输协议** — KingbaseES 始终使用 PostgreSQL wire protocol（端口 54321），但在 SQL 层接受 T-SQL 语法（`TOP`、`BEGIN TRANSACTION`、`GETDATE()` 等）。

```
┌─────────────────────────────────────────────┐
│  应用层（Driver-Level Execution）              │
│  ⚠️ 不适用 SQLAlchemy ORM / Dialect           │
├─────────────────────────────────────────────┤
│  psycopg2 (PostgreSQL wire protocol)          │
├─────────────────────────────────────────────┤
│  KingbaseES 端口 54321                        │
│  ├─ 传输层: PostgreSQL wire protocol          │
│  └─ SQL 层: 取决于 database_mode 配置         │
│       ├─ pg: PostgreSQL 语法                 │
│       ├─ oracle: Oracle 语法                  │
│       └─ sqlserver: T-SQL 语法  ←             │
└─────────────────────────────────────────────┘
```

> **核心架构事实**：KingbaseES = PostgreSQL Wire Protocol + SQL Server-like SQL Mode + 非 PostgreSQL catalog system。协议层兼容 PG，但 SQL 语义、事务模型、系统目录均非 PG 标准，这是 SQLAlchemy PG dialect 无法直连的根本原因。

## 二、连接方式实测

### 2.1 原生 psycopg2 直连 ✅

```python
import psycopg2

conn = psycopg2.connect(
    host='114.232.68.44', port=54321,
    user='system', password='Jksoft8000',
    database='demo_db'
)
conn.autocommit = True  # 必须设置，否则 PG 协议层发 BEGIN 会报错

cur = conn.cursor()
cur.execute("SELECT @@VERSION")           # T-SQL 语法，正常执行
cur.execute("SELECT GETDATE()")           # T-SQL 函数，正常
cur.execute("SELECT TOP 5 * FROM sys_tables")  # T-SQL TOP，正常
```

**结论**：原生 psycopg2 可用。必须在连接后立即设置 `autocommit=True`。

> **关于 ksycopg2**：KingbaseES 提供了 `ksycopg2`（psycopg2 的厂商 fork，`pip install ksycopg2`），API 与 psycopg2 兼容。但 ksycopg2 是厂商扩展驱动，**不是 SQLAlchemy 标准生态组件**（SQLAlchemy 官方只认 psycopg2 / psycopg / asyncpg）。本项目统一使用 psycopg2 作为标准驱动。

### 2.2 SQLAlchemy PG 方言 ❌（两个阻断问题）

#### 阻断 1: `BEGIN` 语法冲突

SQLAlchemy PG 方言在连接时自动发送 `BEGIN`（PG 事务开始），KingbaseES SQL Server 模式只接受 `BEGIN TRANSACTION`：

```
LINE 1: BEGIN
             ^
syntax error at end of input
```

`isolation_level='AUTOCOMMIT'` 无法在连接建立阶段阻止此行为。

#### 阻断 2: 版本字符串解析失败

PG 方言期待 `PostgreSQL X.Y.Z` 格式，收到 `KingbaseES V009R001C010` 会抛出：

```
AssertionError: Could not determine version from string 'KingbaseES V009R001C010'
```

此错误发生在 `dialect.initialize()` 阶段，早于任何 SQL 执行。

#### 关于 monkey-patch 的说明

社区存在通过 monkey-patch `_get_server_version_info` 绕过版本解析的做法：

```python
from sqlalchemy.dialects.postgresql import base as pg_base
pg_base.PGDialect._get_server_version_info = lambda *args: (12, 4)
```

⚠️ **这不能作为设计方案**。原因：PG dialect 的失败不是单纯的"版本字符串问题"，而是 **dialect 初始化假设数据库就是 PostgreSQL**。KingbaseES SQLServer mode 的 SQL 语义、事务模型（`BEGIN TRANSACTION` vs `BEGIN`）、catalog 体系（`sys_catalog` vs `pg_catalog`）均与 PG 不同。monkey-patch 只是"骗过启动"，后续 ORM 操作仍会遇到兼容性冲突。**本项目禁止 dialect hack**。

### 2.3 SQLAlchemy + psycopg2 creator ✅ (绕过上述问题)

```python
import psycopg2
from sqlalchemy import create_engine

def get_conn():
    conn = psycopg2.connect(
        host='114.232.68.44', port=54321,
        user='system', password='Jksoft8000',
        database='demo_db',
        options='-c client_encoding=utf8'
    )
    conn.autocommit = True
    return conn

engine = create_engine('postgresql+psycopg2://', creator=get_conn)
```

但仍有局限：
- 反射（Inspector）依赖 `pg_catalog` → 被重命名为 `sys_catalog`
- `get_table_names()` 等反射功能不可用
- 需要手动查询 `sys_tables`, `sys_columns` 等

### 2.4 pyodbc / pymssql ❌

KingbaseES 在任何模式下都不提供 TDS 协议端口。pyodbc/pymssql 无法连接。

### 2.5 Dialect 现状评估

#### PyPI 标准生态：无可用包

```
$ pip3 install sqlalchemy-kingbase
ERROR: No matching distribution found for sqlalchemy-kingbase
```

#### 社区实验性实现：不可依赖

存在第三方仓库 [LFunTech/sqlalchemy-kingbase](https://github.com/LFunTech/sqlalchemy-kingbase)，但属于**实验性实现**：

- 无版本发布体系
- 无 CI coverage
- 无 SQLAlchemy 2.x 兼容性验证
- 无官方 endorsement

```python
# 仅供参考，不建议在生产使用
engine = create_engine('kingbase://username:password@host:54321/db')
```

#### 企业交付版本：非标准开源生态

KingbaseES 安装包内附带 SQLAlchemy 方言包（[官方文档](https://help.kingbase.com.cn/v8.6.7.12/development/client-interfaces-frame/sqlalchemy/sqlalchemy-1.html)），但：

- ❌ 未进入 PyPI 标准生态
- ❌ 未形成可持续开源维护链路
- ❌ 基于 SQLAlchemy 1.3.17 制作，2.x 兼容性不可验证
- ❌ 依赖 ksycopg2（厂商 fork），非 SQLAlchemy 标准驱动链

**结论：当前不存在可靠的 SQLAlchemy dialect 方案。**

## 三、版本对比

| 项目 | 远程服务器 | 本地 Docker |
|------|-----------|-------------|
| 版本 | V009R004C019 | V009R001C010 |
| database_mode | **sqlserver** | oracle（不支持运行时切换） |
| sqlserver_compatibility | — | on（oracle 模式下的兼容子集） |
| 驱动 | psycopg2 ✅ | psycopg2 ✅ |
| 连接验证 | ✅ 成功 | ✅ 成功（oracle 模式） |

**关键发现**：本地 Docker V009R001C010 虽然枚举值包含 `sqlserver`，但运行时切换后服务崩溃，需要新版本镜像或全新 initdb。

## 四、建议连接策略

### 架构决策：Driver-Level Execution Abstraction

KingbaseES 与 DM8 的正确抽象方式不是 ORM，而是 **Driver-Level Execution**：

| 数据库 | 抽象层 | 原因 |
|--------|--------|------|
| MSSQL | SQLAlchemy ORM + Dialect | 完整官方支持 |
| KingbaseES | psycopg2 raw driver executor | dialect 设计假设冲突，无可靠 ORM 方案 |
| DM8 | dmPython raw driver executor | 同上 |

### Phase 1（当前）

| 数据库 | 连接方式 | 优先级 |
|--------|---------|--------|
| MSSQL | SQLAlchemy + pyodbc (ODBC Driver 18) | P0 — 完整 ORM 支持 |
| KingbaseES | psycopg2 + autocommit（raw execution） | P1 — 驱动级执行 |
| DM8 | dmPython（待验证） | P2 — 待启动容器验证 |

❌ **禁止**：dialect hack / monkey-patch / 未认证社区 dialect

### Phase 2（未来，如需提升抽象层）

- SQL Compatibility Layer（SQL transform engine）
- SQL AST Normalization
- **NOT** ORM adaptation — 问题本质是 dialect mismatch，不是 ORM bug

### SQLAlchemy ORM 不适合作为 KingbaseES 主路径的根本原因

1. **事务模型冲突**：PG dialect 发送 `BEGIN`，KingbaseES sqlserver mode 要求 `BEGIN TRANSACTION`
2. **版本解析假设**：dialect 初始化硬编码 `PostgreSQL` 前缀，且假设数据库就是 PostgreSQL
3. **Catalog 体系不兼容**：反射依赖 `pg_catalog`，KingbaseES 使用 `sys_catalog`
4. **无可靠 dialect 方案**：PyPI 无发布、社区实现未认证、企业交付版本非开源生态

## 五、来源

- 实测：KingbaseES V009R001C010 Docker 容器（本地）+ V009R004C019 远程服务器
- KingbaseES 系统表：`sys_settings` 枚举值确认 `database_mode` 支持 sqlserver
- KingbaseES 官方文档：`https://help.kingbase.com.cn/`（SQL Server 兼容性章节）
- KingbaseES 官方 SQLAlchemy 框架文档：`https://help.kingbase.com.cn/v8.6.7.12/development/client-interfaces-frame/sqlalchemy/sqlalchemy-1.html`
- GitHub 社区方言包：`https://github.com/LFunTech/sqlalchemy-kingbase`
- 社区实测文章：掘金《KingbaseES 的 SQL Server 兼容性测试》、博客园《SQLAlchemy 兼容 KingbaseES 数据库问题解决》
