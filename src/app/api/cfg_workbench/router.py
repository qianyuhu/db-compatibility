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
# Session manager — replaces _sessions / _active_ws dicts
# ---------------------------------------------------------------------------

from app.core.sp_compiler.execution.session_manager import SessionManager
from app.core.sp_compiler.execution.state import (
    EventType,
    NodeState,
    SessionState,
)

_session_manager = SessionManager()


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
# REST: Execute a single CFG node (deprecated — use execute-all)
# ---------------------------------------------------------------------------


@router.post("/execute-node", response_model=ExecuteNodeResponse)
def execute_node(req: ExecuteNodeRequest, request: Request) -> ExecuteNodeResponse:
    """Single-node execution is deprecated.

    Use /execute-all to compile, create, and execute the stored procedure
    across all target databases.
    """
    rate_limit(request, max_requests=100, window_seconds=60)

    return ExecuteNodeResponse(
        node_id=req.node.get("id", "unknown"),
        status="skipped",
        results={},
        diff=None,
        execution_time_ms=0.0,
    )


# ---------------------------------------------------------------------------
# REST: Execute stored procedure across all target databases
# ---------------------------------------------------------------------------


@router.post("/execute-all")
def execute_all(req: ExecuteAllRequest, request: Request) -> dict:
    """Compile, create, and execute the stored procedure on all target DBs.

    Extracts the original T-SQL from the graph model, compiles it for each
    target dialect, creates the procedure on each DB, executes it, and
    compares results across databases.
    """
    rate_limit(request, max_requests=30, window_seconds=60)

    session_id = str(uuid.uuid4())[:8]
    session = _session_manager.create_session(
        session_id=session_id,
        graph_model=req.graph_model,
    )

    from app.core.sp_compiler.execution.engine import ExecutionEngine

    nodes = req.graph_model.get("nodes", [])
    node_ids = [n.get("id", "") for n in nodes]
    original_tsql = req.graph_model.get("original_tsql", "")
    proc_name = req.graph_model.get("procedure_name", "migrated_sp")

    session.init_node_states(node_ids)
    engine = ExecutionEngine.for_session(session, target_dbs=req.target_dbs)

    results: list[dict] = []

    try:
        session.start()

        if not original_tsql:
            raise ValueError("No original_tsql found in graph model")

        # Execute the whole procedure across all target DBs
        node_results = engine.execute_procedure(
            original_tsql=original_tsql,
            proc_name=proc_name,
            node_ids=node_ids,
        )

        # Map results back to CFG nodes
        # First result is the __procedure__ result; rest are per-node
        proc_result = node_results[0] if node_results else None

        for nid in node_ids:
            session.start_node(nid)
            if proc_result:
                if proc_result.status == "success":
                    session.finish_node(nid, data=_result_to_dict(proc_result))
                else:
                    session.fail_node(nid, error=_extract_error(proc_result))
                session.advance_step()

            results.append({
                "node_id": nid,
                "status": proc_result.status if proc_result else "failed",
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
                    for db, r in (proc_result.results if proc_result else {}).items()
                },
                "diff": {
                    "row_diff": proc_result.diff.row_diff,
                    "column_diff": proc_result.diff.column_diff,
                    "value_diffs": proc_result.diff.value_diffs,
                    "status": proc_result.diff.status,
                } if proc_result and proc_result.diff else None,
                "execution_time_ms": proc_result.execution_time_ms if proc_result else 0,
            })

        session.complete()

    except Exception as exc:
        session.fail(error=str(exc))
        results.append({
            "node_id": "__session__",
            "status": "failed",
            "results": {},
            "diff": None,
            "execution_time_ms": 0,
            "error": str(exc),
        })

    return {
        "session_id": session_id,
        "session_state": session.state.name,
        "results": results,
        "trace": session.get_replay_data(),
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

    session = _session_manager.get_session(session_id)
    if session is None:
        return TraceResponse(
            session_id=session_id,
            trace={"error": "Session not found", "session_id": session_id},
        )

    return TraceResponse(
        session_id=session_id,
        trace=session.get_replay_data(),
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
    node_failed, node_skipped, and execution_complete events as they
    happen during execution.

    Client commands (JSON over WebSocket):
        {"command": "execute-node", "node": {...}, "target_dbs": [...]}
            Execute a single node — events stream back in real time.

        {"command": "execute-all", "graph_model": {...}, "target_dbs": [...], "breakpoints": [...]}
            Execute all nodes sequentially — each node's events stream back
            as they happen.  The session state machine is used throughout.

        {"command": "ping"}
            Responds with {"type": "pong"}.

        {"command": "close"}
            Close the connection.
    """
    # --- Auth check ---
    if _WS_TOKEN is not None:
        token = websocket.query_params.get("token", "")
        if token != _WS_TOKEN:
            await websocket.close(
                code=4001, reason="Unauthorized: invalid or missing token"
            )
            return

    await websocket.accept()

    # Get or create the session
    session = _session_manager.get_or_create(session_id)
    _session_manager.bind_websocket(session_id, websocket)

    # Wire WebSocket forwarder to the session's event bus
    import asyncio as _asyncio

    _loop = _asyncio.get_running_loop()

    def ws_forward(event_type: str, node_id: str, data: dict | None = None) -> None:
        """Forward execution events to the WebSocket client as JSON."""
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
        _loop.call_soon_threadsafe(
            lambda m=message: _asyncio.ensure_future(websocket.send_json(m))
        )

    unsub_ws = session.event_bus.subscribe(ws_forward)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            cmd = msg.get("command", "")

            if cmd == "execute-node":
                await websocket.send_json({
                    "type": "error",
                    "message": "Single-node execution deprecated. Use execute-all.",
                })

            elif cmd == "execute-all":
                if not rate_limit_ws(websocket, max_requests=30, window_seconds=60):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Rate limit exceeded. Slow down.",
                    })
                    continue

                await _ws_execute_all(session, msg, websocket)

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
        _session_manager.unbind_websocket(session_id)
        # Don't remove the session — trace data is still needed for replay


# ---------------------------------------------------------------------------
# WebSocket: execute-all helper
# ---------------------------------------------------------------------------


async def _ws_execute_all(
    session: Any,
    msg: dict,
    websocket: WebSocket,
) -> None:
    """Execute stored procedure via WebSocket with streaming events.

    Compiles the T-SQL to each target dialect, creates the procedure on
    each DB, executes it, and streams results back via WebSocket.
    """
    from app.core.sp_compiler.execution.engine import ExecutionEngine

    graph_model = msg.get("graph_model", {})
    target_dbs = msg.get("target_dbs", ["mssql", "kingbasees", "dm8"])

    nodes = graph_model.get("nodes", [])
    node_ids = [n.get("id", "") for n in nodes]
    original_tsql = graph_model.get("original_tsql", "")
    proc_name = graph_model.get("procedure_name", "migrated_sp")

    # Reset session for a fresh run
    session.node_states.clear()
    session.node_order.clear()
    session.current_step = 0
    session.graph_model = graph_model
    session.tracer.reset()
    session.init_node_states(node_ids)

    engine = ExecutionEngine.for_session(session, target_dbs=target_dbs)

    try:
        session.start()

        if not original_tsql:
            raise ValueError("No original_tsql found in graph model")

        # Execute the whole procedure across all target DBs
        node_results = engine.execute_procedure(
            original_tsql=original_tsql,
            proc_name=proc_name,
            node_ids=node_ids,
        )

        proc_result = node_results[0] if node_results else None

        # Map results back to CFG nodes
        for nid in node_ids:
            session.start_node(nid)
            if proc_result:
                if proc_result.status == "success":
                    session.finish_node(nid, data=_result_to_dict(proc_result))
                else:
                    session.fail_node(nid, error=_extract_error(proc_result))
                session.advance_step()

        session.complete()

        await websocket.send_json({
            "type": "execution_complete",
            "node_id": "",
            "timestamp": time.time(),
            "data": {
                "session_state": session.state.name,
                "nodes_executed": len(session.node_order),
            },
        })

    except Exception as exc:
        session.fail(error=str(exc))
        await websocket.send_json({
            "type": "execution_complete",
            "node_id": "",
            "timestamp": time.time(),
            "data": {
                "session_state": "FAILED",
                "error": str(exc),
            },
        })


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


def _result_to_dict(result: Any) -> dict:
    """Convert a NodeExecutionResult to a JSON-serializable dict."""
    return {
        "node_id": result.node_id,
        "status": result.status,
        "execution_time_ms": result.execution_time_ms,
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
    }


def _extract_error(result: Any) -> str | None:
    """Extract the first error message from a failed result."""
    for r in result.results.values():
        if r.error:
            return r.error
    return None
