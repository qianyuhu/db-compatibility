"""
Phase 2 Step 4 · SQL Rewrite Rule Engine Tests.

Tests the declarative rule engine: rule correctness, edge cases,
stability (ordering + confidence), reverse rewriting, and rule structure.
"""

from __future__ import annotations

import math

import pytest

from app.api.sql_compare.rewrite.ast_normalizer import NormalizedAst, normalize
from app.api.sql_compare.rewrite.engine import (
    RewriteResult,
    _validate,
    rewrite_sql,
)
from app.api.sql_compare.rewrite.rules import (
    RULE_REGISTRY,
    AppliedRuleInfo,
    RewriteRule,
    apply_rules,
    compute_overall_confidence,
    get_rules,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _result_contains_rule(result: RewriteResult, rule_name: str) -> bool:
    """Check if a rule with the given name was applied."""
    return any(r.name == rule_name for r in result.rules_applied)


def _get_rule_confidence(result: RewriteResult, rule_name: str) -> float | None:
    """Get the confidence of an applied rule by name."""
    for r in result.rules_applied:
        if r.name == rule_name:
            return r.confidence
    return None


# ===========================================================================
# 1. Rule Correctness — MSSQL → KingbaseES
# ===========================================================================


class TestMssqlToKingbaseEsCorrectness:
    """Verify each MSSQL→KingbaseES rule produces correct output."""

    # -- TOP → LIMIT ----------------------------------------------------------

    def test_top_to_limit(self):
        result = rewrite_sql(
            "SELECT TOP 10 id, name FROM products ORDER BY created_at DESC",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "TOP" not in result.rewritten_sql.upper().split("SELECT")[1]
        assert "LIMIT 10" in result.rewritten_sql
        assert _result_contains_rule(result, "TOP → LIMIT")

    def test_top_to_limit_no_top(self):
        """SQL without TOP should not trigger the TOP→LIMIT rule."""
        result = rewrite_sql(
            "SELECT id, name FROM products WHERE is_active = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert not _result_contains_rule(result, "TOP → LIMIT")

    # -- GETDATE → NOW --------------------------------------------------------

    def test_getdate_to_now(self):
        result = rewrite_sql(
            "SELECT id FROM products WHERE GETDATE() > created_at",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "GETDATE()" not in result.rewritten_sql
        assert "NOW()" in result.rewritten_sql
        assert _result_contains_rule(result, "GETDATE → NOW")

    # -- ISNULL → COALESCE ---------------------------------------------------

    def test_isnull_to_coalesce(self):
        result = rewrite_sql(
            "SELECT id, ISNULL(description, 'N/A') AS desc FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "ISNULL" not in result.rewritten_sql
        assert "COALESCE(description, 'N/A')" in result.rewritten_sql
        assert _result_contains_rule(result, "ISNULL → COALESCE")

    def test_isnull_to_coalesce_multiple(self):
        """Multiple ISNULL calls in one statement should all be replaced."""
        result = rewrite_sql(
            "SELECT ISNULL(a, 'x'), ISNULL(b, 0) FROM t",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "ISNULL" not in result.rewritten_sql
        assert "COALESCE(a, 'x')" in result.rewritten_sql
        assert "COALESCE(b, 0)" in result.rewritten_sql

    # -- LEN → LENGTH --------------------------------------------------------

    def test_len_to_length(self):
        result = rewrite_sql(
            "SELECT LEN(name) AS name_len FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "LEN(" not in result.rewritten_sql
        assert "LENGTH(name)" in result.rewritten_sql
        assert _result_contains_rule(result, "LEN → LENGTH")

    # -- NEWID → gen_random_uuid ---------------------------------------------

    def test_newid_to_gen_random_uuid(self):
        result = rewrite_sql(
            "INSERT INTO logs (id, message) VALUES (NEWID(), 'test')",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "NEWID()" not in result.rewritten_sql
        assert "gen_random_uuid()" in result.rewritten_sql
        assert _result_contains_rule(result, "NEWID → gen_random_uuid")

    # -- [brackets] → "quotes" ------------------------------------------------

    def test_brackets_to_quotes(self):
        result = rewrite_sql(
            "SELECT [id], [name] FROM [products] WHERE [is_active] = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "[" not in result.rewritten_sql
        assert '"id"' in result.rewritten_sql
        assert '"products"' in result.rewritten_sql
        assert _result_contains_rule(result, '[标识符] → "标识符"')

    # -- CHARINDEX → POSITION -------------------------------------------------

    def test_charindex_to_position(self):
        result = rewrite_sql(
            "SELECT * FROM t WHERE CHARINDEX('abc', col) > 0",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "CHARINDEX" not in result.rewritten_sql
        assert "POSITION('abc' IN col)" in result.rewritten_sql
        assert _result_contains_rule(result, "CHARINDEX → POSITION")

    # -- DATEADD → INTERVAL ---------------------------------------------------

    def test_dateadd_day_to_interval(self):
        result = rewrite_sql(
            "SELECT DATEADD(DAY, 7, created_at) FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEADD" not in result.rewritten_sql
        assert "INTERVAL '7' DAY" in result.rewritten_sql
        assert _result_contains_rule(result, "DATEADD → + INTERVAL")

    def test_dateadd_quarter_to_interval(self):
        """Quarter should be converted to 3*N months."""
        result = rewrite_sql(
            "SELECT DATEADD(QUARTER, 2, created_at) FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEADD" not in result.rewritten_sql
        assert "INTERVAL '6' MONTH" in result.rewritten_sql

    # -- DATEDIFF → EXTRACT ---------------------------------------------------

    def test_datediff_day_to_extract(self):
        result = rewrite_sql(
            "SELECT DATEDIFF(DAY, start_date, end_date) FROM events",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEDIFF" not in result.rewritten_sql
        assert "EXTRACT(DAY FROM" in result.rewritten_sql
        assert _result_contains_rule(result, "DATEDIFF → EXTRACT")

    def test_datediff_unsupported_unit_fallback(self):
        """DATEDIFF with unsupported units (hour, minute) keeps original with warning."""
        result = rewrite_sql(
            "SELECT DATEDIFF(HOUR, start_time, end_time) FROM events",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Fallback: keeps original DATEDIFF with a WARNING comment
        assert "WARNING" in result.rewritten_sql
        assert "DATEDIFF" in result.rewritten_sql  # original preserved
        assert _result_contains_rule(result, "DATEDIFF → EXTRACT")

    def test_datediff_month_to_age(self):
        """DATEDIFF(MONTH, a, b) → EXTRACT(YEAR FROM AGE(...)) * 12 + EXTRACT(MONTH FROM AGE(...))"""
        result = rewrite_sql(
            "SELECT DATEDIFF(MONTH, start_date, end_date) FROM events",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEDIFF" not in result.rewritten_sql
        assert "EXTRACT(YEAR FROM AGE" in result.rewritten_sql
        assert "EXTRACT(MONTH FROM AGE" in result.rewritten_sql

    def test_datediff_year_to_age(self):
        """DATEDIFF(YEAR, a, b) → EXTRACT(YEAR FROM AGE(...))"""
        result = rewrite_sql(
            "SELECT DATEDIFF(YEAR, start_date, end_date) FROM events",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEDIFF" not in result.rewritten_sql
        assert "EXTRACT(YEAR FROM AGE" in result.rewritten_sql

    # -- DATEPART → EXTRACT ---------------------------------------------------

    def test_datepart_to_extract(self):
        result = rewrite_sql(
            "SELECT DATEPART(YEAR, created_at) FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "DATEPART" not in result.rewritten_sql
        assert "EXTRACT(YEAR FROM" in result.rewritten_sql
        assert _result_contains_rule(result, "DATEPART → EXTRACT")


# ===========================================================================
# 2. Rule Correctness — MSSQL → DM8
# ===========================================================================


class TestMssqlToDm8Correctness:
    """Verify MSSQL→DM8 rules use Oracle-compatible syntax."""

    def test_getdate_to_sysdate(self):
        result = rewrite_sql(
            "SELECT GETDATE() FROM dual",
            source_db="mssql",
            target_db="dm8",
        )
        assert "GETDATE()" not in result.rewritten_sql
        assert "SYSDATE" in result.rewritten_sql

    def test_isnull_to_nvl(self):
        result = rewrite_sql(
            "SELECT ISNULL(col, 0) FROM t",
            source_db="mssql",
            target_db="dm8",
        )
        assert "ISNULL" not in result.rewritten_sql
        assert "NVL(col, 0)" in result.rewritten_sql
        assert _result_contains_rule(result, "ISNULL → NVL")

    def test_newid_to_sys_guid(self):
        result = rewrite_sql(
            "INSERT INTO t (id) VALUES (NEWID())",
            source_db="mssql",
            target_db="dm8",
        )
        assert "NEWID()" not in result.rewritten_sql
        assert "SYS_GUID()" in result.rewritten_sql

    def test_top_to_limit_dm8(self):
        result = rewrite_sql(
            "SELECT TOP 5 * FROM products",
            source_db="mssql",
            target_db="dm8",
        )
        assert "TOP" not in result.rewritten_sql.upper().split("SELECT")[1]
        assert "LIMIT 5" in result.rewritten_sql


# ===========================================================================
# 3. Reverse Rewrite — KingbaseES → MSSQL
# ===========================================================================


class TestKingbaseEsToMssql:
    """Verify reverse-direction rules produce valid MSSQL syntax."""

    def test_limit_to_top(self):
        result = rewrite_sql(
            "SELECT id, name FROM products ORDER BY created_at DESC LIMIT 10",
            source_db="kingbasees",
            target_db="mssql",
        )
        assert "LIMIT 10" not in result.rewritten_sql
        assert "SELECT TOP 10" in result.rewritten_sql
        assert _result_contains_rule(result, "LIMIT → TOP")

    def test_now_to_getdate(self):
        result = rewrite_sql(
            "SELECT * FROM t WHERE NOW() > created_at",
            source_db="kingbasees",
            target_db="mssql",
        )
        assert "NOW()" not in result.rewritten_sql
        assert "GETDATE()" in result.rewritten_sql
        assert _result_contains_rule(result, "NOW → GETDATE")

    def test_coalesce_to_isnull(self):
        result = rewrite_sql(
            "SELECT COALESCE(desc, 'N/A') FROM products",
            source_db="kingbasees",
            target_db="mssql",
        )
        assert "COALESCE" not in result.rewritten_sql
        assert "ISNULL(desc, 'N/A')" in result.rewritten_sql
        assert _result_contains_rule(result, "COALESCE → ISNULL")

    def test_length_to_len(self):
        result = rewrite_sql(
            "SELECT LENGTH(name) FROM products",
            source_db="kingbasees",
            target_db="mssql",
        )
        assert "LENGTH" not in result.rewritten_sql
        assert "LEN(name)" in result.rewritten_sql
        assert _result_contains_rule(result, "LENGTH → LEN")

    def test_gen_random_uuid_to_newid(self):
        result = rewrite_sql(
            "INSERT INTO t (id) VALUES (gen_random_uuid())",
            source_db="kingbasees",
            target_db="mssql",
        )
        assert "gen_random_uuid" not in result.rewritten_sql
        assert "NEWID()" in result.rewritten_sql
        assert _result_contains_rule(result, "gen_random_uuid → NEWID")


# ===========================================================================
# 4. Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Boundary conditions and error paths."""

    def test_empty_sql(self):
        result = rewrite_sql(
            "",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Empty SQL is still returned as-is (engine doesn't crash)
        assert result.original_sql == ""
        # Validation may warn about empty rewritten SQL
        # but the engine should not raise

    def test_sql_with_no_dialect_features(self):
        """SQL that needs no rewriting returns unchanged with no rules applied."""
        result = rewrite_sql(
            "SELECT id, name FROM products WHERE is_active = true",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert result.rewritten_sql.strip() == result.original_sql.strip()
        assert len(result.rules_applied) == 0
        # No dialect-specific functions → no rules should fire
        assert result.confidence == 1.0

    def test_identity_same_database(self):
        """source_db == target_db returns unchanged immediately."""
        result = rewrite_sql(
            "SELECT TOP 10 GETDATE(), ISNULL(x, 0), LEN(y) FROM [t]",
            source_db="mssql",
            target_db="mssql",
        )
        assert result.rewritten_sql == result.original_sql
        assert len(result.rules_applied) == 0
        assert result.confidence == 1.0

    def test_unknown_db_pair(self):
        """A pair with no rules defined returns original SQL with a warning."""
        result = rewrite_sql(
            "SELECT * FROM t",
            source_db="dm8",
            target_db="kingbasees",
        )
        assert result.rewritten_sql == result.original_sql
        assert len(result.rules_applied) == 0
        assert len(result.warnings) > 0
        assert "No rewrite rules defined" in result.warnings[0]

    def test_multiple_rules_chain(self):
        """A single SQL with multiple dialect features applies all matching rules."""
        result = rewrite_sql(
            "SELECT TOP 5 id, ISNULL(name, '?'), LEN(desc) "
            "FROM [products] WHERE GETDATE() > created_at",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Should apply: TOP→LIMIT, ISNULL→COALESCE, LEN→LENGTH,
        #              brackets→quotes, GETDATE→NOW
        assert "TOP" not in result.rewritten_sql.upper().split("SELECT")[1]
        assert "ISNULL" not in result.rewritten_sql
        assert "LEN(" not in result.rewritten_sql
        assert "[" not in result.rewritten_sql
        assert "GETDATE" not in result.rewritten_sql
        assert len(result.rules_applied) >= 5

    def test_rule_failure_isolation(self):
        """When a rule fails, it's skipped but others still apply."""
        result = rewrite_sql(
            "SELECT TOP 10 id, GETDATE() AS now FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Both rules should apply successfully
        assert "TOP" not in result.rewritten_sql.upper().split("SELECT")[1]
        assert "GETDATE()" not in result.rewritten_sql

    def test_patindex_warning_rule(self):
        """PATINDEX triggers a warning rule that prepends a comment."""
        result = rewrite_sql(
            "SELECT PATINDEX('%abc%', col) FROM t",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "WARNING" in result.rewritten_sql
        assert "PATINDEX" in result.rewritten_sql  # original kept

    def test_top_percent_warning_rule(self):
        """TOP PERCENT triggers a warning without mechanical rewrite.

        TOP→LIMIT must NOT fire on TOP PERCENT — the syntax has no direct
        equivalent in LIMIT (PERCENT is semantic, not row-count based).
        """
        result = rewrite_sql(
            "SELECT TOP 10 PERCENT * FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert "WARNING" in result.rewritten_sql
        assert "TOP" in result.rewritten_sql  # original TOP kept
        assert not _result_contains_rule(result, "TOP → LIMIT"), (
            "TOP→LIMIT should NOT fire on TOP PERCENT"
        )
        assert _result_contains_rule(result, "TOP PERCENT 警告")


# ===========================================================================
# 5. Stability — Ordering & Confidence
# ===========================================================================


class TestStability:
    """Rule ordering correctness and confidence computation."""

    def test_top_applied_before_getdate(self):
        """TOP→LIMIT must apply before GETDATE→NOW to avoid cross-contamination."""
        result = rewrite_sql(
            "SELECT TOP 5 id FROM products WHERE GETDATE() > created_at",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Both rules should be applied
        assert _result_contains_rule(result, "TOP → LIMIT")
        assert _result_contains_rule(result, "GETDATE → NOW")
        # TOP→LIMIT appears first in rule list, should be first in applied
        top_idx = next(
            i for i, r in enumerate(result.rules_applied) if r.name == "TOP → LIMIT"
        )
        getdate_idx = next(
            i
            for i, r in enumerate(result.rules_applied)
            if r.name == "GETDATE → NOW"
        )
        assert top_idx < getdate_idx, "TOP→LIMIT must apply before GETDATE→NOW"

    def test_confidence_geometric_mean(self):
        """Overall confidence is the geometric mean of applied rule confidences."""
        confidences = [0.98, 0.95, 0.92]
        expected = math.prod(confidences) ** (1.0 / 3)
        actual = compute_overall_confidence(confidences)
        assert actual == pytest.approx(expected, rel=1e-6)

    def test_confidence_perfect_when_no_rules(self):
        """Empty list → confidence = 1.0."""
        assert compute_overall_confidence([]) == 1.0

    def test_confidence_single_rule(self):
        """Single rule → confidence equals that rule's confidence."""
        assert compute_overall_confidence([0.85]) == pytest.approx(0.85)

    def test_confidence_low_rule_penalizes_heavily(self):
        """Geometric mean penalizes low-confidence rules more than arithmetic mean."""
        confidences = [0.98, 0.98, 0.40]  # one low-confidence rule
        geo_mean = compute_overall_confidence(confidences)
        arith_mean = sum(confidences) / len(confidences)
        assert geo_mean < arith_mean, (
            f"Geometric mean ({geo_mean:.4f}) should be less than "
            f"arithmetic mean ({arith_mean:.4f})"
        )

    def test_rewrite_result_confidence_rounding(self):
        """Confidence from rewrite_sql is rounded to 4 decimal places."""
        result = rewrite_sql(
            "SELECT TOP 10 GETDATE() FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        # Should be product of [0.98, 0.95] ** 0.5
        expected = round((0.98 * 0.95) ** 0.5, 4)
        assert result.confidence == expected

    def test_unapplied_rules_do_not_affect_confidence(self):
        """Only rules that actually changed the SQL contribute to confidence."""
        result = rewrite_sql(
            "SELECT id FROM products",
            source_db="mssql",
            target_db="kingbasees",
        )
        # No dialect features → no rules applied → confidence = 1.0
        assert result.confidence == 1.0


# ===========================================================================
# 5a. Post-Rewrite Validation
# ===========================================================================


class TestValidation:
    """Verify the _validate() structural integrity checks."""

    def test_valid_sql_passes(self):
        """Normal SQL produces no validation warnings."""
        warnings = _validate(
            "SELECT id, name FROM products WHERE is_active = 1",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert len(warnings) == 0

    def test_empty_sql_warns(self):
        """Empty rewritten SQL should produce a warning."""
        warnings = _validate("", source_db="mssql", target_db="kingbasees")
        assert len(warnings) == 1
        assert "empty" in warnings[0].lower()

    def test_top_and_limit_conflict_warns(self):
        """Both TOP and LIMIT in the same statement triggers a conflict warning."""
        warnings = _validate(
            "SELECT TOP 10 id FROM products LIMIT 10",
            source_db="mssql",
            target_db="kingbasees",
        )
        assert len(warnings) == 1
        assert "TOP" in warnings[0] and "LIMIT" in warnings[0]

    def test_only_top_no_warning(self):
        """TOP without LIMIT is valid MSSQL — no warning."""
        warnings = _validate(
            "SELECT TOP 10 id FROM products",
            source_db="mssql",
            target_db="mssql",
        )
        assert len(warnings) == 0

    def test_only_limit_no_warning(self):
        """LIMIT without TOP is valid PG — no warning."""
        warnings = _validate(
            "SELECT id FROM products LIMIT 10",
            source_db="kingbasees",
            target_db="kingbasees",
        )
        assert len(warnings) == 0


# ===========================================================================
# 6. Rule Structure Validation
# ===========================================================================


class TestRuleStructure:
    """Verify the declarative rule definitions are well-formed."""

    def test_all_rules_have_unique_ids(self):
        """Every rule across all rule sets must have a unique id."""
        all_ids: list[str] = []
        for rule_set in RULE_REGISTRY.values():
            for rule in rule_set:
                all_ids.append(rule.id)
        duplicates = {rid for rid in all_ids if all_ids.count(rid) > 1}
        assert not duplicates, f"Duplicate rule IDs found: {duplicates}"

    def test_all_rules_have_apply_or_pattern(self):
        """Every rule must have either apply or (pattern+replace)."""
        malformed: list[str] = []
        for rule_set in RULE_REGISTRY.values():
            for rule in rule_set:
                has_declarative = (
                    rule.pattern is not None and rule.replace is not None
                )
                has_apply = rule.apply is not None
                if not has_declarative and not has_apply:
                    malformed.append(rule.id)
        assert not malformed, (
            f"Rules missing both pattern/replace and apply: {malformed}"
        )

    def test_simple_rules_use_pattern_replace(self):
        """Rules that ARE simple regex substitutions should use pattern+replace.

        These 9 rules are pure regex substitutions with no AST-dependent logic:
          GETDATE→NOW, GETUTCDATE→CURRENT_TIMESTAMP, NEWID→gen_random_uuid,
          GETDATE→SYSDATE, GETUTCDATE→SYSTIMESTAMP, NEWID→SYS_GUID,
          NOW→GETDATE, LENGTH→LEN, gen_random_uuid→NEWID
        """
        expected_simple_ids = {
            "mssql_to_pg_getdate_to_now",
            "mssql_to_pg_getutcdate_to_current_timestamp",
            "mssql_to_pg_newid_to_gen_random_uuid",
            "mssql_to_dm8_getdate_to_sysdate",
            "mssql_to_dm8_getutcdate_to_systimestamp",
            "mssql_to_dm8_newid_to_sys_guid",
            "kingbasees_to_mssql_now_to_getdate",
            "kingbasees_to_mssql_length_to_len",
            "kingbasees_to_mssql_gen_random_uuid_to_newid",
        }

        for rule_set in RULE_REGISTRY.values():
            for rule in rule_set:
                if rule.id in expected_simple_ids:
                    assert rule.pattern is not None, (
                        f"Simple rule {rule.id} should use pattern, not apply"
                    )
                    assert rule.replace is not None, (
                        f"Simple rule {rule.id} should use replace, not apply"
                    )
                    assert rule.apply is None, (
                        f"Simple rule {rule.id} should not have apply() — "
                        f"use pattern+replace instead"
                    )

    def test_rules_have_correct_db_mapping(self):
        """Each rule's source_db/target_db should match its registry key."""
        for (src, tgt), rule_set in RULE_REGISTRY.items():
            for rule in rule_set:
                assert rule.source_db == src, (
                    f"Rule {rule.id}: source_db={rule.source_db} "
                    f"but registry key is ({src}, {tgt})"
                )
                assert rule.target_db == tgt, (
                    f"Rule {rule.id}: target_db={rule.target_db} "
                    f"but registry key is ({src}, {tgt})"
                )

    def test_rule_count_matches_spec(self):
        """Verify expected rule counts per direction pair."""
        assert len(RULE_REGISTRY[("mssql", "kingbasees")]) == 14
        assert len(RULE_REGISTRY[("mssql", "dm8")]) == 12
        assert len(RULE_REGISTRY[("kingbasees", "mssql")]) == 6

    def test_all_confidence_values_in_range(self):
        """Every rule confidence must be in [0.0, 1.0]."""
        for rule_set in RULE_REGISTRY.values():
            for rule in rule_set:
                assert 0.0 <= rule.confidence <= 1.0, (
                    f"Rule {rule.id} has invalid confidence {rule.confidence}"
                )


# ===========================================================================
# 7. apply_rules Executor Unit Tests
# ===========================================================================


class TestApplyRulesExecutor:
    """Direct tests of the centralized apply_rules() executor."""

    def test_apply_rules_with_pattern_rule(self):
        """Simple pattern+replace rule should work without an apply callable."""
        rules = [
            RewriteRule(
                id="test_pattern_rule",
                name="TEST → PASSED",
                description="Test pattern rule",
                source_db="mssql",
                target_db="kingbasees",
                pattern=r"\bTEST\b",
                replace="PASSED",
                confidence=1.0,
            )
        ]
        norm = normalize("SELECT TEST FROM dual")
        rewritten, applied, warnings = apply_rules(
            "SELECT TEST FROM dual", norm, rules
        )
        assert rewritten == "SELECT PASSED FROM dual"
        assert len(applied) == 1
        assert applied[0].name == "TEST → PASSED"
        assert len(warnings) == 0

    def test_apply_rules_with_apply_callable(self):
        """Complex rule with apply callable should work."""
        def _upper_test(sql: str, _norm: NormalizedAst) -> str:
            return sql.replace("test", "UPPER_TEST")

        rules = [
            RewriteRule(
                id="test_apply_rule",
                name="Apply Test",
                description="Test apply callable",
                source_db="mssql",
                target_db="kingbasees",
                apply=_upper_test,
                confidence=0.90,
            )
        ]
        norm = normalize("SELECT test FROM dual")
        rewritten, applied, warnings = apply_rules(
            "SELECT test FROM dual", norm, rules
        )
        assert rewritten == "SELECT UPPER_TEST FROM dual"
        assert len(applied) == 1
        assert len(warnings) == 0

    def test_apply_rules_no_change_means_not_applied(self):
        """Rule that doesn't change the SQL shouldn't appear in applied list."""
        rules = [
            RewriteRule(
                id="test_no_match",
                name="No Match",
                description="Should not match",
                source_db="mssql",
                target_db="kingbasees",
                pattern=r"\bNONEXISTENT\b",
                replace="STILL_NOT_THERE",
                confidence=0.50,
            )
        ]
        norm = normalize("SELECT id FROM products")
        rewritten, applied, warnings = apply_rules(
            "SELECT id FROM products", norm, rules
        )
        assert rewritten == "SELECT id FROM products"
        assert len(applied) == 0

    def test_apply_rules_exception_isolation(self):
        """A rule that raises is skipped; subsequent rules still apply."""
        def _broken(_sql: str, _norm: NormalizedAst) -> str:
            raise ValueError("Simulated rule failure")

        rules = [
            RewriteRule(
                id="test_broken",
                name="Broken Rule",
                description="This rule always fails",
                source_db="mssql",
                target_db="kingbasees",
                apply=_broken,
                confidence=0.50,
            ),
            RewriteRule(
                id="test_ok",
                name="OK Rule",
                description="This rule works",
                source_db="mssql",
                target_db="kingbasees",
                pattern=r"\bOK_TEST\b",
                replace="WORKED",
                confidence=1.0,
            ),
        ]
        norm = normalize("SELECT OK_TEST FROM dual")
        rewritten, applied, warnings = apply_rules(
            "SELECT OK_TEST FROM dual", norm, rules
        )
        assert rewritten == "SELECT WORKED FROM dual"
        assert len(applied) == 1
        assert applied[0].name == "OK Rule"
        assert len(warnings) == 1
        assert "Broken Rule" in warnings[0]

    def test_apply_rules_ast_refreshed_after_each_rule(self):
        """AST should be normalized after each rule changes the SQL."""
        # This tests that ISNULL→COALESCE followed by LEN→LENGTH both work
        # even though ISNULL changes the SQL that LEN needs to inspect
        from app.api.sql_compare.rewrite.rules import (
            _apply_isnull_to_coalesce,
            _apply_len_to_length,
        )

        rules = [
            RewriteRule(
                id="test_isnull",
                name="ISNULL→COALESCE",
                description="Test ISNULL",
                source_db="mssql",
                target_db="kingbasees",
                apply=_apply_isnull_to_coalesce,
                confidence=0.92,
            ),
            RewriteRule(
                id="test_len",
                name="LEN→LENGTH",
                description="Test LEN",
                source_db="mssql",
                target_db="kingbasees",
                apply=_apply_len_to_length,
                confidence=0.90,
            ),
        ]
        sql = "SELECT ISNULL(name, '?') AS n, LEN(name) AS l FROM t"
        norm = normalize(sql)
        rewritten, applied, warnings = apply_rules(sql, norm, rules)
        assert "ISNULL" not in rewritten
        assert "LEN(" not in rewritten
        assert len(applied) == 2
        assert len(warnings) == 0

    def test_apply_rules_malformed_rule_warns(self):
        """Rule with neither apply nor pattern+replace should warn and skip."""
        rules = [
            RewriteRule(
                id="test_malformed",
                name="Malformed",
                description="No apply or pattern",
                source_db="mssql",
                target_db="kingbasees",
                confidence=0.50,
            )
        ]
        norm = normalize("SELECT 1")
        rewritten, applied, warnings = apply_rules("SELECT 1", norm, rules)
        assert rewritten == "SELECT 1"
        assert len(applied) == 0
        assert len(warnings) == 1
        assert "Malformed" in warnings[0]


# ===========================================================================
# 8. AST Normalizer Tests
# ===========================================================================


class TestAstNormalizer:
    """Verify the AST normalizer correctly extracts dialect features."""

    def test_normalize_detects_top(self):
        norm = normalize("SELECT TOP 10 id FROM products")
        assert norm.has_top is True
        assert norm.limit == 10

    def test_normalize_detects_limit(self):
        norm = normalize("SELECT id FROM products LIMIT 5")
        assert norm.limit == 5

    def test_normalize_detects_isnull(self):
        norm = normalize("SELECT ISNULL(col, 0) FROM t")
        assert len(norm.isnull_calls) == 1
        assert norm.isnull_calls[0] == ["col", "0"]

    def test_normalize_detects_len(self):
        norm = normalize("SELECT LEN(name) FROM t")
        assert len(norm.len_calls) == 1
        assert norm.len_calls[0] == "name"

    def test_normalize_detects_getdate_count(self):
        norm = normalize("SELECT GETDATE(), GETDATE() FROM t")
        assert norm.getdate_calls == 2

    def test_normalize_detects_newid_count(self):
        norm = normalize("INSERT INTO t VALUES (NEWID())")
        assert norm.newid_calls == 1

    def test_normalize_detects_brackets(self):
        norm = normalize("SELECT [id] FROM [products]")
        assert norm.has_brackets is True
        assert "id" in norm.bracket_idents
        assert "products" in norm.bracket_idents


# ===========================================================================
# 9. get_rules Lookup Tests
# ===========================================================================


class TestGetRules:
    """Verify rule registry lookup."""

    def test_get_rules_known_pair(self):
        rules = get_rules("mssql", "kingbasees")
        assert len(rules) == 14

    def test_get_rules_unknown_pair(self):
        rules = get_rules("dm8", "mssql")
        assert len(rules) == 0

    def test_get_rules_nonexistent_db(self):
        rules = get_rules("oracle", "mysql")
        assert len(rules) == 0
