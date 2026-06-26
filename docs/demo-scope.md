# Demo 范围与验证矩阵（三阶段 — 事实先行）

> Phase 0 输出文档 · 2026-06-26（v5）
>
> 策略：Phase 1 收集事实 → Phase 2 设计兼容层 → Phase 3 评估自动化
> 原则：Phase 1 不包含 Web 框架、不设计解决方案、不做自动化评估

---

## 项目定位

### 我们要回答的问题

> "现有 MSSQL 项目迁移到 KingbaseES 和 DM8 时，差异是否能够被兼容层或工具屏蔽？"

### 不是目标

- ❌ 不是验证 FastAPI 好不好用
- ❌ 不是从零设计"数据库无关"系统
- ❌ 不是提前设计兼容层

### 是目标

- ✅ 以 MSSQL 为基准，收集三库真实差异数据
- ✅ 基于真实数据判断"差异能否被屏蔽"
- ✅ 为现有 MSSQL 项目提供可操作的迁移路径

---

## 三阶段策略

```
Phase 1: 事实收集                    Phase 2: 兼容层设计               Phase 3: 自动化评估
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
策略：只收集事实，不设计方案           策略：基于 Phase 1 真实差异           策略：评估迁移自动化可行性
                                    设计并验证兼容层

MSSQL 基准（纯 pytest）              ←Phase1 差异数据输入←              ←Phase2 方案输入←
↓                                    针对真实问题设计：                  MSSQL 源码扫描规则
KingbaseES 验证                       ├─ TypeDecorator                  自动识别规则库
├─ PG 方言可用性                      ├─ with_variant                   自动修复生成
├─ CRUD / 类型 / Reflection           ├─ Repository Adapter              可自动 vs 需人工比例
├─ Alembic / SQL 编译                 ├─ Dialect Adapter
├─ Stored Procedure                   └─ Alembic Adapter                产出：
↓                                    ↓                                  auto-migration-feasibility.md
DM8 验证                              验证：方案能否屏蔽差异？
├─ dmSQLAlchemy 覆盖度               ↓
├─ 同上方六个维度                      差异清单 →
↓                                    ├─ 已被屏蔽的差异
Phase 1 产出（纯事实）：               ├─ 无法屏蔽的差异
compatibility-matrix.md              └─ 屏蔽方案与代价
known-differences.md
（无解决方案，无 Web 框架代码）         产出：
                                     compatibility-layer-design.md
                                     phase2-report.md

时间：2-3 天                          时间：+2-3 天                          时间：+1-2 天
```

---

## Phase 1 — 事实收集

### 1.0 技术栈（最小化）

```
pytest
  ↓
Repository（纯 Python 类，不含 HTTP）
  ↓
SQLAlchemy Session
  ↓
MSSQL / KingbaseES / DM8
```

**Phase 1 明确不包含**：
- ❌ FastAPI
- ❌ api/ / services/ / main.py
- ❌ Pydantic schemas
- ❌ HTTP 端点
- ❌ 任何 Web 框架代码
- ❌ `compat/` 目录
- ❌ TypeDecorator / with_variant / Adapter

只保留 `models/` + `repositories/` + `core/` + `tests/`。

### 1.1 目录结构

```
db-compatibility-demo/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py              # Settings（APP_ACTIVE_DB 切换）
│       │   └── database.py            # 引擎 + Session + get_session
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py                # DeclarativeBase
│       │   └── product.py             # Product（8 种字段类型）
│       ├── repositories/
│       │   ├── __init__.py
│       │   ├── base.py                # Repository[T]
│       │   └── product.py             # ProductRepository
│       └── migrations/
│           ├── env.py
│           └── versions/
│               └── 001_create_products.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                        # fixtures
│   ├── test_m1_kingbasees_pg_dialect.py   # M1: PG 方言验证
│   ├── test_m2_dm8_dialect.py             # M2: DM8 方言验证
│   ├── test_m3_reflection.py              # M3: Reflection
│   ├── test_m4_alembic.py                 # M4: Alembic
│   ├── test_m5_sql_compilation.py         # M5: SQL 编译
│   └── test_m6_procedure.py               # M6: 存储过程
│
├── docker/
│   ├── compose.yml                    # mssql only
│   ├── compose.kingbasees.yml
│   ├── compose.dm8.yml
│   └── Dockerfile
│
├── alembic.ini
├── pyproject.toml
└── README.md
```

### 1.2 Product 模型（扩展类型覆盖）

