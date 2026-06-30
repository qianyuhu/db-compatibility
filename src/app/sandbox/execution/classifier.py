"""
Issue Classifier — transforms test failures into typed, tracked issues.

Classification dimensions:
1. Error type (syntax, data, schema, behavior, contract)
2. Diff category (type_mapping, precision, boolean, nullability, collation)
3. Root cause heuristics (SQL dialect, type system, rounding rules)

Every classified issue follows the lifecycle:
    NEW → IDENTIFIED → FIXING → FIXED → VERIFIED → RESOLVED
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .schemas import (
    FixStrategy,
    IssueSeverity,
    IssueStatus,
    IssueType,
    MigrationIssue,
)


# =========================================================================
# Classification Rules
# =========================================================================

# Patterns in error messages that indicate SQL rewrite issues
SQL_REWRITE_PATTERNS: list[tuple[str, str]] = [
    ("LIMIT", "LIMIT vs TOP/ROWNUM dialect mismatch"),
    ("TOP", "TOP vs LIMIT dialect mismatch"),
    ("FETCH NEXT", "FETCH NEXT vs LIMIT dialect mismatch"),
    ("ROWNUM", "ROWNUM pseudo-column unsupported"),
    ("DATEPART", "DATEPART function not available"),
    ("DATEADD", "DATEADD function not available"),
    ("GETDATE", "GETDATE vs NOW() vs CURRENT_TIMESTAMP"),
    ("MERGE", "MERGE/UPSERT statement unsupported"),
    ("IDENTITY", "IDENTITY column syntax difference"),
    ("NEWID", "NEWID() vs UUID function"),
    ("SCOPE_IDENTITY", "SCOPE_IDENTITY() not available"),
    ("@@ROWCOUNT", "@@ROWCOUNT not available"),
    ("VARCHAR.*MAX", "VARCHAR(MAX) vs TEXT type mapping"),
    ("NVARCHAR", "NVARCHAR vs VARCHAR encoding difference"),
    ("UNIQUEIDENTIFIER", "UNIQUEIDENTIFIER vs UUID type mapping"),
    ("VARBINARY", "VARBINARY(MAX) vs BYTEA/BLOB mapping"),
    ("syntax error", "SQL syntax error — dialect incompatibility"),
    ("Syntax error", "SQL syntax error — dialect incompatibility"),
    ("could not be bound", "SQL parameter binding error"),
    ("column .* does not exist", "Column name case-sensitivity mismatch"),
    ("relation .* does not exist", "Table name case-sensitivity mismatch"),
]

# Diff categories → IssueType mapping
DIFF_CATEGORY_TO_ISSUE: dict[str, IssueType] = {
    "type_mapping": IssueType.SCHEMA_MAPPING,
    "precision": IssueType.DATA_PRECISION,
    "boolean": IssueType.SCHEMA_MAPPING,
    "nullability": IssueType.SCHEMA_MAPPING,
    "collation": IssueType.DATA_PRECISION,
    "datetime": IssueType.DATA_PRECISION,
    "ordering": IssueType.API_CONTRACT,
    "missing_column": IssueType.API_CONTRACT,
    "extra_column": IssueType.API_CONTRACT,
    "encoding": IssueType.DATA_PRECISION,
    "rounding": IssueType.DATA_PRECISION,
}

# Severity heuristics
SEVERITY_RULES: dict[tuple[bool, bool, bool], IssueSeverity] = {
    # (has_error, data_mismatch, is_known_issue)
    (True, False, False): IssueSeverity.HIGH,
    (True, True, False): IssueSeverity.BLOCKER,
    (False, True, False): IssueSeverity.MEDIUM,
    (False, False, True): IssueSeverity.LOW,
    (False, True, True): IssueSeverity.MEDIUM,
    (True, False, True): IssueSeverity.MEDIUM,
}


# =========================================================================
# Issue Classifier
# =========================================================================


class IssueClassifier:
    """Classify test failures into structured, typed issues.

    Usage:
        classifier = IssueClassifier(source_db="mssql", target_db="kingbasees")
        issue = classifier.classify(test_result, test_case)
        # → MigrationIssue with type, severity, root_cause
    """

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    # =========================================================================
    # Public API
    # =========================================================================

    def classify(
        self,
        test_result: Any,  # TestCaseResult
        test_case: Any | None = None,  # MigrationTestCase
    ) -> MigrationIssue:
        """Classify a single test failure into a MigrationIssue.

        Args:
            test_result: TestCaseResult from the sandbox runner
            test_case: Original MigrationTestCase definition (optional)

        Returns:
            MigrationIssue with full classification metadata
        """
        issue_type = self._determine_type(test_result)
        severity = self._determine_severity(test_result)
        root_cause = self._determine_root_cause(test_result, issue_type)
        description = self._build_description(test_result, issue_type)
        table_name, field_name = self._extract_table_field(test_result)

        # Generate stable issue ID from test ID + type
        issue_id = self._generate_issue_id(test_result, issue_type)

        # Collect affected test IDs
        affected_test_ids = [test_result.test_id] if hasattr(test_result, 'test_id') else []

        return MigrationIssue(
            issue_id=issue_id,
            issue_type=issue_type,
            severity=severity,
            status=IssueStatus.IDENTIFIED,
            test_id=test_result.test_id if hasattr(test_result, 'test_id') else "",
            test_name=test_result.test_name if hasattr(test_result, 'test_name') else "",
            source_db=self.source_db,
            target_db=self.target_db,
            table_name=table_name,
            field_name=field_name,
            description=description,
            root_cause=root_cause,
            diff_detail=self._extract_diff_detail(test_result),
            fix_strategy=None,
            fix_attempts=0,
            affected_test_ids=affected_test_ids,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

    def classify_batch(
        self,
        test_results: list[Any],
        test_cases: list[Any] | None = None,
    ) -> list[MigrationIssue]:
        """Classify multiple test results. Only returns issues for FAIL/ERROR results."""
        issues: list[MigrationIssue] = []
        tc_map: dict[str, Any] = {}
        if test_cases:
            tc_map = {tc.id: tc for tc in test_cases}

        for result in test_results:
            status = getattr(result, 'status', 'PASS')
            if status in ("FAIL", "ERROR"):
                tc = tc_map.get(getattr(result, 'test_id', ''))
                issue = self.classify(result, tc)
                issues.append(issue)

        return issues

    # =========================================================================
    # Classification Helpers
    # =========================================================================

    def _determine_type(self, test_result: Any) -> IssueType:
        """Determine the issue type from a test result."""
        error_msg = getattr(test_result, 'error_message', '') or ''
        diff_detail = getattr(test_result, 'diff_detail', []) or []
        category = getattr(test_result, 'category', '') or ''
        known_issues = getattr(test_result, 'known_issues', []) or []

        # Rule 1: Error message indicates SQL rewrite issue
        if error_msg:
            for pattern, _ in SQL_REWRITE_PATTERNS:
                import re
                if re.search(pattern, error_msg, re.IGNORECASE):
                    return IssueType.SQL_REWRITE

        # Rule 2: Diff category mapping
        if diff_detail:
            for diff in diff_detail:
                diff_cat = diff.get("category", "") if isinstance(diff, dict) else ""
                if diff_cat in DIFF_CATEGORY_TO_ISSUE:
                    return DIFF_CATEGORY_TO_ISSUE[diff_cat]

        # Rule 3: Category-based inference
        if category in ("sql_crud", "sql_aggregation", "sql_join", "sql_edge"):
            if error_msg:
                return IssueType.SQL_REWRITE
            return IssueType.DATA_PRECISION
        elif category == "schema":
            return IssueType.SCHEMA_MAPPING
        elif category in ("api_order", "api_inventory"):
            return IssueType.API_CONTRACT
        elif category == "orm":
            return IssueType.ORM_BEHAVIOR

        # Rule 4: Known issues → ORM behavior (expected variance)
        if known_issues:
            return IssueType.ORM_BEHAVIOR

        return IssueType.DATA_PRECISION  # Default

    def _determine_severity(self, test_result: Any) -> IssueSeverity:
        """Determine severity from test result characteristics."""
        has_error = bool(getattr(test_result, 'error_message', None))
        data_mismatch = not getattr(test_result, 'data_match', True)
        known_issues = bool(getattr(test_result, 'known_issues', None))

        # Check for blocker patterns
        if has_error:
            error_msg = str(getattr(test_result, 'error_message', '')).lower()
            blocker_patterns = [
                "connection refused", "could not connect", "access denied",
                "permission denied", "database .* not found", "login failed",
            ]
            for pattern in blocker_patterns:
                import re
                if re.search(pattern, error_msg):
                    return IssueSeverity.BLOCKER

        # Check diff detail for high-severity patterns
        diff_detail = getattr(test_result, 'diff_detail', []) or []
        if diff_detail:
            high_severity_cats = {"precision", "encoding", "missing_column"}
            for diff in diff_detail:
                cat = diff.get("category", "") if isinstance(diff, dict) else ""
                if cat in high_severity_cats:
                    return IssueSeverity.HIGH

        # Use severity rules table
        key = (has_error, data_mismatch, bool(known_issues))
        if key in SEVERITY_RULES:
            return SEVERITY_RULES[key]

        return IssueSeverity.MEDIUM

    def _determine_root_cause(self, test_result: Any, issue_type: IssueType) -> str:
        """Determine root cause from test result analysis."""
        error_msg = getattr(test_result, 'error_message', '') or ''
        diff_detail = getattr(test_result, 'diff_detail', []) or []

        if issue_type == IssueType.SQL_REWRITE:
            if error_msg:
                for pattern, explanation in SQL_REWRITE_PATTERNS:
                    import re
                    if re.search(pattern, error_msg, re.IGNORECASE):
                        return explanation
            return "SQL dialect incompatibility — syntax, function, or keyword difference"

        elif issue_type == IssueType.SCHEMA_MAPPING:
            if diff_detail:
                cats = set(d.get("category", "") if isinstance(d, dict) else "" for d in diff_detail)
                if "type_mapping" in cats:
                    return "数据类型映射差异 — 源库和目标库的列类型不兼容"
                if "boolean" in cats:
                    return "布尔值表示方式不同 — 1/0 vs t/f vs true/false"
                if "nullability" in cats:
                    return "NULL 值处理差异 — 默认值或约束不同"
            return "Schema 结构不一致 — 列定义或约束差异"

        elif issue_type == IssueType.DATA_PRECISION:
            if diff_detail:
                cats = set(d.get("category", "") if isinstance(d, dict) else "" for d in diff_detail)
                if "precision" in cats:
                    return "数值精度差异 — DECIMAL/NUMERIC 类型的精度或舍入规则不同"
                if "datetime" in cats:
                    return "日期时间精度或时区处理差异"
                if "rounding" in cats:
                    return "数值舍入规则差异 — 四舍五入 vs 银行家舍入"
            return "数据精度差异 — 源库和目标库的数值/时间精度不一致"

        elif issue_type == IssueType.ORM_BEHAVIOR:
            return "ORM 查询生成或行为差异 — SQLAlchemy dialect 实现不一致"

        elif issue_type == IssueType.API_CONTRACT:
            if diff_detail:
                cats = set(d.get("category", "") if isinstance(d, dict) else "" for d in diff_detail)
                if "missing_column" in cats:
                    return "API 响应字段缺失 — 目标库返回的列少于源库"
                if "extra_column" in cats:
                    return "API 响应包含额外字段 — 目标库返回了源库没有的列"
            return "API 响应契约不一致 — 字段名、顺序或类型差异"

        return "未知原因 — 需要人工分析"

    def _build_description(self, test_result: Any, issue_type: IssueType) -> str:
        """Build a human-readable issue description."""
        test_name = getattr(test_result, 'test_name', 'unknown test')
        diff_summary = getattr(test_result, 'diff_summary', '') or ''
        error_msg = getattr(test_result, 'error_message', '') or ''

        if error_msg:
            return f"[{test_name}] 执行错误: {error_msg[:200]}"

        if diff_summary:
            return f"[{test_name}] {diff_summary[:300]}"

        return f"[{test_name}] {issue_type.value} — 数据或结构不一致"

    def _extract_table_field(self, test_result: Any) -> tuple[str, str]:
        """Extract affected table and field from test result."""
        table_name = ""
        field_name = ""

        diff_detail = getattr(test_result, 'diff_detail', []) or []
        if diff_detail:
            first_diff = diff_detail[0] if isinstance(diff_detail[0], dict) else {}
            field_name = first_diff.get("field", "")
            # Try to parse table from field (e.g., "products.price" → table="products")
            if "." in field_name:
                parts = field_name.split(".", 1)
                table_name = parts[0]
                field_name = parts[1]

        return table_name, field_name

    def _extract_diff_detail(self, test_result: Any) -> dict[str, Any]:
        """Extract relevant diff detail as a plain dict."""
        diff_detail = getattr(test_result, 'diff_detail', []) or []
        error_msg = getattr(test_result, 'error_message', '') or ''

        return {
            "error_message": error_msg,
            "diff_summary": getattr(test_result, 'diff_summary', ''),
            "diff_items": [
                d if isinstance(d, dict) else str(d)
                for d in (diff_detail[:10] if diff_detail else [])
            ],
            "row_count_match": getattr(test_result, 'row_count_match', None),
            "data_match": getattr(test_result, 'data_match', None),
            "column_match": getattr(test_result, 'column_match', None),
        }

    @staticmethod
    def _generate_issue_id(test_result: Any, issue_type: IssueType) -> str:
        """Generate a stable, unique issue ID."""
        test_id = getattr(test_result, 'test_id', 'unknown')
        raw = f"{test_id}:{issue_type.value}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]
