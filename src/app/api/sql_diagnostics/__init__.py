"""
SQL Object-Level Diagnostics Engine — table / column / function / join analysis.

Pipeline:
    SQL → ObjectExtractor → RiskAnalyzer → Cross-DB Compatibility Report

Submodules:
    extractor          — Extract tables, columns, functions, joins from SQL
    analyzer           — Map objects to risk levels across target databases
    diagnose_schemas   — Pydantic request/response models
    diagnose_router    — POST /api/sql/diagnose endpoint
"""