```python
# models/product.py
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean,
    DateTime, Text, JSON, LargeBinary, func,
)
from .base import Base

class Product(Base):
    __tablename__ = "products"

    # 基础类型
    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(50), unique=True, nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    price       = Column(Numeric(10, 2), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, server_default=func.now(), nullable=False)

    # 扩展类型（国产化迁移易出问题的类型）
    description = Column(Text, nullable=True)          # Text → MSSQL NVARCHAR(MAX) / PG TEXT / DM8 CLOB
    extra_data  = Column(JSON, nullable=True)           # JSON → MSSQL 无原生 / PG JSONB / DM8 JSON
    file_hash   = Column(String(36), nullable=True)     # UUID 模拟 → MSSQL UNIQUEIDENTIFIER / PG UUID / DM8 VARCHAR2(36)
    thumbnail   = Column(LargeBinary, nullable=True)    # 二进制 → MSSQL VARBINARY(MAX) / PG BYTEA / DM8 BLOB
```

**10 种字段类型覆盖**：Integer, String(50), String(200), Numeric, Boolean, DateTime, Text, JSON, String(36)(UUID模拟), LargeBinary。

**不是要求全部通过。而是验证：不支持时如何报错、能否被 Phase 2 的兼容层解决。**

### 1.3 六大验证矩阵

#### M1：KingbaseES PostgreSQL 方言直连验证

| # | 测试项 | 方法 | 记录内容 |
|---|--------|------|---------|
| K1 | 连接 | `postgresql+psycopg2://user:pass@host:54321/db` | 成功/失败 + 配置参数 |
| K2 | CRUD | 复用 MSSQL 基准代码（零修改） | 每项通过/失败 + 错误信息 |
| K3 | 10种类型往返 | 写后读 | 值一致性 + 精度 |
| K4 | 自增 PK | Integer autoincrement | IDENTITY / SERIAL 行为 |
| K5 | 分页（有/无 ORDER BY） | list(skip, limit) | MSSQL 报错 vs PG 接受 |
| K6 | String Unicode | 中文写入→读取 | 编码是否正确 |

#### M2：DM8 方言验证

| # | 测试项 | 方法 | 记录内容 |
|---|--------|------|---------|
| D1 | 连接 | `dm+dmPython://user:pass@host:5236/db` | 成功/失败 |
| D2 | CRUD | 复用 MSSQL 基准代码 | 每项通过/失败 + 错误信息 |
| D3 | 10种类型往返 | 写后读 | SMALLINT→Bool 转换、DATE含时间等 |
| D4 | 自增 PK | Integer autoincrement | IDENTITY 是否需显式声明 |
| D5 | 分页（ANSI vs ROWNUM） | list(skip, limit) | 两种模式行为差异 |
| D6 | String Unicode | 中文写入→读取 | 编码是否正确 |

#### M3：SQLAlchemy Inspector (Reflection) 兼容性

| # | 测试项 | 方法 | 记录内容 |
|---|--------|------|---------|
| R1 | get_table_names() | `inspector.get_table_names()` | 三库返回一致性 |
| R2 | get_columns() | `inspector.get_columns('products')` | 列名/类型/Nullable 正确性 |
| R3 | get_pk_constraint() | `inspector.get_pk_constraint('products')` | 主键识别 |
| R4 | get_indexes() | `inspector.get_indexes('products')` | 索引信息 |
| R5 | get_unique_constraints() | 唯一约束识别 | 三库一致性 |
| R6 | **KingbaseES sys_* 影响** | 对比 PG 方言 reflection 结果 | 是否因 sys_* 失败 |

#### M4：Alembic upgrade / autogenerate 兼容性

| # | 测试项 | 方法 | 记录内容 |
|---|--------|------|---------|
| A1 | upgrade head | `alembic upgrade head` | 建表 DDL 正确性 |
| A2 | downgrade | `alembic downgrade -1` | 删表成功 |
| A3 | autogenerate 新增字段 | 模型加字段 → `--autogenerate` | 检测正确性 |
| A4 | autogenerate 新增表 | 新增模型 → `--autogenerate` | 生成正确性 |
| A5 | **MSSQL batch mode** | ALTER TABLE 行为 | 是否需要 batch mode |
| A6 | **KingbaseES autogenerate** | PG 方言 + KingbaseES | sys_* 是否导致不可用 |
| A7 | **DM8 autogenerate** | dmSQLAlchemy 方言 | autogenerate 可用程度 |

#### M5：SQL Compilation 兼容性

| # | 测试项 | SQLAlchemy 操作 | 验证问题 |
|---|--------|----------------|---------|
| S1 | SELECT | `session.get()` / `select()` | WHERE 子句编译差异 |
| S2 | INSERT | `session.add()` + `commit()` | 自增值获取方式 |
| S3 | UPDATE | `session.query().update()` / ORM update | SET 子句编译差异 |
| S4 | DELETE | `session.query().delete()` / ORM delete | 行为差异 |
| S5 | LIMIT/OFFSET | `.limit().offset()` | 生成 SQL 文本差异 |
| S6 | ORDER BY | `.order_by()` | NULL 排序差异 |
| S7 | COUNT | `func.count()` | 返回值类型差异 |
| S8 | 批量 INSERT | `session.execute(insert(values), [...])` | 三库语法差异 |
| S9 | GROUP BY | `.group_by()` | 编译正确性 |
| S10 | LIKE | `.filter(Product.name.like('%搜索%'))` | 中文 LIKE 行为 |

