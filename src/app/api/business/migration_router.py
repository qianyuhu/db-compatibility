"""Migration API Router — ERP 迁移流水线端点。"""

from fastapi import APIRouter

from app.services.migration_service import MigrationService

from .schemas import (
    MigrationPhaseSummary,
    MigrationPipelineResponse,
    MigrationRunRequest,
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
