"""
SQL Diff Explanation Engine — 自动分析双库执行差异的根因。

从对比结果中自动推理差异原因，提供人类可读的中文解释。
覆盖以下差异类别:
    - 小数精度舍入 (FLOAT/DECIMAL)
    - datetime 类型映射差异
    - 排序规则差异
    - NULL 处理差异
    - SQL 重写转换副作用 (LIMIT/TOP, DATEPART, etc.)
    - 列名大小写差异
    - Boolean 表示差异 (1/0 vs true/false)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# Data Classes
# =========================================================================


@dataclass(frozen=True)
class DiffExplanation:
    """单条差异的解释。"""

    field_or_row: str  # 字段名或行号
    reason: str  # 中文原因描述
    possible_causes: list[str] = field(default_factory=list)  # 可能的原因列表
    category: str = "unknown"  # precision | type_mapping | collation | null_handling | rewrite | casing | boolean

    @property
    def severity(self) -> str:
        """差异严重程度：low | medium | high"""
        if self.category in ("type_mapping", "rewrite"):
            return "medium"
        if self.category == "precision":
            return "low"
        if self.category in ("null_handling", "collation"):
            return "high"
        return "medium"


@dataclass(frozen=True)
class Layer1Summary:
    """Layer 1 — 差异摘要视图。"""

    status: str  # "MATCH" | "DIFF" | "ERROR"
    row_count_match: bool = True
    column_type_match: bool = True
    data_match: bool = True
    execution_time_match: bool = True
    total_diffs: int = 0
    summary_text: str = ""

    @property
    def has_any_diff(self) -> bool:
        return not (self.row_count_match and self.column_type_match and self.data_match)


@dataclass(frozen=True)
class Layer2FieldDiff:
    """Layer 2 — 字段/列级别的差异。"""

    field_name: str
    source_value: str
    target_value: str
    match: bool = True
    category: str = ""


@dataclass(frozen=True)
class Layer3RowDiff:
    """Layer 3 — 行级别的差异详情。"""

    row_index: int
    field_name: str
    source_value: Any
    target_value: Any
    explanation: DiffExplanation | None = None


@dataclass(frozen=True)
class ThreeLayerDiff:
    """完整的 3 层差异分析结果。"""

    layer1: Layer1Summary
    layer2: list[Layer2FieldDiff] = field(default_factory=list)
    layer3: list[Layer3RowDiff] = field(default_factory=list)
    explanations: list[DiffExplanation] = field(default_factory=list)


# =========================================================================
# Explanation Engine
# =========================================================================


def generate_three_layer_diff(
    source_result: dict[str, Any],
    target_result: dict[str, Any],
    source_db: str = "mssql",
    target_db: str = "kingbasees",
    original_sql: str = "",
    rewritten_sql: str = "",
) -> ThreeLayerDiff:
    """从双库执行结果生成 3 层差异分析。

    Args:
        source_result: 源库执行结果
        target_result: 目标库执行结果
        source_db: 源库类型
        target_db: 目标库类型
        original_sql: 原始 SQL（用于分析重写影响）
        rewritten_sql: 改写后 SQL

    Returns:
        包含 3 层差异的完整分析结果
    """
    src_rows = source_result.get("rows", []) or []
    tgt_rows = target_result.get("rows", []) or []
    src_cols = source_result.get("columns", []) or []
    tgt_cols = target_result.get("columns", []) or []
    src_count = source_result.get("row_count", 0)
    tgt_count = target_result.get("row_count", 0)
    src_time = source_result.get("execution_time_ms", 0)
    tgt_time = target_result.get("execution_time_ms", 0)

    # ---- Layer 1: Summary ----
    row_count_match = src_count == tgt_count
    column_match = _columns_equal(src_cols, tgt_cols)
    time_match = _times_comparable(src_time, tgt_time)

    layer2_diffs, data_match = _compute_layer2(src_cols, tgt_cols, src_rows, tgt_rows)

    layer3_diffs, explanations = _compute_layer3(
        src_rows, tgt_rows, src_cols, tgt_cols,
        source_db, target_db, original_sql, rewritten_sql,
    )

    total_diffs = len([d for d in layer2_diffs if not d.match]) + len(layer3_diffs)

    status = "MATCH"
    if not row_count_match or not data_match:
        status = "DIFF"
    if not src_count and not tgt_count:
        status = "ERROR" if source_result.get("error") or target_result.get("error") else "DIFF"

    summary_text = _build_summary_text(
        row_count_match, column_match, data_match, time_match,
        total_diffs, source_db, target_db,
    )

    layer1 = Layer1Summary(
        status=status,
        row_count_match=row_count_match,
        column_type_match=column_match,
        data_match=data_match,
        execution_time_match=time_match,
        total_diffs=total_diffs,
        summary_text=summary_text,
    )

    return ThreeLayerDiff(
        layer1=layer1,
        layer2=layer2_diffs,
        layer3=layer3_diffs,
        explanations=list(set(explanations)),  # dedup
    )


# =========================================================================
# Layer 2 — Field-Level Diff
# =========================================================================


def _compute_layer2(
    src_cols: list[str],
    tgt_cols: list[str],
    src_rows: list[list[Any]],
    tgt_rows: list[list[Any]],
) -> tuple[list[Layer2FieldDiff], bool]:
    """计算列/字段级别的差异。"""
    diffs: list[Layer2FieldDiff] = []
    all_cols = list(dict.fromkeys(src_cols + tgt_cols))  # union, order preserved

    data_match = True

    for col in all_cols:
        in_src = col in src_cols
        in_tgt = col in tgt_cols

        if not in_src and not in_tgt:
            continue

        if not in_src:
            diffs.append(Layer2FieldDiff(
                field_name=col,
                source_value="— (missing)",
                target_value=f"present ({_sample_value(tgt_rows, tgt_cols, col)})",
                match=False,
                category="column_missing_in_source",
            ))
            data_match = False
        elif not in_tgt:
            diffs.append(Layer2FieldDiff(
                field_name=col,
                source_value=f"present ({_sample_value(src_rows, src_cols, col)})",
                target_value="— (missing)",
                match=False,
                category="column_missing_in_target",
            ))
            data_match = False
        else:
            # Check if values differ in this column
            col_differs = _column_values_differ(src_rows, tgt_rows, src_cols, tgt_cols, col)
            if col_differs:
                src_sample = _sample_value(src_rows, src_cols, col)
                tgt_sample = _sample_value(tgt_rows, tgt_cols, col)
                diffs.append(Layer2FieldDiff(
                    field_name=col,
                    source_value=src_sample,
                    target_value=tgt_sample,
                    match=False,
                    category="value_mismatch",
                ))
                data_match = False
            else:
                sample = _sample_value(src_rows, src_cols, col)
                diffs.append(Layer2FieldDiff(
                    field_name=col,
                    source_value=sample,
                    target_value=sample,
                    match=True,
                ))

    return diffs, data_match


# =========================================================================
# Layer 3 — Row-Level Diff + Explanations
# =========================================================================


def _compute_layer3(
    src_rows: list[list[Any]],
    tgt_rows: list[list[Any]],
    src_cols: list[str],
    tgt_cols: list[str],
    source_db: str,
    target_db: str,
    original_sql: str,
    rewritten_sql: str,
) -> tuple[list[Layer3RowDiff], list[DiffExplanation]]:
    """计算行级别的差异和自动解释。"""
    diffs: list[Layer3RowDiff] = []
    explanations: list[DiffExplanation] = []

    if not src_rows or not tgt_rows:
        return diffs, explanations

    common_cols = [c for c in src_cols if c in tgt_cols]
    min_rows = min(len(src_rows), len(tgt_rows))

    for row_idx in range(min_rows):
        for col_name in common_cols:
            src_col_idx = src_cols.index(col_name)
            tgt_col_idx = tgt_cols.index(col_name)

            if src_col_idx >= len(src_rows[row_idx]) or tgt_col_idx >= len(tgt_rows[row_idx]):
                continue

            src_val = src_rows[row_idx][src_col_idx]
            tgt_val = tgt_rows[row_idx][tgt_col_idx]

            if not _values_equal(src_val, tgt_val):
                explanation = _explain_value_diff(
                    col_name, src_val, tgt_val,
                    source_db, target_db,
                    original_sql, rewritten_sql,
                )
                if explanation:
                    explanations.append(explanation)

                diffs.append(Layer3RowDiff(
                    row_index=row_idx,
                    field_name=col_name,
                    source_value=src_val,
                    target_value=tgt_val,
                    explanation=explanation,
                ))

    # Cap at 200 rows to avoid overwhelming output
    return diffs[:200], explanations


# =========================================================================
# Value Comparison Helpers
# =========================================================================


def _values_equal(a: Any, b: Any) -> bool:
    """宽松比较两个值是否相等。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    # Boolean normalization
    if isinstance(a, bool) and isinstance(b, (int, float)):
        return a == bool(b)
    if isinstance(b, bool) and isinstance(a, (int, float)):
        return bool(a) == b

    # Numeric comparison with tolerance
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.0001

    # String comparison
    return str(a).strip() == str(b).strip()


