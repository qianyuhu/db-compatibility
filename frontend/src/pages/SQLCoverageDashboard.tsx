import { Card, Tag, Typography, Table, Tooltip } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DashboardOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

// =========================================================================
// Coverage Data
// =========================================================================

interface CoverageRow {
  module: string;
  select: boolean;
  join: boolean;
  groupBy: boolean;
  transaction: boolean;
  upsert: boolean;
  index: boolean;
}

const COVERAGE_DATA: CoverageRow[] = [
  {
    module: "Customer",
    select: true,
    join: false,
    groupBy: false,
    transaction: false,
    upsert: false,
    index: true,
  },
  {
    module: "Product",
    select: true,
    join: false,
    groupBy: false,
    transaction: false,
    upsert: false,
    index: true,
  },
  {
    module: "Order",
    select: true,
    join: true,
    groupBy: true,
    transaction: true,
    upsert: false,
    index: true,
  },
  {
    module: "Inventory",
    select: true,
    join: true,
    groupBy: true,
    transaction: true,
    upsert: true,
    index: true,
  },
  {
    module: "Sales Report",
    select: true,
    join: true,
    groupBy: true,
    transaction: false,
    upsert: false,
    index: true,
  },
  {
    module: "Inv. Report",
    select: true,
    join: true,
    groupBy: true,
    transaction: false,
    upsert: false,
    index: true,
  },
  {
    module: "Cust. Report",
    select: true,
    join: true,
    groupBy: true,
    transaction: false,
    upsert: false,
    index: true,
  },
];

// =========================================================================
// SQL Category Descriptions
// =========================================================================

const CATEGORY_TOOLTIPS: Record<string, string> = {
  select: "SELECT 查询 — 基本数据检索",
  join: "JOIN 多表关联 — 跨表数据联合查询",
  groupBy: "GROUP BY 聚合 — 数据分组与统计",
  transaction: "TRANSACTION 事务 — 多步操作的事务性保证",
  upsert: "UPSERT / MERGE — 存在则更新、不存在则插入",
  index: "INDEX 索引 — 通过索引提升查询性能",
};

// =========================================================================
// Component
// =========================================================================

const COVERAGE_COLUMNS: ColumnsType<CoverageRow> = [
  {
    title: "Module",
    dataIndex: "module",
    key: "module",
    width: 140,
    render: (name: string) => (
      <Typography.Text strong>{name}</Typography.Text>
    ),
  },
  {
    title: "SELECT",
    dataIndex: "select",
    key: "select",
    align: "center",
    width: 100,
    render: renderCoverage,
  },
  {
    title: "JOIN",
    dataIndex: "join",
    key: "join",
    align: "center",
    width: 100,
    render: renderCoverage,
  },
  {
    title: "GROUP BY",
    dataIndex: "groupBy",
    key: "groupBy",
    align: "center",
    width: 110,
    render: renderCoverage,
  },
  {
    title: "TRANSACTION",
    dataIndex: "transaction",
    key: "transaction",
    align: "center",
    width: 130,
    render: renderCoverage,
  },
  {
    title: "UPSERT",
    dataIndex: "upsert",
    key: "upsert",
    align: "center",
    width: 100,
    render: renderCoverage,
  },
  {
    title: "INDEX",
    dataIndex: "index",
    key: "index",
    align: "center",
    width: 100,
    render: renderCoverage,
  },
];

function renderCoverage(covered: boolean) {
  return (
    <Tooltip
      title={
        covered
          ? "已覆盖 — 该模块在此 SQL 类别下已验证"
          : "未覆盖 — 需要添加此类别的 SQL 测试"
      }
    >
      {covered ? (
        <Tag color="success" style={{ margin: 0 }}>
          <CheckCircleFilled style={{ marginRight: 4 }} />
          覆盖
        </Tag>
      ) : (
        <Tag color="error" style={{ margin: 0 }}>
          <CloseCircleFilled style={{ marginRight: 4 }} />
          缺失
        </Tag>
      )}
    </Tooltip>
  );
}

export default function SQLCoverageDashboard() {
  const totalModules = COVERAGE_DATA.length;
  const sqlCategories = ["select", "join", "groupBy", "transaction", "upsert", "index"] as const;

  const totalCells = totalModules * sqlCategories.length;
  const coveredCells = COVERAGE_DATA.reduce(
    (sum, row) => sum + sqlCategories.filter((cat) => row[cat]).length,
    0,
  );

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <DashboardOutlined /> SQL Coverage Dashboard
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        SQL 迁移测试覆盖矩阵 — 按模块和 SQL 类别展示验证状态
      </Typography.Paragraph>

      {/* Summary Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#1677ff" }}>
              {totalModules}
            </div>
            <Typography.Text type="secondary">覆盖模块</Typography.Text>
          </div>
        </Card>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#52c41a" }}>
              {sqlCategories.length}
            </div>
            <Typography.Text type="secondary">SQL 类别</Typography.Text>
          </div>
        </Card>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#1677ff" }}>
              {coveredCells}/{totalCells}
            </div>
            <Typography.Text type="secondary">
              覆盖 ({((coveredCells / totalCells) * 100).toFixed(0)}%)
            </Typography.Text>
          </div>
        </Card>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#faad14" }}>
              {totalCells - coveredCells}
            </div>
            <Typography.Text type="secondary">待覆盖</Typography.Text>
          </div>
        </Card>
      </div>

      {/* Coverage Matrix Table */}
      <Card title="SQL 兼容性覆盖矩阵">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          绿色 = 已验证通过；红色 = 待实现/验证
        </Typography.Paragraph>

        <Table
          columns={COVERAGE_COLUMNS}
          dataSource={COVERAGE_DATA.map((row, i) => ({ ...row, key: i }))}
          pagination={false}
          bordered
          size="middle"
        />
      </Card>

      {/* Category Legend */}
      <Card title="SQL 类别说明" size="small" style={{ marginTop: 24 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 12,
          }}
        >
          {Object.entries(CATEGORY_TOOLTIPS).map(([key, desc]) => (
            <div key={key}>
              <Typography.Text code>{key.toUpperCase()}</Typography.Text>
              <br />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {desc}
              </Typography.Text>
            </div>
          ))}
        </div>
      </Card>

      {/* Summary */}
      <Card size="small" style={{ marginTop: 16 }}>
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          ✅ 所有模块覆盖了 <strong>SELECT</strong> 和 <strong>INDEX</strong>（基本 SQL 能力）。
          <br />
          ⚠️ <strong>JOIN</strong> 和 <strong>GROUP BY</strong> 在 Customer/Product 主数据模块中缺失（可通过报表查询覆盖）。
          <br />
          ⚠️ <strong>TRANSACTION</strong> 仅在 Order/Inventory 模块验证（创建订单 + 调整库存联动）。
          <br />
          ⚠️ <strong>UPSERT</strong> 仅 Inventory 模块覆盖（ensure_inventory 模式）。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
