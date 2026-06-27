import { Table, Typography, Tag, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { SingleResult } from "../api/sqlDemo";
import { renderCellValue } from "../lib/renderUtils";

interface Props {
  dbLabel: string;
  color: string;
  result: SingleResult | undefined;
}

export default function SideBySideResult({
  dbLabel,
  color,
  result,
}: Props) {
  if (!result) {
    return (
      <Empty
        description="等待执行..."
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  if (!result.success) {
    return (
      <div
        style={{
          padding: 16,
          background: "#fff2f0",
          border: "1px solid #ffccc7",
          borderRadius: 6,
        }}
      >
        <Typography.Text type="danger" strong>
          ❌ 执行失败
        </Typography.Text>
        <Typography.Paragraph
          code
          style={{
            marginTop: 8,
            padding: 8,
            background: "#fff1f0",
            borderRadius: 4,
            fontSize: 12,
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {result.error}
        </Typography.Paragraph>
        {result.suggestion && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            💡 {result.suggestion}
          </Typography.Paragraph>
        )}
      </div>
    );
  }

  if (result.columns.length === 0) {
    return (
      <Empty
        description="执行成功，但未返回数据"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const tableColumns: ColumnsType<Record<string, unknown>> = result.columns.map(
    (col, idx) => ({
      title: col,
      dataIndex: `col_${idx}`,
      key: `col_${idx}`,
      ellipsis: true,
      width: Math.min(200, Math.max(80, col.length * 10)),
      render: renderCellValue,
    }),
  );

  const dataSource = result.rows.map((row, rowIdx) => {
    const record: Record<string, unknown> = { _key: rowIdx };
    result.columns.forEach((_, colIdx) => {
      record[`col_${colIdx}`] = row[colIdx];
    });
    return record;
  });

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <span>
          <Tag color={color}>{dbLabel}</Tag>
          <Typography.Text strong>
            {result.row_count} 行
          </Typography.Text>
        </span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {result.execution_time_ms}ms
        </Typography.Text>
      </div>
      <Table
        columns={tableColumns}
        dataSource={dataSource}
        rowKey="_key"
        size="small"
        bordered
        pagination={
          result.row_count > 50
            ? {
                pageSize: 50,
                showSizeChanger: true,
                showTotal: (t) => `共 ${t} 行`,
              }
            : false
        }
        scroll={{ x: "max-content" }}
        style={{ background: "#fff" }}
      />
    </div>
  );
}
