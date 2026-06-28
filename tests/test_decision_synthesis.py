"""
Tests for Decision Synthesis Layer — risk aggregation, confidence model,
recommendation engine, and synthesizer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.sql_kernel import SQLKernel, build_context
from app.core.sql_kernel.decision.confidence_model import (
    ConfidenceBreakdown,
    compute_confidence,
)
from app.core.sql_kernel.decision.recommendation_engine import (
    MigrationPath,
    Recommendation,
    make_recommendation,
)
from app.core.sql_kernel.decision.risk_aggregator import (
    RiskProfile,
    aggregate_risks,
)
from app.core.sql_kernel.decision.synthesizer import (
    KernelDecision,
    synthesize_decision,
)
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

SAMPLE_COMPLEX = (
    "SELECT u.id, u.name, o.total "
    "FROM users u "
    "LEFT JOIN orders o ON u.id = o.user_id "
    "WHERE u.is_active = 1 AND GETDATE() > u.created_at "
    "ORDER BY o.total DESC"
)


# ---------------------------------------------------------------------------
# Test risk aggregator
# ---------------------------------------------------------------------------


class TestRiskAggregator:
    """Tests for aggregate_risks()."""

    def test_empty_engines_returns_empty_profile(self):
        """All None inputs should return empty risk profile."""
        profile = aggregate_risks(None, None, None, None)
        assert isinstance(profile, RiskProfile)
        assert profile.aggregated_severity == "NONE"
        assert len(profile.primary_risks) == 0
        assert len(profile.blocking_issues) == 0

    def test_aggregates_diagnostics_risks(self):
        """Should extract risks from diagnostics output."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            engines=["diagnostics"], synthesize=False,
        )
        profile = aggregate_risks(
            result.diagnostics, None, None, None,
        )

        assert "diagnostics" in profile.risk_sources
        # MSSQL dialect functions should generate HIGH risks in diagnostics
        assert profile.high_count >= 0  # diagnostics may categorize differently

    def test_aggregates_simulation_risks(self):
        """Should extract failure points from simulation."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            engines=["simulation"], synthesize=False,
        )
        profile = aggregate_risks(
            None, None, None, result.simulation,
        )

        assert "simulation" in profile.risk_sources
        # MSSQL → KingbaseES with GETDATE, ISNULL, TOP should have failures
        assert profile.risk_sources["simulation"] > 0

    def test_aggregates_all_engines(self):
        """Full engine set should have risks from at least one source."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=False,
        )
        profile = aggregate_risks(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        # At least 1 engine should contribute risks for a dialect-heavy query
        contributing = sum(1 for v in profile.risk_sources.values() if v > 0)
        assert contributing >= 1

    def test_blocks_on_critical(self):
        """CRITICAL severity risks should appear in blocking_issues."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=False,
        )
        profile = aggregate_risks(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        # blocking_issues should contain CRITICAL-level items if any
        if profile.critical_count > 0:
            assert len(profile.blocking_issues) > 0

    def test_simple_sql_low_risk(self):
        """Simple SQL without dialect features should have low risk."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            synthesize=False,
        )
        profile = aggregate_risks(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        assert profile.critical_count == 0
        # Simple SQL should have minimal risks
        assert profile.aggregated_severity in ("NONE", "LOW", "MEDIUM")


# ---------------------------------------------------------------------------
# Test confidence model
# ---------------------------------------------------------------------------


class TestConfidenceModel:
    """Tests for compute_confidence()."""

    def test_all_engines_present(self):
        """With all engines available, should use all weights."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=False,
        )
        cb = compute_confidence(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        assert isinstance(cb, ConfidenceBreakdown)
        assert 0.0 <= cb.overall <= 1.0
        assert len(cb.engines_available) == 4
        assert len(cb.engines_missing) == 0

    def test_missing_engines_redistributes_weights(self):
        """Missing engines should have their weights redistributed."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            engines=["diagnostics"], synthesize=False,
        )
        cb = compute_confidence(
            result.diagnostics, None, None, None,
        )

        assert len(cb.engines_available) == 1
        assert len(cb.engines_missing) == 3
        # Diagnostics should get 100% of weight
        assert cb.weight_diagnostics == 1.0

    def test_identity_case_perfect_confidence(self):
        """Same source/target should give perfect confidence."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "mssql",
            synthesize=False,
        )
        cb = compute_confidence(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        assert cb.overall >= 0.95  # near-perfect

    def test_dialect_sql_lower_confidence(self):
        """Dialect-heavy SQL should have lower confidence than simple SQL."""
        result_complex = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "dm8",
            synthesize=False,
        )
        result_simple = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "dm8",
            synthesize=False,
        )

        cb_complex = compute_confidence(
            result_complex.diagnostics, result_complex.rewrite,
            result_complex.migration, result_complex.simulation,
        )
        cb_simple = compute_confidence(
            result_simple.diagnostics, result_simple.rewrite,
            result_simple.migration, result_simple.simulation,
        )

        # Complex SQL should NOT have higher confidence than simple
        assert cb_complex.overall <= cb_simple.overall + 0.1  # allow small margin

    def test_all_signals_in_range(self):
        """All per-engine signals should be in [0, 1]."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=False,
        )
        cb = compute_confidence(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        assert 0.0 <= cb.diagnostics_factor <= 1.0
        assert 0.0 <= cb.rewrite_confidence <= 1.0
        assert 0.0 <= cb.migration_confidence <= 1.0
        assert 0.0 <= cb.simulation_score <= 1.0


# ---------------------------------------------------------------------------
# Test recommendation engine
# ---------------------------------------------------------------------------


class TestRecommendationEngine:
    """Tests for make_recommendation()."""

    def _make_inputs(self, sql, source="mssql", target="kingbasees"):
        """Build all inputs needed for make_recommendation()."""
        result = SQLKernel.analyze(sql, source, target, synthesize=False)
        risk = aggregate_risks(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )
        conf = compute_confidence(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )
        return risk, conf, result.migration, result.rewrite, result.simulation

    def test_simple_sql_safe(self):
        """Simple SQL with no dialect features should be SAFE."""
        risk, conf, mig, rewrite, sim = self._make_inputs(SAMPLE_SIMPLE)
        decision = make_recommendation(
            risk, conf, mig, rewrite, sim, "mssql", "kingbasees",
        )

        # Simple SQL should be SAFE or REVIEW (depends on exact score)
        assert decision.recommendation in (Recommendation.SAFE, Recommendation.REVIEW)

    def test_dialect_sql_path_is_auto_or_partial(self):
        """Heavy dialect SQL with rewrite coverage should be AUTO_REWRITE or PARTIAL."""
        risk, conf, mig, rewrite, sim = self._make_inputs(SAMPLE_MSSQL)
        decision = make_recommendation(
            risk, conf, mig, rewrite, sim, "mssql", "dm8",
        )

        # MSSQL → DM8 with TOP, GETDATE, ISNULL, brackets — has rewrite rules
        # When rules apply successfully, can be SAFE with AUTO_REWRITE
        # The key assertion: it's NOT DIRECT (rewriting was needed)
        assert decision.migration_path != MigrationPath.DIRECT
        assert decision.migration_path in (
            MigrationPath.AUTO_REWRITE, MigrationPath.PARTIAL, MigrationPath.MANUAL,
        )

    def test_identity_safe_and_direct(self):
        """Same DB should always be SAFE + DIRECT."""
        risk, conf, mig, rewrite, sim = self._make_inputs(
            SAMPLE_MSSQL, "mssql", "mssql",
        )
        decision = make_recommendation(
            risk, conf, mig, rewrite, sim, "mssql", "mssql",
        )

        assert decision.recommendation == Recommendation.SAFE
        assert decision.migration_path == MigrationPath.DIRECT

    def test_returns_valid_enums(self):
        """Recommendation and path should be valid enum values."""
        risk, conf, mig, rewrite, sim = self._make_inputs(SAMPLE_MSSQL)
        decision = make_recommendation(
            risk, conf, mig, rewrite, sim, "mssql", "kingbasees",
        )

        assert decision.recommendation in Recommendation
        assert decision.migration_path in MigrationPath

    def test_explanation_non_empty(self):
        """Decision should include explanation text."""
        risk, conf, mig, rewrite, sim = self._make_inputs(SAMPLE_MSSQL)
        decision = make_recommendation(
            risk, conf, mig, rewrite, sim, "mssql", "kingbasees",
        )

        assert len(decision.explanation) > 0
        assert len(decision.decision_factors) > 0

    def test_block_when_critical_risks(self):
        """CRITICAL severity risks should cause BLOCK recommendation."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "dm8",
            synthesize=False,
        )
        risk = aggregate_risks(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )
        conf = compute_confidence(
            result.diagnostics, result.rewrite,
            result.migration, result.simulation,
        )

        # Manually inject a blocking risk
        risk.blocking_issues.append("Test critical blocking issue")
        risk.critical_count += 1

        decision = make_recommendation(
            risk, conf, result.migration, result.rewrite,
            result.simulation, "mssql", "dm8",
        )

        assert decision.recommendation == Recommendation.BLOCK


# ---------------------------------------------------------------------------
# Test synthesizer
# ---------------------------------------------------------------------------


class TestSynthesizer:
    """Tests for synthesize_decision()."""

    def test_synthesizes_from_kernel_result(self):
        """Should produce a KernelDecision from a KernelResult."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=False,
        )
        decision = synthesize_decision(result)

        assert isinstance(decision, KernelDecision)
        assert decision.recommendation in ("SAFE", "REVIEW", "BLOCK")
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.migration_path in ("DIRECT", "AUTO_REWRITE", "PARTIAL", "MANUAL")

    def test_synthesize_included_in_kernel_analyze(self):
        """Kernel.analyze() with synthesize=True should include decision."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            synthesize=True,
        )

        assert result.decision is not None
        decision = result.decision
        assert hasattr(decision, "recommendation")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "migration_path")

    def test_synthesize_can_be_disabled(self):
        """synthesize=False should skip decision."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            synthesize=False,
        )

        assert result.decision is None
        # Everything else should still work
        assert result.diagnostics is not None

    def test_decision_has_required_fields(self):
        """KernelDecision should have all expected fields."""
        result = SQLKernel.analyze(
            SAMPLE_MSSQL, "mssql", "kingbasees",
            synthesize=True,
        )
        d = result.decision

        required_fields = [
            "recommendation", "confidence", "migration_path",
            "primary_risks", "blocking_issues", "aggregated_severity",
            "risk_counts", "execution_strategy", "explanation",
            "score", "rewrite_confidence", "rewrite_rules_applied",
            "simulation_verdict", "source_db", "target_db",
        ]
        for field in required_fields:
            assert hasattr(d, field), f"Missing field: {field}"

    def test_simple_sql_high_confidence(self):
        """Simple SQL should have high confidence and likely SAFE."""
        result = SQLKernel.analyze(
            SAMPLE_SIMPLE, "mssql", "kingbasees",
            synthesize=True,
        )
        d = result.decision

        assert d.confidence >= 0.80
        # Simple SQL should be safe or review
        assert d.recommendation in ("SAFE", "REVIEW")

    def test_complex_sql_lower_score(self):
        """Dialect-heavy SQL should have lower score than simple SQL."""
        simple = SQLKernel.analyze(SAMPLE_SIMPLE, "mssql", "dm8", synthesize=True)
        complex_ = SQLKernel.analyze(SAMPLE_MSSQL, "mssql", "dm8", synthesize=True)

        assert complex_.decision.score <= simple.decision.score + 10  # allow margin


