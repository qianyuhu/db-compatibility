"""
Event Store — append-only event log for event sourcing.

Each session has one ``EventStore``.  State changes are recorded as
immutable ``EventStoreEntry`` rows and the current ``SessionState`` can be
derived by folding the log through ``SessionStateMachine``.

Usage:
    from app.core.sp_compiler.execution.event_store import EventStore

    store = EventStore(session_id="abc123")
    store.append("session_started")
    store.append("node_started", node_id="B0_N0")
    store.append("node_finished", node_id="B0_N0", data={"status": "success"})

    assert store.fold() == SessionState.RUNNING
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .state import (
    EventType,
    SessionState,
    SessionStateMachine,
)


@dataclass(frozen=True)
class EventStoreEntry:
    """A single immutable event in the session log.

    Attributes:
        event_type: The canonical event type string (e.g. ``"node_started"``).
        session_id: Owning session.
        sequence: Monotonic counter starting at 1.
        timestamp: Unix epoch when the event was recorded.
        node_id: The affected node, if any.
        data: Optional payload (e.g. execution result, error message).
    """

    event_type: str
    session_id: str
    sequence: int
    timestamp: float
    node_id: str | None = None
    data: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable representation."""
        result: dict[str, Any] = {
            "event_type": self.event_type,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
        }
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.data is not None:
            result["data"] = self.data
        return result


class EventStore:
    """Append-only event log for one session.

    Not thread-safe — a session is expected to be the unit of concurrency
    isolation (single-threaded execution per session).

    Attributes:
        session_id: The session this store belongs to.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id: str = session_id
        self._entries: list[EventStoreEntry] = []
        self._sequence: int = 0

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: str,
        node_id: str | None = None,
        data: dict | None = None,
    ) -> EventStoreEntry:
        """Record a new event and return the immutable entry.

        Args:
            event_type: Canonical event type (use ``EventType`` values).
            node_id: The affected UI node, if applicable.
            data: Optional payload dictionary.

        Returns:
            The newly created ``EventStoreEntry``.
        """
        self._sequence += 1
        entry = EventStoreEntry(
            event_type=event_type,
            session_id=self.session_id,
            sequence=self._sequence,
            timestamp=time.time(),
            node_id=node_id,
            data=data,
        )
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_entries(self) -> list[EventStoreEntry]:
        """Return all entries in insertion order (defensive copy)."""
        return list(self._entries)

    def get_entries_since(self, sequence: int) -> list[EventStoreEntry]:
        """Return entries with ``sequence > *sequence*``.

        Useful for incremental replay — a client that has seen up to
        sequence N only needs events N+1 and beyond.
        """
        return [e for e in self._entries if e.sequence > sequence]

    # ------------------------------------------------------------------
    # Derivation (event sourcing)
    # ------------------------------------------------------------------

    def fold(self) -> SessionState:
        """Reconstruct the current ``SessionState`` by replaying all
        session-level events through ``SessionStateMachine``.

        Only events that affect the session-level state machine are
        considered (``SESSION_CREATED``, ``SESSION_STARTED``, etc.).
        Node-level events are skipped during folding.
        """
        state = SessionState.INIT
        session_events = {
            EventType.SESSION_CREATED,
            EventType.SESSION_STARTED,
            EventType.SESSION_PAUSED,
            EventType.SESSION_RESUMED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
        }
        for entry in self._entries:
            if entry.event_type in session_events:
                event = EventType(entry.event_type)
                try:
                    state = SessionStateMachine.transition(state, event)
                except ValueError:
                    # If we hit an invalid transition during fold the log
                    # is inconsistent — return the best-effort state.
                    pass
        return state

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def event_count(self) -> int:
        """Total number of recorded events."""
        return len(self._entries)

    @property
    def last_sequence(self) -> int:
        """The sequence number of the most recent entry (0 if empty)."""
        return self._sequence
