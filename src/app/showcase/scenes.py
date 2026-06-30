"""
Showcase Scene Definitions — pre-defined demo scenes for the Migration Capability Showcase.

Each scene demonstrates one specific migration capability with visual
side-by-side results across MSSQL, KingbaseES, and DM8.

Design:
    - Scenes are frozen dataclasses (immutable, deterministic)
    - Each scene contains the SQL/API/ORM operation + metadata + insights
    - SQL scenes: exact SQL to execute across all 3 DBs
    - API scenes: operation definition (engine fills in execution details)
    - ORM scenes: model + operation (engine generates dialect-specific SQL)

This is a SHOWCASE (可视化演示), NOT a test system.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# =========================================================================
# Scene type enumeration
# =========================================================================

SCENE_TYPE_SQL = "SQL"
SCENE_TYPE_API = "API"
SCENE_TYPE_ORM = "ORM"


# =========================================================================
# ShowcaseScene dataclass
# =========================================================================

@dataclass(frozen=True)
class ShowcaseScene:
    """A single demo scene in the Migration Capability Showcase.

    Attributes:
        id: Unique scene identifier (e.g. "sql_case_when")
        name: Display name in Chinese
        type: "SQL" | "API" | "ORM"
        description: What this scene demonstrates (Chinese)
        category: Sub-category for grouping
        sql: SQL to execute (SQL scenes only, None for API/ORM)
        setup_sql: Optional SQL to run before the main SQL (e.g. CREATE TABLE)
        cleanup_sql: Optional SQL to run after (e.g. DROP TABLE)
        api_operation: Operation name for API scenes
        api_endpoint: API endpoint path for API scenes
        api_method: HTTP method for API scenes
        orm_model: SQLAlchemy model name for ORM scenes
        orm_operation: Operation type for ORM scenes (bulk_insert, batch_update, delete)
        migration_insight: What this scene teaches about migration (Chinese)
        key_differences: Known behavioral differences across DBs
        tags: Categorization tags
    """

    id: str
    name: str
    type: str  # SCENE_TYPE_SQL | SCENE_TYPE_API | SCENE_TYPE_ORM
    description: str
    category: str = ""
    sql: str | None = None
    sql_overrides: dict[str, str] = field(default_factory=dict)
    setup_sql: str | None = None
    cleanup_sql: str | None = None
    api_operation: str | None = None
    api_endpoint: str | None = None
    api_method: str = "POST"
    orm_model: str | None = None
    orm_operation: str | None = None
    migration_insight: str = ""
    key_differences: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize scene metadata for API response (no execution data)."""
        return {
            "scene_id": self.id,
            "scene_name": self.name,
            "type": self.type,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "migration_insight": self.migration_insight,
            "key_differences": self.key_differences,
        }


# =========================================================================
# SQL Scenes (3)
# =========================================================================

SCENE_SQL_CASE_WHEN = ShowcaseScene(
    id="sql_case_when",
    name="订单等级计算 (Order Level Classification)",
    type=SCENE_TYPE_SQL,
    description="使用 CASE WHEN 对订单按金额进行客户等级分层，验证三库语法一致性",
    category="case_when",
    sql="""SELECT
    id,
    order_no,
    customer_id,
    total_amount,
    CASE
        WHEN total_amount > 100000 THEN 'VIP'
        WHEN total_amount > 10000 THEN 'PREMIUM'
        ELSE 'NORMAL'
    END AS customer_level
FROM orders
ORDER BY total_amount DESC""",
    migration_insight=(
        "CASE WHEN 是 SQL:2003 标准语法，在 MSSQL、KingbaseES、DM8 三库中完全一致。"
        "无需任何改写即可迁移。分支条件支持嵌套，各库行为无差异。"
    ),
    key_differences=[],
    tags=["CASE WHEN", "条件表达式", "业务分层", "标准SQL"],
)

