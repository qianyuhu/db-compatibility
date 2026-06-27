# 数据库环境报告 — Phase 1 Step 1

> 生成日期: 2026-06-27
>
> 目标: 完成三种数据库的连接验证，为后续兼容性测试提供基础。

---

## 一、MSSQL (SQL Server 2022)

| 项目 | 详情 |
|------|------|
| **Driver** | pyodbc 5.3.0 |
| **Dialect** | `mssql+pyodbc` (SQLAlchemy 2.0.51) |
| **Server Version** | Microsoft SQL Server 2022 (RTM-CU25) — 16.0.4255.1 (X64) |
| **连接字符串** | `mssql+pyodbc://sa:***@localhost:1433/demo_db?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=no` |
| **Collation** | SQL_Latin1_General_CP1_CI_AS |
| **连接状态** | ✅ 连接成功 |
| **SQLAlchemy Engine** | ✅ 标准 support |
| **SQLAlchemy Session** | ✅ 标准 support |

### 验证结果

```
$ pytest tests/test_connection.py -k "MSSQL" -v
test_connection          PASSED  ✓ SELECT @@VERSION 成功
test_sqlalchemy_engine   PASSED  ✓ get_engine() 返回有效 Engine
```

### 容器信息

```
docker ps
sqlserver  mcr.microsoft.com/mssql/server:2022-latest  Up 31 minutes  1433:1433
```

### 已知问题

无。MSSQL 是本项目的生产基准，SQLAlchemy + pyodbc + ODBC Driver 18 组合工作正常。

---

## 二、KingbaseES MSSQL Compatible Edition

| 项目 | 详情 |
|------|------|
| **Driver** | psycopg2 2.9.12（原生，非 SQLAlchemy Dialect） |
| **Dialect** | **无** — PG Dialect 存在两个阻断 bug（见下方） |
| **Server Version** | KingbaseES V009R004C019 |
| **兼容模式** | `database_mode = sqlserver` |
| **兼容子开关** | `sqlserver_compatibility = on`（已在 oracle 模式的本地 Docker 确认） |
| **编码** | GB18030 (`lc_collate = zh_CN.GB18030`) |
| **连接字符串** | `postgresql+psycopg2://system:***@114.232.68.44:54321/demo_db` |
| **连接状态** | ✅ 原生 psycopg2 (autocommit) 连接成功 |
| **SQLAlchemy Engine** | ❌ 不可用（见下方阻断问题） |
| **SQLAlchemy Session** | ❌ 不可用 |

### 验证结果

```
$ APP_ACTIVE_DB=kingbasees pytest tests/test_connection.py -k "KingbaseES" -v
test_connection              PASSED ✓ version(), database_mode, SELECT 1
test_raw_connection_works    PASSED ✓ 原生 psycopg2 (autocommit)
test_sqlalchemy_engine_is_none PASSED ✓ engine 为 None（预期行为）
```

### 两个阻断问题（SQLAlchemy PG Dialect 不可用）

#### 阻断 1: `BEGIN` 事务语法冲突

PG Dialect 在连接时自动发送 `BEGIN`（PG 事务语法），KingbaseES SQL Server 模式只接受 `BEGIN TRANSACTION`（T-SQL 语法）。

```
LINE 1: BEGIN
             ^
syntax error at end of input
```

#### 阻断 2: 版本字符串解析失败

PG Dialect 期待 `PostgreSQL X.Y.Z`，收到 `KingbaseES V009R004C019` 抛出 `AssertionError`。

#### 绕过方案

使用原生 psycopg2 连接，设置 `autocommit=True`：

```python
import psycopg2
conn = psycopg2.connect(host='...', port=54321, ...)
conn.autocommit = True  # 必须在连接后立即设置
cur = conn.cursor()
cur.execute("SELECT @@VERSION")
cur.execute("SELECT GETDATE()")
cur.execute("BEGIN TRANSACTION; ...; COMMIT;")
```

SQLAlchemy `create_engine()` 的 `creator` 参数可以传入此 autocommit 连接，但初始化阶段的版本解析仍会失败。

### 本地 Docker vs 远程服务器

| 项目 | 本地 Docker | 远程服务器 |
|------|------------|-----------|
| 版本 | V009R001C010 | V009R004C019 |
| database_mode | oracle | **sqlserver** ✅ |
| 镜像 | `kingbase_v009r001c010b0004_single_x86:v1` | — |
| 状态 | oracle 模式（切换 sqlserver 后崩溃） | 正常 |

