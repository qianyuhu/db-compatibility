# db-compatibility-demo

> **Phase 1 — 事实收集**
>
> MSSQL → KingbaseES → DM8 三库兼容性验证。
> 同一套 SQLAlchemy ORM 代码，三个数据库，收集真实差异数据。

---

## 项目目标

回答一个问题：

> "现有 MSSQL 项目迁移到 KingbaseES / DM8 时，
> 差异是否能够被兼容层或自动化工具屏蔽？"

当前 Phase 1 的做法：

- 以 MSSQL 为基准
- 运行同一套 pytest 测试
- 收集三库的真实差异
- **先不设计任何兼容方案**

---

## 技术栈（Phase 1）

```
pytest
  ↓
Repository（纯 Python）
  ↓
SQLAlchemy Session
  ↓
MSSQL / KingbaseES / DM8
```

**不在 Phase 1 范围内**：FastAPI、Service、API、Pydantic Schema、TypeDecorator、with_variant、Adapter。

---

## 快速开始

### 1. 系统依赖 (macOS)

```bash
# ODBC 驱动（MSSQL 连接必需）
brew install unixodbc
brew install --cask microsoft-odbc-driver-for-sql-server
```

### 2. 安装 Python 依赖

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# DM8 驱动（需要 DM8 客户端库）
# pip install dmPython dmSQLAlchemy
```

### 2. 启动数据库

```bash
# MSSQL（基准）
docker compose -f docker/compose.yml up -d

# KingbaseES（PG 协议，端口 54321）
docker compose -f docker/compose.kingbasees.yml up -d

# DM8（端口 5236）
docker compose -f docker/compose.dm8.yml up -d
```

### 3. 配置环境

```bash
# .env 包含默认值，.env.local 覆盖敏感信息（密码等）
# 配置读取优先级：.env.local > .env
cp .env .env.local
# 编辑 .env.local 填入实际密码
```

### 4. 运行迁移

```bash
# MSSQL
APP_ACTIVE_DB=mssql alembic upgrade head

# KingbaseES
APP_ACTIVE_DB=kingbasees alembic upgrade head

# DM8
APP_ACTIVE_DB=dm8 alembic upgrade head
```

### 5. 运行测试

```bash
# Step 1: SQL 编译对比（无需数据库连接，始终可跑）
pytest tests/test_sql_compile.py -v -s

# Step 2: MSSQL 基准（需 docker 启动 + 迁移完成）
APP_ACTIVE_DB=mssql alembic upgrade head
APP_ACTIVE_DB=mssql pytest tests/ -v

# Step 3: KingbaseES（需 docker 启动 + 环境变量）
KINGBASEES_AVAILABLE=1 APP_ACTIVE_DB=kingbasees alembic upgrade head
KINGBASEES_AVAILABLE=1 APP_ACTIVE_DB=kingbasees pytest tests/ -v

# Step 4: DM8
DM8_AVAILABLE=1 APP_ACTIVE_DB=dm8 alembic upgrade head
DM8_AVAILABLE=1 APP_ACTIVE_DB=dm8 pytest tests/ -v

# 注意：不可达的数据库自动 pytest.skip()，不会报错
```

---

## 项目结构

```
db-compatibility-demo/
├── src/app/
│   ├── core/
│   │   ├── config.py          # Settings — APP_ACTIVE_DB 切换
│   │   └── database.py        # engine + sessionmaker + get_session
│   ├── models/
│   │   ├── base.py            # DeclarativeBase
│   │   └── product.py         # Product（6种字段类型）
│   ├── repositories/
│   │   ├── base.py            # Repository[T] 泛型基类
│   │   └── product.py         # ProductRepository
│   └── migrations/
│       ├── env.py             # 动态 dialect 注入
│       ├── script.py.mako
│       └── versions/
├── tests/
│   ├── conftest.py            # 三库 parametrize + 连接探测 + Alembic fixtures
│   ├── test_baseline_crud.py  # CRUD 基准
│   ├── test_alembic.py        # Alembic upgrade/downgrade/autogenerate
│   ├── test_reflection.py     # Inspector 对比
│   └── test_sql_compile.py    # SQL 编译输出 → docs/
├── docker/                    # Docker compose 文件
├── docs/                      # Phase 0 研究文档 + Phase 1 输出
├── alembic.ini
├── pyproject.toml
└── README.md
```

---

## 三阶段策略

| 阶段 | 目标 | 状态 |
|------|------|------|
| Phase 0 | 调研、架构设计、风险分析 | ✅ 完成 |
| **Phase 1** | **事实收集（当前）** | 🔵 进行中 |
| Phase 2 | 兼容层设计与验证 | ⬜ 待启动 |
| Phase 3 | 自动化迁移工具评估 | ⬜ 待启动 |

详见 [`docs/architecture-design.md`](docs/architecture-design.md) 和 [`docs/demo-scope.md`](docs/demo-scope.md)。

---

## Phase 1 验证矩阵

| 矩阵 | 内容 | 测试文件 |
|------|------|---------|
| SQL Compilation | SELECT/INSERT/UPDATE/DELETE/LIMIT/LIKE 编译对比 | `test_sql_compile.py` |
| Alembic | upgrade/downgrade/autogenerate 三库对比 | `test_alembic.py` |
| CRUD 基准 | Create / Read / Update / Delete | `test_baseline_crud.py` |
| Reflection | Inspector 表/列/主键/索引/约束 | `test_reflection.py` |

---

## 预计风险点

以下是从 Phase 0 调研中识别的风险（**仅预测，待真实测试验证**）：

| # | 风险 | 预测影响 |
|---|------|---------|
| 1 | KingbaseES sys_* 系统表导致 reflection 失败 | 🔴 Inspector 不可用 |
| 2 | DM8 Boolean → SMALLINT，ORM 读写行为异常 | 🟡 is_active 字段 |
| 3 | MSSQL OFFSET 必须 ORDER BY，影响分页 | 🟡 list() 行为 |
| 4 | 三库自增 ID 获取方式不同 (IDENTITY/SERIAL/IDENTITY_INSERT) | 🟡 create() 返回值 |
| 5 | DateTime 精度差异 (100ns/μs/秒) | 🟢 创建时间精度 |
| 6 | MSSQL BIT 不能直接与 Python bool 映射 | 🟡 is_active 类型 |
| 7 | DM8 dmPython 驱动依赖系统库 | 🔴 安装复杂度 |
| 8 | KingbaseES 社区方言停更 (v0.0.1)，PG 方言可能有边缘问题 | 🔴 M1 矩阵 |
| 9 | macOS 缺少 unixODBC / ODBC Driver 18 导致 pyodbc 无法加载 | 🔴 测试环境 |