def _columns_equal(src_cols: list[str], tgt_cols: list[str]) -> bool:
    """检查列集合是否相等（忽略大小写差异）。"""
    src_set = {c.lower() for c in src_cols}
    tgt_set = {c.lower() for c in tgt_cols}
    return src_set == tgt_set


def _times_comparable(src_ms: float, tgt_ms: float) -> bool:
    """检查执行时间是否可比（相差小于 5 倍）。"""
    if src_ms == 0 or tgt_ms == 0:
        return True
    ratio = max(src_ms, tgt_ms) / min(src_ms, tgt_ms)
    return ratio < 5.0


def _sample_value(rows: list[list[Any]], cols: list[str], col_name: str) -> str:
    """从第一个有效值中抽取样本。"""
    if col_name not in cols:
        return "N/A"
    idx = cols.index(col_name)
    for row in rows:
        if idx < len(row) and row[idx] is not None:
            return str(row[idx])
    return "NULL"


def _column_values_differ(
    src_rows: list[list[Any]],
    tgt_rows: list[list[Any]],
    src_cols: list[str],
    tgt_cols: list[str],
    col_name: str,
) -> bool:
    """检查某列的值是否存在差异。"""
    if col_name not in src_cols or col_name not in tgt_cols:
        return True

    src_idx = src_cols.index(col_name)
    tgt_idx = tgt_cols.index(col_name)
    min_rows = min(len(src_rows), len(tgt_rows))

    for row_idx in range(min_rows):
        if src_idx >= len(src_rows[row_idx]) or tgt_idx >= len(tgt_rows[row_idx]):
            return True
        if not _values_equal(src_rows[row_idx][src_idx], tgt_rows[row_idx][tgt_idx]):
            return True

    return False


