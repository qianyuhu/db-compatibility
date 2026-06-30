"""
Sandbox Fixed Dataset — deterministic, identical across all target databases.

Design:
- Small dataset (10 customers, 10 products, 20 orders, ~40 order_items, 10 inventory)
- All IDs are deterministic (no auto-generation dependency)
- Covers edge cases: NULL values, boundary prices, mixed statuses
- Used as the ground truth for migration validation

Tables (FK dependency order):
    customers → products → orders → order_items → inventory
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# =========================================================================
# Fixed timestamps (deterministic, same across all DBs)
# =========================================================================

FIXED_NOW = datetime(2025, 1, 15, 10, 30, 0)


# =========================================================================
# Customers (10 rows)
# =========================================================================

@dataclass(frozen=True)
class SandboxCustomer:
    id: int
    code: str
    name: str
    contact: str | None
    phone: str | None
    email: str | None
    is_active: bool


SANDBOX_CUSTOMERS: list[SandboxCustomer] = [
    SandboxCustomer(1, "C001", "华为技术有限公司", "赵伟", "13800000001", "c001@huawei.com", True),
    SandboxCustomer(2, "C002", "阿里巴巴科技有限公司", "钱芳", "13800000002", "c002@alibaba.com", True),
    SandboxCustomer(3, "C003", "腾讯科技股份有限公司", "孙娜", "13800000003", "c003@tencent.com", True),
    SandboxCustomer(4, "C004", "字节跳动网络技术有限公司", "李敏", "13800000004", "c004@bytedance.com", True),
    SandboxCustomer(5, "C005", "小米科技有限公司", "周静", "13800000005", "c005@xiaomi.com", True),
    SandboxCustomer(6, "C006", "百度在线网络技术有限公司", "吴丽", "13800000006", "c006@baidu.com", False),  # inactive
    SandboxCustomer(7, "C007", "京东集团有限公司", "郑强", "13800000007", "c007@jd.com", True),
    SandboxCustomer(8, "C008", "美团科技有限公司", "王磊", "13800000008", "c008@meituan.com", True),
    SandboxCustomer(9, "C009", "网易杭州有限公司", "冯洋", None, None, True),  # NULL contact/phone/email
    SandboxCustomer(10, "C010", "滴滴出行科技有限公司", "陈勇", "13800000010", "c010@didi.com", True),
]


# =========================================================================
# Products (10 rows)
# =========================================================================

@dataclass(frozen=True)
class SandboxProduct:
    id: int
    code: str
    name: str
    price: float
    is_active: bool


SANDBOX_PRODUCTS: list[SandboxProduct] = [
    SandboxProduct(1, "P001", "高性能服务器 R740", 89999.00, True),
    SandboxProduct(2, "P002", "云存储阵列 DS4800", 125000.00, True),
    SandboxProduct(3, "P003", "万兆交换机 S6730", 15800.00, True),
    SandboxProduct(4, "P004", "数据库一体机 D2000", 450000.00, True),
    SandboxProduct(5, "P005", "UPS 不间断电源", 32000.00, True),
    SandboxProduct(6, "P006", "光纤模块 SFP+", 1200.00, False),  # inactive product
    SandboxProduct(7, "P007", "机架式 KVM 切换器", 4800.00, True),
    SandboxProduct(8, "P008", "网络防火墙 USG6600", 68000.00, True),
    SandboxProduct(9, "P009", "负载均衡器 F5 BIG-IP", 188000.00, True),
    SandboxProduct(10, "P010", "全闪存阵列 AF260", 320000.00, True),
]


# =========================================================================
# Orders (20 rows) + Order Items (~40 rows)
# =========================================================================

@dataclass(frozen=True)
class SandboxOrder:
    id: int
    order_no: str
    customer_id: int
    status: str  # COMPLETED / PENDING / PROCESSING / CANCELLED
    total_amount: float
    item_count: int
    notes: str | None


@dataclass(frozen=True)
class SandboxOrderItem:
    id: int
    order_id: int
    product_id: int
    quantity: int
    unit_price: float
    subtotal: float


SANDBOX_ORDERS: list[SandboxOrder] = [
    # id, order_no, customer_id, status, total_amount, item_count, notes
    SandboxOrder(1, "ORD-000001", 1, "COMPLETED", 89999.00, 1, "服务器采购订单"),
    SandboxOrder(2, "ORD-000002", 2, "COMPLETED", 140800.00, 2, "交换机+防火墙采购"),
    SandboxOrder(3, "ORD-000003", 3, "PENDING", 450000.00, 1, "数据库一体机项目"),
    SandboxOrder(4, "ORD-000004", 4, "COMPLETED", 320000.00, 1, "全闪存阵列采购"),
    SandboxOrder(5, "ORD-000005", 5, "PROCESSING", 35200.00, 2, "UPS+光纤模块采购"),
    SandboxOrder(6, "ORD-000006", 1, "COMPLETED", 188000.00, 1, "负载均衡器部署"),
    SandboxOrder(7, "ORD-000007", 7, "PENDING", 125000.00, 1, "存储扩容项目"),
    SandboxOrder(8, "ORD-000008", 8, "COMPLETED", 324800.00, 2, "服务器+交换机采购"),
    SandboxOrder(9, "ORD-000009", 9, "CANCELLED", 450000.00, 1, "数据库一体机(已取消)"),
    SandboxOrder(10, "ORD-000010", 10, "COMPLETED", 32000.00, 1, "UPS备件采购"),
    SandboxOrder(11, "ORD-000011", 2, "PROCESSING", 99099.00, 3, None),  # NULL notes
    SandboxOrder(12, "ORD-000012", 3, "COMPLETED", 15800.00, 1, "交换机补充"),
    SandboxOrder(13, "ORD-000013", 4, "PENDING", 508800.00, 2, "服务器+存储采购"),
    SandboxOrder(14, "ORD-000014", 5, "COMPLETED", 68000.00, 1, "防火墙升级"),
    SandboxOrder(15, "ORD-000015", 6, "CANCELLED", 1200.00, 1, None),  # inactive customer
    SandboxOrder(16, "ORD-000016", 7, "COMPLETED", 4800.00, 1, "KVM切换器"),
    SandboxOrder(17, "ORD-000017", 8, "PROCESSING", 320000.00, 1, "存储阵列扩容"),
    SandboxOrder(18, "ORD-000018", 9, "COMPLETED", 202800.00, 2, "负载均衡+交换机"),
    SandboxOrder(19, "ORD-000019", 10, "PENDING", 188000.00, 1, "负载均衡器采购"),
    SandboxOrder(20, "ORD-000020", 1, "COMPLETED", 125000.00, 1, "存储设备采购"),
]

SANDBOX_ORDER_ITEMS: list[SandboxOrderItem] = [
    # id, order_id, product_id, quantity, unit_price, subtotal
    # Order 1: 1 item
    SandboxOrderItem(1, 1, 1, 1, 89999.00, 89999.00),
    # Order 2: 2 items
    SandboxOrderItem(2, 2, 3, 1, 15800.00, 15800.00),
    SandboxOrderItem(3, 2, 8, 1, 125000.00, 125000.00),  # note: different unit_price from P008 (68000)
    # Order 3: 1 item
    SandboxOrderItem(4, 3, 4, 1, 450000.00, 450000.00),
    # Order 4: 1 item
    SandboxOrderItem(5, 4, 10, 1, 320000.00, 320000.00),
    # Order 5: 2 items
    SandboxOrderItem(6, 5, 5, 1, 32000.00, 32000.00),
    SandboxOrderItem(7, 5, 6, 1, 3200.00, 3200.00),  # note: different unit_price from P006 (1200)
    # Order 6: 1 item
    SandboxOrderItem(8, 6, 9, 1, 188000.00, 188000.00),
    # Order 7: 1 item
    SandboxOrderItem(9, 7, 2, 1, 125000.00, 125000.00),
    # Order 8: 2 items
    SandboxOrderItem(10, 8, 1, 1, 89999.00, 89999.00),
    SandboxOrderItem(11, 8, 3, 2, 15800.00, 31600.00),
    # Order 9: 1 item (CANCELLED)
    SandboxOrderItem(12, 9, 4, 1, 450000.00, 450000.00),
    # Order 10: 1 item
    SandboxOrderItem(13, 10, 5, 1, 32000.00, 32000.00),
    # Order 11: 3 items, NULL notes
    SandboxOrderItem(14, 11, 1, 1, 89999.00, 89999.00),
    SandboxOrderItem(15, 11, 7, 1, 4800.00, 4800.00),
    SandboxOrderItem(16, 11, 8, 1, 4300.00, 4300.00),  # different unit_price
    # Order 12: 1 item
    SandboxOrderItem(17, 12, 3, 1, 15800.00, 15800.00),
    # Order 13: 2 items
    SandboxOrderItem(18, 13, 1, 1, 89999.00, 89999.00),
    SandboxOrderItem(19, 13, 2, 1, 418801.00, 418801.00),  # different from P002 price (125000)
    # Order 14: 1 item
    SandboxOrderItem(20, 14, 8, 1, 68000.00, 68000.00),
    # Order 15: 1 item (CANCELLED, inactive customer)
    SandboxOrderItem(21, 15, 6, 1, 1200.00, 1200.00),
    # Order 16: 1 item
    SandboxOrderItem(22, 16, 7, 1, 4800.00, 4800.00),
    # Order 17: 1 item
    SandboxOrderItem(23, 17, 10, 1, 320000.00, 320000.00),
    # Order 18: 2 items
    SandboxOrderItem(24, 18, 9, 1, 188000.00, 188000.00),
    SandboxOrderItem(25, 18, 3, 1, 14800.00, 14800.00),  # slightly different from P003 price
    # Order 19: 1 item
    SandboxOrderItem(26, 19, 9, 1, 188000.00, 188000.00),
    # Order 20: 1 item
    SandboxOrderItem(27, 20, 2, 1, 125000.00, 125000.00),
]


# =========================================================================
# Inventory (10 rows — one per product)
# =========================================================================

@dataclass(frozen=True)
class SandboxInventory:
    id: int
    product_id: int
    warehouse: str
    quantity: int
    min_quantity: int


SANDBOX_INVENTORY: list[SandboxInventory] = [
    # id, product_id, warehouse, quantity, min_quantity
    SandboxInventory(1, 1, "MAIN", 50, 5),
    SandboxInventory(2, 2, "MAIN", 20, 3),
    SandboxInventory(3, 3, "SH", 100, 10),
    SandboxInventory(4, 4, "BJ", 5, 2),       # low stock
    SandboxInventory(5, 5, "MAIN", 30, 5),
    SandboxInventory(6, 6, "GZ", 200, 20),
    SandboxInventory(7, 7, "SH", 45, 5),
    SandboxInventory(8, 8, "BJ", 15, 3),
    SandboxInventory(9, 9, "MAIN", 8, 2),
    SandboxInventory(10, 10, "CD", 3, 5),      # below min (low stock alert)
]


# =========================================================================
# Full dataset container
# =========================================================================

@dataclass(frozen=True)
class SandboxDataset:
    """Complete fixed dataset for migration testing."""
    customers: list[SandboxCustomer] = field(default_factory=lambda: list(SANDBOX_CUSTOMERS))
    products: list[SandboxProduct] = field(default_factory=lambda: list(SANDBOX_PRODUCTS))
    orders: list[SandboxOrder] = field(default_factory=lambda: list(SANDBOX_ORDERS))
    order_items: list[SandboxOrderItem] = field(default_factory=lambda: list(SANDBOX_ORDER_ITEMS))
    inventory: list[SandboxInventory] = field(default_factory=lambda: list(SANDBOX_INVENTORY))

    @property
    def table_names(self) -> list[str]:
        """FK dependency order for clean/reset operations."""
        return ["inventory", "order_items", "orders", "products", "customers"]

    @property
    def row_counts(self) -> dict[str, int]:
        """Expected row counts for verification."""
        return {
            "customers": len(self.customers),
            "products": len(self.products),
            "orders": len(self.orders),
            "order_items": len(self.order_items),
            "inventory": len(self.inventory),
        }


# Singleton
SANDBOX_DATASET = SandboxDataset()
