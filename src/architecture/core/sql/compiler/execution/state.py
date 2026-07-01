"""
Execution State Machine — canonical state definitions and transition rules.

All session and node state transitions are validated through the static
methods on ``SessionStateMachine`` and ``NodeStateMachine``. No other module
should mutate state directly — always route through these validators.

Usage:
    from architecture.core.sql.compiler.execution.state import (
        SessionState, NodeState, EventType,
        SessionStateMachine, NodeStateMachine,
    )

    new_state = SessionStateMachine.transition(SessionState.INIT, EventType.SESSION_STARTED)
    assert new_state == SessionState.RUNNING
"""

from __future__ import annotations

from enum import Enum, auto


class SessionState(Enum):
    """Top-level session lifecycle states."""

    INIT = auto()       # Created, not yet started
    RUNNING = auto()    # Execution in progress
    PAUSED = auto()     # Suspended at a breakpoint
    FAILED = auto()     # Terminated by error (terminal)
    COMPLETED = auto()  # All nodes executed (terminal)


class NodeState(Enum):
    """Per-node execution states."""

    PENDING = auto()   # Not yet visited
    RUNNING = auto()   # Currently executing
    SUCCESS = auto()   # Completed successfully
    FAILED = auto()    # Completed with error
    SKIPPED = auto()   # Not executable (e.g. IF condition, breakpoint skip)


class EventType(str, Enum):
    """Canonical event types.

    Inherits from both ``str`` and ``Enum`` so enum values can be used
    interchangeably with the string-based event system in ``EventBus``.
    """

    SESSION_CREATED   = "session_created"
    SESSION_STARTED   = "session_started"
    NODE_STARTED      = "node_started"
    NODE_FINISHED     = "node_finished"
    NODE_FAILED       = "node_failed"
    NODE_SKIPPED      = "node_skipped"
    SESSION_PAUSED    = "session_paused"
    SESSION_RESUMED   = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED    = "session_failed"


# ---------------------------------------------------------------------------
# Transition tables — (current_state, event) → new_state
# ---------------------------------------------------------------------------

_SESSION_TRANSITIONS: dict[tuple[SessionState, EventType], SessionState] = {
    # INIT → RUNNING (start execution)
    (SessionState.INIT, EventType.SESSION_STARTED): SessionState.RUNNING,

    # RUNNING → PAUSED / COMPLETED / FAILED
    (SessionState.RUNNING, EventType.SESSION_PAUSED):    SessionState.PAUSED,
    (SessionState.RUNNING, EventType.SESSION_COMPLETED): SessionState.COMPLETED,
    (SessionState.RUNNING, EventType.SESSION_FAILED):    SessionState.FAILED,

    # PAUSED → RUNNING / COMPLETED / FAILED
    (SessionState.PAUSED, EventType.SESSION_RESUMED):   SessionState.RUNNING,
    (SessionState.PAUSED, EventType.SESSION_COMPLETED): SessionState.COMPLETED,
    (SessionState.PAUSED, EventType.SESSION_FAILED):    SessionState.FAILED,
}

_NODE_TRANSITIONS: dict[tuple[NodeState, EventType], NodeState] = {
    # PENDING → RUNNING (start execution) or SKIPPED (breakpoint / not executable)
    (NodeState.PENDING, EventType.NODE_STARTED):  NodeState.RUNNING,
    (NodeState.PENDING, EventType.NODE_SKIPPED):  NodeState.SKIPPED,

    # RUNNING → SUCCESS / FAILED / SKIPPED
    (NodeState.RUNNING, EventType.NODE_FINISHED): NodeState.SUCCESS,
    (NodeState.RUNNING, EventType.NODE_FAILED):   NodeState.FAILED,
    (NodeState.RUNNING, EventType.NODE_SKIPPED):  NodeState.SKIPPED,
}

# Terminal states — once entered, no further transitions are valid
_SESSION_TERMINAL: frozenset[SessionState] = frozenset({
    SessionState.FAILED,
    SessionState.COMPLETED,
})

_NODE_TERMINAL: frozenset[NodeState] = frozenset({
    NodeState.SUCCESS,
    NodeState.FAILED,
    NodeState.SKIPPED,
})


class SessionStateMachine:
    """Validate and perform session-level state transitions."""

    @staticmethod
    def allowed_events(state: SessionState) -> list[EventType]:
        """Return the list of event types valid from *state*."""
        if state in _SESSION_TERMINAL:
            return []
        return [
            event
            for (s, event) in _SESSION_TRANSITIONS
            if s == state
        ]

    @staticmethod
    def transition(state: SessionState, event: EventType) -> SessionState:
        """Return the new state after *event*, or raise ``ValueError``.

        Raises:
            ValueError: If the transition is not valid from *state*.
        """
        key = (state, event)
        if key not in _SESSION_TRANSITIONS:
            allowed = SessionStateMachine.allowed_events(state)
            raise ValueError(
                f"Invalid session transition: {state.name} + {event.value} → ?. "
                f"Allowed events: {[e.value for e in allowed]}"
            )
        return _SESSION_TRANSITIONS[key]

    @staticmethod
    def is_terminal(state: SessionState) -> bool:
        """Return True if *state* is a terminal (absorbing) state."""
        return state in _SESSION_TERMINAL


class NodeStateMachine:
    """Validate and perform node-level state transitions."""

    @staticmethod
    def allowed_events(state: NodeState) -> list[EventType]:
        """Return the list of event types valid from *state*."""
        if state in _NODE_TERMINAL:
            return []
        return [
            event
            for (s, event) in _NODE_TRANSITIONS
            if s == state
        ]

    @staticmethod
    def transition(state: NodeState, event: EventType) -> NodeState:
        """Return the new node state after *event*, or raise ``ValueError``.

        Raises:
            ValueError: If the transition is not valid from *state*.
        """
        key = (state, event)
        if key not in _NODE_TRANSITIONS:
            allowed = NodeStateMachine.allowed_events(state)
            raise ValueError(
                f"Invalid node transition: {state.name} + {event.value} → ?. "
                f"Allowed events: {[e.value for e in allowed]}"
            )
        return _NODE_TRANSITIONS[key]

    @staticmethod
    def is_terminal(state: NodeState) -> bool:
        """Return True if *state* is a terminal (absorbing) state."""
        return state in _NODE_TERMINAL
