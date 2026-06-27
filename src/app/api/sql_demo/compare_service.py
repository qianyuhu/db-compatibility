"""
SQL Compare 服务层 — 多库并行执行 + Diff 引擎 + SQL 方言改写建议。

架构:
    compare_router.py → compare_service.py → service.execute_sql (单库执行器)
                                               ↘ diff engine
                                               ↘ rewrite detector

核心能力:
    1. 并行执行同一 SQL 到多个数据库
    2. Schema / Row Count / Value 三维度差异分析
    3. SQL 方言自动检测和改写建议 (TOP N → LIMIT 等)
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .service import execute_sql, validate_sql
from .compare_schemas import (
    ColumnDiff,
    DiffResult,
    SingleResult,
    SqlRewrite,
    ValueDiffItem,
)


# =========================================================================
# 对比执行
# =========================================================================


def execute_compare(
    sql: str,
    db_types: list[str],
) -> tuple[dict[str, dict[str, Any]], list[SqlRewrite]]:
    """在多个数据库上并行执行同一 SQL。

    Args:
        sql: SQL 语句
        db_types: 目标数据库列表

    Returns:
        (results_dict, rewrites): 各库执行结果 + SQL 改写建议
    """
    # 安全校验（全局一次）
    validate_sql(sql)

    # 生成改写建议（执行前）
    rewrites = detect_dialect_rewrites(sql, db_types)

    # 并行执行到各数据库
    results: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=len(db_types)) as pool:
        futures = {
            pool.submit(execute_sql, db_type, sql): db_type
            for db_type in db_types
        }
        for future in as_completed(futures):
            db_type = futures[future]
            try:
                results[db_type] = future.result()
            except Exception as exc:
                results[db_type] = {
                    "success": False,
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "execution_time_ms": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "suggestion": "对比执行线程异常",
                }

    return results, rewrites


# =========================================================================
# Diff 引擎
# =========================================================================


def compute_diff(
    results: dict[str, dict[str, Any]],
) -> DiffResult:
    """对比多个数据库的执行结果，生成三维度差异分析。

    维度:
        1. Schema diff — 列名是否一致
        2. Row count diff — 行数是否一致
        3. Value diff — 按行列对齐的具体值差异

    Args:
        results: {db_type: execute_sql 返回的 result dict}

    Returns:
        DiffResult 包含三个维度的差异详情
    """
    # 收集所有数据库的列名
    db_columns: dict[str, list[str]] = {}
    db_row_counts: dict[str, int] = {}

    for db_type, result in results.items():
        db_columns[db_type] = result.get("columns", [])
        db_row_counts[db_type] = result.get("row_count", 0)

    # ---- Schema diff ----
    column_diff, column_details = _compute_schema_diff(db_columns)

    # ---- Row count diff ----
    row_count_diff = len(set(db_row_counts.values())) > 1

    # ---- Value diff ----
    value_diff = _compute_value_diff(results, db_columns)

    # 限制 value diff 数量：最多返回 200 条差异
    value_diff = value_diff[:200]

    return DiffResult(
        row_count_diff=row_count_diff,
        row_count_details=db_row_counts,
        column_diff=column_diff,
        column_details=column_details,
        value_diff=value_diff,
    )


def _compute_schema_diff(
    db_columns: dict[str, list[str]],
) -> tuple[bool, list[ColumnDiff]]:
    """计算列名差异。

    Returns:
        (has_diff, column_details): 是否存在差异 + 各库的列详情
    """
    all_columns = list(db_columns.values())
    if not all_columns:
        return False, []

    # 所有库的列名并集
    union_columns: set[str] = set()
    for cols in all_columns:
        union_columns.update(cols)

    has_diff = any(
        set(cols) != union_columns for cols in all_columns
    )

    column_details: list[ColumnDiff] = []
    for db_type, cols in db_columns.items():
        missing = [c for c in union_columns if c not in cols]
        column_details.append(
            ColumnDiff(
                db_type=db_type,
                columns=cols,
                missing_from_others=missing,
            )
        )

    return has_diff, column_details


def _compute_value_diff(
    results: dict[str, dict[str, Any]],
    db_columns: dict[str, list[str]],
) -> list[ValueDiffItem]:
    """按行索引 + 列名对齐，找出值差异。

    策略:
        - 以最短行数为基准，只对比共同行（多余行由 row_count_diff 报告）
        - 取所有库列名的交集，只对比共同列
        - 逐行逐列比较值（转为字符串后比较）

    Returns:
        ValueDiffItem 列表，每项记录一行一列在各库的不同值
    """
    db_types = list(results.keys())
    if len(db_types) < 2:
        return []

    # 只对比成功的库
    successful_dbs = [
        db for db in db_types
        if results[db].get("success") and results[db].get("rows") is not None
    ]
    if len(successful_dbs) < 2:
        return []

    # 取列名交集
    common_columns = _intersect_columns(
        [db_columns[db] for db in successful_dbs]
    )
    if not common_columns:
        return []

    # 取最小行数
    min_rows = min(
        results[db]["row_count"] for db in successful_dbs
    )

    diffs: list[ValueDiffItem] = []

    for row_idx in range(min_rows):
        for col_name in common_columns:
            # 获取各库该位置的值
            values: dict[str, Any] = {}
            for db_type in successful_dbs:
                cols = db_columns[db_type]
                col_idx = cols.index(col_name) if col_name in cols else -1
                if col_idx >= 0 and col_idx < len(results[db_type]["rows"][row_idx]):
                    values[db_type] = results[db_type]["rows"][row_idx][col_idx]
                else:
                    values[db_type] = None

            # 比较值是否一致
            if _values_differ(values):
                diffs.append(
                    ValueDiffItem(
                        row_index=row_idx,
                        column=col_name,
                        values=values,
                    )
                )

    return diffs


def _intersect_columns(column_lists: list[list[str]]) -> list[str]:
    """返回多个列名列表的交集，保持第一个列表的顺序。"""
    if not column_lists:
        return []

    common = set(column_lists[0])
    for cols in column_lists[1:]:
        common = common & set(cols)

    # 按第一个列表的顺序返回
    return [c for c in column_lists[0] if c in common]


def _values_differ(values: dict[str, Any]) -> bool:
    """判断各库的值是否一致。

    比较策略:
        - 转换为字符串后比较（容忍类型差异如 int vs float）
        - None 视为相等
    """
    if len(values) < 2:
        return False

    serialized: list[str] = []
    for v in values.values():
        if v is None:
            serialized.append("<NULL>")
        elif isinstance(v, bool):
            serialized.append("true" if v else "false")
        elif isinstance(v, float):
            # 浮点数保留 6 位小数比较，容忍精度差异
            serialized.append(f"{v:.6f}")
        elif isinstance(v, (int, str)):
            serialized.append(str(v))
        elif isinstance(v, (bytes, bytearray)):
            serialized.append(f"<BINARY:{len(v)}bytes>")
        elif hasattr(v, "isoformat"):
            serialized.append(v.isoformat())
        else:
            serialized.append(repr(v))

    return len(set(serialized)) > 1


# =========================================================================
# SQL 方言改写检测
# =========================================================================


def detect_dialect_rewrites(
    sql: str,
    db_types: list[str],
) -> list[SqlRewrite]:
    """检测 SQL 中的方言特定语法，为不支持的数据库生成改写建议。

    已知规则:
        - TOP N → KingbaseES/DM8 建议 LIMIT
        - FETCH FIRST N ROWS ONLY → MSSQL 建议 TOP N
        - [] 方括号标识符 → KingbaseES/DM8 建议 ""
        - NEWID() → KingbaseES/DM8 建议 GEN_RANDOM_UUID()
        - GETDATE() → KingbaseES 建议 NOW(), DM8 建议 SYSDATE
        - ISNULL() → KingbaseES/DM8 建议 COALESCE()
        - LEN() → KingbaseES/DM8 建议 LENGTH()

    Returns:
        SqlRewrite 列表，为空表示无需改写
    """
    rewrites: list[SqlRewrite] = []

    upper_sql = sql.upper().strip()

    # -- TOP N 检测 --
    top_match = re.match(r"SELECT\s+TOP\s+(\d+)", upper_sql, re.IGNORECASE)
    if top_match:
        n = top_match.group(1)
        # 提取 SELECT TOP N 之后的部分
        remaining = re.sub(
            r"^SELECT\s+TOP\s+\d+\s*",
            "",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )

        for db_type in db_types:
            if db_type == "kingbasees":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=f"SELECT {remaining} LIMIT {n}",
                        reason=f"KingbaseES 不支持 TOP {n} 语法，建议使用 LIMIT {n}",
                    )
                )
            elif db_type == "dm8":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=f"SELECT {remaining} LIMIT {n}",
                        reason=f"DM8 不支持 TOP {n} 语法，建议使用 LIMIT {n}",
                    )
                )

    # -- FETCH FIRST N ROWS ONLY 检测 --
    fetch_match = re.search(
        r"FETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY",
        upper_sql,
        re.IGNORECASE,
    )
    if fetch_match:
        n = fetch_match.group(1)
        # 将 FETCH FIRST N ROWS ONLY 替换为 TOP N
        base_sql = re.sub(
            r"\s*FETCH\s+FIRST\s+\d+\s+ROWS?\s+ONLY\s*",
            "",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if "mssql" in db_types:
            rewrites.append(
                SqlRewrite(
                    original=sql.strip(),
                    db_type="mssql",
                    suggested=re.sub(
                        r"^SELECT\s+",
                        f"SELECT TOP {n} ",
                        base_sql,
                        count=1,
                        flags=re.IGNORECASE,
                    ),
                    reason=f"MSSQL 不支持 FETCH FIRST 语法，建议使用 TOP {n}",
                )
            )

    # -- [] 方括号标识符检测 (MSSQL 特有) --
    bracket_pattern = re.findall(r"\[([^\]]+)\]", sql)
    if bracket_pattern:
        for db_type in db_types:
            if db_type == "kingbasees":
                rewritten = sql
                for ident in bracket_pattern:
                    rewritten = rewritten.replace(
                        f"[{ident}]",
                        f'"{ident}"',
                    )
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=rewritten,
                        reason=(
                            "KingbaseES 使用双引号标识符而非方括号。"
                            f"已替换 {len(bracket_pattern)} 个方括号标识符。"
                        ),
                    )
                )
            elif db_type == "dm8":
                rewritten = sql
                for ident in bracket_pattern:
                    rewritten = rewritten.replace(
                        f"[{ident}]",
                        f'"{ident}"',
                    )
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=rewritten,
                        reason=(
                            "DM8 使用双引号标识符而非方括号。"
                            f"已替换 {len(bracket_pattern)} 个方括号标识符。"
                        ),
                    )
                )

    # -- NEWID() 检测 --
    if re.search(r"\bNEWID\s*\(\s*\)", upper_sql):
        for db_type in db_types:
            if db_type == "kingbasees":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bNEWID\s*\(\s*\)",
                            "GEN_RANDOM_UUID()",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="KingbaseES 不支持 NEWID()，建议使用 GEN_RANDOM_UUID()",
                    )
                )
            elif db_type == "dm8":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bNEWID\s*\(\s*\)",
                            "SYS_GUID()",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="DM8 不支持 NEWID()，建议使用 SYS_GUID()",
                    )
                )

    # -- GETDATE() 检测 --
    if re.search(r"\bGETDATE\s*\(\s*\)", upper_sql):
        for db_type in db_types:
            if db_type == "kingbasees":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bGETDATE\s*\(\s*\)",
                            "NOW()",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="KingbaseES 不支持 GETDATE()，建议使用 NOW()",
                    )
                )
            elif db_type == "dm8":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bGETDATE\s*\(\s*\)",
                            "SYSDATE",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="DM8 不支持 GETDATE()，建议使用 SYSDATE",
                    )
                )

    # -- ISNULL() 检测 --
    if re.search(r"\bISNULL\s*\((.+?),(.+?)\)", upper_sql):
        for db_type in db_types:
            if db_type == "kingbasees":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bISNULL\s*\((.+?),(.+?)\)",
                            r"COALESCE(\1,\2)",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="KingbaseES 不支持 ISNULL()，建议使用 COALESCE()",
                    )
                )
            elif db_type == "dm8":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bISNULL\s*\((.+?),(.+?)\)",
                            r"COALESCE(\1,\2)",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason="DM8 不支持 ISNULL()，建议使用 COALESCE()",
                    )
                )

    # -- LEN() 检测 --
    if re.search(r"\bLEN\s*\((.+?)\)", upper_sql):
        for db_type in db_types:
            if db_type == "kingbasees" or db_type == "dm8":
                rewrites.append(
                    SqlRewrite(
                        original=sql.strip(),
                        db_type=db_type,
                        suggested=re.sub(
                            r"\bLEN\s*\((.+?)\)",
                            r"LENGTH(\1)",
                            sql,
                            flags=re.IGNORECASE,
                        ),
                        reason=f"{'KingbaseES' if db_type == 'kingbasees' else 'DM8'} 不支持 LEN()，建议使用 LENGTH()",
                    )
                )

    return rewrites
