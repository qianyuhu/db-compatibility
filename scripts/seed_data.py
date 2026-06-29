"""
Seed MSSQL with realistic ERP test data (1000+ 条).

清理 MSSQL + KingbaseES 的 demo_db，然后向 MSSQL 写入大量模拟数据。
FK 依赖顺序: customers → products → orders → order_items → inventory

中文编码注意:
- orders.notes 列为 String(500) → VARCHAR(500)，无法存储中文
- 脚本中先 ALTER 为 NVARCHAR(500) 再写入中文
- 连接串已配置 Charset=UTF-8，参数化查询自动处理 Unicode
"""

import random
import sys
sys.path.insert(0, "src")

from app.core.database import get_raw_connection
from app.core.config import settings

random.seed(42)  # 可重复的确定性数据

# =========================================================================
# 0. 清理 KingbaseES（如果可用）
# =========================================================================
def clean_kingbasees():
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=settings.kingbasees_host,
            port=settings.kingbasees_port,
            database=settings.kingbasees_database,
            user=settings.kingbasees_user,
            password=settings.kingbasees_password,
            options="-c client_encoding=utf8",
            connect_timeout=5,
        )
        conn.autocommit = True
        cur = conn.cursor()
        for t in ("inventory", "order_items", "orders", "products", "customers"):
            try:
                cur.execute(f"DELETE FROM {t}")
                print(f"  KingbaseES: cleaned {t}")
            except Exception as e:
                print(f"  KingbaseES: skip {t} ({e})")
                conn.rollback()
        cur.close()
        conn.close()
        print("✅ KingbaseES cleaned")
    except Exception as e:
        print(f"⚠️  KingbaseES not available: {e}")


# =========================================================================
# 1. 清理 MSSQL
# =========================================================================
conn = get_raw_connection("mssql")
cur = conn.cursor()

# ALTER orders.notes 为 NVARCHAR 以支持中文
try:
    cur.execute("ALTER TABLE orders ALTER COLUMN notes NVARCHAR(500)")
    conn.commit()
    print("✅ ALTER orders.notes → NVARCHAR(500)")
except Exception as e:
    print(f"⚠️  ALTER notes: {e}")
    conn.rollback()

cur.execute("DELETE FROM inventory")
cur.execute("DELETE FROM order_items")
cur.execute("DELETE FROM orders")
cur.execute("DELETE FROM products")
cur.execute("DELETE FROM customers")
for t in ("customers", "products", "orders", "order_items", "inventory"):
    cur.execute(f"DBCC CHECKIDENT ('{t}', RESEED, 0)")
conn.commit()
print("✅ MSSQL tables cleaned")
clean_kingbasees()

# =========================================================================
# 2. Customers (50条)
# =========================================================================
company_prefixes = [
    "华为技术", "阿里巴巴", "腾讯科技", "字节跳动", "小米科技",
    "百度在线", "京东集团", "美团科技", "网易杭州", "滴滴出行",
    "中国平安", "中国移动", "中国建筑", "格力电器", "海尔智家",
    "比亚迪", "宁德时代", "大疆创新", "联想集团", "中兴通讯",
    "科大讯飞", "商汤科技", "旷视科技", "紫光集团", "长城科技",
    "中芯国际", "京东方科技", "TCL科技", "浪潮信息", "中科曙光",
    "海康威视", "大华技术", "用友网络", "金蝶国际", "东软集团",
    "深信服科技", "启明星辰", "天融信科技", "绿盟科技", "安恒信息",
    "新华三技术", "锐捷网络", "神州数码", "太极计算机", "中国软件",
    "金山办公", "万兴科技", "福昕软件", "中望软件", "广联达科技",
]
company_suffixes = ["有限公司", "股份有限公司", "科技有限公司", "网络技术有限公司", "集团有限公司"]
surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
given_names = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "洋", "勇",
               "艳", "杰", "军", "超", "明", "秀英", "华", "平", "刚", "桂英",
               "文", "云", "建华", "玲", "国强", "志强", "秀兰", "海", "春梅", "婷"]

