"""
Execution Engine — CFG node execution, event delivery, and trace recording.

Provides:
    - EventBus: fan-out event delivery for multi-subscriber architectures
    - ExecutionEngine: executes CFG/IR nodes against MSSQL/KingbaseES/DM8
    - ExecutionTracer: records all execution events for replay/debugging
    - Result types: NodeExecutionResult, DBResult, ExecutionDiff
"""

from .event_bus import EventBus
from .engine import (
    DBResult,
    ExecutionDiff,
    ExecutionEngine,
    NodeExecutionResult,
)
from .tracer import ExecutionTracer, TraceEntry

__all__ = [
    "EventBus",
    "DBResult",
    "ExecutionDiff",
    "ExecutionEngine",
    "ExecutionTracer",
    "NodeExecutionResult",
    "TraceEntry",
]
