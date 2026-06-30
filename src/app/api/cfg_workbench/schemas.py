"""
Pydantic schemas for CFG Workbench API requests and responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CompileRequest(BaseModel):
    """Request to compile a T-SQL stored procedure into a CFG graph model.

    Attributes:
        tsql: Complete T-SQL stored procedure source code.
        target_dbs: Database types to target for execution (default all three).
    """
    tsql: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Complete T-SQL stored procedure source code (max 50KB)",
        examples=["CREATE PROCEDURE check_stock @product_id INT AS BEGIN SELECT COUNT(*) FROM inventory WHERE product_id = @product_id END"],
    )
    target_dbs: list[str] = Field(
        default_factory=lambda: ["mssql", "kingbasees", "dm8"],
        description="Target databases for execution",
    )


class ExecuteNodeRequest(BaseModel):
    """Request to execute a single CFG node against all target databases.

    Attributes:
        node: The UINode dict to execute (from the graph model).
        target_dbs: Database types to execute against.
    """
    node: dict = Field(
        ...,
        description="UINode dict from the graph model",
    )
    target_dbs: list[str] = Field(
        default_factory=lambda: ["mssql", "kingbasees", "dm8"],
        description="Target databases for execution",
    )


class ExecuteAllRequest(BaseModel):
    """Request to execute all nodes in a graph model sequentially.

    Attributes:
        graph_model: The complete UIGraphModel dict.
        target_dbs: Database types to execute against.
        breakpoints: Set of node IDs where execution should pause.
    """
    graph_model: dict = Field(
        ...,
        description="Complete UIGraphModel dict",
    )
    target_dbs: list[str] = Field(
        default_factory=lambda: ["mssql", "kingbasees", "dm8"],
        description="Target databases for execution",
    )
    breakpoints: list[str] = Field(
        default_factory=list,
        description="Node IDs where execution should pause",
    )


class SetBreakpointRequest(BaseModel):
    """Request to set or clear a breakpoint on a node.

    Attributes:
        session_id: The execution session ID.
        node_id: The node ID to set/clear the breakpoint on.
        enabled: True to set, False to clear.
    """
    session_id: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    enabled: bool = True


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CompileResponse(BaseModel):
    """Response from the compile endpoint.

    Attributes:
        success: Whether compilation succeeded.
        graph_model: The UIGraphModel for the frontend (null if failed).
        errors: List of error messages (empty on success).
        procedure_name: Extracted procedure name.
        token_count: Number of tokens produced.
        block_count: Number of semantic blocks.
        ir_node_count: Number of IR nodes.
    """
    success: bool
    graph_model: dict | None = None
    errors: list[str] = Field(default_factory=list)
    procedure_name: str = ""
    token_count: int = 0
    block_count: int = 0
    ir_node_count: int = 0


class DBResultSchema(BaseModel):
    """Single-database execution result."""
    db_type: str
    success: bool
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None


class ExecutionDiffSchema(BaseModel):
    """Multi-DB execution diff."""
    row_diff: int = 0
    column_diff: list[str] = Field(default_factory=list)
    value_diffs: list[dict] = Field(default_factory=list)
    status: str = "MATCH"


class ExecuteNodeResponse(BaseModel):
    """Response from executing a single CFG node."""
    node_id: str
    status: str
    results: dict[str, DBResultSchema] = Field(default_factory=dict)
    diff: ExecutionDiffSchema | None = None
    execution_time_ms: float = 0.0


class TraceResponse(BaseModel):
    """Response containing execution trace data."""
    session_id: str
    trace: dict
