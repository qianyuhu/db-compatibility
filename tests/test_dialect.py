"""
test_dialect.py — SQL Dialect 层单元测试。

验证各方言的改写能力:
    - limit/offset rewrite
    - upsert rewrite
    - datetime function mapping
    - identifier quoting
    - parameter normalization
    - pipeline 集成
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architecture.core.sql.dialect import (
    BaseDialect,
    MSSQLDialect,
    KingbaseMSSQLDialect,
    OracleDialect,
    get_dialect,
)
from architecture.core.sql.rewrite.pipeline import rewrite, rewrite_with_detail, compile_sql


# =========================================================================
# Dialect 注册表
# =========================================================================


class TestDialectRegistry:
    """方言注册表测试。"""

    def test_get_mssql(self):
        d = get_dialect("mssql")
        assert isinstance(d, MSSQLDialect)
        assert d.name == "mssql"

    def test_get_kingbasees(self):
        d = get_dialect("kingbasees")
        assert isinstance(d, KingbaseMSSQLDialect)
        assert d.name == "kingbase_mssql"

    def test_get_oracle(self):
        d = get_dialect("oracle")
        assert isinstance(d, OracleDialect)
        assert d.name == "oracle"

    def test_get_dm8_returns_oracle(self):
        d = get_dialect("dm8")
        assert isinstance(d, OracleDialect)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown db_type"):
            get_dialect("mysql")


# =========================================================================
# MSSQL Dialect
# =========================================================================


class TestMSSQLDialect:
    """MSSQL 方言改写测试。"""

    @pytest.fixture
    def dialect(self) -> MSSQLDialect:
        return MSSQLDialect()

    # --- LIMIT/OFFSET ---

    def test_limit_to_top(self, dialect: MSSQLDialect):
        sql = "SELECT * FROM users LIMIT 10"
        result = dialect.rewrite_limit_offset(sql)
        assert "TOP 10" in result.upper()
        assert "LIMIT" not in result.upper()

    def test_limit_offset_to_fetch(self, dialect: MSSQLDialect):
        sql = "SELECT * FROM users ORDER BY id LIMIT 10 OFFSET 5"
        result = dialect.rewrite_limit_offset(sql)
        assert "OFFSET 5 ROWS" in result
        assert "FETCH NEXT 10 ROWS ONLY" in result

    def test_no_limit_unchanged(self, dialect: MSSQLDialect):
        sql = "SELECT * FROM users"
        assert dialect.rewrite_limit_offset(sql) == sql

    def test_already_has_top(self, dialect: MSSQLDialect):
        sql = "SELECT TOP 5 * FROM users LIMIT 5"
        result = dialect.rewrite_limit_offset(sql)
        assert result.count("TOP") == 1  # 不重复添加

    # --- UPSERT ---

    def test_on_conflict_warning(self, dialect: MSSQLDialect):
        sql = "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2"
        result = dialect.rewrite_upsert(sql)
        assert "WARNING" in result

    def test_simple_insert_unchanged(self, dialect: MSSQLDialect):
        sql = "INSERT INTO t (a) VALUES (1)"
        assert dialect.rewrite_upsert(sql) == sql

    # --- DATETIME ---

    def test_now_to_getdate(self, dialect: MSSQLDialect):
        sql = "SELECT NOW() FROM t"
        result = dialect.map_datetime_func(sql)
        assert "GETDATE()" in result
        assert "NOW()" not in result

    def test_sysdate_to_getdate(self, dialect: MSSQLDialect):
        sql = "SELECT SYSDATE FROM t"
        result = dialect.map_datetime_func(sql)
        assert "GETDATE()" in result

    # --- IDENTIFIER QUOTING ---

    def test_quote_identifier(self, dialect: MSSQLDialect):
        assert dialect.quote_identifier("my_table") == "[my_table]"

    def test_normalize_identifiers_noop(self, dialect: MSSQLDialect):
        sql = "SELECT [id], [name] FROM [users]"
        assert dialect.normalize_identifiers(sql) == sql  # MSSQL 原生方括号

    # --- PARAMS ---

    def test_normalize_params_to_question(self, dialect: MSSQLDialect):
        sql = "SELECT * FROM t WHERE id = %s AND name = %s"
        result = dialect.normalize_params(sql)
        assert result.count("?") == 2
        assert "%s" not in result


# =========================================================================
# KingbaseMSSQL Dialect
# =========================================================================


class TestKingbaseMSSQLDialect:
    """KingbaseES MSSQL Compatible 模式改写测试。"""

    @pytest.fixture
    def dialect(self) -> KingbaseMSSQLDialect:
        return KingbaseMSSQLDialect()

    # --- LIMIT/OFFSET ---

    def test_top_to_limit(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT TOP 10 * FROM users"
        result = dialect.rewrite_limit_offset(sql)
        assert "LIMIT 10" in result
        assert "TOP" not in result.upper()

    def test_limit_preserved(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT * FROM users LIMIT 10"
        result = dialect.rewrite_limit_offset(sql)
        assert "LIMIT 10" in result

    def test_offset_fetch_to_limit_offset(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT * FROM users ORDER BY id OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"
        result = dialect.rewrite_limit_offset(sql)
        assert "LIMIT 5" in result
        assert "OFFSET 10" in result

    # --- DATETIME ---

    def test_getdate_to_now(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT GETDATE() FROM t"
        result = dialect.map_datetime_func(sql)
        assert "NOW()" in result
        assert "GETDATE()" not in result

    def test_sysdate_to_now(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT SYSDATE FROM t"
        result = dialect.map_datetime_func(sql)
        assert "NOW()" in result

    # --- IDENTIFIER QUOTING ---

    def test_quote_identifier(self, dialect: KingbaseMSSQLDialect):
        assert dialect.quote_identifier("my_table") == '"my_table"'

    def test_normalize_identifiers(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT [id], [name] FROM [users]"
        result = dialect.normalize_identifiers(sql)
        assert '"id"' in result
        assert '"name"' in result
        assert '"users"' in result

    # --- PARAMS ---

    def test_params_unchanged(self, dialect: KingbaseMSSQLDialect):
        sql = "SELECT * FROM t WHERE id = %s"
        assert dialect.normalize_params(sql) == sql


# =========================================================================
# Oracle Dialect
# =========================================================================


class TestOracleDialect:
    """Oracle 方言改写测试。"""

    @pytest.fixture
    def dialect(self) -> OracleDialect:
        return OracleDialect()

    # --- LIMIT/OFFSET ---

    def test_limit_to_fetch_first(self, dialect: OracleDialect):
        sql = "SELECT * FROM users LIMIT 10"
        result = dialect.rewrite_limit_offset(sql)
        assert "FETCH FIRST 10 ROWS ONLY" in result
        assert "LIMIT" not in result.upper()

    def test_limit_offset_to_fetch(self, dialect: OracleDialect):
        sql = "SELECT * FROM users ORDER BY id LIMIT 10 OFFSET 5"
        result = dialect.rewrite_limit_offset(sql)
        assert "OFFSET 5 ROWS" in result
        assert "FETCH NEXT 10 ROWS ONLY" in result

    # --- DATETIME ---

    def test_now_to_sysdate(self, dialect: OracleDialect):
        sql = "SELECT NOW() FROM t"
        result = dialect.map_datetime_func(sql)
        assert "SYSDATE" in result

    def test_getdate_to_sysdate(self, dialect: OracleDialect):
        sql = "SELECT GETDATE() FROM t"
        result = dialect.map_datetime_func(sql)
        assert "SYSDATE" in result

    # --- IDENTIFIER QUOTING ---

    def test_quote_identifier_uppercase(self, dialect: OracleDialect):
        assert dialect.quote_identifier("my_table") == '"MY_TABLE"'

    # --- PARAMS ---

    def test_params_to_numbered(self, dialect: OracleDialect):
        sql = "SELECT * FROM t WHERE id = %s AND name = %s"
        result = dialect.normalize_params(sql)
        assert ":1" in result
        assert ":2" in result
        assert "%s" not in result


# =========================================================================
# Pipeline 集成测试
# =========================================================================


class TestPipeline:
    """SQL Rewrite Pipeline 集成测试。"""

    def test_mssql_full_pipeline(self):
        dialect = get_dialect("mssql")
        sql = "SELECT [id], NOW() FROM users WHERE id = %s LIMIT 10"
        result = rewrite(sql, dialect)
        # LIMIT → TOP, NOW() → GETDATE(), %s → ?, [id] 保持不变
        assert "TOP 10" in result.upper()
        assert "GETDATE()" in result
        assert "?" in result

    def test_kingbase_full_pipeline(self):
        dialect = get_dialect("kingbasees")
        sql = "SELECT TOP 10 [id], GETDATE() FROM users WHERE id = %s"
        result = rewrite(sql, dialect)
        # TOP → LIMIT, GETDATE() → NOW(), %s 保持, [id] → "id"
        assert "LIMIT 10" in result
        assert "NOW()" in result
        assert "%s" in result
        assert '"id"' in result

    def test_pipeline_with_detail(self):
        dialect = get_dialect("mssql")
        sql = "SELECT * FROM t LIMIT 5"
        result = rewrite_with_detail(sql, dialect)
        assert result.dialect == "mssql"
        assert "rewrite_limit_offset" in result.steps_applied

    def test_compile_sql(self):
        dialect = get_dialect("mssql")
        sql = "SELECT * FROM t WHERE id = %s LIMIT 10"
        compiled_sql, params = compile_sql(sql, dialect, ("abc",))
        assert "TOP 10" in compiled_sql.upper()
        assert params == ("abc",)

    def test_identity_no_changes(self):
        dialect = get_dialect("kingbasees")
        sql = "SELECT * FROM users"
        result = rewrite_with_detail(sql, dialect)
        assert result.steps_applied == []
