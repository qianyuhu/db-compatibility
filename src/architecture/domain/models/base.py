"""
声明式基类。

Phase 1 约束:
- 使用 SQLAlchemy 原生 DeclarativeBase
- 不做 mixin / 软删除 / 时间戳基类
- 不引入任何自定义 MetaData 配置
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
