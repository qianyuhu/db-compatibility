"""
core.schema.builder — Schema Graph 构建器（三源统一转换）。

从不同数据源自动构建 SchemaGraph:
    - TableBuilder: SQLAlchemy Inspector / MetaData → Table 子图
    - SPBuilder:    SPCompiler IRProcedure → SP 子图
"""

from .sp_builder import SPBuilder
from .table_builder import TableBuilder

__all__ = ["TableBuilder", "SPBuilder"]
