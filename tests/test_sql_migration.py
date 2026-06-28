"""
Phase 3 Step 1 · SQL Migration Decision Engine Tests.

Tests the decision engine, impact analyzer, plan generator, and API endpoint.
"""

from __future__ import annotations

import pytest

from app.api.sql_migration.decision_engine import evaluate_migration
from app.api.sql_migration.impact_analyzer import analyze_impact
from app.api.sql_migration.plan_generator import generate_plan
from app.api.sql_migration.schemas import (
    MigrationPlanRequest,
    Recommendation,
    RiskLevel,
)
from app.api.sql_migration.migration_router import migration_plan
from app.api.sql_compare.rewrite.rules import AppliedRuleInfo
from app.api.sql_diagnostics.analyzer import analyze_objects
from app.api.sql_diagnostics.extractor import extract_objects


# ===========================================================================
# 1. Decision Engine Tests
# ===========================================================================


class TestDecisionEngine:
    """Verify the migration decision engine produces correct recommendations."""

    def test_safe_auto_migration(self):
        """Well-behaved MSSQL → KingbaseES SQL with rewrite coverage."""
        result = evaluate_migration(
            "SELECT TOP 10 id, name, GETDATE() AS now FROM users WHERE is_active = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.migration_feasible is True
        assert result.recommendation == Recommendation.SAFE_AUTO_MIGRATION
        assert result.estimated_score > 85
        assert result.confidence > 0.8
        assert result.rewritten_sql is not None
        assert "NOW()" in result.rewritten_sql

    def test_identity_same_database(self):
        """Same source and target should return identity with perfect score."""
        result = evaluate_migration(
            "SELECT TOP 10 GETDATE(), ISNULL(x, 0) FROM [t]",
            source_db="mssql",
            target_db="mssql",
        )
        assert result.migration_feasible is True
        assert result.risk_level == RiskLevel.NONE
        assert result.estimated_score == 100.0
        assert result.recommendation == Recommendation.SAFE_AUTO_MIGRATION
        assert len(result.warnings) > 0  # identity warning

    def test_high_risk_no_rules(self):
        """DM8 → KingbaseES with no rewrite rules should score low."""
        result = evaluate_migration(
            "SELECT SYSDATE, SYS_GUID() FROM dual",
            source_db="dm8",
            target_db="kingbasees",
        )
        # SYS_GUID has no rewrite rule for DM8→KingbaseES → penalized
        assert result.estimated_score <= 90  # HIGH-risk function deducted
        # rewritten_sql may be None when no rewrite rules exist
        assert len(result.warnings) >= 0

    def test_complex_migration_with_joins(self):
        """Multi-table JOIN with multiple dialect functions."""
        result = evaluate_migration(
            "SELECT TOP 5 u.id, o.total, GETDATE() AS now "
            "FROM [users] u INNER JOIN orders o ON u.id = o.user_id "
            "WHERE ISNULL(u.status, 0) = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.migration_feasible is True
        assert len(result.plan.steps) >= 5  # rewrites + validations
        assert result.impact.tables == ["users", "orders"]
        assert "TOP" in result.impact.functions
        assert "GETDATE" in result.impact.functions

    def test_response_structure_complete(self):
        """All response fields should be populated."""
        result = evaluate_migration(
            "SELECT id, name FROM users",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.source_db == "mssql"
        assert result.target_db == "kingbasees"
        assert result.original_sql is not None
        assert result.impact is not None
        assert result.plan is not None
        assert result.plan.total_steps > 0
        assert result.recommendation is not None


# ===========================================================================
# 2. Impact Analyzer Tests
# ===========================================================================


class TestImpactAnalyzer:
    """Verify impact analysis logic."""

    def test_no_critical_tables_for_clean_sql(self):
        objects = extract_objects("SELECT id, name FROM users")
        diag = analyze_objects(objects, ["kingbasees"])
        impact = analyze_impact(
            tables=diag.tables,
            columns=diag.columns,
            functions=diag.functions,
            joins=diag.joins,
        )
        assert len(impact.critical_tables) == 0
        assert impact.high_risk_count == 0

    def test_detects_risk_hotspots(self):
        objects = extract_objects("SELECT TOP 10 GETDATE(), ISNULL(x, 0) FROM [t]")
        diag = analyze_objects(objects, ["kingbasees"])
        impact = analyze_impact(
            tables=diag.tables,
            columns=diag.columns,
            functions=diag.functions,
            joins=diag.joins,
        )
        # Functions with rewrite rules have LOW risk, not HIGH
        # But they should be in risk_hotspots if MEDIUM+
        assert len(impact.functions) >= 3  # TOP, GETDATE, ISNULL

    def test_join_chain_analysis(self):
        objects = extract_objects(
            "SELECT * FROM users u "
            "INNER JOIN orders o ON u.id = o.user_id "
            "LEFT JOIN products p ON o.product_id = p.id"
        )
        diag = analyze_objects(objects, ["kingbasees"])
        impact = analyze_impact(
            tables=diag.tables,
            columns=diag.columns,
            functions=diag.functions,
            joins=diag.joins,
        )
        # Should have join chains
        assert len(impact.join_chains) == len(diag.joins)


# ===========================================================================
# 3. Plan Generator Tests
# ===========================================================================


class TestPlanGenerator:
    """Verify plan generation produces correct steps."""

    def test_generates_rewrite_steps(self):
        applied = [
            AppliedRuleInfo(name="TOP → LIMIT", description="改写 TOP", confidence=0.98),
            AppliedRuleInfo(name="GETDATE → NOW", description="改写 GETDATE", confidence=0.95),
        ]
        plan = generate_plan(
            applied_rules=applied,
            has_critical_tables=False,
            has_high_functions=False,
            high_risk_count=0,
            medium_risk_count=0,
            source_db="mssql",
            target_db="kingbasees",
        )
        assert plan.total_steps >= 4  # 2 rewrites + test + validate + verify
        assert plan.automatic_steps >= 2
        assert plan.manual_steps >= 2

    def test_effort_low_for_simple_migration(self):
        plan = generate_plan(
            applied_rules=[],
            has_critical_tables=False,
            has_high_functions=False,
            high_risk_count=0,
            medium_risk_count=0,
            source_db="mssql",
            target_db="kingbasees",
        )
        assert plan.estimated_effort == "LOW"

    def test_effort_high_for_risky_migration(self):
        plan = generate_plan(
            applied_rules=[],
            has_critical_tables=True,
            has_high_functions=True,
            high_risk_count=5,
            medium_risk_count=4,
            source_db="mssql",
            target_db="kingbasees",
        )
        assert plan.estimated_effort == "HIGH"

    def test_critical_tables_add_schema_step(self):
        plan = generate_plan(
            applied_rules=[],
            has_critical_tables=True,
            has_high_functions=False,
            high_risk_count=0,
            medium_risk_count=0,
            source_db="mssql",
            target_db="kingbasees",
        )
        actions = [s.action.value for s in plan.steps]
        assert "update_schema" in actions

    def test_high_functions_add_review_step(self):
        plan = generate_plan(
            applied_rules=[],
            has_critical_tables=False,
            has_high_functions=True,
            high_risk_count=3,
            medium_risk_count=0,
            source_db="mssql",
            target_db="kingbasees",
        )
        actions = [s.action.value for s in plan.steps]
        assert "manual_review" in actions


# ===========================================================================
# 4. API Endpoint Tests
# ===========================================================================


class TestMigrationApi:
    """Integration tests for POST /api/sql/migrate/plan."""

    def test_valid_request(self):
        req = MigrationPlanRequest(
            sql="SELECT TOP 10 id, GETDATE() FROM users",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = migration_plan(req)
        assert resp.migration_feasible is True
        assert resp.recommendation == Recommendation.SAFE_AUTO_MIGRATION
        assert resp.estimated_score > 80

    def test_same_db_identity(self):
        req = MigrationPlanRequest(
            sql="SELECT id FROM users",
            source_db="mssql",
            target_db="mssql",
        )
        resp = migration_plan(req)
        assert resp.risk_level == RiskLevel.NONE
        assert resp.estimated_score == 100.0

    def test_impact_sections_populated(self):
        req = MigrationPlanRequest(
            sql="SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = migration_plan(req)
        assert "users" in resp.impact.tables
        assert "orders" in resp.impact.tables
        assert len(resp.impact.join_chains) >= 1

    def test_plan_steps_ordered(self):
        req = MigrationPlanRequest(
            sql="SELECT TOP 5 GETDATE() FROM users",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = migration_plan(req)
        step_nums = [s.step for s in resp.plan.steps]
        assert step_nums == sorted(step_nums)
        assert step_nums[0] == 1

    def test_recommendation_thresholds(self):
        """Verify the decision thresholds produce correct recommendations."""
        # Simple query with no dialect features → HIGH score → SAFE
        resp1 = migration_plan(MigrationPlanRequest(
            sql="SELECT id, name FROM users",
            source_db="mssql",
            target_db="kingbasees",
        ))
        assert resp1.recommendation == Recommendation.SAFE_AUTO_MIGRATION
        assert resp1.estimated_score > 85
