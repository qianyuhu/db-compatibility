"""
Event Bus — fan-out event delivery for execution engine events.

Replaces the single-callback pattern with a multi-subscriber design so the
execution engine, tracer, and WebSocket forwarder can all observe events
without mutating each other's state.

Usage:
    from architecture.core.sql.compiler.execution.event_bus import EventBus

    bus = EventBus()
    unsub = bus.subscribe(tracer.on_event)
    bus.subscribe(ws_forward)
    engine = ExecutionEngine(target_dbs=..., event_bus=bus)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .state import EventType

# Matches ExecutionEngine.EventCallback signature
EventListener = Callable[[str, str, dict | None], None]


class EventBus:
    """Fan-out event delivery with multiple subscribers.

    Each subscriber is a callable with signature:
        listener(event_type: str, node_id: str, data: dict | None) -> None

    Subscribers are called in registration order. Exceptions in one
    subscriber do not prevent other subscribers from receiving the event.

    Not thread-safe — intended for single-session, synchronous usage.
    """

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Register a listener. Returns an unsubscribe function.

        >>> bus = EventBus()
        >>> unsub = bus.subscribe(lambda t, n, d: print(t, n))
        >>> unsub()  # remove the listener
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass  # Already removed

        return unsubscribe

    def emit(self, event_type: str, node_id: str, data: dict | None = None) -> None:
        """Deliver an event to all registered listeners.

        Args:
            event_type: "node_started" | "node_finished" | "node_failed"
            node_id: The UINode ID.
            data: Optional event payload.
        """
        for listener in self._listeners:
            try:
                listener(event_type, node_id, data)
            except Exception:
                pass  # Don't let one failing listener break others

    def emit_event(
        self,
        event_type: EventType,
        node_id: str = "",
        data: dict | None = None,
    ) -> None:
        """Typed variant of ``emit()`` that accepts ``EventType`` enum values.

        Delegates to ``emit()`` using ``event_type.value`` so existing
        listeners see the same string-based event types they always have.

        Args:
            event_type: An ``EventType`` enum member.
            node_id: The UINode ID (empty string for session-level events).
            data: Optional event payload.
        """
        self.emit(event_type.value, node_id, data)

    def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()

    @property
    def listener_count(self) -> int:
        """Number of registered listeners."""
        return len(self._listeners)