customers = []
for i in range(1, 51):
    code = f"C{i:03d}"
    name = company_prefixes[i - 1] + random.choice(company_suffixes)
    contact = random.choice(surnames) + random.choice(given_names)
    phone = f"138{random.randint(0, 9)}{random.randint(10000000, 99999999)}"
    email = f"user{i:03d}@company{i:02d}.com"
    is_active = 1 if random.random() > 0.15 else 0
    customers.append((i, code, name, contact, phone, email, is_active))

cur.execute("SET IDENTITY_INSERT customers ON")
for c in customers:
    cur.execute(
        "INSERT INTO customers (id, code, name, contact, phone, email, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", c,
    )
cur.execute("SET IDENTITY_INSERT customers OFF")
conn.commit()
print(f"✅ Inserted {len(customers)} customers")

# =========================================================================
# 3. Products (50条)
# =========================================================================
product_defs = [
    ("高性能服务器 R740", 89999), ("云存储阵列 DS4800", 125000),
    ("万兆交换机 S6730", 15800), ("数据库一体机 D2000", 450000),
    ("UPS 不间断电源", 32000), ("光纤模块 SFP+", 1200),
    ("机架式 KVM 切换器", 4800), ("网络防火墙 USG6600", 68000),
    ("负载均衡器 F5 BIG-IP", 188000), ("全闪存阵列 AF260", 320000),
    ("GPU 计算卡 Tesla V100", 78000), ("企业级 SSD 3.84TB", 6800),
    ("核心路由器 NE40E", 156000), ("无线控制器 AC6605", 28000),
    ("视频会议室终端 TE30", 35000), ("工业交换机 S5735-L", 12500),
    ("安全审计系统 SAS", 98000), ("备份一体机 PB9650", 210000),
    ("智能 PDU 电源分配器", 4500), ("服务器内存条 DDR4 64GB", 3200),
    ("分布式存储 Ceph 节点", 280000), ("容器云平台 K8s 版", 360000),
    ("SD-WAN 网关设备", 42000), ("对象存储网关 OSS", 55000),
    ("GPU 服务器 GN8000", 520000), ("万兆网卡 CX5", 2800),
    ("光纤跳线 LC-SC", 180), ("机柜式空调 PEX", 78000),
    ("动环监控系统", 145000), ("智能门禁系统", 18000),
    ("高清视频会议 MCU", 96000), ("PoE 交换机 S5735-P", 22000),
    ("入侵检测 IDS NIP", 115000), ("日志审计系统 LAS", 86000),
    ("虚拟化平台 Fusion", 198000), ("超融合一体机 HCI", 680000),
    ("边缘计算网关 EG", 38000), ("工业防火墙 ICS", 128000),
    ("数据备份软件许可", 48000), ("磁带库 MSL G3", 165000),
    ("KVM 延长器", 3600), ("服务器导轨套件", 800),
    ("电源延长线 PDU 基础", 1200), ("理线架 1U", 350),
    ("标签打印机", 2400), ("UPS 电池组", 8500),
    ("服务器机箱风扇", 650), ("散热硅脂 30g", 120),
    ("网线 Cat6 305米", 580), ("光纤配线架 ODF 24口", 1800),
]
products = []
for i, (name, base_price) in enumerate(product_defs, 1):
    price = round(base_price * random.uniform(0.95, 1.05), 2)
    products.append((i, f"P{i:03d}", name, price))

cur.execute("SET IDENTITY_INSERT products ON")
for p in products:
    cur.execute(
        "INSERT INTO products (id, code, name, price, is_active) VALUES (?, ?, ?, ?, 1)", p,
    )
cur.execute("SET IDENTITY_INSERT products OFF")
conn.commit()
print(f"✅ Inserted {len(products)} products")