SCENE_SQL_INSERT_SELECT = ShowcaseScene(
    id="sql_insert_select",
    name="订单汇总表生成 (Order Summary Generation)",
    type=SCENE_TYPE_SQL,
    description="使用 INSERT SELECT 从订单表汇总数据到汇总表，展示三库数据迁移行为",
    category="insert_select",
    setup_sql="""-- 创建订单汇总表（如已存在则跳过）
BEGIN TRY
    CREATE TABLE order_summary (
        customer_id INT PRIMARY KEY,
        total_spent DECIMAL(12, 2),
        order_count INT,
        avg_amount DECIMAL(12, 2)
    );
END TRY
BEGIN CATCH
    -- 表已存在，忽略
END CATCH""",
    sql="""INSERT INTO order_summary (customer_id, total_spent, order_count, avg_amount)
SELECT
    customer_id,
    SUM(total_amount) AS total_spent,
    COUNT(*) AS order_count,
    AVG(total_amount) AS avg_amount
FROM orders
GROUP BY customer_id
ORDER BY customer_id""",
    cleanup_sql="DROP TABLE IF EXISTS order_summary",
    migration_insight=(
        "INSERT SELECT 是标准 SQL，三库均支持。但需要注意：\n"
        "1. MSSQL 需要 SET IDENTITY_INSERT ON（如果目标表有 IDENTITY 列）\n"
        "2. KingbaseES 使用序列管理自增，不冲突\n"
        "3. DM8 的 IDENTITY 列在显式插入时需特殊处理\n"
        "4. 数值精度（DECIMAL）在三库中可能略有差异，建议统一使用 ROUND()"
    ),
    key_differences=[
        "IDENTITY/序列处理方式不同",
        "DECIMAL 聚合精度可能略有差异",
    ],
    tags=["INSERT SELECT", "数据汇总", "表迁移", "聚合函数"],
)

SCENE_SQL_BATCH_INSERT = ShowcaseScene(
    id="sql_batch_insert",
    name="批量客户导入 (Batch Customer Import)",
    type=SCENE_TYPE_SQL,
    description="使用多行 VALUES 批量插入客户数据，展示三库批量写入行为差异",
    category="batch_insert",
    setup_sql="""-- 清理测试数据
DELETE FROM customers WHERE code IN ('B101', 'B102', 'B103') OR id IN (901, 902, 903)""",
    sql="""INSERT INTO customers (code, name, contact, phone, email, is_active, created_at)
VALUES
    ('B101', '批量测试客户A', '张三', '13800000101', 'b101@test.com', 1, '2025-01-15 10:30:00'),
    ('B102', '批量测试客户B', '李四', '13800000102', 'b102@test.com', 1, '2025-01-15 10:30:00'),
    ('B103', '批量测试客户C', '王五', '13800000103', 'b103@test.com', 0, '2025-01-15 10:30:00')""",
    sql_overrides={
        "kingbasees": (
            "INSERT INTO customers (id, code, name, contact, phone, email, is_active, created_at)\n"
            "VALUES\n"
            "    (901, 'B101', '批量测试客户A', '张三', '13800000101', 'b101@test.com', 1, '2025-01-15 10:30:00'),\n"
            "    (902, 'B102', '批量测试客户B', '李四', '13800000102', 'b102@test.com', 1, '2025-01-15 10:30:00'),\n"
            "    (903, 'B103', '批量测试客户C', '王五', '13800000103', 'b103@test.com', 0, '2025-01-15 10:30:00')"
        ),
    },
    cleanup_sql="DELETE FROM customers WHERE code IN ('B101', 'B102', 'B103') OR id IN (901, 902, 903)",
    migration_insight=(
        "多行 VALUES 批量插入在三库中语法一致，但行为有细微差异：\n"
        "1. MSSQL：需要在批量插入前 SET IDENTITY_INSERT ON；最多 1000 行/批次\n"
        "2. KingbaseES：序列自动递增，显式指定 ID 后需 ALTER SEQUENCE RESTART\n"
        "3. DM8：显式 ID 插入后，IDENTITY 种子不会自动更新\n"
        "迁移建议：使用 ORM 的 bulk_insert 或手动管理序列/IDENTITY"
    ),
    key_differences=[
        "IDENTITY 列插入行为（MSSQL 需 IDENTITY_INSERT）",
        "自增种子更新策略不同",
        "KingbaseES 序列不会因显式 ID 而自动更新",
    ],
    tags=["BATCH INSERT", "批量写入", "VALUES", "IDENTITY", "序列"],
)


# =========================================================================
# API Scenes (3)
# =========================================================================

SCENE_API_CUSTOMER_LIST = ShowcaseScene(
    id="api_customer_list",
    name="客户列表跨库一致性查询 (Customer List Cross-DB)",
    type=SCENE_TYPE_API,
    description="通过 API 查询客户列表，对比三库返回的 JSON 结构、行数和排序一致性",
    category="customer_list",
    api_operation="list_customers",
    api_endpoint="/api/business/customers/list",
    api_method="POST",
    migration_insight=(
        "客户列表查询是最常见的 API 场景。迁移验证应关注：\n"
        "1. 返回行数三库一致（基础）\n"
        "2. JSON 字段名和类型一致（列映射）\n"
        "3. 排序行为一致（ORDER BY 在不同字符集下的行为）\n"
        "4. NULL 值序列化一致（null vs 空字符串）\n"
        "5. 响应时间在可接受范围内"
    ),
    key_differences=[
        "中文字符排序规则可能不同（MSSQL: Chinese_PRC_CI_AS, KingbaseES: zh_CN.UTF-8）",
        "NULL 排序位置（MSSQL: NULL 最小, PG: NULL 最大）",
        "布尔值序列化（MSSQL: 1/0, KingbaseES: true/false, DM8: 1/0）",
    ],
    tags=["API", "客户查询", "JSON对比", "排序一致性"],
)

