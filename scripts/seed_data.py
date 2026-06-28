"""
Seed MSSQL with realistic ERP test data.

FK dependency order: customers → products → orders → order_items → inventory
All tables use explicit IDs via IDENTITY_INSERT for deterministic FK references.
"""

import sys
sys.path.insert(0, "src")

from app.core.database import get_raw_connection

conn = get_raw_connection("mssql")
cur = conn.cursor()

# ---- Clean existing data (reversed FK order) ----
cur.execute("DELETE FROM inventory")
cur.execute("DELETE FROM order_items")
cur.execute("DELETE FROM orders")
cur.execute("DELETE FROM products")
cur.execute("DELETE FROM customers")
# Reset identity counters
for t in ("customers", "products", "orders", "order_items", "inventory"):
    cur.execute(f"DBCC CHECKIDENT ('{t}', RESEED, 0)")
print("Cleaned all tables")

# =========================================================================
# 1. Customers (5条)
# =========================================================================
customers = [
    (1, "C001", "华为技术有限公司", "张三", "13800001001", "zhangsan@huawei.com", 1),
    (2, "C002", "阿里巴巴集团",     "李四", "13800001002", "lisi@alibaba-inc.com", 1),
    (3, "C003", "腾讯科技有限公司", "王五", "13800001003", "wangwu@tencent.com", 1),
    (4, "C004", "字节跳动",         "赵六", "13800001004", "zhaoliu@bytedance.com", 1),
    (5, "C005", "小米科技",         "孙七", "13800001005", "sunqi@xiaomi.com", 0),
]
cur.execute("SET IDENTITY_INSERT customers ON")
for cid, code, name, contact, phone, email, is_active in customers:
    cur.execute(
        "INSERT INTO customers (id, code, name, contact, phone, email, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, code, name, contact, phone, email, is_active),
    )
cur.execute("SET IDENTITY_INSERT customers OFF")
print(f"Inserted {len(customers)} customers")

# =========================================================================
# 2. Products (8条)
# =========================================================================
products = [
    (1, "P001", "高性能服务器 R740",   89999.00),
    (2, "P002", "云存储阵列 DS4800",  125000.00),
    (3, "P003", "万兆交换机 S6730",    15800.00),
    (4, "P004", "数据库一体机 D2000", 450000.00),
    (5, "P005", "UPS 不间断电源",      32000.00),
    (6, "P006", "光纤模块 SFP+",        1200.00),
    (7, "P007", "机架式 KVM 切换器",    4800.00),
    (8, "P008", "网络防火墙 USG6600",  68000.00),
]
cur.execute("SET IDENTITY_INSERT products ON")
for pid, code, name, price in products:
    cur.execute(
        "INSERT INTO products (id, code, name, price, is_active) VALUES (?, ?, ?, ?, 1)",
        (pid, code, name, price),
    )
cur.execute("SET IDENTITY_INSERT products OFF")
print(f"Inserted {len(products)} products")

# =========================================================================
# 3. Orders (8条)
# =========================================================================
orders = [
    (1, "ORD-000001", 1, "COMPLETED",  102499.00, 2, "服务器采购订单"),
    (2, "ORD-000002", 2, "COMPLETED",  450000.00, 1, "数据库一体机项目"),
    (3, "ORD-000003", 3, "PENDING",    173600.00, 3, None),
    (4, "ORD-000004", 1, "COMPLETED",   32000.00, 1, "UPS 备件"),
    (5, "ORD-000005", 4, "PROCESSING",  69600.00, 2, "防火墙+交换机"),
    (6, "ORD-000006", 2, "PENDING",    125000.00, 1, None),
    (7, "ORD-000007", 3, "CANCELLED",   15800.00, 1, "客户取消"),
    (8, "ORD-000008", 1, "PROCESSING", 141000.00, 3, "季度采购计划"),
]
cur.execute("SET IDENTITY_INSERT orders ON")
for oid, order_no, cust_id, status, amount, item_count, notes in orders:
    cur.execute(
        "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (oid, order_no, cust_id, status, amount, item_count, notes),
    )
cur.execute("SET IDENTITY_INSERT orders OFF")
print(f"Inserted {len(orders)} orders")

# =========================================================================
# 4. Order Items (16条)
# =========================================================================
order_items = [
    # Order 1: R740 + DS4800
    (1, 1, 1, 1, 89999.00,  89999.00),
    (2, 1, 2, 1, 125000.00, 125000.00),
    # Order 2: D2000
    (3, 2, 4, 1, 450000.00, 450000.00),
    # Order 3: S6730×2 + SFP+×20 + KVM
    (4, 3, 3, 2,  15800.00,  31600.00),
    (5, 3, 6, 20, 1200.00,   24000.00),
    (6, 3, 7, 1,  4800.00,    4800.00),
    # Order 4: UPS
    (7, 4, 5, 1, 32000.00, 32000.00),
    # Order 5: USG6600 + S6730
    (8, 5, 8, 1, 68000.00, 68000.00),
    (9, 5, 3, 1, 15800.00, 15800.00),
    # Order 6: DS4800
    (10, 6, 2, 1, 125000.00, 125000.00),
    # Order 7: S6730 (CANCELLED)
    (11, 7, 3, 1, 15800.00, 15800.00),
    # Order 8: R740 + USG6600 + SFP+×10
    (12, 8, 1, 1,  89999.00, 89999.00),
    (13, 8, 8, 1,  68000.00, 68000.00),
    (14, 8, 6, 10, 1200.00,  12000.00),
]
cur.execute("SET IDENTITY_INSERT order_items ON")
for iid, oid, pid, qty, price, subtotal in order_items:
    cur.execute(
        "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (iid, oid, pid, qty, price, subtotal),
    )
cur.execute("SET IDENTITY_INSERT order_items OFF")
print(f"Inserted {len(order_items)} order_items")

# =========================================================================
# 5. Inventory (8条) — one per product
# =========================================================================
inventory = [
    (1, "MAIN", 45, 10),
    (2, "MAIN", 12,  5),
    (3, "MAIN", 80, 20),
    (4, "MAIN",  3,  1),
    (5, "MAIN", 25,  5),
    (6, "SH",  200, 50),
    (7, "MAIN", 15,  5),
    (8, "MAIN",  8,  2),
]
for pid, warehouse, qty, min_qty in inventory:
    cur.execute(
        "INSERT INTO inventory (product_id, warehouse, quantity, min_quantity) "
        "VALUES (?, ?, ?, ?)",
        (pid, warehouse, qty, min_qty),
    )
print(f"Inserted {len(inventory)} inventory records")

conn.commit()
conn.close()
print("\n✅ Seed complete! 5 customers + 8 products + 8 orders + 14 order_items + 8 inventory")
