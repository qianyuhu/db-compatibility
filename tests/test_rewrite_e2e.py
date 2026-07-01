"""
End-to-End Rewrite Rules Validation — runs SQL on real databases.

Pipeline:
    1. Execute original MSSQL SQL on MSSQL → get source result
    2. Rewrite via engine → get target SQL
    3. Execute rewritten SQL on KingbaseES / DM8 → get target result
    4. Compare results (columns, row count, data)

Prerequisites:
    - All three databases (MSSQL, KingbaseES, DM8) must be reachable
    - Demo schema + seed data must be loaded

Run:
    python -m pytest tests/test_rewrite_e2e.py -v --tb=short
"""

import sys
import os
import re
import pytest
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from architecture.core.config import settings
from architecture.core.sql.rewrite.engine import rewrite_sql, RewriteResult


# ===========================================================================
# Direct database connections (bypass DBGateway single-db limitation)
# ===========================================================================


def _connect_mssql():
    """Direct pyodbc connection to MSSQL."""
    import pyodbc
    kwargs = settings.raw_connection_kwargs
    return pyodbc.connect(kwargs["connection_string"])


def _connect_kingbasees():
    """Direct psycopg2 connection to KingbaseES."""
    import psycopg2
    return psycopg2.connect(
        host=settings.kingbasees_host,
        port=settings.kingbasees_port,
        dbname=settings.kingbasees_database,
        user=settings.kingbasees_user,
        password=settings.kingbasees_password,
    )


def _connect_dm8():
    """Direct dmPython connection to DM8."""
    import dmPython
    return dmPython.connect(
        server=settings.dm8_host,
        port=settings.dm8_port,
        user=settings.dm8_user,
        password=settings.dm8_password,
    )


def _execute_query(db_type: str, sql: str) -> dict[str, Any]:
    """Execute a SELECT query on the specified database.

    Returns dict with: success, columns, rows, row_count, error, sql_executed
    """
    conn = None
    cursor = None
    try:
        if db_type == "mssql":
            conn = _connect_mssql()
        elif db_type == "kingbasees":
            conn = _connect_kingbasees()
            conn.autocommit = True
        elif db_type == "dm8":
            conn = _connect_dm8()
        else:
            return {"success": False, "error": f"Unknown db_type: {db_type}",
                    "columns": [], "rows": [], "row_count": 0, "sql_executed": sql}

        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [list(row) for row in cursor.fetchall()]
        return {
            "success": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "error": None,
            "sql_executed": sql,
        }
    except Exception as exc:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "sql_executed": sql,
        }
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass


# ===========================================================================
# Test cases — each entry is an MSSQL SQL that exercises specific rules
# ===========================================================================


@dataclass
class E2ECase:
    """End-to-end test case definition."""
    id: str
    category: str
    mssql_sql: str
    expected_rules: list[str] = field(default_factory=list)
    skip_dm8: bool = False
    skip_data_compare: bool = False  # True for volatile results (GETDATE/NOW)
    note: str = ""


