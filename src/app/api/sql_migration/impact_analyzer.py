"""
SQL Migration Impact Analyzer — assesses migration blast radius.

Identifies:
  - Critical tables: tables affected by HIGH/CRITICAL-risk functions or joins
  - Function dependency graph: which tables rely on which dialect functions
  - Join chain risk: cumulative risk scored along multi-table JOIN paths
  - Risk hotspots: specific columns or functions that are most problematic
"""

from __future__ import annotations

from app.api.sql_diagnostics.diagnose_schemas import (
    ColumnDiagnostic,
    FunctionDiagnostic,
    JoinDiagnostic,
    RiskLevel,
    TableDiagnostic,
)

from .schemas import ImpactAnalysis, JoinChainRisk, RiskLevel as MigrationRisk


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_impact(
    tables: list[TableDiagnostic],
    columns: list[ColumnDiagnostic],
    functions: list[FunctionDiagnostic],
    joins: list[JoinDiagnostic],
) -> ImpactAnalysis:
    """Analyze migration impact across all extracted objects.

    Args:
        tables: Table diagnostics from the diagnostics engine.
        columns: Column diagnostics.
        functions: Function diagnostics.
        joins: Join diagnostics.

    Returns:
        ImpactAnalysis with critical tables, hotspots, and join chain risks.
    """
    # Identify critical tables
    critical_tables = _find_critical_tables(tables, functions, joins)

    # Collect risk hotspots
    hotspots = _find_risk_hotspots(columns, functions, joins)

    # Analyze join chains
    join_chains = _analyze_join_chains(tables, joins)

    # Collect all table names
    all_tables = [t.name for t in tables]

    # Collect all function names
    all_functions = [f.name for f in functions]

    # Count high/medium risk objects
    all_objects = list(tables) + list(columns) + list(functions) + list(joins)
    high_risk = sum(1 for o in all_objects if o.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL))
    medium_risk = sum(1 for o in all_objects if o.risk == RiskLevel.MEDIUM)

    return ImpactAnalysis(
        tables=all_tables,
        critical_tables=critical_tables,
        functions=all_functions,
        risk_hotspots=hotspots,
        join_chains=join_chains,
        total_objects=len(all_objects),
        high_risk_count=high_risk,
        medium_risk_count=medium_risk,
    )


# ---------------------------------------------------------------------------
# Critical table detection
# ---------------------------------------------------------------------------


def _find_critical_tables(
    tables: list[TableDiagnostic],
    functions: list[FunctionDiagnostic],
    joins: list[JoinDiagnostic],
) -> list[str]:
    """Identify tables that are materially affected by migration risk.

    A table becomes 'critical' when:
      - A HIGH/CRITICAL-risk function references one of its columns
      - It participates in a HIGH/CRITICAL-risk JOIN chain
      - Its own risk level is HIGH or above
    """
    critical: set[str] = set()

    # Tables with inherent HIGH+ risk
    for t in tables:
        if t.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            critical.add(t.name)

    # Tables referenced by HIGH+ functions (via issue text)
    for f in functions:
        if f.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            for issue in f.issues:
                for t in tables:
                    if t.name.lower() in issue.lower():
                        critical.add(t.name)

    # Tables in HIGH+ joins
    for j in joins:
        if j.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            critical.add(j.table)

    return sorted(critical)


# ---------------------------------------------------------------------------
# Risk hotspots
# ---------------------------------------------------------------------------


def _find_risk_hotspots(
    columns: list[ColumnDiagnostic],
    functions: list[FunctionDiagnostic],
    joins: list[JoinDiagnostic],
) -> list[str]:
    """Identify specific risk hotspots — columns and functions needing attention.

    Hotspots are:
      - Columns with MEDIUM+ risk
      - Functions with MEDIUM+ risk
      - Join conditions that are risky
    """
    hotspots: list[str] = []

    for c in columns:
        if c.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL):
            hotspots.append(c.name)

    for f in functions:
        if f.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL):
            hotspots.append(f.raw)

    for j in joins:
        if j.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL):
            hotspots.append(f"JOIN {j.table} ({j.risk.value})")

    return hotspots


# ---------------------------------------------------------------------------
# Join chain risk scoring
# ---------------------------------------------------------------------------


def _analyze_join_chains(
    tables: list[TableDiagnostic],
    joins: list[JoinDiagnostic],
) -> list[JoinChainRisk]:
    """Score risk along JOIN chains.

    Each JOIN chain is scored by:
      - Number of tables in the chain (longer = riskier)
      - Risk levels of individual JOIN clauses
      - Presence of dialect functions referencing joined tables
    """
    if not joins:
        return []

    chains: list[JoinChainRisk] = []

    # Build simple chains: each JOIN connects two tables
    # Find the "from" table for each join by looking at the ON condition
    for join in joins:
        # Determine which table this join connects FROM
        from_table = _resolve_from_table(join, tables)

        chain_tables = [from_table, join.table] if from_table else [join.table]
        chain_tables = [t for t in chain_tables if t]

        # Score the chain
        chain_risk = _score_join_chain(chain_tables, join)

        chains.append(JoinChainRisk(
            chain=chain_tables,
            risk_level=_map_risk(chain_risk),
            description=_describe_chain(chain_tables, join),
        ))

    return chains


def _resolve_from_table(
    join: JoinDiagnostic,
    tables: list[TableDiagnostic],
) -> str:
    """Resolve which table a JOIN connects FROM based on the ON condition."""
    if not join.condition:
        return ""

    condition_lower = join.condition.lower()
    for table in tables:
        name_lower = table.name.lower()
        alias_lower = (table.alias or "").lower()
        if name_lower in condition_lower or (alias_lower and alias_lower in condition_lower):
            return table.name
    return ""


def _score_join_chain(chain: list[str], join: JoinDiagnostic) -> float:
    """Score a join chain's risk from 0 (safe) to 100 (critical).

    Factors:
      - Base risk per table in chain: 5 points each
      - JOIN type risk: FULL=20, CROSS=10, others=0
      - JOIN-level diagnostic risk: MEDIUM=15, HIGH=30, CRITICAL=50
    """
    score = 0.0

    # Chain length
    score += len(chain) * 5

    # JOIN type
    jt = join.join_type.upper()
    if jt == "FULL":
        score += 20
    elif jt == "CROSS":
        score += 10
    elif jt == "NATURAL":
        score += 25

    # Diagnostic risk
    if join.risk == RiskLevel.CRITICAL:
        score += 50
    elif join.risk == RiskLevel.HIGH:
        score += 30
    elif join.risk == RiskLevel.MEDIUM:
        score += 15

    return min(score, 100.0)


def _describe_chain(chain: list[str], join: JoinDiagnostic) -> str:
    """Generate a human-readable description of a JOIN chain."""
    arrow_chain = " → ".join(chain)
    desc = f"{arrow_chain} ({join.join_type} JOIN)"
    if join.condition:
        desc += f" ON {join.condition}"
    if join.risk not in (RiskLevel.NONE,):
        desc += f" — risk: {join.risk.value}"
    return desc


def _map_risk(score: float) -> MigrationRisk:
    """Map a numeric risk score to MigrationRisk level."""
    if score >= 70:
        return MigrationRisk.CRITICAL
    if score >= 50:
        return MigrationRisk.HIGH
    if score >= 25:
        return MigrationRisk.MEDIUM
    if score >= 10:
        return MigrationRisk.LOW
    return MigrationRisk.NONE
