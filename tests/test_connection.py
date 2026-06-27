"""
数据库连接验证 — Phase 1 Step 1 核心测试。

验证 MSSQL、KingbaseES MSSQL Compatible、DM8 三种数据库均能:
- SELECT 1
- 输出: 数据库类型、Driver、Dialect、Server Version、连接状态

KingbaseES 使用原生 psycopg2（autocommit 模式），见调研报告。
"""

import pytest


# =========================================================================
# 连接探针函数（每个 DB 独立）
# =========================================================================

def _probe_mssql():
    """探测 MSSQL 连接。返回 (success, info_dict)。"""
    from app.core.config import Settings

    info = {
        "db_type": "MSSQL",
        "driver": "pyodbc",
        "dialect": "mssql+pyodbc",
        "host": "",
        "server_version": "",
        "success": False,
        "error": None,
        "suggestion": None,
    }
    try:
        s = Settings()
        s.active_db = "mssql"
        info["host"] = f"{s.mssql_host}:{s.mssql_port}"

        import pyodbc  # noqa: F401 — 验证驱动可用
        from sqlalchemy import create_engine, text

        engine = create_engine(
            s.database_url,
            echo=False,
            connect_args={"connect_timeout": 10},
        )
        with engine.connect() as conn:
            version = conn.execute(text("SELECT @@VERSION")).scalar()
            conn.execute(text("SELECT 1"))
        engine.dispose()

        info["success"] = True
        info["server_version"] = version.split("\n")[0].strip() if version else ""
        return True, info
    except ImportError as e:
        info["error"] = str(e)
        info["suggestion"] = "安装 pyodbc: pip install pyodbc; 安装 ODBC Driver 18: brew install msodbcsql18"
        return False, info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        info["suggestion"] = _suggest_fix("mssql", e)
        return False, info


def _probe_kingbasees():
    """探测 KingbaseES MSSQL Compatible 连接（原生 psycopg2）。"""
    from app.core.config import Settings

    info = {
        "db_type": "KingbaseES MSSQL Compatible",
        "driver": "psycopg2 (原生, autocommit 模式)",
        "dialect": "无 — PG Dialect 版本解析失败（已知问题）",
        "host": "",
        "server_version": "",
        "database_mode": "",
        "success": False,
        "error": None,
        "suggestion": None,
    }
    try:
        s = Settings()
        s.active_db = "kingbasees"
        info["host"] = f"{s.kingbasees_host}:{s.kingbasees_port}"

        import psycopg2  # noqa: F401

        # 使用本地 Settings 实例直连，避免全局 settings 的单例干扰
        conn = psycopg2.connect(
            host=s.kingbasees_host,
            port=s.kingbasees_port,
            database=s.kingbasees_database,
            user=s.kingbasees_user,
            password=s.kingbasees_password,
            connect_timeout=10,
            options="-c client_encoding=utf8",
        )
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT version()")
        info["server_version"] = cur.fetchone()[0]

        cur.execute(
            "SELECT name, setting FROM sys_settings WHERE name = 'database_mode'"
        )
        row = cur.fetchone()
        info["database_mode"] = row[1] if row else "unknown"

        cur.execute("SELECT 1")
        cur.close()
        conn.close()

        info["success"] = True
        return True, info
    except ImportError as e:
        info["error"] = str(e)
        info["suggestion"] = "安装 psycopg2: pip install psycopg2-binary"
        return False, info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        info["suggestion"] = _suggest_fix("kingbasees", e)
        return False, info


