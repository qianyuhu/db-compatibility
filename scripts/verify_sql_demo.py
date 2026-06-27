"""
SQL Demo 连线验证脚本 — 在真实 MSSQL 上执行所有 SQL 文件并验证行数。
"""
import re
import sys
sys.path.insert(0, "src")

from app.core.config import settings
from sqlalchemy import create_engine, text


def exec_sql_file(conn, filepath: str) -> int:
    """Execute a .sql file against MSSQL.

    Strategy:
    - Split by ^GO$ into batches (procedure/function/view/trigger files)
    - Each GO batch is executed as a whole via exec_driver_sql (handles
      multi-statement batches with semicolons inside CREATE bodies).
    - Files without GO (schema, data, crud, query, transaction, index):
      split by semicolons for individual statement execution.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    executed = 0
    go_batches = re.split(r"^GO\s*$", content, flags=re.MULTILINE | re.IGNORECASE)

    has_go = len(go_batches) > 1

    for go_batch in go_batches:
        batch = go_batch.strip()
        if not batch:
            continue

        if has_go:
            # Execute whole GO batch as one unit (preserves CREATE bodies)
            # Remove trailing semicolons that might confuse the driver
            batch = batch.rstrip(";")
            # Skip pure comment batches
            lines = [l for l in batch.split("\n") if l.strip() and not l.strip().startswith("--")]
            if not lines:
                continue
            try:
                conn.exec_driver_sql(batch)
                executed += 1
            except Exception as e:
                preview = "\n".join(lines[:5])[:300]
                print(f"  ERROR in {filepath} (GO batch):\n  {preview}")
                print(f"  -> {type(e).__name__}: {e}")
                raise
        else:
            # No GO — split by semicolons for simple DDL/DML
            stmts = batch.split(";")
            for stmt in stmts:
                stmt = stmt.strip()
                if not stmt:
                    continue
                lines = [l for l in stmt.split("\n") if l.strip() and not l.strip().startswith("--")]
                if not lines:
                    continue
                try:
                    conn.execute(text(stmt))
                    executed += 1
                except Exception as e:
                    preview = "\n".join(lines[:5])[:200]
                    print(f"  ERROR in {filepath}:\n  {preview}")
                    print(f"  -> {type(e).__name__}: {e}")
                    raise
    return executed


def main():
    engine = create_engine(settings.database_url, echo=False)
    sql_dir = "demo/sqlserver"

    # ── 0. Cleanup ──────────────────────────────────────────────
    print("=" * 60)
    print("0. Dropping existing objects...")
    with engine.connect() as conn:
        drops = [
            "DROP TABLE IF EXISTS dbo.InventoryLog",
            "DROP TABLE IF EXISTS dbo.OrderItem",
            "DROP TABLE IF EXISTS dbo.[Order]",
            "DROP TABLE IF EXISTS dbo.Product",
            "DROP TABLE IF EXISTS dbo.Customer",
            "DROP SEQUENCE IF EXISTS dbo.OrderSeq",
        ]
        for d in drops:
            try:
                conn.execute(text(d))
            except Exception as e:
                print(f"  Drop warning: {e}")
        # Also drop dependent objects that might exist
        try:
            conn.execute(text("DROP TYPE IF EXISTS dbo.OrderItemType"))
        except Exception:
            pass
        conn.commit()
    print("  Cleanup complete")

    # ── 1. schema.sql ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("1. Executing schema.sql...")
    with engine.connect() as conn:
        n = exec_sql_file(conn, f"{sql_dir}/schema.sql")
        conn.commit()
        print(f"  ✓ {n} statements executed")

    # Verify tables
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sys.tables WHERE type='U' ORDER BY name")
        ).fetchall()
        table_names = [t[0] for t in tables]
        print(f"  Tables created ({len(table_names)}): {table_names}")

        # Verify column counts
        for tname in table_names:
            cols = conn.execute(
                text(f"SELECT COUNT(*) FROM sys.columns WHERE object_id = OBJECT_ID('dbo.{tname}')")
            ).scalar()
            print(f"    {tname}: {cols} columns")

    # ── 2. data.sql ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("2. Executing data.sql...")
    with engine.connect() as conn:
        n = exec_sql_file(conn, f"{sql_dir}/data.sql")
        conn.commit()
        print(f"  ✓ {n} statements executed")

    # Verify row counts
    with engine.connect() as conn:
        expected = {
            "Customer": 25, "Product": 55, "[Order]": 110, "OrderItem": 310
        }
        all_ok = True
        for table, expected_count in expected.items():
            actual = conn.execute(text(f"SELECT COUNT(*) FROM dbo.{table}")).scalar()
            status = "✓" if actual == expected_count else "✗"
            if actual != expected_count:
                all_ok = False
            print(f"  {status} {table}: {actual} (expected {expected_count})")
        if all_ok:
            print("  ✅ All row counts match!")

    # ── 3-5. Views, Functions, Indexes ─────────────────────────
    print("\n" + "=" * 60)
    print("3. Executing function.sql...")
    with engine.connect() as conn:
        n = exec_sql_file(conn, f"{sql_dir}/function.sql")
        conn.commit()
        print(f"  ✓ {n} statements")

    print("\n4. Executing view.sql...")
    with engine.connect() as conn:
        n = exec_sql_file(conn, f"{sql_dir}/view.sql")
        conn.commit()
        print(f"  ✓ {n} statements")

    print("\n5. Executing index.sql...")
    with engine.connect() as conn:
        n = exec_sql_file(conn, f"{sql_dir}/index.sql")
        conn.commit()
        print(f"  ✓ {n} statements")

    # ── Verify views and functions ─────────────────────────────
    print("\n" + "=" * 60)
    print("Object verification:")
    with engine.connect() as conn:
        views = conn.execute(
            text("SELECT name FROM sys.views ORDER BY name")
        ).fetchall()
        procs = conn.execute(
            text("SELECT name FROM sys.procedures ORDER BY name")
        ).fetchall()
        funcs = conn.execute(
            text("SELECT name FROM sys.objects WHERE type IN ('FN','IF','TF') ORDER BY name")
        ).fetchall()
        print(f"  Views: {[v[0] for v in views]}")
        print(f"  Procedures: {[p[0] for p in procs]}")
        print(f"  Functions: {[f[0] for f in funcs]}")

    print("\n" + "=" * 60)
    print("✅ SQL Demo verification complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
