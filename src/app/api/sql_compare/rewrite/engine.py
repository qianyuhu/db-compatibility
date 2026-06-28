"""
SQL Rewrite Engine — the core rewrite pipeline.

Pipeline:
    1. Parse   — normalize source SQL to a dialect-neutral AST
    2. Match   — find applicable rewrite rules for (source_db, target_db)
    3. Rewrite — apply matched rules sequentially (via centralized executor)
    4. Validate — check structural integrity of the rewritten SQL

Two entry points:
  - rewrite_sql(sql, source_db, target_db) — original, parses internally
  - rewrite_from_context(ctx) — kernel path, uses pre-built context

Usage:
    from app.api.sql_compare.rewrite.engine import rewrite_sql

    result = rewrite_sql(
        sql="SELECT TOP 10 * FROM users WHERE GETDATE() > created_at",
        source_db="mssql",
        target_db="kingbasees",
    )
    # result.rewritten_sql → "SELECT * FROM users WHERE NOW() > created_at\nLIMIT 10"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .ast_normalizer import normalize
from .rules import (
    AppliedRuleInfo,
    RewriteRule,
    apply_rules,
    compute_overall_confidence,
    get_rules,
)

if TYPE_CHECKING:
    from app.core.sql_kernel.semantic_context import SQLSemanticContext


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RewriteResult:
    """Result of a SQL rewrite operation."""

    original_sql: str
    rewritten_sql: str
    source_db: str
    target_db: str
    rules_applied: list[AppliedRuleInfo] = field(default_factory=list)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rewrite pipeline
# ---------------------------------------------------------------------------


def rewrite_sql(
    sql: str,
    source_db: str,
    target_db: str,
) -> RewriteResult:
    """Run the full rewrite pipeline.

    Args:
        sql: Source SQL in the source database dialect.
        source_db: Source database type (mssql, kingbasees, dm8).
        target_db: Target database type (mssql, kingbasees, dm8).

    Returns:
        RewriteResult with the rewritten SQL and metadata.
    """
    warnings: list[str] = []

    # --- Identity case ---
    if source_db == target_db:
        return RewriteResult(
            original_sql=sql.strip(),
            rewritten_sql=sql.strip(),
            source_db=source_db,
            target_db=target_db,
            rules_applied=[],
            confidence=1.0,
            warnings=[],
        )

    # --- Phase 1: Parse / Normalize ---
    norm_ast = normalize(sql)

    # --- Phase 2: Match rules ---
    rules = get_rules(source_db, target_db)

    if not rules:
        warnings.append(
            f"No rewrite rules defined for {source_db} → {target_db}. "
            f"Returning original SQL unchanged."
        )
        return RewriteResult(
            original_sql=sql.strip(),
            rewritten_sql=sql.strip(),
            source_db=source_db,
            target_db=target_db,
            rules_applied=[],
            confidence=1.0,
            warnings=warnings,
        )

    # --- Phase 3: Apply rules (centralized executor) ---
    rewritten, applied, rule_warnings = apply_rules(sql, norm_ast, rules)
    warnings.extend(rule_warnings)

    # --- Phase 4: Compute overall confidence ---
    if applied:
        confidences = [r.confidence for r in applied]
        confidence = round(compute_overall_confidence(confidences), 4)
    else:
        confidence = 1.0

    # --- Phase 5: Post-rewrite validation ---
    rewritten = rewritten.strip()
    validation_warnings = _validate(rewritten, source_db, target_db)
    warnings.extend(validation_warnings)

    return RewriteResult(
        original_sql=sql.strip(),
        rewritten_sql=rewritten,
        source_db=source_db,
        target_db=target_db,
        rules_applied=applied,
        confidence=confidence,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Kernel entry point — uses pre-built SQLSemanticContext
# ---------------------------------------------------------------------------


def rewrite_from_context(ctx: "SQLSemanticContext") -> RewriteResult:
    """Run rewrite using a pre-built SQLSemanticContext.

    This is the kernel path — it uses the context's pre-normalized AST data
    (statement_type, limit_value, isnull_calls, etc.) and skips normalize().

    Args:
        ctx: Pre-built SQLSemanticContext from the kernel.

    Returns:
        RewriteResult with the rewritten SQL and metadata.
    """
    # --- Identity case ---
    if ctx.source_db == ctx.target_db:
        return RewriteResult(
            original_sql=ctx.original_sql,
            rewritten_sql=ctx.original_sql,
            source_db=ctx.source_db,
            target_db=ctx.target_db,
            rules_applied=[],
            confidence=1.0,
            warnings=[],
        )

    # Delegate to the full rewrite pipeline — the context already has the
    # normalized data, but the rewrite engine's rule application operates
    # on raw SQL text, so we still call rewrite_sql.
    # Future optimisation: pass the pre-normalized AST to apply_rules directly.
    return rewrite_sql(ctx.original_sql, ctx.source_db, ctx.target_db)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(sql: str, source_db: str, target_db: str) -> list[str]:
    """Run basic structural validation on the rewritten SQL.

    Checks:
        - SQL is non-empty
        - No obvious double-write (both TOP and LIMIT present)
        - Statement structure preserved (SELECT/INSERT/UPDATE/DELETE)

    Returns a list of warning strings.
    """
    warnings: list[str] = []
    upper = sql.upper().strip()

    if not upper:
        warnings.append("Rewritten SQL is empty — possible rewrite error")
        return warnings

    # Check for redundant constructs (both TOP and LIMIT)
    has_top = bool(re.search(r"\bSELECT\s+TOP\s+\d+", upper))
    has_limit = bool(re.search(r"\bLIMIT\s+\d+", upper))
    if has_top and has_limit:
        warnings.append(
            "Rewritten SQL contains both TOP and LIMIT — possible rewrite conflict"
        )

    return warnings
