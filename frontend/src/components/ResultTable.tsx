import { Table, Empty, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { renderCellValue } from "../lib/renderUtils";

interface Props {
  columns: string[];
  rows: unknown[][];
  executionTimeMs: number;
}

export default function ResultTable({ columns, rows, executionTimeMs }: Props) {
  if (columns.length === 0) {
    return (
      <Empty
        description="执行成功，但未返回数据行"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const tableColumns: ColumnsType<Record<string, unknown>> = columns.map((col, idx) => ({
    title: col,
    dataIndex: `col_${idx}`,
    key: `col_${idx}`,
    ellipsis: true,
    width: col.length > 20 ? 250 : 150,
    render: renderCellValue,
  }));

  const dataSource = rows.map((row, rowIdx) => {
    const record: Record<string, unknown> = { _key: rowIdx };
    columns.forEach((_, colIdx) => {
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
        <Typography.Text strong>
          结果: {rows.length} 行
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {executionTimeMs}ms
        </Typography.Text>
      </div>
      <Table
        columns={tableColumns}
        dataSource={dataSource}
        rowKey="_key"
        size="small"
        bordered
        pagination={
          rows.length > 50
            ? { pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 行` }
            : false
        }
        scroll={{ x: "max-content" }}
        style={{ background: "#fff" }}
      />
    </div>
  );
}
