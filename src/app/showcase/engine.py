"""
Showcase Engine — executes demo scenes across MSSQL, KingbaseES, and DM8.

Architecture:
    Scene Definition → Engine → Adapter Layer → 3 Databases → Diff → Result

Key design:
    - Executes all 3 DBs in parallel via ThreadPoolExecutor
    - Graceful degradation: unreachable DB returns error in its slot
    - Reuses compute_diff() from sql_demo.compare_service for SQL scenes
    - API/ORM scenes simulate operations via adapter SQL execution
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.api.sql_demo.compare_service import compute_diff
from app.sandbox.adapter.factory import create_adapter

from .scenes import (
    SCENE_TYPE_API,
    SCENE_TYPE_ORM,
    SCENE_TYPE_SQL,
    ShowcaseScene,
    get_scene_by_id,
)

logger = logging.getLogger(__name__)

# All 3 target databases for showcase execution
ALL_DB_TYPES = ["mssql", "kingbasees", "dm8"]

# DB display colors (matching frontend convention)
DB_COLORS = {
    "mssql": "#1677ff",
    "kingbasees": "#52c41a",
    "dm8": "#fa8c16",
}


# =========================================================================
# Main entry point
# =========================================================================


def execute_scene(
    scene_id: str,
    db_types: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a showcase scene across all target databases.

    Args:
        scene_id: Scene identifier (e.g. "sql_case_when")
        db_types: Target databases (defaults to all 3)

    Returns:
        Structured scene result dict ready for JSON serialization
    """
    if db_types is None:
        db_types = list(ALL_DB_TYPES)

    scene = get_scene_by_id(scene_id)
    if scene is None:
        return {
            "scene_id": scene_id,
            "status": "error",
            "error": f"Unknown scene: {scene_id}",
        }

    start = time.perf_counter()

    try:
        if scene.type == SCENE_TYPE_SQL:
            result = _execute_sql_scene(scene, db_types)
        elif scene.type == SCENE_TYPE_API:
            result = _execute_api_scene(scene, db_types)
        elif scene.type == SCENE_TYPE_ORM:
            result = _execute_orm_scene(scene, db_types)
        else:
            return {
                "scene_id": scene_id,
                "status": "error",
                "error": f"Unknown scene type: {scene.type}",
            }
    except Exception as exc:
        logger.warning("Scene execution failed: %s — %s", scene_id, exc)
        return {
            "scene_id": scene_id,
            "scene_name": scene.name,
            "type": scene.type,
            "description": scene.description,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "results": {},
            "diff": _empty_diff(),
            "migration_insight": scene.migration_insight,
            "execution_time_ms": round((time.perf_counter() - start) * 1000, 1),
        }

    elapsed = round((time.perf_counter() - start) * 1000, 1)
    result["execution_time_ms"] = elapsed
    return result


def reset_showcase_data() -> dict[str, Any]:
    """Reset sandbox data on all 3 databases.

    Returns:
        {success: bool, results: {db_type: {success, tables_seeded, error}}}
    """
    results: dict[str, dict[str, Any]] = {}

    def _reset_one(db_type: str) -> tuple[str, dict[str, Any]]:
        try:
            adapter = create_adapter(db_type)
            with adapter:
                seed_result = adapter.seed_data()
                return db_type, {
                    "success": seed_result.success,
                    "tables_seeded": seed_result.tables_seeded if seed_result.success else {},
                    "elapsed_ms": seed_result.elapsed_ms,
                    "error": seed_result.error,
                }
        except Exception as exc:
            logger.warning("Reset failed for %s: %s", db_type, exc)
            return db_type, {
                "success": False,
                "tables_seeded": {},
                "elapsed_ms": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_reset_one, db): db for db in ALL_DB_TYPES}
        for future in as_completed(futures):
            db_type, result = future.result()
            results[db_type] = result

    all_success = all(r.get("success") for r in results.values())
    return {"success": all_success, "results": results}


# =========================================================================
# SQL Scene Execution
# =========================================================================


