"""
SQL Compatibility Score Engine.

Evaluates SQL compatibility (0-100) across MSSQL / KingbaseES / DM8
using four scoring dimensions: syntax, execution, result, and risk.
"""

from .score_schemas import Finding, ScoreBreakdown, ScoreRequest, ScoreResponse
from .score_service import calculate_score

__all__ = [
    "calculate_score",
    "ScoreRequest",
    "ScoreResponse",
    "ScoreBreakdown",
    "Finding",
]
