"""
architecture_guard.py — 架构 import 规则检查器。

防止架构退化：确保各层之间的依赖方向正确。

规则:
    - app/service/ 不允许直接 import sqlalchemy, psycopg2, pyodbc, dmPython
    - app/api/ 不允许直接 import app/repository 或 architecture/core/db
    - app/repository/ 不允许直接 import psycopg2, pyodbc, dmPython
    - architecture/tooling/ 不允许 import app/service

Usage:
    python src/architecture_guard.py          # 检查并报告
    pytest tests/test_architecture.py         # 作为测试运行
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# =========================================================================
# 规则定义
# =========================================================================

FORBIDDEN_IMPORTS: dict[str, list[str]] = {
    # Service 层不应直接接触 DB driver 或 tooling
    "app/service": [
        "psycopg2", "pyodbc", "dmPython",
        "architecture.tooling",  # Phase 2: service 禁止 import tooling
    ],
    # API 层不应直接访问 Repository 或 DB Gateway
    "app/api": ["app.repository", "app.repository.", "architecture.core.db"],
    # Repository 不应直接接触 driver 或 SQLKernel
    "app/repository": [
        "psycopg2", "pyodbc", "dmPython",
        "architecture.tooling.kernel", "tooling.kernel",  # Phase 2: 禁止调用 SQLKernel
    ],
    # Tooling 不应反向依赖业务层
    "architecture/tooling": ["app.service", "app.repository"],
    # Phase 2: DBGateway 不允许 import app 层
    "architecture/core/db": ["app.service", "app.repository", "app.api"],
    # Phase 2: Dialect 层必须纯 core 层（不 import app/tooling）
    "architecture/core/sql/dialect": ["app.", "architecture.tooling"],
    # Phase 3: Schema 层必须纯 core 层（不依赖 app/tooling/driver）
    "architecture/core/schema": [
        "app.", "architecture.tooling",
        "psycopg2", "pyodbc", "dmPython", "sqlalchemy",
    ],
    # Phase 3: Builder 层可以引用 IR 和 extractor，但不直接引用 app/tooling
    "architecture/core/schema/builder": [
        "app.", "architecture.tooling",
        "psycopg2", "pyodbc", "dmPython",
    ],
    # Phase 3: Diff 层必须纯 schema 层（不依赖 builder/IR/app）
    "architecture/core/schema/diff": [
        "app.", "architecture.tooling",
        "architecture.core.schema.builder",
        "architecture.core.sql",
        "psycopg2", "pyodbc", "dmPython", "sqlalchemy",
    ],
}

# deprecated 标记容忍规则（允许存在但标记为 deprecated）
DEPRECATED_TOLERANCE: dict[str, list[str]] = {
    # Service 层暂时允许 sqlalchemy 和 import app.api.schemas（过渡期）
    "app/service": ["sqlalchemy", "app.api.schemas", "from app.api"],
    # API 层暂时允许 sqlalchemy（Router 还在用 Session）
    "app/api": ["sqlalchemy"],
}


@dataclass
class Violation:
    """单条违规记录。"""

    file_path: str
    line_number: int
    line_content: str
    rule: str
    severity: str  # "error" | "warning"


@dataclass
class CheckResult:
    """检查结果。"""

    violations: list[Violation] = field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _get_python_files(base_dir: Path, subdir: str) -> list[Path]:
    """获取指定子目录下的所有 Python 文件。"""
    target = base_dir / subdir
    if not target.exists():
        return []
    return list(target.rglob("*.py"))


def _check_file(
    file_path: Path,
    rule_prefix: str,
    forbidden: list[str],
    severity: str = "error",
) -> list[Violation]:
    """检查单个文件的 import 是否违反规则。"""
    violations: list[Violation] = []

    # deps.py 是依赖注入工厂，允许访问 core.db
    if file_path.name == "deps.py":
        return violations

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return violations

    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        # 跳过注释行
        if stripped.startswith("#"):
            continue

        # 检查 import 语句
        if stripped.startswith(("import ", "from ")):
            for pattern in forbidden:
                if pattern in stripped:
                    violations.append(Violation(
                        file_path=str(file_path),
                        line_number=line_no,
                        line_content=stripped[:120],
                        rule=f"{rule_prefix}: forbidden '{pattern}'",
                        severity=severity,
                    ))

    return violations


def check_architecture(src_dir: str | Path = "src") -> CheckResult:
    """执行架构规则检查。

    Args:
        src_dir: 源码根目录

    Returns:
        CheckResult 包含所有违规记录
    """
    base = Path(src_dir)
    result = CheckResult()

    # 检查硬性禁止的 import
    for subdir, forbidden in FORBIDDEN_IMPORTS.items():
        files = _get_python_files(base, subdir)
        for file_path in files:
            violations = _check_file(file_path, subdir, forbidden, severity="error")
            result.violations.extend(violations)

    # 检查 deprecated 容忍的 import（标记为 warning）
    for subdir, patterns in DEPRECATED_TOLERANCE.items():
        files = _get_python_files(base, subdir)
        for file_path in files:
            violations = _check_file(file_path, subdir, patterns, severity="warning")
            result.violations.extend(violations)

    return result


def format_report(result: CheckResult) -> str:
    """格式化检查报告。"""
    lines: list[str] = []

    if result.passed and not result.warnings:
        lines.append("✓ Architecture check passed — no violations found.")
        return "\n".join(lines)

    if result.errors:
        lines.append(f"✗ {len(result.errors)} architecture violation(s):")
        for v in result.errors:
            lines.append(f"  ERROR: {v.file_path}:{v.line_number}")
            lines.append(f"    {v.line_content}")
            lines.append(f"    Rule: {v.rule}")

    if result.warnings:
        lines.append(f"⚠ {len(result.warnings)} deprecated usage(s) (tolerated):")
        for v in result.warnings:
            lines.append(f"  WARN: {v.file_path}:{v.line_number}")
            lines.append(f"    {v.line_content}")

    lines.append("")
    lines.append(f"Summary: {len(result.errors)} error(s), {len(result.warnings)} warning(s)")

    return "\n".join(lines)


# =========================================================================
# CLI
# =========================================================================

if __name__ == "__main__":
    src_path = sys.argv[1] if len(sys.argv) > 1 else "src"
    result = check_architecture(src_path)
    print(format_report(result))
    sys.exit(0 if result.passed else 1)