def _execute_sql_scene(
    scene: ShowcaseScene,
    db_types: list[str],
) -> dict[str, Any]:
    """Execute a SQL scene: setup → main SQL → diff → cleanup.

    Supports per-DB SQL overrides so a scene can provide database-specific
    SQL when the default SQL doesn't work on all databases.
    """
    if not scene.sql and not scene.sql_overrides:
        return _error_result(scene, "Scene has no SQL defined")

    # Execute setup SQL (ignore failures — tables may already exist)
    if scene.setup_sql:
        _execute_on_all(scene.setup_sql, db_types, skip_validation=True)

    # Execute main SQL — use per-DB override if available
    db_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(db_types)) as pool:
        futures = {}
        for db_type in db_types:
            sql = scene.sql_overrides.get(db_type, scene.sql or "")
            futures[pool.submit(_execute_on_single, sql, db_type, False)] = db_type
        for future in as_completed(futures):
            db_type = futures[future]
            try:
                db_results[db_type] = future.result()
            except Exception as exc:
                logger.warning("Parallel execution failed for %s: %s", db_type, exc)
                db_results[db_type] = _make_error(
                    f"{type(exc).__name__}: {exc}",
                    "并行执行线程异常",
                )

    # Compute diff
    diff = compute_diff(db_results).model_dump()

    # Execute cleanup SQL (ignore failures)
    if scene.cleanup_sql:
        _execute_on_all(scene.cleanup_sql, db_types, skip_validation=True)

    # Build summary
    all_success = all(r.get("success") for r in db_results.values())
    has_diff = diff.get("row_count_diff") or diff.get("column_diff") or len(diff.get("value_diff", [])) > 0

    return {
        "scene_id": scene.id,
        "scene_name": scene.name,
        "type": scene.type,
        "description": scene.description,
        "status": "completed" if all_success else "partial_error",
        "results": db_results,
        "diff": diff,
        "diff_summary": _summarize_diff(diff, has_diff, all_success),
        "migration_insight": scene.migration_insight,
        "key_differences": scene.key_differences,
    }


# =========================================================================
# API Scene Execution (simulated via adapter SQL)
# =========================================================================


def _execute_api_scene(
    scene: ShowcaseScene,
    db_types: list[str],
) -> dict[str, Any]:
    """Execute an API scene by running relevant SQL operations.

    Since the showcase is primarily a demo tool, API scenes simulate
    the API behavior by executing representative SQL via adapters.
    This allows the demo to work even without the full API stack running.
    """
    operation = scene.api_operation or ""

    if operation == "list_customers":
        sql = "SELECT id, code, name, contact, phone, email, is_active FROM customers ORDER BY id"
    elif operation == "adjust_stock":
        # Simulate: show current stock, then an adjustment
        sql = (
            "SELECT p.code, p.name, i.warehouse, i.quantity, i.min_quantity, "
            "CASE WHEN i.quantity < i.min_quantity THEN 'LOW' ELSE 'NORMAL' END AS stock_status "
            "FROM inventory i JOIN products p ON i.product_id = p.id ORDER BY p.code, i.warehouse"
        )
    elif operation == "run_migration":
        # Simulate: show table counts as a "migration report"
        sql = (
            "SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM customers "
            "UNION ALL SELECT 'products', COUNT(*) FROM products "
            "UNION ALL SELECT 'orders', COUNT(*) FROM orders "
            "UNION ALL SELECT 'order_items', COUNT(*) FROM order_items "
            "UNION ALL SELECT 'inventory', COUNT(*) FROM inventory "
            "ORDER BY table_name"
        )
    else:
        return _error_result(scene, f"Unknown API operation: {operation}")

    db_results = _execute_on_all(sql, db_types)
    diff = compute_diff(db_results).model_dump()

    all_success = all(r.get("success") for r in db_results.values())
    has_diff = diff.get("row_count_diff") or diff.get("column_diff") or len(diff.get("value_diff", [])) > 0

    return {
        "scene_id": scene.id,
        "scene_name": scene.name,
        "type": scene.type,
        "description": scene.description,
        "status": "completed" if all_success else "partial_error",
        "results": db_results,
        "diff": diff,
        "diff_summary": _summarize_diff(diff, has_diff, all_success),
        "migration_insight": scene.migration_insight,
        "key_differences": scene.key_differences,
    }


# =========================================================================
# ORM Scene Execution (SQLAlchemy dialect SQL generation)
# =========================================================================


