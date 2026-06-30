"""Migration API Router — ERP 迁移流水线端点。"""

from fastapi import APIRouter, HTTPException

from app.services.migration_service import MigrationService

from .schemas import (
    MigrationPhaseSummary,
    MigrationPipelineResponse,
    MigrationRunRequest,
    SqlValidationRequest,
    SqlValidationResult,
    SingleResult,
    TableVerificationResult,
    VerificationRequest,
    VerificationResponse,
)

router = APIRouter(prefix="/api/business", tags=["business-migration"])


@router.post(
    "/migrate/run",
    response_model=MigrationPipelineResponse,
    summary="执行 ERP 迁移流水线",
    description=(
        "触发完整迁移流水线：Schema Migration → Data Migration "
        "→ Business Validation → Compatibility Report。"
    ),
)
def run_migration(
    request: MigrationRunRequest,
) -> MigrationPipelineResponse:
    """触发完整迁移流水线。"""
    svc = MigrationService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    result = svc.run_migration(phases=request.phases)

    return MigrationPipelineResponse(
        source_db=result.source_db,
        target_db=result.target_db,
        phases=[
            MigrationPhaseSummary(
                name=p.name,
                status=p.status,
                detail=p.detail,
                error=p.error,
                elapsed_ms=p.elapsed_ms,
            )
            for p in result.phases
        ],
        overall_status=result.overall_status,
        total_time_ms=result.total_time_ms,
        warnings=result.warnings,
    )


@router.get(
    "/migrate/tables",
    summary="获取允许验证的表列表",
    description="返回按 FK 依赖排序的业务表列表。前端应从此端点获取，避免硬编码。",
)
def get_allowed_tables() -> list[str]:
    """返回业务表白名单 — 后端作为唯一来源。"""
    return MigrationService.get_allowed_tables()


@router.post(
    "/migrate/verify",
    response_model=VerificationResponse,
    summary="验证双库实际数据一致性",
    description=(
        "并行对每个业务表执行 SELECT COUNT(*) 在源库和目标库上，"
        "对比行数判断迁移数据是否一致。仅接受白名单内的表名。"
    ),
)
def verify_migration(
    request: VerificationRequest,
) -> VerificationResponse:
    """验证源库和目标库的每个表行数是否一致（并行执行）。"""
    svc = MigrationService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    try:
        data = svc.verify_table_counts(tables=request.tables)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return VerificationResponse(
        source_db=request.source_db,
        target_db=request.target_db,
        tables=[
            TableVerificationResult(
                table_name=t["table_name"],
                source_count=t.get("source_count"),
                target_count=t.get("target_count"),
                source_error=t.get("source_error"),
                target_error=t.get("target_error"),
                status=t["status"],
                source_time_ms=t.get("source_time_ms", 0.0),
                target_time_ms=t.get("target_time_ms", 0.0),
            )
            for t in data["tables"]
        ],
        all_match=data["all_match"],
        match_count=data["match_count"],
        total_tables=data["total_tables"],
        verified=data["verified"],
        total_time_ms=data["total_time_ms"],
    )


@router.post(
    "/migrate/validate-sql",
    response_model=SqlValidationResult,
    summary="验证 SQL 在双库上的执行结果一致性",
    description="在源库和目标库上执行任意 SQL 并对比结果。用于手动验证关键业务查询。",
)
def validate_sql(
    request: SqlValidationRequest,
) -> SqlValidationResult:
    """在双库上执行 SQL 并对比结果。"""
    svc = MigrationService(
        source_db=request.source_db,
        target_db=request.target_db,
    )

    data = svc.validate_sql(sql=request.sql)

    def _to_single_result(raw: dict) -> SingleResult:
        return SingleResult(
            success=raw.get("success", False),
            columns=raw.get("columns", []),
            rows=raw.get("rows", []),
            row_count=raw.get("row_count", 0),
            db_type=raw.get("db_type", ""),
            execution_time_ms=raw.get("execution_time_ms", 0),
            error=raw.get("error"),
            suggestion=raw.get("suggestion"),
        )

    return SqlValidationResult(
        sql=data["sql"],
        source_result=_to_single_result(data["source_result"]),
        target_result=_to_single_result(data["target_result"]),
        equal=data["equal"],
        diff_detail=data["diff_detail"],
        enhanced_diff=data.get("enhanced_diff"),
        execution_time_ms=data["execution_time_ms"],
    )
