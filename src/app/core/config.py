"""
配置中心 — 通过 APP_ACTIVE_DB 切换目标数据库。

Phase 1 约束:
- 不做任何兼容层抽象
- 仅返回 SQLAlchemy 连接 URL
- 各数据库差异由测试自行发现

环境文件优先级: .env < .env.local（后者覆盖前者）
密码安全: 使用 sqlalchemy.engine.URL.create() 而非 f-string 拼接，
          自动处理 @ # / : 等特殊字符。
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

    # ---- MSSQL ----
    mssql_host: str = "localhost"
    mssql_port: int = 1433
    mssql_database: str = "demo_db"
    mssql_user: str = "sa"
    mssql_password: str = ""

    # ---- KingbaseES (PostgreSQL 协议兼容) ----
    kingbasees_host: str = "localhost"
    kingbasees_port: int = 54321
    kingbasees_database: str = "demo_db"
    kingbasees_user: str = "system"
    kingbasees_password: str = ""

    # ---- DM8 (达梦) ----
    dm8_host: str = "localhost"
    dm8_port: int = 5236
    dm8_database: str = "demo_db"
    dm8_user: str = "SYSDBA"
    dm8_password: str = ""

    # ---- URL 生成 (使用 SQLAlchemy URL.create 防特殊字符) ----

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
        # KingbaseES 使用 PostgreSQL 协议 — 直接用 psycopg2 驱动
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
        # DM8 官方 dmPython 驱动
        return URL.create(
            "dm+dmPython",
            username=self.dm8_user,
            password=self.dm8_password,
            host=self.dm8_host,
            port=self.dm8_port,
            database=self.dm8_database,
        ).render_as_string(hide_password=False)


settings = Settings()
