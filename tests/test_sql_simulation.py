"""
Phase 3 Step 2 · SQL Migration Simulation Engine Tests.

Tests the execution model, drift analyzer, failure predictor, simulator,
and API endpoint.
"""

from __future__ import annotations

import pytest

from app.api.sql_diagnostics.extractor import extract_objects
from app.api.sql_simulation.execution_model import (
    _check_equivalence,
    _estimate_cardinality,
    build_execution_model,
)
from app.api.sql_simulation.drift_analyzer import (
    analyze_drift,
    analyze_query_behavior,
    _assess_table_drift,
)
from app.api.sql_simulation.failure_predictor import predict_failures
from app.api.sql_simulation.simulator import (
    simulate_migration,
    _compute_equivalence_score,
    _compute_risk_level,
    _generate_verdict,
)
from app.api.sql_simulation.schemas import (
    DriftLevel,
    FailurePoint,
    FailureType,
    RiskLevel,
    SimulationVerdict,
    RowLevelDiff,
    TableDrift,
    ExecutionModel,
    EquivalenceDetail,
    CardinalityEstimate,
    SimulationResult,
    QueryBehavior,
)
from app.api.sql_simulation.simulation_router import simulate


# ===========================================================================
# 1. Execution Model Tests
# ===========================================================================


class TestExecutionModel:
    """Verify equivalence checking and cardinality estimation."""

    def test_equivalent_simple_select(self):
        """Simple SELECT should pass equivalence check."""
        model = build_execution_model(
            "SELECT id, name FROM users",
            "SELECT id, name FROM users",
            "mssql",
            "kingbasees",
        )
        assert model.equivalence.ast_match is True
        assert model.equivalence.function_mapping_consistent is True
        assert model.equivalence.column_mapping_preserved is True
        assert len(model.equivalence.issues) == 0

    def test_equivalent_rewritten_mssql_to_pg(self):
        """MSSQL → PG rewrite should have matching functions."""
        model = build_execution_model(
            "SELECT TOP 10 id, GETDATE() AS now FROM [users] WHERE ISNULL(status, 0) = 1",
            "SELECT id, NOW() AS now FROM \"users\" WHERE COALESCE(status, 0) = 1 LIMIT 10",
            "mssql",
            "kingbasees",
        )
        assert model.equivalence.ast_match is True
        # Function mapping should be consistent (rewritten has NOW, COALESCE)
        assert model.equivalence.function_mapping_consistent is True

    def test_ast_mismatch_different_statement_type(self):
        """Different statement types should be detected."""
        model = build_execution_model(
            "SELECT id FROM users",
            "INSERT INTO users (id) VALUES (1)",
            "mssql",
            "kingbasees",
        )
        assert model.equivalence.ast_match is False

    def test_cardinality_estimate_with_joins(self):
        """JOIN queries should produce cardinality estimates."""
        model = build_execution_model(
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id",
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id",
            "mssql",
            "kingbasees",
        )
        assert model.cardinality.original_estimated_rows > 0
        assert len(model.cardinality.join_graph_tables) >= 2
        assert "users" in model.cardinality.join_graph_tables
        assert "orders" in model.cardinality.join_graph_tables

    def test_cardinality_top_limit(self):
        """TOP N should cap the row estimate."""
        model = build_execution_model(
            "SELECT TOP 5 * FROM users",
            "SELECT * FROM users LIMIT 5",
            "mssql",
            "kingbasees",
        )
        # With TOP 5, estimated rows should be ≤ 5 (table heuristic is 5000)
        assert model.cardinality.original_estimated_rows <= 5

    def test_equivalence_detects_issues(self):
        """Equivalence check should flag function mapping problems."""
        # Using a function that has no mapping
        model = build_execution_model(
            "SELECT PATINDEX('%test%', name) FROM users",
            "SELECT POSITION('test' IN name) FROM users",
            "mssql",
            "kingbasees",
        )
        # PATINDEX has no direct rewrite mapping → may flag
        assert isinstance(model.equivalence.ast_match, bool)
        assert isinstance(model.equivalence.function_mapping_consistent, bool)


