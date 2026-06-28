"""
Phase 2.5 · SQL Object-Level Diagnostics Engine Tests.

Tests the extractor, analyzer, and API endpoint for table/column/function/join
cross-DB compatibility diagnostics.
"""

from __future__ import annotations

import pytest

from app.api.sql_diagnostics.analyzer import analyze_objects
from app.api.sql_diagnostics.diagnose_schemas import (
    DiagnoseRequest,
    RiskLevel,
)
from app.api.sql_diagnostics.diagnose_router import sql_diagnose
from app.api.sql_diagnostics.extractor import (
    ExtractedObjects,
    extract_objects,
)


# ===========================================================================
# 1. Extractor Tests
# ===========================================================================


class TestExtractor:
    """Verify object extraction from SQL text."""

    def test_extract_simple_table(self):
        objects = extract_objects("SELECT id, name FROM users")
        assert len(objects.tables) == 1
        assert objects.tables[0].name == "users"
        assert objects.tables[0].alias is None

    def test_extract_table_with_alias(self):
        objects = extract_objects("SELECT u.id FROM users u")
        assert len(objects.tables) == 1
        assert objects.tables[0].name == "users"
        assert objects.tables[0].alias == "u"

    def test_extract_table_with_as_alias(self):
        objects = extract_objects("SELECT u.id FROM users AS u")
        assert len(objects.tables) == 1
        assert objects.tables[0].name == "users"
        assert objects.tables[0].alias == "u"

    def test_extract_multiple_tables(self):
        objects = extract_objects(
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert len(objects.tables) == 2
        table_names = {t.name for t in objects.tables}
        assert table_names == {"users", "orders"}

    def test_extract_top_function(self):
        objects = extract_objects("SELECT TOP 10 id FROM users")
        funcs = [f for f in objects.functions if f.name == "TOP"]
        assert len(funcs) == 1
        assert funcs[0].args == ["10"]
        assert funcs[0].raw == "TOP 10"

    def test_extract_getdate(self):
        objects = extract_objects("SELECT GETDATE() FROM users")
        funcs = [f for f in objects.functions if f.name == "GETDATE"]
        assert len(funcs) == 1
        assert funcs[0].raw == "GETDATE()"

    def test_extract_isnull(self):
        objects = extract_objects("SELECT ISNULL(col, 0) FROM t")
        funcs = [f for f in objects.functions if f.name == "ISNULL"]
        assert len(funcs) == 1
        assert "col" in funcs[0].args
        assert "0" in funcs[0].args

    def test_extract_columns_with_table_prefix(self):
        objects = extract_objects("SELECT u.id, u.name, u.email FROM users u")
        assert len(objects.columns) >= 2
        col_names = {c.full_name for c in objects.columns}
        assert "users.id" in col_names or "u.id" in col_names

    def test_extract_inner_join(self):
        objects = extract_objects(
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        )
        assert len(objects.joins) == 1
        assert objects.joins[0].join_type == "INNER"
        assert objects.joins[0].table == "orders"

    def test_extract_left_join(self):
        objects = extract_objects(
            "SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        )
        assert len(objects.joins) == 1
        assert objects.joins[0].join_type == "LEFT"

    def test_empty_sql(self):
        objects = extract_objects("")
        assert len(objects.tables) == 0
        assert len(objects.columns) == 0
        assert len(objects.functions) == 0

    def test_no_false_positives_on_keywords(self):
        """Keywords like SELECT, FROM, WHERE should not appear as objects."""
        objects = extract_objects("SELECT id FROM users WHERE id = 1")
        table_names = {t.name.upper() for t in objects.tables}
        assert "SELECT" not in table_names
        assert "FROM" not in table_names
        assert "WHERE" not in table_names


# ===========================================================================
# 2. Analyzer Tests
# ===========================================================================


class TestAnalyzer:
    """Verify risk analysis for extracted objects."""

    def test_standard_table_no_risk(self):
        objects = extract_objects("SELECT id FROM users")
        analysis = analyze_objects(objects, ["mssql", "kingbasees", "dm8"])
        assert len(analysis.tables) == 1
        assert analysis.tables[0].risk == RiskLevel.NONE
        assert analysis.tables[0].db_compatibility["mssql"] is True
        assert analysis.tables[0].db_compatibility["kingbasees"] is True

    def test_top_function_has_rewrite_rule(self):
        objects = extract_objects("SELECT TOP 10 id FROM users")
        analysis = analyze_objects(objects, ["mssql", "kingbasees"])
        funcs = [f for f in analysis.functions if f.name == "TOP"]
        assert len(funcs) == 1
        assert funcs[0].has_rewrite_rule is True

    def test_getdate_not_compatible_with_kingbasees_without_rewrite(self):
        """GETDATE is MSSQL-specific but has a rewrite rule."""
        objects = extract_objects("SELECT GETDATE() FROM users")
        analysis = analyze_objects(objects, ["kingbasees"])
        funcs = [f for f in analysis.functions if f.name == "GETDATE"]
        assert len(funcs) == 1
        # GETDATE has rewrite to NOW, so it should not be HIGH
        assert funcs[0].risk != RiskLevel.HIGH

    def test_standard_count_function_no_risk(self):
        objects = extract_objects("SELECT COUNT(*) FROM users")
        analysis = analyze_objects(objects, ["mssql", "kingbasees", "dm8"])
        count_funcs = [f for f in analysis.functions if f.name == "COUNT"]
        assert len(count_funcs) == 1
        assert count_funcs[0].risk == RiskLevel.NONE

    def test_inner_join_no_risk(self):
        objects = extract_objects(
            "SELECT * FROM users INNER JOIN orders ON users.id = orders.user_id"
        )
        analysis = analyze_objects(objects, ["mssql", "kingbasees"])
        assert len(analysis.joins) == 1
        assert analysis.joins[0].risk == RiskLevel.NONE

    def test_builds_summary_correctly(self):
        objects = extract_objects(
            "SELECT TOP 10 id, GETDATE(), COUNT(*) FROM users"
        )
        analysis = analyze_objects(objects, ["mssql", "kingbasees"])
        assert analysis.summary.total_objects > 0
        # Functions: TOP (LOW), GETDATE (LOW), COUNT (NONE)
        assert analysis.summary.functions.low >= 2
        assert analysis.summary.functions.none >= 1


# ===========================================================================
# 3. API Endpoint Tests
# ===========================================================================


class TestDiagnoseApi:
    """Integration tests for the POST /api/sql/diagnose endpoint."""

    def test_simple_select(self):
        req = DiagnoseRequest(
            sql="SELECT id, name FROM users WHERE is_active = 1",
            db_types=["mssql", "kingbasees"],
        )
        resp = sql_diagnose(req)
        assert resp.sql == req.sql
        assert resp.db_types == req.db_types
        assert len(resp.tables) >= 1
        assert resp.tables[0].name == "users"
        assert resp.summary.total_objects > 0

    def test_complex_query_with_multiple_objects(self):
        req = DiagnoseRequest(
            sql=(
                "SELECT TOP 10 u.id, u.name, GETDATE() AS now, "
                "ISNULL(u.phone, 'N/A') AS phone "
                "FROM users u "
                "LEFT JOIN orders o ON u.id = o.user_id "
                "WHERE u.is_active = 1"
            ),
            db_types=["mssql", "kingbasees", "dm8"],
        )
        resp = sql_diagnose(req)
        assert len(resp.tables) == 2
        assert len(resp.functions) >= 3  # TOP, GETDATE, ISNULL
        assert len(resp.joins) == 1
        assert resp.summary.total_objects > 0

    def test_minimal_sql_extracts_nothing(self):
        """SQL with only whitespace produces empty results."""
        req = DiagnoseRequest(
            sql="SELECT 1",  # minimal valid SQL, extracts no tables/functions/joins
            db_types=["mssql"],
        )
        resp = sql_diagnose(req)
        assert resp.tables == []
        assert resp.functions == []
        assert resp.joins == []

    def test_single_db_type(self):
        req = DiagnoseRequest(
            sql="SELECT GETDATE() FROM users",
            db_types=["dm8"],
        )
        resp = sql_diagnose(req)
        assert len(resp.db_types) == 1
        # GETDATE should have some compatibility info for dm8
        funcs = [f for f in resp.functions if f.name == "GETDATE"]
        assert len(funcs) == 1

    def test_response_structure_valid(self):
        """All response fields should be present and well-formed."""
        req = DiagnoseRequest(
            sql="SELECT id FROM users JOIN orders ON users.id = orders.uid",
            db_types=["mssql", "kingbasees"],
        )
        resp = sql_diagnose(req)
        # Check all top-level fields exist
        assert hasattr(resp, "sql")
        assert hasattr(resp, "db_types")
        assert hasattr(resp, "tables")
        assert hasattr(resp, "columns")
        assert hasattr(resp, "functions")
        assert hasattr(resp, "joins")
        assert hasattr(resp, "summary")
        # Summary structure
        assert hasattr(resp.summary, "total_objects")
        assert hasattr(resp.summary, "tables")
        assert hasattr(resp.summary, "functions")
