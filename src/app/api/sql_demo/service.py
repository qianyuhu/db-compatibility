"""
SQL 执行服务层 — 安全校验 + 多库执行器工厂。

架构:
    router.py → service.py → app.core.database (raw connections)
                              ↘ app.core.database (SQLAlchemy engine for MSSQL/DM8)

安全策略:
    - 禁止 DROP / ALTER / TRUNCATE / DELETE（可配置）
    - 仅允许 SELECT / SHOW / EXPLAIN / DESCRIBE / WITH
    - KingbaseES 必须走原生 psycopg2（autocommit 模式）
"""

import re
import threading
import time
from typing import Any

from sqlalchemy import text

# =========================================================================
# SQL 安全校验
# =========================================================================

# 默认禁止的关键字（大写匹配）
_FORBIDDEN_KEYWORDS = [
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "INSERT",
    "UPDATE",
    "DELETE",
    "GRANT",
    "REVOKE",
    "EXECUTE",
    "EXEC",
    "CALL",
    "MERGE",
    "REPLACE",
]

# 允许的关键字前缀（仅限只读操作）
_ALLOWED_PREFIXES = [
    "SELECT",
    "SHOW",
    "EXPLAIN",
    "DESCRIBE",
    "DESC ",
    "WITH",
]


class SQLSecurityError(ValueError):
    """SQL 安全校验失败。"""

    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message)
        self.suggestion = suggestion


def validate_sql(sql: str) -> None:
    """校验 SQL 语句安全性。

    规则:
    1. 去除注释后检查第一个关键字
    2. 首关键字必须在允许列表中
    3. 检查是否包含禁止关键字（防止注释绕过）

    Raises:
        SQLSecurityError: SQL 语句不安全
    """
    # 去除单行注释 (-- ...) 和多行注释 (/* ... */)
    cleaned = re.sub(r"--[^\n]*", "", sql)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    if not cleaned:
        raise SQLSecurityError(
            "SQL 语句为空",
            suggestion="请输入有效的 SQL 查询语句",
        )

    # 提取首关键字
    first_word_match = re.match(r"^(\w+)", cleaned, re.IGNORECASE)
    if not first_word_match:
        raise SQLSecurityError(
            "无法解析 SQL 语句",
            suggestion="请检查 SQL 语法",
        )

    first_word = first_word_match.group(1).upper()

    # 检查首关键字是否在允许列表
    allowed = any(
        first_word == prefix.strip().split()[0]
        for prefix in _ALLOWED_PREFIXES
    )

    if not allowed:
        raise SQLSecurityError(
            f"不允许的 SQL 类型: {first_word}",
            suggestion=(
                f"仅允许 SELECT / SHOW / EXPLAIN / DESCRIBE / WITH 查询。"
                f"如需执行 DML，请联系管理员。"
            ),
        )

    # 二次检查：扫描全文是否包含禁止关键字
    # 用单词边界匹配避免误判（如 description 中包含 DESC）
    upper_sql = cleaned.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, upper_sql):
            raise SQLSecurityError(
                f"SQL 包含禁止的关键字: {keyword}",
                suggestion="该操作已被安全策略阻止。仅允许只读查询。",
            )


# =========================================================================
# 执行器
# =========================================================================


def _execute_mssql(sql: str, params: tuple | None = None) -> dict[str, Any]:
    """通过 SQLAlchemy + pyodbc 执行 MSSQL 查询（复用缓存 Engine）。"""
    engine = _get_cached_engine("mssql")

    with engine.connect() as conn:
        # 将 %s 占位符转为 pyodbc 的 ? 占位符
        if params:
            sql = sql.replace("%s", "?")
        
        # MSSQL 性能优化：使用 FAST_FORWARD 游标（只进只读，性能最佳）
        # 通过 execution_options 设置，避免锁竞争
        result = conn.execute(
            text(sql).execution_options(isolation_level="READ UNCOMMITTED"),
            params or {}
        )

        columns = list(result.keys()) if result.returns_rows else []
        rows = []
        if result.returns_rows:
            rows = [list(row) for row in result.fetchall()]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }


def _execute_kingbasees(sql: str, params: tuple | None = None) -> dict[str, Any]:
    """通过原生 psycopg2（autocommit 模式）执行 KingbaseES 查询。"""
    conn = _get_raw_connection_for("kingbasees")

    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())

        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        # 将 Row 对象转为 list
        rows = [list(row) for row in rows]

        cur.close()
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    finally:
        conn.close()


def _execute_dm8(sql: str, params: tuple | None = None) -> dict[str, Any]:
    """通过原生 dmPython 执行 DM8 查询。"""
    conn = _get_raw_connection_for("dm8")

    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())

        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        rows = [list(row) for row in rows]

        cur.close()
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    finally:
        conn.close()


# =========================================================================
# 执行器工厂
# =========================================================================

_EXECUTORS = {
    "mssql": _execute_mssql,
    "kingbasees": _execute_kingbasees,
    "dm8": _execute_dm8,
}


def _make_settings(db_type: str):
    """创建指定数据库的 Settings 实例（不修改全局状态）。"""
    from app.core.config import Settings

    s = Settings()
    s.active_db = db_type
    return s


# ---- Engine 缓存（线程安全：每个 db_type 一个 Engine）----