# =========================================================================
# Explanation Heuristics
# =========================================================================


def _explain_value_diff(
    col_name: str,
    src_val: Any,
    tgt_val: Any,
    source_db: str,
    target_db: str,
    original_sql: str,
    rewritten_sql: str,
) -> DiffExplanation | None:
    """根据值和上下文自动推理差异原因。"""

    # 1. Decimal precision
    if _is_decimal_diff(src_val, tgt_val):
        return DiffExplanation(
            field_or_row=col_name,
            reason=f"小数精度舍入：{source_db.upper()} {src_val} → {target_db.upper()} {tgt_val}",
            possible_causes=[
                "• Decimal precision rounding (FLOAT/DECIMAL 精度差异)",
                f"• {source_db.upper()} DECIMAL(10,2) vs {target_db.upper()} NUMERIC(10,2) 内部表示差异",
                "• 浮点运算顺序不同导致末尾精度漂移",
            ],
            category="precision",
        )

    # 2. Datetime type mapping
    if _is_datetime_diff(src_val, tgt_val):
        return DiffExplanation(
            field_or_row=col_name,
            reason=f"datetime 类型映射差异：{source_db.upper()} {src_val} → {target_db.upper()} {tgt_val}",
            possible_causes=[
                "• datetime 类型映射差异 (DATETIME2 vs TIMESTAMP vs DATETIME)",
                f"• {source_db.upper()} 支持 100ns 精度，{target_db.upper()} 可能为微秒精度",
                "• 时区处理差异 (WITH TIMEZONE vs WITHOUT TIMEZONE)",
            ],
            category="type_mapping",
        )

    # 3. NULL handling
    if src_val is None or tgt_val is None:
        return DiffExplanation(
            field_or_row=col_name,
            reason=f"NULL 处理差异：{source_db.upper()}={src_val}, {target_db.upper()}={tgt_val}",
            possible_causes=[
                "• NULL 处理语义差异 (ANSI_NULLS 设置)",
                "• COALESCE/ISNULL/NVL 行为差异",
                "• LEFT JOIN 中 NULL 填充逻辑不同",
            ],
            category="null_handling",
        )

    # 4. Boolean representation
    if _is_boolean_diff(src_val, tgt_val):
        return DiffExplanation(
            field_or_row=col_name,
            reason=f"Boolean 表示差异：{source_db.upper()}={src_val}, {target_db.upper()}={tgt_val}",
            possible_causes=[
                f"• {source_db.upper()} 使用 BIT (1/0)，{target_db.upper()} 使用 BOOLEAN (true/false)",
                "• 布尔类型跨库映射不一致",
            ],
            category="type_mapping",
        )

    # 5. String/collation
    if isinstance(src_val, str) and isinstance(tgt_val, str):
        if src_val.strip().lower() == tgt_val.strip().lower():
            return DiffExplanation(
                field_or_row=col_name,
                reason=f"大小写/空白差异：'{src_val}' vs '{tgt_val}'",
                possible_causes=[
                    "• 排序规则 (collation) 差异",
                    "• 字符串尾部空格处理逻辑不同",
                    "• 大小写敏感性设置不同",
                ],
                category="collation",
            )

    # 6. SQL rewrite impact
    if rewritten_sql and original_sql != rewritten_sql:
        if _could_be_rewrite_side_effect(col_name, original_sql, rewritten_sql):
            return DiffExplanation(
                field_or_row=col_name,
                reason=f"SQL 重写可能影响结果：{original_sql[:80]}... → {rewritten_sql[:80]}...",
                possible_causes=[
                    "• SQL rewrite transformation side-effect (LIMIT/TOP ordering)",
                    "• 函数语义变化 (ISNULL→COALESCE, GETDATE→NOW)",
                    "• 分页偏移量语义差异 (OFFSET vs ROW_NUMBER)",
                ],
                category="rewrite",
            )

    # 7. Generic
    return DiffExplanation(
        field_or_row=col_name,
        reason=f"值不一致：{source_db.upper()}={src_val}, {target_db.upper()}={tgt_val}",
        possible_causes=[
            f"• {source_db.upper()} 和 {target_db.upper()} 的类型系统差异",
            "• 聚合函数实现差异",
            "• JOIN 行为差异",
        ],
        category="unknown",
    )


