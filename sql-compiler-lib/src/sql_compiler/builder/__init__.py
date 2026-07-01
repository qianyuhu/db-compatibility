"""
IR Builder — assembles and validates IRProcedure from extracted IR nodes.
"""

from .ir_builder import build_procedure, build_simple_procedure, IRBuildError

__all__ = [
    "build_procedure",
    "build_simple_procedure",
    "IRBuildError",
]
