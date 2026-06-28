"""
SQL Semantic Context — unified source of truth for all SQL intelligence engines.

Combines the three previously-separate representations:
  - ExtractedObjects (diagnostics extractor) — tables, columns, functions, joins
  - SqlAst (sql_ast.py) — statement type, TOP, brackets, functions
  - NormalizedAst (ast_normalizer.py) — ISNULL/LEN/GETDATE args, unified limit

All 5 engines (diagnostics, rewrite, score, migration, simulation) read from
this single context — no engine parses SQL independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.api.sql_diagnostics.extractor import (
    ColumnRef,
    FunctionRef,
    JoinRef,
    TableRef,
)


# ---------------------------------------------------------------------------
# SQLSemanticContext — the single source of truth
# ---------------------------------------------------------------------------


@dataclass
class SQLSemanticContext:
    """Unified semantic context built once, shared across all engines.

    Covers three analysis dimensions:
      1. Object-level — tables, columns, functions, joins (from ExtractedObjects)
      2. AST-level — statement type, TOP/LIMIT, brackets, dialect functions
      3. Metadata — source/target DB, original and rewritten SQL
    """

    # === Object-level (from ExtractedObjects) ===
    tables: list[TableRef] = field(default_factory=list)
    columns: list[ColumnRef] = field(default_factory=list)
    functions: list[FunctionRef] = field(default_factory=list)
    joins: list[JoinRef] = field(default_factory=list)

    # === AST-level (from NormalizedAst / SqlAst) ===
    statement_type: str = "UNKNOWN"
    limit_value: int | None = None       # unified: TOP or FETCH FIRST or LIMIT
    has_top: bool = False
    has_fetch_first: bool = False
    has_brackets: bool = False
    bracket_idents: list[str] = field(default_factory=list)
    dialect_functions: list[str] = field(default_factory=list)  # function names found
    isnull_calls: list[list[str]] = field(default_factory=list)
    len_calls: list[str] = field(default_factory=list)
    getdate_count: int = 0
    newid_count: int = 0
    tables_simple: list[str] = field(default_factory=list)  # simple name list

    # === Metadata ===
    source_db: str = ""
    target_db: str = ""
    original_sql: str = ""
    rewritten_sql: str | None = None


# ---------------------------------------------------------------------------
# KernelResult — unified output from all engines
# ---------------------------------------------------------------------------


@dataclass
class KernelResult:
    """Aggregated result from SQLKernel.analyze().

    Each engine's output is optional — only populated if the engine was
    included in the `engines` parameter.
    """

    source_db: str = ""
    target_db: str = ""
    original_sql: str = ""
    rewritten_sql: str | None = None

    # Engine outputs (None = engine not run)
    diagnostics: object | None = None      # ObjectAnalysis
    rewrite: object | None = None          # RewriteResult
    score: object | None = None            # ScoreResponse
    migration: object | None = None        # MigrationPlanResponse
    simulation: object | None = None       # SimulationResponse

    # Decision synthesis (None = not synthesised)
    decision: object | None = None         # KernelDecision

    # Metadata
    engines_run: list[str] = field(default_factory=list)
    total_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BusinessExecutionResult — dual-DB execution result from SQLKernel.execute_on_both()
# ---------------------------------------------------------------------------


@dataclass
class BusinessExecutionResult:
    """Result from SQLKernel.execute_on_both() — SQL execution on two databases.

    Combines the dual-DB execution result with optional kernel analysis.
    """

    source_db: str = ""
    target_db: str = ""
    sql: str = ""
    rewritten_sql: str | None = None
    source_result: dict | None = None
    target_result: dict | None = None
    kernel: KernelResult | None = None
    equal: bool = False
    diff: list[dict] = field(default_factory=list)
    execution_time_ms: float = 0.0
