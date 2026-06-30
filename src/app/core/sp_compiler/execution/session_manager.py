"""
Session Manager — thread-safe registry for ``Session`` instances.

Replaces the scattered ``_sessions`` and ``_active_ws`` module-level dicts
in ``router.py``.  Provides:

    * create / get / remove lifecycle
    * Optional WebSocket binding (1:1 session ↔ WebSocket)
    * Stale-session cleanup (prevents unbounded memory growth)

Usage:
    from app.core.sp_compiler.execution.session_manager import SessionManager

    manager = SessionManager()
    session = manager.create_session("abc123")
    ...
    manager.remove_session("abc123")
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .session import Session


class SessionManager:
    """Thread-safe registry of execution sessions.

    Each session is identified by a unique ``session_id`` string.
    WebSocket connections are bound 1:1 to sessions — binding a new
    WebSocket to an existing session replaces the previous binding.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._ws_bindings: dict[str, Any] = {}  # session_id → WebSocket
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        graph_model: dict | None = None,
    ) -> Session:
        """Create a new session and register it.

        Args:
            session_id: Unique identifier for the session.
            graph_model: Optional CFG graph model dict.

        Returns:
            The newly created ``Session``.

        Raises:
            ValueError: If *session_id* is already registered.
        """
        with self._lock:
            if session_id in self._sessions:
                raise ValueError(
                    f"Session '{session_id}' already exists. "
                    f"Use get_session() to retrieve it."
                )
            session = Session(session_id=session_id, graph_model=graph_model)
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> Session | None:
        """Return the session for *session_id*, or ``None``."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(
        self,
        session_id: str,
        graph_model: dict | None = None,
    ) -> Session:
        """Return existing session or create a new one.

        This is the safe replacement for the old ``_get_or_create_tracer``
        function — it guarantees exactly one ``Session`` per ID.
        """
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
            return self.create_session(session_id, graph_model=graph_model)

    def remove_session(self, session_id: str) -> None:
        """Remove a session and its WebSocket binding.

        Idempotent — does nothing if *session_id* is not registered.
        """
        with self._lock:
            self._sessions.pop(session_id, None)
            self._ws_bindings.pop(session_id, None)

    # ------------------------------------------------------------------
    # WebSocket binding
    # ------------------------------------------------------------------

    def bind_websocket(self, session_id: str, websocket: Any) -> None:
        """Associate a WebSocket connection with a session.

        Only one WebSocket per session — binding a new one replaces any
        previous binding for that session.
        """
        with self._lock:
            self._ws_bindings[session_id] = websocket

    def unbind_websocket(self, session_id: str) -> None:
        """Remove the WebSocket binding for a session.

        Idempotent — does nothing if no binding exists.
        """
        with self._lock:
            self._ws_bindings.pop(session_id, None)

    def get_websocket(self, session_id: str) -> Any | None:
        """Return the bound WebSocket, or ``None``."""
        with self._lock:
            return self._ws_bindings.get(session_id)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_stale(self, max_age_seconds: float = 3600.0) -> int:
        """Remove sessions older than *max_age_seconds*.

        Sessions still in RUNNING or PAUSED state are skipped — only
        terminal (FAILED, COMPLETED) or INIT sessions are candidates.

        Returns:
            Number of sessions removed.
        """
        now = time.time()
        removed = 0
        with self._lock:
            stale_ids = []
            for sid, session in self._sessions.items():
                age = now - session.created_at
                if age > max_age_seconds and session.state in (
                    Session.state.__class__.INIT,
                    Session.state.__class__.COMPLETED,
                    Session.state.__class__.FAILED,
                ):
                    stale_ids.append(sid)

            for sid in stale_ids:
                self._sessions.pop(sid, None)
                self._ws_bindings.pop(sid, None)
                removed += 1

        return removed

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Number of registered sessions."""
        with self._lock:
            return len(self._sessions)

    @property
    def ws_count(self) -> int:
        """Number of active WebSocket bindings."""
        with self._lock:
            return len(self._ws_bindings)
