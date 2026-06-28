"""
Tests for SQL Intelligence Kernel — unified semantic context and orchestrator.

Verifies:
  - Context builder produces correct unified context
  - SQLKernel.analyze() returns all engine results
  - Kernel works with subset of engines
  - Identity case (same source/target)
  - Backward compat — old engine functions still work
  - Kernel router endpoint
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.sql_kernel import SQLKernel, build_context
from app.core.sql_kernel.semantic_context import KernelResult, SQLSemanticContext
from app.main import app


# ---------------------------------------------------------------------------
# Sample SQL for testing
# ---------------------------------------------------------------------------

SAMPLE_MSSQL = (
    "SELECT TOP 10 id, name, GETDATE() AS current_time "
    "FROM [users] "
    "WHERE ISNULL(status, 0) = 1 "
    "ORDER BY created_at DESC"
)

SAMPLE_SIMPLE = "SELECT id, name FROM products WHERE is_active = 1"


# ---------------------------------------------------------------------------
# Test context builder
# ---------------------------------------------------------------------------


class TestContextBuilder:
    """Tests for build_context() — the single parse entry point."""

    def test_builds_context_with_objects(self):
        """Context should contain extracted tables, columns, functions."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert isinstance(ctx, SQLSemanticContext)
        assert len(ctx.tables) > 0
        assert len(ctx.columns) > 0
        assert len(ctx.functions) > 0
        assert ctx.source_db == "mssql"
        assert ctx.target_db == "kingbasees"
        assert ctx.original_sql == SAMPLE_MSSQL.strip()

    def test_builds_context_with_ast_features(self):
        """Context should contain AST-level features from normalizer."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert ctx.statement_type == "SELECT"
        assert ctx.has_top is True
        assert ctx.limit_value == 10
        assert ctx.has_brackets is True
        assert len(ctx.bracket_idents) > 0
        assert "GETDATE" in ctx.dialect_functions
        assert "TOP" in ctx.dialect_functions

    def test_builds_context_with_isnull(self):
        """Context should extract ISNULL call arguments."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert len(ctx.isnull_calls) > 0
        assert ctx.isnull_calls[0] == ["status", "0"]

    def test_builds_context_same_db_no_rewrite(self):
        """Same DB should not trigger auto-rewrite."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "mssql")

        assert ctx.rewritten_sql is None or ctx.rewritten_sql == ctx.original_sql

    def test_builds_context_cross_db_auto_rewrites(self):
        """Cross-DB should auto-rewrite."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")

        # Should have a rewritten version
        assert ctx.rewritten_sql is not None
        # Should NOT contain MSSQL-specific syntax
        assert "TOP" not in ctx.rewritten_sql.upper()
        assert "GETDATE" not in ctx.rewritten_sql.upper()

    def test_builds_context_respects_rewritten_sql_param(self):
        """Pre-computed rewritten_sql should be used as-is."""
        custom = "SELECT * FROM users LIMIT 10"
        ctx = build_context(
            SAMPLE_MSSQL, "mssql", "kingbasees", rewritten_sql=custom,
        )

        assert ctx.rewritten_sql == custom

    def test_builds_context_simple_sql(self):
        """Simple SQL without dialect features should work."""
        ctx = build_context(SAMPLE_SIMPLE, "mssql", "kingbasees")

        assert ctx.statement_type == "SELECT"
        assert ctx.has_top is False
        assert ctx.has_brackets is False
        assert ctx.getdate_count == 0
        assert len(ctx.tables) > 0

    def test_tables_simple_populated(self):
        """Simple table name list should be populated."""
        ctx = build_context(SAMPLE_SIMPLE, "mssql", "kingbasees")

        assert len(ctx.tables_simple) > 0
        assert any("products" in t.lower() for t in ctx.tables_simple)


# ---------------------------------------------------------------------------
# Test SQLKernel.analyze()
# ---------------------------------------------------------------------------


