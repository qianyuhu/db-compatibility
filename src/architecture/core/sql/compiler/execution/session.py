"""
Session — unified execution session owning all lifecycle resources.

Replaces the scattered ``_sessions`` tracer dict, ``_active_ws`` WebSocket
dict, and ad-hoc ``_get_or_create_tracer()`` helper.  A ``Session`` is the
single owner of:

    * Tracer (event recording)
    * EventBus (in-process pub/sub)
    * EventStore (append-only event sourcing log)
    * VariableEnvironment (mutable variable state for IF/WHILE/ASSIGN)
    * ExecutionEngine (created lazily)
    * Graph model, breakpoints, step position, node order

All state transitions are validated through ``SessionStateMachine`` and
``NodeStateMachine``.  The ``EventStore`` is the source of truth — current
state can always be reconstructed by folding the event log.

Usage:
    from architecture.core.sql.compiler.execution.session import Session

    session = Session(session_id="abc123", graph_model=model)
    session.start()
    session.start_node("B0_N0")
    session.finish_node("B0_N0", data={"result": ...})
    session.complete()

    # Reconstruct from events
    restored = Session.replay("abc123", session.event_store.get_entries())
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .event_bus import EventBus
from .event_store import EventStore, EventStoreEntry
from .state import (
    EventType,
    NodeState,
    NodeStateMachine,
    SessionState,
    SessionStateMachine,
)
from .tracer import ExecutionTracer

if TYPE_CHECKING:
    from .engine import ExecutionEngine


# ---------------------------------------------------------------------------
# Variable Environment — lightweight in-memory variable store
# ---------------------------------------------------------------------------


@dataclass
class _Variable:
    name: str
    value: str | int | float | None = None
    data_type: str = "VARCHAR"


class VariableEnvironment:
    """In-memory variable state for IF/WHILE/ASSIGN node evaluation.

    Follows the immutable-update pattern — every ``set()`` returns a new
    ``VariableEnvironment`` rather than mutating in place.  (In practice
    the Session holds a single instance and replaces it on each assign.)
    """

    def __init__(self) -> None:
        self._vars: dict[str, _Variable] = {}

    def set(
        self,
        name: str,
        value: str | int | float | None,
        data_type: str = "VARCHAR",
    ) -> VariableEnvironment:
        """Return a new ``VariableEnvironment`` with *name* set to *value*."""
        new = VariableEnvironment()
        new._vars = dict(self._vars)
        new._vars[name] = _Variable(name=name, value=value, data_type=data_type)
        return new

    def get(self, name: str) -> _Variable | None:
        """Return the variable, or ``None`` if not set."""
        return self._vars.get(name)

    def snapshot(self) -> dict[str, dict]:
        """JSON-serializable snapshot of all variables."""
        return {
            name: {"value": var.value, "data_type": var.data_type}
            for name, var in self._vars.items()
        }


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """Unified execution session.

    Owns all state for one CFG execution run.  The ``EventStore`` is the
    authoritative source of truth — ``Session.state`` and ``node_states``
    are derived caches that must always agree with ``event_store.fold()``
    and per-node event replay.
    """

    session_id: str
    state: SessionState = SessionState.INIT
    node_states: dict[str, NodeState] = field(default_factory=dict)

    # Owned resources
    tracer: ExecutionTracer = field(default_factory=lambda: ExecutionTracer(""))
    event_bus: EventBus = field(default_factory=EventBus)
    variable_env: VariableEnvironment = field(default_factory=VariableEnvironment)

    # Set after __post_init__
    event_store: EventStore = field(init=False)

    # Optional / late-bound
    engine: Any = None          # ExecutionEngine (lazy to avoid circular import)
    graph_model: dict | None = None
    breakpoints: set[str] = field(default_factory=set)
    current_step: int = 0
    node_order: list[str] = field(default_factory=list)
    websocket: Any = None       # WebSocket connection (set by router)

    # Metadata
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def __post_init__(self) -> None:
        """Wire up EventStore, Tracer, and record SESSION_CREATED."""
        object.__setattr__(self, "event_store", EventStore(self.session_id))
        self.event_store.append(EventType.SESSION_CREATED.value)

        # Ensure tracer has the correct session_id and is subscribed
        self.tracer.session_id = self.session_id
        self.event_bus.subscribe(self.tracer.on_event)

    # ==================================================================
    # Session Lifecycle
    # ==================================================================

    def start(self) -> None:
        """INIT → RUNNING.  Call before executing the first node."""
        self._session_transition(EventType.SESSION_STARTED)
        self.started_at = time.time()

    def pause(self) -> None:
        """RUNNING → PAUSED.  Called when a breakpoint is hit."""
        self._session_transition(EventType.SESSION_PAUSED)

    def resume(self) -> None:
        """PAUSED → RUNNING.  Called when the user resumes from a breakpoint."""
        self._session_transition(EventType.SESSION_RESUMED)

    def complete(self) -> None:
        """RUNNING | PAUSED → COMPLETED.  All nodes have been processed."""
        self._session_transition(EventType.SESSION_COMPLETED)
        self.completed_at = time.time()

    def fail(self, error: str | None = None) -> None:
        """RUNNING | PAUSED → FAILED.  Execution terminated by an error."""
        data = {"error": error} if error else None
        self._session_transition(EventType.SESSION_FAILED, data)
        self.completed_at = time.time()

    # ==================================================================
    # Node Lifecycle
    # ==================================================================

    def init_node_states(self, node_ids: list[str]) -> None:
        """Initialize all node states to PENDING.

        Called once after the graph model is attached, before execution begins.
        """
        for nid in node_ids:
            if nid not in self.node_states:
                self.node_states[nid] = NodeState.PENDING

    def start_node(self, node_id: str) -> None:
        """PENDING → RUNNING."""
        self._node_transition(node_id, EventType.NODE_STARTED)
        # Also emit through event bus so WS listeners see it
        self.event_bus.emit(EventType.NODE_STARTED.value, node_id)

    def finish_node(self, node_id: str, data: dict | None = None) -> None:
        """RUNNING → SUCCESS."""
        self._node_transition(node_id, EventType.NODE_FINISHED, data)
        self.event_bus.emit(EventType.NODE_FINISHED.value, node_id, data)
        self._record_node_order(node_id)

    def fail_node(self, node_id: str, error: str | None = None) -> None:
        """RUNNING → FAILED."""
        err_data = {"error": error} if error else None
        self._node_transition(node_id, EventType.NODE_FAILED, err_data)
        self.event_bus.emit(EventType.NODE_FAILED.value, node_id, err_data)
        self._record_node_order(node_id)

    def skip_node(self, node_id: str, reason: str = "") -> None:
        """PENDING | RUNNING → SKIPPED (not executable, or at breakpoint)."""
        data = {"reason": reason} if reason else None
        self._node_transition(node_id, EventType.NODE_SKIPPED, data)
        self.event_bus.emit(EventType.NODE_SKIPPED.value, node_id, data)
        self._record_node_order(node_id)

    # ==================================================================
    # Execution Control
    # ==================================================================

    def is_at_breakpoint(self, node_id: str) -> bool:
        """True if *node_id* has an active breakpoint."""
        return node_id in self.breakpoints

    def advance_step(self) -> int:
        """Increment and return the step counter."""
        self.current_step += 1
        return self.current_step

    def should_continue(self) -> bool:
        """True if execution may proceed (not terminal, not manually stopped)."""
        return not SessionStateMachine.is_terminal(self.state)

    # ==================================================================
    # Event Sourcing — Replay
    # ==================================================================

    @staticmethod
    def replay(
        session_id: str,
        entries: list[EventStoreEntry],
    ) -> Session:
        """Reconstruct a ``Session`` by folding event log entries.

        This is a pure function — no side effects, no network calls.
        The returned ``Session`` has derived ``state`` and ``node_states``
        but no active WebSocket, engine, or event bus subscriptions.
        """
        session = Session(session_id=session_id)
        # Clear the auto-created SESSION_CREATED entry so we don't double-count
        session.event_store._entries.clear()
        session.event_store._sequence = 0

        for entry in entries:
            # Replay into event store
            session.event_store.append(
                entry.event_type,
                node_id=entry.node_id,
                data=entry.data,
            )

            event_type_str = entry.event_type
            try:
                event = EventType(event_type_str)
            except ValueError:
                continue  # Unknown event type — skip silently

            # Session-level events
            if event in (
                EventType.SESSION_CREATED,
                EventType.SESSION_STARTED,
                EventType.SESSION_PAUSED,
                EventType.SESSION_RESUMED,
                EventType.SESSION_COMPLETED,
                EventType.SESSION_FAILED,
            ):
                try:
                    session.state = SessionStateMachine.transition(
                        session.state, event
                    )
                except ValueError:
                    pass

            # Node-level events
            elif event in (
                EventType.NODE_STARTED,
                EventType.NODE_FINISHED,
                EventType.NODE_FAILED,
                EventType.NODE_SKIPPED,
            ):
                node_id = entry.node_id
                if node_id is None:
                    continue

                current = session.node_states.get(node_id, NodeState.PENDING)
                try:
                    session.node_states[node_id] = NodeStateMachine.transition(
                        current, event
                    )
                except ValueError:
                    pass

            if entry.node_id and entry.node_id not in session.node_order:
                session.node_order.append(entry.node_id)

        return session

    def get_replay_data(self) -> dict:
        """JSON-serializable replay data matching frontend expectations.

        Returns a dict with ``session_id``, ``state``, and ordered ``events``
        where each event carries ``event_type``, ``node_id``, ``timestamp``,
        and optional ``data``.
        """
        entries = self.event_store.get_entries()
        return {
            "session_id": self.session_id,
            "state": self.state.name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_events": len(entries),
            "events": [e.as_dict() for e in entries],
        }

    # ==================================================================
    # Internal Helpers
    # ==================================================================

    def _session_transition(
        self,
        event: EventType,
        data: dict | None = None,
    ) -> None:
        """Validate and perform a session-level state transition.

        Appends to the EventStore and emits through the EventBus so all
        subscribers (tracer, WebSocket forwarder) see the change.
        """
        self.state = SessionStateMachine.transition(self.state, event)
        self.event_store.append(event.value, data=data)
        self.event_bus.emit(event.value, "", data)

    def _node_transition(
        self,
        node_id: str,
        event: EventType,
        data: dict | None = None,
    ) -> None:
        """Validate and perform a node-level state transition.

        Updates the in-memory ``node_states`` cache and appends to the
        EventStore.  Does NOT emit through EventBus (callers are expected
        to call ``event_bus.emit()`` after this if they want subscribers
        notified).
        """
        current = self.node_states.get(node_id, NodeState.PENDING)
        self.node_states[node_id] = NodeStateMachine.transition(current, event)
        self.event_store.append(event.value, node_id=node_id, data=data)

    def _record_node_order(self, node_id: str) -> None:
        """Record node execution order (deduplicated)."""
        if node_id not in self.node_order:
            self.node_order.append(node_id)
