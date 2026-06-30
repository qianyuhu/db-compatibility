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
from app.api.sql_compare.rewrite.rewrite_router import router as sql_rewrite_router
from app.api.sql_compare.score_router import router as sql_score_router
from app.api.sql_diagnostics.diagnose_router import router as sql_diagnostics_router
from app.api.sql_migration.migration_router import router as sql_migration_router
from app.api.sql_simulation.simulation_router import router as sql_simulation_router
from app.core.sql_kernel.kernel_router import router as sql_kernel_router
from app.api.business.order_router import router as business_order_router
from app.api.business.inventory_router import router as business_inventory_router
from app.api.business.migration_router import router as business_migration_router
from app.api.business.customer_router import router as business_customer_router
from app.api.business.product_router import router as business_product_router
from app.api.business.report_router import router as business_report_router
from app.api.business.sandbox_router import router as sandbox_router
from app.api.sql_compat.compat_router import router as sql_compat_router
from app.api.showcase_router import router as showcase_router

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
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(sql_demo_router)
app.include_router(sql_compare_router)
app.include_router(sql_score_router)
app.include_router(sql_rewrite_router)
app.include_router(sql_diagnostics_router)
app.include_router(sql_migration_router)
app.include_router(sql_simulation_router)
app.include_router(sql_kernel_router)
app.include_router(business_order_router)
app.include_router(business_inventory_router)
app.include_router(business_migration_router)
app.include_router(business_customer_router)
app.include_router(business_product_router)
app.include_router(business_report_router)
app.include_router(sandbox_router)
app.include_router(sql_compat_router)
app.include_router(showcase_router)


@app.get("/api/health", tags=["health"])
def health_check():
    """健康检查端点。返回所有可用数据库类型。"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "available_dbs": ["mssql", "kingbasees", "dm8"],
    }