E2E_CASES: list[E2ECase] = [
    # --- Baseline: simple function rewrites ---
    E2ECase(
        id="E01",
        category="TOP → LIMIT",
        mssql_sql="SELECT TOP 5 full_name, credit_limit FROM Customer ORDER BY credit_limit DESC",
        expected_rules=["TOP → LIMIT"],
    ),
    E2ECase(
        id="E02",
        category="GETDATE → NOW",
        mssql_sql="SELECT full_name, GETDATE() AS query_time FROM Customer WHERE customer_id <= 3",
        expected_rules=["GETDATE → NOW"],
        skip_data_compare=True,
    ),
    E2ECase(
        id="E03",
        category="ISNULL → COALESCE",
        mssql_sql="SELECT full_name, ISNULL(phone, N'无电话') AS phone FROM Customer WHERE customer_id <= 5",
        expected_rules=["ISNULL → COALESCE"],
    ),
    E2ECase(
        id="E04",
        category="LEN → LENGTH",
        mssql_sql="SELECT full_name, LEN(full_name) AS name_len FROM Customer WHERE customer_id <= 5",
        expected_rules=["LEN → LENGTH"],
    ),
    E2ECase(
        id="E05",
        category="NEWID → gen_random_uuid",
        mssql_sql="SELECT full_name, NEWID() AS random_id FROM Customer WHERE customer_id <= 3",
        expected_rules=["NEWID → gen_random_uuid"],
        skip_data_compare=True,  # Random UUIDs always differ
    ),
    E2ECase(
        id="E06",
        category="Bracket → Quote identifiers",
        mssql_sql='SELECT order_id, order_no FROM [Order] WHERE order_id <= 5',
        expected_rules=['[标识符] → "标识符"'],
    ),
    # --- Combined rewrites ---
    E2ECase(
        id="E07",
        category="TOP + GETDATE + ISNULL + brackets",
        mssql_sql=(
            "SELECT TOP 3 c.full_name, ISNULL(c.phone, N'无') AS phone, "
            "GETDATE() AS now_time FROM Customer c "
            "WHERE c.is_vip = 1 ORDER BY c.credit_limit DESC"
        ),
        expected_rules=["TOP → LIMIT", "GETDATE → NOW", "ISNULL → COALESCE"],
        skip_data_compare=True,
    ),
    E2ECase(
        id="E08",
        category="CHARINDEX → POSITION",
        mssql_sql="SELECT full_name, CHARINDEX(N'科技', full_name) AS pos FROM Customer WHERE customer_id <= 5",
        expected_rules=["CHARINDEX → POSITION"],
    ),
    E2ECase(
        id="E09",
        category="DATEADD → + INTERVAL",
        mssql_sql="SELECT full_name, DATEADD(day, 30, registered_at) AS follow_up FROM Customer WHERE customer_id <= 3",
        expected_rules=["DATEADD → + INTERVAL"],
    ),
    E2ECase(
        id="E10",
        category="IIF → CASE WHEN",
        mssql_sql="SELECT full_name, IIF(is_vip = 1, N'VIP', N'普通') AS tier_label FROM Customer WHERE customer_id <= 5",
        expected_rules=["IIF → CASE WHEN"],
    ),
    E2ECase(
        id="E11",
        category="FORMAT → TO_CHAR",
        mssql_sql="SELECT full_name, FORMAT(registered_at, 'yyyy-MM-dd') AS reg_date FROM Customer WHERE customer_id <= 3",
        expected_rules=["FORMAT → TO_CHAR"],
    ),
    E2ECase(
        id="E12",
        category="CONCAT → ||",
        mssql_sql="SELECT CONCAT(customer_code, N' - ', full_name) AS display FROM Customer WHERE customer_id <= 3",
        expected_rules=["CONCAT → ||"],
    ),
    E2ECase(
        id="E13",
        category="EOMONTH → DATE_TRUNC",
        mssql_sql="SELECT full_name, EOMONTH(registered_at) AS month_end FROM Customer WHERE customer_id <= 3",
        expected_rules=["EOMONTH → DATE_TRUNC"],
    ),
    E2ECase(
        id="E14",
        category="SYSDATETIME → NOW",
        mssql_sql="SELECT full_name, SYSDATETIME() AS now_time FROM Customer WHERE customer_id <= 3",
        expected_rules=["SYSDATETIME → NOW"],
        skip_data_compare=True,
    ),
    E2ECase(
        id="E15",
        category="@@IDENTITY → LASTVAL",
        mssql_sql="SELECT @@IDENTITY AS last_id, full_name FROM Customer WHERE customer_id = 1",
        expected_rules=["@@IDENTITY/SCOPE_IDENTITY → LASTVAL"],
    ),
]


# ===========================================================================
# Test runner
# ===========================================================================


