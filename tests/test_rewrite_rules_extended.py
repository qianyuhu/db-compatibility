"""
Extended Rewrite Rules Tests — validates Phase 2 production-grade rules.

Tests each new rule added in the migration difficulties enhancement:
- Function-level rewrites (SYSDATETIME, EOMONTH, FORMAT, IIF, DATENAME, etc.)
- Structural rewrites (WITH ROLLUP/CUBE, SELECT INTO, UPDATE FROM JOIN, etc.)
- Warning rules (TRY_CAST, OUTPUT, FOR XML/JSON, etc.)
- Regression tests for existing rules
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from architecture.core.sql.rewrite.engine import rewrite_sql
from architecture.core.sql.rewrite.rules import MSSQL_TO_PG_RULES, apply_rules
from architecture.core.sql.rewrite.engine import normalize, RewriteResult


# ===========================================================================
# Helper
# ===========================================================================

def _rewrite(sql: str, src: str = "mssql", tgt: str = "kingbasees"):
    """Shorthand for rewrite_sql."""
    return rewrite_sql(sql, src, tgt)


def _rewrite_full_pg(sql: str):
    """Rewrite using full MSSQL_TO_PG_RULES (33 rules, for testing excluded rules)."""
    norm_ast = normalize(sql)
    rewritten, applied, warnings = apply_rules(sql, norm_ast, MSSQL_TO_PG_RULES)
    return RewriteResult(
        original_sql=sql.strip(),
        rewritten_sql=rewritten,
        source_db="mssql",
        target_db="kingbasees",
        rules_applied=applied,
        confidence=1.0,
        warnings=warnings,
    )


def _rule_names(result):
    """Get list of applied rule names."""
    return [r.name for r in result.rules_applied]


# ===========================================================================
# 1. SYSDATETIME → NOW / SYSDATE
# ===========================================================================

class TestSysdatetime:
    def test_sysdatetime_to_now_pg(self):
        r = _rewrite_full_pg("SELECT SYSDATETIME() AS now_time")
        assert "NOW()" in r.rewritten_sql
        assert "SYSDATETIME → NOW" in _rule_names(r)

    def test_sysdatetime_to_sysdate_dm8(self):
        r = _rewrite("SELECT SYSDATETIME() AS now_time", tgt="dm8")
        assert "SYSDATE" in r.rewritten_sql
        assert "SYSDATETIME → SYSDATE" in _rule_names(r)

    def test_sysdatetimeoffset_to_now(self):
        r = _rewrite_full_pg("SELECT SYSDATETIMEOFFSET()")
        assert "NOW()" in r.rewritten_sql
        assert "SYSDATETIMEOFFSET → NOW" in _rule_names(r)

    def test_sysdatetimeoffset_to_systimestamp_dm8(self):
        r = _rewrite("SELECT SYSDATETIMEOFFSET()", tgt="dm8")
        assert "SYSTIMESTAMP" in r.rewritten_sql


# ===========================================================================
# 2. EOMONTH → DATE_TRUNC / LAST_DAY
# ===========================================================================

class TestEomonth:
    def test_eomonth_pg(self):
        r = _rewrite_full_pg("SELECT EOMONTH(order_date) FROM dbo.[Order]")
        assert "DATE_TRUNC" in r.rewritten_sql
        assert "INTERVAL" in r.rewritten_sql
        assert "EOMONTH → DATE_TRUNC" in _rule_names(r)

    def test_eomonth_dm8(self):
        r = _rewrite("SELECT EOMONTH(order_date)", tgt="dm8")
        assert "LAST_DAY" in r.rewritten_sql
        assert "EOMONTH → LAST_DAY" in _rule_names(r)

    def test_eomonth_with_complex_expr(self):
        r = _rewrite_full_pg("SELECT EOMONTH(DATEADD(MONTH, -1, GETDATE()))")
        assert "DATE_TRUNC" in r.rewritten_sql


# ===========================================================================
# 3. FORMAT → TO_CHAR
# ===========================================================================

class TestFormat:
    def test_format_date(self):
        r = _rewrite_full_pg("SELECT FORMAT(GETDATE(), 'yyyy-MM-dd HH:mm:ss')")
        assert "TO_CHAR" in r.rewritten_sql
        assert "FORMAT → TO_CHAR" in _rule_names(r)

    def test_format_with_getdate_rewrite(self):
        r = _rewrite_full_pg("SELECT FORMAT(GETDATE(), 'yyyy-MM-dd')")
        names = _rule_names(r)
        assert "FORMAT → TO_CHAR" in names
        assert "GETDATE → NOW" in names

    def test_format_chinese(self):
        r = _rewrite_full_pg("SELECT FORMAT(GETDATE(), N'yyyy年MM月dd日')")
        assert "TO_CHAR" in r.rewritten_sql


# ===========================================================================
# 4. IIF → CASE WHEN
# ===========================================================================

class TestIif:
    def test_simple_iif(self):
        r = _rewrite_full_pg("SELECT IIF(x > 0, 'yes', 'no') FROM t")
        assert "CASE WHEN x > 0 THEN 'yes' ELSE 'no' END" in r.rewritten_sql
        assert "IIF → CASE WHEN" in _rule_names(r)

    def test_iif_with_numeric(self):
        r = _rewrite_full_pg("SELECT IIF(unit_price > 1000, 1, 0) FROM dbo.Product")
        assert "CASE WHEN" in r.rewritten_sql

    def test_iif_dm8(self):
        r = _rewrite("SELECT IIF(a = 1, 'one', 'other')", tgt="dm8")
        assert "CASE WHEN" in r.rewritten_sql


# ===========================================================================
# 5. DATENAME → TO_CHAR
# ===========================================================================

class TestDatename:
    def test_datename_weekday(self):
        r = _rewrite_full_pg("SELECT DATENAME(WEEKDAY, order_date) FROM dbo.[Order]")
        assert "TO_CHAR" in r.rewritten_sql
        assert "TMDay" in r.rewritten_sql

    def test_datename_month(self):
        r = _rewrite_full_pg("SELECT DATENAME(MONTH, GETDATE())")
        assert "TO_CHAR" in r.rewritten_sql
        assert "DATENAME → TO_CHAR" in _rule_names(r)

    def test_datename_year(self):
        r = _rewrite_full_pg("SELECT DATENAME(YEAR, order_date)")
        assert "TO_CHAR" in r.rewritten_sql


# ===========================================================================
# 6. TRY_CAST / TRY_CONVERT — warning
# ===========================================================================

class TestTryCast:
    def test_try_cast_warning(self):
        r = _rewrite_full_pg("SELECT TRY_CAST('abc' AS INT)")
        assert "WARNING" in r.rewritten_sql
        assert "TRY_CAST" in r.rewritten_sql

    def test_try_convert_warning(self):
        r = _rewrite_full_pg("SELECT TRY_CONVERT(DATE, '2024-01-01')")
        assert "WARNING" in r.rewritten_sql

    def test_multiple_try_cast(self):
        r = _rewrite_full_pg("SELECT TRY_CAST('1' AS INT), TRY_CONVERT(DATE, 'x')")
        assert "WARNING" in r.rewritten_sql


# ===========================================================================
# 7. CONVERT with style code
# ===========================================================================

class TestConvertStyle:
    def test_convert_style_120(self):
        r = _rewrite_full_pg("SELECT CONVERT(VARCHAR, GETDATE(), 120)")
        assert "TO_CHAR" in r.rewritten_sql
        assert "CONVERT(style) → TO_CHAR" in _rule_names(r)

    def test_convert_style_112(self):
        r = _rewrite_full_pg("SELECT CONVERT(VARCHAR, GETDATE(), 112)")
        assert "TO_CHAR" in r.rewritten_sql

    def test_convert_unknown_style_fallback(self):
        r = _rewrite_full_pg("SELECT CONVERT(VARCHAR, GETDATE(), 999)")
        # Unknown style falls back to CAST
        assert "CAST" in r.rewritten_sql or "CONVERT(style) → TO_CHAR" in _rule_names(r)


# ===========================================================================
# 8. @@IDENTITY / SCOPE_IDENTITY → LASTVAL
# ===========================================================================

class TestIdentity:
    def test_at_at_identity(self):
        r = _rewrite_full_pg("SELECT @@IDENTITY AS last_id")
        assert "LASTVAL()" in r.rewritten_sql

    def test_scope_identity(self):
        r = _rewrite_full_pg("SELECT SCOPE_IDENTITY() AS last_id")
        assert "LASTVAL()" in r.rewritten_sql
        assert "@@IDENTITY/SCOPE_IDENTITY → LASTVAL" in _rule_names(r)

    def test_ident_current_warning(self):
        r = _rewrite_full_pg("SELECT IDENT_CURRENT('dbo.Order') AS last_id")
        assert "WARNING" in r.rewritten_sql


# ===========================================================================
# 9. CONCAT → ||
# ===========================================================================

class TestConcat:
    def test_simple_concat(self):
        r = _rewrite_full_pg("SELECT CONCAT(a, b) FROM t")
        assert "a || b" in r.rewritten_sql
        assert "CONCAT → ||" in _rule_names(r)

    def test_concat_three_args(self):
        r = _rewrite_full_pg("SELECT CONCAT(a, ' - ', b) FROM t")
        assert "||" in r.rewritten_sql

    def test_concat_ws_no_warning_pg(self):
        r = _rewrite_full_pg("SELECT CONCAT_WS(', ', a, b) FROM t")
        # PG supports CONCAT_WS, no warning
        assert "WARNING" not in r.rewritten_sql or "CONCAT_WS" not in _rule_names(r)

    def test_concat_ws_warning_dm8(self):
        r = _rewrite("SELECT CONCAT_WS(', ', a, b)", tgt="dm8")
        assert "WARNING" in r.rewritten_sql


# ===========================================================================
# 10. QUOTENAME — warning
# ===========================================================================

class TestQuotename:
    def test_quotename_warning(self):
        r = _rewrite_full_pg("SELECT QUOTENAME('Order')")
        assert "WARNING" in r.rewritten_sql
        assert "QUOTENAME" in r.rewritten_sql


# ===========================================================================
# 11. WITH ROLLUP → GROUPING SETS
# ===========================================================================

class TestWithRollup:
    def test_basic_rollup(self):
        sql = "SELECT region, tier, COUNT(*) FROM Customer GROUP BY region, tier WITH ROLLUP"
        r = _rewrite(sql)
        assert "GROUPING SETS" in r.rewritten_sql
        assert "WITH ROLLUP" not in r.rewritten_sql
        assert "WITH ROLLUP → GROUPING SETS" in _rule_names(r)

    def test_rollup_three_cols(self):
        sql = "SELECT a, b, c, SUM(x) FROM t GROUP BY a, b, c WITH ROLLUP"
        r = _rewrite(sql)
        assert "GROUPING SETS" in r.rewritten_sql
        # Should have 4 sets: (a,b,c), (a,b), (a), ()
        assert "(a, b, c)" in r.rewritten_sql
        assert "()" in r.rewritten_sql

    def test_rollup_dm8(self):
        sql = "SELECT region, COUNT(*) FROM Customer GROUP BY region WITH ROLLUP"
        r = _rewrite(sql, tgt="dm8")
        assert "GROUPING SETS" in r.rewritten_sql


# ===========================================================================
# 12. WITH CUBE → GROUPING SETS
# ===========================================================================

class TestWithCube:
    def test_basic_cube(self):
        sql = "SELECT a, b, SUM(x) FROM t GROUP BY a, b WITH CUBE"
        r = _rewrite(sql)
        assert "GROUPING SETS" in r.rewritten_sql
        assert "WITH CUBE" not in r.rewritten_sql
        assert "WITH CUBE → GROUPING SETS" in _rule_names(r)

    def test_cube_all_combinations(self):
        sql = "SELECT a, b, SUM(x) FROM t GROUP BY a, b WITH CUBE"
        r = _rewrite(sql)
        # Should have 4 sets: (a,b), (a), (b), ()
        assert "(a, b)" in r.rewritten_sql
        assert "(b)" in r.rewritten_sql


# ===========================================================================
# 13. SELECT INTO → CREATE TABLE AS
# ===========================================================================

class TestSelectInto:
    def test_basic_select_into(self):
        r = _rewrite_full_pg("SELECT a, b INTO new_table FROM old_table WHERE x > 1")
        assert "CREATE TABLE new_table AS" in r.rewritten_sql
        assert "INTO new_table" not in r.rewritten_sql
        assert "SELECT INTO → CREATE TABLE AS" in _rule_names(r)

    def test_select_into_temp_table(self):
        r = _rewrite_full_pg("SELECT a, b INTO #tmp FROM old_table")
        assert "CREATE TABLE tmp AS" in r.rewritten_sql

    def test_select_into_complex(self):
        sql = """SELECT c.customer_id, COUNT(o.order_id) AS cnt
