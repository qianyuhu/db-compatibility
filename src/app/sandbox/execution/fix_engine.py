"""
Fix Strategy Engine — generates and applies fix plans for classified issues.

Fix Types:
A. SQL Rewrite Fix — automatic dialect conversion (LIMIT↔TOP, DATEPART↔EXTRACT, etc.)
B. Schema Adjustment Fix — type mapping correction (NVARCHAR(MAX)→TEXT, etc.)
C. Data Normalization Fix — precision rounding alignment (ROUND, CAST)
D. Query Behavior Fix — ORM adjustment rules (column mapping, lazy loading)

Each fix produces a FixStrategy plan and a FixResult after application.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from .schemas import (
    FixResult,
    FixStrategy,
    FixType,
    IssueSeverity,
    IssueStatus,
    IssueType,
    MigrationIssue,
)


# =========================================================================
# SQL Rewrite Rules
# =========================================================================

# Pattern: (source_pattern, target_replacement, description, applicable_dbs)
SQL_REWRITE_RULES: list[dict[str, Any]] = [
    {
        "name": "limit_to_top",
        "pattern": r"LIMIT\s+(\d+)\s*$",
        "replacement": r"TOP \1",
        "description": "Convert LIMIT to TOP for MSSQL compatibility",
        "source_db": "kingbasees",
        "target_db": "mssql",
        "confidence": 0.95,
    },
    {
        "name": "top_to_limit",
        "pattern": r"SELECT\s+TOP\s+(\d+)",
        "replacement": r"SELECT",
        "post_append": " LIMIT \\1",
        "description": "Convert TOP to LIMIT for KingbaseES/DM8 compatibility",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.90,
        "note": "Requires post-processing to append LIMIT",
    },
    {
        "name": "datepart_to_extract",
        "pattern": r"DATEPART\(\s*(\w+)\s*,\s*",
        "replacement": r"EXTRACT(\1 FROM ",
        "description": "Convert DATEPART to EXTRACT",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.85,
        "note": "Requires closing parenthesis fix",
    },
    {
        "name": "getdate_to_now",
        "pattern": r"GETDATE\(\)",
        "replacement": r"CURRENT_TIMESTAMP",
        "description": "Convert GETDATE() to CURRENT_TIMESTAMP",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.98,
    },
    {
        "name": "newid_to_uuid",
        "pattern": r"NEWID\(\)",
        "replacement": r"gen_random_uuid()",
        "description": "Convert NEWID() to gen_random_uuid()",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.95,
    },
    {
        "name": "isnull_to_coalesce",
        "pattern": r"ISNULL\(\s*([^,]+)\s*,\s*([^)]+)\s*\)",
        "replacement": r"COALESCE(\1, \2)",
        "description": "Convert ISNULL to COALESCE",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.97,
    },
    {
        "name": "fetch_next_to_limit",
        "pattern": r"OFFSET\s+(\d+)\s+ROWS\s+FETCH\s+NEXT\s+(\d+)\s+ROWS\s+ONLY",
        "replacement": r"LIMIT \2 OFFSET \1",
        "description": "Convert FETCH NEXT to LIMIT OFFSET",
        "source_db": "mssql",
        "target_db": "kingbasees",
        "confidence": 0.93,
    },
]

# Schema type mappings: (source_type_pattern, target_type, rule)
SCHEMA_TYPE_MAPPINGS: dict[str, dict[str, str]] = {
    "mssql": {
        "NVARCHAR\\(MAX\\)": "TEXT",
        "VARCHAR\\(MAX\\)": "TEXT",
        "VARBINARY\\(MAX\\)": "BYTEA",
        "UNIQUEIDENTIFIER": "UUID",
        "DATETIME2": "TIMESTAMP",
        "DATETIMEOFFSET": "TIMESTAMPTZ",
        "MONEY": "NUMERIC(19,4)",
        "SMALLMONEY": "NUMERIC(10,4)",
        "BIT": "BOOLEAN",
        "IMAGE": "BYTEA",
        "NTEXT": "TEXT",
    },
    "kingbasees": {
        "TEXT": "NVARCHAR(MAX)",
        "BYTEA": "VARBINARY(MAX)",
        "UUID": "UNIQUEIDENTIFIER",
        "TIMESTAMP": "DATETIME2",
        "TIMESTAMPTZ": "DATETIMEOFFSET",
        "BOOLEAN": "BIT",
    },
}


# =========================================================================
# Fix Strategy Engine
# =========================================================================


class FixStrategyEngine:
    """Generates and applies fix strategies for classified migration issues.

    Usage:
        engine = FixStrategyEngine(source_db="mssql", target_db="kingbasees")
        strategy = engine.generate_strategy(issue)
        result = engine.apply_fix(strategy, test_runner)
    """

    def __init__(self, source_db: str, target_db: str):
        self.source_db = source_db
        self.target_db = target_db

    # =========================================================================
    # Strategy Generation
    # =========================================================================

    def generate_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate a fix strategy for a classified issue.

        Returns a FixStrategy with concrete steps tailored to the issue type.
        """
        if issue.issue_type == IssueType.SQL_REWRITE:
            return self._sql_rewrite_strategy(issue)
        elif issue.issue_type == IssueType.SCHEMA_MAPPING:
            return self._schema_adjustment_strategy(issue)
        elif issue.issue_type == IssueType.DATA_PRECISION:
            return self._data_normalization_strategy(issue)
        elif issue.issue_type == IssueType.ORM_BEHAVIOR:
            return self._query_behavior_strategy(issue)
        elif issue.issue_type == IssueType.API_CONTRACT:
            return self._api_contract_strategy(issue)
        else:
            return self._generic_strategy(issue)

    def generate_strategies(self, issues: list[MigrationIssue]) -> list[FixStrategy]:
        """Generate fix strategies for a batch of issues."""
        return [self.generate_strategy(issue) for issue in issues]

    # =========================================================================
    # Fix Application
    # =========================================================================

    def apply_fix(
        self,
        strategy: FixStrategy,
        test_runner: Any | None = None,
    ) -> FixResult:
        """Apply a fix strategy and (optionally) re-run affected tests.

        Args:
            strategy: The fix strategy to apply
            test_runner: MigrationTestRunner instance for re-running tests

        Returns:
            FixResult with success/failure, before/after state, and re-run results
        """
        start = time.perf_counter()
        before_state = {"strategy": strategy.to_dict()}

        try:
            # Step 1: Apply the fix based on type
            if strategy.fix_type == FixType.SQL_REWRITE:
                success, message = self._apply_sql_rewrite(strategy)
            elif strategy.fix_type == FixType.SCHEMA_ADJUSTMENT:
                success, message = self._apply_schema_adjustment(strategy)
            elif strategy.fix_type == FixType.DATA_NORMALIZATION:
                success, message = self._apply_data_normalization(strategy)
            elif strategy.fix_type == FixType.QUERY_BEHAVIOR:
                success, message = self._apply_query_behavior_fix(strategy)
            else:
                success, message = False, f"Unknown fix type: {strategy.fix_type}"

            after_state = {"applied": success, "message": message}

            # Step 2: Re-run affected tests
            re_run_results: list[dict[str, Any]] = []
            if success and test_runner:
                try:
                    re_run_results = self._re_run_affected_tests(strategy, test_runner)
                except Exception as exc:
                    re_run_results = [{"error": f"Re-run failed: {exc}"}]

            elapsed = round((time.perf_counter() - start) * 1000, 1)

            return FixResult(
                issue_id=strategy.issue_id,
                fix_type=strategy.fix_type,
                success=success,
                message=message,
                before_state=before_state,
                after_state=after_state,
                re_run_results=re_run_results,
                elapsed_ms=elapsed,
            )

        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return FixResult(
                issue_id=strategy.issue_id,
                fix_type=strategy.fix_type,
                success=False,
                message=f"Fix application error: {exc}",
                before_state=before_state,
                after_state={"error": str(exc)},
                re_run_results=[],
                elapsed_ms=elapsed,
            )

    # =========================================================================
    # Strategy Generators (private)
    # =========================================================================

    def _sql_rewrite_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate SQL rewrite fix strategy."""
        error_msg = issue.diff_detail.get("error_message", "")
        steps: list[str] = []
        rewrite_rules: list[str] = []
        rewritten_sql = ""
        confidence = 0.0

        # Match against known rewrite rules
        for rule in SQL_REWRITE_RULES:
            if rule["source_db"] == self.source_db and rule["target_db"] == self.target_db:
                pattern = rule["pattern"]
                if re.search(pattern, error_msg, re.IGNORECASE):
                    rewrite_rules.append(rule["name"])
                    steps.append(f"Apply rule: {rule['name']} — {rule['description']}")
                    confidence = max(confidence, rule["confidence"])

        if not rewrite_rules:
            steps = [
                f"1. 分析 SQL 语法错误: {error_msg[:200]}",
                "2. 识别不兼容的 SQL 语法元素（LIMIT/TOP/DATEPART 等）",
                "3. 使用 dialect-specific rewrite 引擎转换 SQL",
                "4. 在目标库上验证改写后的 SQL 执行结果",
            ]
            confidence = 0.5

        steps.append(f"5. 重新运行受影响测试: {issue.affected_test_ids}")

        return FixStrategy(
            fix_type=FixType.SQL_REWRITE,
            issue_id=issue.issue_id,
            description=f"SQL 方言重写: {issue.description[:100]}",
            steps=steps,
            original_sql=issue.diff_detail.get("error_message", ""),
            rewritten_sql=rewritten_sql,
            rewrite_rules=rewrite_rules,
            estimated_success_probability=confidence,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    def _schema_adjustment_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate schema adjustment fix strategy."""
        table = issue.table_name or "(检测表名)"
        field = issue.field_name or "(检测字段)"

        steps = [
            f"1. 检测 {table}.{field} 的类型映射问题",
            f"2. 从当前类型映射规则查找目标类型",
            f"3. 生成 ALTER TABLE 或 CAST 语句",
            f"4. 验证类型转换后数据不丢失精度",
            f"5. 重新运行受影响测试",
        ]

        # Try to find a type mapping rule
        type_rule = ""
        source_type = ""
        target_type = ""
        source_mappings = SCHEMA_TYPE_MAPPINGS.get(self.source_db, {})
        for src_pat, tgt in source_mappings.items():
            if re.search(src_pat, issue.root_cause, re.IGNORECASE):
                source_type = src_pat
                target_type = tgt
                type_rule = f"{self.source_db}.{src_pat} → {self.target_db}.{tgt}"
                break

        return FixStrategy(
            fix_type=FixType.SCHEMA_ADJUSTMENT,
            issue_id=issue.issue_id,
            description=f"Schema 类型调整: {table}.{field}",
            steps=steps,
            source_type=source_type,
            target_type=target_type,
            type_mapping_rule=type_rule,
            estimated_success_probability=0.80 if type_rule else 0.50,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    def _data_normalization_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate data normalization fix strategy."""
        steps = [
            "1. 识别有精度差异的字段",
            "2. 确定目标精度（根据业务需求）",
            "3. 应用 ROUND() / CAST() / TRUNC() 标准化函数",
            "4. 验证标准化后源库和目标库值一致",
            "5. 重新运行受影响测试",
        ]

        confidence = 0.75
        if "precision" in issue.root_cause.lower():
            steps.insert(2, "2a. 使用 ROUND(value, decimals) 统一舍入精度")
            confidence = 0.85
        elif "datetime" in issue.root_cause.lower():
            steps.insert(2, "2a. 使用 CAST(value AS TIMESTAMP) 统一时间精度")
            confidence = 0.80
        elif "rounding" in issue.root_cause.lower():
            steps.insert(2, "2a. 统一使用 ROUND() 或 TRUNC() 实现一致舍入")
            confidence = 0.70

        return FixStrategy(
            fix_type=FixType.DATA_NORMALIZATION,
            issue_id=issue.issue_id,
            description=f"数据精度标准化: {issue.field_name or issue.description[:100]}",
            steps=steps,
            estimated_success_probability=confidence,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    def _query_behavior_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate ORM query behavior fix strategy."""
        steps = [
            "1. 确认 ORM dialect 配置正确",
            "2. 排查 SQLAlchemy 生成的 SQL 在目标库的差异",
            "3. 添加 with_variant() 或 TypeDecorator 处理类型映射",
            "4. 验证查询结果一致性",
            "5. 重新运行受影响测试",
        ]

        if issue.known_issues if hasattr(issue, 'known_issues') else False:
            steps.append("6. 记录为已知差异，不需要额外修复")
            confidence = 0.90
        else:
            confidence = 0.50

        return FixStrategy(
            fix_type=FixType.QUERY_BEHAVIOR,
            issue_id=issue.issue_id,
            description=f"ORM 行为调整: {issue.description[:100]}",
            steps=steps,
            estimated_success_probability=confidence,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    def _api_contract_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate API contract fix strategy."""
        steps = [
            "1. 对比源库和目标库 API 响应结构",
            "2. 识别缺失/额外的字段和排序差异",
            "3. 在应用层添加字段映射或排序适配",
            "4. 验证 API 响应一致性",
            "5. 重新运行受影响测试",
        ]

        return FixStrategy(
            fix_type=FixType.QUERY_BEHAVIOR,
            issue_id=issue.issue_id,
            description=f"API 契约调整: {issue.description[:100]}",
            steps=steps,
            estimated_success_probability=0.70,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    def _generic_strategy(self, issue: MigrationIssue) -> FixStrategy:
        """Generate a generic fallback fix strategy."""
        return FixStrategy(
            fix_type=FixType.QUERY_BEHAVIOR,
            issue_id=issue.issue_id,
            description=f"通用修复: {issue.description[:100]}",
            steps=[
                f"1. 分析问题: {issue.root_cause[:100]}",
                "2. 查找类似已知问题的修复方案",
                "3. 应用修复并在目标库验证",
                "4. 重新运行受影响测试",
            ],
            estimated_success_probability=0.40,
            affected_test_count=len(issue.affected_test_ids),
            is_reversible=True,
        )

    # =========================================================================
    # Fix Application Helpers (private)
    # =========================================================================

    def _apply_sql_rewrite(self, strategy: FixStrategy) -> tuple[bool, str]:
        """Apply a SQL rewrite fix.

        In production, this would invoke the actual SQL rewrite engine.
        For Phase 1, records the strategy for manual or batch application.
        """
        rules = strategy.rewrite_rules
        if not rules:
            return False, "没有匹配的 SQL 重写规则 — 需要人工介入"

        # The rewrite is applied by recording the strategy.
        # Actual SQL re-execution happens in the loop engine's re-run phase.
        return True, (
            f"SQL 重写策略已记录: {', '.join(rules)}. "
            f"规则将在下次循环执行时自动应用。"
        )

    def _apply_schema_adjustment(self, strategy: FixStrategy) -> tuple[bool, str]:
        """Apply a schema adjustment fix."""
        if not strategy.type_mapping_rule:
            return False, "未找到类型映射规则 — 需要人工指定目标列类型"

        return True, (
            f"Schema 调整策略已记录: {strategy.type_mapping_rule}. "
            f"映射将在下次迁移脚本生成时应用。"
        )

    def _apply_data_normalization(self, strategy: FixStrategy) -> tuple[bool, str]:
        """Apply a data normalization fix."""
        return True, (
            f"数据标准化策略已记录. "
            f"标准化函数将在 SQL 生成时自动注入。"
        )

    def _apply_query_behavior_fix(self, strategy: FixStrategy) -> tuple[bool, str]:
        """Apply a query behavior fix."""
        return True, (
            f"ORM 行为调整策略已记录. "
            f"Dialect 适配规则将在 ORM 查询时应用。"
        )

    def _re_run_affected_tests(
        self,
        strategy: FixStrategy,
        test_runner: Any,
    ) -> list[dict[str, Any]]:
        """Re-run only the tests affected by this fix.

        Uses test dependency tracking to minimize re-execution scope.
        """
        results: list[dict[str, Any]] = []
        affected_ids = [strategy.issue_id]  # Use issue_id as proxy

        try:
            # Try to re-run by IDs if the runner supports it
            if hasattr(test_runner, 'run_by_ids'):
                runner_result = test_runner.run_by_ids(affected_ids)
                if hasattr(runner_result, 'test_results'):
                    for tr in runner_result.test_results:
                        results.append({
                            "test_id": getattr(tr, 'test_id', ''),
                            "test_name": getattr(tr, 'test_name', ''),
                            "status": getattr(tr, 'status', 'UNKNOWN'),
                        })
        except Exception as exc:
            results.append({"error": f"Re-run error: {exc}"})

        return results
