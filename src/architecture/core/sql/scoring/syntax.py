"""
Syntax Compatibility Score (weight: 30%).

Evaluates whether the SQL uses dialect-specific syntax that prevents
cross-database execution. Based on the lightweight SQL AST.

Scoring rules:
    - Starts at 100, deducts per incompatible pattern per DB
    - Average across target DBs
    - Patterns: TOP, GETDATE, ISNULL, LEN, bracket identifiers, NEWID
"""

from ..sql_ast import SqlAst
from ..score_schemas import Finding


# ---------------------------------------------------------------------------
# Per-pattern deduction rules
# ---------------------------------------------------------------------------

# Each rule: (deduction, function_name, issue_template, suggestion_template)
_SYNTAX_RULES: dict[str, dict[str, tuple[int, str, str, str]]] = {
    "TOP": {
        "kingbasees": (
            20,
            "TOP",
            "TOP N 语法在 KingbaseES 中不支持",
            "将 SELECT TOP N 替换为 SELECT ... LIMIT N",
        ),
        "dm8": (
            20,
            "TOP",
            "TOP N 语法在 DM8 中不支持",
            "将 SELECT TOP N 替换为 SELECT ... LIMIT N",
        ),
    },
    "GETDATE": {
        "kingbasees": (
            15,
            "GETDATE",
            "GETDATE() 函数在 KingbaseES 中不支持",
            "将 GETDATE() 替换为 NOW()",
        ),
        "dm8": (
            10,
            "GETDATE",
            "GETDATE() 函数在 DM8 中不支持",
            "将 GETDATE() 替换为 SYSDATE",
        ),
    },
    "GETUTCDATE": {
        "kingbasees": (
            15,
            "GETUTCDATE",
            "GETUTCDATE() 函数不支持",
            "将 GETUTCDATE() 替换为 NOW() AT TIME ZONE 'UTC'",
        ),
        "dm8": (
            15,
            "GETUTCDATE",
            "GETUTCDATE() 函数不支持",
            "将 GETUTCDATE() 替换为 SYS_EXTRACT_UTC(SYSTIMESTAMP)",
        ),
    },
    "ISNULL": {
        "kingbasees": (
            15,
            "ISNULL",
            "ISNULL() 函数在 KingbaseES 中不支持",
            "将 ISNULL(a, b) 替换为 COALESCE(a, b)",
        ),
        "dm8": (
            15,
            "ISNULL",
            "ISNULL() 函数在 DM8 中不支持",
            "将 ISNULL(a, b) 替换为 COALESCE(a, b)",
        ),
    },
    "LEN": {
        "kingbasees": (
            10,
            "LEN",
            "LEN() 函数在 KingbaseES 中不支持",
            "将 LEN() 替换为 LENGTH()",
        ),
        "dm8": (
            10,
            "LEN",
            "LEN() 函数在 DM8 中不支持",
            "将 LEN() 替换为 LENGTH()",
        ),
    },
    "NEWID": {
        "kingbasees": (
            10,
            "NEWID",
            "NEWID() 函数在 KingbaseES 中不支持",
            "将 NEWID() 替换为 GEN_RANDOM_UUID()",
        ),
        "dm8": (
            10,
            "NEWID",
            "NEWID() 函数在 DM8 中不支持",
            "将 NEWID() 替换为 SYS_GUID()",
        ),
    },
    "CHARINDEX": {
        "kingbasees": (
            10,
            "CHARINDEX",
            "CHARINDEX() 在 KingbaseES 中不支持（参数顺序与 POSITION 相反）",
            "将 CHARINDEX(a, b) 替换为 POSITION(a IN b) 或 STRPOS(b, a)",
        ),
        "dm8": (
            10,
            "CHARINDEX",
            "CHARINDEX() 在 DM8 中不支持",
            "将 CHARINDEX(a, b) 替换为 INSTR(b, a)",
        ),
    },
    "DATEADD": {
        "kingbasees": (
            10,
            "DATEADD",
            "DATEADD() 在 KingbaseES 中不支持",
            "将 DATEADD(unit, n, date) 替换为 date + INTERVAL 'n unit'",
        ),
        "dm8": (
            10,
            "DATEADD",
            "DATEADD() 在 DM8 中不支持",
            "将 DATEADD(unit, n, date) 替换为 DATEADD(unit, n, date) 或使用 DM8 等价函数",
        ),
    },
    "DATEDIFF": {
        "kingbasees": (
            10,
            "DATEDIFF",
            "DATEDIFF() 在 KingbaseES 中不支持",
            "将 DATEDIFF(unit, a, b) 替换为 EXTRACT(EPOCH FROM (b - a)) 等",
        ),
        "dm8": (
            10,
            "DATEDIFF",
            "DATEDIFF() 在 DM8 中可能需要调整",
            "检查 DM8 的 DATEDIFF 函数签名是否与 MSSQL 一致",
        ),
    },
    "DATEPART": {
        "kingbasees": (
            10,
            "DATEPART",
            "DATEPART() 在 KingbaseES 中不支持",
            "将 DATEPART(unit, date) 替换为 EXTRACT(unit FROM date)",
        ),
        "dm8": (
            10,
            "DATEPART",
            "DATEPART() 在 DM8 中不支持",
            "将 DATEPART(unit, date) 替换为 EXTRACT(unit FROM date)",
        ),
    },
}

