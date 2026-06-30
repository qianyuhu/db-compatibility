"""
SQL Compatibility Engine — 结构化 SQL 兼容性分析和迁移验证引擎。

Pipeline:
    SQL Input → Parser (AST) → Dialect Analyzer → Rewrite Engine
    → Compatibility Scorer → Execution (Dual DB) → Diff + Explanation

核心能力:
    1. SQL 分类 (SELECT / JOIN / GROUP BY / WINDOW / SUBQUERY / LIMIT / MERGE / DATE)
    2. 语法重写 (TOP→LIMIT, DATEPART→EXTRACT, ISNULL→COALESCE 等)
    3. 兼容性评分 (0-100)
    4. 风险标签 (LOW / MEDIUM / HIGH / BLOCKER)
    5. 双库执行 + 差异解释

Usage:
    from app.core.sql_compatibility_engine.classifier import classify_sql
    from app.core.sql_compatibility_engine.scorer import compute_compatibility_score
    from app.core.sql_compatibility_engine.engine import CompatibilityEngine
"""

# Lazy imports to avoid circular dependency chains during module initialization.
# Use the submodules directly:
#   from app.core.sql_compatibility_engine.classifier import classify_sql
#   from app.core.sql_compatibility_engine.engine import CompatibilityEngine
