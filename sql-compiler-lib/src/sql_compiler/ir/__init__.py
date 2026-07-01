"""
Control Flow IR Node Definitions — the single source of truth for SP representation.

All nodes are frozen dataclasses for immutability, following project convention.
The Union type IRNode enables type narrowing in generators and optimizers.

Node types:
    IRProcedure   — top-level container for the entire SP
    IRVariable    — declared variable or parameter
    IRAssign      — variable assignment (SET @var = expr)
    IRSQL         — SQL statement (SELECT/INSERT/UPDATE/DELETE) with optional sqlglot AST
    IRIf          — IF / THEN / ELSE
    IRWhile       — WHILE loop
    IRTransaction — BEGIN TRANSACTION / COMMIT / ROLLBACK
    IRExec        — EXEC procedure_name
    IRBlock       — Anonymous BEGIN...END block
    IRReturn      — RETURN [value]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Union


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IRNodeType(Enum):
    """Discriminant for IR node types — used for pattern matching."""
    PROCEDURE = auto()
    VARIABLE = auto()
    ASSIGN = auto()
    SQL = auto()
    IF = auto()
    WHILE = auto()
    TRANSACTION = auto()
    EXEC = auto()
    BLOCK = auto()
    RETURN = auto()


class VariableScope(Enum):
    """Distinguishes parameters from local variables — important for codegen."""
    LOCAL = auto()
    PARAMETER = auto()
    CURSOR = auto()


# ---------------------------------------------------------------------------
# IR Node dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IRProcedure:
    """Top-level procedure container — single source of truth for the whole SP.

    Attributes:
        name: Procedure name (without schema prefix).
        parameters: Tuple of IRVariable nodes representing input/output params.
        variables: Tuple of IRVariable nodes for locally-declared variables.
        body: Tuple of IRNode nodes representing the procedure body.
        original_source: Original T-SQL source text (preserved for diagnostics).
    """
    name: str
    parameters: tuple[IRVariable, ...] = field(default_factory=tuple)
    variables: tuple[IRVariable, ...] = field(default_factory=tuple)
    body: tuple[IRNode, ...] = field(default_factory=tuple)
    original_source: str = ""

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.PROCEDURE


@dataclass(frozen=True)
class IRVariable:
    """A declared variable or parameter.

    Variable names are normalized — the @ prefix is stripped during parsing.
    E.g., T-SQL `@product_id` becomes `product_id` in IR.

    Attributes:
        name: Normalized variable name (no @ prefix).
        data_type: SQL data type string, e.g. "INT", "VARCHAR(100)", "DECIMAL(10,2)".
        default_value: Optional default value expression.
        is_output: True for OUTPUT parameters.
        scope: LOCAL, PARAMETER, or CURSOR.
        source_line: Original source line for error reporting.
    """
    name: str
    data_type: str
    default_value: str | None = None
    is_output: bool = False
    scope: VariableScope = VariableScope.LOCAL
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.VARIABLE


@dataclass(frozen=True)
class IRAssign:
    """Variable assignment: SET @var = expression.

    Also handles SELECT @var = col FROM table — the expression field
    captures the full assignment source.

    Attributes:
        target: Variable name (no @ prefix).
        expression: Raw expression text for the right-hand side.
        is_scalar_query: True when the value comes from a scalar subquery
                         (e.g., SET @x = (SELECT COUNT(*) FROM t)).
        source_line: Original source line for error reporting.
    """
    target: str
    expression: str
    is_scalar_query: bool = False
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.ASSIGN


@dataclass(frozen=True)
class IRSQL:
    """A SQL statement within the procedure body.

    ONLY SELECT/INSERT/UPDATE/DELETE statements go through this node.
    Control flow statements (IF, WHILE) NEVER become IRSQL nodes.

    Attributes:
        sql_text: Raw SQL text as it appears in the source.
        sqlglot_ast: Optional parsed AST from sqlglot. None if sqlglot failed
                     or if parsing was skipped. Always preserved as fallback.
        is_dml: True for SELECT/INSERT/UPDATE/DELETE. False for DDL.
        is_select_into: True when the SQL is `SELECT @var = col FROM table`
                        (T-SQL pattern for variable assignment from query).
        target_variable: Variable name when is_select_into is True.
        source_line: Original source line.
    """
    sql_text: str
    sqlglot_ast: Any = None
    is_dml: bool = True
    is_select_into: bool = False
    target_variable: str | None = None
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.SQL


@dataclass(frozen=True)
class IRIf:
    """IF / THEN / ELSE conditional branch.

    Supports optional ELSE body and nested IF nodes (ELSE IF pattern).

    Attributes:
        condition: Raw condition expression text (e.g., "@x > 10").
        then_body: Tuple of IRNode nodes for the THEN branch.
        else_body: Tuple of IRNode nodes for the ELSE branch (empty if no ELSE).
        source_line: Original source line.
    """
    condition: str
    then_body: tuple[IRNode, ...] = field(default_factory=tuple)
    else_body: tuple[IRNode, ...] = field(default_factory=tuple)
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.IF


@dataclass(frozen=True)
class IRWhile:
    """WHILE loop.

    Attributes:
        condition: Raw condition expression text (e.g., "@counter < 10").
        body: Tuple of IRNode nodes for the loop body.
        source_line: Original source line.
    """
    condition: str
    body: tuple[IRNode, ...] = field(default_factory=tuple)
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.WHILE


@dataclass(frozen=True)
class IRTransaction:
    """Transaction control: BEGIN TRANSACTION / COMMIT / ROLLBACK.

    Not a container for steps — each transaction statement is a separate
    IRTransaction node. The transaction boundary is implicit in the ordering.

    Attributes:
        action: "BEGIN", "COMMIT", or "ROLLBACK".
        savepoint_name: Optional savepoint name for nested transactions.
        source_line: Original source line.
    """
    action: str
    savepoint_name: str | None = None
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.TRANSACTION


@dataclass(frozen=True)
class IRExec:
    """EXEC / EXECUTE procedure_name [arguments].

    Attributes:
        procedure_name: Name of the procedure to execute.
        arguments: Tuple of argument expressions (strings as in source).
        has_result_set: True if the procedure returns a result set.
        source_line: Original source line.
    """
    procedure_name: str
    arguments: tuple[str, ...] = field(default_factory=tuple)
    has_result_set: bool = False
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.EXEC


@dataclass(frozen=True)
class IRBlock:
    """Anonymous BEGIN...END block (scope grouping, no semantics beyond nesting).

    Used for explicit BEGIN...END blocks that don't correspond to IF/WHILE.
    """
    body: tuple[IRNode, ...] = field(default_factory=tuple)
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.BLOCK


@dataclass(frozen=True)
class IRReturn:
    """RETURN [value].

    In T-SQL, RETURN is used for both early exit and returning status codes.
    In PL/pgSQL, it returns a value from the function.

    Attributes:
        value: Optional return value expression (None = RETURN without value).
        source_line: Original source line.
    """
    value: str | None = None
    source_line: int = 0

    @property
    def node_type(self) -> IRNodeType:
        return IRNodeType.RETURN


# ---------------------------------------------------------------------------
# Union type — enables type narrowing in generators
# ---------------------------------------------------------------------------

IRNode = Union[
    IRProcedure,
    IRVariable,
    IRAssign,
    IRSQL,
    IRIf,
    IRWhile,
    IRTransaction,
    IRExec,
    IRBlock,
    IRReturn,
]
