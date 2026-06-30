"""
CFG Optimizer — IR-level and CFG-level optimizations.

Optimizations:
    1. Dead Code Elimination — remove unreachable basic blocks
    2. Constant Folding — evaluate constant expressions at compile time
    3. Branch Simplification — remove branches with constant conditions
    4. SQL Block Merge — merge consecutive SQL statements when safe
    5. Loop Invariant Code Motion — hoist constant SQL out of loops

These operate at two levels:
    - IR-level: transform IRNode trees (constant folding, branch simplification)
    - CFG-level: transform the CFG (dead code elimination)

Usage:
    from app.core.sp_compiler.cfg import CFGBuilder, CFGOptimizer

    cfg = CFGBuilder.build(ir)
    optimized_cfg = CFGOptimizer.dead_code_elimination(cfg)
    optimized_ir = CFGOptimizer.constant_folding(ir)
"""

from __future__ import annotations

from ..ir import (
    IRAssign,
    IRBlock,
    IRIf,
    IRNode,
    IRProcedure,
    IRWhile,
)
from .builder import CFG, BasicBlock


class CFGOptimizer:
    """Collection of CFG and IR optimization passes.

    Each optimization is a pure function: input → output, no side effects.
    """

    # ------------------------------------------------------------------
    # Dead Code Elimination (CFG-level)
    # ------------------------------------------------------------------

    @staticmethod
    def dead_code_elimination(cfg: CFG) -> CFG:
        """Remove basic blocks that are not reachable from the entry.

        Uses a simple graph traversal: starting from the entry block,
        mark all reachable blocks via successor edges. Unreachable blocks
        are removed.

        Args:
            cfg: The input CFG.

        Returns:
            New CFG with unreachable blocks removed.
        """
        # Graph traversal from entry
        reachable: set[int] = set()
        stack = [cfg.entry_block_id]

        block_map = {b.id: b for b in cfg.blocks}

        while stack:
            bid = stack.pop()
            if bid in reachable:
                continue
            reachable.add(bid)

            block = block_map.get(bid)
            if block:
                for succ in block.successors:
                    if succ not in reachable:
                        stack.append(succ)

        # Filter reachable blocks
        live_blocks = tuple(
            b for b in cfg.blocks if b.id in reachable
        )

        # Filter edges to only those connecting live blocks
        live_edges = tuple(
            e for e in cfg.edges
            if e.from_block in reachable and e.to_block in reachable
        )

        return CFG(
            blocks=live_blocks,
            edges=live_edges,
            entry_block_id=cfg.entry_block_id,
            exit_block_ids=tuple(
                eid for eid in cfg.exit_block_ids if eid in reachable
            ),
            name=cfg.name,
        )

    # ------------------------------------------------------------------
    # Constant Folding (IR-level)
    # ------------------------------------------------------------------

    @staticmethod
    def constant_folding(ir: IRProcedure) -> IRProcedure:
        """Fold constant expressions in the IR.

        Evaluates simple arithmetic at compile time:
            SET @x = 1 + 2  →  SET @x = 3
            SET @x = 2 * 3  →  SET @x = 6

        Only folds when both operands are numeric literals and the
        operator is safe (+, -, *, /).

        Args:
            ir: The input IRProcedure.

        Returns:
            New IRProcedure with constant-folded expressions.
        """
        def _fold_node(node: IRNode) -> IRNode:
            if isinstance(node, IRAssign):
                folded_expr = _fold_expression(node.expression)
                if folded_expr != node.expression:
                    return IRAssign(
                        target=node.target,
                        expression=folded_expr,
                        is_scalar_query=node.is_scalar_query,
                        source_line=node.source_line,
                    )

            elif isinstance(node, IRIf):
                folded_cond = _fold_expression(node.condition)
                then_body = tuple(_fold_node(n) for n in node.then_body)
                else_body = tuple(_fold_node(n) for n in node.else_body)
                if (folded_cond != node.condition or
                    then_body != node.then_body or
                    else_body != node.else_body):
                    return IRIf(
                        condition=folded_cond,
                        then_body=then_body,
                        else_body=else_body,
                        source_line=node.source_line,
                    )

            elif isinstance(node, IRWhile):
                folded_cond = _fold_expression(node.condition)
                body = tuple(_fold_node(n) for n in node.body)
                if folded_cond != node.condition or body != node.body:
                    return IRWhile(
                        condition=folded_cond,
                        body=body,
                        source_line=node.source_line,
                    )

            return node

        new_body = tuple(_fold_node(n) for n in ir.body)
        return IRProcedure(
            name=ir.name,
            parameters=ir.parameters,
            variables=ir.variables,
            body=new_body,
            original_source=ir.original_source,
        )

    # ------------------------------------------------------------------
    # Branch Simplification (IR-level)
    # ------------------------------------------------------------------

    @staticmethod
    def branch_simplification(ir: IRProcedure) -> IRProcedure:
        """Simplify branches with constant conditions.

        If the condition is a known constant:
            IF 1=1 THEN ... ELSE ...  →  ... (remove ELSE)
            IF 0=1 THEN ... ELSE ...  →  ... (remove THEN)

        Args:
            ir: The input IRProcedure.

        Returns:
            New IRProcedure with simplified branches.
        """
        def _simplify_node(node: IRNode) -> IRNode | None:
            if isinstance(node, IRIf):
                # Check for constant true/false conditions
                cond = node.condition.strip()

                if _is_always_true(cond):
                    # Keep only THEN body
                    return IRBlock(
                        body=tuple(
                            n for n in
                            (_simplify_node(n) for n in node.then_body)
                            if n is not None
                        ),
                        source_line=node.source_line,
                    )

                if _is_always_false(cond):
                    # Keep only ELSE body (or nothing)
                    if node.else_body:
                        return IRBlock(
                            body=tuple(
                                n for n in
                                (_simplify_node(n) for n in node.else_body)
                                if n is not None
                            ),
                            source_line=node.source_line,
                        )
                    return None  # Remove entirely

                # Recursively simplify nested
                then_body = tuple(
                    n for n in
                    (_simplify_node(n) for n in node.then_body)
                    if n is not None
                )
                else_body = tuple(
                    n for n in
                    (_simplify_node(n) for n in node.else_body)
                    if n is not None
                )
                return IRIf(
                    condition=cond,
                    then_body=then_body,
                    else_body=else_body,
                    source_line=node.source_line,
                )

            elif isinstance(node, IRWhile):
                cond = node.condition.strip()
                if _is_always_false(cond):
                    return None  # Loop never executes

                body = tuple(
                    n for n in
                    (_simplify_node(n) for n in node.body)
                    if n is not None
                )
                return IRWhile(
                    condition=cond,
                    body=body,
                    source_line=node.source_line,
                )

            return node

        new_body = tuple(
            n for n in
            (_simplify_node(n) for n in ir.body)
            if n is not None
        )

        return IRProcedure(
            name=ir.name,
            parameters=ir.parameters,
            variables=ir.variables,
            body=new_body,
            original_source=ir.original_source,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fold_expression(expr: str) -> str:
    """Attempt to evaluate a constant arithmetic expression.

    Supports: +, -, *, / with integer operands.

    Returns the folded value as a string, or the original expression
    if folding is not possible.
    """
    import re

    expr = expr.strip()

    # Match simple binary arithmetic: number operator number
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)$", expr)
    if not match:
        return expr

    try:
        left = float(match.group(1))
        op = match.group(2)
        right = float(match.group(3))

        if op == "+":
            result = left + right
        elif op == "-":
            result = left - right
        elif op == "*":
            result = left * right
        elif op == "/":
            if right == 0:
                return expr  # Division by zero — don't fold
            result = left / right
        else:
            return expr

        # Preserve integer formatting
        if result == int(result):
            return str(int(result))
        return str(result)

    except (ValueError, ZeroDivisionError):
        return expr


def _is_always_true(condition: str) -> bool:
    """Check if a condition is trivially always true.

    E.g., "1=1", "1 = 1", "true"
    """
    cond = condition.strip().upper()
    always_true_patterns = [
        "1=1", "1 = 1",
        "0=0", "0 = 0",
        "TRUE",
        "1 <> 0", "1 != 0",
    ]
    return cond in always_true_patterns


def _is_always_false(condition: str) -> bool:
    """Check if a condition is trivially always false.

    E.g., "1=0", "0=1", "false"
    """
    cond = condition.strip().upper()
    always_false_patterns = [
        "1=0", "1 = 0",
        "0=1", "0 = 1",
        "FALSE",
        "0=2", "0 = 2",
    ]
    return cond in always_false_patterns