# =========================================================================
# Detection Helpers
# =========================================================================


def _is_decimal_diff(a: Any, b: Any) -> bool:
    """检测是否为小数精度差异（差值极小）。"""
    try:
        fa, fb = float(a), float(b)
        diff = abs(fa - fb)
        return 0 < diff < 0.01
    except (TypeError, ValueError):
        return False


def _is_datetime_diff(a: Any, b: Any) -> bool:
    """检测是否为 datetime 差异。"""
    sa, sb = str(a), str(b)
    # Check for date-like strings
    date_patterns = [
        r"\d{4}-\d{2}-\d{2}",
        r"\d{4}/\d{2}/\d{2}",
    ]
    for pat in date_patterns:
        if re.search(pat, sa) and re.search(pat, sb):
            return True
    # Check for datetime objects
    if hasattr(a, "isoformat") or hasattr(b, "isoformat"):
        return True
    return False


def _is_boolean_diff(a: Any, b: Any) -> bool:
    """检测是否为 Boolean 表示差异。"""
    bool_like = {True, False, 0, 1, "true", "false", "True", "False", "1", "0"}
    return a in bool_like and b in bool_like and type(a) != type(b)


def _could_be_rewrite_side_effect(
    col_name: str,
    original_sql: str,
    rewritten_sql: str,
) -> bool:
    """检查差异是否可能来自 SQL 重写。"""
    # Date/time columns often affected by function rewrites
    date_cols = {"created_at", "updated_at", "order_date", "date", "time", "timestamp"}
    if col_name.lower() in date_cols and "GETDATE" in original_sql.upper():
        return True

    # Amount/price columns affected by aggregation rewrites
    amount_cols = {"total", "amount", "price", "sum", "total_amount", "total_spent"}
    if col_name.lower() in amount_cols:
        if original_sql.upper() != rewritten_sql.upper():
            return True

    return False


