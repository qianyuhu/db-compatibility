"""
Execution Model — equivalence checking and cardinality estimation.

Simulates how rewritten SQL will behave at execution time on the target
database without actually connecting to a live database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.api.sql_compare.rewrite.ast_normalizer import normalize
from app.api.sql_diagnostics.extractor import extract_objects, TableRef

from .schemas import (
    CardinalityEstimate,
    EquivalenceDetail,
    ExecutionModel,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Known function mappings (source → target semantic equivalent)
# ---------------------------------------------------------------------------

_FUNCTION_MAPPINGS: dict[tuple[str, str], dict[str, str]] = {
    ("mssql", "kingbasees"): {
        "GETDATE": "NOW",
        "GETUTCDATE": "CURRENT_TIMESTAMP",
        "ISNULL": "COALESCE",
        "LEN": "LENGTH",
        "NEWID": "gen_random_uuid",
        "CHARINDEX": "POSITION",
        "DATEADD": "INTERVAL",
        "DATEDIFF": "EXTRACT",
        "DATEPART": "EXTRACT",
    },
    ("mssql", "dm8"): {
        "GETDATE": "SYSDATE",
        "GETUTCDATE": "SYSTIMESTAMP",
        "ISNULL": "NVL",
        "LEN": "LENGTH",
        "NEWID": "SYS_GUID",
        "CHARINDEX": "POSITION",
        "DATEADD": "INTERVAL",
        "DATEDIFF": "EXTRACT",
        "DATEPART": "EXTRACT",
    },
    ("kingbasees", "mssql"): {
        "NOW": "GETDATE",
        "CURRENT_TIMESTAMP": "GETUTCDATE",
        "COALESCE": "ISNULL",
        "LENGTH": "LEN",
        "gen_random_uuid": "NEWID",
        "POSITION": "CHARINDEX",
    },
}


# ---------------------------------------------------------------------------
# Table size heuristics (rows × columns → estimated size factor)
# ---------------------------------------------------------------------------

_DEFAULT_TABLE_SIZE = 10_000

# Heuristic adjustments based on common table naming patterns
_TABLE_SIZE_HEURISTICS: dict[str, int] = {
    "users": 5_000,
    "orders": 50_000,
    "products": 2_000,
    "order_items": 200_000,
    "categories": 100,
    "logs": 1_000_000,
    "sessions": 500_000,
    "payments": 30_000,
    "inventory": 10_000,
    "customers": 20_000,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_execution_model(
    original_sql: str,
    rewritten_sql: str,
    source_db: str,
    target_db: str,
) -> ExecutionModel:
    """Build a complete execution model for the migration simulation.

    Args:
        original_sql: Source SQL in the source database dialect.
        rewritten_sql: Rewritten SQL in the target database dialect.
        source_db: Source database type.
        target_db: Target database type.

    Returns:
        ExecutionModel with equivalence and cardinality assessments.
    """
    equivalence = _check_equivalence(original_sql, rewritten_sql, source_db, target_db)
    cardinality = _estimate_cardinality(original_sql, rewritten_sql)

    return ExecutionModel(equivalence=equivalence, cardinality=cardinality)


# ---------------------------------------------------------------------------
# Equivalence Check
# ---------------------------------------------------------------------------


def _check_equivalence(
    original_sql: str,
    rewritten_sql: str,
    source_db: str,
    target_db: str,
) -> EquivalenceDetail:
    """Check whether the rewritten SQL is semantically equivalent to the original.

    Uses three signals:
        1. AST structural diff (normalized form comparison)
        2. Function mapping consistency (each dialect function has correct target)
        3. Column mapping preservation (selected columns are preserved)
    """
    issues: list[str] = []

    # --- Signal 1: AST structural diff ---
    norm_original = normalize(original_sql)
    norm_rewritten = normalize(rewritten_sql)
    ast_match = _ast_structural_match(original_sql, rewritten_sql, norm_original, norm_rewritten)
    if not ast_match:
        issues.append("AST 结构与原始 SQL 存在显著差异")

    # --- Signal 2: Function mapping consistency ---
    func_consistent = _check_function_mapping(original_sql, rewritten_sql, source_db, target_db)
    if not func_consistent:
        issues.append("部分函数映射不一致或缺失")

    # --- Signal 3: Column mapping preservation ---
    col_preserved = _check_column_preservation(original_sql, rewritten_sql)
    if not col_preserved:
        issues.append("列映射可能丢失或变更")

    return EquivalenceDetail(
        ast_match=ast_match,
        function_mapping_consistent=func_consistent,
        column_mapping_preserved=col_preserved,
        issues=issues,
    )


def _ast_structural_match(
    original_sql: str,
    rewritten_sql: str,
    norm_original: object,
    norm_rewritten: object,
) -> bool:
    """Compare normalized SQL structure for significant differences.

    Checks:
        - Same statement type (SELECT/INSERT/UPDATE/DELETE)
        - Similar clause count (FROM, WHERE, JOIN, ORDER BY, GROUP BY)
        - Rewrite didn't completely change the query shape
    """
    orig_upper = original_sql.upper().strip()
    rewritten_upper = rewritten_sql.upper().strip()

    # Both must start with the same statement type
    stmt_types = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
    orig_type = next((t for t in stmt_types if orig_upper.startswith(t)), None)
    rewritten_type = next((t for t in stmt_types if rewritten_upper.startswith(t)), None)

    if orig_type != rewritten_type:
        return False

    # Count major clauses — they should be within reasonable range
    clauses = ("FROM", "WHERE", "JOIN", "ORDER BY", "GROUP BY", "HAVING")
    orig_clause_count = sum(1 for c in clauses if c in orig_upper)
    rewritten_clause_count = sum(1 for c in clauses if c in rewritten_upper)

    # Allow ±1 clause difference (rewrites may add/remove minor clauses)
    if abs(orig_clause_count - rewritten_clause_count) > 1:
        return False

    return True


def _check_function_mapping(
    original_sql: str,
    rewritten_sql: str,
    source_db: str,
    target_db: str,
) -> bool:
    """Verify that each dialect function in the original has a mapped equivalent
    in the rewritten SQL."""
    mapping = _FUNCTION_MAPPINGS.get((source_db, target_db), {})

    # Extract functions from original SQL
    orig_objects = extract_objects(original_sql)
    rewritten_objects = extract_objects(rewritten_sql)

    orig_funcs = {f.name.upper() for f in orig_objects.functions}
    rewritten_funcs = {f.name.upper() for f in rewritten_objects.functions}

    # Check each original function has a mapping and the target function exists
    for func in orig_funcs:
        expected_target = mapping.get(func)
        if expected_target and expected_target not in rewritten_funcs:
            # The target function should appear in rewritten SQL
            # But some mappings are complex (e.g. DATEADD → INTERVAL with restructured args)
            # We give a pass for known complex mappings
            if func in ("DATEADD", "DATEDIFF", "DATEPART", "CHARINDEX", "STUFF"):
                continue
            return False

    return True


def _check_column_preservation(original_sql: str, rewritten_sql: str) -> bool:
    """Check that selected columns are preserved across the rewrite."""
    orig_objects = extract_objects(original_sql)
    rewritten_objects = extract_objects(rewritten_sql)

    # Only check when both have extractable columns
    if not orig_objects.columns or not rewritten_objects.columns:
        return True

    orig_col_names = {c.name.lower() for c in orig_objects.columns}

    # If the original has explicitly named columns, they should appear in rewritten
    # (excluding function-based columns and * wildcards)
    if "*" in orig_col_names:
        return True

    rewritten_col_names = {c.name.lower() for c in rewritten_objects.columns}

    # Allow some columns to be transformed by function mapping
    # (e.g. GETDATE() becomes NOW() as a column expression)
    common = orig_col_names & rewritten_col_names
    if len(orig_col_names) > 0 and len(common) == 0:
        # Check if all original columns are function outputs (no common columns expected)
        orig_upper = original_sql.upper()
        select_part = _extract_select_list(orig_upper)
        if select_part and not select_part.strip().startswith("*"):
            func_count = len([c for c in orig_objects.columns if _has_function_call(original_sql, c)])
            # If most columns are function-derived, differences are expected
            if func_count < len(orig_objects.columns) * 0.5:
                return False

    return True


def _extract_select_list(sql_upper: str) -> str:
    """Extract the column list between SELECT and FROM."""
    m = re.search(r'\bSELECT\s+(.+?)\s+\bFROM\b', sql_upper, re.DOTALL)
    return m.group(1) if m else ""


def _has_function_call(sql: str, col_ref) -> bool:
    """Check if a column reference appears inside a function call in the SQL."""
    # Simple heuristic: if the column name appears after a known function pattern
    col_name = col_ref.name if hasattr(col_ref, 'name') else str(col_ref)
    pattern = re.compile(
        rf'\b[A-Z_][A-Z0-9_]*\s*\([^)]*{re.escape(col_name)}[^)]*\)',
        re.IGNORECASE,
    )
    return bool(pattern.search(sql))


# ---------------------------------------------------------------------------
# Cardinality Estimation
# ---------------------------------------------------------------------------


def _estimate_cardinality(
    original_sql: str,
    rewritten_sql: str,
) -> CardinalityEstimate:
    """Estimate row-count impact using rule-based heuristics.

    MVP approach (no actual statistics):
        1. Extract tables and JOINs to build a join graph
        2. Apply table-size heuristics
        3. Estimate variance from query structure changes
    """
    orig_objects = extract_objects(original_sql)
    rewritten_objects = extract_objects(rewritten_sql)

    orig_tables = [t.name.lower() for t in orig_objects.tables]
    rewritten_tables = [t.name.lower() for t in rewritten_objects.tables]
    all_tables = sorted(set(orig_tables + rewritten_tables))

    # Estimate rows based on table size heuristics
    orig_rows = _estimate_row_count(orig_objects)
    rewritten_rows = _estimate_row_count(rewritten_objects)

    # Calculate variance
    if orig_rows > 0:
        variance = round((rewritten_rows - orig_rows) / orig_rows * 100, 1)
    else:
        variance = 0.0

    description = _describe_cardinality(variance, orig_rows, rewritten_rows)

    return CardinalityEstimate(
        original_estimated_rows=orig_rows,
        rewritten_estimated_rows=rewritten_rows,
        variance_pct=variance,
        join_graph_tables=all_tables,
        description=description,
    )


def _estimate_row_count(objects) -> int:
    """Estimate row count from extracted objects using heuristics.

    Uses:
        - TOP/LIMIT clauses as the primary cap
        - JOIN cardinality multipliers
        - Table size heuristics for the driving table
    """
    # Find the largest table as driving table
    table_sizes = []
    for t in objects.tables:
        name_lower = t.name.lower()
        size = _TABLE_SIZE_HEURISTICS.get(name_lower, _DEFAULT_TABLE_SIZE)
        table_sizes.append(size)

    if not table_sizes:
        return 0

    base_rows = max(table_sizes) if table_sizes else _DEFAULT_TABLE_SIZE

    # Apply TOP/LIMIT cap
    for f in objects.functions:
        if f.name.upper() == "TOP" and f.args:
            limit_val = int(f.args[0])
            base_rows = min(base_rows, limit_val)
            break

    # Also check for LIMIT pattern in raw SQL
    top_match = re.search(r'\bTOP\s+(\d+)\b', str(objects), re.IGNORECASE)
    if top_match:
        base_rows = min(base_rows, int(top_match.group(1)))

    # JOIN multiplier (each JOIN can increase or decrease cardinality)
    join_count = len(objects.joins)
    if join_count > 0:
        # Simple heuristic: each INNER JOIN with FK typically preserves rows,
        # but LEFT JOIN may increase. We use a small multiplier.
        inner_joins = sum(1 for j in objects.joins if j.join_type.upper() == "INNER")
        left_joins = sum(1 for j in objects.joins if j.join_type.upper() == "LEFT")
        full_joins = sum(1 for j in objects.joins if j.join_type.upper() == "FULL")

        # INNER JOINs with PK/FK typically keep the same row count
        # LEFT JOINs may duplicate rows from the left table
        # FULL JOINs combine both sides
        multiplier = 1.0 + (left_joins * 0.2) + (full_joins * 0.5)
        base_rows = int(base_rows * multiplier)

    return base_rows


def _describe_cardinality(variance: float, orig_rows: int, rewritten_rows: int) -> str:
    """Generate a human-readable description of the cardinality change."""
    if variance == 0:
        return f"行数无变化 (预计 {orig_rows:,} 行)"

    direction = "增加" if variance > 0 else "减少"
    abs_pct = abs(variance)

    if abs_pct < 1:
        level = "极小幅度"
    elif abs_pct < 5:
        level = "小幅"
    elif abs_pct < 20:
        level = "中等幅度"
    else:
        level = "大幅"

    return (
        f"行数预计{direction} {abs_pct}% ({level})："
        f"原始 {orig_rows:,} 行 → 改写后 {rewritten_rows:,} 行"
    )
