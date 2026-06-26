# 架构设计方案（三阶段实施）

> Phase 0 输出文档 · 2026-06-26（v5）
>
> 原则：Phase 1 只收集事实，不含 Web 框架、不设计兼容层、不做自动化评估

---

## 1. 项目定位

| 维度 | 说明 |
|------|------|
| **主数据库** | MSSQL (SQL Server 2019+) — 当前生产平台 |
| **迁移目标** | KingbaseES, DM8 — 国产化替代方案 |
| **最终目标** | 输出"差异是否可被兼容层或工具屏蔽"的结论 |
| **交付物** | compatibility-matrix → known-differences → 兼容层方案 → 自动化评估 |

## 2. 设计约束

| 约束 | 说明 |
|------|------|
| **MSSQL 优先** | 所有实现以 MSSQL 为基准，再验证迁移目标 |
| **Phase 1 零 Web 框架** | 只保留 pytest → Repository → SQLAlchemy → DB，无 FastAPI |
| **Phase 1 零兼容层** | 不设计 TypeDecorator / Adapter / with_variant |
| **Phase 1 零解决方案** | known-differences.md 只记录问题/根因/影响/严重度 |
| **Phase 1 零自动化评估** | 自动化可行性在 Phase 3 |
| **同步 Session** | 简单，聚焦兼容性验证 |

---

## 3. 三阶段策略

```
Phase 1: 事实收集                    Phase 2: 兼容层设计               Phase 3: 自动化评估
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pytest → Repository → SQLAlchemy    ←Phase1 真实差异数据←              ←Phase2 方案数据←
↓
MSSQL 基准                          TypeDecorator                      MSSQL 扫描规则
↓                                   Dialect Adapter                    自动识别规则库
KingbaseES 验证 (M1)                Alembic Adapter                    可自动 vs 需人工
├─ PG 方言能否直连？                 Repository Adapter
├─ CRUD / 类型 / 自增 / 分页          ↓
├─ Reflection / Alembic             验证屏蔽效果                       auto-migration-feasibility.md
├─ SQL 编译 / Stored Procedure      ↓
↓                                   差异清单 →
DM8 验证 (M2)                       ├─ 已屏蔽
├─ dmSQLAlchemy 覆盖度              └─ 不可屏蔽 + 代价
└─ 同上方全部维度
↓                                   compatibility-layer-design.md
compatibility-matrix.md
known-differences.md
（纯事实，不含方案）
```

---

## 4. Phase 1 目录结构

```
db-compatibility-demo/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py              # APP_ACTIVE_DB=mssql|kingbasees|dm8
│       │   └── database.py            # create_engine + Session + get_session
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py                # DeclarativeBase
│       │   └── product.py             # Product（10 种字段类型）
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
│   ├── conftest.py                    # fixtures (db_name parametrize)
│   ├── test_m1_kingbasees_pg_dialect.py
│   ├── test_m2_dm8_dialect.py
│   ├── test_m3_reflection.py
│   ├── test_m4_alembic.py
│   ├── test_m5_sql_compilation.py
│   └── test_m6_procedure.py
│
├── docker/
│   ├── compose.yml                    # mssql
│   ├── compose.kingbasees.yml
│   └── compose.dm8.yml
│
├── alembic.ini
├── pyproject.toml
└── README.md
```

**Phase 1 目录中明确不存在**：
- `api/` — 无 HTTP 端点
- `services/` — 无业务编排层
- `main.py` — 无 FastAPI 应用
- `compat/` — 无兼容层
- `schemas/` — 无 Pydantic 模型

---

## 5. Phase 1 详细设计

### 5.1 技术栈（最小化）

```
pytest
  ↓ 调用
Repository (纯 Python 类)
  ↓ 使用
SQLAlchemy Session
  ↓ 连接
MSSQL / KingbaseES / DM8
```

不需要 Web 框架。pytest fixture 提供 Session，Repository 直接操作数据库。

### 5.2 配置

