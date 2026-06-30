"""
CFG Workbench Router — REST + WebSocket API for the interactive CFG execution UI.

REST Endpoints:
    POST /api/cfg/compile        — Compile T-SQL → UIGraphModel
    POST /api/cfg/execute-node   — Execute a single CFG node
    POST /api/cfg/execute-all    — Execute all nodes in topological order
    GET  /api/cfg/trace/{id}     — Get execution trace for replay

WebSocket:
    WS   /api/cfg/ws/{session_id} — Real-time execution event stream
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from .rate_limiter import rate_limit, rate_limit_ws
from .schemas import (
    CompileRequest,
    CompileResponse,
    ExecuteAllRequest,
    ExecuteNodeRequest,
    ExecuteNodeResponse,
    TraceResponse,
)

router = APIRouter(prefix="/api/cfg", tags=["cfg-workbench"])

# ---------------------------------------------------------------------------
# WebSocket auth token
# ---------------------------------------------------------------------------

# Default token for demo/research use. Override via CFG_WS_TOKEN env var.
_WS_TOKEN: str | None = os.environ.get("CFG_WS_TOKEN")

# ---------------------------------------------------------------------------
# In-memory session store (trace data + active WebSocket connections)
# ---------------------------------------------------------------------------

# session_id → ExecutionTracer
_sessions: dict[str, Any] = {}

# session_id → WebSocket
_active_ws: dict[str, WebSocket] = {}


def _get_or_create_tracer(session_id: str):
    """Get or create an ExecutionTracer for a session."""
    from app.core.sp_compiler.execution.tracer import ExecutionTracer

    if session_id not in _sessions:
        _sessions[session_id] = ExecutionTracer(session_id=session_id)
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# REST: Compile T-SQL → UIGraphModel
# ---------------------------------------------------------------------------


@router.post("/compile", response_model=CompileResponse)
def compile_tsql(req: CompileRequest, request: Request) -> CompileResponse:
    """Compile a T-SQL stored procedure and return the CFG as a UI graph model.

    The response includes the complete UIGraphModel (nodes + edges) that the
    frontend React Flow canvas can render directly.
    """
    rate_limit(request, max_requests=30, window_seconds=60)

    try:
        from app.core.sp_compiler import compile_sp
        from app.core.sp_compiler.cfg import CFGBuilder, serialize_cfg

        result = compile_sp(req.tsql, target_db="kingbasees")

        if not result.success:
            return CompileResponse(
                success=False,
                errors=result.errors,
            )

        if result.ir is None:
            return CompileResponse(
                success=False,
                errors=["IR construction returned None"],
            )

        # Build CFG with branch-preserving edges
        cfg = CFGBuilder.build(result.ir)

        # Serialize to UI model
        ui_model = serialize_cfg(cfg, result.ir)

        return CompileResponse(
            success=True,
            graph_model=_dataclass_to_dict(ui_model),
            procedure_name=result.procedure_name,
            token_count=result.token_count,
            block_count=result.block_count,
            ir_node_count=result.ir_node_count,
        )

    except Exception as exc:
        return CompileResponse(
            success=False,
            errors=[f"Compilation error: {type(exc).__name__}: {exc}"],
        )


# ---------------------------------------------------------------------------
# REST: Execute a single CFG node
# ---------------------------------------------------------------------------


@router.post("/execute-node", response_model=ExecuteNodeResponse)
def execute_node(req: ExecuteNodeRequest, request: Request) -> ExecuteNodeResponse:
    """Execute a single CFG node against all target databases.

    The node is executed in parallel across all target DBs. Results and
    diffs are returned in the response.
    """
    rate_limit(request, max_requests=100, window_seconds=60)

    from app.core.sp_compiler.execution.engine import ExecutionEngine

    engine = ExecutionEngine(target_dbs=req.target_dbs)
    result = engine.execute_node(req.node)

    return ExecuteNodeResponse(
        node_id=result.node_id,
        status=result.status,
        results={
            db: {
                "db_type": r.db_type,
                "success": r.success,
                "columns": r.columns,
                "rows": r.rows,
                "row_count": r.row_count,
                "execution_time_ms": r.execution_time_ms,
                "error": r.error,
            }
            for db, r in result.results.items()
        },
        diff={
            "row_diff": result.diff.row_diff,
            "column_diff": result.diff.column_diff,
            "value_diffs": result.diff.value_diffs,
            "status": result.diff.status,
        } if result.diff else None,
        execution_time_ms=result.execution_time_ms,
    )


# ---------------------------------------------------------------------------
# REST: Execute all nodes in topological order
# ---------------------------------------------------------------------------


@router.post("/execute-all")
def execute_all(req: ExecuteAllRequest, request: Request) -> dict:
    """Execute all nodes in the graph model sequentially.

    Creates a new execution session, runs nodes in topological order,
    and returns the session ID for trace retrieval.

    Breakpoints are respected: execution pauses at marked nodes.
    For now, breakpoints are returned in the response so the frontend
    can handle pausing via step-by-step execution.
    """
    rate_limit(request, max_requests=30, window_seconds=60)

    session_id = str(uuid.uuid4())[:8]

    tracer = _get_or_create_tracer(session_id)
    tracer.reset()

    from app.core.sp_compiler.execution.engine import ExecutionEngine
    from app.core.sp_compiler.execution.event_bus import EventBus

    # Use EventBus for clean fan-out: tracer + any other subscribers
    bus = EventBus()
    bus.subscribe(tracer.on_event)

    engine = ExecutionEngine(
        target_dbs=req.target_dbs,
        event_bus=bus,
    )

    nodes = req.graph_model.get("nodes", [])
    breakpoints = set(req.breakpoints)
    results: list[dict] = []

    for node in nodes:
        node_id = node.get("id", "")
        if node_id in breakpoints:
            results.append({
                "node_id": node_id,
                "status": "paused",
                "results": {},
                "diff": None,
                "execution_time_ms": 0,
            })
            continue

        result = engine.execute_node(node)
        results.append({
            "node_id": result.node_id,
            "status": result.status,
            "results": {
                db: {
                    "db_type": r.db_type,
                    "success": r.success,
                    "columns": r.columns,
                    "rows": r.rows,
                    "row_count": r.row_count,
                    "execution_time_ms": r.execution_time_ms,
                    "error": r.error,
                }
                for db, r in result.results.items()
            },
            "diff": {
                "row_diff": result.diff.row_diff,
                "column_diff": result.diff.column_diff,
                "value_diffs": result.diff.value_diffs,
                "status": result.diff.status,
            } if result.diff else None,
            "execution_time_ms": result.execution_time_ms,
        })

    return {
        "session_id": session_id,
        "results": results,
        "trace": tracer.get_summary(),
    }


# ---------------------------------------------------------------------------
# REST: Get execution trace for replay
# ---------------------------------------------------------------------------


@router.get("/trace/{session_id}", response_model=TraceResponse)
def get_trace(session_id: str, request: Request) -> TraceResponse:
    """Retrieve the full execution trace for a session.

    The trace can be played back in the UI to replay the execution.
    """
    rate_limit(request, max_requests=60, window_seconds=60)

    tracer = _sessions.get(session_id)
    if tracer is None:
        return TraceResponse(
            session_id=session_id,
            trace={"error": "Session not found", "session_id": session_id},
        )

    return TraceResponse(
        session_id=session_id,
        trace=tracer.get_trace(),
    )


# ---------------------------------------------------------------------------
# WebSocket: Real-time execution event stream
# ---------------------------------------------------------------------------


@router.websocket("/ws/{session_id}")
async def ws_execution_events(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time execution event streaming.

    Authentication: pass ?token=<CFG_WS_TOKEN> in the query string.
    When CFG_WS_TOKEN is not set (default), the check is skipped.

    The frontend connects here to receive node_started, node_finished,
    and node_failed events as they happen during execution.

    Events are JSON messages:
        {"type": "node_started", "node_id": "B0_N0", "timestamp": 1234567890}
        {"type": "node_finished", "node_id": "B0_N0", "timestamp": ..., "result": {...}}
        {"type": "node_failed", "node_id": "B0_N0", "timestamp": ..., "error": "..."}
        {"type": "execution_complete", "timestamp": ...}
    """
    # --- Auth check ---
    if _WS_TOKEN is not None:
        token = websocket.query_params.get("token", "")
        if token != _WS_TOKEN:
            await websocket.close(code=4001, reason="Unauthorized: invalid or missing token")
            return

    await websocket.accept()
    _active_ws[session_id] = websocket

    # Set up event bus with tracer + WebSocket forwarder
    from app.core.sp_compiler.execution.event_bus import EventBus

    tracer = _get_or_create_tracer(session_id)
    bus = EventBus()

    # Tracer records all events
    bus.subscribe(tracer.on_event)

    # Capture the event loop for async send from sync listener
    import asyncio as _asyncio
    _loop = _asyncio.get_running_loop()

    # WebSocket forwarder pushes events to the client
    def ws_forward(event_type: str, node_id: str, data: dict | None = None) -> None:
        """Forward execution events to the WebSocket client as JSON.

        Schedules the async send on the event loop since EventBus
        listeners are synchronous. This is safe because we're always
        called from within the ws_execution_events async context.
        """
        try:
            message: dict[str, Any] = {
                "type": event_type,
                "node_id": node_id,
                "timestamp": time.time(),
            }
            if data:
                message["data"] = _dataclass_to_dict(data)
        except Exception:
            message = {
                "type": event_type,
                "node_id": node_id,
                "timestamp": time.time(),
            }
        # Fire-and-forget: schedule the WebSocket send on the running loop
        _loop.call_soon_threadsafe(
            lambda m=message: _asyncio.ensure_future(websocket.send_json(m))
        )

    unsub_ws = bus.subscribe(ws_forward)

    try:
        # Keep connection alive — the client sends commands or just listens
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            cmd = msg.get("command", "")
            if cmd == "execute-node":
                # Rate-limit WS commands
                if not rate_limit_ws(websocket, max_requests=100, window_seconds=60):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Rate limit exceeded. Slow down.",
                    })
                    continue

                # Execute a single node and stream results via WebSocket
                from app.core.sp_compiler.execution.engine import ExecutionEngine

                engine = ExecutionEngine(
                    target_dbs=msg.get("target_dbs", ["mssql", "kingbasees", "dm8"]),
                    event_bus=bus,
                )
                engine.execute_node(msg.get("node", {}))

            elif cmd == "ping":
                await websocket.send_json({"type": "pong"})

            elif cmd == "close":
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        unsub_ws()
        bus.clear()
        _active_ws.pop(session_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> dict:
    """Convert a dataclass instance to a plain dict for JSON serialization."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if hasattr(obj, '__dataclass_fields__'):
        result: dict = {}
        for f in obj.__dataclass_fields__.values():
            value = getattr(obj, f.name)
            if hasattr(value, '__dataclass_fields__'):
                result[f.name] = _dataclass_to_dict(value)
            elif isinstance(value, (list, tuple)):
                result[f.name] = [_dataclass_to_dict(v) for v in value]
            elif isinstance(value, dict):
                result[f.name] = {k: _dataclass_to_dict(v) for k, v in value.items()}
            else:
                result[f.name] = value
        return result
    return obj
