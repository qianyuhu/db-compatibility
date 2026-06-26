# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Mission

Research whether a Compatibility Layer can shield MSSQL/KingbaseES/DM8 differences so existing MSSQL projects can migrate to domestic databases with minimal changes. The project answers: **"Can unified abstraction, compatibility layers, or automated tools enable seamless or minimal-change migration?"**

## Three-Phase Strategy (see `docs/architecture-design.md` for full details)

```
Phase 1: 事实收集 (current)     Phase 2: 兼容层设计          Phase 3: 自动化评估
Facts only, no solutions        Design compat layer          Automation feasibility
pytest → Repository → SQLAlchemy  based on Phase 1 data       based on Phase 2 data
```

**Currently: Phase 0 complete. Phase 1 not yet started.**

## Phase 1 Critical Constraints

These are hard rules — violating any means restarting the phase:

- **No web framework** — No FastAPI, no `api/`, no `services/`, no `main.py`, no Pydantic schemas. Stack is `pytest → Repository → SQLAlchemy → DB`.
- **No compatibility layer** — No TypeDecorator, no `with_variant`, no Dialect Adapter, no `compat/` directory. Use bare SQLAlchemy generics.
- **No solutions in output** — `known-differences.md` must only contain problem/root cause/impact/severity. No "fixable by" or "automation difficulty" columns.
- **MSSQL-first** — All benchmarks pass on MSSQL before testing KingbaseES or DM8.
- **Single table first** — Product model only (10 field types). Multi-table models deferred to Phase 2.

## Product Model (10 field types for migration testing)

```python
class Product(Base):
    __tablename__ = "products"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(50), unique=True, nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    price       = Column(Numeric(10, 2), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, server_default=func.now(), nullable=False)
    description = Column(Text, nullable=True)          # NVARCHAR(MAX) / TEXT / CLOB
    extra_data  = Column(JSON, nullable=True)           # No native MSSQL type
    file_hash   = Column(String(36), nullable=True)     # UNIQUEIDENTIFIER / UUID / VARCHAR2(36)
    thumbnail   = Column(LargeBinary, nullable=True)    # VARBINARY(MAX) / BYTEA / BLOB
```

## Database Connection Strategy

- **MSSQL**: `mssql+pyodbc://` with ODBC Driver 18. RCSI must be enabled at database level.
- **KingbaseES**: `postgresql+psycopg2://` on port 54321 (PG wire-protocol compatible, but `pg_*` catalogs renamed to `sys_*`). Community `sqlalchemy-kingbase` dialect exists but is alpha quality.
- **DM8**: `dm+dmPython://` on port 5236. Official `dmPython` driver + `dmSQLAlchemy` dialect with active maintenance.

## Key Commands (to be used during Phase 1)

```bash
# Run all tests against a specific database
APP_ACTIVE_DB=mssql pytest tests/ -v
APP_ACTIVE_DB=kingbasees pytest tests/ -v
APP_ACTIVE_DB=dm8 pytest tests/ -v

# Run a single test
pytest tests/test_m5_sql_compilation.py -v -k "test_select"

# Database setup via Docker
docker compose -f docker/compose.yml up -d        # MSSQL
docker compose -f docker/compose.kingbasees.yml up -d
docker compose -f docker/compose.dm8.yml up -d

# Alembic
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "description"
```

## Project Structure (Phase 1 target — not yet created)

```
src/app/
  core/         config.py (APP_ACTIVE_DB switch), database.py (engine + session)
  models/       base.py, product.py
  repositories/ base.py (Repository[T]), product.py (ProductRepository)
  migrations/   env.py, versions/
tests/
  conftest.py                    parametrized db_name fixture
  test_m1_kingbasees_pg_dialect.py
  test_m2_dm8_dialect.py
  test_m3_reflection.py
  test_m4_alembic.py
  test_m5_sql_compilation.py
  test_m6_procedure.py
docker/         compose.yml, compose.kingbasees.yml, compose.dm8.yml
docs/           Phase 0 research outputs (complete)
```

## Verification Matrices (M1-M6)

| M# | File | What | Priority |
|----|------|------|----------|
| M1 | `test_m1_kingbasees_pg_dialect.py` | KingbaseES PG dialect direct connection | P5 |
| M2 | `test_m2_dm8_dialect.py` | DM8 dialect verification | P6 |
| M3 | `test_m3_reflection.py` | SQLAlchemy Inspector across 3 DBs | P7 |
| M4 | `test_m4_alembic.py` | Alembic upgrade/autogenerate | P8 |
| M5 | `test_m5_sql_compilation.py` | SQL compilation correctness (CRUD, pagination, batch, etc.) | P4→P9 |
| M6 | `test_m6_procedure.py` | Stored procedure compatibility | P10 |

DM8 testing (P6) runs before Reflection/Alembic (P7-P8) because if dmSQLAlchemy can't connect, later matrices are meaningless.

## Key Risks (from Phase 0 research)

- **CRITICAL**: KingbaseES has no official Python support. Community dialect is alpha. `pg_*` → `sys_*` catalog rename breaks SQLAlchemy reflection.
- **HIGH**: MSSQL lacks native JSON type. Three databases use three different stored-procedure PL dialects.
- **MEDIUM**: Boolean, DateTime, UUID types differ across all three databases.

## Phase Gates

- **Phase 1 → Phase 2**: All 6 matrices have data, `compatibility-matrix.md` and `known-differences.md` are complete (facts only). User explicitly approves transition.
- **Phase 2 → Phase 3**: Compatibility layer designed and verified against Phase 1 data.
- Each phase produces standalone reports. Do not start next phase until current phase deliverables are accepted.
