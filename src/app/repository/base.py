"""
Repository[T] — 泛型数据访问基类（双轨制）。

支持两种模式:
    1. ORM mode (session): 使用 SQLAlchemy Session（历史遗留）
    2. Gateway mode (gateway): 使用 DBGateway（新路径）

Phase 过渡策略:
    - 两种模式并存，不强制切换
    - 新方法优先使用 gateway 路径
    - 旧 ORM 方法保留但标记 deprecated
"""

from __future__ import annotations

from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Repository(Generic[T]):
    """泛型 Repository，子类只需声明 model。"""

    model: type[T]
    _table_name: str = ""  # 子类应设置表名

    def __init__(self, session: Session = None, gateway=None):
        self.session = session
        self._gateway = gateway

    @property
    def mode(self) -> str:
        """当前操作模式。"""
        return "gateway" if self._gateway else "orm"

    # ==================================================================
    # ORM mode methods (deprecated: use gateway path)
    # ==================================================================

    def get(self, id: int) -> Optional[T]:
        """按主键获取单条记录。"""
        if self._gateway:
            return self._gateway_get(id)
        return self.session.get(self.model, id)

    def list(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "id",
    ) -> tuple[Sequence[T], int]:
        """分页列表 + 总数。"""
        if self._gateway:
            return self._gateway_list(skip, limit, order_by)
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

    def create(self, data: dict) -> T:
        """创建一条记录。"""
        if self._gateway:
            return self._gateway_create(data)
        entity = self.model(**data)
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def update(self, id: int, data: dict) -> Optional[T]:
        """按主键更新记录。"""
        if self._gateway:
            return self._gateway_update(id, data)
        entity = self.get(id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def delete(self, id: int) -> bool:
        """按主键删除记录。"""
        if self._gateway:
            return self._gateway_delete(id)
        entity = self.get(id)
        if entity is None:
            return False
        self.session.delete(entity)
        self.session.commit()
        return True

    # ==================================================================
    # Gateway mode methods (新路径)
    # ==================================================================

    def _gateway_get(self, id: int) -> Optional[T]:
        """Gateway 模式: 按主键获取。返回 dict 而非 ORM 对象。"""
        from architecture.core.sql.builder import SQLBuilder
        builder = SQLBuilder(self._gateway.db_type)
        sql, params = builder.select(self._table_name, where={"id": id})
        result = self._gateway.query(sql, params)
        if result.rows:
            return dict(zip(result.columns, result.rows[0]))
        return None

    def _gateway_list(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "id",
    ) -> tuple[list[dict], int]:
        """Gateway 模式: 分页列表。"""
        from architecture.core.sql.builder import SQLBuilder
        builder = SQLBuilder(self._gateway.db_type)

        # Count
        count_sql, count_params = builder.count(self._table_name)
        total = self._gateway.scalar(count_sql, count_params) or 0

        # List
        sql, params = builder.select(
            self._table_name,
            order_by=order_by,
            limit=limit,
            offset=skip if skip > 0 else None,
        )
        result = self._gateway.query(sql, params)
        rows = result.to_dicts()
        return rows, total

    def _gateway_create(self, data: dict) -> dict:
        """Gateway 模式: 创建记录。"""
        from architecture.core.sql.builder import SQLBuilder
        builder = SQLBuilder(self._gateway.db_type)
        sql, params = builder.insert(self._table_name, data)
        self._gateway.execute(sql, params)
        # 返回创建的数据（不含自增 ID）
        return data

    def _gateway_update(self, id: int, data: dict) -> Optional[dict]:
        """Gateway 模式: 更新记录。"""
        from architecture.core.sql.builder import SQLBuilder
        builder = SQLBuilder(self._gateway.db_type)
        sql, params = builder.update(self._table_name, data, {"id": id})
        result = self._gateway.execute(sql, params)
        if result.rows_affected == 0:
            return None
        return {"id": id, **data}

    def _gateway_delete(self, id: int) -> bool:
        """Gateway 模式: 删除记录。"""
        from architecture.core.sql.builder import SQLBuilder
        builder = SQLBuilder(self._gateway.db_type)
        sql, params = builder.delete(self._table_name, {"id": id})
        result = self._gateway.execute(sql, params)
        return result.rows_affected > 0