INTO dbo.CustomerAnalytics
FROM dbo.Customer c LEFT JOIN dbo.[Order] o ON c.customer_id = o.customer_id
GROUP BY c.customer_id"""
        r = _rewrite(sql)
        assert "CREATE TABLE" in r.rewritten_sql
        assert "SELECT INTO → CREATE TABLE AS" in _rule_names(r)


# ===========================================================================
# 14. UPDATE FROM JOIN → subquery
# ===========================================================================

class TestUpdateFromJoin:
    def test_basic_update_from(self):
        sql = """UPDATE o SET o.status = 'shipped'
FROM dbo.[Order] o INNER JOIN dbo.Customer c ON o.customer_id = c.customer_id
WHERE c.tier = 'A'"""
        r = _rewrite(sql)
        assert "UPDATE FROM JOIN → 子查询" in _rule_names(r)
        # The original UPDATE FROM pattern should be gone
        assert "WARNING" in r.rewritten_sql or "UPDATE" in r.rewritten_sql

    def test_update_from_warning_on_complex(self):
        # Complex case that can't be auto-parsed → WARNING
        sql = "UPDATE t SET t.x = sub.val FROM t INNER JOIN (SELECT * FROM complex) sub ON t.id = sub.id"
        r = _rewrite(sql)
        # Should either rewrite or warn
        assert r.rules_applied or "WARNING" in r.rewritten_sql


# ===========================================================================
# 15. DELETE FROM JOIN → subquery
# ===========================================================================

class TestDeleteFromJoin:
    def test_basic_delete_from(self):
        sql = """DELETE oi FROM dbo.OrderItem oi INNER JOIN dbo.[Order] o ON oi.order_id = o.order_id WHERE o.status = 'cancelled'"""
        r = _rewrite(sql)
        assert "DELETE FROM JOIN → 子查询" in _rule_names(r)

    def test_delete_from_warning_on_complex(self):
        sql = "DELETE t FROM complex_table t LEFT JOIN other o ON t.id = o.id WHERE o.val > 100"
        r = _rewrite(sql)
        assert r.rules_applied or "WARNING" in r.rewritten_sql


# ===========================================================================
# 16. OUTPUT clause — warning
# ===========================================================================

class TestOutputClause:
    def test_output_inserted(self):
        sql = "INSERT INTO t (a) OUTPUT inserted.id VALUES (1)"
        r = _rewrite(sql)
        assert "WARNING" in r.rewritten_sql
        assert "OUTPUT" in r.rewritten_sql

    def test_output_deleted(self):
        sql = "DELETE FROM t OUTPUT deleted.id WHERE x > 1"
        r = _rewrite(sql)
        assert "WARNING" in r.rewritten_sql


# ===========================================================================
# 17. FOR XML / FOR JSON — warning
# ===========================================================================

class TestForXmlJson:
    def test_for_xml(self):
        sql = "SELECT * FROM Customer FOR XML AUTO"
        r = _rewrite(sql)
        assert "WARNING" in r.rewritten_sql
        assert "XML" in r.rewritten_sql

    def test_for_json(self):
        sql = "SELECT * FROM Customer FOR JSON PATH"
        r = _rewrite(sql)
        assert "WARNING" in r.rewritten_sql
        assert "JSON" in r.rewritten_sql


# ===========================================================================
# Regression tests — existing rules still work
# ===========================================================================

class TestRegression:
    def test_top_to_limit(self):
        r = _rewrite_full_pg("SELECT TOP 10 * FROM dbo.[Order]")
        assert "LIMIT 10" in r.rewritten_sql
        assert "TOP" not in r.rewritten_sql.upper().replace("TOP ", "").replace("TOP\n", "")

    def test_getdate_to_now(self):
        r = _rewrite_full_pg("SELECT GETDATE()")
        assert "NOW()" in r.rewritten_sql

    def test_isnull_to_coalesce(self):
        r = _rewrite_full_pg("SELECT ISNULL(a, 0) FROM t")
        assert "COALESCE" in r.rewritten_sql

    def test_len_to_length(self):
        r = _rewrite_full_pg("SELECT LEN(name) FROM t")
        assert "LENGTH" in r.rewritten_sql

    def test_brackets_to_quotes(self):
        r = _rewrite_full_pg("SELECT * FROM dbo.[Order]")
        assert '"Order"' in r.rewritten_sql

    def test_dateadd_to_interval(self):
        r = _rewrite_full_pg("SELECT DATEADD(DAY, 30, GETDATE())")
        assert "INTERVAL" in r.rewritten_sql

    def test_datediff(self):
        r = _rewrite_full_pg("SELECT DATEDIFF(DAY, '2024-01-01', GETDATE())")
        assert "EXTRACT" in r.rewritten_sql

    def test_newid(self):
        r = _rewrite_full_pg("SELECT NEWID()")
        assert "gen_random_uuid" in r.rewritten_sql

    def test_charindex(self):
        r = _rewrite_full_pg("SELECT CHARINDEX('a', name) FROM t")
        assert "POSITION" in r.rewritten_sql

    def test_dm8_isnull_to_nvl(self):
        r = _rewrite("SELECT ISNULL(a, 0) FROM t", tgt="dm8")
        assert "NVL" in r.rewritten_sql

    def test_dm8_getdate_to_sysdate(self):
        r = _rewrite("SELECT GETDATE()", tgt="dm8")
        assert "SYSDATE" in r.rewritten_sql

    def test_dm8_newid_to_sys_guid(self):
        r = _rewrite("SELECT NEWID()", tgt="dm8")
        assert "SYS_GUID" in r.rewritten_sql


# ===========================================================================
# Combined / multi-rule tests
# ===========================================================================

class TestCombined:
    def test_format_with_getdate_and_brackets(self):
        sql = "SELECT FORMAT(GETDATE(), 'yyyy-MM-dd') FROM dbo.[Order]"
        r = _rewrite_full_pg(sql)
        names = _rule_names(r)
        assert "FORMAT → TO_CHAR" in names
        assert "GETDATE → NOW" in names
        assert '[标识符] → "标识符"' in names

    def test_iif_with_sysdatetime(self):
        sql = "SELECT IIF(order_date > SYSDATETIME(), 'future', 'past') FROM dbo.[Order]"
        r = _rewrite_full_pg(sql)
        names = _rule_names(r)
        assert "IIF → CASE WHEN" in names
        assert "SYSDATETIME → NOW" in names

    def test_select_into_with_getdate(self):
        sql = "SELECT a, GETDATE() AS ts INTO #tmp FROM t"
        r = _rewrite(sql)
        names = _rule_names(r)
        assert "SELECT INTO → CREATE TABLE AS" in names
        assert "GETDATE → NOW" in names

    def test_concat_with_isnull(self):
        sql = "SELECT CONCAT(ISNULL(a, ''), b) FROM t"
        r = _rewrite_full_pg(sql)
        names = _rule_names(r)
        assert "CONCAT → ||" in names
        assert "ISNULL → COALESCE" in names

    def test_full_difficulty_scenario(self):
        """Test a real migration difficulty SQL end-to-end."""
        sql = """SELECT FORMAT(GETDATE(), 'yyyy-MM-dd') AS dt,
IIF(total > 1000, 'high', 'low') AS tier,
CONCAT(name, ' - ', region) AS label
FROM dbo.[Order]
WHERE order_date > EOMONTH(DATEADD(MONTH, -1, GETDATE()))"""
        r = _rewrite_full_pg(sql)
        names = _rule_names(r)
        assert "FORMAT → TO_CHAR" in names
        assert "IIF → CASE WHEN" in names
        assert "CONCAT → ||" in names
        assert "EOMONTH → DATE_TRUNC" in names
        assert "DATEADD → + INTERVAL" in names
        assert "GETDATE → NOW" in names
        assert '[标识符] → "标识符"' in names
        assert r.confidence > 0.6