_engine_cache: dict[str, Any] = {}
_engine_cache_lock = threading.Lock()


def _get_cached_engine(db_type: str):
    """返回缓存的 SQLAlchemy Engine，避免每次查询重建连接池。"""
    if db_type not in _engine_cache:
        with _engine_cache_lock:
            if db_type not in _engine_cache:  # double-check
                from sqlalchemy import create_engine as _ce

                s = _make_settings(db_type)
                
                # MSSQL 性能优化：更大的连接池 + 快速失败
                if db_type == "mssql":
                    _engine_cache[db_type] = _ce(
                        s.database_url,
                        echo=False,
                        pool_size=10,  # 增大连接池从3到10
                        max_overflow=20,  # 允许额外的溢出连接
                        pool_pre_ping=True,
                        pool_recycle=1800,
                        pool_timeout=30,  # 获取连接超时30秒
                    )
                else:
                    _engine_cache[db_type] = _ce(
                        s.database_url,
                        echo=False,
                        pool_size=3,
                        pool_pre_ping=True,
                        pool_recycle=1800,
                    )
    return _engine_cache[db_type]


def _get_raw_connection_for(db_type: str):
    """为指定数据库创建独立的原生连接，不修改全局状态。

    线程安全：每次调用都基于局部 Settings 实例获取连接参数。
    """
    s = _make_settings(db_type)
    kwargs = s.raw_connection_kwargs

    if db_type == "kingbasees":
        import psycopg2

        conn = psycopg2.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
            options=kwargs.get("options", ""),
            connect_timeout=kwargs.get("connect_timeout", 10),
        )
        conn.autocommit = True
        return conn

    elif db_type == "dm8":
        import dmPython

        return dmPython.connect(
            host=kwargs["host"],
            port=kwargs["port"],
            database=kwargs["database"],
            user=kwargs["user"],
            password=kwargs["password"],
        )

    elif db_type == "mssql":
        import pyodbc

        return pyodbc.connect(kwargs["connection_string"])

    raise ValueError(f"Unsupported db_type: {db_type}")


def execute_sql(
    db_type: str, sql: str, skip_validation: bool = False, params: tuple | None = None
) -> dict[str, Any]:
    """统一 SQL 执行入口。

    1. 安全校验（可选跳过，用于内部生成的业务 SQL）
    2. 选择执行器
    3. 执行并计时
    4. 返回统一格式结果

    Args:
        db_type: 数据库类型 (mssql/kingbasees/dm8)
        sql: SQL 语句（使用 %s 占位符）
        skip_validation: 跳过只读安全校验
        params: 参数化查询参数 tuple
    """
    # 安全校验
    if not skip_validation:
        validate_sql(sql)

    executor = _EXECUTORS.get(db_type)
    if executor is None:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "db_type": db_type,
            "execution_time_ms": 0,
            "error": f"不支持的数据库类型: {db_type}",
            "suggestion": "db_type 必须是 mssql / kingbasees / dm8 之一",
        }

    # 执行 + 计时
    start = time.perf_counter()
    try:
        result = executor(sql, params)
        elapsed_ms = (time.perf_counter() - start) * 1000

        return {
            "success": True,
            **result,
            "db_type": db_type,
            "execution_time_ms": round(elapsed_ms, 1),
            "error": None,
            "suggestion": None,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000

        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "db_type": db_type,
            "execution_time_ms": round(elapsed_ms, 1),
            "error": f"{type(exc).__name__}: {exc}",
            "suggestion": _suggest_fix(db_type, exc),
        }


def _suggest_fix(db_type: str, exc: Exception) -> str:
    """根据异常类型给出修复建议。"""
    msg = str(exc).lower()

    if "timeout" in msg or "refused" in msg or "could not connect" in msg:
        return (
            f"{db_type} 数据库不可达。"
            f"检查容器是否运行、防火墙是否开放端口。"
        )
    if "password" in msg or "authentication" in msg or "login" in msg:
        return f"认证失败。检查 .env 中 {db_type} 的用户名和密码。"
    if "does not exist" in msg:
        return f"数据库或对象不存在。检查 SQL 语句。"
    if "syntax" in msg or "parse" in msg:
        return f"SQL 语法错误。请检查语句是否符合 {db_type} 的 SQL 方言。"
    if "relation" in msg and "does not exist" in msg:
        return f"表不存在。请检查表名是否正确（MSSQL 可能需要 dbo. 前缀）。"
    if "column" in msg and "does not exist" in msg:
        return f"列名不存在。请检查字段拼写。"
    if "kingbase" in msg.lower() and "BEGIN" in str(exc):
        return "KingbaseES 事务语法冲突 — 这通常是已知的 PG Dialect 问题。"
    if "could not find driver" in msg.lower():
        return f"驱动程序未安装。请安装 {db_type} 对应的 Python 驱动。"
    if "is not a valid identifier" in msg:
        return "SQL 标识符无效。检查表名/列名是否需要方括号（MSSQL）或双引号。"
    if "invalid character" in msg:
        return "SQL 包含无效字符，可能是中文标点混入。"
    if "memory" in msg or "allocation" in msg:
        return "数据库内存不足。尝试限制返回行数（加 TOP / LIMIT）。"

    return f"执行失败。请检查 SQL 语法和 {db_type} 数据库状态。"
