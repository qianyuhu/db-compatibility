"""
SQL Compatibility Engine API Router — 兼容性分析端点。
"""

from fastapi import APIRouter

from app.core.sql_compatibility_engine.engine import CompatibilityEngine

from .compat_schemas import (
    ClassificationResponse,
    CompatibilityAnalysisRequest,
    CompatibilityAnalysisResponse,
    DimensionScoreResponse,
    FeatureDetectionResponse,
    ScoreResponse,
)

router = APIRouter(prefix="/api/sql", tags=["sql-compatibility"])


@router.post(
    "/compat/analyze",
    response_model=CompatibilityAnalysisResponse,
    summary="SQL 兼容性分析",
    description=(
        "一站式 SQL 兼容性分析：分类 → 重写 → 评分 → 可选执行。"
        "返回完整的兼容性画像包括分类、改写 SQL、评分和风险标签。"
    ),
)
def analyze_compatibility(
    request: CompatibilityAnalysisRequest,
) -> CompatibilityAnalysisResponse:
    """运行完整的 SQL 兼容性分析管道。"""
    result = CompatibilityEngine.analyze(
        sql=request.sql,
        source_db=request.source_db,
        target_db=request.target_db,
        execute=request.execute,
    )

    # ---- Build classification response ----
    features_resp = [
        FeatureDetectionResponse(
            category=f.category.value,
            count=f.count,
            details=f.details,
            risk=f.risk.value,
        )
        for f in result.classification.features
    ]

    classification_resp = ClassificationResponse(
        categories=[c.value for c in result.classification.categories],
        features=features_resp,
        statement_type=result.classification.statement_type,
        complexity=result.classification.complexity,
        total_features=result.classification.total_features,
        risk_summary=result.classification.risk_summary,
    )

    # ---- Build score response ----
    score_resp = None
    if result.compatibility_score:
        score_resp = ScoreResponse(
            total_score=result.compatibility_score.total_score,
            dimensions=[
                DimensionScoreResponse(
                    name=d.name,
                    raw_score=d.raw_score,
                    max_score=d.max_score,
                    weight=d.weight,
                    percentage=d.percentage,
                    deductions=d.deductions,
                )
                for d in result.compatibility_score.dimensions
            ],
            risk_tags=result.compatibility_score.risk_tags,
            overall_risk=result.compatibility_score.overall_risk,
            summary=result.compatibility_score.summary,
            supported_features=result.compatibility_score.supported_features,
            unsupported_features=result.compatibility_score.unsupported_features,
            rewritten_features=result.compatibility_score.rewritten_features,
        )

    # ---- Build execution result ----
    execution_result_resp = None
    if result.execution_result:
        src = result.execution_result.source_result or {}
        tgt = result.execution_result.target_result or {}
        execution_result_resp = {
            "equal": result.execution_result.equal,
            "source_success": src.get("success", False),
            "target_success": tgt.get("success", False),
            "source_row_count": src.get("row_count", 0),
            "target_row_count": tgt.get("row_count", 0),
            "execution_time_ms": result.execution_result.execution_time_ms,
        }

    return CompatibilityAnalysisResponse(
        original_sql=result.original_sql,
        source_db=result.source_db,
        target_db=result.target_db,
        rewritten_sql=result.rewritten_sql,
        classification=classification_resp,
        score=score_resp,
        execution_result=execution_result_resp,
        enhanced_diff=result.enhanced_diff,
        total_time_ms=result.total_time_ms,
        warnings=result.warnings,
    )