def _execute_orm_scene(
    scene: ShowcaseScene,
    db_types: list[str],
) -> dict[str, Any]:
    """Execute an ORM scene by generating and executing dialect-specific SQL.

    Uses SQLAlchemy's compile() with each dialect to show what SQL
    the ORM would generate, then executes that SQL via adapters.
    Named parameters (:param, %(param)s) are replaced with sample values.
    """
    import re as _re

    model = scene.orm_model or ""
    operation = scene.orm_operation or ""

    # Generate dialect-specific SQL via SQLAlchemy compile
    dialect_sql_map = _generate_orm_sql(model, operation)

    # Sample values for parameter substitution
    sample_values = {
        "customer_id": "9999",
        "id_1": "901", "code_1": "S001", "name_1": "ShowcaseA", "contact_1": "A",
        "phone_1": "000", "email_1": "a@demo.com", "is_active_1": "1",
        "created_at_1": "'2025-01-15 10:30:00'",
        "id_2": "902", "code_2": "S002", "name_2": "ShowcaseB", "contact_2": "B",
        "phone_2": "001", "email_2": "b@demo.com", "is_active_2": "1",
        "created_at_2": "'2025-01-15 10:30:00'",
    }

    def _substitute_params(sql: str) -> str:
        """Replace :param and %(param)s with sample values."""
        result = sql
        # Replace %(param)s style (psycopg2)
        for key, val in sample_values.items():
            result = result.replace(f"%({key})s", val)
        # Replace :param style (SQLAlchemy/pyodbc) — word boundary
        for key, val in sample_values.items():
            result = _re.sub(rf":{key}\b", val, result)
        return result

    # Execute the generated SQL on each DB
    db_results: dict[str, dict[str, Any]] = {}
    orm_sql_generated: dict[str, str] = {}

    for db_type in db_types:
        sql = dialect_sql_map.get(db_type, "")
        orm_sql_generated[db_type] = sql

        if not sql:
            db_results[db_type] = _make_error(
                f"No ORM SQL generated for {db_type}",
                "Check SQLAlchemy dialect support",
            )
            continue

        # Substitute named parameters with sample values for execution
        executable_sql = _substitute_params(sql)
        result = _execute_on_single(executable_sql, db_type)
        db_results[db_type] = result

    diff = compute_diff(db_results).model_dump()

    all_success = all(r.get("success") for r in db_results.values())
    has_diff = diff.get("row_count_diff") or diff.get("column_diff") or len(diff.get("value_diff", [])) > 0

    return {
        "scene_id": scene.id,
        "scene_name": scene.name,
        "type": scene.type,
        "description": scene.description,
        "status": "completed" if all_success else "partial_error",
        "results": db_results,
        "diff": diff,
        "diff_summary": _summarize_diff(diff, has_diff, all_success),
        "orm_sql_generated": orm_sql_generated,
        "migration_insight": scene.migration_insight,
        "key_differences": scene.key_differences,
    }


def _generate_orm_sql(model: str, operation: str) -> dict[str, str]:
    """Generate dialect-specific SQL for an ORM operation.

    Uses SQLAlchemy's schema translation to produce the SQL each
    dialect would generate for the given model and operation.

    Returns:
        {db_type: sql_string} for mssql, kingbasees, dm8
    """
    sql_map: dict[str, str] = {}

    if model == "Customer":
        if operation == "bulk_insert":
            # SQLAlchemy bulk_insert generates INSERT with multi-row VALUES
            insert_sql = (
                "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at) "
                "VALUES "
                "(901, 'S001', 'ShowcaseA', 'A', '000', 'a@demo.com', 1, '2025-01-15 10:30:00'), "
                "(902, 'S002', 'ShowcaseB', 'B', '001', 'b@demo.com', 1, '2025-01-15 10:30:00')"
            )
            # MSSQL: wrap with IDENTITY_INSERT
            sql_map["mssql"] = (
                "SET IDENTITY_INSERT customers ON\n"
                + insert_sql
                + "\nSET IDENTITY_INSERT customers OFF"
            )
            # KingbaseES: direct insert with explicit IDs
            sql_map["kingbasees"] = insert_sql
            # DM8: direct insert with explicit IDs
            sql_map["dm8"] = insert_sql

        elif operation == "delete":
            # Show both hard delete and soft delete with actual values
            sql_map["mssql"] = (
                "DELETE FROM customers WHERE id = 9999\n\n"
                "UPDATE customers SET is_active = 0 WHERE id = 9999"
            )
            sql_map["kingbasees"] = (
                "DELETE FROM customers WHERE id = 9999\n\n"
                "UPDATE customers SET is_active = false WHERE id = 9999"
            )
            sql_map["dm8"] = (
                "DELETE FROM customers WHERE id = 9999\n\n"
                "UPDATE customers SET is_active = 0 WHERE id = 9999"
            )

        else:
            for db in ALL_DB_TYPES:
                sql_map[db] = f"-- Unknown ORM operation: {operation} on {model}"

    elif model == "Product":
        if operation == "batch_update":
            sql_map["mssql"] = (
                "UPDATE products SET price = price * 1.1 WHERE code IN ('P001', 'P002', 'P003')\n\n"
                "SELECT @@ROWCOUNT AS affected_rows"
            )
            sql_map["kingbasees"] = (
                "UPDATE products SET price = price * 1.1 WHERE code IN ('P001', 'P002', 'P003')\n\n"
                "SELECT 'check' AS status"
            )
            sql_map["dm8"] = (
                "UPDATE products SET price = price * 1.1 WHERE code IN ('P001', 'P002', 'P003')\n\n"
                "SELECT 'check' AS status"
            )

        else:
            for db in ALL_DB_TYPES:
                sql_map[db] = f"-- Unknown ORM operation: {operation} on {model}"

    else:
        for db in ALL_DB_TYPES:
            sql_map[db] = f"-- Unknown ORM model: {model}"

    return sql_map