本地 Docker 版本较旧，虽枚举值包含 `sqlserver` 但无法稳定运行。建议获取 V009R004C019+ 镜像。

### 需要关注的问题

1. **没有正式的 KingbaseES SQLAlchemy Dialect** — 社区 `sqlalchemy-kingbase` 未发布到 PyPI
2. **系统表命名差异** — `pg_*` → `sys_*`，Reflection（Inspector）不可用
3. **编码差异** — GB18030 vs MSSQL 的 UTF-16，字符串处理需注意
4. **数据类型映射** — 需逐项验证（见后续 M5 SQL Compilation 矩阵）
5. **存储过程** — PL/SQL 语法 vs T-SQL 语法

---

## 三、DM8 (达梦)

| 项目 | 详情 |
|------|------|
| **Driver** | dmPython（未安装）|
| **Dialect** | `dm+dmPython` |
| **Server Version** | 未知 |
| **连接字符串** | `dm+dmPython://SYSDBA:***@localhost:5236/demo_db` |
| **连接状态** | ❌ 驱动未安装 + Docker 未启动 |
| **SQLAlchemy Engine** | ❌ 待验证 |
| **SQLAlchemy Session** | ❌ 待验证 |

### 验证结果

```
$ pytest tests/test_connection.py -k "DM8" -v
test_connection  SKIPPED (dmPython 未安装，DM8 Docker 未启动)
```

### 待完成

```bash
# 1. 安装驱动
pip install dmPython

# 2. 启动 Docker
docker compose -f docker/compose.dm8.yml up -d

# 3. 验证
pytest tests/test_connection.py::TestDM8Connection -v
```

---

## 四、测试结果汇总

```
$ pytest tests/test_connection.py -v
tests/test_connection.py::TestMSSQLConnection::test_connection PASSED
tests/test_connection.py::TestMSSQLConnection::test_sqlalchemy_engine PASSED
tests/test_connection.py::TestKingbaseESConnection::test_connection PASSED
tests/test_connection.py::TestKingbaseESConnection::test_raw_connection_works PASSED
tests/test_connection.py::TestKingbaseESConnection::test_sqlalchemy_engine_is_none PASSED
tests/test_connection.py::TestDM8Connection::test_connection SKIPPED
tests/test_connection.py::TestAllDatabases::test_connection_summary PASSED

6 passed, 1 skipped
```

### 连接汇总

| 数据库 | Driver | Dialect | Server Version | 状态 |
|--------|--------|---------|---------------|------|
| MSSQL | pyodbc | mssql+pyodbc ✅ | SQL Server 2022 (16.0.4255.1) | ✅ |
| KingbaseES | psycopg2 (原生) | 无（PG Dialect 阻断） | KingbaseES V009R004C019 | ✅ (原生模式) |
| DM8 | dmPython | dm+dmPython | — | ❌ 待安装 |

---

## 五、目录结构（当前）

```
src/app/
  core/
    config.py           # 三库配置（APP_ACTIVE_DB 切换）
    database.py         # get_engine() / get_session_local() / get_raw_connection() / get_db()

tests/
  conftest.py           # pytest fixtures（三库 parametrize）
  test_connection.py    # 数据库连接验证（本次新建）
  test_alembic.py       # M4 Alembic 矩阵（已有）
  test_sql_compile.py   # M5 SQL 编译矩阵（已有）

docs/
  database-environment-report.md           # 本报告（本次新建）
  kingbase-mssql-driver-investigation.md  # KingbaseES Driver 调研（本次新建）

demo/sqlserver/         # SQL Demo（12 个 SQL 文件，已验证）
```

---

## 六、后续建议

### 立即可做

1. **M5: SQL Compilation** — 用 `test_sql_compile.py` 对比三库 ORM → SQL 生成差异
2. **M1: KingbaseES MSSQL 兼容性验证** — 用原生 psycopg2 执行 MSSQL Demo SQL 文件

### 需要环境准备

3. **DM8 环境** — 安装 dmPython + 启动 Docker
4. **KingbaseES 本地镜像** — 获取 V009R004C019+ 镜像以支持 sqlserver 模式本地测试

### 待设计

5. **M3: Reflection** — 确认 KingbaseES/DM8 Inspector 支持程度
6. **M4: Alembic** — 三库迁移兼容性
7. **M6: Procedure** — 存储过程 PL 方言对比
