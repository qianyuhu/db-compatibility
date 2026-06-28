"""
SQL Migration Plan Generator — produces step-by-step migration instructions.

Translates rewrite rules + diagnostic findings into an ordered,
actionable migration plan with effort estimation.
"""

from __future__ import annotations

from app.api.sql_compare.rewrite.rules import AppliedRuleInfo

from .schemas import MigrationPlan, MigrationStep, StepAction


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_plan(
    applied_rules: list[AppliedRuleInfo],
    has_critical_tables: bool,
    has_high_functions: bool,
    high_risk_count: int,
    medium_risk_count: int,
    source_db: str,
    target_db: str,
) -> MigrationPlan:
    """Generate an ordered migration plan.

    Args:
        applied_rules: Rules successfully applied during SQL rewrite.
        has_critical_tables: Whether any tables were flagged as critical.
        has_high_functions: Whether any HIGH-risk functions remain.
        high_risk_count: Number of HIGH+CRITICAL risk objects.
        medium_risk_count: Number of MEDIUM risk objects.
        source_db: Source database dialect.
        target_db: Target database dialect.

    Returns:
        MigrationPlan with ordered steps and effort estimation.
    """
    steps: list[MigrationStep] = []
    step_num = 1

    # -- Phase 1: Automatic SQL rewrites --
    for rule in applied_rules:
        steps.append(MigrationStep(
            step=step_num,
            action=StepAction.REWRITE_SQL,
            description=f"应用改写规则: {rule.name}",
            detail=rule.description,
            automatic=True,
        ))
        step_num += 1

    # -- Phase 2: Schema adjustments (if critical tables exist) --
    if has_critical_tables:
        steps.append(MigrationStep(
            step=step_num,
            action=StepAction.UPDATE_SCHEMA,
            description="检查并调整关键表结构",
            detail=(
                f"部分表使用了 {source_db} 特有语法，"
                f"需要在 {target_db} 中调整列类型或索引定义"
            ),
            automatic=False,
        ))
        step_num += 1

    # -- Phase 3: Manual review for remaining HIGH-risk items --
    if has_high_functions or high_risk_count > 0:
        steps.append(MigrationStep(
            step=step_num,
            action=StepAction.MANUAL_REVIEW,
            description=f"人工审查 {high_risk_count} 个高风险对象",
            detail=(
                f"存在 {high_risk_count} 个高风险和 {medium_risk_count} 个中风险对象，"
                f"需要人工确认改写是否正确"
            ),
            automatic=False,
        ))
        step_num += 1

    # -- Phase 4: Test execution --
    steps.append(MigrationStep(
        step=step_num,
        action=StepAction.TEST_RECOMMENDED,
        description=f"在 {target_db} 测试环境执行改写后的 SQL",
        detail="建议先在测试/预发布环境验证 SQL 正确性和性能",
        automatic=False,
    ))
    step_num += 1

    # -- Phase 5: Validate execution --
    steps.append(MigrationStep(
        step=step_num,
        action=StepAction.VALIDATE_EXECUTION,
        description="验证执行结果",
        detail=(
            f"对比 {source_db} 和 {target_db} 的执行结果，"
            f"确保行数、列名、数据值完全一致"
        ),
        automatic=False,
    ))
    step_num += 1

    # -- Phase 6: Final verification --
    steps.append(MigrationStep(
        step=step_num,
        action=StepAction.VERIFY_RESULTS,
        description="生产环境灰度验证",
        detail="建议先在低流量场景验证，确认无异常后全量切换",
        automatic=False,
    ))

    # -- Estimate effort --
    auto_count = sum(1 for s in steps if s.automatic)
    manual_count = sum(1 for s in steps if not s.automatic)

    if high_risk_count > 2:
        effort = "HIGH"
    elif high_risk_count > 0 or medium_risk_count > 3:
        effort = "MEDIUM"
    else:
        effort = "LOW"

    return MigrationPlan(
        steps=steps,
        estimated_effort=effort,
        total_steps=len(steps),
        automatic_steps=auto_count,
        manual_steps=manual_count,
    )