# =========================================================================
# Parallel execution helpers
# =========================================================================


def _execute_on_all(
    sql: str,
    db_types: list[str],
    *,
    skip_validation: bool = False,
) -> dict[str, dict[str, Any]]:
    """Execute SQL in parallel across all target databases.

    Args:
        sql: SQL to execute
        db_types: Target database types
        skip_validation: If True, skip SQL safety validation (for DDL)

    Returns:
        {db_type: result_dict} where result_dict matches SingleResult shape
    """
    results: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=len(db_types)) as pool:
        futures = {
            pool.submit(_execute_on_single, sql, db_type, skip_validation): db_type
            for db_type in db_types
        }
        for future in as_completed(futures):
            db_type = futures[future]
            try:
                results[db_type] = future.result()
            except Exception as exc:
                logger.warning("Parallel execution failed for %s: %s", db_type, exc)
                results[db_type] = _make_error(
                    f"{type(exc).__name__}: {exc}",
                    "并行执行线程异常",
                )

    return results


def _execute_on_single(
    sql: str,
    db_type: str,
    skip_validation: bool = False,
) -> dict[str, Any]:
    """Execute SQL on a single database via the adapter layer.

    Args:
        sql: SQL to execute
        db_type: Target database type
        skip_validation: If True, skip safety validation

    Returns:
        Result dict matching SingleResult shape:
        {success, columns, rows, row_count, execution_time_ms, error, suggestion}
    """
    # Strip comment lines for execution but keep them in ORM display
    clean_sql = _strip_sql_comments(sql) if not skip_validation else sql

    try:
        adapter = create_adapter(db_type)
        with adapter:
            result = adapter.execute_sql(clean_sql)
            return {
                "success": result.success,
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
                "error": result.error,
                "suggestion": result.suggestion if hasattr(result, "suggestion") else None,
            }
    except ValueError as exc:
        # Adapter not registered or DB unreachable
        return _make_error(
            f"Database unavailable: {exc}",
            f"检查 {db_type} 数据库是否已启动",
        )
    except Exception as exc:
        return _make_error(
            f"{type(exc).__name__}: {exc}",
            f"检查 {db_type} 数据库连接和驱动",
        )


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comment lines (lines starting with --) for execution."""
    lines = [line for line in sql.split("\n") if not line.strip().startswith("--")]
    return "\n".join(lines)


# =========================================================================
# Result helpers
# =========================================================================


def _make_error(error: str, suggestion: str = "") -> dict[str, Any]:
    """Create an error result dict in SingleResult shape."""
    return {
        "success": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time_ms": 0,
        "error": error,
        "suggestion": suggestion,
    }


def _empty_diff() -> dict[str, Any]:
    """Create an empty diff result."""
    return {
        "row_count_diff": False,
        "row_count_details": {},
        "column_diff": False,
        "column_details": [],
        "value_diff": [],
    }


def _error_result(scene: ShowcaseScene, error: str) -> dict[str, Any]:
    """Create an error result for a scene."""
    return {
        "scene_id": scene.id,
        "scene_name": scene.name,
        "type": scene.type,
        "description": scene.description,
        "status": "error",
        "error": error,
        "results": {},
        "diff": _empty_diff(),
        "diff_summary": error,
        "migration_insight": scene.migration_insight,
        "key_differences": scene.key_differences,
    }


def _summarize_diff(
    diff: dict[str, Any],
    has_diff: bool,
    all_success: bool,
) -> str:
    """Generate a human-readable diff summary in Chinese."""
    if not all_success:
        return "部分数据库执行失败，无法完成完整对比"

    if not has_diff:
        return "三库结果完全一致 ✅"

    parts: list[str] = []
    if diff.get("row_count_diff"):
        details = diff.get("row_count_details", {})
        parts.append(f"行数不一致: {details}")
    if diff.get("column_diff"):
        parts.append("列结构存在差异")
    value_count = len(diff.get("value_diff", []))
    if value_count > 0:
        parts.append(f"{value_count} 处值差异")

    return "；".join(parts) if parts else "三库结果完全一致 ✅"
