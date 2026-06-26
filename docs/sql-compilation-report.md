# SQL Compilation Report

> Phase 1 · 自动生成 · 三库 SQL 编译对比
> 可用 dialect: mssql, kingbasees

同一段 SQLAlchemy ORM 代码，在不同 dialect 下生成的原始 SQL 文本。
差异即迁移风险点。

---

## SELECT WHERE id=:id

### mssql

```sql
SELECT products.id, products.code, products.name, products.price, products.is_active, products.created_at 
FROM products 
WHERE products.id = 1
```

### kingbasees

```sql
SELECT products.id, products.code, products.name, products.price, products.is_active, products.created_at 
FROM products 
WHERE products.id = 1
```

---

## SELECT ORDER BY id OFFSET 10 LIMIT 20

### mssql

```sql
SELECT anon_1.id, anon_1.code, anon_1.name, anon_1.price, anon_1.is_active, anon_1.created_at 
FROM (SELECT products.id AS id, products.code AS code, products.name AS name, products.price AS price, products.is_active AS is_active, products.created_at AS created_at, ROW_NUMBER() OVER (ORDER BY products.id) AS mssql_rn 
FROM products) AS anon_1 
WHERE mssql_rn > 10 AND mssql_rn <= 20 + 10
```

### kingbasees

```sql
SELECT products.id, products.code, products.name, products.price, products.is_active, products.created_at 
FROM products ORDER BY products.id 
 LIMIT 20 OFFSET 10
```

---

## SELECT COUNT(*)

### mssql

```sql
SELECT count(*) AS count_1 
FROM products
```

### kingbasees

```sql
SELECT count(*) AS count_1 
FROM products
```

---

## INSERT single row

### mssql

```sql
INSERT INTO products (code, name, price, is_active, created_at) OUTPUT inserted.id VALUES ('P001', '测试', 99.99, 1, '2026-06-01 00:00:00+00:00')
```

### kingbasees

```sql
INSERT INTO products (code, name, price, is_active, created_at) VALUES ('P001', '测试', 99.99, true, '2026-06-01 00:00:00+00:00') RETURNING products.id
```

---

## INSERT bulk (2 rows)

### mssql

```sql
INSERT INTO products (code, name, price, is_active) VALUES ('B001', 'Batch 1', 10, 1), ('B002', 'Batch 2', 20, 0)
```

### kingbasees

```sql
INSERT INTO products (code, name, price, is_active) VALUES ('B001', 'Batch 1', 10, true), ('B002', 'Batch 2', 20, false)
```

---

## UPDATE SET name,price WHERE id=:id

### mssql

```sql
UPDATE products SET name='New', price=200 WHERE products.id = 1
```

### kingbasees

```sql
UPDATE products SET name='New', price=200 WHERE products.id = 1
```

---

## DELETE WHERE id=:id

### mssql

```sql
DELETE FROM products WHERE products.id = 1
```

### kingbasees

```sql
DELETE FROM products WHERE products.id = 1
```

---

## SELECT WHERE name LIKE '%搜索%'

### mssql

```sql
SELECT products.id, products.code, products.name, products.price, products.is_active, products.created_at 
FROM products 
WHERE products.name LIKE '%搜索%'
```

### kingbasees

```sql
SELECT products.id, products.code, products.name, products.price, products.is_active, products.created_at 
FROM products 
WHERE products.name LIKE '%%搜索%%'
```

---
