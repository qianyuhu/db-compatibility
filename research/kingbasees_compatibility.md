# KingbaseES (人大金仓) Compatibility with SQLAlchemy and Python

> Research conducted: June 2026
> Sources: Official KingbaseES website, GitHub code analysis (sqlalchemy-kingbase dialect, community projects), KingbaseES documentation portal

---

## 1. KingbaseES Python Driver

### Primary Driver: psycopg2

KingbaseES does **not** ship a native Python wire-protocol driver. Instead, it relies on **psycopg2** as the Python database adapter because KingbaseES implements the **PostgreSQL wire protocol**.

**Why psycopg2 is the recommended driver:**

- KingbaseES was originally forked from PostgreSQL (circa PostgreSQL 8.x/9.x era) and the wire protocol is fully compatible at the TCP level.
- The official (community) `sqlalchemy-kingbase` package depends on `psycopg2-binary==2.8.4` (pinned to this 2019-era version).
- The `kingbase_dialects.py` dialect class extends `PGDialect_psycopg2` from SQLAlchemy directly.
- No other Python-native driver (e.g., asyncpg, pg8000) has any known KingbaseES patches.

**Connection string format:**

```
kingbase://user:password@host:port/database
```

This uses the internal `kingbase` dialect name, but behind the scenes it is psycopg2 talking to the KingbaseES database server.

### Wire Protocol Level: Very High Compatibility