@dataclass
class E2EResult:
    """Result of a single E2E test case."""
    case_id: str
    category: str
    mssql_sql: str
    rewritten_sql: str = ""
    rules_applied: list[str] = field(default_factory=list)
    # Source (MSSQL) execution
    source_ok: bool = False
    source_columns: list[str] = field(default_factory=list)
    source_rows: int = 0
    source_error: str = ""
    # Target execution
    target_db: str = ""
    target_ok: bool = False
    target_columns: list[str] = field(default_factory=list)
    target_rows: int = 0
    target_error: str = ""
    # Comparison
    columns_match: bool = False
    rows_match: bool = False
    data_match: bool = False
    overall_pass: bool = False


def _normalize_row(row: list) -> list:
    """Normalize row values for cross-database comparison."""
    result = []
    for v in row:
        if v is None:
            result.append(None)
        elif hasattr(v, 'isoformat'):
            # datetime/date — compare as string (precision may differ)
            result.append(str(v)[:19])
        elif isinstance(v, bool):
            result.append(1 if v else 0)
        elif isinstance(v, (int, float)):
            result.append(round(float(v), 2))
        elif isinstance(v, str):
            stripped = v.strip()
            # KingbaseES MSSQL compat may return INT/DECIMAL/DATETIME as strings
            # Handle datetime strings: "2026-07-26 15:36:07.000"
            if len(stripped) >= 19 and stripped[4] == '-' and stripped[10] == ' ':
                result.append(stripped[:19])  # truncate to seconds
            else:
                try:
                    result.append(round(float(stripped), 2))
                except ValueError:
                    result.append(stripped)
        elif isinstance(v, bytes):
            result.append(v.hex())
        elif hasattr(v, '__float__'):
            # Decimal and other numeric types
            result.append(round(float(v), 2))
        else:
            result.append(str(v))
    return result


def run_e2e_case(case: E2ECase, target_db: str) -> E2EResult:
    """Run a single E2E test case against a target database."""
    result = E2EResult(
        case_id=case.id,
        category=case.category,
        mssql_sql=case.mssql_sql,
        target_db=target_db,
    )

    # 1. Execute on MSSQL
    src = _execute_query("mssql", case.mssql_sql)
    result.source_ok = src["success"]
    result.source_columns = src["columns"]
    result.source_rows = src["row_count"]
    result.source_error = src.get("error", "") or ""

    if not result.source_ok:
        return result

    # 2. Rewrite
    rw: RewriteResult = rewrite_sql(case.mssql_sql, "mssql", target_db)
    result.rewritten_sql = rw.rewritten_sql
    result.rules_applied = [r.name for r in rw.rules_applied]

    # 3. Execute rewritten SQL on target
    tgt = _execute_query(target_db, rw.rewritten_sql)
    result.target_ok = tgt["success"]
    result.target_columns = tgt["columns"]
    result.target_rows = tgt["row_count"]
    result.target_error = tgt.get("error", "") or ""

    # 4. Compare
    if result.target_ok:
        result.columns_match = result.source_columns == result.target_columns
        result.rows_match = result.source_rows == result.target_rows

        # Data comparison (normalized)
        if case.skip_data_compare:
            # Volatile results (GETDATE/NOW) — skip exact data compare
            result.data_match = True
        elif result.rows_match and result.source_rows > 0:
            src_normalized = [_normalize_row(r) for r in src["rows"]]
            tgt_normalized = [_normalize_row(r) for r in tgt["rows"]]
            # Sort for order-independent comparison (unless ORDER BY present)
            if "ORDER BY" not in case.mssql_sql.upper():
                src_normalized.sort(key=str)
                tgt_normalized.sort(key=str)
            result.data_match = src_normalized == tgt_normalized
        elif result.source_rows == 0 and result.target_rows == 0:
            result.data_match = True

    result.overall_pass = (
        result.target_ok
        and result.columns_match
        and result.rows_match
        and result.data_match
    )

    return result