SCENE_API_INVENTORY_ADJUST = ShowcaseScene(
    id="api_inventory_adjust",
    name="库存变更模拟 (Inventory Adjustment Simulation)",
    type=SCENE_TYPE_API,
    description="模拟库存变更流程：API → ORM → DB UPDATE → SELECT 验证，展示三库同步结果",
    category="inventory_adjust",
    api_operation="adjust_stock",
    api_endpoint="/api/business/inventory/adjust",
    api_method="POST",
    migration_insight=(
        "库存变更涉及 UPDATE + 验证 SELECT，是典型的写操作迁移场景：\n"
        "1. 事务行为：MSSQL 默认 READ COMMITTED，KingbaseES/DM8 默认 READ COMMITTED\n"
        "2. 行级锁：三库均支持行级锁，但锁升级策略不同\n"
        "3. 受影响行数：UPDATE 返回的 rowcount 含义一致\n"
        "4. 验证查询：SELECT 结果应完全一致（数值精度除外）\n"
        "迁移建议：业务操作后始终执行验证 SELECT，确保数据一致性"
    ),
    key_differences=[
        "事务隔离级别默认值可能不同",
        "锁升级策略差异（MSSQL 可能升级为页锁）",
        "UPDATE 并发行为在高负载下可能不同",
    ],
    tags=["API", "库存变更", "UPDATE", "事务", "写操作验证"],
)

SCENE_API_MIGRATION_RUN = ShowcaseScene(
    id="api_migration_run",
    name="一键迁移执行 (One-Click Migration Pipeline)",
    type=SCENE_TYPE_API,
    description="执行完整的 Schema → Data → Validation → Report 迁移流水线，展示各阶段结果",
    category="migration_run",
    api_operation="run_migration",
    api_endpoint="/api/business/migrate/run",
    api_method="POST",
    migration_insight=(
        "迁移流水线是迁移项目的核心操作，分四个阶段：\n"
        "1. Schema 迁移：DDL 从源库提取 → 方言改写 → 目标库执行\n"
        "2. Data 迁移：逐表批量复制，处理 IDENTITY/序列/类型映射\n"
        "3. Validation：行数 + 关键查询一致性校验\n"
        "4. Report：生成兼容性分数和差异报告\n"
        "关键风险点：DDL 方言差异（TIMESTAMP vs DATETIME2）、\n"
        "大表批量复制性能、约束（FK/UNIQUE）处理顺序。"
    ),
    key_differences=[
        "DDL 方言差异（TIMESTAMP, DATETIME2, TEXT vs CLOB）",
        "IDENTITY vs SEQUENCE 行为",
        "FK 约束在数据迁移时的处理",
        "大表批量复制的性能差异",
    ],
    tags=["API", "迁移流水线", "Pipeline", "Schema", "Data", "Validation"],
)


# =========================================================================
# ORM Scenes (3)
# =========================================================================

SCENE_ORM_BULK_INSERT = ShowcaseScene(
    id="orm_bulk_insert",
    name="客户批量导入 ORM 行为 (Bulk Insert via ORM)",
    type=SCENE_TYPE_ORM,
    description="使用 ORM 批量插入客户数据，展示三库的 ORM SQL 生成和执行行为差异",
    category="bulk_insert",
    orm_model="Customer",
    orm_operation="bulk_insert",
    migration_insight=(
        "ORM 批量插入在不同数据库上的行为差异：\n"
        "1. MSSQL：SQLAlchemy 生成 INSERT ... VALUES (...), (...)，配合 IDENTITY_INSERT\n"
        "2. KingbaseES：生成 INSERT ... VALUES (...), (...)，使用序列管理 ID\n"
        "3. DM8：dmSQLAlchemy 可能生成多行 INSERT 或逐行 INSERT（取决于配置）\n"
        "\n"
        "迁移要点：\n"
        "- SQLAlchemy 的 bulk_insert_mappings 跨方言可用\n"
        "- IDENTITY/序列回填行为不同（MSSQL 返回 SCOPE_IDENTITY，PG 返回 RETURNING）\n"
        "- 性能：逐行 INSERT（慢）vs 批量 INSERT（快），dmPython 走逐行模式\n"
        "- 事务回滚行为一致"
    ),
    key_differences=[
        "SQLAlchemy 方言生成 SQL 不同",
        "IDENTITY/SCOPE_IDENTITY vs RETURNING vs dmPython 逐行",
        "批量插入性能差异（MSSQL 最快，DM8 最慢）",
    ],
    tags=["ORM", "批量插入", "SQLAlchemy", "bulk_insert", "IDENTITY"],
)

