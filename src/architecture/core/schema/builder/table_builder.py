"""
TableBuilder — 从 SQLAlchemy Inspector / MetaData 自动构建 SchemaGraph。

两种入口:
    1. from_inspector(inspector) — 从真实数据库提取（生产环境）
    2. from_metadata(metadata)   — 从 ORM 模型定义提取（开发/测试）

提取内容:
    - TableNode + ColumnNode（列类型、nullable、default、identity）
    - ConstraintNode（PK / FK / UNIQUE / CHECK）
    - IndexNode（索引列、unique、clustered）
    - REFERENCES 边（FK 关系自动建立表间依赖）

Design:
    - 纯静态方法，无状态
    - 不 import sqlalchemy 在模块顶层（architecture_guard 规则）
    - 节点 id 格式: "{schema}.{table}" 或 "{schema}.{table}.{column}"
    - 默认 schema 从 Inspector 获取（MSSQL="dbo", PG="public"）

Usage:
    from architecture.core.schema.builder.table_builder import TableBuilder

    # inspector = inspect(engine)  # SQLAlchemy Inspector
    # graph = TableBuilder.from_inspector(inspector)

    # 或从 ORM MetaData
    from architecture.domain.models import Base
    graph = TableBuilder.from_metadata(Base.metadata)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from architecture.core.schema.edges import SchemaEdge, SchemaEdgeType
from architecture.core.schema.graph import SchemaGraph
from architecture.core.schema.nodes import (
    ColumnNode,
    ConstraintNode,
    ConstraintType,
    IndexNode,
    IndexType,
    TableNode,
)

logger = logging.getLogger(__name__)


class TableBuilder:
    """从 SQLAlchemy 元数据构建 Table 子图。"""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def from_inspector(
        inspector: Any,
        schema: str | None = None,
        table_names: list[str] | None = None,
    ) -> SchemaGraph:
        """从 SQLAlchemy Inspector（真实数据库连接）构建 SchemaGraph。

        Args:
            inspector: sqlalchemy.engine.reflection.Inspector 实例。
            schema: 目标 schema（None 使用默认 schema）。
            table_names: 限定表名列表（None 提取全部表）。

        Returns:
            包含 Table/Column/Constraint/Index 节点和 FK 边的 SchemaGraph。
        """
        graph = SchemaGraph()
        effective_schema = schema or inspector.default_schema_name or "dbo"

        if table_names is None:
            table_names = inspector.get_table_names(schema=effective_schema)

        # Phase 1: 创建所有 TableNode + ColumnNode
        for tbl_name in sorted(table_names):
            _build_table_from_inspector(graph, inspector, tbl_name, effective_schema)

        # Phase 2: 建立 FK 边（需要所有表节点已存在）
        for tbl_name in sorted(table_names):
            _build_fk_edges_from_inspector(graph, inspector, tbl_name, effective_schema)

        logger.info(
            "TableBuilder.from_inspector: %d nodes, %d edges (schema=%s)",
            graph.node_count, graph.edge_count, effective_schema,
        )
        return graph

    @staticmethod
    def from_metadata(
        metadata: Any,
        schema: str | None = None,
    ) -> SchemaGraph:
        """从 SQLAlchemy MetaData（ORM 模型定义）构建 SchemaGraph。

        Args:
            metadata: sqlalchemy.MetaData 实例。
            schema: 目标 schema（None 使用 "dbo"）。

        Returns:
            包含 Table/Column/Constraint/Index 节点和 FK 边的 SchemaGraph。
        """
        graph = SchemaGraph()
        effective_schema = schema or "dbo"

        # Phase 1: 创建所有 TableNode + ColumnNode
        for tbl_name in sorted(metadata.tables.keys()):
            table = metadata.tables[tbl_name]
            _build_table_from_sa_table(graph, table, effective_schema)

        # Phase 2: 建立 FK 边
        for tbl_name in sorted(metadata.tables.keys()):
            table = metadata.tables[tbl_name]
            _build_fk_edges_from_sa_table(graph, table, effective_schema)

        logger.info(
            "TableBuilder.from_metadata: %d nodes, %d edges (schema=%s)",
            graph.node_count, graph.edge_count, effective_schema,
        )
        return graph


# =========================================================================
# Internal helpers — Inspector mode
# =========================================================================


def _build_table_from_inspector(
    graph: SchemaGraph,
    inspector: Any,
    table_name: str,
    schema: str,
) -> None:
    """从 Inspector 提取单张表的所有节点。"""
    table_id = f"{schema}.{table_name}"

    # Columns
    columns_info = inspector.get_columns(table_name, schema=schema)
    col_names: list[str] = []
    for i, col in enumerate(columns_info, start=1):
        col_name = col["name"]
        col_names.append(col_name)
        col_id = f"{table_id}.{col_name}"

        data_type = str(col.get("type", ""))
        nullable = col.get("nullable", True)
        default_val = col.get("default")
        if default_val is not None:
            default_val = str(default_val)

        # Identity detection
        is_identity = False
        identity = col.get("identity")
        if identity:
            is_identity = True

        graph.add_node(ColumnNode(
            id=col_id,
            name=col_name,
            schema=schema,
            data_type=data_type,
            nullable=nullable,
            default_value=default_val,
            is_identity=is_identity,
            ordinal_position=i,
            parent_table=table_id,
        ))

    # Primary Key
    pk_info = inspector.get_pk_constraint(table_name, schema=schema)
    pk_cols = tuple(pk_info.get("constrained_columns", []))
    pk_name = pk_info.get("name", f"pk_{table_name}")
    primary_key = pk_cols[0] if pk_cols else None

    if pk_cols:
        graph.add_node(ConstraintNode(
            id=f"{table_id}.{pk_name or 'pk'}",
            name=pk_name or f"pk_{table_name}",
            schema=schema,
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=pk_cols,
            parent_table=table_id,
        ))

    # Foreign Keys
    fk_list = inspector.get_foreign_keys(table_name, schema=schema)
    for fk in fk_list:
        fk_name = fk.get("name", f"fk_{table_name}_{fk.get('constrained_columns', ['?'])[0]}")
        fk_cols = tuple(fk.get("constrained_columns", []))
        ref_table = fk.get("referred_table", "")
        ref_schema = fk.get("referred_schema", schema) or schema
        ref_cols = tuple(fk.get("referred_columns", []))

        graph.add_node(ConstraintNode(
            id=f"{table_id}.{fk_name or 'fk'}",
            name=fk_name or f"fk_{table_name}",
            schema=schema,
            constraint_type=ConstraintType.FOREIGN_KEY,
            columns=fk_cols,
            referenced_table=f"{ref_schema}.{ref_table}",
            referenced_columns=ref_cols,
            parent_table=table_id,
        ))

    # Unique constraints
    unique_list = inspector.get_unique_constraints(table_name, schema=schema)
    for uq in unique_list:
        uq_name = uq.get("name", f"uq_{table_name}")
        uq_cols = tuple(uq.get("column_names", []))
        if uq_cols:
            graph.add_node(ConstraintNode(
                id=f"{table_id}.{uq_name or 'uq'}",
                name=uq_name or f"uq_{table_name}",
                schema=schema,
                constraint_type=ConstraintType.UNIQUE,
                columns=uq_cols,
                parent_table=table_id,
            ))

    # Indexes
    idx_list = inspector.get_indexes(table_name, schema=schema)
    for idx in idx_list:
        idx_name = idx.get("name", f"idx_{table_name}")
        idx_cols = tuple(idx.get("column_names", []))
        is_unique = idx.get("unique", False)

        # Clustered detection (dialect-specific, MSSQL has 'dialect_options')
        is_clustered = False
        dialect_opts = idx.get("dialect_options", {})
        if isinstance(dialect_opts, dict):
            mssql_opts = dialect_opts.get("mssql", {})
            if isinstance(mssql_opts, dict):
                is_clustered = mssql_opts.get("clustered", False)

        graph.add_node(IndexNode(
            id=f"{table_id}.{idx_name or 'idx'}",
            name=idx_name or f"idx_{table_name}",
            schema=schema,
            index_type=IndexType.CLUSTERED if is_clustered else IndexType.BTREE,
            columns=idx_cols,
            is_unique=is_unique,
            is_clustered=is_clustered,
            parent_table=table_id,
        ))

    # TableNode
    graph.add_node(TableNode(
        id=table_id,
        name=table_name,
        schema=schema,
        columns=tuple(col_names),
        primary_key=primary_key,
    ))


def _build_fk_edges_from_inspector(
    graph: SchemaGraph,
    inspector: Any,
    table_name: str,
    schema: str,
) -> None:
    """从 Inspector 提取 FK 边（REFERENCES）。"""
    table_id = f"{schema}.{table_name}"
    fk_list = inspector.get_foreign_keys(table_name, schema=schema)

    for fk in fk_list:
        ref_table = fk.get("referred_table", "")
        ref_schema = fk.get("referred_schema", schema) or schema
        ref_id = f"{ref_schema}.{ref_table}"

        # 只有当引用的表也在图中时才建边
        if graph.has_node(ref_id):
            constrained = fk.get("constrained_columns", [])
            referred = fk.get("referred_columns", [])
            mapping = ""
            if constrained and referred:
                mapping = f"{table_name}.{constrained[0]} -> {ref_table}.{referred[0]}"

            graph.add_edge(SchemaEdge(
                source_id=table_id,
                target_id=ref_id,
                edge_type=SchemaEdgeType.REFERENCES,
                metadata={"mapping": mapping} if mapping else {},
            ))


# =========================================================================
# Internal helpers — MetaData mode
# =========================================================================


def _build_table_from_sa_table(
    graph: SchemaGraph,
    table: Any,
    schema: str,
) -> None:
    """从 SQLAlchemy Table 对象提取节点。"""
    table_name = table.name
    table_id = f"{schema}.{table_name}"
    col_names: list[str] = []

    for i, col in enumerate(table.columns, start=1):
        col_name = col.name
        col_names.append(col_name)
        col_id = f"{table_id}.{col_name}"

        data_type = str(col.type)
        nullable = col.nullable if col.nullable is not None else True
        default_val = None
        if col.default is not None:
            default_val = str(col.default.arg) if hasattr(col.default, "arg") else str(col.default)
        if col.server_default is not None:
            default_val = str(col.server_default.arg) if hasattr(col.server_default, "arg") else str(col.server_default)

        is_identity = bool(col.autoincrement) if hasattr(col, "autoincrement") else False

        graph.add_node(ColumnNode(
            id=col_id,
            name=col_name,
            schema=schema,
            data_type=data_type,
            nullable=nullable,
            default_value=default_val,
            is_identity=is_identity,
            ordinal_position=i,
            parent_table=table_id,
        ))

    # Primary Key
    pk_cols = tuple(col.name for col in table.primary_key.columns)
    primary_key = pk_cols[0] if pk_cols else None
    if pk_cols:
        graph.add_node(ConstraintNode(
            id=f"{table_id}.pk",
            name=f"pk_{table_name}",
            schema=schema,
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=pk_cols,
            parent_table=table_id,
        ))

    # Unique constraints (from columns with unique=True)
    for col in table.columns:
        if col.unique:
            graph.add_node(ConstraintNode(
                id=f"{table_id}.uq_{col.name}",
                name=f"uq_{table_name}_{col.name}",
                schema=schema,
                constraint_type=ConstraintType.UNIQUE,
                columns=(col.name,),
                parent_table=table_id,
            ))

    # Indexes (from columns with index=True)
    for col in table.columns:
        if col.index:
            graph.add_node(IndexNode(
                id=f"{table_id}.idx_{col.name}",
                name=f"ix_{table_name}_{col.name}",
                schema=schema,
                columns=(col.name,),
                is_unique=bool(col.unique),
                parent_table=table_id,
            ))

    # FK constraints (from ForeignKey objects)
    for col in table.columns:
        for fk in col.foreign_keys:
            ref_full = fk.target_fullname if hasattr(fk, "target_fullname") else str(fk.column)
            # Parse "tablename.columnname"
            parts = ref_full.rsplit(".", 1)
            ref_table = parts[0] if len(parts) == 2 else ""
            ref_col = parts[1] if len(parts) == 2 else ref_full

            fk_name = fk.name if hasattr(fk, "name") and fk.name else f"fk_{table_name}_{col.name}"
            ref_id = f"{schema}.{ref_table}"

            graph.add_node(ConstraintNode(
                id=f"{table_id}.{fk_name}",
                name=fk_name,
                schema=schema,
                constraint_type=ConstraintType.FOREIGN_KEY,
                columns=(col.name,),
                referenced_table=ref_id,
                referenced_columns=(ref_col,),
                parent_table=table_id,
            ))

    # TableNode
    graph.add_node(TableNode(
        id=table_id,
        name=table_name,
        schema=schema,
        columns=tuple(col_names),
        primary_key=primary_key,
    ))


def _build_fk_edges_from_sa_table(
    graph: SchemaGraph,
    table: Any,
    schema: str,
) -> None:
    """从 SQLAlchemy Table 对象提取 FK 边。"""
    table_name = table.name
    table_id = f"{schema}.{table_name}"

    for col in table.columns:
        for fk in col.foreign_keys:
            ref_full = fk.target_fullname if hasattr(fk, "target_fullname") else str(fk.column)
            parts = ref_full.rsplit(".", 1)
            ref_table = parts[0] if len(parts) == 2 else ""
            ref_col = parts[1] if len(parts) == 2 else ref_full
            ref_id = f"{schema}.{ref_table}"

            if graph.has_node(ref_id):
                graph.add_edge(SchemaEdge(
                    source_id=table_id,
                    target_id=ref_id,
                    edge_type=SchemaEdgeType.REFERENCES,
                    metadata={
                        "mapping": f"{table_name}.{col.name} -> {ref_table}.{ref_col}",
                    },
                ))
