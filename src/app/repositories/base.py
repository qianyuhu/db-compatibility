"""
Repository[T] — 泛型数据访问基类。

Phase 1 约束:
- 不引入 Unit of Work / TransactionManager
- 不引入 DDD Repository 接口
- 每个操作独立 commit()（最简单、最可测）

MSSQL 注意:
- list() 中的 OFFSET/LIMIT 必须伴随 ORDER BY（MSSQL 硬要求）
"""

from typing import Generic, Optional, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Repository(Generic[T]):
    """泛型 Repository，子类只需声明 model。"""

    model: type[T]

    def __init__(self, session: Session):
        self.session = session

    # ---- Read ----

    def get(self, id: int) -> Optional[T]:
        """按主键获取单条记录。"""
        return self.session.get(self.model, id)

    def list(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "id",
    ) -> tuple[Sequence[T], int]:
        """分页列表 + 总数。

        Returns:
            (rows, total_count)
        """
        total = self.session.scalar(
            select(func.count()).select_from(self.model)
        )
        stmt = (
            select(self.model)
            .order_by(getattr(self.model, order_by))
            .offset(skip)
            .limit(limit)
        )
        rows = self.session.scalars(stmt).all()
        return rows, total

    # ---- Write ----

    def create(self, data: dict) -> T:
        """创建一条记录，commit 后 refresh 以获取自增 ID。"""
        entity = self.model(**data)
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def update(self, id: int, data: dict) -> Optional[T]:
        """按主键更新记录。返回 None 表示记录不存在。"""
        entity = self.get(id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def delete(self, id: int) -> bool:
        """按主键删除记录。返回 False 表示记录不存在。"""
        entity = self.get(id)
        if entity is None:
            return False
        self.session.delete(entity)
        self.session.commit()
        return True
