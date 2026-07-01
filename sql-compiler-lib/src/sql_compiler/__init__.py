"""
SQL Compiler & Rewrite Library — MSSQL → KingbaseES / DM8 Migration Toolkit

Two core capabilities:

1. **SQL Rewrite Engine** — Rule-based SQL translation
   - rewrite_sql(sql, source_db, target_db) → RewriteResult
   - 33 MSSQL→PG rules, 23 MSSQL→KingbaseES(MSSQL-compat) rules, DM8 rules

2. **SP Compiler** — T-SQL Stored Procedure → Target Code
   - compile_sp(sp_text, target_db) → CompilationResult
   - Targets: KingbaseES (PL/pgSQL), DM8

Usage:
    from sql_compiler import compile_sp, rewrite_sql

    # Rewrite a single SQL statement
    result = rewrite_sql("SELECT TOP 10 * FROM t", "mssql", "kingbasees")

    # Compile a stored procedure
    sp_result = compile_sp(tsql_text, target_db="kingbasees")
"""

from .engine import SPCompiler, CompilationResult, compile_sp
from .rewrite import rewrite_sql, RewriteResult, RewriteRule

__all__ = [
    # SP Compiler
    "SPCompiler",
    "CompilationResult",
    "compile_sp",
    # SQL Rewrite
    "rewrite_sql",
    "RewriteResult",
    "RewriteRule",
]
