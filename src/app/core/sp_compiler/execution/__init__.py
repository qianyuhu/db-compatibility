"""
Execution Engine — CFG node execution, event delivery, and trace recording.

Provides:
    - EventBus: fan-out event delivery for multi-subscriber architectures
    - EventStore: append-only event sourcing log per session
    - ExecutionEngine: executes CFG/IR nodes against MSSQL/KingbaseES/DM8
    - ExecutionTracer: records all execution events for replay/debugging
    - Session: unified execution session owning all lifecycle resources
    - SessionManager: thread-safe session registry
    - State machines: SessionStateMachine, NodeStateMachine
    - State enums: SessionState, NodeState, EventType
    - Result types: NodeExecutionResult, DBResult, ExecutionDiff
"""

from .engine import (
    DBResult,
    ExecutionDiff,
    ExecutionEngine,
    NodeExecutionResult,
)
from .event_bus import EventBus
from .event_store import EventStore, EventStoreEntry
from .session import Session, VariableEnvironment
from .session_manager import SessionManager
from .state import (
    EventType,
    NodeState,
    NodeStateMachine,
    SessionState,
    SessionStateMachine,
)
from .tracer import ExecutionTracer, TraceEntry

__all__ = [
    # Event infrastructure
    "EventBus",
    "EventStore",
    "EventStoreEntry",
    # Engine + results
    "DBResult",
    "ExecutionDiff",
    "ExecutionEngine",
    "NodeExecutionResult",
    # Session
    "Session",
    "SessionManager",
    "VariableEnvironment",
    # State machine
    "EventType",
    "NodeState",
    "NodeStateMachine",
    "SessionState",
    "SessionStateMachine",
    # Tracer
    "ExecutionTracer",
    "TraceEntry",
]
