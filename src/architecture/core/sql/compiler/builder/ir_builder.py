"""
IR Builder — assembles and validates a complete IRProcedure from extracted IR nodes.

This is the validation gate before code generation. It ensures:
    1. Variable names are unique across parameters and locals
    2. No dangling references (future: variable use-before-declare detection)

The builder separates "gathering" (collecting IR nodes from the extractor)
from "assembling" (validating and constructing the final IRProcedure).

Usage:
    from architecture.core.sql.compiler.builder import build_procedure

    ir = build_procedure(
        name="get_product_count",
        parameters=[IRVariable(name="pid", data_type="INT", scope=VariableScope.PARAMETER)],
        body=ir_nodes,
        original_source=tsql_text,
    )
"""

from __future__ import annotations

from ..ir import (
    IRAssign,
    IRBlock,
    IRExec,
    IRIf,
    IRNode,
    IRProcedure,
    IRReturn,
    IRSQL,
    IRTransaction,
    IRVariable,
    IRWhile,
    VariableScope,
)


# ---------------------------------------------------------------------------
# Builder error
# ---------------------------------------------------------------------------


class IRBuildError(ValueError):
    """Raised when IR assembly validation fails."""
    pass


# ---------------------------------------------------------------------------
# Main builder function
# ---------------------------------------------------------------------------


def build_procedure(
    name: str,
    parameters: list[IRVariable],
    body: list[IRNode],
    original_source: str = "",
) -> IRProcedure:
    """Assemble and validate a complete IRProcedure.

    This is the final step before code generation. All IR nodes from the
    extractor are assembled into a validated, immutable IRProcedure.

    Validation rules:
        1. Parameter names must be unique (case-insensitive, normalized)
        2. All parameters must have scope=PARAMETER
        3. Procedure name must be non-empty

    Args:
        name: Procedure name (without schema prefix).
        parameters: List of IRVariable nodes for input/output parameters.
        body: List of IRNode nodes representing the procedure body.
        original_source: Original T-SQL source text (for diagnostics).

    Returns:
        Validated IRProcedure.

    Raises:
        IRBuildError: If validation fails.
    """
    # Validate name
    if not name or not name.strip():
        raise IRBuildError("Procedure name cannot be empty")

    name = name.strip()

    # Normalize parameter scopes
    normalized_params: list[IRVariable] = []
    for p in parameters:
        if p.scope != VariableScope.PARAMETER:
            # Force parameter scope on passed parameters
            normalized_params.append(IRVariable(
                name=p.name,
                data_type=p.data_type,
                default_value=p.default_value,
                is_output=p.is_output,
                scope=VariableScope.PARAMETER,
                source_line=p.source_line,
            ))
        else:
            normalized_params.append(p)

    # Validate unique parameter names
    seen: set[str] = set()
    for param in normalized_params:
        key = param.name.lower()
        if key in seen:
            raise IRBuildError(
                f"Duplicate parameter name: @{param.name}"
            )
        seen.add(key)

    # Collect local variables from body for duplicate check
    local_vars = _collect_local_variables(body)
    for lv in local_vars:
        key = lv.name.lower()
        if key in seen:
            raise IRBuildError(
                f"Local variable '@{lv.name}' conflicts with parameter"
            )
        seen.add(key)

    return IRProcedure(
        name=name,
        parameters=tuple(normalized_params),
        variables=tuple(local_vars),
        body=tuple(body),
        original_source=original_source,
    )


# ---------------------------------------------------------------------------
# Local variable collector
# ---------------------------------------------------------------------------


def _collect_local_variables(nodes: list[IRNode]) -> list[IRVariable]:
    """Walk the IR tree and collect all locally-declared variables.

    Recursively descends into nested blocks (IRIf, IRWhile, IRBlock).
    Variables declared inside nested scopes are collected flat (PL/pgSQL
    and DM both have flat DECLARE sections at the function/procedure level).

    Args:
        nodes: List of IRNode nodes from the body.

    Returns:
        List of IRVariable nodes with scope=LOCAL.
    """
    variables: list[IRVariable] = []

    for node in nodes:
        if isinstance(node, IRVariable):
            if node.scope == VariableScope.LOCAL:
                variables.append(node)
        elif isinstance(node, IRIf):
            variables.extend(_collect_local_variables(list(node.then_body)))
            variables.extend(_collect_local_variables(list(node.else_body)))
        elif isinstance(node, IRWhile):
            variables.extend(_collect_local_variables(list(node.body)))
        elif isinstance(node, IRBlock):
            variables.extend(_collect_local_variables(list(node.body)))

    return variables


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def build_simple_procedure(
    name: str,
    *body_nodes: IRNode,
    original_source: str = "",
) -> IRProcedure:
    """Build a simple IRProcedure with no parameters.

    Convenience for testing and programmatic IR construction.

    Args:
        name: Procedure name.
        *body_nodes: IR nodes forming the procedure body.
        original_source: Original T-SQL source text.

    Returns:
        IRProcedure.
    """
    return build_procedure(
        name=name,
        parameters=[],
        body=list(body_nodes),
        original_source=original_source,
    )
