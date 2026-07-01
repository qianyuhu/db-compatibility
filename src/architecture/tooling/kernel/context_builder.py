"""
Context Builder — builds a SQLSemanticContext from raw SQL.

This is the ONLY module that calls SQL parsers.  All engines receive the
already-built context and never parse SQL independently.

Reuses existing battle-tested parsers:
  - extract_objects() from diagnostics — object-level extraction
  - normalize() from rewrite engine — AST-level features
  - rewrite_sql() from rewrite engine — auto-rewrite when needed
"""

from __future__ import annotations

from architecture.core.sql.rewrite.ast_normalizer import normalize
from architecture.core.sql.rewrite.engine import rewrite_sql
from architecture.core.sql.diagnostics.extractor import extract_objects

from .semantic_context import SQLSemanticContext


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_context(
    sql: str,
    source_db: str,
    target_db: str,
    *,
    rewritten_sql: str | None = None,
    auto_rewrite: bool = True,
) -> SQLSemanticContext:
    """Build a unified SQLSemanticContext from raw SQL.

    This is the single parse entry point.  It:
      1. Extracts objects (tables, columns, functions, joins) via extract_objects()
      2. Normalises AST-level features (TOP, LIMIT, ISNULL, LEN, etc.) via normalize()
      3. Optionally auto-rewrites the SQL for the target dialect

    Args:
        sql: Raw SQL in the source database dialect.
        source_db: Source database type (mssql, kingbasees, dm8).
        target_db: Target database type (mssql, kingbasees, dm8).
        rewritten_sql: Pre-computed rewritten SQL.  If None and auto_rewrite is
            True, the rewrite engine is invoked automatically.
        auto_rewrite: If True (default), automatically rewrite when source != target.

    Returns:
        SQLSemanticContext ready for consumption by all engines.
    """
    # --- Object-level extraction (reuses diagnostics extractor) ---
    objects = extract_objects(sql)

    # --- AST-level normalisation (reuses rewrite normalizer) ---
    norm = normalize(sql)

    # --- Auto-rewrite if needed ---
    _rewritten: str | None = rewritten_sql
    if _rewritten is None and auto_rewrite and source_db != target_db:
        try:
            result = rewrite_sql(sql, source_db, target_db)
            _rewritten = result.rewritten_sql
            if _rewritten == sql.strip():
                _rewritten = None  # no change → treat as no rewrite
        except Exception:
            _rewritten = None  # rewrite failed → engines handle gracefully

    return SQLSemanticContext(
        # Object-level
        tables=objects.tables,
        columns=objects.columns,
        functions=objects.functions,
        joins=objects.joins,

        # AST-level
        statement_type=norm.statement_type,
        limit_value=norm.limit,
        has_top=norm.has_top,
        has_fetch_first=norm.has_fetch_first,
        has_brackets=norm.has_brackets,
        bracket_idents=list(norm.bracket_idents),
        dialect_functions=list(norm.functions),
        isnull_calls=[list(args) for args in norm.isnull_calls],
        len_calls=list(norm.len_calls),
        getdate_count=norm.getdate_calls,
        newid_count=norm.newid_calls,
        tables_simple=list(norm.tables),

        # Metadata
        source_db=source_db,
        target_db=target_db,
        original_sql=sql.strip(),
        rewritten_sql=_rewritten,
    )
