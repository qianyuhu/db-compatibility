"""
Control Flow Graph Builder — converts IRProcedure into a CFG.

Transforms the tree-structured IR into a graph of basic blocks with explicit
control flow edges. This enables:
    - Dead code detection
    - Loop analysis
    - Branch optimization
    - Execution path analysis
    - Visual graph rendering (via CFG → UI model serialization)

Basic Block definition:
    A sequence of IR nodes with a single entry point and a single exit point.
    Control flow can only enter at the first instruction and leave at the last.

Usage:
    from architecture.core.sql.compiler.cfg import CFGBuilder

    cfg = CFGBuilder.build(ir_procedure)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ir import (
    IRBlock,
    IRIf,
    IRNode,
    IRProcedure,
    IRReturn,
    IRWhile,
)


# ---------------------------------------------------------------------------
# CFG data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BasicBlock:
    """A basic block: straight-line sequence of IR nodes.

    Attributes:
        id: Unique block identifier (sequential integer).
        nodes: Tuple of IRNode nodes in execution order.
        successors: Block IDs that can follow this block.
        predecessors: Block IDs that can lead to this block.
        is_entry: True if this block is the CFG entry.
        is_exit: True if this block is a CFG exit point.
    """
    id: int
    nodes: tuple[IRNode, ...] = field(default_factory=tuple)
    successors: tuple[int, ...] = field(default_factory=tuple)
    predecessors: tuple[int, ...] = field(default_factory=tuple)
    is_entry: bool = False
    is_exit: bool = False


@dataclass(frozen=True)
class CFGEdge:
    """A control flow edge connecting two basic blocks.

    Attributes:
        from_block: Source block ID.
        to_block: Target block ID.
        edge_type: Type of control flow edge.
            "sequential"   — straight-line fallthrough
            "true_branch"  — taken when IF/WHILE condition is true
            "false_branch" — taken when IF/WHILE condition is false
            "loop_back"    — back edge from loop body end to loop header
        condition: The condition expression for branch edges (None for sequential).
        label: Human-readable edge label ("true", "false", "loop", or "").
    """
    from_block: int
    to_block: int
    edge_type: str
    condition: str | None = None
    label: str = ""


@dataclass(frozen=True)
class CFG:
    """Control Flow Graph with basic blocks and explicit edges.

    The CFG is the executable representation of a stored procedure.
    It can be analyzed, optimized, and used to generate code with
    explicit control flow paths.

    Attributes:
        blocks: All basic blocks, indexed by their id field.
        edges: All control flow edges between blocks.
        entry_block_id: ID of the CFG entry block.
        exit_block_ids: IDs of CFG exit blocks.
        name: Procedure name.
    """
    blocks: tuple[BasicBlock, ...] = field(default_factory=tuple)
    edges: tuple[CFGEdge, ...] = field(default_factory=tuple)
    entry_block_id: int = 0
    exit_block_ids: tuple[int, ...] = field(default_factory=tuple)
    name: str = ""


# ---------------------------------------------------------------------------
# CFG Builder
# ---------------------------------------------------------------------------


class CFGBuilder:
    """Build a CFG from an IRProcedure.

    The algorithm:
        1. Flatten the IR body into a linear sequence with branch markers
        2. Partition the linear sequence into basic blocks at branch boundaries
        3. Compute predecessor/successor edges using branch marker information:
           - IF:  condition block → true_branch → THEN body
                  condition block → false_branch → ELSE body (or join point)
           - WHILE: header → true_branch → body
                    body end → loop_back → header
                    header → false_branch → exit
           - RETURN: no successors (exit block)
        4. Add sequential edges for blocks not covered by branch edges
    """

    @staticmethod
    def build(ir: IRProcedure) -> CFG:
        """Build a CFG from an IRProcedure.

        Args:
            ir: The IRProcedure to convert.

        Returns:
            A CFG with basic blocks and control flow edges.
        """
        # Stage 1: Flatten IR body, tracking branch/loop structures
        flat_nodes, branch_info = CFGBuilder._flatten_with_info(ir.body)

        # Stage 2: Partition into basic blocks
        blocks, boundaries = CFGBuilder._partition_into_blocks(
            flat_nodes, branch_info
        )

        # Build flat index → block ID mapping for edge creation
        block_of: dict[int, int] = {}
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(flat_nodes)
            for j in range(start, max(end, start + 1)):
                block_of[j] = i

        # Stage 3: Build control flow edges using branch markers
        blocks, edges = CFGBuilder._build_edges(
            blocks, block_of, branch_info
        )

        # Stage 4: Find entry and exit blocks
        exit_ids = tuple(
            b.id for b in blocks
            if any(isinstance(n, IRReturn) for n in b.nodes)
        )
        if not exit_ids and blocks:
            # Last block is implicit exit
            exit_ids = (blocks[-1].id,)

        return CFG(
            blocks=tuple(blocks),
            edges=tuple(edges),
            entry_block_id=blocks[0].id if blocks else 0,
            exit_block_ids=exit_ids,
            name=ir.name,
        )

    # ------------------------------------------------------------------
    # Stage 1: Flatten with branch info
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_with_info(
        nodes: tuple[IRNode, ...],
    ) -> tuple[list[IRNode], list[dict]]:
        """Flatten IR nodes into a linear list while tracking branch points.

        IRIf and IRWhile are structural nodes — they do NOT appear in the
        flat list themselves. Instead, their branch points are recorded as
        markers at the flat indices where their bodies begin/end.

        Returns:
            Tuple of (flat_nodes, branch_info).
            branch_info entries:
                {"index": int, "type": "if", "condition": str, "has_else": bool}
                {"index": int, "type": "else_join"}
                {"index": int, "type": "if_end"}
                {"index": int, "type": "while_header", "condition": str}
                {"index": int, "type": "while_end"}
                {"index": int, "type": "return"}
        """
        flat: list[IRNode] = []
        branches: list[dict] = []

        def _walk(node_list: tuple[IRNode, ...]) -> None:
            for node in node_list:
                if isinstance(node, IRIf):
                    branches.append({
                        "index": len(flat),
                        "type": "if",
                        "condition": node.condition,
                        "has_else": bool(node.else_body),
                    })
                    _walk(node.then_body)
                    if node.else_body:
                        branches.append({
                            "index": len(flat),
                            "type": "else_join",
                        })
                        _walk(node.else_body)
                    branches.append({
                        "index": len(flat),
                        "type": "if_end",
                    })

                elif isinstance(node, IRWhile):
                    branches.append({
                        "index": len(flat),
                        "type": "while_header",
                        "condition": node.condition,
                    })
                    _walk(node.body)
                    branches.append({
                        "index": len(flat),
                        "type": "while_end",
                    })

                elif isinstance(node, IRBlock):
                    _walk(node.body)

                elif isinstance(node, IRReturn):
                    flat.append(node)
                    branches.append({
                        "index": len(flat) - 1,
                        "type": "return",
                    })

                else:
                    # Linear node: assign, sql, exec, transaction, variable
                    flat.append(node)

        _walk(nodes)
        return flat, branches

    # ------------------------------------------------------------------
    # Stage 2: Partition into basic blocks
    # ------------------------------------------------------------------

    @staticmethod
    def _partition_into_blocks(
        nodes: list[IRNode],
        branches: list[dict],
    ) -> tuple[list[BasicBlock], list[int]]:
        """Partition flat nodes into basic blocks at branch/join boundaries.

        Block boundaries occur at:
            - The start (index 0)
            - Every branch marker position (if, else_join, if_end, while_header, while_end)
            - The position after an `if` or `while_header` marker (to isolate the
              condition block from the body)

        Returns:
            Tuple of (blocks, boundaries) where boundaries[i] is the flat
            index where block i starts.
        """
        if not nodes:
            return [], [0]

        boundary_indices: set[int] = {0}

        for b in branches:
            boundary_indices.add(b["index"])
            # Split after "if" and "while_header" markers to separate the
            # condition-introducing block from the body block
            if b["type"] in ("if", "while_header"):
                if b["index"] < len(nodes):
                    boundary_indices.add(b["index"] + 1)

        boundaries = sorted(boundary_indices)
        blocks: list[BasicBlock] = []

        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(nodes)
            if start < end:
                block_nodes = tuple(nodes[start:end])
            else:
                # Empty boundary block (e.g., empty join/merge point)
                block_nodes = ()
            blocks.append(BasicBlock(
                id=len(blocks),
                nodes=block_nodes,
            ))

        return blocks, boundaries

    # ------------------------------------------------------------------
    # Stage 3: Build edges
    # ------------------------------------------------------------------

    @staticmethod
    def _build_edges(
        blocks: list[BasicBlock],
        block_of: dict[int, int],
        branches: list[dict],
    ) -> tuple[list[BasicBlock], list[CFGEdge]]:
        """Compute successor/predecessor edges using branch marker information.

        Uses a stack-based approach to pair IF/ELSE/END-IF and WHILE/END-WHILE
        markers, creating the correct branch, loop-back, and sequential edges.

        Returns:
            Tuple of (blocks_with_edges, edges_list).
        """
        n = len(blocks)

        def _block_at(flat_idx: int) -> int | None:
            """Return the block ID containing the given flat index."""
            return block_of.get(flat_idx)

        def _block_before(flat_idx: int) -> int | None:
            """Return the block ID containing the node just before flat_idx."""
            if flat_idx <= 0:
                return 0
            # Walk backwards to find a mapped index
            for j in range(flat_idx - 1, -1, -1):
                bid = block_of.get(j)
                if bid is not None:
                    return bid
            return 0

        # Track which edges exist (for deduplication)
        added_edges: set[tuple[int, int, str]] = set()

        def _add_edge(from_b: int, to_b: int, etype: str, condition: str | None = None, label: str = "") -> None:
            """Add an edge if it doesn't already exist and isn't self-referential."""
            if from_b == to_b:
                return
            key = (from_b, to_b, etype)
            if key in added_edges:
                return
            added_edges.add(key)

        successor_map: dict[int, set[int]] = {i: set() for i in range(n)}
        predecessor_map: dict[int, set[int]] = {i: set() for i in range(n)}
        edges: list[CFGEdge] = []

        def _commit_edge(from_b: int, to_b: int, etype: str, condition: str | None = None, label: str = "") -> None:
            if from_b == to_b:
                return
            key = (from_b, to_b, etype)
            if key in added_edges:
                return
            added_edges.add(key)
            successor_map[from_b].add(to_b)
            predecessor_map[to_b].add(from_b)
            edges.append(CFGEdge(
                from_block=from_b,
                to_block=to_b,
                edge_type=etype,
                condition=condition,
                label=label,
            ))

        # ------------------------------------------------------------------
        # Pass 1: Branch edges (IF/ELSE and WHILE)
        # ------------------------------------------------------------------
        if_stack: list[dict] = []   # push on "if", pop on "if_end"
        while_stack: list[dict] = []  # push on "while_header", pop on "while_end"

        for b in branches:
            btype = b["type"]
            bidx = b["index"]

            # --- IF handling ---
            if btype == "if":
                # Store for matching with else_join / if_end
                if_info = dict(b)
                # The block containing the node right before the IF marker
                # is the "condition block" (implicitly contains the IF decision)
                if_info["_cond_block"] = _block_before(bidx)
                if_stack.append(if_info)

            elif btype == "else_join":
                if if_stack:
                    if_stack[-1]["_else_start"] = bidx

            elif btype == "if_end":
                if not if_stack:
                    continue
                if_info = if_stack.pop()

                cond_block = if_info["_cond_block"]
                then_first = _block_at(if_info["index"])
                else_start = if_info.get("_else_start")
                has_else = if_info.get("has_else", False)
                join_block = _block_at(bidx)
                condition = if_info.get("condition", "")

                # True branch: condition block → first THEN block
                if then_first is not None and cond_block is not None:
                    _commit_edge(cond_block, then_first, "true_branch", condition, "true")

                if has_else and else_start is not None:
                    # False branch: condition block → first ELSE block
                    else_first = _block_at(else_start)
                    if else_first is not None and cond_block is not None:
                        _commit_edge(cond_block, else_first, "false_branch", condition, "false")

                    # ELSE end → join point
                    else_end = _block_before(bidx)
                    if else_end is not None and join_block is not None:
                        _commit_edge(else_end, join_block, "sequential")

                    # THEN end → join point
                    then_end = _block_before(else_start)
                    if then_end is not None and join_block is not None:
                        _commit_edge(then_end, join_block, "sequential")

                else:
                    # No ELSE: false branch goes to join, THEN end → join
                    if join_block is not None and cond_block is not None:
                        _commit_edge(cond_block, join_block, "false_branch", condition, "false")

                    then_end = _block_before(bidx)
                    if then_end is not None and join_block is not None:
                        _commit_edge(then_end, join_block, "sequential")

            # --- WHILE handling ---
            elif btype == "while_header":
                wh_info = dict(b)
                wh_info["_header_block"] = _block_before(bidx)
                wh_info["_body_first"] = _block_at(bidx)
                while_stack.append(wh_info)

            elif btype == "while_end":
                if not while_stack:
                    continue
                wh_info = while_stack.pop()

                header_block = wh_info["_header_block"]
                body_first = wh_info["_body_first"]
                exit_block = _block_at(bidx)
                condition = wh_info.get("condition", "")

                # True branch: header → first body block
                if body_first is not None and header_block is not None:
                    _commit_edge(header_block, body_first, "true_branch", condition, "true")

                # Loop back: last body block → header
                last_body = _block_before(bidx)
                if last_body is not None and header_block is not None:
                    _commit_edge(last_body, header_block, "loop_back", condition, "loop")

                # False branch: header → exit (after loop)
                if exit_block is not None and header_block is not None:
                    _commit_edge(header_block, exit_block, "false_branch", condition, "false")

        # ------------------------------------------------------------------
        # Pass 2: Sequential edges for blocks not connected by branches
        # ------------------------------------------------------------------
        for i in range(n - 1):
            # Skip exit blocks (end with RETURN)
            last_node = blocks[i].nodes[-1] if blocks[i].nodes else None
            if isinstance(last_node, IRReturn):
                continue

            # Skip if already connected to i+1 via a branch edge
            if (i + 1) in successor_map[i]:
                continue

            # Skip if this block has a loop_back successor (loop body exits
            # only via the false_branch from the header, not sequentially)
            has_loop_back = any(
                e.edge_type == "loop_back" and e.from_block == i
                for e in edges
            )
            if has_loop_back:
                continue

            _commit_edge(i, i + 1, "sequential")

        # ------------------------------------------------------------------
        # Build result blocks with updated successor/predecessor info
        # ------------------------------------------------------------------
        result: list[BasicBlock] = []
        for i in range(n):
            result.append(BasicBlock(
                id=blocks[i].id,
                nodes=blocks[i].nodes,
                successors=tuple(sorted(successor_map.get(i, set()))),
                predecessors=tuple(sorted(predecessor_map.get(i, set()))),
                is_entry=(i == 0),
                is_exit=any(
                    isinstance(n, IRReturn) for n in blocks[i].nodes
                ),
            ))

        return result, edges

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def print_cfg(cfg: CFG) -> str:
        """Generate a human-readable CFG representation."""
        lines = [f"CFG for '{cfg.name}':"]
        lines.append(f"  Entry: B{cfg.entry_block_id}")
        lines.append(f"  Exits: {[f'B{i}' for i in cfg.exit_block_ids]}")
        lines.append(f"  Blocks: {len(cfg.blocks)}")
        lines.append(f"  Edges: {len(cfg.edges)}")
        for block in cfg.blocks:
            nodes_str = ", ".join(
                f"{type(n).__name__}" for n in block.nodes
            )
            succ_str = ", ".join(f"B{s}" for s in block.successors)
            pred_str = ", ".join(f"B{p}" for p in block.predecessors)
            lines.append(
                f"    B{block.id}: [{nodes_str}] "
                f"succs={{{succ_str}}} preds={{{pred_str}}}"
                f"{' [ENTRY]' if block.is_entry else ''}"
                f"{' [EXIT]' if block.is_exit else ''}"
            )
        for edge in cfg.edges:
            cond_str = f" ({edge.condition})" if edge.condition else ""
            lines.append(
                f"    B{edge.from_block} --[{edge.edge_type}{cond_str}]--> B{edge.to_block}"
            )
        return "\n".join(lines)