SCENE_ORM_BATCH_UPDATE = ShowcaseScene(
    id="orm_batch_update",
    name="批量价格调整 (Batch Price Adjustment via ORM)",
    type=SCENE_TYPE_ORM,
    description="使用 ORM 批量更新产品价格，比较三库 UPDATE SQL 生成和执行结果",
    category="batch_update",
    orm_model="Product",
    orm_operation="batch_update",
    migration_insight=(
        "ORM 批量更新（bulk update）在三库上的差异：\n"
        "1. MSSQL：支持 UPDATE ... FROM 语法，SQLAlchemy 生成标准 UPDATE\n"
        "2. KingbaseES：支持 UPDATE ... FROM，与 PG 兼容\n"
        "3. DM8：支持标准 UPDATE，dmSQLAlchemy 方言处理类型转换\n"
        "\n"
        "迁移要点：\n"
        "- UPDATE 涉及 JOIN 时三库语法可能不同\n"
        "- 受影响行数（rowcount）返回值含义不同\n"
        "- NUMERIC 精度在更新后应验证 ROUND() 一致性"
    ),
    key_differences=[
        "UPDATE FROM 语法差异（MSSQL/KingbaseES 支持，DM8 有限制）",
        "受影响行数语义（匹配 vs 实际变更）",
        "NUMERIC 精度存储差异",
    ],
    tags=["ORM", "批量更新", "UPDATE", "SQLAlchemy", "价格调整"],
)

SCENE_ORM_DELETE = ShowcaseScene(
    id="orm_delete",
    name="客户删除行为对比 (Customer Delete Behavior)",
    type=SCENE_TYPE_ORM,
    description="使用 ORM 删除客户数据，展示三库 DELETE 行为、外键约束和软删除策略差异",
    category="delete",
    orm_model="Customer",
    orm_operation="delete",
    migration_insight=(
        "ORM 删除操作在三库上的行为差异：\n"
        "1. 硬删除（DELETE）：三库语法一致，但 FK CASCADE 行为可能不同\n"
        "2. 软删除（UPDATE is_active=0）：三库行为完全一致（推荐）\n"
        "3. TRUNCATE：MSSQL 支持，KingbaseES 支持，DM8 支持但语法略有差异\n"
        "\n"
        "迁移建议：\n"
        "- 生产环境推荐软删除（is_active=0），避免 FK 级联风险\n"
        "- 硬删除前检查 FK 约束定义（CASCADE vs RESTRICT）\n"
        "- DM8 的 DELETE 在有触发器时可能需要额外处理"
    ),
    key_differences=[
        "FK CASCADE 行为差异",
        "TRUNCATE vs DELETE 性能和语法",
        "触发器在 DELETE 上的行为差异",
        "软删除（is_active=0）三库完全一致（推荐方案）",
    ],
    tags=["ORM", "删除", "DELETE", "软删除", "FK约束", "CASCADE"],
)


# =========================================================================
# Scene collections
# =========================================================================

SQL_SCENES: list[ShowcaseScene] = [
    SCENE_SQL_CASE_WHEN,
    SCENE_SQL_INSERT_SELECT,
    SCENE_SQL_BATCH_INSERT,
]

API_SCENES: list[ShowcaseScene] = [
    SCENE_API_CUSTOMER_LIST,
    SCENE_API_INVENTORY_ADJUST,
    SCENE_API_MIGRATION_RUN,
]

ORM_SCENES: list[ShowcaseScene] = [
    SCENE_ORM_BULK_INSERT,
    SCENE_ORM_BATCH_UPDATE,
    SCENE_ORM_DELETE,
]

ALL_SCENES: list[ShowcaseScene] = SQL_SCENES + API_SCENES + ORM_SCENES


# =========================================================================
# Lookup helpers
# =========================================================================

_SCENE_BY_ID: dict[str, ShowcaseScene] = {s.id: s for s in ALL_SCENES}


def get_scene_by_id(scene_id: str) -> ShowcaseScene | None:
    """Look up a scene definition by its ID."""
    return _SCENE_BY_ID.get(scene_id)


def list_scenes_by_type(scene_type: str) -> list[ShowcaseScene]:
    """Filter scenes by type (SQL/API/ORM)."""
    return [s for s in ALL_SCENES if s.type == scene_type]
