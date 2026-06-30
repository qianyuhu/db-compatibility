"""
SQL Classifier — 检测和分类 SQL 语句中的语言特性。

识别以下 SQL 类别:
    - SELECT (基本查询)
    - JOIN (INNER / LEFT / RIGHT / FULL / CROSS)
    - GROUP BY (聚合)
    - WINDOW FUNCTION (窗口函数: ROW_NUMBER, RANK, LAG, LEAD 等)
    - SUBQUERY (子查询)
    - LIMIT / TOP (行数限制)
    - MERGE / UPSERT (合并操作)
    - DATE FUNCTIONS (日期函数: DATEPART, DATEADD, DATEDIFF 等)
    - CTE (WITH 子句)
    - UNION (集合操作)
    - TRANSACTION (事务控制)
    - AGGREGATION (聚合函数: SUM, AVG, COUNT, MIN, MAX)

返回分类结果和各类特性的计数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


# =========================================================================
# Enums
# =========================================================================


class RiskLevel(str, Enum):
    """兼容性风险等级。"""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKER = "blocker"


class SqlCategory(str, Enum):
    """SQL 语句类别。"""

    SELECT = "SELECT"
    JOIN = "JOIN"
    GROUP_BY = "GROUP_BY"
    WINDOW_FUNCTION = "WINDOW_FUNCTION"
    SUBQUERY = "SUBQUERY"
    LIMIT_TOP = "LIMIT_TOP"
    MERGE_UPSERT = "MERGE_UPSERT"
    DATE_FUNCTIONS = "DATE_FUNCTIONS"
    CTE = "CTE"
    UNION = "UNION"
    TRANSACTION = "TRANSACTION"
    AGGREGATION = "AGGREGATION"
    ORDER_BY = "ORDER_BY"
    HAVING = "HAVING"
    DISTINCT = "DISTINCT"


# =========================================================================
# Data Classes
# =========================================================================


@dataclass(frozen=True)
class FeatureDetection:
    """检测到的单个 SQL 特性。"""

    category: SqlCategory
    count: int = 1
    details: list[str] = field(default_factory=list)  # 特性详情
    risk: RiskLevel = RiskLevel.NONE


@dataclass(frozen=True)
class ClassificationResult:
    """SQL 分类结果。"""

    categories: list[SqlCategory]
    features: list[FeatureDetection]
    statement_type: str  # DML / DDL / DCL / TCL
    complexity: str  # simple / medium / complex
    total_features: int = 0

    @property
    def has_window_functions(self) -> bool:
        return SqlCategory.WINDOW_FUNCTION in self.categories

    @property
    def has_subquery(self) -> bool:
        return SqlCategory.SUBQUERY in self.categories

    @property
    def has_joins(self) -> bool:
        return SqlCategory.JOIN in self.categories

    @property
    def has_merge(self) -> bool:
        return SqlCategory.MERGE_UPSERT in self.categories

    @property
    def risk_summary(self) -> dict[str, int]:
        """各风险等级的特性计数。"""
        summary: dict[str, int] = {"none": 0, "low": 0, "medium": 0, "high": 0, "blocker": 0}
        for f in self.features:
            summary[f.risk.value] += 1
        return summary


# =========================================================================
# Classifier
# =========================================================================


def classify_sql(sql: str) -> ClassificationResult:
    """分析 SQL 语句并返回分类结果。

    Args:
        sql: 要分析的 SQL 语句

    Returns:
        ClassificationResult 包含检测到的类别、特性计数和风险级别
    """
    upper_sql = sql.upper().strip()
    features: list[FeatureDetection] = []
    categories: list[SqlCategory] = []

    # ---- Statement Type ----
    statement_type = _detect_statement_type(upper_sql)

    # ---- Category Detection ----

    # SELECT
    if upper_sql.startswith("SELECT") or upper_sql.startswith("WITH"):
        categories.append(SqlCategory.SELECT)

    # JOIN
    join_features = _detect_joins(upper_sql)
    if join_features:
        categories.append(SqlCategory.JOIN)
        features.append(join_features)

    # GROUP BY
    if re.search(r"\bGROUP\s+BY\b", upper_sql):
        categories.append(SqlCategory.GROUP_BY)
        features.append(FeatureDetection(
            category=SqlCategory.GROUP_BY,
            count=len(re.findall(r"\bGROUP\s+BY\b", upper_sql)),
            risk=RiskLevel.LOW,
        ))

    # AGGREGATION
    agg_features = _detect_aggregation(upper_sql)
    if agg_features:
        categories.append(SqlCategory.AGGREGATION)
        features.append(agg_features)

    # WINDOW FUNCTION
    window_features = _detect_window_functions(upper_sql)
    if window_features:
        categories.append(SqlCategory.WINDOW_FUNCTION)
        features.append(window_features)

    # SUBQUERY
    subquery_features = _detect_subquery(sql, upper_sql)
    if subquery_features:
        categories.append(SqlCategory.SUBQUERY)
        features.append(subquery_features)

    # LIMIT / TOP
    limit_features = _detect_limit_top(upper_sql)
    if limit_features:
        categories.append(SqlCategory.LIMIT_TOP)
        features.append(limit_features)

    # MERGE / UPSERT
    merge_features = _detect_merge(upper_sql)
    if merge_features:
        categories.append(SqlCategory.MERGE_UPSERT)
        features.append(merge_features)

    # DATE FUNCTIONS
    date_features = _detect_date_functions(upper_sql)
    if date_features:
        categories.append(SqlCategory.DATE_FUNCTIONS)
        features.append(date_features)

    # CTE
    if re.search(r"\bWITH\b\s+\w+\s+AS\s*\(", upper_sql):
        categories.append(SqlCategory.CTE)
        features.append(FeatureDetection(
            category=SqlCategory.CTE,
            count=len(re.findall(r"\bWITH\b\s+\w+\s+AS\s*\(", upper_sql)),
            risk=RiskLevel.LOW,
            details=["Common Table Expression detected"],
        ))

    # UNION
    if re.search(r"\bUNION\b", upper_sql):
        categories.append(SqlCategory.UNION)
        features.append(FeatureDetection(
            category=SqlCategory.UNION,
            count=len(re.findall(r"\bUNION\b", upper_sql)),
            risk=RiskLevel.LOW,
        ))

    # ORDER BY
    if re.search(r"\bORDER\s+BY\b", upper_sql):
        categories.append(SqlCategory.ORDER_BY)

    # HAVING
    if re.search(r"\bHAVING\b", upper_sql):
        categories.append(SqlCategory.HAVING)

    # DISTINCT
    if re.search(r"\bSELECT\s+DISTINCT\b", upper_sql):
        categories.append(SqlCategory.DISTINCT)
        features.append(FeatureDetection(
            category=SqlCategory.DISTINCT,
            risk=RiskLevel.LOW,
        ))

    # ---- Complexity ----
    complexity = _assess_complexity(categories, features)

    return ClassificationResult(
        categories=categories,
        features=features,
        statement_type=statement_type,
        complexity=complexity,
        total_features=sum(f.count for f in features),
    )


# =========================================================================
# Detection Helpers
# =========================================================================


def _detect_statement_type(upper_sql: str) -> str:
    """检测 SQL 语句类型。"""
    first_word = upper_sql.split()[0] if upper_sql else ""
    dml = {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "WITH"}
    ddl = {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME"}
    dcl = {"GRANT", "REVOKE"}
    tcl = {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT"}

    if first_word in dml:
        return "DML"
    if first_word in ddl:
        return "DDL"
    if first_word in dcl:
        return "DCL"
    if first_word in tcl:
        return "TCL"
    return "UNKNOWN"


def _detect_joins(upper_sql: str) -> FeatureDetection | None:
    """检测 JOIN 子句。"""
    join_types = {
        "INNER JOIN": "INNER JOIN",
        "LEFT JOIN": "LEFT JOIN",
        "RIGHT JOIN": "RIGHT JOIN",
        "FULL JOIN": "FULL JOIN",
        "FULL OUTER JOIN": "FULL OUTER JOIN",
        "CROSS JOIN": "CROSS JOIN",
        "NATURAL JOIN": "NATURAL JOIN",
        "JOIN": "JOIN",  # implicit INNER
    }

    details: list[str] = []
    total = 0
    risk = RiskLevel.NONE

    for pattern, label in join_types.items():
        count = len(re.findall(r"\b" + pattern + r"\b", upper_sql))
        if count > 0:
            details.append(f"{label} ×{count}")
            total += count
            # FULL/RIGHT joins are less portable
            if "FULL" in pattern or "RIGHT" in pattern:
                risk = RiskLevel.MEDIUM

    if total == 0:
        return None

    return FeatureDetection(
        category=SqlCategory.JOIN,
        count=total,
        details=details,
        risk=risk,
    )


def _detect_aggregation(upper_sql: str) -> FeatureDetection | None:
    """检测聚合函数。"""
    agg_funcs = {
        r"\bSUM\s*\(": "SUM",
        r"\bAVG\s*\(": "AVG",
        r"\bCOUNT\s*\(": "COUNT",
        r"\bMIN\s*\(": "MIN",
        r"\bMAX\s*\(": "MAX",
    }

    details: list[str] = []
    total = 0

    for pattern, label in agg_funcs.items():
        count = len(re.findall(pattern, upper_sql))
        if count > 0:
            details.append(f"{label} ×{count}")
            total += count

    if total == 0:
        return None

    return FeatureDetection(
        category=SqlCategory.AGGREGATION,
        count=total,
        details=details,
        risk=RiskLevel.LOW,
    )


def _detect_window_functions(upper_sql: str) -> FeatureDetection | None:
    """检测窗口函数。"""
    window_funcs = [
        "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE",
        "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
        "SUM", "AVG", "COUNT", "MIN", "MAX",
    ]

    # Only detect if OVER clause is present
    if not re.search(r"\bOVER\s*\(", upper_sql):
        return None

    details: list[str] = []
    total = 0

    for func in window_funcs:
        pattern = r"\b" + func + r"\s*\(.*?\)\s*OVER\s*\("
        count = len(re.findall(pattern, upper_sql, re.DOTALL))
        if count > 0:
            details.append(f"{func}() OVER ×{count}")
            total += count

    if total == 0:
        return None

    return FeatureDetection(
        category=SqlCategory.WINDOW_FUNCTION,
        count=total,
        details=details,
        risk=RiskLevel.HIGH,  # Window functions have varying support
    )


def _detect_subquery(sql: str, upper_sql: str) -> FeatureDetection | None:
    """检测子查询。"""
    # Count nested SELECT statements (excluding the main one)
    nested_selects = len(re.findall(r"\(\s*SELECT\b", upper_sql))

    # Also check for subqueries in FROM (derived tables)
    derived_tables = len(re.findall(r"\bFROM\s*\(\s*SELECT\b", upper_sql))

    # Check for scalar subqueries in SELECT
    scalar_subqueries = len(re.findall(r"SELECT\b.*?\(\s*SELECT\b", upper_sql, re.DOTALL))

    total = nested_selects + derived_tables + scalar_subqueries

    if total == 0:
        return None

    return FeatureDetection(
        category=SqlCategory.SUBQUERY,
        count=total,
        details=[
            f"Nested SELECT: {nested_selects}",
            f"Derived tables: {derived_tables}",
            f"Scalar subqueries: {scalar_subqueries}",
        ],
        risk=RiskLevel.MEDIUM,
    )


def _detect_limit_top(upper_sql: str) -> FeatureDetection | None:
    """检测行数限制语法。"""
    details: list[str] = []
    risk = RiskLevel.NONE

    # MSSQL TOP
    top_match = re.match(r"SELECT\s+TOP\s+(\d+)", upper_sql)
    if top_match:
        details.append(f"TOP {top_match.group(1)}")
        risk = RiskLevel.MEDIUM  # Non-standard

    # TOP PERCENT
    top_pct = re.search(r"SELECT\s+TOP\s+(\d+)\s+PERCENT", upper_sql)
    if top_pct:
        details.append(f"TOP {top_pct.group(1)} PERCENT")
        risk = RiskLevel.HIGH  # Even less portable

    # LIMIT
    limit_match = re.search(r"\bLIMIT\s+(\d+)", upper_sql)
    if limit_match:
        details.append(f"LIMIT {limit_match.group(1)}")

    # OFFSET
    offset_match = re.search(r"\bOFFSET\s+(\d+)", upper_sql)
    if offset_match:
        details.append(f"OFFSET {offset_match.group(1)}")

    # FETCH FIRST
    fetch_match = re.search(r"FETCH\s+(FIRST|NEXT)\s+(\d+)\s+ROWS?", upper_sql)
    if fetch_match:
        details.append(f"FETCH {fetch_match.group(1)} {fetch_match.group(2)}")

    if not details:
        return None

    return FeatureDetection(
        category=SqlCategory.LIMIT_TOP,
        count=1,
        details=details,
        risk=risk,
    )


def _detect_merge(upper_sql: str) -> FeatureDetection | None:
    """检测 MERGE/UPSERT 语法。"""
    details: list[str] = []
    risk = RiskLevel.HIGH

    if re.search(r"\bMERGE\b", upper_sql):
        details.append("MERGE statement")
        risk = RiskLevel.BLOCKER  # Different syntax across DBs

    if re.search(r"\bON\s+CONFLICT\b", upper_sql):
        details.append("ON CONFLICT (PostgreSQL/UPSERT)")
        risk = RiskLevel.MEDIUM

    if re.search(r"\bON\s+DUPLICATE\s+KEY\b", upper_sql):
        details.append("ON DUPLICATE KEY (MySQL)")
        risk = RiskLevel.MEDIUM

    if not details:
        return None

    return FeatureDetection(
        category=SqlCategory.MERGE_UPSERT,
        count=len(details),
        details=details,
        risk=risk,
    )


def _detect_date_functions(upper_sql: str) -> FeatureDetection | None:
    """检测日期函数使用。"""
    date_funcs = {
        r"\bGETDATE\s*\(": ("GETDATE()", RiskLevel.MEDIUM),
        r"\bGETUTCDATE\s*\(": ("GETUTCDATE()", RiskLevel.MEDIUM),
        r"\bDATEADD\s*\(": ("DATEADD()", RiskLevel.MEDIUM),
        r"\bDATEDIFF\s*\(": ("DATEDIFF()", RiskLevel.MEDIUM),
        r"\bDATEPART\s*\(": ("DATEPART()", RiskLevel.MEDIUM),
        r"\bDATENAME\s*\(": ("DATENAME()", RiskLevel.MEDIUM),
        r"\bSYSDATE\b": ("SYSDATE", RiskLevel.LOW),
        r"\bNOW\s*\(": ("NOW()", RiskLevel.LOW),
        r"\bCURRENT_TIMESTAMP\b": ("CURRENT_TIMESTAMP", RiskLevel.NONE),
        r"\bEXTRACT\s*\(": ("EXTRACT()", RiskLevel.NONE),
    }

    details: list[str] = []
    total = 0
    max_risk = RiskLevel.NONE
    risk_order = {RiskLevel.NONE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.BLOCKER: 4}

    for pattern, (label, risk) in date_funcs.items():
        count = len(re.findall(pattern, upper_sql))
        if count > 0:
            details.append(f"{label} ×{count}")
            total += count
            if risk_order[risk] > risk_order[max_risk]:
                max_risk = risk

    if total == 0:
        return None

    return FeatureDetection(
        category=SqlCategory.DATE_FUNCTIONS,
        count=total,
        details=details,
        risk=max_risk,
    )


def _assess_complexity(
    categories: list[SqlCategory],
    features: list[FeatureDetection],
) -> str:
    """评估 SQL 复杂度。"""
    score = 0

    if SqlCategory.SUBQUERY in categories:
        score += 2
    if SqlCategory.WINDOW_FUNCTION in categories:
        score += 3
    if SqlCategory.JOIN in categories:
        score += 1
        # Multiple joins
        join_feat = next((f for f in features if f.category == SqlCategory.JOIN), None)
        if join_feat and join_feat.count > 2:
            score += 2
    if SqlCategory.MERGE_UPSERT in categories:
        score += 3
    if SqlCategory.CTE in categories:
        score += 2
    if SqlCategory.UNION in categories:
        score += 1

    if score <= 1:
        return "simple"
    if score <= 4:
        return "medium"
    return "complex"
