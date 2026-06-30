import { Table, Typography, Tag, Alert, Empty, Card } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { DiffResult, ValueDiffItem } from "../api/sqlDemo";

const DB_LABELS: Record<string, string> = {
  mssql: "MSSQL",
  kingbasees: "KingbaseES",
  dm8: "DM8",
};

const DB_COLORS: Record<string, string> = {
  mssql: "#1677ff",
  kingbasees: "#52c41a",
  dm8: "#fa8c16",
};

interface Props {
  diff: DiffResult;
}

export default function DiffTable({ diff }: Props) {
  const hasAnyDiff =
    diff.row_count_diff ||
    diff.column_diff ||
    diff.value_diff.length > 0;

  return (
    <div>
      {/* 总体摘要 */}
      <Alert
        type={hasAnyDiff ? "warning" : "success"}
        showIcon
        title={
          hasAnyDiff ? (
            <Typography.Text strong>检测到差异</Typography.Text>
          ) : (
            <Typography.Text strong style={{ color: "#389e0d" }}>
              结果一致 — 三库返回完全相同
            </Typography.Text>
          )
        }
        description={
          hasAnyDiff
            ? [
                diff.row_count_diff && "行数不一致",
                diff.column_diff && "列结构不一致",
                diff.value_diff.length > 0 &&
                  `${diff.value_diff.length} 处值差异`,
              ]
                .filter(Boolean)
                .join(" • ")
            : "Schema、行数、数据值三个维度均无差异。"
        }
        style={{ marginBottom: 16 }}
      />

      {/* 行数比较 */}
      {diff.row_count_diff && (
        <Card
          size="small"
          title="📊 行数差异"
          style={{ marginBottom: 12 }}
          styles={{ body: { padding: 12 } }}
        >
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {Object.entries(diff.row_count_details).map(([db, count]) => (
              <Tag key={db} color={DB_COLORS[db] || "default"}>
                {DB_LABELS[db] || db}: {count} 行
              </Tag>
            ))}
          </div>
        </Card>
      )}

      {/* 列结构差异 */}
      {diff.column_diff && diff.column_details.length > 0 && (
        <Card
          size="small"
          title="📋 列结构差异"
          style={{ marginBottom: 12 }}
          styles={{ body: { padding: 12 } }}
        >
          {diff.column_details.map((detail) => (
            <div key={detail.db_type} style={{ marginBottom: 8 }}>
              <Tag color={DB_COLORS[detail.db_type] || "default"}>
                {DB_LABELS[detail.db_type] || detail.db_type}
              </Tag>
              <Typography.Text code style={{ fontSize: 12 }}>
                {detail.columns.join(", ") || "(无列)"}
              </Typography.Text>
              {detail.missing_from_others.length > 0 && (
                <Typography.Text
                  type="danger"
                  style={{ marginLeft: 8, fontSize: 12 }}
                >
                  缺失: {detail.missing_from_others.join(", ")}
                </Typography.Text>
              )}
            </div>
          ))}
        </Card>
      )}

      {/* 值差异表格 */}
      {diff.value_diff.length > 0 && (
        <Card
          size="small"
          title={`🔍 值差异 (${diff.value_diff.length} 处)`}
          styles={{ body: { padding: 0 } }}
        >
          <ValueDiffTable items={diff.value_diff} />
        </Card>
      )}

      {/* 无差异 */}
      {!hasAnyDiff && (
        <Empty
          description="未发现任何差异"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      )}
    </div>
  );
}

// ---- 值差异子组件 ----

function ValueDiffTable({ items }: { items: ValueDiffItem[] }) {
  // 获取所有涉及的数据库
  const dbTypes = items.length > 0 ? Object.keys(items[0].values) : [];

  const columns: ColumnsType<ValueDiffItem> = [
    {
      title: "#",
      dataIndex: "row_index",
      key: "row_index",
      width: 70,
      render: (val: number) => (
        <Typography.Text code>行 {val}</Typography.Text>
      ),
    },
    {
      title: "列",
      dataIndex: "column",
      key: "column",
      width: 140,
      render: (val: string) => (
        <Typography.Text strong>{val}</Typography.Text>
      ),
    },
    ...dbTypes.map((db) => ({
      title: (
        <Tag color={DB_COLORS[db] || "default"}>
          {DB_LABELS[db] || db}
        </Tag>
      ),
      dataIndex: ["values", db] as [string, string],
      key: db,
      ellipsis: true,
      render: (_: unknown, record: ValueDiffItem) => {
        const val = record.values[db];
        return (
          <Typography.Text
            style={{
              background: "#fff7e6",
              padding: "2px 6px",
              borderRadius: 3,
              fontSize: 12,
              fontFamily: "monospace",
            }}
          >
            {val === null ? (
              <Typography.Text type="secondary" italic>
                (null)
              </Typography.Text>
            ) : typeof val === "boolean" ? (
              val ? "true" : "false"
            ) : (
              String(val)
            )}
          </Typography.Text>
        );
      },
    })),
  ];

  return (
    <Table
      columns={columns}
      dataSource={items}
      rowKey={(r) => `diff-${r.row_index}-${r.column}`}
      size="small"
      bordered
      pagination={
        items.length > 50
          ? {
              pageSize: 50,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 处差异`,
            }
          : false
      }
      scroll={{ x: "max-content" }}
      style={{ background: "#fff" }}
    />
  );
}