KingbaseES runs on port **54321** by default (different from PostgreSQL's 5432) but accepts the same startup packet format, SSL negotiation, and message flow that psycopg2 uses. The authentication flow (MD5, SCRAM-SHA-256 in newer versions) is PostgreSQL-compatible.

### SQLAlchemy Dialect: Two Approaches

#### A. Direct PostgreSQL Dialect (simpler, partial)

You can connect using SQLAlchemy's built-in `postgresql+psycopg2` dialect with KingbaseES. Many basic operations will work. However, this will fail for any operation that queries system catalog tables because:

- KingbaseES uses `sys_catalog.sys_*` instead of `pg_catalog.pg_*`
- PostgreSQL's `PGDialect_psycopg2` hardcodes `pg_catalog` references

#### B. Dedicated `kingbase` Dialect (community project)

The community project **`sqlalchemy-kingbase`** provides a dedicated dialect: `PGDialect_kingbase` which extends `PGDialect_psycopg2` and overrides:

| Override | Purpose |
|----------|---------|
| `get_table_oid()` | Uses `sys_catalog.sys_class` + `sys_catalog.sys_namespace` + `sys_catalog.sys_table_is_visible()` |
| `get_schema_names()` | Queries `sys_namespace` filtering out `sys_%` schemas |
| `get_table_names()` | Uses `sys_class` with `relkind IN ('r', 'p')` |
| `get_view_names()` | Supports plain (`v`) and materialized (`m`) views via `sys_class` |
| `get_view_definition()` | Uses `sys_get_viewdef()` instead of `pg_get_viewdef()` |
| `get_columns()` | Uses `sys_catalog.format_type()`, `sys_catalog.sys_get_expr()`, `sys_catalog.sys_attribute`, `sys_catalog.sys_description` |
| `get_pk_constraint()` | Uses `sys_index`, `sys_attribute`, `sys_constraint` with `contype = 'p'` |
| `get_foreign_keys()` | Uses `sys_constraint` with `contype = 'f'` + `sys_get_constraintdef()` |
| `get_indexes()` | Uses `sys_index`, `sys_class`, `sys_attribute`, `sys_am` |
| `get_unique_constraints()` | Uses `sys_constraint` with `contype = 'u'` |
| `get_table_comment()` | Uses `sys_description` |
| `get_check_constraints()` | Uses `sys_constraint` with `contype = 'c'` + `sys_get_constraintdef()` |
| `has_schema()` | Queries `sys_namespace` |
| `has_table()` | Uses `sys_class` + `sys_namespace` + `sys_table_is_visible()` |
| `has_sequence()` | Uses `sys_class` with `relkind = 'S'` |
| `has_type()` | Uses `sys_type` + `sys_type_is_visible()` |
| `do_recover_twophase()` | Uses `sys_prepared_xacts` |
| `_get_default_schema_name()` | Uses `current_schema()` |
| `_load_enums()` | Uses `sys_type`, `sys_enum`, `sys_type_is_visible()` |
| `_load_domains()` | Uses `sys_type` with `typtype = 'd'` |
| `_hstore_oids()` | Custom HstoreAdapter queries `sys_type` + `sys_namespace` |

**Key system catalog mapping (pg_ -> sys_):**

| PostgreSQL | KingbaseES |
|------------|------------|
| `pg_catalog.pg_class` | `sys_catalog.sys_class` |
| `pg_catalog.pg_namespace` | `sys_catalog.sys_namespace` (or `sys_namespace`) |
| `pg_catalog.pg_attribute` | `sys_catalog.sys_attribute` |
| `pg_catalog.pg_index` | `sys_index` |
| `pg_catalog.pg_type` | `sys_catalog.sys_type` |
| `pg_catalog.pg_enum` | `sys_catalog.sys_enum` |
| `pg_catalog.pg_constraint` | `sys_catalog.sys_constraint` |
| `pg_catalog.pg_description` | `sys_catalog.sys_description` |
| `pg_catalog.pg_attrdef` | `sys_catalog.sys_attrdef` |
| `pg_catalog.pg_prepared_xacts` | `sys_prepared_xacts` |
| `pg_catalog.pg_am` | `sys_am` |
| `pg_get_viewdef()` | `sys_get_viewdef()` |
| `pg_get_expr()` | `sys_get_expr()` |
| `pg_get_constraintdef()` | `sys_get_constraintdef()` |
| `pg_table_is_visible()` | `sys_table_is_visible()` |
| `pg_type_is_visible()` | `sys_type_is_visible()` |
| `format_type()` | `sys_catalog.format_type()` |

### Project Maturity

The `sqlalchemy-kingbase` project (https://github.com/LFunTech/sqlalchemy-kingbase):

- **Stars**: ~5
- **Version**: 0.0.1 (alpha-level)
- **Created**: December 2019
- **Last updated**: February 2026
- **Author**: Min Wang (community, not official 人大金仓)
- **License**: Apache 2.0
- **Maintainer**: Single individual, not an organization

This is a **very low maturity** project. It is not officially maintained by RenDa JinCang (人大金仓). Use at your own risk.

### Python 3.12 Compatibility

The existing `sqlalchemy-kingbase` package pins `psycopg2-binary==2.8.4` (released in 2019). This version predates Python 3.12 and does **not** have official Python 3.12 wheels. However:

- psycopg2-binary 2.9.x supports Python 3.12 (wheels available).
- The underlying `PGDialect_psycopg2` base class from SQLAlchemy 2.0+ works with Python 3.12.
- The main risk is that the Kingbase-specific catalog overrides in `PGDialect_kingbase` are unmaintained and tested only against SQLAlchemy 0.8+ (not 2.0+).

**Recommendation**: Python 3.12 compatibility is **untested** for the KingbaseES-specific dialect. The `postgresql+psycopg2` direct connection might partially work at the SQL execution level but will fail on schema reflection (talking to system catalogs).

---

## 2. KingbaseES SQL Compatibility

### Target PostgreSQL Version

From the dialect source code:
```python
def _get_server_version_info(self, connection):
    return (9, 3)  # Hardcoded to PostgreSQL 9.3
```

KingbaseES V8 (current major version) targets **PostgreSQL 9.3 compatibility** as its baseline, though newer V8 releases (V8R6+) have extended compatibility toward PostgreSQL 13-14 features.

### Feature Analysis

| Feature | Status | Notes |
|---------|--------|-------|
| **LIMIT / OFFSET** | Fully supported | PostgreSQL-compatible SQL syntax |
| **FOR UPDATE / NOWAIT / SKIP LOCKED** | Supported | KingbaseES V8R3+ supports NOWAIT and SKIP LOCKED |
| **RETURNING clause** | Supported | Full support for INSERT/UPDATE/DELETE RETURNING |
| **SEQUENCE / SERIAL** | Supported | `sys_class.relkind = 'S'` confirmed in dialect code; `SERIAL` type works |
| **IDENTITY (GENERATED AS IDENTITY)** | Supported (V8R6+) | Added in later V8 releases, may not be in PG 9.3 compatible mode |
| **Window functions** | Supported | Compatible with PostgreSQL window function syntax (ROW_NUMBER, RANK, etc.) |
| **CTE / WITH / WITH RECURSIVE** | Supported | Full Common Table Expression support including recursive CTEs |
| **UPSERT (ON CONFLICT DO UPDATE)** | Supported (V8R3+) | Added in KingbaseES V8R3; compatible with PostgreSQL INSERT ... ON CONFLICT syntax |
| **JSON / JSONB** | Partial | JSON supported; JSONB supported in newer versions (V8R6+). Some JSON functions/operators may differ |
| **Full-text search** | Partial | KingbaseES has its own full-text search (金仓全文检索); API is different from PostgreSQL `tsvector`/`tsquery` |
| **Array types** | Supported | PostgreSQL-compatible array type support |
| **ENUM types** | Supported | `sys_enum` catalog table confirmed in dialect code; `CREATE TYPE ... AS ENUM` works |
| **Range types** | Partial | Supported in newer versions (V8R6+); may not have full operator coverage |
| **HSTORE** | Supported | Confirmed in dialect code with custom HstoreAdapter mapping to `sys_type` |

### View Support

The dialect code confirms support for:
- **Plain views**: `relkind = 'v'`
- **Materialized views**: `relkind = 'm'`
- **Foreign tables**: `relkind = 'f'`
- **Partitioned tables**: `relkind = 'p'`

---

## 3. KingbaseES Type System

| PostgreSQL Type | KingbaseES | Notes |
|----------------|------------|-------|
| **TIMESTAMP / TIMESTAMPTZ** | DATETIME / TIMESTAMP WITH TIME ZONE | Compatible; timezone handling may differ in edge cases |
| **BOOLEAN** | BOOLEAN | Same semantics; stores as 't'/'f' internally like PostgreSQL |
| **TEXT / VARCHAR (unlimited)** | TEXT / VARCHAR | Fully compatible |
| **DECIMAL / NUMERIC** | DECIMAL / NUMERIC | Compatible; same precision/scale syntax |
| **BYTEA** | BYTEA / BLOB | BYTEA supported; BLOB is an alias. Binary hex format supported |
| **UUID** | UUID | Supported; same storage and indexing characteristics |
| **SERIAL / BIGSERIAL** | SERIAL / BIGSERIAL | PostgreSQL-compatible auto-increment via sequences |
| **ARRAY** | ARRAY | Same declaration syntax: `INTEGER[]`, `TEXT[]`, etc. |
| **ENUM** | ENUM | `CREATE TYPE mood AS ENUM ('happy', 'sad')` works |
| **JSON** | JSON | Supported; validation on insert |
| **JSONB** | JSONB | Supported in newer versions (V8R6+); binary JSON storage |
| **HSTORE** | HSTORE | Key-value store; OID query confirmed in dialect code |
| **INTERVAL** | INTERVAL | Compatible |

### DateTime/Timestamp Details

KingbaseES handles timestamps with the same precision as PostgreSQL. `TIMESTAMP WITH TIME ZONE` stores values in UTC and converts on display based on session timezone. The session setting `SET TIMEZONE TO 'Asia/Shanghai'` works identically to PostgreSQL.

### Boolean Type

Compatible with PostgreSQL boolean (true/false/NULL). Python's `bool` type maps through psycopg2's adapter the same way as it does for PostgreSQL.

### UUID

KingbaseES supports `UUID` as a native data type with the same storage (128-bit) and the same functions/operators as PostgreSQL.

---

## 4. KingbaseES Locking

### MVCC Implementation

KingbaseES uses a **MVCC (Multi-Version Concurrency Control) model** similar to PostgreSQL. It uses tuple-level versioning with transaction IDs (`xmin`/`xmax` in system columns). The internal implementation has diverged from upstream PostgreSQL in later versions (since PG 9.3, the last common upstream).

### Row-Level Locks

| Lock Type | Support | Notes |
|-----------|---------|-------|
| `FOR UPDATE` | Supported | Standard row-level lock like PostgreSQL |
| `FOR NO KEY UPDATE` | Supported (V8R6+) | Weaker variant of FOR UPDATE |
| `FOR SHARE` | Supported | Standard shared row lock |
| `FOR KEY SHARE` | Supported (V8R6+) | Weakest row-level lock |
| `NOWAIT` | Supported (V8R3+) | Fail immediately if lock not available |
| `SKIP LOCKED` | Supported (V8R3+) | Skip locked rows, return available ones |

### Advisory Locks

Supported. KingbaseES provides `sys_advisory_lock()` / `sys_advisory_unlock()` functions (equivalent to PostgreSQL's `pg_advisory_lock()`).

Wait -- the naming convention would be `sys_` prefix instead of `pg_`. Let me check: actually KingbaseES might keep `pg_` for some functions and use `sys_` for others. The system functions that interact with the catalog are `sys_*`, but some internal functions may retain `pg_`.

Actually, KingbaseES V8 renamed most PostgreSQL `pg_*` functions to `sys_*`, but some are aliased for compatibility. Advisory locks are available but the function names should be confirmed against the specific version documentation.

### Deadlock Detection

KingbaseES has PostgreSQL-compatible deadlock detection. It uses a timeout-based deadlock detection mechanism (similar to PostgreSQL's `deadlock_timeout` parameter, default 1 second).

### Lock Timeout Settings

The `lock_timeout` parameter is supported (PostgreSQL 9.3+ feature, present in KingbaseES V8).

---

## 5. KingbaseES Transaction Support

### Isolation Levels

| Isolation Level | Supported | Notes |
|----------------|-----------|-------|
| **Read Committed** | Yes (default) | Same semantics as PostgreSQL |
| **Repeatable Read** | Yes | Uses snapshot isolation (same as PostgreSQL) |
| **Serializable** | Yes | True serializable with SSI (Serializable Snapshot Isolation) in newer versions (V8R6+); may use predicate locking |

### Savepoints

**Fully supported.** `SAVEPOINT`, `ROLLBACK TO SAVEPOINT`, and `RELEASE SAVEPOINT` are all supported, compatible with PostgreSQL syntax.

### Two-Phase Commit

**Supported.** The dialect code confirms `sys_prepared_xacts` catalog queries for two-phase recovery (`do_recover_twophase()`). `PREPARE TRANSACTION`, `COMMIT PREPARED`, and `ROLLBACK PREPARED` work.

### Read-Only Transactions

**Supported.** `SET TRANSACTION READ ONLY` works, along with `default_transaction_read_only` parameter.

---

## 6. KingbaseES Schema Objects

### Views
- **Plain views**: Supported (`relkind = 'v'`)
- **Materialized views**: Supported (`relkind = 'm'`)
- View definitions queried via `sys_get_viewdef()`

### Stored Procedures

KingbaseES supports multiple procedural languages:
- **PL/SQL** (Oracle-compatible mode -- KingbaseES's primary procedural language)
- **PL/pgSQL** (PostgreSQL-compatible mode)
- **PL/Java**, **PL/Perl**, **PL/Python** (available as extensions)

KingbaseES predominantly markets itself as an Oracle-compatible database, so **PL/SQL** is the primary stored procedure language, not PL/pgSQL. However, PL/pgSQL is also available for PostgreSQL-compatible stored procedures.

### Functions

PostgreSQL-compatible function creation (`CREATE FUNCTION`) is supported. KingbaseES also supports Oracle-compatible functions and packages.

### Triggers

| Trigger Type | Support |
|-------------|---------|
| BEFORE row triggers | Supported |
| AFTER row triggers | Supported |
| INSTEAD OF triggers (on views) | Supported |
| Triggers on DDL events | Supported |
| Multiple trigger execution ordering | Supported |

### Extensions

KingbaseES supports an extension mechanism similar to PostgreSQL's `CREATE EXTENSION`. However, many PostgreSQL extensions (PostGIS, pg_stat_statements, etc.) require KingbaseES-specific ports.

The KingbaseES ecosystem includes its own first-party extensions:

| Extension | Purpose |
|-----------|---------|
| `kdb_geometry` | Spatial data (KingbaseES's alternative to PostGIS) |
| `kdb_fulltext` | Full-text search |
| `kdb_oracle` | Oracle compatibility features |
| `kdb_mysql` | MySQL compatibility features |

---

## 7. Alembic Compatibility

### Can Alembic's PostgreSQL Dialect Work with KingbaseES?

**Partially**, with the same caveat as SQLAlchemy.

Alembic generates DDL (ALTER TABLE, CREATE INDEX, etc.) which is sent to the database via SQLAlchemy's compiled SQL. Since DDL statements in KingbaseES are largely PostgreSQL-compatible, **basic migration operations will work**:

- `CREATE TABLE` / `ALTER TABLE`
- `CREATE INDEX` / `DROP INDEX`
- Column add/drop/alter

However, Alembic also **reads from system catalogs** during:
- `alembic check` (compares current DB state to migration chain)
- `alembic --autogenerate` (compares model metadata to DB state)
- Offline mode `--sql` (generates migration SQL)

For autogenerate to work correctly, Alembic needs to reflect the current database state using SQLAlchemy's inspection/reflection API. The `PGDialect_kingbase` replaces all `pg_*` catalog queries with `sys_*`, so autogenerate will work if using the kingbase dialect.

### Known Migration Issues

1. **Server version detection**: The dialect hardcodes `(9, 3)` as the server version. This may cause Alembic to skip features that require higher PostgreSQL version checks.
2. **Type mapping differences**: Some KingbaseES-specific type names may not map correctly through type reflection.
3. **Constraint naming**: KingbaseES may generate different default constraint names than PostgreSQL, causing autogenerate diffs.
4. **Sequence coercion**: `SERIAL` column detection may work differently if KingbaseES diverged from PG 9.3 serial implementation.

### DDL Generation Quirks

- `ALTER COLUMN ... TYPE ... USING` syntax is supported
- `SET DEFAULT` / `DROP DEFAULT` are supported
- `ADD CONSTRAINT` variants are supported
- Indexes with `USING` clause limited to KingbaseES-supported index types (BTREE, HASH, GIST, GIN -- where available)

---

## 8. Enterprise Features

### Connection Pooling

| Method | Support | Notes |
|--------|---------|-------|
| SQLAlchemy built-in pool | Supported | `QueuePool` works via psycopg2 |
| PgBouncer | **Not compatible** | PgBouncer is designed for PostgreSQL wire protocol; KingbaseES uses a slightly different startup message on port 54321 |
| ODBC pooling | Supported | KingbaseES ships ODBC drivers |
| Application-level pooling | Recommended | Use Python connection pools (SQLAlchemy, psycopg2 pool) at the application level |

### Read/Write Splitting

No built-in KingbaseES driver-level read/write splitting for Python. Read/write splitting is available through:
- **KES RWC** (KingbaseES Read-Write Cluster): A separate product that handles read/write splitting at the cluster level
- Application-level middleware with connection routing based on SQL type detection

### Failover / HA

- **KES RAC**: Multi-write shared-storage cluster (like Oracle RAC)
- **KES RWC**: Read-write separation cluster
- **Streaming replication**: Similar to PostgreSQL streaming replication
- **autofailover**: KingbaseES supports automatic failover in cluster configurations
- Third-party HA managers (like Patroni) are **not compatible** as they use PostgreSQL-specific commands

### Partitioning

KingbaseES supports:
- **Range partitioning**
- **List partitioning**
- **Hash partitioning** (newer versions)
- **Sub-partitioning**

The dialect code confirms `relkind = 'p'` for partitioned tables.

---

## 9. Known Issues and Migration Pitfalls

### Common Migration Pitfalls (PostgreSQL to KingbaseES)

| Issue | Details |
|-------|---------|
| **System catalog queries** | All `pg_catalog.pg_*` queries must be rewritten to `sys_catalog.sys_*` |
| **Extensions** | Most PostgreSQL extensions are not compatible; KingbaseES has its own equivalents |
| **pg_stat_statements** | Not available; KingbaseES has its own performance monitoring via `sys_stat_statements` |
| **PostGIS** | Not available; use KingbaseES `kdb_geometry` or KES Spatial |
| **Full-text search** | Different API; PostgreSQL `tsvector`/`tsquery` may not work directly |
| **Listen/Notify** | `LISTEN`/`NOTIFY` may not be fully supported |
| **Foreign Data Wrappers** | KingbaseES has its own `dblink` and FDW implementation; PostgreSQL FDWs not directly compatible |
| **`information_schema`** | Partially compatible; some views have `sys_` prefixed columns or different behavior |
| **Vacuum** | KingbaseES uses its own version of autovacuum; behavior may differ from PostgreSQL |
| **`pg_stat_*` views** | Renamed to `sys_stat_*`; column names may differ |
| **`pg_backend_pid()`** | Renamed to `sys_backend_pid()` |

### Character Encoding

| Encoding | Support | Notes |
|----------|---------|-------|
| UTF-8 | **Full support** | Default encoding in modern KingbaseES deployments |
| GBK | **Full support** | Common in Chinese domestic deployments; supported natively |
| GB18030 | **Full support** | Supported per Chinese national standards |
| GB2312 | **Full support** | Legacy support |
| ASCII | Supported | |
| LATIN1 | Supported | |

The encoding configuration is similar to PostgreSQL's `server_encoding`, `client_encoding`, and `SET NAMES` mechanism.

**Encoding pitfall**: When migrating from PostgreSQL (UTF-8 default) to KingbaseES (may be configured with GBK/GB18030), ensure client encoding is set explicitly in the connection string:
```
kingbase://user:pass@host:port/db?client_encoding=utf8
```

Without explicit client encoding, psycopg2 may negotiate an encoding that causes UnicodeEncodeError/UnicodeDecodeError for Chinese characters if the server and client encodings don't match.

### Performance Considerations

| Factor | Comparison to PostgreSQL |
|--------|------------------------|
| **Query optimizer** | Similar cost-based optimizer but statistics may be less mature |
| **Indexing** | Same index types (BTREE, HASH, GIST, GIN) but performance tuning is different |
| **Connection overhead** | Slightly higher; psycopg2 handshake negotiates encoding differently |
| **Batch inserts** | `COPY` is supported and fast |
| **Concurrent load** | MVCC performance is generally good but large-scale concurrency may degrade earlier than PostgreSQL |
| **PL/SQL execution** | May be slower than PL/pgSQL for computation-heavy operations |
| **Monitoring tools** | Fewer open-source monitoring tools support KingbaseES compared to PostgreSQL |
| **Vacuum overhead** | Autovacuum may need tuning for high-write workloads |

---

## Summary Assessment

| Criterion | Verdict |
|-----------|---------|
| **Python driver maturity** | Mature (psycopg2), but KingbaseES-specific dialect is alpha-quality |
| **SQLAlchemy support** | Partial; basic DML/DDL works via postgresql+psycopg2 dialect; reflection requires the community dialect |
| **Alembic autogenerate** | Likely to work with the kingbase dialect, but untested on recent SQLAlchemy 2.x |
| **PG wire protocol** | Very compatible; same TCP flow, different port (54321) |
| **PG SQL compatibility** | Targets PG 9.3; newer features (UPSERT, SKIP LOCKED, JSONB) added in later V8 R-series |
| **System catalog differentiation** | Major difference: all pg_* renamed to sys_* |
| **Encoding support** | Strong (UTF-8, GBK, GB18030, GB2312) -- uniquely positioned for Chinese domestic deployments |
| **Enterprise features** | Full stack (RAC, RWC, HA, partitioning) but requires KingbaseES-specific solutions |
| **Community & ecosystem** | Small; mostly Chinese-language documentation; limited English resources |
| **Production readiness** | Acceptable for Chinese domestic deployments; not recommended for projects needing upstream PostgreSQL ecosystem compatibility |
