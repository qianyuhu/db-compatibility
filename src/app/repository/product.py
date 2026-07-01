"""ProductRepository — 扩展泛型基类，增加按 code 查询。"""

from typing import Optional

from sqlalchemy import select

from architecture.domain.models.product import Product
from .base import Repository


class ProductRepository(Repository[Product]):
    model = Product
    _table_name = "products"

    def find_by_code(self, code: str) -> Optional[Product]:
        """按业务编码查找产品。"""
        stmt = select(Product).where(Product.code == code)
        return self.session.scalar(stmt)
