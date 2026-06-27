"""
FastAPI 应用入口 — SQL Demo 可视化执行平台。

启动方式:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

架构:
    Browser → FastAPI Router → Service → Executor → DB Driver → Database
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sql_demo.compare_router import router as sql_compare_router
from app.api.sql_demo.router import router as sql_demo_router

app = FastAPI(
    title="SQL Demo — Multi-Database Execution Platform",
    description=(
        "统一 SQL 执行平台，支持 MSSQL / KingbaseES MSSQL Compatible / DM8 "
        "三种数据库的查询操作。提供 Web UI 和 REST API。"
    ),
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS — 允许前端本地开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(sql_demo_router)
app.include_router(sql_compare_router)


@app.get("/api/health", tags=["health"])
def health_check():
    """健康检查端点。返回所有可用数据库类型。"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "available_dbs": ["mssql", "kingbasees", "dm8"],
    }