def _probe_dm8():
    """探测 DM8 连接。"""
    from app.core.config import Settings

    info = {
        "db_type": "DM8",
        "driver": "dmPython",
        "dialect": "dm+dmPython",
        "host": "",
        "server_version": "",
        "success": False,
        "error": None,
        "suggestion": None,
    }
    try:
        s = Settings()
        s.active_db = "dm8"
        info["host"] = f"{s.dm8_host}:{s.dm8_port}"

        import dmPython  # noqa: F401

        conn = dmPython.connect(
            user=s.dm8_user,
            password=s.dm8_password,
            server=s.dm8_host,
            port=s.dm8_port,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.execute("SELECT banner FROM v$version WHERE banner LIKE 'DM%'")
        row = cur.fetchone()
        info["server_version"] = row[0] if row else ""
        cur.close()
        conn.close()

        info["success"] = True
        return True, info
    except ImportError as e:
        info["error"] = str(e)
        info["suggestion"] = (
            "安装 dmPython: pip install dmPython; "
            "DM8 Docker 未启动: docker compose -f docker/compose.dm8.yml up -d"
        )
        return False, info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        info["suggestion"] = _suggest_fix("dm8", e)
        return False, info


def _suggest_fix(db_type: str, exc: Exception) -> str:
    """根据异常类型给出修复建议。"""
    msg = str(exc).lower()
    if "timeout" in msg or "refused" in msg or "could not connect" in msg:
        return f"数据库不可达。检查 {db_type} 容器是否运行、防火墙是否开放端口。"
    if "password" in msg or "authentication" in msg or "login" in msg:
        return f"认证失败。检查 .env 中 {db_type} 的用户名和密码。"
    if "does not exist" in msg:
        return f"数据库不存在。需要在 {db_type} 中创建目标数据库。"
    return "检查 .env 配置、网络连通性和驱动安装。"


# =========================================================================
# Tests
# =========================================================================


class TestMSSQLConnection:
    """MSSQL 连接验证 — 生产基准数据库。"""

    def test_connection(self):
        """MSSQL 应能通过 SQLAlchemy + pyodbc 连接并执行 SELECT 1。"""
        success, info = _probe_mssql()

        print(f"\n  DB Type:   {info['db_type']}")
        print(f"  Driver:    {info['driver']}")
        print(f"  Dialect:   {info['dialect']}")
        print(f"  Host:      {info['host']}")
        print(f"  Version:   {info.get('server_version', 'N/A')[:100]}")
        print(f"  Success:   {info['success']}")

        if not success:
            print(f"  Error:     {info['error']}")
            print(f"  Suggestion:{info['suggestion']}")
            pytest.fail(f"MSSQL 连接失败: {info['error']} — {info['suggestion']}")

        assert info["success"] is True
        assert info["server_version"] != ""

    def test_sqlalchemy_engine(self):
        """MSSQL 应能通过 database.py 的 get_engine() 获取 engine。"""
        from app.core.config import Settings
        import sys

        # 强制 MSSQL
        s = Settings()
        s.active_db = "mssql"

        # Reload database module with correct settings
        if "app.core.database" in sys.modules:
            import importlib
            import app.core.database as db_mod
            import app.core.config as cfg_mod
            importlib.reload(cfg_mod)
            importlib.reload(db_mod)

        from app.core.database import get_engine
        from sqlalchemy import text

        eng = get_engine()
        assert eng is not None, "MSSQL engine 不应为 None"
        with eng.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            assert result == 1


class TestKingbaseESConnection:
    """KingbaseES MSSQL Compatible 连接验证。"""

    def test_connection(self):
        """KingbaseES MSSQL 兼容模式应能通过原生 psycopg2 连接。"""
        success, info = _probe_kingbasees()

        print(f"\n  DB Type:   {info['db_type']}")
        print(f"  Driver:    {info['driver']}")
        print(f"  Dialect:   {info['dialect']}")
        print(f"  Host:      {info['host']}")
        print(f"  Version:   {info.get('server_version', 'N/A')[:100]}")
        print(f"  Mode:      {info.get('database_mode', 'N/A')}")
        print(f"  Success:   {info['success']}")

        if not success:
            print(f"  Error:     {info['error']}")
            print(f"  Suggestion:{info['suggestion']}")
            pytest.fail(
                f"KingbaseES 连接失败: {info['error']} — {info['suggestion']}"
            )

        assert info["success"] is True
        assert info["server_version"] != ""
        # 确认处于 SQL Server 兼容模式
        assert info.get("database_mode") == "sqlserver", (
            f"期望 database_mode=sqlserver，实际={info.get('database_mode')}"
        )

    def test_raw_connection_works(self):
        """KingbaseES 应能通过原生 psycopg2（autocommit）连接并执行 SELECT 1。"""
        from app.core.config import Settings
        import psycopg2

        s = Settings()
        s.active_db = "kingbasees"

        conn = psycopg2.connect(
            host=s.kingbasees_host,
            port=s.kingbasees_port,
            database=s.kingbasees_database,
            user=s.kingbasees_user,
            password=s.kingbasees_password,
            connect_timeout=10,
            options="-c client_encoding=utf8",
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 AS one")
        result = cur.fetchone()[0]
        # KingbaseES MSSQL 兼容模式可能返回字符串或整数
        assert int(result) == 1, f"Expected 1, got {result} ({type(result)})"
        cur.close()
        conn.close()

    def test_sqlalchemy_engine_is_none(self):
        """KingbaseES 不应提供 SQLAlchemy Engine（已知限制）。"""
        # 切换到 KingbaseES 的 Settings 上下文
        from app.core.config import Settings
        import app.core.database as db_mod

        # 临时替换全局 settings
        s = Settings()
        s.active_db = "kingbasees"
        original = db_mod.settings
        db_mod.settings = s
        try:
            eng = db_mod.get_engine()
            assert eng is None, (
                "KingbaseES MSSQL 兼容模式不支持 SQLAlchemy PG Dialect"
            )
        finally:
            db_mod.settings = original


class TestDM8Connection:
    """DM8 连接验证。"""

    def test_connection(self):
        """DM8 应能通过 dmPython 连接。"""
        try:
            import dmPython  # noqa: F401
        except ImportError:
            pytest.skip("dmPython 未安装，DM8 Docker 未启动")

        success, info = _probe_dm8()

        print(f"\n  DB Type:   {info['db_type']}")
        print(f"  Driver:    {info['driver']}")
        print(f"  Dialect:   {info['dialect']}")
        print(f"  Host:      {info['host']}")
        print(f"  Version:   {info.get('server_version', 'N/A')[:100]}")
        print(f"  Success:   {info['success']}")

        if not success:
            print(f"  Error:     {info['error']}")
            print(f"  Suggestion:{info['suggestion']}")
            pytest.fail(f"DM8 连接失败: {info['error']} — {info['suggestion']}")

        assert info["success"] is True
        assert info["server_version"] != ""


# =========================================================================
# 综合测试
# =========================================================================


class TestAllDatabases:
    """综合验证：输出所有数据库连接状态。"""

    def test_connection_summary(self):
        """输出三种数据库的连接汇总。"""
        results = {}
        for name, probe_fn in [
            ("MSSQL", _probe_mssql),
            ("KingbaseES", _probe_kingbasees),
            ("DM8", _probe_dm8),
        ]:
            success, info = probe_fn()
            results[name] = info

        print("\n" + "=" * 70)
        print("数据库连接汇总")
        print("=" * 70)

        all_pass = True
        for name, info in results.items():
            status = "✅ 连接成功" if info["success"] else "❌ 连接失败"
            print(f"\n{name}")
            print(f"  Driver:     {info['driver']}")
            print(f"  Dialect:    {info['dialect']}")
            print(f"  Server:     {info.get('server_version', 'N/A')[:80]}")
            print(f"  Host:       {info['host']}")
            print(f"  Status:     {status}")
            if not info["success"]:
                all_pass = False
                print(f"  Error:      {info['error']}")
                print(f"  Suggestion: {info['suggestion']}")

        print("\n" + "=" * 70)
        print(f"总体状态: {'✅ 全部通过' if all_pass else '⚠️  部分数据库不可达'} ")
        print("=" * 70)

        # 至少 MSSQL 必须通过（生产基准）
        assert results["MSSQL"]["success"], (
            f"MSSQL 必须可达: {results['MSSQL']['error']}"
        )
