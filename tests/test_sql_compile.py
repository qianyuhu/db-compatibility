"""
Phase 1 · SQL Compilation 对比。

无需连接数据库 — 使用 SQLAlchemy 编译层生成三库的 SQL 文本。
输出保存到 docs/sql-compilation-report.md。

目的: 对比同一段 ORM 代码在不同 dialect 下生成的原始 SQL。
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects import mssql as mssql_dialect
from sqlalchemy.dialects import postgresql as pg_dialect


def _build_test_table():
    """构建一个与 Product 结构一致的 Table 用于编译测试。"""
    metadata = MetaData()
    return Table(
        "products",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("code", String(50), nullable=False),
        Column("name", String(200), nullable=False),
        Column("price", Numeric(10, 2), nullable=False),
        Column("is_active", Boolean),  # BIT (MSSQL) / BOOLEAN (PG) / SMALLINT (DM8)
        Column("created_at", DateTime),
    )


# ============================================================
# Dialect 配置
# ============================================================

DIALECTS = {
    "mssql": mssql_dialect.dialect(),
    "kingbasees": pg_dialect.dialect(),  # PG 协议兼容
    # "dm8": dm_dialect.dialect(),  # 需要 dmSQLAlchemy 安装后启用
}

# 如果 dmSQLAlchemy 可用则添加
try:
    from sqlalchemy_dm import dm_dialect
    DIALECTS["dm8"] = dm_dialect.dialect()
except ImportError:
    pass  # DM8 方言未安装，编译测试跳过 DM8


# ============================================================
# 编译辅助
# ============================================================

def _compile(stmt, dialect_name: str) -> str:
    """将 SQLAlchemy 语句编译为目标数据库的 SQL 文本。"""
    dialect = DIALECTS.get(dialect_name)
    if dialect is None:
        return f"-- {dialect_name}: dialect not available"
    try:
        compiled = stmt.compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
        return str(compiled).strip()
    except Exception as e:
        return f"-- {dialect_name}: COMPILE ERROR: {type(e).__name__}: {e}"


def _compile_all(stmt, label: str) -> dict[str, str]:
    """对全部可用 dialect 编译同一条语句。"""
    return {db: _compile(stmt, db) for db in DIALECTS}


# ============================================================
# 编译测试
# ============================================================

class TestSQLCompile:
    """SQL 编译对比 — 验证同一段 ORM 代码在三库生成的原始 SQL。"""

    def test_select_by_id(self):
        """SELECT ... WHERE id = ?"""
        table = _build_test_table()
        stmt = select(table).where(table.c.id == 1)
        results = _compile_all(stmt, "SELECT by id")
        _print_results("SELECT WHERE id=1", results)

    def test_select_with_order_limit(self):
        """SELECT ... ORDER BY ... OFFSET ... LIMIT ..."""
        table = _build_test_table()
        stmt = (
            select(table)
            .order_by(table.c.id)
            .offset(10)
            .limit(20)
        )
        results = _compile_all(stmt, "SELECT with OFFSET/LIMIT")
        _print_results("SELECT ORDER BY id OFFSET 10 LIMIT 20", results)

    def test_select_count(self):
        """SELECT COUNT(*) FROM ..."""
        table = _build_test_table()
        stmt = select(func.count()).select_from(table)
        results = _compile_all(stmt, "SELECT COUNT")
        _print_results("SELECT COUNT(*)", results)

    def test_insert(self):
        """INSERT INTO ... VALUES ..."""
        table = _build_test_table()
        stmt = insert(table).values(
            code="P001",
            name="Test",
            price=99.99,
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        results = _compile_all(stmt, "INSERT")
        _print_results("INSERT single row", results)

    def test_insert_bulk(self):
        """INSERT 批量 — .values([{...}, {...}])"""
        table = _build_test_table()
        stmt = insert(table).values([
            {"code": "B001", "name": "Batch 1", "price": 10, "is_active": True},
            {"code": "B002", "name": "Batch 2", "price": 20, "is_active": False},
        ])
        results = _compile_all(stmt, "INSERT bulk")
        _print_results("INSERT bulk (2 rows)", results)

    def test_update(self):
        """UPDATE ... SET ... WHERE ..."""
        table = _build_test_table()
        stmt = (
            update(table)
            .where(table.c.id == 1)
            .values(name="Updated", price=199.99)
        )
        results = _compile_all(stmt, "UPDATE")
        _print_results("UPDATE SET name,price WHERE id=1", results)

    def test_delete(self):
        """DELETE FROM ... WHERE ..."""
        table = _build_test_table()
        stmt = delete(table).where(table.c.id == 1)
        results = _compile_all(stmt, "DELETE")
        _print_results("DELETE WHERE id=1", results)

    def test_select_like(self):
        """SELECT ... WHERE name LIKE '%keyword%'"""
        table = _build_test_table()
        stmt = select(table).where(table.c.name.like("%搜索%"))
        results = _compile_all(stmt, "SELECT LIKE")
        _print_results("SELECT WHERE name LIKE '%搜索%'", results)


# ============================================================
# 报告生成
# ============================================================

def _print_results(label: str, results: dict[str, str]):
    """打印编译结果到 stdout（pytest -s 可见）。"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for db, sql in results.items():
        print(f"\n--- {db} ---")
        print(sql)


def test_generate_compile_report():
    """汇总所有编译结果，输出 Markdown 到 docs/sql-compilation-report.md。

    这个测试始终通过（不验证正确性），只输出差异供分析。
    """
    table = _build_test_table()

    cases: list[tuple[str, any]] = [
        ("SELECT WHERE id=:id", select(table).where(table.c.id == 1)),
        (
            "SELECT ORDER BY id OFFSET 10 LIMIT 20",
            select(table).order_by(table.c.id).offset(10).limit(20),
        ),
        ("SELECT COUNT(*)", select(func.count()).select_from(table)),
        (
            "INSERT single row",
            insert(table).values(
                code="P001",
                name="测试",
                price=99.99,
                is_active=1,
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        ),
        (
            "INSERT bulk (2 rows)",
            insert(table).values([
                {"code": "B001", "name": "Batch 1", "price": 10, "is_active": True},
                {"code": "B002", "name": "Batch 2", "price": 20, "is_active": False},
            ]),
        ),
        (
            "UPDATE SET name,price WHERE id=:id",
            update(table).where(table.c.id == 1).values(name="New", price=200),
        ),
        ("DELETE WHERE id=:id", delete(table).where(table.c.id == 1)),
        (
            "SELECT WHERE name LIKE '%搜索%'",
            select(table).where(table.c.name.like("%搜索%")),
        ),
    ]

    lines: list[str] = []
    lines.append("# SQL Compilation Report")
    lines.append("")
    lines.append("> Phase 1 · 自动生成 · 三库 SQL 编译对比")
    lines.append(f"> 可用 dialect: {', '.join(DIALECTS.keys())}")
    lines.append("")
    lines.append("同一段 SQLAlchemy ORM 代码，在不同 dialect 下生成的原始 SQL 文本。")
    lines.append("差异即迁移风险点。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for label, stmt in cases:
        lines.append(f"## {label}")
        lines.append("")
        results = _compile_all(stmt, label)
        for db_name in DIALECTS:
            sql = results.get(db_name, "-- unavailable")
            lines.append(f"### {db_name}")
            lines.append("")
            lines.append("```sql")
            lines.append(sql)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    report_path = os.path.join(
        os.path.dirname(__file__), "..", "docs", "sql-compilation-report.md"
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ SQL compilation report written to: {report_path}")
