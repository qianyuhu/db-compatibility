"""
SQL Compatibility Engine — 主要的编排器。

Pipeline:
    SQL Input → Classifier → Rewrite Engine → Compatibility Scorer
    → Dual DB Execution → Diff + Explanation

整合了分类、重写、评分、执行和差异解释的完整管道。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .classifier import ClassificationResult, classify_sql
from .scorer import CompatibilityScore, compute_compatibility_score

if TYPE_CHECKING:
    from architecture.core.sql.rewrite.rewrite_schemas import RewriteResult
    from architecture.tooling.kernel.semantic_context import BusinessExecutionResult


# =========================================================================
# Data Classes
# =========================================================================


@dataclass(frozen=True)
class CompatibilityResult:
    """SQL 兼容性分析总结果。"""

    # Input
    original_sql: str
    source_db: str
    target_db: str

    # Classification
    classification: ClassificationResult

    # Rewrite
    rewritten_sql: str | None = None
    rewrite_result: RewriteResult | None = None

    # Scoring
    compatibility_score: CompatibilityScore | None = None

    # Execution
    execution_result: BusinessExecutionResult | None = None

    # Enhanced diff
    enhanced_diff: dict[str, Any] | None = None

    # Meta
    total_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """便捷访问兼容性评分。"""
        return self.compatibility_score.total_score if self.compatibility_score else 0.0

    @property
    def overall_risk(self) -> str:
        """便捷访问总体风险。"""
        return self.compatibility_score.overall_risk if self.compatibility_score else "UNKNOWN"

    @property
    def is_safe(self) -> bool:
        """迁移是否安全。"""
        return self.score >= 85 and self.overall_risk in ("NONE", "LOW")


# =========================================================================
# Engine
# =========================================================================


class CompatibilityEngine:
    """SQL 兼容性分析引擎 — 一站式分析 SQL 的跨数据库兼容性。"""

    @staticmethod
    def analyze(
        sql: str,
        source_db: str,
        target_db: str,
        *,
        execute: bool = False,
        skip_rewrite: bool = False,
    ) -> CompatibilityResult:
        """运行完整的兼容性分析管道。

        Args:
            sql: 原始 SQL 语句
            source_db: 源数据库类型 (mssql / kingbasees / dm8)
            target_db: 目标数据库类型 (mssql / kingbasees / dm8)
            execute: 是否在双库上执行并对比结果
            skip_rewrite: 跳过重写步骤

        Returns:
            CompatibilityResult 包含所有分析结果
        """
        start = time.perf_counter()
        warnings: list[str] = []

        # ---- Step 1: Classify ----
        classification = classify_sql(sql)

        # ---- Step 2: Rewrite ----
        rewritten_sql: str | None = None
        rewrite_result: RewriteResult | None = None
        rewrite_coverage = 0

        if not skip_rewrite and source_db != target_db:
            try:
                from architecture.core.sql.rewrite.engine import rewrite_sql as do_rewrite

                rewrite_result = do_rewrite(
                    sql=sql,
                    source_db=source_db,
                    target_db=target_db,
                )
                rewritten_sql = rewrite_result.rewritten_sql
                rewrite_coverage = len(rewrite_result.applied_rules)
            except Exception as exc:
                warnings.append(f"Rewrite failed: {exc}")
        else:
            rewritten_sql = sql

        # ---- Step 3: Score ----
        compatibility_score = compute_compatibility_score(
            classification=classification,
            source_db=source_db,
            target_db=target_db,
            rewrite_coverage=rewrite_coverage,
        )

        # ---- Step 4: Execute (optional) ----
        execution_result: BusinessExecutionResult | None = None
        enhanced_diff: dict[str, Any] | None = None

        if execute:
            try:
                exec_sql = rewritten_sql or sql
                execution_result = SQLKernel.execute_on_both(
                    sql=exec_sql,
                    source_db=source_db,
                    target_db=target_db,
                    skip_validation=True,
                    analyze_kernel=True,
                )

                # Generate enhanced diff if results differ
                if not execution_result.equal:
                    try:
                        from app.api.sql_demo.explanation_engine import compute_enhanced_diff

                        src = execution_result.source_result or {}
                        tgt = execution_result.target_result or {}
                        results_map = {source_db: src, target_db: tgt}
                        enhanced = compute_enhanced_diff(
                            results=results_map,
                            original_sql=sql,
                            rewritten_sql=rewritten_sql or "",
                        )
                        enhanced_diff = enhanced.get("three_layer_diff")
                    except Exception as exc:
                        warnings.append(f"Enhanced diff failed: {exc}")
            except Exception as exc:
                warnings.append(f"Execution failed: {exc}")

        # ---- Done ----
        elapsed = round((time.perf_counter() - start) * 1000, 1)

        return CompatibilityResult(
            original_sql=sql,
            source_db=source_db,
            target_db=target_db,
            classification=classification,
            rewritten_sql=rewritten_sql,
            rewrite_result=rewrite_result,
            compatibility_score=compatibility_score,
            execution_result=execution_result,
            enhanced_diff=enhanced_diff,
            total_time_ms=elapsed,
            warnings=warnings,
        )

    @staticmethod
    def analyze_quick(
        sql: str,
        source_db: str,
        target_db: str,
    ) -> CompatibilityResult:
        """快速分析（仅分类 + 重写 + 评分，不执行）。"""
        return CompatibilityEngine.analyze(
            sql=sql,
            source_db=source_db,
            target_db=target_db,
            execute=False,
        )