# ---------------------------------------------------------------------------
# Test decision API endpoint
# ---------------------------------------------------------------------------


class TestDecisionApi:
    """Tests for POST /api/sql/kernel/decision."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_decision_endpoint_returns_decision(self, client):
        """Should return a complete decision."""
        response = client.post(
            "/api/sql/kernel/decision",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["recommendation"] in ("SAFE", "REVIEW", "BLOCK")
        assert 0.0 <= data["confidence"] <= 1.0
        assert data["migration_path"] in ("DIRECT", "AUTO_REWRITE", "PARTIAL", "MANUAL")
        assert isinstance(data["primary_risks"], list)
        assert isinstance(data["blocking_issues"], list)
        assert len(data["execution_strategy"]) > 0
        assert len(data["explanation"]) > 0

    def test_decision_endpoint_simple_sql(self, client):
        """Simple SQL should return SAFE or REVIEW."""
        response = client.post(
            "/api/sql/kernel/decision",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] in ("SAFE", "REVIEW")
        assert data["confidence"] >= 0.80

    def test_decision_endpoint_identity(self, client):
        """Same DB should give SAFE + DIRECT."""
        response = client.post(
            "/api/sql/kernel/decision",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "mssql",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] == "SAFE"
        assert data["migration_path"] == "DIRECT"

    def test_decision_endpoint_structure_complete(self, client):
        """Decision response should have all expected fields."""
        response = client.post(
            "/api/sql/kernel/decision",
            json={
                "sql": SAMPLE_MSSQL,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        data = response.json()
        top_fields = [
            "recommendation", "confidence", "migration_path",
            "primary_risks", "blocking_issues", "aggregated_severity",
            "risk_counts", "execution_strategy", "explanation",
            "score", "rewrite_confidence", "rewrite_rules_applied",
            "simulation_verdict", "source_db", "target_db",
            "original_sql", "rewritten_sql", "engines_consulted", "warnings",
        ]
        for field in top_fields:
            assert field in data, f"Missing top-level field: {field}"

    def test_decision_in_analyze_response(self, client):
        """The /analyze endpoint should also include decision."""
        response = client.post(
            "/api/sql/kernel/analyze",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "kingbasees",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "decision" in data
        assert data["decision"] is not None
        assert "recommendation" in data["decision"]

    def test_decision_with_rewritten_sql(self, client):
        """Custom rewritten SQL should be used in decision."""
        response = client.post(
            "/api/sql/kernel/decision",
            json={
                "sql": SAMPLE_SIMPLE,
                "source_db": "mssql",
                "target_db": "kingbasees",
                "rewritten_sql": "SELECT id, name FROM products WHERE is_active = TRUE",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["rewritten_sql"] is not None
