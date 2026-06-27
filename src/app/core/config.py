"""
配置中心 — 通过 APP_ACTIVE_DB 切换目标数据库。

Phase 1 约束:
- 不做任何兼容层抽象
- 仅提供连接 URL 和基础连接参数
- 各数据库差异由测试层自行发现

环境文件优先级: .env < .env.local（后者覆盖前者）
密码安全: 使用 sqlalchemy.engine.URL.create() 而非 f-string 拼接，
          自动处理 @ # / : 等特殊字符。

数据库 / 驱动映射:
=================================================================
| APP_ACTIVE_DB | 数据库          | Driver           | Dialect      |
|---------------|-----------------|------------------|--------------|
| mssql         | SQL Server 2022 | pyodbc           | mssql+pyodbc |
| kingbasees    | KingbaseES MSSQL| psycopg2         | postgresql   |
|               | Compatible Mode | (custom creator) | +psycopg2    |
| dm8           | 达梦 DM8        | dmPython         | dm+dmPython  |
=================================================================

KingbaseES MSSQL 兼容模式注意事项:
- 传输层使用 PostgreSQL wire protocol (端口 54321)
- SQL 层接受 T-SQL 语法 (TOP, BEGIN TRANSACTION, GETDATE() 等)
- SQLAlchemy PG Dialect 的 BEGIN 与 T-SQL 语法冲突，需 autocommit 模式
- 详见 docs/kingbase-mssql-driver-investigation.md
"""

from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = {
        "env_file": (".env", ".env.local"),  # 后者覆盖前者
        "env_prefix": "APP_",
        "extra": "ignore",  # 忽略未知环境变量
    }

    # ---- 当前激活的数据库 ----
    active_db: str = "mssql"  # mssql | kingbasees | dm8

    # ---- MSSQL (SQL Server 2019+) ----
    mssql_host: str = "localhost"
    mssql_port: int = 1433
    mssql_database: str = "demo_db"
    mssql_user: str = "sa"
    mssql_password: str = ""

    # ---- KingbaseES MSSQL Compatible Edition ----
    # 端口 54321 — PostgreSQL wire protocol, T-SQL 语法层
    kingbasees_host: str = "localhost"
    kingbasees_port: int = 54321
    kingbasees_database: str = "demo_db"
    kingbasees_user: str = "system"
    kingbasees_password: str = ""

    # ---- DM8 (达梦) — 默认端口 5236 ----
    dm8_host: str = "localhost"
    dm8_port: int = 5236
    dm8_database: str = "demo_db"
    dm8_user: str = "SYSDBA"
    dm8_password: str = ""

    # =========================================================================
    # URL 生成 (使用 SQLAlchemy URL.create 防特殊字符)
    # =========================================================================

    @property
    def database_url(self) -> str:
        """根据 active_db 自动生成 SQLAlchemy 连接 URL。"""
        if self.active_db == "mssql":
            return self._mssql_url
        elif self.active_db == "kingbasees":
            return self._kingbasees_url
        elif self.active_db == "dm8":
            return self._dm8_url
        raise ValueError(f"Unsupported active_db: {self.active_db}")

    @property
    def _mssql_url(self) -> str:
        return URL.create(
            "mssql+pyodbc",
            username=self.mssql_user,
            password=self.mssql_password,
            host=self.mssql_host,
            port=self.mssql_port,
            database=self.mssql_database,
            query={
                "driver": "ODBC Driver 18 for SQL Server",
                "TrustServerCertificate": "yes",
                "Encrypt": "no",
            },
        ).render_as_string(hide_password=False)

    @property
    def _kingbasees_url(self) -> str:
        # KingbaseES MSSQL Compatible 使用 PostgreSQL wire protocol
        # 连接后需设 autocommit=True 避免 PG Dialect 发送 BEGIN
        return URL.create(
            "postgresql+psycopg2",
            username=self.kingbasees_user,
            password=self.kingbasees_password,
            host=self.kingbasees_host,
            port=self.kingbasees_port,
            database=self.kingbasees_database,
            query={"options": "-c client_encoding=utf8"},
        ).render_as_string(hide_password=False)

    @property
    def _dm8_url(self) -> str:
        # DM8 官方 dmPython 驱动 + dmSQLAlchemy dialect
        return URL.create(
            "dm+dmPython",
            username=self.dm8_user,
            password=self.dm8_password,
            host=self.dm8_host,
            port=self.dm8_port,
            database=self.dm8_database,
        ).render_as_string(hide_password=False)

    # =========================================================================
    # 原始连接参数 (供绕过 SQLAlchemy Dialect 的原生驱动使用)
    # =========================================================================

    @property
    def raw_connection_kwargs(self) -> dict:
        """返回原生驱动的连接参数字典，用于绕过 SQLAlchemy Dialect 层。

        KingbaseES MSSQL 模式需要通过此方式连接（见调研报告）。
        """
        if self.active_db == "mssql":
            import urllib.parse
            return {
                "driver": "pyodbc",
                "connection_string": (
                    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                    f"SERVER={self.mssql_host},{self.mssql_port};"
                    f"DATABASE={self.mssql_database};"
                    f"UID={self.mssql_user};"
                    f"PWD={self.mssql_password};"
                    f"TrustServerCertificate=yes;Encrypt=no;"
                ),
            }
        elif self.active_db == "kingbasees":
            return {
                "driver": "psycopg2",
                "host": self.kingbasees_host,
                "port": self.kingbasees_port,
                "database": self.kingbasees_database,
                "user": self.kingbasees_user,
                "password": self.kingbasees_password,
                "options": "-c client_encoding=utf8",
                "connect_timeout": 10,
            }
        elif self.active_db == "dm8":
            return {
                "driver": "dmPython",
                "host": self.dm8_host,
                "port": self.dm8_port,
                "database": self.dm8_database,
                "user": self.dm8_user,
                "password": self.dm8_password,
            }
        raise ValueError(f"Unsupported active_db: {self.active_db}")


settings = Settings()
