"""
CFG Workbench API — REST + WebSocket endpoints for the interactive CFG execution UI.

Endpoints:
    POST /api/cfg/compile        — Compile T-SQL → UIGraphModel
    POST /api/cfg/execute-node   — Execute a single CFG node
    POST /api/cfg/execute-all    — Execute all nodes in topological order
    POST /api/cfg/set-breakpoint — Set/reset a breakpoint on a node
    GET  /api/cfg/trace/{id}     — Get execution trace for replay
    WS   /api/cfg/ws/{id}        — Real-time execution event stream
"""
