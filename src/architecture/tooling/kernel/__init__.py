"""
SQL Intelligence Kernel — unified semantic context and analysis orchestrator.

Architecture:
    SQL → ContextBuilder → SQLSemanticContext → SQLKernel → {
        diagnostics, rewrite, score, migration, simulation
    }

All 5 engines share a single SQLSemanticContext built once from the raw SQL.
No engine parses SQL independently — they consume the pre-built context.
"""

from .semantic_context import SQLSemanticContext, KernelResult
from .context_builder import build_context
from .kernel import SQLKernel

__all__ = [
    "SQLSemanticContext",
    "KernelResult",
    "build_context",
    "SQLKernel",
]
