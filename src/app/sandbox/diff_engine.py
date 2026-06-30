"""
Deterministic Diff Engine — structured comparison of dual-DB execution results.

Layers:
    1. Data-level: row count, field values, ordering
    2. Schema-level: type differences, nullability, defaults
    3. Behavioral-level: API response shape, ORM result consistency

Integration with existing explanation_engine for 3-layer diff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# Diff Result Types
# =========================================================================


@dataclass(frozen=True)
class FieldDiff:
    """Single field-level difference."""
    field_name: str
    source_value: Any
    target_value: Any
    category: str = "value"  # value / type / nullability / ordering


@dataclass(frozen=True)
class RowDiff:
    """Single row-level difference."""
    row_index: int
    fields: list[FieldDiff] = field(default_factory=list)


@dataclass(frozen=True)
class DeterministicDiff:
    """Complete deterministic comparison result.

    This is more opinionated than the raw 3-layer diff — it applies
    test-case-specific tolerances, field filters, and known-issue annotations.
    """
    # Summary
    status: str  # MATCH / DIFF / ERROR
    row_count_match: bool
    data_match: bool
    column_match: bool

    # Detail
    source_row_count: int
    target_row_count: int
    source_columns: list[str]
    target_columns: list[str]
    field_diffs: list[FieldDiff] = field(default_factory=list)
    row_diffs: list[RowDiff] = field(default_factory=list)

    # Meta
    known_issues_matched: list[str] = field(default_factory=list)
    explanation: str = ""


# =========================================================================
# Diff Engine
# =========================================================================


class DiffEngine:
    """Deterministic comparison of source and target database results.

    Applies test-case-specific tolerances, field filters, and known-issue
    annotations to produce explainable diff results.
    """

    @staticmethod
    def compare(
        source_result: dict[str, Any],
        target_result: dict[str, Any],
        *,
        tolerance: dict[str, float] | None = None,
        ignore_fields: list[str] | None = None,
        check_fields: list[str] | None = None,
    ) -> DeterministicDiff:
        """Compare two execution results deterministically.

        Args:
            source_result: Source DB execution result dict
            target_result: Target DB execution result dict
            tolerance: Per-field numeric tolerance (e.g. {"price": 0.01})
            ignore_fields: Fields to exclude from comparison
            check_fields: Only compare these fields (None = compare all)

        Returns:
            DeterministicDiff with structured comparison results.
        """
        tolerance = tolerance or {}
        ignore_fields = ignore_fields or []

        # Handle error cases
        if not source_result.get("success"):
            return DeterministicDiff(
                status="ERROR",
                row_count_match=False,
                data_match=False,
                column_match=False,
                source_row_count=0,
                target_row_count=target_result.get("row_count", 0),
                source_columns=[],
                target_columns=target_result.get("columns", []),
                explanation=f"Source DB error: {source_result.get('error', 'Unknown')}",
            )

        if not target_result.get("success"):
            return DeterministicDiff(
                status="ERROR",
                row_count_match=False,
                data_match=False,
                column_match=False,
                source_row_count=source_result.get("row_count", 0),
                target_row_count=0,
                source_columns=source_result.get("columns", []),
                target_columns=[],
                explanation=f"Target DB error: {target_result.get('error', 'Unknown')}",
            )

        src_cols = source_result.get("columns", [])
        tgt_cols = target_result.get("columns", [])
        src_rows = source_result.get("rows", [])
        tgt_rows = target_result.get("rows", [])

        # Filter columns if check_fields specified
        if check_fields:
            src_indices = [i for i, c in enumerate(src_cols) if c in check_fields]
            tgt_indices = [i for i, c in enumerate(tgt_cols) if c in check_fields]
            src_cols_filtered = [src_cols[i] for i in src_indices]
            tgt_cols_filtered = [tgt_cols[i] for i in tgt_indices]
            src_rows = [[row[i] for i in src_indices] for row in src_rows]
            tgt_rows = [[row[i] for i in tgt_indices] for row in tgt_rows]
            src_cols = src_cols_filtered
            tgt_cols = tgt_cols_filtered

        # Remove ignored fields
        active_src_indices = [i for i, c in enumerate(src_cols) if c not in ignore_fields]
        active_tgt_indices = [i for i, c in enumerate(tgt_cols) if c not in ignore_fields]
        src_cols = [src_cols[i] for i in active_src_indices]
        tgt_cols = [tgt_cols[i] for i in active_tgt_indices]
        src_rows = [[row[i] for i in active_src_indices] for row in src_rows]
        tgt_rows = [[row[i] for i in active_tgt_indices] for row in tgt_rows]

        # Column comparison
        column_match = src_cols == tgt_cols

        # Row count comparison
        row_count_match = len(src_rows) == len(tgt_rows)

        # Data comparison
        field_diffs: list[FieldDiff] = []
        row_diffs: list[RowDiff] = []

        if not column_match:
            field_diffs.append(FieldDiff(
                field_name="[columns]",
                source_value=src_cols,
                target_value=tgt_cols,
                category="type",
            ))

        if row_count_match and column_match:
            max_rows = len(src_rows)
            for row_idx in range(max_rows):
                row_field_diffs: list[FieldDiff] = []
                for col_idx, col_name in enumerate(src_cols):
                    src_val = src_rows[row_idx][col_idx] if col_idx < len(src_rows[row_idx]) else None
                    tgt_val = tgt_rows[row_idx][col_idx] if col_idx < len(tgt_rows[row_idx]) else None

                    if not DiffEngine._values_equal(
                        src_val, tgt_val,
                        tolerance=tolerance.get(col_name),
                    ):
                        diff = FieldDiff(
                            field_name=col_name,
                            source_value=src_val,
                            target_value=tgt_val,
                            category=DiffEngine._categorize_diff(src_val, tgt_val),
                        )
                        row_field_diffs.append(diff)
                        field_diffs.append(diff)

                if row_field_diffs:
                    row_diffs.append(RowDiff(row_index=row_idx, fields=row_field_diffs))

        data_match = len(field_diffs) == 0

        # Determine overall status
        if not column_match or not row_count_match:
            status = "DIFF"
        elif not data_match:
            status = "DIFF"
        else:
            status = "MATCH"

        return DeterministicDiff(
            status=status,
            row_count_match=row_count_match,
            data_match=data_match,
            column_match=column_match,
            source_row_count=len(src_rows),
            target_row_count=len(tgt_rows),
            source_columns=src_cols,
            target_columns=tgt_cols,
            field_diffs=field_diffs,
            row_diffs=row_diffs,
            explanation=DiffEngine._build_explanation(
                status, row_count_match, column_match, data_match, field_diffs,
            ),
        )

    @staticmethod
    def _values_equal(
        src: Any,
        tgt: Any,
        tolerance: float | None = None,
    ) -> bool:
        """Compare two values with optional numeric tolerance.

        Handles:
        - None equality
        - Float/int/Decimal comparison with tolerance
        - String comparison
        - Boolean comparison (1/0 vs True/False)
        - Cross-type coercion (int vs str, Decimal vs str, etc.)
        """
        from decimal import Decimal

        # Both None
        if src is None and tgt is None:
            return True

        # One is None
        if src is None or tgt is None:
            return False

        # Boolean: accept 0/1 vs False/True vs 'True'/'False'
        if isinstance(src, bool) or isinstance(tgt, bool):
            src_bool = DiffEngine._to_bool(src)
            tgt_bool = DiffEngine._to_bool(tgt)
            if src_bool is not None and tgt_bool is not None:
                return src_bool == tgt_bool

        # Numeric comparison: handle int, float, Decimal, and numeric strings
        src_num = DiffEngine._to_number(src)
        tgt_num = DiffEngine._to_number(tgt)
        if src_num is not None and tgt_num is not None:
            if tolerance is not None:
                return abs(float(src_num) - float(tgt_num)) <= tolerance
            # If both are integers (no decimal part), compare as integers
            if src_num == int(src_num) and tgt_num == int(tgt_num):
                return int(src_num) == int(tgt_num)
            # Float comparison with small tolerance
            return abs(float(src_num) - float(tgt_num)) < 0.005

        # String comparison
        if isinstance(src, str) and isinstance(tgt, str):
            # Strip trailing whitespace (some DBs pad CHAR fields)
            return src.rstrip() == tgt.rstrip()

        # Fallback: coerce to string and compare
        return str(src).rstrip() == str(tgt).rstrip()

    @staticmethod
    def _to_number(val: Any) -> float | None:
        """Try to convert a value to a number. Returns None if not numeric."""
        from decimal import Decimal
        if isinstance(val, bool):
            return None  # Handle booleans separately
        if isinstance(val, (int, float, Decimal)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _to_bool(val: Any) -> bool | None:
        """Try to convert a value to a boolean."""
        if isinstance(val, bool):
            return val
        if isinstance(val, int):
            return bool(val)
        if isinstance(val, str):
            low = val.strip().lower()
            if low in ('true', '1', 'yes', 't', 'y'):
                return True
            if low in ('false', '0', 'no', 'f', 'n'):
                return False
        return None

    @staticmethod
    def _categorize_diff(src: Any, tgt: Any) -> str:
        """Categorize the type of difference."""
        if src is None or tgt is None:
            return "nullability"
        if isinstance(src, bool) or isinstance(tgt, bool):
            return "boolean"
        if isinstance(src, (int, float)) and isinstance(tgt, (int, float)):
            return "precision"
        if isinstance(src, str) and isinstance(tgt, str):
            return "collation"
        if type(src) != type(tgt):
            return "type_mapping"
        return "value"

    @staticmethod
    def _build_explanation(
        status: str,
        row_count_match: bool,
        column_match: bool,
        data_match: bool,
        field_diffs: list[FieldDiff],
    ) -> str:
        """Build a human-readable explanation of the diff."""
        if status == "MATCH":
            return "源库和目标库结果完全一致。"

        parts: list[str] = []
        if not column_match:
            parts.append("列结构不一致。")
        if not row_count_match:
            parts.append("返回行数不一致。")
        if not data_match and field_diffs:
            categories = set(d.category for d in field_diffs)
            cat_names = {
                "precision": "数值精度差异",
                "type_mapping": "类型映射差异",
                "nullability": "NULL 处理差异",
                "boolean": "布尔表示差异",
                "collation": "字符串排序/比较差异",
                "value": "数据值差异",
            }
            for cat in sorted(categories):
                name = cat_names.get(cat, cat)
                count = sum(1 for d in field_diffs if d.category == cat)
                parts.append(f"{name}（{count} 处）。")

        return " ".join(parts) if parts else "存在未分类的差异。"


# =========================================================================
# Behavioral Diff (API / ORM consistency)
# =========================================================================


@dataclass(frozen=True)
class BehavioralDiff:
    """API/ORM behavioral comparison result."""
    status: str  # MATCH / DIFF / ERROR
    response_shape_match: bool
    status_code_match: bool
    field_type_match: bool
    details: list[str] = field(default_factory=list)


class BehavioralDiffEngine:
    """Compare API response shapes and ORM result consistency."""

    @staticmethod
    def compare_api_responses(
        source_response: dict[str, Any],
        target_response: dict[str, Any],
    ) -> BehavioralDiff:
        """Compare two API response shapes."""
        details: list[str] = []

        src_keys = set(source_response.keys()) if source_response else set()
        tgt_keys = set(target_response.keys()) if target_response else set()
        response_shape_match = src_keys == tgt_keys

        if not response_shape_match:
            missing = src_keys - tgt_keys
            extra = tgt_keys - src_keys
            if missing:
                details.append(f"Source-only keys: {sorted(missing)}")
            if extra:
                details.append(f"Target-only keys: {sorted(extra)}")

        status_code_match = (
            source_response.get("success") == target_response.get("success")
        )

        # Basic field type comparison
        field_type_match = True
        for key in src_keys & tgt_keys:
            src_val = source_response.get(key)
            tgt_val = target_response.get(key)
            if type(src_val).__name__ != type(tgt_val).__name__:
                field_type_match = False
                details.append(
                    f"Type mismatch for '{key}': "
                    f"{type(src_val).__name__} vs {type(tgt_val).__name__}"
                )

        if response_shape_match and status_code_match and field_type_match:
            status = "MATCH"
        else:
            status = "DIFF"

        return BehavioralDiff(
            status=status,
            response_shape_match=response_shape_match,
            status_code_match=status_code_match,
            field_type_match=field_type_match,
            details=details,
        )