# =========================================================================
# 4. Orders (200条) + Order Items
# =========================================================================
statuses = ["COMPLETED", "PENDING", "PROCESSING", "CANCELLED"]
status_weights = [0.5, 0.2, 0.2, 0.1]
notes_pool = [
    "服务器采购订单", "数据库一体机项目", "存储扩容项目", "UPS 备件采购",
    "防火墙+交换机采购", "网络设备批量采购", "GPU计算集群建设", "季度采购计划",
    "全闪存阵列采购", "负载均衡器部署", "核心路由器更换", "安全设备采购",
    "备份系统建设", "会议室设备", "服务器内存扩容", "安全审计系统",
    "工业交换机部署", "负载均衡扩容", "交换机补充", "年度服务器采购",
    "数据中心网络设备", "GPU集群二期", "防火墙升级", "存储阵列扩容",
    "PDU电源配件", "路由器采购", "容器云平台部署", "超融合项目",
    "虚拟化平台升级", "边缘计算节点部署", None, None,  # 20% 无备注
]
warehouses = ["MAIN", "SH", "BJ", "GZ", "CD"]

order_items = []
item_id = 0
orders = []

for oid in range(1, 201):
    order_no = f"ORD-{oid:06d}"
    cust_id = random.randint(1, 50)
    status = random.choices(statuses, weights=status_weights, k=1)[0]
    note = random.choice(notes_pool)

    # 每个订单 1~6 个明细行
    n_items = random.randint(1, 6)
    chosen_products = random.sample(range(1, 51), n_items)
    order_total = 0.0

    for pid in chosen_products:
        qty = random.randint(1, 20)
        unit_price = products[pid - 1][3]  # price from products list
        subtotal = round(qty * unit_price, 2)
        order_total += subtotal
        item_id += 1
        order_items.append((item_id, oid, pid, qty, unit_price, subtotal))

    order_total = round(order_total, 2)
    orders.append((oid, order_no, cust_id, status, order_total, n_items, note))

cur.execute("SET IDENTITY_INSERT orders ON")
for o in orders:
    cur.execute(
        "INSERT INTO orders (id, order_no, customer_id, status, total_amount, item_count, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", o,
    )
cur.execute("SET IDENTITY_INSERT orders OFF")
conn.commit()
print(f"✅ Inserted {len(orders)} orders")

cur.execute("SET IDENTITY_INSERT order_items ON")
for oi in order_items:
    cur.execute(
        "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal) "
        "VALUES (?, ?, ?, ?, ?, ?)", oi,
    )
cur.execute("SET IDENTITY_INSERT order_items OFF")
conn.commit()
print(f"✅ Inserted {len(order_items)} order_items")

# =========================================================================
# 5. Inventory (50条) — one per product, various warehouses
# =========================================================================
inventory = []
for pid in range(1, 51):
    wh = random.choice(warehouses)
    qty = random.randint(2, 500)
    min_qty = random.randint(1, max(1, qty // 5))
    inventory.append((pid, wh, qty, min_qty))

for pid, wh, qty, min_qty in inventory:
    cur.execute(
        "INSERT INTO inventory (product_id, warehouse, quantity, min_quantity) "
        "VALUES (?, ?, ?, ?)", (pid, wh, qty, min_qty),
    )
conn.commit()
print(f"✅ Inserted {len(inventory)} inventory records")

# =========================================================================
# 6. 验证中文编码 + 统计
# =========================================================================
print("\n--- 中文编码验证 ---")
cur.execute("SELECT TOP 5 id, name, contact FROM customers ORDER BY id")
for row in cur.fetchall():
    print(f"  Customer {row[0]}: name={row[1]}, contact={row[2]}")

cur.execute("SELECT TOP 5 id, name FROM products ORDER BY id")
for row in cur.fetchall():
    print(f"  Product {row[0]}: name={row[1]}")

cur.execute("SELECT TOP 5 id, notes FROM orders WHERE notes IS NOT NULL ORDER BY id")
for row in cur.fetchall():
    print(f"  Order {row[0]}: notes={row[1]}")

print("\n--- 数据统计 ---")
total = 0
for tbl in ("customers", "products", "orders", "order_items", "inventory"):
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    cnt = cur.fetchone()[0]
    total += cnt
    print(f"  {tbl}: {cnt} 条")
print(f"  ────────────────")
print(f"  总计: {total} 条")

conn.close()
print(f"\n✅ Seed complete!")