#### M6：Stored Procedure 兼容性

| # | 测试项 | 方法 | 记录内容 |
|---|--------|------|---------|
| P1 | 无参数 SP | `CALL/EXEC simple_sp()` | 调用语法差异 |
| P2 | 输入参数 | `CALL sp_with_params(:p1, :p2)` | 参数绑定差异 |
| P3 | 输出参数 | 获取 OUTPUT/OUT 参数 | 三库输出参数 API |
| P4 | 返回结果集 | `SELECT` from SP | 结果集获取方式 |
| P5 | SP 内事务 | SP 内部 COMMIT/ROLLBACK | 事务边界差异 |
| P6 | 错误处理 | SP 执行失败场景 | 错误码/异常差异 |

### 1.4 Phase 1 输出

#### compatibility-matrix.md（纯事实）

```markdown
| 特性 | MSSQL (基准) | KingbaseES (PG Dialect) | DM8 (dmSQLAlchemy) | 严重度 |
|------|-------------|------------------------|--------------------|--------|
| Integer PK 自增 | ✅ IDENTITY | ⚠️ SERIAL(V8R3) / IDENTITY(V8R6) | ✅ IDENTITY | 🟢 低 |
| Boolean | ✅ BIT | ✅ BOOLEAN | ⚠️ SMALLINT | 🟡 中 |
| DateTime | ✅ DATETIME2(100ns) | ✅ TIMESTAMP(μs) | ⚠️ DATE(含时间,秒) | 🟡 中 |
| Text | ✅ NVARCHAR(MAX) | ✅ TEXT | ⚠️ CLOB | 🟢 低 |
| JSON | ❌ 无原生类型 | ✅ JSONB | ✅ JSON/JSONB | 🔴 高 |
| LargeBinary | ✅ VARBINARY(MAX) | ✅ BYTEA | ⚠️ BLOB | 🟢 低 |
| UUID(String36) | ✅ UNIQUEIDENTIFIER | ✅ UUID | ⚠️ VARCHAR2(36) | 🟡 中 |
| Reflection | ✅ | 🔴 sys_* 导致失败 | ✅ | 🔴 高 |
| Alembic autogen | ✅ | 🔴 不可用 | ⚠️ 部分可用 | 🔴 高 |
| LIMIT/OFFSET | ⚠️ 需 ORDER BY | ✅ 可选 | ⚠️ ANSI 需 ORDER BY | 🟡 中 |
| Stored Procedure | ✅ T-SQL | ⚠️ PL/pgSQL | ⚠️ PL/SQL(Oracle) | 🔴 高 |
| ...
```

#### known-differences.md（纯事实，无方案）

```markdown
## 差异 1: KingbaseES Reflection 不可用
- **问题**: inspector.get_columns() / get_table_names() 全部失败
- **根因**: SQLAlchemy PGDialect 硬编码查询 pg_class / pg_namespace，
  KingbaseES 系统表为 sys_class / sys_namespace
- **影响**: 所有依赖 Reflection 的功能不可用（Alembic autogenerate、动态 Schema 查询等）
- **严重度**: 🔴 Critical

## 差异 2: MSSQL 无原生 JSON 类型
- **问题**: SQLAlchemy JSON 类型在 MSSQL 上映射失败或行为异常
- **根因**: SQL Server 无 JSON 数据类型，JSON_QUERY/JSON_VALUE 仅为函数
- **影响**: JSON 列定义在 MSSQL 上生成的 DDL 不正确
- **严重度**: 🔴 High

## 差异 3: DM8 Boolean 无原生类型
- **问题**: Boolean 在 DM8 上映射为 SMALLINT
- **根因**: DM8 不支持 SQL 标准 BOOLEAN 类型
- **影响**: 原生 SQL 中 WHERE is_active = true 语法不正确
- **严重度**: 🟡 Medium

...
```

**Phase 1 明确不写入**：
- ❌ "解决方案"（放 Phase 2 `compatibility-layer-design.md`）
- ❌ "是否可屏蔽"（Phase 1 不知道答案）
- ❌ "自动化难度"（放 Phase 3）

---

## Phase 2 — 兼容层设计与验证

> ⚠️ 仅在 Phase 1 完成后启动。

### Phase 2 任务

