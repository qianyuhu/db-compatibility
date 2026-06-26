"""
配置中心 — 通过 APP_ACTIVE_DB 切换目标数据库。

Phase 1 约束:
- 不做任何兼容层抽象
- 仅返回 SQLAlchemy 连接 URL
- 各数据库差异由测试自行发现
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "env_file": ".env",
        "env_prefix": "APP_",
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
        return (
            f"mssql+pyodbc://{self.mssql_user}:{self.mssql_password}"
            f"@{self.mssql_host}:{self.mssql_port}/{self.mssql_database}"
            "?driver=ODBC+Driver+18+for+SQL+Server"
            "&TrustServerCertificate=yes"
            "&Encrypt=no"
        )

    @property
    def _kingbasees_url(self) -> str:
        # KingbaseES 使用 PostgreSQL 协议 — 直接用 psycopg2 驱动
        return (
            f"postgresql+psycopg2://{self.kingbasees_user}:{self.kingbasees_password}"
            f"@{self.kingbasees_host}:{self.kingbasees_port}/{self.kingbasees_database}"
            "?options=-c+client_encoding=utf8"
        )

    @property
    def _dm8_url(self) -> str:
        # DM8 官方 dmPython 驱动
        return (
            f"dm+dmPython://{self.dm8_user}:{self.dm8_password}"
            f"@{self.dm8_host}:{self.dm8_port}/{self.dm8_database}"
        )


settings = Settings()
