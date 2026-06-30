"""
Control Flow Graph — IR → CFG conversion, optimization, and UI serialization.

The CFG layer adds execution-path semantics on top of the structural IR:
    - Basic blocks with single entry / single exit
    - Explicit branch edges (true/false for IF, loop_back for WHILE)
    - Control flow edge classification
    - Join/merge points
    - UI model serialization for React Flow visualization
"""

from .builder import BasicBlock, CFG, CFGBuilder, CFGEdge
from .optimizer import CFGOptimizer
from .serializer import (
    UIGraphModel,
    UIEdge,
    UINode,
    UINodeSource,
    serialize_cfg,
)

__all__ = [
    "BasicBlock",
    "CFG",
    "CFGBuilder",
    "CFGEdge",
    "CFGOptimizer",
    "UIGraphModel",
    "UIEdge",
    "UINode",
    "UINodeSource",
    "serialize_cfg",
]
