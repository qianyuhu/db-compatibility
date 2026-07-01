"""
Risk Assessment Score (weight: 15%).

Evaluates migration risk based on dialect-specific features and known
incompatibilities between MSSQL and target databases.

Risk rules:
    - MSSQL-specific syntax usage
    - Non-standard SQL functions
    - Known database-specific behaviors
    - Deprecated or vendor-locked features

Scoring:
    - Starts at 100, deduct per risk rule
    - MSSQL-only syntax: -30
    - Non-standard function: -15 per function type
    - Known incompatibility: -40
    - Deprecated features: -20
"""

from typing import Any

from ..sql_ast import SqlAst
from ..score_schemas import Finding


# Functions considered non-standard (vendor-specific)
_NON_STANDARD_FUNCTIONS = {
    "GETDATE": "MSSQL 特有日期函数",
    "GETUTCDATE": "MSSQL 特有 UTC 日期函数",
    "ISNULL": "MSSQL/T-SQL 特有空值处理",
    "LEN": "MSSQL/T-SQL 特有（标准 SQL 使用 LENGTH）",
    "NEWID": "MSSQL 特有 UUID 生成函数",
    "CHARINDEX": "MSSQL 特有字符串搜索（参数顺序与 POSITION 相反）",
    "DATEADD": "MSSQL 特有日期运算",
    "DATEDIFF": "MSSQL 特有日期差值",
    "DATEPART": "MSSQL 特有日期部分提取",
    # Note: TOP is handled separately via ast.has_top (syntax pattern, not function)
    "PATINDEX": "MSSQL 特有模式匹配",
    "STUFF": "MSSQL 特有字符串替换",
    "REPLICATE": "MSSQL 特有字符串重复",
    "SPACE": "MSSQL 特有空格生成",
    "SCOPE_IDENTITY": "MSSQL 特有作用域标识",
}

# Known high-risk patterns
_HIGH_RISK_PATTERNS: list[tuple[str, str]] = [
    ("sys.tables", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("sys.columns", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("sys.indexes", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("sys.schemas", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("sys.views", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("sys.procedures", "MSSQL 系统目录表，在其他数据库中不存在"),
    ("INFORMATION_SCHEMA", "跨数据库系统表可能存在差异"),
    ("@@ROWCOUNT", "MSSQL 全局变量，其他数据库不支持"),
    ("@@IDENTITY", "MSSQL 全局变量，其他数据库不支持"),
    ("@@ERROR", "MSSQL 全局变量，其他数据库不支持"),
    ("@@VERSION", "MSSQL 全局变量，其他数据库不支持"),
    ("@@TRANCOUNT", "MSSQL 全局变量，其他数据库不支持"),
]

# Features that are deprecated or vendor-locked
_DEPRECATED_PATTERNS: list[tuple[str, str]] = [
    ("TEXTIMAGE_ON", "MSSQL 专有存储选项"),
    ("WITH (NOLOCK)", "MSSQL 专有表提示"),
    ("WITH (READUNCOMMITTED)", "MSSQL 专有隔离级别提示"),
    ("FILESTREAM", "MSSQL 专有文件流功能"),
]


def risk_score(
    ast: SqlAst,
    results: dict[str, dict[str, Any]],
) -> tuple[float, list[Finding]]:
    """Calculate risk assessment score.

    Args:
        ast: The parsed SQL AST.
        results: Execution results from execute_compare.

    Returns:
        (score 0-100, list of findings)
    """
    findings: list[Finding] = []
    score = 100.0
    upper_sql = ast.raw_sql.upper()

    # -- Risk 1: Non-standard functions --
    non_standard_count = 0
    for func_name in ast.functions:
        if func_name in _NON_STANDARD_FUNCTIONS:
            non_standard_count += 1
            findings.append(
                Finding(
                    type="risk",
                    db="all",
                    issue=(
                        f"使用了非标准函数 {func_name}(): "
                        f"{_NON_STANDARD_FUNCTIONS[func_name]}"
                    ),
                    severity="medium",
                    detail=f"非标准函数 {func_name}() 增加迁移风险",
                )
            )

    # Each unique non-standard function adds risk
    func_penalty = min(non_standard_count * 15, 60)
    score -= func_penalty

    # -- Risk 2: MSSQL-specific syntax patterns --
    if ast.has_top:
        score -= 30
        findings.append(
            Finding(
                type="risk",
                db="mssql",
                issue="使用了 MSSQL 特有 TOP 语法",
                severity="high",
                detail="TOP N 是 MSSQL 专属语法，标准 SQL 和大多数数据库使用 LIMIT",
            )
        )

    if ast.has_brackets:
        score -= 20
        findings.append(
            Finding(
                type="risk",
                db="mssql",
                issue="使用了 MSSQL 特有方括号标识符",
                severity="medium",
                detail="方括号标识符是 MSSQL 特有语法，标准 SQL 使用双引号",
            )
        )

    # -- Risk 3: Known incompatible patterns --
    for pattern, description in _HIGH_RISK_PATTERNS:
        if pattern.upper() in upper_sql:
            score -= 40
            findings.append(
                Finding(
                    type="risk",
                    db="all",
                    issue=f"高风险: {description}",
                    severity="critical",
                    detail=f"检测到 {pattern}，在各数据库中行为不同或不存在",
                )
            )
            break  # Only flag once for system table usage

    # -- Risk 4: Deprecated/vendor-locked features --
    for pattern, description in _DEPRECATED_PATTERNS:
        if pattern.upper() in upper_sql:
            score -= 20
            findings.append(
                Finding(
                    type="risk",
                    db="mssql",
                    issue=f"使用了 MSSQL 专有功能: {description}",
                    severity="high",
                    detail=f"{pattern} 在其他数据库中不可用，需要重新设计",
                )
            )
            break  # Only flag once

    # -- Risk 5: Execution failures indicate risk --
    failed_dbs = [
        db for db, r in results.items() if not r.get("success")
    ]
    if failed_dbs:
        score -= len(failed_dbs) * 10
        for db in failed_dbs:
            findings.append(
                Finding(
                    type="risk",
                    db=db,
                    issue=f"{db} 执行失败，存在兼容性风险",
                    severity="high",
                    detail=(
                        f"SQL 在 {db} 上无法执行，需要改写才能迁移"
                    ),
                )
            )

    return round(max(score, 0.0), 1), findings
