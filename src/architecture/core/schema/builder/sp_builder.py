"""
SPBuilder — 从 SPCompiler IRProcedure 自动构建 SchemaGraph 中的 SP 子图。

提取内容:
    - ProcedureNode（参数、语言、引用的表和调用的 SP）
    - CALLS 边（SP 之间的调用关系）
    - DEPENDS_ON 边（SP 对表的依赖关系）

工作原理:
    1. 遍历 IRProcedure.body 中的所有 IR 节点
    2. 收集 IRExec → called_procedures
    3. 收集 IRSQL → 用 extractor 提取表引用
    4. 将 IRProcedure 参数转换为 ProcedureNode.parameters
    5. 递归遍历嵌套结构（IRIf/IRWhile/IRBlock）

Design:
    - 依赖 architecture.core.sql.compiler.ir（IRProcedure, IRExec, IRSQL 等）
    - 依赖 architecture.core.sql.diagnostics.extractor（表名提取）
    - 不直接 import sqlalchemy（architecture_guard 规则）

Usage:
    from architecture.core.schema.builder.sp_builder import SPBuilder
    from architecture.core.sql.compiler import compile_sp

    result = compile_sp(tsql_text, "mssql", "kingbasees")
    graph = SPBuilder.from_ir(result.ir, schema="dbo")
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from architecture.core.schema.edges import SchemaEdge, SchemaEdgeType
from architecture.core.schema.graph import SchemaGraph
from architecture.core.schema.nodes import ProcedureNode

logger = logging.getLogger(__name__)


class SPBuilder:
    """从 SPCompiler IR 构建 SP 子图。"""

    @staticmethod
    def from_ir(
        ir: Any,
        schema: str = "dbo",
        known_tables: set[str] | None = None,
    ) -> SchemaGraph:
        """从单个 IRProcedure 构建 SchemaGraph。

        Args:
            ir: IRProcedure 实例。
            schema: 默认 schema 前缀。
            known_tables: 已知表名集合（用于过滤提取到的表引用）。
                         None 表示接受所有提取到的表。

        Returns:
            包含 ProcedureNode + CALLS/DEPENDS_ON 边的 SchemaGraph。
        """
        graph = SchemaGraph()
        _build_sp_from_ir(graph, ir, schema, known_tables)
        return graph

    @staticmethod
    def from_ir_list(
        ir_list: list[Any],
        schema: str = "dbo",
        known_tables: set[str] | None = None,
    ) -> SchemaGraph:
        """从多个 IRProcedure 构建完整的 SP 子图。

        多个 SP 之间的 CALLS 关系会被自动建立。

        Args:
            ir_list: IRProcedure 列表。
            schema: 默认 schema 前缀。
            known_tables: 已知表名集合。

        Returns:
            包含所有 SP 节点和 CALLS/DEPENDS_ON 边的 SchemaGraph。
        """
        graph = SchemaGraph()

        # Phase 1: 创建所有 ProcedureNode
        for ir in ir_list:
            _build_sp_from_ir(graph, ir, schema, known_tables)

        # Phase 2: 建立 CALLS 边（需要所有 SP 节点已存在）
        for ir in ir_list:
            sp_id = f"{schema}.{ir.name}"
            called = _collect_exec_calls(ir)
            for called_name in called:
                called_id = f"{schema}.{called_name}"
                if graph.has_node(called_id):
                    graph.add_edge(SchemaEdge(
                        source_id=sp_id,
                        target_id=called_id,
                        edge_type=SchemaEdgeType.CALLS,
                    ))

        logger.info(
            "SPBuilder.from_ir_list: %d nodes, %d edges",
            graph.node_count, graph.edge_count,
        )
        return graph

    @staticmethod
    def from_tsql(
        tsql_text: str,
        sp_name: str | None = None,
        schema: str = "dbo",
        known_tables: set[str] | None = None,
    ) -> SchemaGraph:
        """从 T-SQL 文本直接构建（调用 SPCompiler 编译后提取 IR）。

        Args:
            tsql_text: T-SQL 存储过程源码。
            sp_name: SP 名称（None 从编译结果获取）。
            schema: 默认 schema 前缀。
            known_tables: 已知表名集合。

        Returns:
            SchemaGraph。
        """
        from architecture.core.sql.compiler.engine import compile_sp

        result = compile_sp(tsql_text, "mssql", "kingbasees")
        if hasattr(result, "ir") and result.ir is not None:
            return SPBuilder.from_ir(result.ir, schema, known_tables)

        # 编译失败时返回空图
        logger.warning("SPCompiler failed, returning empty graph")
        return SchemaGraph()


# =========================================================================
# Internal helpers
# =========================================================================


def _build_sp_from_ir(
    graph: SchemaGraph,
    ir: Any,
    schema: str,
    known_tables: set[str] | None,
) -> None:
    """从单个 IRProcedure 构建 ProcedureNode 和 DEPENDS_ON 边。"""
    sp_id = f"{schema}.{ir.name}"

    # Extract parameters
    params: list[dict[str, str]] = []
    for p in (ir.parameters or ()):
        mode = "OUT" if getattr(p, "is_output", False) else "IN"
        params.append({
            "name": p.name,
            "data_type": p.data_type,
            "mode": mode,
        })

    # Collect EXEC calls (SP → SP)
    called_procs = _collect_exec_calls(ir)

    # Collect table references from SQL statements
    referenced_tables = _collect_table_refs(ir, known_tables)

    # Compute body hash for change detection
    body_hash = ""
    if ir.original_source:
        body_hash = hashlib.sha256(ir.original_source.encode()).hexdigest()[:16]

    # Create ProcedureNode
    graph.add_node(ProcedureNode(
        id=sp_id,
        name=ir.name,
        schema=schema,
        parameters=tuple(params),
        body_hash=body_hash,
        called_procedures=tuple(sorted(called_procs)),
        referenced_tables=tuple(sorted(referenced_tables)),
        language="tsql",
    ))

    # Create DEPENDS_ON edges for table references
    for tbl_name in referenced_tables:
        tbl_id = f"{schema}.{tbl_name}"
        # 如果 known_tables 提供了，只建已知表的边
        # 否则建所有提取到的表（即使表节点尚不存在）
        graph.add_edge(SchemaEdge(
            source_id=sp_id,
            target_id=tbl_id,
            edge_type=SchemaEdgeType.DEPENDS_ON,
            metadata={"source": "ir_sql_extraction"},
        ))

    # Create CALLS edges
    for called_name in called_procs:
        called_id = f"{schema}.{called_name}"
        graph.add_edge(SchemaEdge(
            source_id=sp_id,
            target_id=called_id,
            edge_type=SchemaEdgeType.CALLS,
        ))


def _collect_exec_calls(ir: Any) -> set[str]:
    """递归遍历 IR 树，收集所有 EXEC 调用的 SP 名称。"""
    calls: set[str] = set()
    _walk_ir(ir.body if hasattr(ir, "body") else (), calls, set())
    return calls


def _collect_table_refs(ir: Any, known_tables: set[str] | None) -> set[str]:
    """递归遍历 IR 树，从 SQL 语句中提取表引用。"""
    table_refs: set[str] = set()
    sql_texts: list[str] = []
    _collect_sql_texts(ir.body if hasattr(ir, "body") else (), sql_texts)

    for sql_text in sql_texts:
        try:
            from architecture.core.sql.diagnostics.extractor import extract_objects
            extracted = extract_objects(sql_text)
            for tbl_ref in extracted.tables:
                tbl_name = tbl_ref.name
                if known_tables is None or tbl_name in known_tables:
                    table_refs.add(tbl_name)
        except Exception as exc:
            logger.debug("Failed to extract tables from SQL: %s", exc)

    return table_refs


def _walk_ir(
    nodes: tuple[Any, ...] | Any,
    calls: set[str],
    tables: set[str],
) -> None:
    """递归遍历 IR 节点树。"""
    if not isinstance(nodes, (tuple, list)):
        nodes = (nodes,)

    for node in nodes:
        node_type = getattr(node, "node_type", None)
        if node_type is None:
            continue

        type_name = node_type.name if hasattr(node_type, "name") else str(node_type)

        if type_name == "EXEC":
            proc_name = getattr(node, "procedure_name", "")
            if proc_name:
                calls.add(proc_name)

        # Recurse into container nodes
        for attr in ("then_body", "else_body", "body"):
            child = getattr(node, attr, None)
            if child and isinstance(child, (tuple, list)) and len(child) > 0:
                _walk_ir(child, calls, tables)


def _collect_sql_texts(nodes: tuple[Any, ...] | Any, sql_texts: list[str]) -> None:
    """递归收集所有 IRSQL 节点的 sql_text。"""
    if not isinstance(nodes, (tuple, list)):
        nodes = (nodes,)

    for node in nodes:
        node_type = getattr(node, "node_type", None)
        if node_type is None:
            continue

        type_name = node_type.name if hasattr(node_type, "name") else str(node_type)

        if type_name == "SQL":
            sql_text = getattr(node, "sql_text", "")
            if sql_text:
                sql_texts.append(sql_text)

        # Recurse into container nodes
        for attr in ("then_body", "else_body", "body"):
            child = getattr(node, attr, None)
            if child and isinstance(child, (tuple, list)) and len(child) > 0:
                _collect_sql_texts(child, sql_texts)
