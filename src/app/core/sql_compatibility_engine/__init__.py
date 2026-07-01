"""Re-export shim — canonical location: architecture.core.sql.compat"""
from architecture.core.sql.compat.classifier import classify_sql  # noqa: F401
from architecture.core.sql.compat.scorer import compute_compatibility_score  # noqa: F401
from architecture.core.sql.compat.engine import CompatibilityEngine  # noqa: F401

__all__ = ["classify_sql", "compute_compatibility_score", "CompatibilityEngine"]