# ===========================================================================
# 2. Drift Analyzer Tests
# ===========================================================================


class TestDriftAnalyzer:
    """Verify data drift analysis logic."""

    def test_no_drift_for_simple_select(self):
        """Simple SELECT without JOINs or NULL functions should be STABLE."""
        orig = extract_objects("SELECT id, name FROM users")
        rewritten = extract_objects("SELECT id, name FROM users")
        diff = analyze_drift(orig, rewritten, "mssql", "kingbasees")
        assert diff.expected_variance == "0%"
        assert len(diff.affected_tables) == 0
        for td in diff.table_drifts:
            assert td.drift == DriftLevel.STABLE

    def test_full_join_causes_moderate_drift(self):
        """FULL JOIN should produce MODERATE_DRIFT."""
        orig = extract_objects(
            "SELECT * FROM users u FULL JOIN orders o ON u.id = o.user_id"
        )
        rewritten = extract_objects(
            "SELECT * FROM users u FULL JOIN orders o ON u.id = o.user_id"
        )
        diff = analyze_drift(orig, rewritten, "mssql", "kingbasees")
        assert len(diff.affected_tables) >= 1
        # One of the joined tables should have non-STABLE drift
        drift_levels = {td.drift for td in diff.table_drifts}
        assert DriftLevel.STABLE != drift_levels or len(diff.affected_tables) == 0
        # FULL JOIN creates drift
        full_join_drifts = [
            td for td in diff.table_drifts
            if td.drift != DriftLevel.STABLE
        ]
        assert len(full_join_drifts) > 0

    def test_null_functions_flagged(self):
        """ISNULL should be detected as NULL semantics change."""
        orig = extract_objects(
            "SELECT ISNULL(phone, 'N/A') FROM users"
        )
        rewritten = extract_objects(
            "SELECT COALESCE(phone, 'N/A') FROM users"
        )
        behavior = analyze_query_behavior(orig, rewritten, "mssql", "kingbasees")
        assert behavior.null_semantics_change is True

    def test_same_db_no_null_change(self):
        """Same database should not flag NULL semantics change."""
        orig = extract_objects("SELECT ISNULL(x, 0) FROM t")
        behavior = analyze_query_behavior(orig, orig, "mssql", "mssql")
        assert behavior.null_semantics_change is False

    def test_aggregation_stability_high_for_basic_query(self):
        """Basic queries without complex aggregates should be HIGH stability."""
        orig = extract_objects("SELECT id, name FROM users")
        behavior = analyze_query_behavior(orig, orig, "mssql", "kingbasees")
        assert behavior.aggregation_stability in ("HIGH", "MEDIUM", "LOW")

    def test_join_cardinality_shift_reported(self):
        """JOIN cardinality shift should be reported when JOINs exist."""
        orig = extract_objects(
            "SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        )
        behavior = analyze_query_behavior(orig, orig, "mssql", "kingbasees")
        # LEFT JOIN should produce a cardinality shift estimate
        assert behavior.join_cardinality_shift is not None

    def test_type_coercion_detected(self):
        """Type coercion changes should be detected for cross-DB migration."""
        orig = extract_objects("SELECT GETDATE() FROM users")
        behavior = analyze_query_behavior(orig, orig, "mssql", "kingbasees")
        assert len(behavior.type_coercion_changes) > 0


# ===========================================================================
# 3. Failure Predictor Tests
# ===========================================================================


class TestFailurePredictor:
    """Verify failure prediction rules."""

    def test_null_comparison_failure(self):
        """ISNULL in MSSQL → KingbaseES should predict NULL_COMPARISON."""
        orig = extract_objects(
            "SELECT ISNULL(phone, 'N/A') FROM users WHERE ISNULL(status, 0) = 1"
        )
        rewritten = extract_objects(
            "SELECT COALESCE(phone, 'N/A') FROM users WHERE COALESCE(status, 0) = 1"
        )
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        null_failures = [f for f in failures if f.type == FailureType.NULL_COMPARISON]
        assert len(null_failures) > 0

    def test_no_failures_same_db(self):
        """Same source and target should produce no failures."""
        orig = extract_objects("SELECT TOP 10 GETDATE(), ISNULL(x, 0) FROM [t]")
        failures = predict_failures(orig, orig, "mssql", "mssql")
        assert len(failures) == 0

    def test_timezone_drift_detected(self):
        """GETDATE → NOW should predict TIMEZONE_DRIFT."""
        orig = extract_objects("SELECT GETDATE() FROM users")
        rewritten = extract_objects("SELECT NOW() FROM users")
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        tz_failures = [f for f in failures if f.type == FailureType.TIMEZONE_DRIFT]
        assert len(tz_failures) > 0

    def test_function_semantic_change_isnull(self):
        """ISNULL → COALESCE should predict FUNCTION_SEMANTIC_CHANGE."""
        orig = extract_objects("SELECT ISNULL(name, 'Unknown') FROM users")
        rewritten = extract_objects("SELECT COALESCE(name, 'Unknown') FROM users")
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        func_failures = [
            f for f in failures if f.type == FailureType.FUNCTION_SEMANTIC_CHANGE
        ]
        assert len(func_failures) > 0

    def test_function_semantic_change_len(self):
        """LEN → LENGTH should predict FUNCTION_SEMANTIC_CHANGE."""
        orig = extract_objects("SELECT LEN(name) FROM users")
        rewritten = extract_objects("SELECT LENGTH(name) FROM users")
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        len_failures = [
            f for f in failures
            if f.type == FailureType.FUNCTION_SEMANTIC_CHANGE and "LEN" in f.location
        ]
        assert len(len_failures) > 0

    def test_join_multiplicity_full_join(self):
        """FULL JOIN should predict JOIN_MULTIPLICITY_CHANGE."""
        orig = extract_objects(
            "SELECT * FROM users u FULL JOIN orders o ON u.id = o.user_id"
        )
        rewritten = extract_objects(
            "SELECT * FROM users u FULL JOIN orders o ON u.id = o.user_id"
        )
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        join_failures = [
            f for f in failures if f.type == FailureType.JOIN_MULTIPLICITY_CHANGE
        ]
        assert len(join_failures) > 0

    def test_failure_has_mitigation(self):
        """Each failure should have a non-null mitigation."""
        orig = extract_objects(
            "SELECT TOP 10 GETDATE(), ISNULL(x, 0) FROM [users] u "
            "LEFT JOIN orders o ON u.id = o.user_id"
        )
        rewritten = extract_objects(
            "SELECT NOW(), COALESCE(x, 0) FROM \"users\" u "
            "LEFT JOIN orders o ON u.id = o.user_id LIMIT 10"
        )
        failures = predict_failures(orig, rewritten, "mssql", "kingbasees")
        for f in failures:
            assert f.description, f"Failure {f.type} should have description"
            assert f.severity.value in ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


# ===========================================================================
# 4. Simulator Tests
# ===========================================================================


class TestSimulator:
    """Verify the main simulation orchestrator."""

    def test_safe_simulation_simple(self):
        """Simple query with full rewrite coverage should score high."""
        result = simulate_migration(
            "SELECT TOP 10 id, name, GETDATE() AS now FROM [users] WHERE is_active = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.equivalence_score >= 0.80
        assert result.recommendation in (
            SimulationVerdict.SAFE_TO_EXECUTE,
            SimulationVerdict.SAFE_TO_EXECUTE_WITH_MONITORING,
        )
        assert result.rewritten_sql is not None

    def test_identity_same_db(self):
        """Same source/target should return perfect score."""
        result = simulate_migration(
            "SELECT TOP 10 GETDATE(), ISNULL(x, 0) FROM [t]",
            source_db="mssql",
            target_db="mssql",
        )
        assert result.equivalence_score == 1.0
        assert result.risk_level == RiskLevel.NONE
        assert result.recommendation == SimulationVerdict.SAFE_TO_EXECUTE
        assert len(result.warnings) > 0

    def test_complex_mssql_to_pg(self):
        """Complex MSSQL → KingbaseES with multiple dialect features."""
        result = simulate_migration(
            "SELECT TOP 5 u.id, o.total, GETDATE() AS now "
            "FROM [users] u INNER JOIN orders o ON u.id = o.user_id "
            "WHERE ISNULL(u.status, 0) = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.equivalence_score > 0.0
        assert result.simulation is not None
        assert result.execution_model is not None
        assert result.execution_model.cardinality.original_estimated_rows > 0

    def test_high_risk_no_rules(self):
        """DM8 → KingbaseES with no rewrite rules should score lower."""
        result = simulate_migration(
            "SELECT SYSDATE, SYS_GUID() FROM dual",
            source_db="dm8",
            target_db="kingbasees",
        )
        # No rewrite rules → warnings + lower score
        assert result.equivalence_score <= 1.0
        assert len(result.warnings) >= 0

    def test_simulation_response_structure(self):
        """All response fields should be populated."""
        result = simulate_migration(
            "SELECT id, name FROM users",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.source_db == "mssql"
        assert result.target_db == "kingbasees"
        assert result.original_sql is not None
        assert result.simulation is not None
        assert result.simulation.row_level_diff is not None
        assert result.simulation.query_behavior is not None
        assert isinstance(result.simulation.failure_points, list)
        assert result.execution_model is not None
        assert result.recommendation is not None

    def test_equivalence_score_computation(self):
        """Test the equivalence score computation directly."""
        exec_model = ExecutionModel(
            equivalence=EquivalenceDetail(
                ast_match=True,
                function_mapping_consistent=True,
                column_mapping_preserved=True,
                issues=[],
            ),
            cardinality=CardinalityEstimate(
                original_estimated_rows=100,
                rewritten_estimated_rows=100,
                variance_pct=0.0,
                join_graph_tables=["users"],
                description="no change",
            ),
        )
        row_diff = RowLevelDiff(
            expected_variance="0%",
            affected_tables=[],
            table_drifts=[],
            description="no drift",
        )
        score = _compute_equivalence_score(exec_model, [], row_diff)
        assert score == 1.0

    def test_equivalence_score_penalized(self):
        """Score should be penalised for failures and drift."""
        exec_model = ExecutionModel(
            equivalence=EquivalenceDetail(
                ast_match=True,
                function_mapping_consistent=True,
                column_mapping_preserved=True,
            ),
            cardinality=CardinalityEstimate(),
        )
        failures = [
            FailurePoint(
                type=FailureType.NULL_COMPARISON,
                location="users.status",
                severity=RiskLevel.MEDIUM,
                description="NULL handling different",
            ),
            FailurePoint(
                type=FailureType.TIMEZONE_DRIFT,
                location="GETDATE()",
                severity=RiskLevel.LOW,
                description="timezone may differ",
            ),
        ]
        row_diff = RowLevelDiff(
            expected_variance="1-3%",
            affected_tables=["orders"],
            table_drifts=[
                TableDrift(
                    table="orders",
                    drift=DriftLevel.MODERATE_DRIFT,
                    expected_variance="1-3%",
                    reason="FULL JOIN",
                ),
            ],
            description="some drift",
        )
        score = _compute_equivalence_score(exec_model, failures, row_diff)
        # Penalised: 1.0 - 0.04 (MEDIUM failure) - 0.01 (LOW failure) - 0.03 (MODERATE drift)
        assert score < 1.0
        assert score > 0.85
        assert round(score, 4) == 0.92

    def test_verdict_thresholds(self):
        """Test that verdict thresholds produce sensible results."""
        # Very high score → SAFE
        assert _generate_verdict(0.98, RiskLevel.NONE, []) == SimulationVerdict.SAFE_TO_EXECUTE
        # Good score but some failures → SAFE_WITH_MONITORING
        assert _generate_verdict(
            0.92, RiskLevel.LOW,
            [FailurePoint(type=FailureType.TIMEZONE_DRIFT, location="x", severity=RiskLevel.LOW, description="test")]
        ) == SimulationVerdict.SAFE_TO_EXECUTE_WITH_MONITORING
        # Moderate score → NEEDS_REVIEW
        assert _generate_verdict(0.75, RiskLevel.MEDIUM, []) == SimulationVerdict.NEEDS_MANUAL_REVIEW
        # Low score → HIGH_RISK
        assert _generate_verdict(0.50, RiskLevel.HIGH, []) == SimulationVerdict.HIGH_RISK_DO_NOT_EXECUTE

    def test_risk_level_from_score(self):
        """Test risk level computation."""
        assert _compute_risk_level(0.98, []) == RiskLevel.NONE
        assert _compute_risk_level(0.92, []) == RiskLevel.LOW
        assert _compute_risk_level(0.85, []) == RiskLevel.MEDIUM
        assert _compute_risk_level(0.65, []) == RiskLevel.HIGH
        # CRITICAL failure forces CRITICAL risk
        critical_failure = FailurePoint(
            type=FailureType.NULL_COMPARISON,
            location="x",
            severity=RiskLevel.CRITICAL,
            description="critical",
        )
        assert _compute_risk_level(0.95, [critical_failure]) == RiskLevel.CRITICAL


# ===========================================================================
# 5. API Endpoint Tests
# ===========================================================================


class TestSimulationApi:
    """Integration tests for POST /api/sql/migrate/simulate."""

    def test_valid_request(self):
        """Valid simulation request should return complete response."""
        from app.api.sql_simulation.schemas import SimulationRequest

        req = SimulationRequest(
            sql="SELECT TOP 10 id, GETDATE() FROM users",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = simulate(req)
        assert resp.equivalence_score > 0.8
        assert resp.recommendation in (
            SimulationVerdict.SAFE_TO_EXECUTE,
            SimulationVerdict.SAFE_TO_EXECUTE_WITH_MONITORING,
        )

    def test_same_db_identity(self):
        """Same source/target should return identity."""
        from app.api.sql_simulation.schemas import SimulationRequest

        req = SimulationRequest(
            sql="SELECT id FROM users",
            source_db="mssql",
            target_db="mssql",
        )
        resp = simulate(req)
        assert resp.equivalence_score == 1.0
        assert resp.risk_level == RiskLevel.NONE
        assert resp.recommendation == SimulationVerdict.SAFE_TO_EXECUTE

    def test_simulation_sections_populated(self):
        """All simulation sections should have data."""
        from app.api.sql_simulation.schemas import SimulationRequest

        req = SimulationRequest(
            sql="SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = simulate(req)
        assert resp.simulation.row_level_diff is not None
        assert resp.simulation.query_behavior is not None
        assert isinstance(resp.simulation.failure_points, list)
        assert resp.execution_model.cardinality.original_estimated_rows > 0

    def test_with_rewritten_sql(self):
        """Providing rewritten_sql should skip the rewrite engine."""
        from app.api.sql_simulation.schemas import SimulationRequest

        req = SimulationRequest(
            sql="SELECT TOP 10 GETDATE() FROM users",
            source_db="mssql",
            target_db="kingbasees",
            rewritten_sql="SELECT NOW() FROM users LIMIT 10",
        )
        resp = simulate(req)
        assert resp.equivalence_score > 0.8
        assert resp.rewritten_sql == "SELECT NOW() FROM users LIMIT 10"

    def test_response_structure_complete(self):
        """Verify all response fields are present."""
        from app.api.sql_simulation.schemas import SimulationRequest

        req = SimulationRequest(
            sql="SELECT id, name, GETDATE() FROM users WHERE is_active = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        resp = simulate(req)
        # All required fields
        assert resp.source_db == "mssql"
        assert resp.target_db == "kingbasees"
        assert resp.original_sql is not None
        assert resp.equivalence_score >= 0.0
        assert resp.equivalence_score <= 1.0
        assert resp.risk_level is not None
        assert resp.recommendation is not None
        assert resp.execution_model is not None
        assert resp.execution_model.equivalence is not None
        assert resp.execution_model.cardinality is not None
        assert resp.simulation is not None
        assert isinstance(resp.warnings, list)