# Bracket identifier deduction per DB
_BRACKET_DEDUCTION = 10
_BRACKET_ISSUE = "使用了 MSSQL 特有方括号标识符 [{idents}]"
_BRACKET_SUGGESTION = "将方括号标识符替换为双引号或去除"


def syntax_score(
    ast: SqlAst,
    db_types: list[str],
) -> tuple[float, list[Finding]]:
    """Calculate syntax compatibility score.

    Scores each target DB independently, then averages.
    MSSQL is always 100 (native syntax).

    Args:
        ast: The parsed SQL AST.
        db_types: Target database types.

    Returns:
        (score 0-100, list of findings)
    """
    findings: list[Finding] = []
    db_scores: dict[str, float] = {}

    for db_type in db_types:
        if db_type == "mssql":
            # MSSQL is the source — no syntax deductions
            db_scores[db_type] = 100.0
            continue

        score = 100.0

        # -- Check each function for incompatibility --
        for func_name in ast.functions:
            if func_name in _SYNTAX_RULES:
                rule = _SYNTAX_RULES[func_name]
                if db_type in rule:
                    deduction, _, issue_tpl, suggestion_tpl = rule[db_type]
                    score -= deduction
                    findings.append(
                        Finding(
                            type="syntax",
                            db=db_type,
                            issue=issue_tpl,
                            severity=_deduction_severity(deduction),
                            detail=suggestion_tpl,
                        )
                    )

        # -- Check bracket identifiers --
        if ast.has_brackets:
            idents_str = ", ".join(ast.bracket_idents[:5])
            if len(ast.bracket_idents) > 5:
                idents_str += f" ... ({len(ast.bracket_idents) - 5} more)"

            score -= _BRACKET_DEDUCTION
            findings.append(
                Finding(
                    type="syntax",
                    db=db_type,
                    issue=_BRACKET_ISSUE.format(idents=idents_str),
                    severity="medium",
                    detail=_BRACKET_SUGGESTION,
                )
            )

        db_scores[db_type] = max(score, 0.0)

    # Average across target DBs
    avg_score = sum(db_scores.values()) / len(db_scores) if db_scores else 100.0
    return round(avg_score, 1), findings


def _deduction_severity(deduction: int) -> str:
    """Map deduction amount to severity label."""
    if deduction >= 20:
        return "high"
    if deduction >= 15:
        return "medium"
    return "low"
