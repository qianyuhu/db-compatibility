"""
test_architecture.py — 架构护栏测试。

验证各层之间的 import 依赖方向正确，防止架构退化。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 src/ 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architecture_guard import check_architecture, CheckResult


@pytest.fixture
def arch_result() -> CheckResult:
    """执行架构检查。"""
    src_dir = Path(__file__).parent.parent / "src"
    return check_architecture(src_dir)


class TestArchitectureRules:
    """架构规则测试。"""

    def test_no_hard_violations(self, arch_result: CheckResult):
        """不允许有硬性违规（error 级别）。"""
        if arch_result.errors:
            msg_lines = [f"Found {len(arch_result.errors)} architecture violation(s):"]
            for v in arch_result.errors:
                msg_lines.append(f"  {v.file_path}:{v.line_number}: {v.line_content}")
                msg_lines.append(f"    Rule: {v.rule}")
            pytest.fail("\n".join(msg_lines))

    def test_tooling_isolation(self, arch_result: CheckResult):
        """Tooling 层不得反向依赖业务层。"""
        tooling_violations = [
            v for v in arch_result.violations
            if "architecture/tooling" in v.rule
        ]
        assert len(tooling_violations) == 0, (
            f"Tooling layer has {len(tooling_violations)} violation(s) — "
            "tooling must not depend on app/service or app/repository"
        )

    def test_no_driver_in_service(self, arch_result: CheckResult):
        """Service 层不得直接 import DB driver。"""
        driver_violations = [
            v for v in arch_result.errors
            if "app/service" in v.rule and any(
                d in v.line_content for d in ["psycopg2", "pyodbc", "dmPython"]
            )
        ]
        assert len(driver_violations) == 0, (
            f"Service layer directly imports DB driver(s): "
            f"{[v.line_content for v in driver_violations]}"
        )

    def test_no_driver_in_repository(self, arch_result: CheckResult):
        """Repository 层不得直接 import DB driver。"""
        driver_violations = [
            v for v in arch_result.errors
            if "app/repository" in v.rule and any(
                d in v.line_content for d in ["psycopg2", "pyodbc", "dmPython"]
            )
        ]
        assert len(driver_violations) == 0, (
            f"Repository layer directly imports DB driver(s): "
            f"{[v.line_content for v in driver_violations]}"
        )

    def test_deprecated_usages_reported(self, arch_result: CheckResult):
        """deprecated 用法应被报告为 warning（不阻断）。"""
        # 仅打印警告数量，不失败
        if arch_result.warnings:
            print(f"\n[INFO] {len(arch_result.warnings)} deprecated usage(s) found (tolerated):")
            for v in arch_result.warnings[:5]:  # 只显示前 5 个
                print(f"  {v.file_path}:{v.line_number}: {v.line_content}")
