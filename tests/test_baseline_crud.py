"""
Phase 1 · 基准 CRUD 测试。

MSSQL 上全部通过后，再对 KingbaseES / DM8 运行。
验证: SQLAlchemy ORM 的 Create / Read / Update / Delete 在三库上的行为一致性。

所有失败均记录，不做任何兼容性修复。
"""

import pytest


class TestCreate:
    """Product 创建测试。"""

    def test_create_basic(self, product_repo, db_name):
        """创建一个合法的 Product 记录。"""
        data = {
            "code": "P001",
            "name": "测试产品",
            "price": 99.99,
            "is_active": True,
        }
        product = product_repo.create(data)

        assert product.id is not None, f"[{db_name}] 自增 ID 未生成"
        assert product.code == "P001", f"[{db_name}] code 不匹配"
        assert product.name == "测试产品", f"[{db_name}] name 不匹配"
        assert float(product.price) == 99.99, f"[{db_name}] price 不匹配"
        assert product.is_active is True, f"[{db_name}] is_active 不匹配"

    def test_create_unicode(self, product_repo, db_name):
        """创建包含中文的记录 — 验证 Unicode 处理。"""
        data = {
            "code": "中文产品",
            "name": "日本語テスト",
            "price": 50.00,
        }
        product = product_repo.create(data)

        assert product.code == "中文产品", f"[{db_name}] Unicode code 不匹配"
        assert product.name == "日本語テスト", f"[{db_name}] Unicode name 不匹配"

    def test_create_duplicate_code(self, product_repo, db_name):
        """创建重复 code 应抛出 IntegrityError。"""
        product_repo.create({"code": "DUP001", "name": "First", "price": 10})

        with pytest.raises(Exception) as exc_info:
            product_repo.create({"code": "DUP001", "name": "Second", "price": 20})

        # 记录异常类型（三库可能不同）
        print(f"[{db_name}] duplicate code error: {type(exc_info.value).__name__}: {exc_info.value}")


class TestRead:
    """Product 读取测试。"""

    def test_get_existing(self, product_repo, db_name):
        """按 ID 读取已存在的记录。"""
        created = product_repo.create({"code": "R001", "name": "Read Test", "price": 30})
        fetched = product_repo.get(created.id)

        assert fetched is not None, f"[{db_name}] 按 ID 读取返回 None"
        assert fetched.id == created.id
        assert fetched.code == "R001"

    def test_get_non_existing(self, product_repo, db_name):
        """读取不存在的 ID 返回 None。"""
        result = product_repo.get(99999)
        assert result is None, f"[{db_name}] 不存在的 ID 应返回 None"

    def test_list_pagination(self, product_repo, db_name):
        """分页列表 — 验证 LIMIT / OFFSET 行为。"""
        # 创建 5 条记录
        for i in range(5):
            product_repo.create({
                "code": f"LIST{i:03d}",
                "name": f"Product {i}",
                "price": 10.0 + i,
            })

        # 第一页（2条）
        page1, total = product_repo.list(skip=0, limit=2, order_by="id")
        assert total == 5, f"[{db_name}] total 应为 5，实为 {total}"
        assert len(page1) == 2, f"[{db_name}] page1 长度应为 2，实为 {len(page1)}"

        # 第二页（2条）
        page2, _ = product_repo.list(skip=2, limit=2, order_by="id")
        assert len(page2) == 2, f"[{db_name}] page2 长度应为 2"

        # 第三页（1条，最后一页）
        page3, _ = product_repo.list(skip=4, limit=2, order_by="id")
        assert len(page3) == 1, f"[{db_name}] page3 长度应为 1"

        # 分页结果不重叠
        ids_page1 = {p.id for p in page1}
        ids_page2 = {p.id for p in page2}
        ids_page3 = {p.id for p in page3}
        assert ids_page1.isdisjoint(ids_page2), f"[{db_name}] page1 和 page2 重叠"
        assert ids_page1.isdisjoint(ids_page3), f"[{db_name}] page1 和 page3 重叠"


class TestUpdate:
    """Product 更新测试。"""

    def test_update_existing(self, product_repo, db_name):
        """更新已存在记录。"""
        created = product_repo.create({"code": "U001", "name": "Before", "price": 10})
        updated = product_repo.update(created.id, {"name": "After", "price": 20})

        assert updated is not None, f"[{db_name}] update 返回 None"
        assert updated.name == "After", f"[{db_name}] name 未更新: {updated.name}"
        assert float(updated.price) == 20.0, f"[{db_name}] price 未更新: {updated.price}"
        assert updated.code == "U001", f"[{db_name}] code 被意外修改: {updated.code}"

    def test_update_non_existing(self, product_repo, db_name):
        """更新不存在的记录返回 None。"""
        result = product_repo.update(99999, {"name": "Ghost"})
        assert result is None, f"[{db_name}] 不存在的记录 update 应返回 None"

    def test_update_partial(self, product_repo, db_name):
        """部分更新 — 只传需要修改的字段。"""
        created = product_repo.create({"code": "U002", "name": "Full", "price": 100})
        updated = product_repo.update(created.id, {"price": 150})

        assert updated.name == "Full", f"[{db_name}] 未传字段被意外修改"
        assert float(updated.price) == 150.0


class TestDelete:
    """Product 删除测试。"""

    def test_delete_existing(self, product_repo, db_name):
        """删除已存在记录。"""
        created = product_repo.create({"code": "D001", "name": "ToDelete", "price": 1})
        result = product_repo.delete(created.id)

        assert result is True, f"[{db_name}] delete 应返回 True"
        assert product_repo.get(created.id) is None, f"[{db_name}] 删除后仍可读取"

    def test_delete_non_existing(self, product_repo, db_name):
        """删除不存在的记录返回 False。"""
        result = product_repo.delete(99999)
        assert result is False, f"[{db_name}] 不存在的记录 delete 应返回 False"