# ===========================================================================
# Report generation
# ===========================================================================


def print_report(results: list[E2EResult]):
    """Print formatted E2E test report."""
    total = len(results)
    passed = sum(1 for r in results if r.overall_pass)
    target_ok = sum(1 for r in results if r.target_ok)
    failed = total - passed

    print("\n" + "=" * 80)
    print("                    E2E Rewrite Validation Report")
    print("=" * 80)
    print(f"  Total cases:       {total}")
    print(f"  Target SQL OK:     {target_ok}/{total}")
    print(f"  Results match:     {passed}/{total} ({100*passed//max(total,1)}%)")
    print(f"  Failed:            {failed}/{total}")

    # Group by target_db
    by_target: dict[str, list[E2EResult]] = {}
    for r in results:
        by_target.setdefault(r.target_db, []).append(r)

    for target_db, tgt_results in by_target.items():
        t_total = len(tgt_results)
        t_pass = sum(1 for r in tgt_results if r.overall_pass)
        t_ok = sum(1 for r in tgt_results if r.target_ok)
        print(f"\n  [{target_db.upper()}] target_ok={t_ok}/{t_total}, match={t_pass}/{t_total}")

    # Detailed results
    print("\n" + "=" * 80)
    print("                          Detailed Results")
    print("=" * 80)

    for r in results:
        status = "PASS" if r.overall_pass else "FAIL"
        icon = "\u2705" if r.overall_pass else "\u274c"
        print(f"\n[{r.case_id}] {r.category} [{r.target_db}] {icon} {status}")
        print(f"  MSSQL SQL  : {r.mssql_sql[:80]}{'...' if len(r.mssql_sql)>80 else ''}")
        print(f"  Rewritten  : {r.rewritten_sql[:80]}{'...' if len(r.rewritten_sql)>80 else ''}")
        print(f"  Rules      : {r.rules_applied}")
        print(f"  Source     : {'OK' if r.source_ok else 'FAIL'} ({r.source_rows} rows)")
        if r.source_error:
            print(f"  Source Err : {r.source_error[:80]}")
        print(f"  Target     : {'OK' if r.target_ok else 'FAIL'} ({r.target_rows} rows)")
        if r.target_error:
            err_short = r.target_error.split("\n")[0][:100]
            print(f"  Target Err : {err_short}")
        if r.target_ok and not r.overall_pass:
            if not r.columns_match:
                print(f"  \u26a0\ufe0f  Column mismatch: {r.source_columns} vs {r.target_columns}")
            if not r.rows_match:
                print(f"  \u26a0\ufe0f  Row count mismatch: {r.source_rows} vs {r.target_rows}")
            if r.rows_match and not r.data_match:
                print(f"  \u26a0\ufe0f  Data mismatch")

    # Summary of failure categories
    print("\n" + "=" * 80)
    print("                        Failure Analysis")
    print("=" * 80)

    syntax_errors = [r for r in results if r.target_error and "syntax" in r.target_error.lower()]
    func_errors = [r for r in results if r.target_error and "not a recognized" in r.target_error.lower()]
    other_errors = [r for r in results if r.target_error and r not in syntax_errors and r not in func_errors]

    if syntax_errors:
        print(f"\n  Syntax errors ({len(syntax_errors)}):")
        for r in syntax_errors:
            print(f"    [{r.case_id}] {r.category}: rewritten SQL uses incompatible syntax")

    if func_errors:
        print(f"\n  Unknown function errors ({len(func_errors)}):")
        for r in func_errors:
            print(f"    [{r.case_id}] {r.category}: rewritten SQL uses unsupported function")

    if other_errors:
        print(f"\n  Other errors ({len(other_errors)}):")
        for r in other_errors:
            print(f"    [{r.case_id}] {r.category}: {r.target_error[:80]}")

    data_mismatches = [r for r in results if r.target_ok and not r.overall_pass]
    if data_mismatches:
        print(f"\n  Data/structure mismatches ({len(data_mismatches)}):")
        for r in data_mismatches:
            issues = []
            if not r.columns_match: issues.append("columns")
            if not r.rows_match: issues.append("rows")
            if r.rows_match and not r.data_match: issues.append("data")
            print(f"    [{r.case_id}] {r.category}: {', '.join(issues)}")

    print()


