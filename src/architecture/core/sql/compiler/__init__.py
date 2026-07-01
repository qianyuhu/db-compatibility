"""
🚀 Hybrid Migration Engine — T-SQL Stored Procedure → Control Flow IR → Target Code
   + Interactive CFG Execution Workbench

Three-stage database procedural compiler:

    T-SQL SP
       ↓
    [1] Lexer + Block Segmenter
       ↓
    [2] Control Flow Extractor → IR Builder (sqlglot for SQL sub-statements only)
       ↓
    [3] Target Code Generator (PL/pgSQL / DM Procedure)
       ↓
    [CFG Builder] → CFG (with branch-preserving edges)
       ↓
    [Serializer] → UI Graph Model (React Flow compatible)
       ↓
    [Execution Engine] → Multi-DB node execution + diff comparison
       ↓
    [Validator] Execution Validation via existing DBAdapter + DiffEngine

Usage:
    from architecture.core.sql.compiler import compile_sp

    result = compile_sp(tsql_text, target_db="kingbasees")
    if result.success:
        print(result.generated_code)
"""

from .engine import SPCompiler, CompilationResult, compile_sp

__all__ = [
    "SPCompiler",
    "CompilationResult",
    "compile_sp",
]