class TestSQLKernelAnalyze:
    """Tests for SQLKernel.analyze() — the unified orchestrator."""

    def test_analyze_all_stateless_engines(self):
        """Default engines (diagnostics, rewrite, migration, simulation) all run."""
        result = SQLKernel.analyze(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert isinstance(result, KernelResult)
        assert result.diagnostics is not None
        assert result.rewrite is not None
        assert result.migration is not None
        assert result.simulation is not None
        # Score excluded by default (requires DB)
        assert result.score is None

    def test_analyze_specific_engines(self):
        """Should only run requested engines."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            engines=["diagnostics", "rewrite"],
        )

        assert result.diagnostics is not None
        assert result.rewrite is not None
        assert result.migration is None
        assert result.simulation is None
        assert result.score is None
        assert set(result.engines_run) == {"diagnostics", "rewrite"}

    def test_analyze_single_engine(self):
        """Single engine should work."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            engines=["simulation"],
        )

        assert result.simulation is not None
        assert result.diagnostics is None
        assert result.rewrite is None

    def test_analyze_identity_case(self):
        """Same source/target should return identity results."""
        result = SQLKernel.analyze(SAMPLE_MSSQL, "mssql", "mssql")

        assert result.diagnostics is not None
        # Simulation identity case: score = 1.0, risk = NONE
        assert result.simulation is not None

        # Check simulation identity
        sim = result.simulation
        assert hasattr(sim, "equivalence_score")
        assert sim.equivalence_score == 1.0

    def test_analyze_returns_timing(self):
        """KernelResult should include timing info."""
        result = SQLKernel.analyze(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert result.total_time_ms > 0
        assert len(result.engines_run) > 0

    def test_analyze_simple_sql(self):
        """Simple SQL without dialect features should work."""
        result = SQLKernel.analyze(SAMPLE_SIMPLE, "mssql", "kingbasees")

        assert result.diagnostics is not None
        assert result.rewrite is not None
        # Simple SQL should have high migration feasibility
        assert result.migration is not None

    def test_analyze_all_engines_includes_score(self):
        """Explicitly requesting 'score' should include it."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            engines=["diagnostics", "rewrite", "migration", "simulation", "score"],
        )

        # Score will fail without DB, but it should be attempted
        assert "score" in result.engines_run


# ---------------------------------------------------------------------------
# Test backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Original engine functions should still work independently."""

    def test_simulate_migration_still_works(self):
        """Original simulate_migration() should still work."""
        from app.api.sql_simulation.simulator import simulate_migration

        result = simulate_migration(SAMPLE_MSSQL, "mssql", "kingbasees")
        assert result.equivalence_score is not None
        assert result.source_db == "mssql"
        assert result.target_db == "kingbasees"

    def test_evaluate_migration_still_works(self):
        """Original evaluate_migration() should still work."""
        from app.api.sql_migration.decision_engine import evaluate_migration

        result = evaluate_migration(SAMPLE_SIMPLE, "mssql", "kingbasees")
        assert result.migration_feasible is not None
        assert result.source_db == "mssql"

    def test_analyze_objects_still_works(self):
        """Original analyze_objects() should still work."""
        from app.api.sql_diagnostics.analyzer import analyze_objects
        from app.api.sql_diagnostics.extractor import extract_objects

        objects = extract_objects(SAMPLE_SIMPLE)
        analysis = analyze_objects(objects, ["kingbasees"])
        assert analysis.summary.total_objects > 0

    def test_rewrite_sql_still_works(self):
        """Original rewrite_sql() should still work."""
        from app.api.sql_compare.rewrite.engine import rewrite_sql

        result = rewrite_sql(SAMPLE_MSSQL, "mssql", "kingbasees")
        assert result.rewritten_sql is not None
        assert "GETDATE" not in result.rewritten_sql.upper()

    def test_simulate_from_context_works(self):
        """New context-based simulate_from_context() should work."""
        from app.api.sql_simulation.simulator import simulate_from_context

        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")
        result = simulate_from_context(ctx)
        assert result.equivalence_score is not None

    def test_analyze_objects_from_context_works(self):
        """New context-based analyze_objects_from_context() should work."""
        from app.api.sql_diagnostics.analyzer import analyze_objects_from_context

        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")
        result = analyze_objects_from_context(ctx)
        assert result.summary.total_objects > 0

    def test_evaluate_migration_from_context_works(self):
        """New context-based evaluate_migration_from_context() should work."""
        from app.api.sql_migration.decision_engine import evaluate_migration_from_context

        ctx = build_context(SAMPLE_SIMPLE, "mssql", "kingbasees")
        result = evaluate_migration_from_context(ctx)
        assert result.migration_feasible is not None

    def test_rewrite_from_context_works(self):
        """New context-based rewrite_from_context() should work."""
        from app.api.sql_compare.rewrite.engine import rewrite_from_context

        ctx = build_context(SAMPLE_MSSQL, "mssql", "kingbasees")
        result = rewrite_from_context(ctx)
        assert result.rewritten_sql is not None


# ---------------------------------------------------------------------------
# Test kernel router (API endpoint)
# ---------------------------------------------------------------------------


class TestKernelApi:
    """Tests for POST /api/sql/kernel/analyze."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_analyze_endpoint_returns_all_engines(self, client):
        """Default request should return diagnostics, rewrite, migration, simulation."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["diagnostics"] is not None
        assert data["rewrite"] is not None
        assert data["migration"] is not None
        assert data["simulation"] is not None
        assert data["score"] is None  # excluded by default
        assert len(data["engines_run"]) == 4

    def test_analyze_endpoint_specific_engines(self, client):
        """Requesting specific engines should only return those."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "kingbasees",
                "engines": ["diagnostics"],
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["diagnostics"] is not None
        assert data["rewrite"] is None
        assert data["migration"] is None
        assert data["simulation"] is None

    def test_analyze_endpoint_identity(self, client):
        """Same source/target should work."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "mssql",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source_db"] == "mssql"
        assert data["target_db"] == "mssql"

    def test_analyze_endpoint_with_rewritten_sql(self, client):
        """Pre-computed rewritten SQL should be accepted."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "kingbasees",
                "rewritten_sql": "SELECT * FROM users LIMIT 10",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["rewritten_sql"] == "SELECT * FROM users LIMIT 10"

    def test_analyze_endpoint_invalid_engine_rejected(self, client):
        """Invalid engine name should return 400."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "kingbasees",
                "engines": ["invalid_engine"],
            },
        )

        assert response.status_code == 400

    def test_analyze_endpoint_response_structure(self, client):
        """Response should have expected top-level fields."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        data = response.json()
        expected_fields = [
            "source_db", "target_db", "original_sql", "rewritten_sql",
            "diagnostics", "rewrite", "score", "migration", "simulation",
            "engines_run", "total_time_ms", "warnings",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    def test_build_context_standalone(self):
        """build_context() should work standalone without kernel."""
        ctx = build_context(SAMPLE_MSSQL, "mssql", "dm8")

        assert ctx.source_db == "mssql"
        assert ctx.target_db == "dm8"
        assert len(ctx.tables) > 0
        assert len(ctx.functions) > 0

    def test_kernel_build_context_static(self):
        """SQLKernel.build_context() static method should work."""
        ctx = SQLKernel.build_context(SAMPLE_MSSQL, "mssql", "kingbasees")

        assert isinstance(ctx, SQLSemanticContext)
        assert ctx.statement_type == "SELECT"