```python
# core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "APP_"}
    active_db: str = "mssql"

    # MSSQL
    mssql_host: str = "localhost"; mssql_port: int = 1433
    mssql_database: str = "demo_db"; mssql_user: str = "sa"; mssql_password: str = ""

    # KingbaseES
    kingbasees_host: str = "localhost"; kingbasees_port: int = 54321
    kingbasees_database: str = "demo_db"; kingbasees_user: str = "system"; kingbasees_password: str = ""

    # DM8
    dm8_host: str = "localhost"; dm8_port: int = 5236
    dm8_database: str = "demo_db"; dm8_user: str = "SYSDBA"; dm8_password: str = ""

    @property
    def database_url(self) -> str:
        if self.active_db == "mssql":
            return (
                f"mssql+pyodbc://{self.mssql_user}:{self.mssql_password}"
                f"@{self.mssql_host}:{self.mssql_port}/{self.mssql_database}"
                "?driver=ODBC+Driver+18+for+SQL+Server"
                "&TrustServerCertificate=yes&Encrypt=no"
            )
        elif self.active_db == "kingbasees":
            return (
                f"postgresql+psycopg2://{self.kingbasees_user}:{self.kingbasees_password}"
                f"@{self.kingbasees_host}:{self.kingbasees_port}/{self.kingbasees_database}"
                "?options=-c+client_encoding=utf8"
            )
        elif self.active_db == "dm8":
            return (
                f"dm+dmPython://{self.dm8_user}:{self.dm8_password}"
                f"@{self.dm8_host}:{self.dm8_port}/{self.dm8_database}"
            )
        raise ValueError(f"Unknown active_db: {self.active_db}")

settings = Settings()
```

### 5.3 数据库引擎

```python
# core/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from .config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_session() -> Session:
    """返回一个新的 Session（非 generator，供 pytest fixture 使用）"""
    return SessionLocal()
```

### 5.4 模型

> **实现状态**：初始骨架实现了 6 种基础类型（id/code/name/price/is_active/created_at）。
> 扩展类型（Text/JSON/LargeBinary/String(36)）将在 Phase 1 后续迭代中加入。
> 此文档描述最终目标，非当前代码快照。

```python
# models/product.py — 当前骨架（6 种基础类型）
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, DateTime, func,
)
from .base import Base

class Product(Base):
    __tablename__ = "products"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(50), unique=True, nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    price       = Column(Numeric(10, 2), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, server_default=func.now(), nullable=False)

    # --- 以下字段在后续迭代加入 ---
    # description = Column(Text, nullable=True)
    # extra_data  = Column(JSON, nullable=True)
    # file_hash   = Column(String(36), nullable=True)    # UUID 模拟
    # thumbnail   = Column(LargeBinary, nullable=True)
```

使用最朴素的 SQLAlchemy 泛型，不做任何 `with_variant` 或 `TypeDecorator` 适配。

**这就是我们要测试的东西。**

### 5.5 Repository

```python
# repositories/base.py
from typing import TypeVar, Generic, Optional, Sequence
from sqlalchemy.orm import Session
from sqlalchemy import select, func, insert

T = TypeVar("T")

class Repository(Generic[T]):
    model: type[T]

    def __init__(self, session: Session):
        self.session = session

    def get(self, id: int) -> Optional[T]:
        return self.session.get(self.model, id)

    def list(self, skip: int = 0, limit: int = 100,
             order_by: str = "id") -> tuple[Sequence[T], int]:
        total = self.session.scalar(
            select(func.count()).select_from(self.model)
        )
        stmt = (
            select(self.model)
            .order_by(getattr(self.model, order_by))
            .offset(skip).limit(limit)
        )
        return self.session.scalars(stmt).all(), total

    def create(self, data: dict) -> T:
        entity = self.model(**data)
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def update(self, id: int, data: dict) -> Optional[T]:
        entity = self.get(id)
        if not entity:
            return None
        for k, v in data.items():
            setattr(entity, k, v)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def delete(self, id: int) -> bool:
        entity = self.get(id)
        if not entity:
            return False
        self.session.delete(entity)
        self.session.commit()
        return True

    def bulk_insert(self, records: list[dict]) -> int:
        """Core 层批量插入"""
        stmt = insert(self.model).values(records)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount


# repositories/product.py
from app.models.product import Product

class ProductRepository(Repository[Product]):
    model = Product
```

### 5.6 测试基础设施

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.models.base import Base
from app.models.product import Product

def _make_settings(db_name: str) -> Settings:
    s = Settings()
    s.active_db = db_name
    return s