# =========================================================================
# Summary Builder
# =========================================================================


def _build_summary_text(
    row_count_match: bool,
    column_match: bool,
    data_match: bool,
    time_match: bool,
    total_diffs: int,
    source_db: str,
    target_db: str,
) -> str:
    """生成人类可读的差异摘要文本。"""
    checks: list[str] = []
    checks.append("✓ Row Count: OK" if row_count_match else "✗ Row Count: mismatch")
    checks.append("✓ Column Type: OK" if column_match else "✗ Column Type: mismatches")
    checks.append("✓ Data Diff: OK" if data_match else f"✗ Data Diff: {total_diffs} differences")
    checks.append("✓ Execution Time: OK" if time_match else "⚠ Execution Time: significant difference")

    return "\n".join(checks)


# =========================================================================
# Direct diff computation (for compare_service integration)
# =========================================================================


def compute_enhanced_diff(
    results: dict[str, dict[str, Any]],
    original_sql: str = "",
    rewritten_sql: str = "",
) -> dict[str, Any]:
    """从多库执行结果计算增强的 3 层差异（用于 API 响应）。

    Args:
        results: {db_type: result_dict}
        original_sql: 原始 SQL
        rewritten_sql: 改写后 SQL

    Returns:
        包含 three_layer_diff 和 explanations 的字典
    """
    db_types = list(results.keys())
    if len(db_types) < 2:
        return {"three_layer_diff": None, "explanations": []}

    source_db = db_types[0]
    target_db = db_types[1]
    source_result = results.get(source_db, {})
    target_result = results.get(target_db, {})

    three_layer = generate_three_layer_diff(
        source_result=source_result,
        target_result=target_result,
        source_db=source_db,
        target_db=target_db,
        original_sql=original_sql,
        rewritten_sql=rewritten_sql,
    )

    return {
        "three_layer_diff": {
            "layer1": {
                "status": three_layer.layer1.status,
                "row_count_match": three_layer.layer1.row_count_match,
                "column_type_match": three_layer.layer1.column_type_match,
                "data_match": three_layer.layer1.data_match,
                "execution_time_match": three_layer.layer1.execution_time_match,
                "total_diffs": three_layer.layer1.total_diffs,
                "summary_text": three_layer.layer1.summary_text,
            },
            "layer2": [
                {
                    "field_name": d.field_name,
                    "source_value": d.source_value,
                    "target_value": d.target_value,
                    "match": d.match,
                    "category": d.category,
                }
                for d in three_layer.layer2
            ],
            "layer3": [
                {
                    "row_index": d.row_index,
                    "field_name": d.field_name,
                    "source_value": d.source_value,
                    "target_value": d.target_value,
                    "explanation": {
                        "field_or_row": d.explanation.field_or_row if d.explanation else "",
                        "reason": d.explanation.reason if d.explanation else "",
                        "possible_causes": d.explanation.possible_causes if d.explanation else [],
                        "category": d.explanation.category if d.explanation else "unknown",
                        "severity": d.explanation.severity if d.explanation else "medium",
                    } if d.explanation else None,
                }
                for d in three_layer.layer3
            ],
            "explanations": [
                {
                    "field_or_row": e.field_or_row,
                    "reason": e.reason,
                    "possible_causes": e.possible_causes,
                    "category": e.category,
                    "severity": e.severity,
                }
                for e in three_layer.explanations
            ],
        },
        "explanations": [
            {
                "field_or_row": e.field_or_row,
                "reason": e.reason,
                "possible_causes": e.possible_causes,
                "category": e.category,
                "severity": e.severity,
            }
            for e in three_layer.explanations
        ],
    }
