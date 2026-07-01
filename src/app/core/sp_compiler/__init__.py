"""Re-export shim — canonical location: architecture.core.sql.compiler"""
from architecture.core.sql.compiler.engine import SPCompiler, CompilationResult, compile_sp  # noqa: F401

__all__ = ["SPCompiler", "CompilationResult", "compile_sp"]
