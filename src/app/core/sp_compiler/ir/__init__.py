"""
Re-export shim — canonical location: architecture.core.sql.compiler.ir

All IR node definitions live in the architecture layer. This module
re-exports them so that `from app.core.sp_compiler.ir import X` works
and resolves to the same class objects used by the compiler engine.
"""

from architecture.core.sql.compiler.ir import (  # noqa: F401
    IRNodeType,
    VariableScope,
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
    IRNode,
)

__all__ = [
    "IRNodeType",
    "VariableScope",
    "IRProcedure",
    "IRVariable",
    "IRAssign",
    "IRSQL",
    "IRIf",
    "IRWhile",
    "IRTransaction",
    "IRExec",
    "IRBlock",
    "IRReturn",
    "IRNode",
]