def _get_available_dbs() -> list[str]:
    """获取可用的数据库列表"""
    dbs = ["mssql"]  # 始终可用
    # CI 环境变量控制额外数据库
    if os.environ.get("KINGBASEES_AVAILABLE"):
        dbs.append("kingbasees")
    if os.environ.get("DM8_AVAILABLE"):
        dbs.append("dm8")
    return dbs

@pytest.fixture(params=_get_available_dbs())
def db_name(request) -> str:
    return request.param

@pytest.fixture
def db_session(db_name: str) -> Session:
    """每个测试获取独立的 Session，测试后清理"""
    s = _make_settings(db_name)
    engine = create_engine(s.database_url)

    # 确保表存在
    Base.metadata.create_all(bind=engine)

    session = Session(engine)
    yield session

    # 清理
    session.close()
    # 清空所有数据
    clean_session = Session(engine)
    try:
        clean_session.query(Product).delete()
        clean_session.commit()
    finally:
        clean_session.close()
    engine.dispose()
```

### 5.7 六个验证矩阵（详见 `demo-scope.md`）

| 矩阵 | 验证内容 | 执行顺序 |
|------|---------|---------|
| M1 | KingbaseES PostgreSQL 方言直连 | P5（提前） |
| M2 | DM8 方言验证 | P6（提前） |
| M3 | SQLAlchemy Inspector (Reflection) | P7 |
| M4 | Alembic upgrade / autogenerate | P8 |
| M5 | SQL Compilation 正确性 | P4 基准 → P9 三库 |
| M6 | Stored Procedure 兼容性 | P10 |

---

## 6. Phase 2 — 兼容层设计（基于 Phase 1 数据）

> ⚠️ 仅在 Phase 1 完成后启动。

### 6.1 目录结构（Phase 2 新增）

```
src/app/compat/          ← Phase 2 新增
├── __init__.py
├── types.py             # TypeDecorator (Boolean/DateTime/JSON/UUID)
├── dialects/
│   ├── __init__.py
│   ├── kingbasees.py    # KingbaseES Dialect Adapter (sys_* reflection)
│   └── dm8.py           # DM8 Dialect Adapter（如有需要）
└── locks.py             # 统一锁封装

src/app/repositories/
└── base.py              # 增强：paginate() / batch_insert() / acquire_row_lock()
```

### 6.2 兼容层设计方法论

```
Phase 1 known-differences.md
    │
    ▼
分类每个差异：
    │
    ├── 可用 TypeDecorator 屏蔽？
    │   → compat/types.py
    │
    ├── 可用 Dialect Adapter 屏蔽？
    │   → compat/dialects/
    │
    ├── 可用 Repository Adapter 屏蔽？
    │   → repositories/base.py（增强）
    │
    ├── 可用 Alembic Adapter 屏蔽？
    │   → migrations/_ddl_backend.py
    │
    └── 无法屏蔽？
        → migration-guide.md 记录为"需人工介入"
```

### 6.3 Phase 2 新增验证

- 多表模型（Order / OrderItem / Inventory）
- 跨表事务 + 乐观锁 + 悲观锁
- 兼容层屏蔽效果验证

### 6.4 Phase 2 产出

- `compatibility-layer-design.md`
- `phase2-report.md`

---

## 7. Phase 3 — 自动化迁移工具评估

> ⚠️ 仅在 Phase 2 完成后启动。

### 产出

- `auto-migration-feasibility.md`
- 自动化覆盖率 + 需人工介入比例
- Migration Assistant 原型设计（如果可行）

---

## 8. 关键架构决策

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | Phase 1 技术栈 | pytest + Repository + SQLAlchemy（无 Web 框架） | FastAPI 对 DB 兼容性验证零价值 |
| 2 | Phase 1 模型 | Product 单表，10 种字段类型 | 覆盖基础+扩展类型的差异发现 |
| 3 | Phase 1 类型策略 | 原生 SQLAlchemy 泛型，不做 any 适配 | 先知道真实差异，再设计方案 |
| 4 | DM8 测试顺序 | KBasees→DM8→Reflection→Alembic（先验证基本可用性） | 如果方言不可用，后续矩阵无意义 |
| 5 | known-differences 格式 | 只含问题/根因/影响/严重度，不含方案 | Phase 1 不设计解决方案 |
| 6 | 自动化评估时机 | Phase 3 | Phase 1 不知道哪些能被屏蔽 |
| 7 | KingbaseES 策略 | 先用 PG 方言直连 | 先验证可用性，再决定是否 fork |
