"""CustomerRepository — 扩展泛型基类，增加按 code 查询。"""
# deprecated: ORM path will be replaced by DBGateway + SQLBuilder

from typing import Optional

from sqlalchemy import select

from architecture.domain.models.customer import Customer
from .base import Repository


class CustomerRepository(Repository[Customer]):
    model = Customer
    _table_name = "customers"

    def find_by_code(self, code: str) -> Optional[Customer]:
        """按业务编码查找客户。"""
        stmt = select(Customer).where(Customer.code == code)
        return self.session.scalar(stmt)
