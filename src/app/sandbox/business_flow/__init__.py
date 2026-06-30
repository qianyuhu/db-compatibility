"""
Business Flow Registry — structured definitions of end-to-end business flows.

Each flow represents a complete API → ORM → SQL → DB → Verify chain.
These definitions feed into the CoverageAnalyzer's business_flow dimension
and serve as the specification for Business Flow Test Cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessFlowStep:
    """A single step in a business flow chain."""
    id: str
    description: str
    layer: str  # "api" / "orm" / "sql" / "db" / "verify"


@dataclass(frozen=True)
class BusinessFlow:
    """A complete end-to-end business flow.

    Each flow has 5 steps representing the full chain:
      API → ORM → SQL → DB Validation → Reverse Verification
    """
    id: str
    name: str
    steps: list[BusinessFlowStep]


# =========================================================================
# Predefined Business Flows
# =========================================================================

BUSINESS_FLOWS: dict[str, BusinessFlow] = {
    "create": BusinessFlow(
        id="create",
        name="Create Flow (创建流程)",
        steps=[
            BusinessFlowStep("create_api", "API 创建调用 (POST)", "api"),
            BusinessFlowStep("create_orm", "ORM 模型创建 (Repository.create)", "orm"),
            BusinessFlowStep("create_sql", "INSERT 语句执行", "sql"),
            BusinessFlowStep("create_validate", "SELECT 计数验证 (行数正确)", "db"),
            BusinessFlowStep("create_reverse_verify", "目标库反向查询验证", "verify"),
        ],
    ),
    "update": BusinessFlow(
        id="update",
        name="Update Flow (更新流程)",
        steps=[
            BusinessFlowStep("update_api", "API 更新调用 (PUT)", "api"),
            BusinessFlowStep("update_orm", "ORM 模型更新 (Repository.update)", "orm"),
            BusinessFlowStep("update_sql", "UPDATE 语句执行", "sql"),
            BusinessFlowStep("update_validate", "SELECT 值验证 (数据正确)", "db"),
            BusinessFlowStep("update_reverse_verify", "目标库反向查询验证", "verify"),
        ],
    ),
    "delete": BusinessFlow(
        id="delete",
        name="Delete Flow (删除流程)",
        steps=[
            BusinessFlowStep("delete_api", "API 删除调用 (DELETE)", "api"),
            BusinessFlowStep("delete_orm", "ORM 模型删除 (Repository.delete)", "orm"),
            BusinessFlowStep("delete_sql", "DELETE 语句执行", "sql"),
            BusinessFlowStep("delete_validate", "SELECT 计数验证 (行为一致)", "db"),
            BusinessFlowStep("delete_reverse_verify", "目标库反向查询验证", "verify"),
        ],
    ),
    "inventory": BusinessFlow(
        id="inventory",
        name="Inventory Flow (库存流程)",
        steps=[
            BusinessFlowStep("inventory_api", "API 库存查询", "api"),
            BusinessFlowStep("inventory_orm", "ORM 库存查询 (InventoryRepository)", "orm"),
            BusinessFlowStep("inventory_sql", "SELECT FROM inventory", "sql"),
            BusinessFlowStep("inventory_alert", "低库存阈值检查 (quantity < min)", "db"),
            BusinessFlowStep("inventory_reverse_verify", "目标库反向查询验证", "verify"),
        ],
    ),
    "order": BusinessFlow(
        id="order",
        name="Order Flow (订单流程 / 多表关联)",
        steps=[
            BusinessFlowStep("order_api", "API 订单创建 (含明细)", "api"),
            BusinessFlowStep("order_orm", "ORM 订单+明细创建 (Transaction)", "orm"),
            BusinessFlowStep("order_sql", "INSERT orders + order_items", "sql"),
            BusinessFlowStep("order_join", "多表 JOIN 验证 (4表关联)", "db"),
            BusinessFlowStep("order_reverse_verify", "目标库 JOIN 反向验证", "verify"),
        ],
    ),
}


# =========================================================================
# Coverage measurement helpers
# =========================================================================

def total_flow_steps() -> int:
    """Return total number of required business flow steps."""
    return sum(len(flow.steps) for flow in BUSINESS_FLOWS.values())


def all_step_ids() -> list[str]:
    """Return all business flow step IDs."""
    step_ids: list[str] = []
    for flow in BUSINESS_FLOWS.values():
        for step in flow.steps:
            step_ids.append(step.id)
    return step_ids


def flow_summary() -> dict[str, int]:
    """Return per-flow step counts."""
    return {flow_id: len(flow.steps) for flow_id, flow in BUSINESS_FLOWS.items()}
