"""
Execution Compatibility Score (weight: 30%).

Evaluates whether the SQL can actually execute on each target database.
Based on the real execution results from compare_service.execute_compare().

Scoring rules:
    - 100 if all DBs execute successfully
    - Proportional deduction: (successful_dbs / total_dbs) * 100
    - Additional penalty for dialect-related errors
"""

from typing import Any

from ..score_schemas import Finding


# Keywords in error messages that specifically suggest dialect incompatibility
# (NOT general schema errors like "column does not exist" or "relation not found")
_DIALECT_ERROR_INDICATORS = [
    "syntax error",
    "parse error",
    "unrecognized",
    "unsupported",
    "not supported",
    "cannot be used",
    "unexpected token",
    "at or near",
    "incorrect syntax",
    "invalid syntax",
]


def execution_score(
    results: dict[str, dict[str, Any]],
) -> tuple[float, list[Finding]]:
    """Calculate execution success score.

    Args:
        results: {db_type: execution_result_dict} from execute_compare.

    Returns:
        (score 0-100, list of findings)
    """
    if not results:
        return 100.0, []

    findings: list[Finding] = []
    total = len(results)
    successful = 0

    for db_type, result in results.items():
        if result.get("success"):
            successful += 1
        else:
            error_msg = result.get("error", "")
            suggestion = result.get("suggestion", "")

            # Determine if this is a dialect error
            is_dialect = _is_dialect_error(error_msg)

            findings.append(
                Finding(
                    type="execution",
                    db=db_type,
                    issue=f"SQL 在 {db_type} 上执行失败: {_truncate_error(error_msg)}",
                    severity="high" if is_dialect else "medium",
                    detail=suggestion or _classify_error(error_msg),
                )
            )

    # Base score: proportion of successful executions
    raw_score = (successful / total) * 100.0 if total > 0 else 100.0

    # Apply dialect penalty: count unique DBs with dialect failures, not findings
    dialect_fail_dbs: set[str] = {
        f.db
        for f in findings
        if f.type == "execution" and f.severity == "high"
    }
    penalty = len(dialect_fail_dbs) * 10  # -10 per DB with dialect failure
    final_score = max(raw_score - penalty, 0.0)

    return round(final_score, 1), findings


def _is_dialect_error(error_msg: str) -> bool:
    """Check if an error message suggests a dialect/syntax incompatibility."""
    lower = error_msg.lower()
    return any(indicator in lower for indicator in _DIALECT_ERROR_INDICATORS)


def _truncate_error(error_msg: str, max_len: int = 200) -> str:
    """Truncate long error messages for findings display."""
    if len(error_msg) <= max_len:
        return error_msg
    return error_msg[: max_len - 3] + "..."


def _classify_error(error_msg: str) -> str:
    """Classify an error message into a category for user guidance."""
    lower = error_msg.lower()

    if "connect" in lower or "timeout" in lower or "refused" in lower:
        return "数据库连接失败 — 检查数据库服务是否运行"
    if "auth" in lower or "password" in lower or "login" in lower:
        return "认证失败 — 检查用户名和密码"
    if "syntax" in lower or "parse" in lower:
        return "SQL 语法不兼容 — 该数据库不支持此 SQL 方言"
    if "unsupported" in lower or "not supported" in lower:
        return "使用了该数据库不支持的语法或功能"
    if "does not exist" in lower:
        return "表或对象不存在 — 检查表名是否正确"
    if "invalid" in lower:
        return "SQL 包含无效的标识符或语法"
    if "memory" in lower:
        return "数据库内存不足 — 尝试减少返回行数"

    return "执行失败 — 请检查 SQL 语法和数据库状态"
