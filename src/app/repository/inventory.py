"""InventoryRepository — 扩展泛型基类，增加按产品查询和库存调整。"""

from typing import Optional

from sqlalchemy import select

from architecture.domain.models.inventory import Inventory
from .base import Repository


class InventoryRepository(Repository[Inventory]):
    model = Inventory
    _table_name = "inventory"

    def find_by_product(self, product_id: int) -> Optional[Inventory]:
        """按产品 ID 查找库存记录。"""
        stmt = select(Inventory).where(Inventory.product_id == product_id)
        return self.session.scalar(stmt)

    def adjust_quantity(self, product_id: int, delta: int) -> Optional[Inventory]:
        """调整库存数量。正数为入库，负数为出库。返回 None 表示产品不存在。

        使用 update() 方法遵循不可变更新模式。
        """
        inv = self.find_by_product(product_id)
        if inv is None:
            return None
        return self.update(inv.id, {"quantity": inv.quantity + delta})

    def ensure_inventory(self, product_id: int, warehouse: str = "MAIN") -> Inventory:
        """确保产品有库存记录，没有则创建。"""
        inv = self.find_by_product(product_id)
        if inv is None:
            inv = self.create({
                "product_id": product_id,
                "warehouse": warehouse,
                "quantity": 0,
                "min_quantity": 10,
            })
        return inv
