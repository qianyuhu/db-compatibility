"""
test_executor.py — ExecutionRouter 单元测试。

验证:
    - ExecMode 枚举
    - ExecResult / ShadowResult / VerifyResult 数据结构
    - ExecutionRouter 类初始化
    - 模块级便捷函数可用性
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.service._executor import (
    ExecMode,
    ExecResult,
    ExecutionRouter,
    ShadowResult,
    VerifyResult,
    execute_single,
    execute_shadow,
    execute_verify,
)


# =========================================================================
# 数据结构测试
# =========================================================================


class TestExecMode:
    """执行模式枚举测试。"""

    def test_single_db_value(self):
        assert ExecMode.SINGLE_DB.value == "single_db"

    def test_dual_db_shadow_value(self):
        assert ExecMode.DUAL_DB_SHADOW.value == "dual_db_shadow"

    def test_migration_verify_value(self):
        assert ExecMode.MIGRATION_VERIFY.value == "migration_verify"


class TestExecResult:
    """ExecResult 数据结构测试。"""

    def test_default_values(self):
        r = ExecResult()
        assert r.mode == ExecMode.SINGLE_DB
        assert r.success is True
        assert r.columns == []
        assert r.rows == []

    def test_to_dict(self):
        r = ExecResult(
            db_type="mssql",
            sql_executed="SELECT 1",
            success=True,
            columns=["col1"],
            rows=[[1]],
            row_count=1,
        )
        d = r.to_dict()
        assert d["db_type"] == "mssql"
        assert d["sql_executed"] == "SELECT 1"
        assert d["success"] is True
        assert d["row_count"] == 1
        assert d["mode"] == "single_db"


class TestShadowResult:
    """ShadowResult 数据结构测试。"""

    def test_default_values(self):
        r = ShadowResult()
        assert r.mode == ExecMode.DUAL_DB_SHADOW
        assert r.equal is True
        assert r.diff == []

    def test_to_dict(self):
        r = ShadowResult(
            source_db="mssql",
            target_db="kingbasees",
            source_sql="SELECT 1",
            target_sql="SELECT 1",
            equal=True,
        )
        d = r.to_dict()
        assert d["source_db"] == "mssql"
        assert d["target_db"] == "kingbasees"
        assert d["equal"] is True
        assert d["mode"] == "dual_db_shadow"


class TestVerifyResult:
    """VerifyResult 数据结构测试。"""

    def test_default_values(self):
        r = VerifyResult()
        assert r.mode == ExecMode.MIGRATION_VERIFY
        assert r.structure_match is True
        assert r.data_match is True

    def test_to_dict(self):
        r = VerifyResult(
            source_db="mssql",
            target_db="kingbasees",
            structure_match=False,
            issues=["Column mismatch"],
        )
        d = r.to_dict()
        assert d["structure_match"] is False
        assert d["issues"] == ["Column mismatch"]


# =========================================================================
# ExecutionRouter 类测试
# =========================================================================


class TestExecutionRouter:
    """ExecutionRouter 类测试。"""

    def test_instantiation(self):
        router = ExecutionRouter()
        assert router is not None

    def test_has_execute_single(self):
        router = ExecutionRouter()
        assert hasattr(router, "execute_single")
        assert callable(router.execute_single)

    def test_has_execute_shadow(self):
        router = ExecutionRouter()
        assert hasattr(router, "execute_shadow")
        assert callable(router.execute_shadow)

    def test_has_execute_verify(self):
        router = ExecutionRouter()
        assert hasattr(router, "execute_verify")
        assert callable(router.execute_verify)


# =========================================================================
# 模块级函数测试
# =========================================================================


class TestModuleFunctions:
    """模块级便捷函数可用性测试。"""

    def test_execute_single_callable(self):
        assert callable(execute_single)

    def test_execute_shadow_callable(self):
        assert callable(execute_shadow)

    def test_execute_verify_callable(self):
        assert callable(execute_verify)


# =========================================================================
# _dual_exec 向后兼容测试
# =========================================================================


class TestDualExecCompat:
    """_dual_exec 向后兼容层测试。"""

    def test_import_works(self):
        from app.service._dual_exec import DualExecResult, execute_on_both
        assert callable(execute_on_both)

    def test_dual_exec_result_fields(self):
        from app.service._dual_exec import DualExecResult
        r = DualExecResult(source_db="mssql", target_db="kingbasees")
        assert r.source_db == "mssql"
        assert r.target_db == "kingbasees"
        assert r.equal is True
        assert r.kernel is None
