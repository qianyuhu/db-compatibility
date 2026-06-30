"""
Migration Decision Engine — final decision on migration readiness.

Decision logic:
    IF failure_rate == 0 AND confidence > 75 AND no_blockers:
        → READY
    ELSE IF failure_rate < 0.20 OR has_blockers:
        → REVIEW_REQUIRED
    ELSE:
        → NOT_READY

The decision is based on:
  - confidence_score: how much evidence we have that migration works
  - failure_rate: proportion of tests that actually failed
  - has_blockers: any BLOCKER severity failures exist
"""

from __future__ import annotations

from .schemas import (
    MIGRATION_NOT_READY,
    MIGRATION_READY,
    MIGRATION_REVIEW_REQUIRED,
    FailureDetail,
    MigrationDecision,
)


class MigrationDecisionEngine:
    """Make the final migration readiness decision.

    Separates the decision logic from scoring so it can be tuned
    independently of the scoring algorithms.
    """

    # Thresholds (configurable)
    FAILURE_RATE_READY = 0.0            # Must be 0% failures for READY
    FAILURE_RATE_THRESHOLD = 0.20       # 20% max for REVIEW_REQUIRED
    CONFIDENCE_READY = 75               # Minimum confidence for READY

    @classmethod
    def decide(
        cls,
        failure_rate: float,
        confidence_score: float,
        failure_details: list[FailureDetail],
    ) -> MigrationDecision:
        """Make the final migration decision.

        Args:
            failure_rate: Proportion of tests that failed (0.0-1.0)
            confidence_score: Confidence score (0-100)
            failure_details: List of actual failures found

        Returns:
            MigrationDecision with status, reasoning, and recommended actions.
        """
        reasoning: list[str] = []
        actions: list[str] = []

        has_blockers = any(f.severity == "BLOCKER" for f in failure_details)
        has_high = any(f.severity == "HIGH" for f in failure_details)
        total_failures = len(failure_details)
        failures_pct = failure_rate * 100

        # ---- Decision Matrix (ordered by severity — first match wins) ----

        # READY: zero failures, high confidence, no blockers
        if (
            failure_rate <= cls.FAILURE_RATE_READY
            and confidence_score > cls.CONFIDENCE_READY
            and not has_blockers
        ):
            status = MIGRATION_READY
            reasoning.append(
                f"零失败率 ({failures_pct:.0f}%), 置信度 {confidence_score}/100 > 阈值 {cls.CONFIDENCE_READY}"
            )
            reasoning.append("所有测试通过，无阻塞性问题")
            actions.append("✅ 可以执行生产迁移")
            actions.append("建议持续监控迁移后的运行状态")

        # NOT_READY: high failure rate OR high failure rate with blockers
        elif failure_rate >= cls.FAILURE_RATE_THRESHOLD:
            status = MIGRATION_NOT_READY
            reasoning.append(
                f"失败率 {failures_pct:.0f}% ≥ 阈值 {cls.FAILURE_RATE_THRESHOLD*100:.0f}%"
            )
            reasoning.append(f"置信度 {confidence_score}/100")
            if has_blockers:
                blocker_count = sum(1 for f in failure_details if f.severity == "BLOCKER")
                reasoning.append(f"发现 {blocker_count} 个阻塞性问题")
            if has_high:
                reasoning.append(f"发现 {sum(1 for f in failure_details if f.severity == 'HIGH')} 个高严重性问题")
            reasoning.append(f"共 {total_failures} 个失败")
            actions.append("解决关键失败问题和阻塞性问题")
            actions.append("运行详细的SQL兼容性分析 (SQL Kernel)")
            actions.append("考虑在每个失败测试上使用兼容层或重写策略")
            actions.append("修复后重新运行完整测试套件")

        # REVIEW_REQUIRED: some failures but below threshold, OR blockers with low failure rate
        elif failure_rate < cls.FAILURE_RATE_THRESHOLD:
            status = MIGRATION_REVIEW_REQUIRED
            reasoning.append(
                f"失败率 {failures_pct:.0f}% < 阈值 {cls.FAILURE_RATE_THRESHOLD*100:.0f}%, "
                f"置信度 {confidence_score}/100"
            )
            if has_blockers:
                blocker_count = sum(1 for f in failure_details if f.severity == "BLOCKER")
                reasoning.append(f"发现 {blocker_count} 个阻塞性问题（需在迁移前解决）")
            if has_high:
                reasoning.append(f"发现 {sum(1 for f in failure_details if f.severity == 'HIGH')} 个高严重性问题")
            reasoning.append(f"共 {total_failures} 个需关注的问题")
            actions.append("审查失败详情，评估对迁移的影响")
            actions.append("解决阻塞性和高严重性问题后重新评估")
            if not has_blockers:
                actions.append("对通过测试的组件可以先进行分批迁移")

        # Fallback (shouldn't normally reach here)
        else:
            status = MIGRATION_NOT_READY
            reasoning.append(f"置信度过低 ({confidence_score}/100) 或失败率过高 ({failures_pct:.0f}%)")
            actions.append("需要全面修复后重新评估")

        return MigrationDecision(
            status=status,
            confidence_score=confidence_score,
            failure_rate=failure_rate,
            reasoning=reasoning,
            recommended_actions=actions,
        )
