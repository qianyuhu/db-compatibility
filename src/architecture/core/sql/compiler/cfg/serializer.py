"""
CFG → UI Graph Model Serializer.

Converts the internal CFG (with BasicBlocks and CFGEdges) into the JSON model
that the frontend React Flow canvas consumes. Each BasicBlock becomes one or
more UINodes; each CFGEdge becomes a UIEdge.

The serializer also embeds the original IR information (SQL text, conditions,
variable assignments) so the UI can display rich context for each node.

Usage:
    from architecture.core.sql.compiler.cfg.serializer import serialize_cfg

    ui_model = serialize_cfg(cfg, ir_procedure)
    # ui_model.to_dict() → JSON-ready dict for API response
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ir import (
    IRAssign,
    IRExec,
    IRIf,
    IRProcedure,
    IRReturn,
    IRSQL,
    IRTransaction,
    IRVariable,
    IRWhile,
    IRNodeType,
)
from .builder import CFG, BasicBlock, CFGEdge


# ---------------------------------------------------------------------------
# UI Model dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UINodeSource:
    """Reference back to the original IR node for rich display.

    Attributes:
        ir_node_type: The IRNodeType discriminant (e.g., "SQL", "IF").
        sql_text: The original SQL text (for SQL nodes).
        condition: The condition expression (for IF/WHILE nodes).
        target: The assignment target (for ASSIGN nodes).
        expression: The assignment expression (for ASSIGN nodes).
        procedure_name: The called procedure name (for EXEC nodes).
        variable_name: The variable name (for VARIABLE nodes).
    """
    ir_node_type: str = ""
    sql_text: str = ""
    condition: str = ""
    target: str = ""
    expression: str = ""
    procedure_name: str = ""
    variable_name: str = ""


@dataclass
class UINode:
    """A single node in the UI graph model.

    Corresponds to one IR node within a basic block. The frontend renders
    each UINode as a React Flow node with shape, label, and status.

    Attributes:
        id: Unique node identifier (e.g., "B0_N0", "B1_N0").
        block_id: The CFG basic block ID this node belongs to.
        type: Visual node type for rendering ("sql", "if", "while",
              "exec", "assign", "return", "transaction", "variable").
        label: Human-readable display label.
        source: Rich source info (IR reference, SQL text, etc.).
        status: Execution status ("pending" | "running" | "success" | "failed").
    """
    id: str
    block_id: int
    type: str
    label: str
    source: UINodeSource = field(default_factory=UINodeSource)
    status: str = "pending"


@dataclass
class UIEdge:
    """A single edge in the UI graph model.

    Attributes:
        id: Unique edge identifier.
        from_id: Source UINode ID.
        to_id: Target UINode ID.
        edge_type: "sequential" | "true_branch" | "false_branch" | "loop_back".
        condition: Condition expression for branch edges.
        label: Display label ("true", "false", "loop", or "").
    """
    id: str
    from_id: str
    to_id: str
    edge_type: str
    condition: str | None = None
    label: str = ""


@dataclass
class UIGraphModel:
    """Top-level UI graph model — the complete CFG visualization data.

    This is what the backend sends to the frontend as JSON.

    Attributes:
        procedure_name: The SP name.
        nodes: All UI nodes in the graph.
        edges: All UI edges in the graph.
        entry_node_id: The first node's ID (execution start).
        exit_node_ids: Exit node IDs (RETURN nodes).
        original_tsql: The original T-SQL source for reference.
    """
    procedure_name: str
    nodes: list[UINode] = field(default_factory=list)
    edges: list[UIEdge] = field(default_factory=list)
    entry_node_id: str = ""
    exit_node_ids: list[str] = field(default_factory=list)
    original_tsql: str = ""


# ---------------------------------------------------------------------------
# Node type mapping (IR → UI)
# ---------------------------------------------------------------------------

# Maps IRNodeType to frontend visual node type strings
_IR_TO_UI_TYPE: dict[str, str] = {
    "SQL": "sql",
    "IF": "if",
    "WHILE": "while",
    "EXEC": "exec",
    "ASSIGN": "assign",
    "RETURN": "return",
    "TRANSACTION": "transaction",
    "VARIABLE": "variable",
    "PROCEDURE": "procedure",
    "BLOCK": "block",
}


def _node_type_to_ui_type(ir_node_type: str) -> str:
    """Convert IRNodeType name to UI visual type."""
    return _IR_TO_UI_TYPE.get(ir_node_type, "sql")


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------


def _make_label(node: Any) -> str:
    """Generate a human-readable label for an IR node.

    The label is what appears inside the graph node. We keep it concise
    (≤60 chars) but descriptive enough to identify the node at a glance.
    """
    if isinstance(node, IRSQL):
        # Truncate long SQL for display
        sql = node.sql_text.strip()
        if len(sql) > 55:
            return sql[:52] + "..."
        return sql

    if isinstance(node, IRIf):
        cond = node.condition
        if len(cond) > 55:
            cond = cond[:52] + "..."
        return f"IF {cond}"

    if isinstance(node, IRWhile):
        cond = node.condition
        if len(cond) > 55:
            cond = cond[:52] + "..."
        return f"WHILE {cond}"

    if isinstance(node, IRAssign):
        return f"SET {node.target} = {node.expression}"

    if isinstance(node, IRExec):
        return f"EXEC {node.procedure_name}"

    if isinstance(node, IRTransaction):
        return f"{node.action} TRANSACTION"

    if isinstance(node, IRReturn):
        if node.value:
            return f"RETURN {node.value}"
        return "RETURN"

    if isinstance(node, IRVariable):
        default = f" = {node.default_value}" if node.default_value else ""
        scope = "PARAM" if hasattr(node, 'scope') and node.scope.name == "PARAMETER" else "LOCAL"
        return f"{scope}: {node.name} {node.data_type}{default}"

    return type(node).__name__


def _make_source(node: Any) -> UINodeSource:
    """Extract rich source information from an IR node."""
    ir_node_type = node.node_type.name if hasattr(node, 'node_type') else type(node).__name__

    source = UINodeSource(ir_node_type=ir_node_type)

    if isinstance(node, IRSQL):
        source.sql_text = node.sql_text

    elif isinstance(node, IRIf):
        source.condition = node.condition

    elif isinstance(node, IRWhile):
        source.condition = node.condition

    elif isinstance(node, IRAssign):
        source.target = node.target
        source.expression = node.expression

    elif isinstance(node, IRExec):
        source.procedure_name = node.procedure_name

    elif isinstance(node, IRVariable):
        source.variable_name = node.name

    return source


# ---------------------------------------------------------------------------
# Main serializer
# ---------------------------------------------------------------------------


def serialize_cfg(cfg: CFG, ir: IRProcedure) -> UIGraphModel:
    """Convert a CFG + IRProcedure into the frontend UIGraphModel.

    Each BasicBlock becomes one or more UINodes. The first node in each block
    acts as the "block header" that CFG edges connect to; subsequent nodes in
    the same block are connected by implicit sequential edges within the block.

    CFGEdges connect the last node of the source block to the first node of
    the target block.

    Args:
        cfg: The CFG with basic blocks and edges.
        ir: The original IRProcedure (for source text and metadata).

    Returns:
        A UIGraphModel ready for JSON serialization.
    """
    # Map block_id → list of UINode IDs in that block (in order)
    block_node_ids: dict[int, list[str]] = {}
    all_nodes: list[UINode] = []
    all_edges: list[UIEdge] = []

    # --- Convert blocks to UI nodes ---
    for block in cfg.blocks:
        node_ids: list[str] = []

        for i, ir_node in enumerate(block.nodes):
            node_id = f"B{block.id}_N{i}"
            ui_type = _node_type_to_ui_type(ir_node.node_type.name)

            ui_node = UINode(
                id=node_id,
                block_id=block.id,
                type=ui_type,
                label=_make_label(ir_node),
                source=_make_source(ir_node),
                status="pending",
            )
            all_nodes.append(ui_node)
            node_ids.append(node_id)

            # Sequential edge within the block (from previous node to this one)
            if i > 0:
                prev_id = f"B{block.id}_N{i - 1}"
                all_edges.append(UIEdge(
                    id=f"e_{prev_id}_{node_id}",
                    from_id=prev_id,
                    to_id=node_id,
                    edge_type="sequential",
                    label="",
                ))

        block_node_ids[block.id] = node_ids

    # --- Convert CFG edges to UI edges ---
    for edge in cfg.edges:
        from_nodes = block_node_ids.get(edge.from_block, [])
        to_nodes = block_node_ids.get(edge.to_block, [])

        if not from_nodes or not to_nodes:
            # One or both blocks are empty (e.g., empty join block)
            # Create a synthetic edge between the blocks' conceptual nodes
            from_id = f"B{edge.from_block}_ENTRY" if not from_nodes else from_nodes[-1]
            to_id = f"B{edge.to_block}_ENTRY" if not to_nodes else to_nodes[0]

            # Only add if we have actual nodes at the endpoints
            if not from_nodes and not to_nodes:
                continue
        else:
            # Connect last node of source block → first node of target block
            from_id = from_nodes[-1]
            to_id = to_nodes[0]

        all_edges.append(UIEdge(
            id=f"e_cfg_{edge.from_block}_{edge.to_block}_{edge.edge_type}",
            from_id=from_id,
            to_id=to_id,
            edge_type=edge.edge_type,
            condition=edge.condition,
            label=edge.label,
        ))

    # --- Determine entry/exit nodes ---
    entry_nodes = block_node_ids.get(cfg.entry_block_id, [])
    entry_node_id = entry_nodes[0] if entry_nodes else ""

    exit_node_ids: list[str] = []
    for exit_bid in cfg.exit_block_ids:
        exit_nodes = block_node_ids.get(exit_bid, [])
        if exit_nodes:
            exit_node_ids.append(exit_nodes[-1])

    return UIGraphModel(
        procedure_name=ir.name,
        nodes=all_nodes,
        edges=all_edges,
        entry_node_id=entry_node_id,
        exit_node_ids=exit_node_ids,
        original_tsql=ir.original_source,
    )
