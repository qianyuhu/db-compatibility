"""
SQL Rewrite Engine — cross-database SQL transformation.

Pipeline:
    SQL → AST Normalization → Rule Matching → Rewrite → Validation → Output

Submodules:
    ast_normalizer  — Normalize dialect-specific SQL to a common AST
    rules           — Transformation rules by (source_db, target_db)
    engine          — Orchestrates the rewrite pipeline
"""
