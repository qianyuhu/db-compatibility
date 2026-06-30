"""
Execution Tracer — records all node execution events for replay and debugging.

Every node_started, node_finished, and node_failed event is recorded with
timestamps. The trace can be retrieved for replay in the UI or analyzed for
performance bottlenecks.

Usage:
    from app.core.sp_compiler.execution.tracer import ExecutionTracer

    tracer = ExecutionTracer(session_id="abc123")
    engine = ExecutionEngine(event_callback=tracer.on_event)
    # ... execute nodes ...
    trace = tracer.get_trace()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEntry:
    """A single event in the execution trace.

    Attributes:
        event_type: "node_started" | "node_finished" | "node_failed"
        node_id: The UINode ID that emitted this event.
        timestamp: Unix timestamp (seconds) when the event occurred.
        data: Optional event data (node result on finished, error on failed).
    """
    event_type: str
    node_id: str
    timestamp: float
    data: dict | None = None


class ExecutionTracer:
    """Records all execution events for a session.

    Acts as the event_callback for ExecutionEngine. Each event becomes a
    TraceEntry. The full trace can be serialized for replay or storage.

    Not thread-safe — intended for single-session, single-thread usage.
    """

    def __init__(self, session_id: str = "") -> None:
        """Initialize the tracer.

        Args:
            session_id: Unique session identifier for this trace.
        """
        self.session_id = session_id
        self.entries: list[TraceEntry] = []
        self.started_at: float | None = None
        self.completed_at: float | None = None
        self._node_order: list[str] = []  # ordered list of executed node IDs

    # ------------------------------------------------------------------
    # Event callback (matching ExecutionEngine.EventCallback signature)
    # ------------------------------------------------------------------

    def on_event(self, event_type: str, node_id: str, data: dict | None = None) -> None:
        """Record an execution event.

        This method matches the EventCallback protocol:
            callback(event_type: str, node_id: str, data: dict | None)

        Args:
            event_type: "node_started" | "node_finished" | "node_failed"
            node_id: The UINode ID.
            data: Optional event data payload.
        """
        now = time.time()

        if self.started_at is None and event_type == "node_started":
            self.started_at = now

        entry = TraceEntry(
            event_type=event_type,
            node_id=node_id,
            timestamp=now,
            data=data,
        )
        self.entries.append(entry)

        if event_type in ("node_finished", "node_failed"):
            if node_id not in self._node_order:
                self._node_order.append(node_id)
            self.completed_at = now

    # ------------------------------------------------------------------
    # Trace retrieval
    # ------------------------------------------------------------------

    def get_trace(self) -> dict:
        """Return the full execution trace as a JSON-serializable dict.

        Returns:
            Dict with session info and ordered event list.
        """
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_events": len(self.entries),
            "nodes_executed": len(self._node_order),
            "node_order": list(self._node_order),
            "events": [
                {
                    "event_type": e.event_type,
                    "node_id": e.node_id,
                    "timestamp": e.timestamp,
                    "data": _serialize_data(e.data),
                }
                for e in self.entries
            ],
        }

    def get_summary(self) -> dict:
        """Return a lightweight trace summary for the timeline UI."""
        return {
            "session_id": self.session_id,
            "nodes_executed": len(self._node_order),
            "total_events": len(self.entries),
            "node_order": list(self._node_order),
            "event_counts": {
                "started": sum(1 for e in self.entries if e.event_type == "node_started"),
                "finished": sum(1 for e in self.entries if e.event_type == "node_finished"),
                "failed": sum(1 for e in self.entries if e.event_type == "node_failed"),
            },
            "events": [
                {
                    "event_type": e.event_type,
                    "node_id": e.node_id,
                    "timestamp": e.timestamp,
                }
                for e in self.entries
            ],
        }

    def reset(self) -> None:
        """Clear all trace data for a new execution run."""
        self.entries.clear()
        self._node_order.clear()
        self.started_at = None
        self.completed_at = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_data(data: dict | None) -> dict | None:
    """Convert trace event data to JSON-serializable form.

    Handles dataclass instances by converting them to dicts.
    """
    if data is None:
        return None
    result: dict = {}
    for key, value in data.items():
        if hasattr(value, '__dataclass_fields__'):
            # Convert dataclass instance to dict
            result[key] = {
                f.name: _serialize_value(getattr(value, f.name))
                for f in value.__dataclass_fields__.values()
            }
        else:
            result[key] = _serialize_value(value)
    return result


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON."""
    if hasattr(value, '__dataclass_fields__'):
        return {
            f.name: _serialize_value(getattr(value, f.name))
            for f in value.__dataclass_fields__.values()
        }
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return value
