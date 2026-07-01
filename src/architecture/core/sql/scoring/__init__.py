"""
SQL Compatibility Scoring — modular scoring engine.

Four independent scoring dimensions:
    syntax.py    — Dialect syntax compatibility
    execution.py — Execution success rate
    result.py    — Result consistency
    risk.py      — Risk assessment

Each module exports a single scoring function returning (score, findings).
"""

from .syntax import syntax_score
from .execution import execution_score
from .result import result_score
from .risk import risk_score

__all__ = [
    "syntax_score",
    "execution_score",
    "result_score",
    "risk_score",
]