# ===========================================================================
# Pytest tests
# ===========================================================================


class TestE2EKingbaseES:
    """E2E tests: MSSQL → KingbaseES."""

    @pytest.fixture(autouse=True)
    def _collect_results(self):
        """Run all cases and store results."""
        self.results = []
        for case in E2E_CASES:
            r = run_e2e_case(case, "kingbasees")
            self.results.append(r)

    def test_report(self):
        """Print the full report (always runs, shows all results)."""
        print_report(self.results)

    def test_target_sql_executes(self):
        """Rewritten SQL must execute without errors on KingbaseES."""
        failures = [r for r in self.results if not r.target_ok]
        if failures:
            details = "\n".join(
                f"  [{r.case_id}] {r.category}: {r.target_error[:80]}"
                for r in failures
            )
            pytest.fail(f"{len(failures)}/{len(self.results)} rewritten SQLs failed on KingbaseES:\n{details}")

    def test_results_match(self):
        """Rewritten SQL results must match original MSSQL results."""
        failures = [r for r in self.results if r.target_ok and not r.overall_pass]
        if failures:
            details = "\n".join(
                f"  [{r.case_id}] {r.category}: cols_match={r.columns_match}, rows_match={r.rows_match}, data_match={r.data_match}"
                for r in failures
            )
            pytest.fail(f"{len(failures)}/{len(self.results)} results differ:\n{details}")


class TestE2EDM8:
    """E2E tests: MSSQL → DM8."""

    @pytest.fixture(autouse=True)
    def _collect_results(self):
        """Run all cases and store results."""
        self.results = []
        for case in E2E_CASES:
            if case.skip_dm8:
                continue
            r = run_e2e_case(case, "dm8")
            self.results.append(r)

    def test_report(self):
        """Print the full report."""
        print_report(self.results)

    def test_target_sql_executes(self):
        """Rewritten SQL must execute without errors on DM8."""
        failures = [r for r in self.results if not r.target_ok]
        if failures:
            details = "\n".join(
                f"  [{r.case_id}] {r.category}: {r.target_error[:80]}"
                for r in failures
            )
            pytest.fail(f"{len(failures)}/{len(self.results)} rewritten SQLs failed on DM8:\n{details}")

    def test_results_match(self):
        """Rewritten SQL results must match original MSSQL results."""
        failures = [r for r in self.results if r.target_ok and not r.overall_pass]
        if failures:
            details = "\n".join(
                f"  [{r.case_id}] {r.category}: cols_match={r.columns_match}, rows_match={r.rows_match}, data_match={r.data_match}"
                for r in failures
            )
            pytest.fail(f"{len(failures)}/{len(self.results)} results differ:\n{details}")


# ===========================================================================
# Standalone runner
# ===========================================================================

if __name__ == "__main__":
    print("\nRunning E2E rewrite validation against real databases...")
    print(f"MSSQL:      {settings.mssql_host}:{settings.mssql_port}")
    print(f"KingbaseES: {settings.kingbasees_host}:{settings.kingbasees_port}")
    print(f"DM8:        {settings.dm8_host}:{settings.dm8_port}")

    all_results: list[E2EResult] = []

    # KingbaseES
    print("\n--- MSSQL → KingbaseES ---")
    for case in E2E_CASES:
        r = run_e2e_case(case, "kingbasees")
        all_results.append(r)

    # DM8
    print("\n--- MSSQL → DM8 ---")
    for case in E2E_CASES:
        if not case.skip_dm8:
            r = run_e2e_case(case, "dm8")
            all_results.append(r)

    print_report(all_results)
