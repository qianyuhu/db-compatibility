"""
Showcase API Router — endpoints for the Migration Capability Showcase.

Endpoints:
    GET  /api/showcase/scenes           — list all demo scenes
    POST /api/showcase/execute/{id}     — execute a scene across all 3 DBs
    POST /api/showcase/reset            — reset sandbox data on all DBs
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.showcase.engine import execute_scene, reset_showcase_data
from app.showcase.scenes import ALL_SCENES, ShowcaseScene

router = APIRouter(prefix="/api/showcase", tags=["showcase"])


# =========================================================================
# Response models
# =========================================================================


class SceneListItem(BaseModel):
    """Scene metadata returned by the list endpoint (no execution)."""

    scene_id: str
    scene_name: str
    type: str
    description: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    migration_insight: str = ""
    key_differences: list[str] = Field(default_factory=list)


class SceneListResponse(BaseModel):
    """List of all available showcase scenes."""

    total: int
    scenes: list[SceneListItem]


class ResetResponse(BaseModel):
    """Response from the reset endpoint."""

    success: bool
    results: dict[str, Any] = Field(default_factory=dict)


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/scenes", response_model=SceneListResponse)
def list_scenes(type: str | None = None):
    """List all available demo scenes.

    Query params:
        type: Filter by type (SQL | API | ORM). Omit for all scenes.
    """
    scenes: list[ShowcaseScene] = ALL_SCENES
    if type and type in ("SQL", "API", "ORM"):
        scenes = [s for s in ALL_SCENES if s.type == type]

    return SceneListResponse(
        total=len(scenes),
        scenes=[SceneListItem(**s.to_dict()) for s in scenes],
    )


@router.post("/execute/{scene_id}")
def execute_showcase_scene(scene_id: str):
    """Execute a demo scene across MSSQL, KingbaseES, and DM8.

    Executes the scene's SQL/API/ORM operation on all 3 databases
    in parallel, computes diffs, and returns structured results
    with side-by-side comparison data.

    Path params:
        scene_id: Scene identifier (e.g. "sql_case_when")
    """
    result = execute_scene(scene_id)
    return result


@router.post("/reset", response_model=ResetResponse)
def reset_showcase():
    """Reset sandbox data on all 3 databases to deterministic state.

    Truncates and re-seeds customers, products, orders, order_items,
    and inventory tables on MSSQL, KingbaseES, and DM8.
    """
    result = reset_showcase_data()
    return ResetResponse(**result)