| # | 任务 | 输入 |
|---|------|------|
| 1 | 分析 Phase 1 差异清单，分类可屏蔽 vs 不可屏蔽 | known-differences.md |
| 2 | 设计 TypeDecorator（Boolean/DateTime/JSON/UUID） | compatibility-matrix.md |
| 3 | 设计 Dialect Adapter（KingbaseES sys_* 反射） | M3 Reflection 失败项 |
| 4 | 设计 Alembic Adapter（DDL 差异适配） | M4 Alembic 失败项 |
| 5 | 设计 Repository Adapter（分页/批量/锁） | M5 SQL Compilation 差异项 |
| 6 | 增加多表模型（Order / OrderItem / Inventory） | — |
| 7 | 验证跨表事务 + 乐观锁 + 悲观锁 | — |
| 8 | 验证兼容层在西场景中的屏蔽效果 | — |

### Phase 2 产出

- `compatibility-layer-design.md`
- `phase2-report.md`
- 更新 `known-differences.md`（增加"屏蔽后状态"列 — 仅在方案已验证后）

---

## Phase 3 — 自动化迁移工具可行性评估

> ⚠️ 仅在 Phase 2 完成后启动。

### Phase 3 任务

| # | 任务 |
|---|------|
| 1 | 定义 MSSQL 项目源码扫描规则 |
| 2 | 基于 Phase 1-2 数据设计兼容性风险识别规则库 |
| 3 | 评估可自动修复的差异比例 |
| 4 | 设计自动修复代码生成逻辑 |
| 5 | 输出自动化覆盖率 + 需人工介入比例 |

### Phase 3 产出

- `auto-migration-feasibility.md`

---

## Phase 1 任务清单（30 个）

```
P0 ─ 环境搭建
  □ 1. pyproject.toml + 依赖
  □ 2. .env 配置（APP_ACTIVE_DB）
  □ 3. core/config.py
  □ 4. core/database.py（engine + session factory）
  □ 5. Docker compose.yml（MSSQL）+ Dockerfile

P1 ─ 模型 + 数据访问
  □ 6. models/base.py
  □ 7. models/product.py（10种字段类型）
  □ 8. repositories/base.py（Repository[T]）
  □ 9. repositories/product.py

P2 ─ 迁移
  □ 10. alembic.ini + migrations/env.py
  □ 11. 001_create_products.py

P3 ─ 测试基础设施
  □ 12. tests/conftest.py（fixtures + db_name parametrize）

P4 ─ MSSQL 基准（先跑通）
  □ 13. tests/test_m5_sql_compilation.py（MSSQL 上全部通过）

P5 ─ KingbaseES PG 方言验证  ← 提前
  □ 14. Docker compose.kingbasees.yml
  □ 15. tests/test_m1_kingbasees_pg_dialect.py
  □ 16. 结论：PG 方言可用程度

P6 ─ DM8 方言验证  ← 提前
  □ 17. Docker compose.dm8.yml
  □ 18. tests/test_m2_dm8_dialect.py
  □ 19. 结论：dmSQLAlchemy 覆盖程度

P7 ─ Reflection
  □ 20. tests/test_m3_reflection.py（三库对比）
  □ 21. 结论：KingbaseES sys_* 影响完整评估

P8 ─ Alembic
  □ 22. tests/test_m4_alembic.py（三库对比）

P9 ─ SQL Compilation（三库完整对比）
  □ 23. tests/test_m5_sql_compilation.py（扩展到三库）

P10 ─ 存储过程
  □ 24. ALembic 迁移增加 SP（三库各自）
  □ 25. tests/test_m6_procedure.py（三库对比）

P11 ─ 文档
  □ 26. compatibility-matrix.md（纯事实）
  □ 27. known-differences.md（纯事实，无方案）
  □ 28. phase1-report.md

Phase 1 完成 → 暂停 → 等待 Phase 2 指令
```

### 验收标准

```bash
# Step 1: MSSQL 基准
$ APP_ACTIVE_DB=mssql pytest tests/ -v
→ MSSQL 全部通过 ✅

# Step 2: KingbaseES
$ APP_ACTIVE_DB=kingbasees pytest tests/ -v
→ 记录每项通过/失败 + 根因

# Step 3: DM8
$ APP_ACTIVE_DB=dm8 pytest tests/ -v
→ 记录每项通过/失败 + 根因

# Step 4: 输出
→ compatibility-matrix.md（6矩阵 × 3数据库）
→ known-differences.md（纯事实，无方案预判）
```

---

## 最终交付物

```
docs/
├── compatibility-report.md          # Phase 0（已完成）
├── database-risk-analysis.md        # Phase 0（已完成）
├── architecture-design.md           # Phase 0（已完成）
├── demo-scope.md                   # 本文档（v5）
│
├── compatibility-matrix.md          # Phase 1
├── known-differences.md             # Phase 1（纯事实）
├── phase1-report.md                 # Phase 1
│
├── compatibility-layer-design.md    # Phase 2
├── phase2-report.md                 # Phase 2
│
└── auto-migration-feasibility.md    # Phase 3
```
