"""
Execution Validator — validates compiled SPs against real database execution.

Uses the existing DBAdapter infrastructure (sandbox/adapter/) to execute
both the original MSSQL SP and the compiled target SP, then compares results
using the existing DiffEngine.
"""

from .diff_engine import SPValidator, SPExecutionDiff

__all__ = [
    "SPValidator",
    "SPExecutionDiff",
]
