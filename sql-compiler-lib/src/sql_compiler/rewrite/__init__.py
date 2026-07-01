"""SQL Rewrite Engine — MSSQL → KingbaseES / DM8 / PostgreSQL.

Public API:
    - rewrite_sql(sql, source_db, target_db) -> RewriteResult
    - MSSQL_TO_KBES_MSSQL_RULES (23 rules for KingbaseES MSSQL-compat mode)
    - MSSQL_TO_PG_RULES (33 rules for full PostgreSQL migration)
    - MSSQL_TO_DM8_RULES (rules for DM8 migration)
"""

from __future__ import annotations

from .engine import rewrite_sql, RewriteResult
from .rules import (
    RewriteRule,
    MSSQL_TO_PG_RULES,
    MSSQL_TO_KBES_MSSQL_RULES,
    MSSQL_TO_DM8_RULES,
    RULE_REGISTRY,
)
from .sql_ast import parse_ast, SqlAst

__all__ = [
    "rewrite_sql",
    "RewriteResult",
    "RewriteRule",
    "MSSQL_TO_PG_RULES",
    "MSSQL_TO_KBES_MSSQL_RULES",
    "MSSQL_TO_DM8_RULES",
    "RULE_REGISTRY",
    "parse_ast",
    "SqlAst",
]
