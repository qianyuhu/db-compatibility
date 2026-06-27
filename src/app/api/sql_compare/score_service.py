"""
SQL Compatibility Score Service — orchestrates scoring across 4 dimensions.

Architecture:
    score_router.py → score_service.calculate_score()
        → compare_service.execute_compare()  [REUSE: parallel execution]
        → compare_service.compute_diff()      [REUSE: diff engine]
        → compare_service.detect_dialect_rewrites()  [REUSE: suggestions]
        → sql_ast.parse_ast()                 [NEW: pattern AST]
        → scoring.syntax_score()              [NEW]
        → scoring.execution_score()           [NEW]
        → scoring.result_score()              [NEW]
        → scoring.risk_score()                [NEW]
        → _compute_final_score()              [weighted sum]

Key constraint: Does NOT re-execute SQL — reuses existing compare_service results.
"""

from __future__ import annotations

import time
from typing import Any

from app.api.sql_demo.compare_service import (
    compute_diff,
    detect_dialect_rewrites,
    execute_compare,
)
from app.api.sql_compare.score_schemas import Finding, ScoreBreakdown, ScoreResponse
from .scoring import execution_score, result_score, risk_score, syntax_score
from .sql_ast import parse_ast


# ---------------------------------------------------------------------------
# Dimension weights
# ---------------------------------------------------------------------------

WEIGHT_SYNTAX = 0.30
WEIGHT_EXECUTION = 0.30
WEIGHT_RESULT = 0.25
WEIGHT_RISK = 0.15


def calculate_score(
    sql: str,
    db_types: list[str],
) -> ScoreResponse:
    """Calculate SQL compatibility score across target databases.

    1. Execute SQL on all target DBs (via compare_service)
    2. Parse SQL AST
    3. Run 4 independent scoring dimensions
    4. Compute weighted final score
    5. Generate suggestions from rewrites + findings

    Args:
        sql: SQL statement to evaluate.
        db_types: Target database types.

    Returns:
        ScoreResponse with overall score, level, breakdown, findings, suggestions.
    """
    start_time = time.perf_counter()

    # -- Step 1: Execute on all target DBs (reuses compare_service) --
    results, rewrites = execute_compare(sql, db_types)

    # -- Step 2: Compute diff (reuses compare_service) --
    diff = compute_diff(results)

    # -- Step 3: Parse SQL AST --
    ast = parse_ast(sql)

    # -- Step 4: Run 4 scoring dimensions --
    syntax_val, syntax_findings = syntax_score(ast, db_types)
    execution_val, execution_findings = execution_score(results)
    result_val, result_findings = result_score(diff, results)
    risk_val, risk_findings = risk_score(ast, results)

    # -- Step 5: Weighted final score --
    final_score = _compute_weighted_score(
        syntax_val,
        execution_val,
        result_val,
        risk_val,
    )

    # -- Step 6: Determine level --
    level = _score_to_level(final_score)

    # -- Step 7: Collect all findings --
    all_findings = (
        syntax_findings
        + execution_findings
        + result_findings
        + risk_findings
    )

    # -- Step 8: Generate suggestions --
    suggestions = _generate_suggestions(rewrites, all_findings)

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return ScoreResponse(
        score=final_score,
        level=level,
        breakdown=ScoreBreakdown(
            syntax=syntax_val,
            execution=execution_val,
            result=result_val,
            risk=risk_val,
        ),
        findings=all_findings,
        suggestions=suggestions,
        db_count=len(db_types),
        execution_time_ms=round(elapsed_ms, 1),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_weighted_score(
    syntax_val: float,
    execution_val: float,
    result_val: float,
    risk_val: float,
) -> float:
    """Compute weighted final score.

    Formula:
        score = syntax * 0.30 + execution * 0.30 + result * 0.25 + risk * 0.15
    """
    weighted = (
        syntax_val * WEIGHT_SYNTAX
        + execution_val * WEIGHT_EXECUTION
        + result_val * WEIGHT_RESULT
        + risk_val * WEIGHT_RISK
    )
    return round(weighted, 1)


def _score_to_level(score: float) -> str:
    """Map numeric score to compatibility level."""
    if score >= 90:
        return "LOW"
    if score >= 70:
        return "MEDIUM"
    if score >= 50:
        return "HIGH"
    return "CRITICAL"


def _generate_suggestions(
    rewrites: list[Any],
    findings: list[Finding],
) -> list[str]:
    """Generate actionable suggestions from rewrites and findings.

    Deduplicates suggestions and returns unique, actionable items.

    Args:
        rewrites: List of SqlRewrite objects from detect_dialect_rewrites.
        findings: All scoring findings.

    Returns:
        Deduplicated list of suggestion strings.
    """
    suggestions: list[str] = []
    seen: set[str] = set()

    # Extract from rewrite suggestions
    for rw in rewrites:
        suggestion = f"[{rw.db_type}] {rw.reason}"
        key = suggestion.lower()
        if key not in seen:
            seen.add(key)
            suggestions.append(suggestion)

    # Extract from findings with detail
    for f in findings:
        if f.detail and f.detail not in {
            "查看完整 Diff 面板获取详细差异",
        }:
            key = f.detail.lower()
            if key not in seen:
                seen.add(key)
                suggestions.append(f.detail)

    # If no issues found at all
    if not suggestions:
        suggestions.append(
            "SQL 在各目标数据库中兼容良好，无需改写"
        )

    return suggestions
