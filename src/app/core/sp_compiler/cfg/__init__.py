"""
Control Flow Graph — IR → CFG conversion and optimization.

The CFG layer adds execution-path semantics on top of the structural IR:
    - Basic blocks with single entry / single exit
    - Explicit branch edges (true/false for IF)
    - Back edges (for WHILE loops)
    - Join/merge points
"""

from .builder import BasicBlock, CFG, CFGBuilder
from .optimizer import CFGOptimizer

__all__ = [
    "BasicBlock",
    "CFG",
    "CFGBuilder",
    "CFGOptimizer",
]
