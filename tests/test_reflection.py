"""
Phase 1 · Reflection (Inspector) 兼容性验证。

验证 SQLAlchemy Inspector 在三库上的行为差异。
重点关注:
- KingbaseES: sys_* 系统表替代 pg_* 是否导致 reflection 失败
- DM8: dmSQLAlchemy 方言 reflection 覆盖程度
"""

import pytest
from sqlalchemy import inspect


class TestReflection:
    """SQLAlchemy Inspector 三库对比。"""

    @pytest.fixture(autouse=True)
    def _ensure_table(self, db_session, product_repo):
        """确保每个测试前 products 表已存在且有数据。"""
        # create_all 在 conftest.py 的 db_session 中已调用
        # 这里插入一条数据确保表不为空
        product_repo.create({"code": "REF001", "name": "Reflection Test", "price": 1})

    def test_get_table_names(self, db_session, db_name):
        """验证 Inspector 能否获取表列表。"""
        inspector = inspect(db_session.bind)

        try:
            tables = inspector.get_table_names()
        except Exception as e:
            pytest.fail(f"[{db_name}] get_table_names() 失败: {type(e).__name__}: {e}")

        assert "products" in tables, (
            f"[{db_name}] products 不在表列表中: {tables}"
        )

    def test_get_columns(self, db_session, db_name):
        """验证列信息反射 — 列名、类型、nullable。"""
        inspector = inspect(db_session.bind)

        try:
            columns = inspector.get_columns("products")
        except Exception as e:
            pytest.fail(f"[{db_name}] get_columns('products') 失败: {type(e).__name__}: {e}")

        col_names = {col["name"] for col in columns}
        expected = {"id", "code", "name", "price", "is_active", "created_at"}

        missing = expected - col_names
        extra = col_names - expected

        assert not missing, f"[{db_name}] 缺少列: {missing}"
        # extra 可能是方言添加的隐藏列，只记录不失败
        if extra:
            print(f"[{db_name}] 额外列: {extra}")

        # 打印每列的反射类型（用于差异对比）
        for col in columns:
            print(
                f"[{db_name}] column={col['name']!r} "
                f"type={col['type']!r} "
                f"nullable={col['nullable']}"
            )

    def test_get_pk_constraint(self, db_session, db_name):
        """验证主键识别。"""
        inspector = inspect(db_session.bind)

        try:
            pk = inspector.get_pk_constraint("products")
        except Exception as e:
            pytest.fail(f"[{db_name}] get_pk_constraint('products') 失败: {type(e).__name__}: {e}")

        assert "id" in pk["constrained_columns"], (
            f"[{db_name}] 主键不包含 'id': {pk}"
        )

    def test_get_indexes(self, db_session, db_name):
        """验证索引信息反射。"""
        inspector = inspect(db_session.bind)

        try:
            indexes = inspector.get_indexes("products")
        except Exception as e:
            pytest.fail(f"[{db_name}] get_indexes('products') 失败: {type(e).__name__}: {e}")

        index_names = {idx["name"] for idx in indexes}
        print(f"[{db_name}] indexes: {index_names}")

        # code 字段有 unique=True，应生成唯一索引
        assert len(indexes) >= 1, f"[{db_name}] 应至少有 1 个索引"

    def test_get_unique_constraints(self, db_session, db_name):
        """验证唯一约束反射。"""
        inspector = inspect(db_session.bind)

        try:
            unique = inspector.get_unique_constraints("products")
        except Exception as e:
            pytest.fail(
                f"[{db_name}] get_unique_constraints('products') 失败: {type(e).__name__}: {e}"
            )

        # code 字段有 unique=True
        print(f"[{db_name}] unique constraints: {unique}")
