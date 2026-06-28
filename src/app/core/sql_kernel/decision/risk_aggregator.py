"""
Risk Aggregator — collects and ranks risks from all 5 engine outputs.

Produces a unified risk profile:
  - primary_risks: top-N risks ranked by severity (human-readable)
  - blocking_issues: risks that prevent safe migration
  - aggregated_severity: overall risk level across all engines
  - risk_sources: which engines contributed how many risks
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Aggregated risk types
# ---------------------------------------------------------------------------


@dataclass
class AggregatedRisk:
    """A single risk item aggregated from one or more engines."""

    description: str                # human-readable description
    severity: str                   # NONE / LOW / MEDIUM / HIGH / CRITICAL
    source_engine: str              # diagnostics / rewrite / migration / simulation
    is_blocking: bool = False       # blocks safe migration
    count: int = 1                  # how many instances (for duplicates)


@dataclass
class RiskProfile:
    """Unified risk profile across all engines."""

    primary_risks: list[str] = field(default_factory=list)   # top risks
    blocking_issues: list[str] = field(default_factory=list)  # blockers only
    all_risks: list[AggregatedRisk] = field(default_factory=list)
    aggregated_severity: str = "NONE"  # worst severity across all engines
    risk_sources: dict[str, int] = field(default_factory=dict)

    # Counts by severity
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0


# ---------------------------------------------------------------------------
# Severity ordering
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 5,
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "NONE": 1,
}


def _worst_severity(a: str, b: str) -> str:
    """Return the worse of two severity levels."""
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate_risks(
    diagnostics: object | None,
    rewrite: object | None,
    migration: object | None,
    simulation: object | None,
) -> RiskProfile:
    """Aggregate risks from all available engine outputs.

    Args:
        diagnostics: ObjectAnalysis from diagnostics engine.
        rewrite: RewriteResult from rewrite engine.
        migration: MigrationPlanResponse from migration engine.
        simulation: SimulationResponse from simulation engine.

    Returns:
        RiskProfile with unified risk picture.
    """
    all_risks: list[AggregatedRisk] = []
    risk_sources: dict[str, int] = {}

    # --- Diagnostics risks ---
    if diagnostics is not None:
        diag_risks = _extract_diagnostics_risks(diagnostics)
        all_risks.extend(diag_risks)
        risk_sources["diagnostics"] = len(diag_risks)

    # --- Rewrite risks ---
    if rewrite is not None:
        rewrite_risks = _extract_rewrite_risks(rewrite)
        all_risks.extend(rewrite_risks)
        risk_sources["rewrite"] = len(rewrite_risks)

    # --- Migration risks ---
    if migration is not None:
        mig_risks = _extract_migration_risks(migration)
        all_risks.extend(mig_risks)
        risk_sources["migration"] = len(mig_risks)

    # --- Simulation risks ---
    if simulation is not None:
        sim_risks = _extract_simulation_risks(simulation)
        all_risks.extend(sim_risks)
        risk_sources["simulation"] = len(sim_risks)

    # Sort by severity (worst first)
    all_risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 0), reverse=True)

    # Compute counts
    critical_count = sum(1 for r in all_risks if r.severity == "CRITICAL")
    high_count = sum(1 for r in all_risks if r.severity == "HIGH")
    medium_count = sum(1 for r in all_risks if r.severity == "MEDIUM")
    low_count = sum(1 for r in all_risks if r.severity == "LOW")

    # Aggregate severity: worst across all
    agg_severity = "NONE"
    for r in all_risks:
        agg_severity = _worst_severity(agg_severity, r.severity)

    # Blocking issues: CRITICAL severity, or HIGH from simulation
    blocking = [
        r.description for r in all_risks
        if r.is_blocking or r.severity == "CRITICAL"
    ]

    # Primary risks: top 5 non-blocking or all if ≤5
    non_blocking = [r for r in all_risks if not r.is_blocking and r.severity != "CRITICAL"]
    primary = [r.description for r in (blocking + non_blocking)[:8]]

    return RiskProfile(
        primary_risks=primary,
        blocking_issues=blocking,
        all_risks=all_risks,
        aggregated_severity=agg_severity,
        risk_sources=risk_sources,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
    )


# ---------------------------------------------------------------------------
# Engine-specific risk extractors
# ---------------------------------------------------------------------------


def _extract_diagnostics_risks(diagnostics) -> list[AggregatedRisk]:
    """Extract risks from ObjectAnalysis (diagnostics engine)."""
    risks: list[AggregatedRisk] = []

    # Check each object type for HIGH/CRITICAL items
    for category, items in [
        ("functions", getattr(diagnostics, "functions", [])),
        ("tables", getattr(diagnostics, "tables", [])),
        ("columns", getattr(diagnostics, "columns", [])),
        ("joins", getattr(diagnostics, "joins", [])),
    ]:
        for item in items:
            risk_val = _get_risk_value(item)
            if risk_val in ("HIGH", "CRITICAL"):
                name = getattr(item, "name", str(item))
                issues = getattr(item, "issues", [])
                issue_text = "; ".join(issues) if issues else f"{name} has {risk_val} risk"

                risks.append(AggregatedRisk(
                    description=f"[{category}] {issue_text}",
                    severity=risk_val,
                    source_engine="diagnostics",
                    is_blocking=(risk_val == "CRITICAL"),
                ))

    return risks


def _extract_rewrite_risks(rewrite) -> list[AggregatedRisk]:
    """Extract risks from RewriteResult (rewrite engine)."""
    risks: list[AggregatedRisk] = []

    confidence = getattr(rewrite, "confidence", 1.0)
    rules = getattr(rewrite, "rules_applied", [])
    warnings = getattr(rewrite, "warnings", [])

    # Low rewrite confidence is a risk
    if confidence < 0.85 and len(rules) > 0:
        severity = "MEDIUM" if confidence >= 0.70 else "HIGH"
        risks.append(AggregatedRisk(
            description=f"改写置信度偏低 ({confidence:.0%})，{len(rules)} 条规则被应用",
            severity=severity,
            source_engine="rewrite",
            is_blocking=(severity == "HIGH"),
        ))

    # Rewrite warnings
    for w in warnings:
        if "error" in w.lower() or "fail" in w.lower():
            risks.append(AggregatedRisk(
                description=f"改写警告: {w}",
                severity="MEDIUM",
                source_engine="rewrite",
            ))

    # No rules available for the direction
    if len(rules) == 0 and confidence < 1.0:
        # Check if there's a warning about no rules
        no_rules_warning = any("No rewrite rules" in w for w in warnings)
        if no_rules_warning:
            risks.append(AggregatedRisk(
                description="无可用的自动改写规则，需要手动改写 SQL",
                severity="HIGH",
                source_engine="rewrite",
                is_blocking=True,
            ))

    return risks


def _extract_migration_risks(migration) -> list[AggregatedRisk]:
    """Extract risks from MigrationPlanResponse (migration engine)."""
    risks: list[AggregatedRisk] = []

    risk_level = _get_risk_value(migration, default="NONE")
    score = getattr(migration, "estimated_score", 100.0)
    feasible = getattr(migration, "migration_feasible", True)
    impact = getattr(migration, "impact", None)

    if not feasible:
        risks.append(AggregatedRisk(
            description=f"迁移可行性评估为不可行 (评分: {score:.0f}/100)",
            severity="CRITICAL",
            source_engine="migration",
            is_blocking=True,
        ))

    if risk_level in ("HIGH", "CRITICAL"):
        risks.append(AggregatedRisk(
            description=f"迁移风险等级: {risk_level} (评分: {score:.0f}/100)",
            severity=risk_level,
            source_engine="migration",
            is_blocking=(risk_level == "CRITICAL"),
        ))

    # Impact analysis risks
    if impact is not None:
        critical_tables = getattr(impact, "critical_tables", [])
        if critical_tables:
            risks.append(AggregatedRisk(
                description=f"存在 {len(critical_tables)} 个关键表需要调整: {', '.join(critical_tables)}",
                severity="HIGH",
                source_engine="migration",
            ))

        hotspots = getattr(impact, "risk_hotspots", [])
        if hotspots:
            risks.append(AggregatedRisk(
                description=f"发现 {len(hotspots)} 个风险热点",
                severity="MEDIUM",
                source_engine="migration",
            ))

    # Migration plan effort
    plan = getattr(migration, "plan", None)
    if plan is not None:
        effort = getattr(plan, "estimated_effort", "LOW")
        manual_steps = getattr(plan, "manual_steps", 0)
        if effort == "HIGH":
            risks.append(AggregatedRisk(
                description=f"迁移工作量评估为 HIGH，{manual_steps} 个手动步骤",
                severity="MEDIUM",
                source_engine="migration",
            ))

    return risks


def _extract_simulation_risks(simulation) -> list[AggregatedRisk]:
    """Extract risks from SimulationResponse (simulation engine)."""
    risks: list[AggregatedRisk] = []

    eq_score = getattr(simulation, "equivalence_score", 1.0)
    risk_level = _get_risk_value(simulation, default="NONE")
    verdict = _get_enum_value(simulation, "recommendation", "SAFE_TO_EXECUTE")
    sim_detail = getattr(simulation, "simulation", None)

    # Low equivalence score
    if eq_score < 0.88:
        severity = "CRITICAL" if eq_score < 0.70 else "HIGH" if eq_score < 0.80 else "MEDIUM"
        risks.append(AggregatedRisk(
            description=f"等价性评分偏低 ({eq_score:.0%})，SQL 改写后语义可能不一致",
            severity=severity,
            source_engine="simulation",
            is_blocking=(severity == "CRITICAL"),
        ))

    # High-risk verdict
    if verdict == "HIGH_RISK_DO_NOT_EXECUTE":
        risks.append(AggregatedRisk(
            description="仿真裁决: 高风险，不建议执行迁移",
            severity="CRITICAL",
            source_engine="simulation",
            is_blocking=True,
        ))
    elif verdict == "NEEDS_MANUAL_REVIEW":
        risks.append(AggregatedRisk(
            description="仿真裁决: 需要人工审查后再执行",
            severity="MEDIUM",
            source_engine="simulation",
        ))

    # Failure points
    if sim_detail is not None:
        failures = getattr(sim_detail, "failure_points", [])
        for fp in failures:
            fp_severity = _get_risk_value(fp, default="MEDIUM")
            fp_type = getattr(fp, "type", "UNKNOWN")
            fp_desc = getattr(fp, "description", str(fp))
            fp_location = getattr(fp, "location", "")

            loc_text = f" ({fp_location})" if fp_location else ""
            risks.append(AggregatedRisk(
                description=f"[{fp_type}]{loc_text}: {fp_desc}",
                severity=fp_severity,
                source_engine="simulation",
                is_blocking=(fp_severity == "CRITICAL"),
            ))

        # Data drift
        row_diff = getattr(sim_detail, "row_level_diff", None)
        if row_diff is not None:
            drifts = getattr(row_diff, "table_drifts", [])
            for td in drifts:
                td_drift = _get_enum_value(td, "drift", "STABLE")
                if td_drift in ("HIGH_DRIFT", "MODERATE_DRIFT"):
                    td_table = getattr(td, "table", "unknown")
                    td_var = getattr(td, "expected_variance", "?")
                    severity = "HIGH" if td_drift == "HIGH_DRIFT" else "MEDIUM"
                    risks.append(AggregatedRisk(
                        description=f"数据漂移: 表 [{td_table}] 预期差异 {td_var}",
                        severity=severity,
                        source_engine="simulation",
                    ))

    return risks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_risk_value(obj, default: str = "NONE") -> str:
    """Extract risk/severity value from an object safely."""
    # Try common attribute names
    for attr in ("risk", "severity", "risk_level"):
        val = getattr(obj, attr, None)
        if val is not None:
            if hasattr(val, "value"):
                return str(val.value)
            return str(val)
    return default


def _get_enum_value(obj, attr: str, default: str) -> str:
    """Extract an enum value from an object attribute."""
    val = getattr(obj, attr, None)
    if val is None:
        return default
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)
