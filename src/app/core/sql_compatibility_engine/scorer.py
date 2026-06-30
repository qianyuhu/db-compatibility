"""
Compatibility Scorer — 计算 SQL 跨数据库兼容性评分（0-100）。

评分维度:
    1. 语法兼容性 (30%) — SQL 语法能否直接执行
    2. 函数兼容性 (25%) — 函数调用在目标库的可用性
    3. 特性兼容性 (25%) — 高级特性（窗口函数/CTE/MERGE）的可移植性
    4. 重写覆盖率 (20%) — 自动重写规则能覆盖多少差异

每个特性根据 risk_level 扣分:
    - NONE: 不扣分
    - LOW: -5
    - MEDIUM: -15
    - HIGH: -30
    - BLOCKER: -50

不足 0 分截断为 0。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .classifier import ClassificationResult, FeatureDetection, RiskLevel, SqlCategory


# =========================================================================
# Data Classes
# =========================================================================


@dataclass(frozen=True)
class DimensionScore:
    """单个评分维度的得分。"""

    name: str  # 维度名
    raw_score: float  # 原始得分
    max_score: float  # 该维度满分
    weight: float  # 该维度权重
    deductions: list[str] = field(default_factory=list)  # 扣分原因

    @property
    def weighted(self) -> float:
        """加权后的分数。"""
        if self.max_score == 0:
            return 0
        return (self.raw_score / self.max_score) * self.weight * 100

    @property
    def percentage(self) -> float:
        """百分比得分 (0-100)。"""
        if self.max_score == 0:
            return 100
        return (self.raw_score / self.max_score) * 100


@dataclass(frozen=True)
class CompatibilityScore:
    """SQL 兼容性评分结果。"""

    total_score: float  # 总分 0-100
    dimensions: list[DimensionScore]
    risk_tags: list[str]  # 风险标签: LOW, MEDIUM, HIGH, BLOCKER
    overall_risk: str  # 最高风险等级
    summary: str  # 人类可读的总结
    supported_features: list[str]
    unsupported_features: list[str]
    rewritten_features: list[str]  # 可重写的特性


# =========================================================================
# Scorer
# =========================================================================


def compute_compatibility_score(
    classification: ClassificationResult,
    source_db: str,
    target_db: str,
    rewrite_coverage: int = 0,  # 重写规则覆盖的特性数
) -> CompatibilityScore:
    """计算 SQL 在源库和目标库之间的兼容性评分。

    Args:
        classification: SQL 分类结果
        source_db: 源数据库类型
        target_db: 目标数据库类型
        rewrite_coverage: 自动重写规则可覆盖的特性数

    Returns:
        CompatibilityScore 综合评分
    """
    dimensions: list[DimensionScore] = []

    # ---- 1. Syntax Compatibility (30%) ----
    syntax_score, syntax_deductions = _score_syntax(classification, target_db)
    dimensions.append(DimensionScore(
        name="语法兼容性",
        raw_score=syntax_score,
        max_score=100,
        weight=0.30,
        deductions=syntax_deductions,
    ))

    # ---- 2. Function Compatibility (25%) ----
    func_score, func_deductions = _score_functions(classification, target_db)
    dimensions.append(DimensionScore(
        name="函数兼容性",
        raw_score=func_score,
        max_score=100,
        weight=0.25,
        deductions=func_deductions,
    ))

    # ---- 3. Feature Compatibility (25%) ----
    feat_score, feat_deductions, supported, unsupported = _score_features(
        classification, target_db
    )
    dimensions.append(DimensionScore(
        name="特性兼容性",
        raw_score=feat_score,
        max_score=100,
        weight=0.25,
        deductions=feat_deductions,
    ))

    # ---- 4. Rewrite Coverage (20%) ----
    rewrite_score, rewrite_deductions, rewritten = _score_rewrite_coverage(
        classification, rewrite_coverage
    )
    dimensions.append(DimensionScore(
        name="重写覆盖率",
        raw_score=rewrite_score,
        max_score=100,
        weight=0.20,
        deductions=rewrite_deductions,
    ))

    # ---- Total ----
    total = sum(d.weighted for d in dimensions)
    total = max(0.0, min(100.0, round(total, 1)))

    # ---- Risk Tags ----
    risk_tags = _assemble_risk_tags(classification)

    # ---- Overall Risk ----
    overall_risk = _determine_overall_risk(total, risk_tags, classification)

    # ---- Summary ----
    summary = _build_score_summary(total, dimensions, risk_tags, source_db, target_db)

    return CompatibilityScore(
        total_score=total,
        dimensions=dimensions,
        risk_tags=risk_tags,
        overall_risk=overall_risk,
        summary=summary,
        supported_features=supported,
        unsupported_features=unsupported,
        rewritten_features=rewritten,
    )


# =========================================================================
# Dimension Scoring
# =========================================================================


def _score_syntax(
    classification: ClassificationResult,
    target_db: str,
) -> tuple[float, list[str]]:
    """评分语法兼容性维度。"""
    deductions: list[str] = []
    score = 100.0

    for feature in classification.features:
        if feature.risk == RiskLevel.BLOCKER:
            deductions.append(f"⛔ {feature.category.value}: BLOCKER — 目标库不支持")
            score -= 50
        elif feature.risk == RiskLevel.HIGH:
            if _is_db_specific(feature, target_db):
                deductions.append(f"❌ {feature.category.value}: 目标库 {target_db.upper()} 语法差异大")
                score -= 30
            else:
                deductions.append(f"⚠ {feature.category.value}: 需验证语法兼容性")
                score -= 10
        elif feature.risk == RiskLevel.MEDIUM:
            deductions.append(f"⚠ {feature.category.value}: 部分语法需调整")
            score -= 15

    return max(0, score), deductions


def _score_functions(
    classification: ClassificationResult,
    target_db: str,
) -> tuple[float, list[str]]:
    """评分函数兼容性维度。"""
    deductions: list[str] = []
    score = 100.0

    # Check date functions specifically
    date_feat = next(
        (f for f in classification.features if f.category == SqlCategory.DATE_FUNCTIONS),
        None,
    )
    if date_feat:
        for detail in date_feat.details:
            func_name = detail.split(" ×")[0] if " ×" in detail else detail
            if _needs_rewrite_for_target(func_name, target_db):
                deductions.append(f"⚠ {func_name}: 目标库 {target_db.upper()} 需重写")
                score -= 20
            else:
                deductions.append(f"✓ {func_name}: 兼容")

    return max(0, score), deductions


def _score_features(
    classification: ClassificationResult,
    target_db: str,
) -> tuple[float, list[str], list[str], list[str]]:
    """评分特性兼容性维度。"""
    deductions: list[str] = []
    supported: list[str] = []
    unsupported: list[str] = []
    score = 100.0

    for category in classification.categories:
        feature = next(
            (f for f in classification.features if f.category == category),
            None,
        )
        risk = feature.risk if feature else RiskLevel.NONE

        if risk == RiskLevel.BLOCKER:
            deductions.append(f"⛔ {category.value}: BLOCKER")
            unsupported.append(category.value)
            score -= 50
        elif risk == RiskLevel.HIGH:
            if _is_feature_unsupported(category, target_db):
                deductions.append(f"❌ {category.value}: 目标库 {target_db.upper()} 不支持")
                unsupported.append(category.value)
                score -= 30
            else:
                supported.append(category.value)
        elif risk == RiskLevel.MEDIUM:
            deductions.append(f"⚠ {category.value}: 需验证")
            score -= 15
        else:
            supported.append(category.value)

    return max(0, score), deductions, supported, unsupported


def _score_rewrite_coverage(
    classification: ClassificationResult,
    rewrite_coverage: int,
) -> tuple[float, list[str], list[str]]:
    """评分重写覆盖率维度。"""
    deductions: list[str] = []
    rewritten: list[str] = []
    score = 100.0

    medium_plus_features = [
        f for f in classification.features
        if f.risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.BLOCKER)
    ]
    total_problematic = len(medium_plus_features)

    if total_problematic == 0:
        deductions.append("✓ 无需要重写的特性")
        return score, deductions, rewritten

    coverage_pct = (rewrite_coverage / total_problematic * 100) if total_problematic > 0 else 100

    for feature in medium_plus_features:
        if feature.risk == RiskLevel.BLOCKER:
            deductions.append(f"⛔ {feature.category.value}: BLOCKER — 无法自动重写")
            score -= 40
        elif feature.risk == RiskLevel.HIGH:
            deductions.append(f"⚠ {feature.category.value}: 部分可重写")
            score -= 20
            rewritten.append(feature.category.value)
        else:
            deductions.append(f"✓ {feature.category.value}: 可自动重写")
            rewritten.append(feature.category.value)

    # Adjust based on coverage
    if coverage_pct < 50:
        deductions.append(f"⚠ 重写覆盖率仅 {coverage_pct:.0f}%")
        score -= 15

    return max(0, score), deductions, rewritten


# =========================================================================
# Helpers
# =========================================================================


def _is_db_specific(feature: FeatureDetection, target_db: str) -> bool:
    """判断特性是否为目标数据库特有的语法。"""
    if feature.category == SqlCategory.LIMIT_TOP:
        # TOP is MSSQL-specific, LIMIT is standard
        has_top = any("TOP" in d for d in feature.details)
        if has_top and target_db in ("kingbasees", "dm8"):
            return True
        if not has_top:
            return False  # LIMIT is widely supported

    if feature.category == SqlCategory.MERGE_UPSERT:
        return True  # Different syntax in every DB

    return False


def _needs_rewrite_for_target(func_name: str, target_db: str) -> bool:
    """判断函数在目标库是否需要重写。"""
    mssql_specific = {"GETDATE()", "GETUTCDATE()", "DATEADD()", "DATEDIFF()", "DATEPART()", "DATENAME()", "ISNULL", "LEN", "NEWID()"}
    pg_specific = {"NOW()", "GEN_RANDOM_UUID()"}
    dm_specific = {"SYSDATE", "SYS_GUID()"}

    if target_db == "kingbasees":
        return func_name in mssql_specific
    if target_db == "dm8":
        return func_name in mssql_specific
    if target_db == "mssql":
        return func_name in pg_specific or func_name in dm_specific

    return False


def _is_feature_unsupported(category: SqlCategory, target_db: str) -> bool:
    """判断特性在目标库是否不支持。"""
    if category == SqlCategory.MERGE_UPSERT:
        return target_db in ("kingbasees", "dm8")  # Different syntax
    if category == SqlCategory.WINDOW_FUNCTION:
        # DM8 supports window functions via Oracle compatibility
        return False
    if category == SqlCategory.CTE:
        return False  # Widely supported
    if category == SqlCategory.LIMIT_TOP:
        # Mssql doesn't support LIMIT; pg/dm8 don't support TOP
        return False  # Rewriteable

    return False


def _assemble_risk_tags(classification: ClassificationResult) -> list[str]:
    """根据分类结果组装风险标签。"""
    tags: list[str] = []

    risk_summary = classification.risk_summary
    if risk_summary.get("blocker", 0) > 0:
        tags.append("BLOCKER")
    if risk_summary.get("high", 0) > 0:
        tags.append("HIGH")
    if risk_summary.get("medium", 0) > 0:
        tags.append("MEDIUM")
    if risk_summary.get("low", 0) > 0:
        tags.append("LOW")

    return tags or ["NONE"]


def _determine_overall_risk(
    total_score: float,
    risk_tags: list[str],
    classification: ClassificationResult,
) -> str:
    """确定总体风险等级。"""
    if "BLOCKER" in risk_tags or total_score < 50:
        return "BLOCKER"
    if "HIGH" in risk_tags or total_score < 70:
        return "HIGH"
    if "MEDIUM" in risk_tags or total_score < 85:
        return "MEDIUM"
    if "LOW" in risk_tags or total_score < 95:
        return "LOW"
    return "NONE"


def _build_score_summary(
    total: float,
    dimensions: list[DimensionScore],
    risk_tags: list[str],
    source_db: str,
    target_db: str,
) -> str:
    """生成评分总结文本。"""
    lines: list[str] = []
    lines.append(f"兼容性评分: {total:.0f} / 100")
    lines.append(f"源库: {source_db.upper()} → 目标库: {target_db.upper()}")

    for d in dimensions:
        icon = "✓" if d.percentage >= 80 else "⚠" if d.percentage >= 50 else "✗"
        lines.append(f"  {icon} {d.name}: {d.percentage:.0f}%")

    if risk_tags and risk_tags != ["NONE"]:
        lines.append(f"风险标签: {', '.join(risk_tags)}")

    return "\n".join(lines)
