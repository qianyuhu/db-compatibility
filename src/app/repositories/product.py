"""ProductRepository — 不添加任何自定义方法前，仅继承泛型基类。"""

from app.models.product import Product
from .base import Repository


class ProductRepository(Repository[Product]):
    model = Product
