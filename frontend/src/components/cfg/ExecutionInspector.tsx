/**
 * Execution Inspector — right panel showing selected node details.
 *
 * Displays:
 *   - Node metadata (type, IR source, SQL text)
 *   - 3-column DB result comparison (MSSQL | KingbaseES | DM8)
 *   - Diff visualization (row count, column, value diffs)
 *   - Error display
 */

import { Card, Descriptions, Tag, Typography, Table, Empty } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
import type { UINode, NodeExecutionResult } from "../../api/cfgWorkbench";

const { Title, Text, Paragraph } = Typography;

interface ExecutionInspectorProps {
  selectedNode: UINode | null;
  executionResult: NodeExecutionResult | null;
  targetDbs: string[];
}

const DB_COLORS: Record<string, string> = {
  mssql: "#1677ff",
  kingbasees: "#52c41a",
  dm8: "#fa8c16",
};

export default function ExecutionInspector({
  selectedNode,
  executionResult,
  targetDbs,
}: ExecutionInspectorProps) {
  if (!selectedNode) {
    return (
      <Card size="small" style={{ height: "100%" }}>
        <Empty
          description="Select a node to inspect"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </Card>
    );
  }

  const source = selectedNode.source;
  const diff = executionResult?.diff;
  const results = executionResult?.results || {};

  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color="blue">{selectedNode.type.toUpperCase()}</Tag>
          <Text strong>{selectedNode.id}</Text>
        </span>
      }
      style={{ height: "100%", overflow: "auto" }}
    >
      {/* Node Source Info */}
      <Title level={5} style={{ marginTop: 0 }}>Source</Title>
      <Descriptions column={1} size="small" colon={false}>
        <Descriptions.Item label="IR Type">
          <Tag>{source.ir_node_type}</Tag>
        </Descriptions.Item>
        {source.sql_text && (
          <Descriptions.Item label="SQL">
            <pre style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap", background: "#f5f5f5", padding: 8, borderRadius: 4 }}>
              {source.sql_text}
            </pre>
          </Descriptions.Item>
        )}
        {source.condition && (
          <Descriptions.Item label="Condition">
            <Text code>{source.condition}</Text>
          </Descriptions.Item>
        )}
        {source.target && (
          <Descriptions.Item label="Target">
            <Text code>{source.target}</Text>
          </Descriptions.Item>
        )}
        {source.expression && (
          <Descriptions.Item label="Expression">
            <Text code>{source.expression}</Text>
          </Descriptions.Item>
        )}
        {source.procedure_name && (
          <Descriptions.Item label="Procedure">
            {source.procedure_name}
          </Descriptions.Item>
        )}
      </Descriptions>

      {/* Execution Results */}
      {executionResult && (
        <>
          <Title level={5} style={{ marginTop: 16 }}>Execution Results</Title>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {targetDbs.map((db) => {
              const r = results[db];
              const dbColor = DB_COLORS[db] || "#8c8c8c";

              return (
                <Card
                  key={db}
                  size="small"
                  title={
                    <Tag color={dbColor} style={{ margin: 0 }}>{db.toUpperCase()}</Tag>
                  }
                  style={{ flex: 1, minWidth: 180 }}
                >
                  {!r ? (
                    <Text type="secondary">No result</Text>
                  ) : r.success ? (
                    <div>
                      <Text type="success">
                        <CheckCircleOutlined style={{ marginRight: 4 }} />
                        {r.row_count} rows
                      </Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {r.execution_time_ms.toFixed(1)}ms
                      </Text>
                      {r.columns.length > 0 && (
                        <Table
                          dataSource={r.rows.slice(0, 5).map((row, i) => {
                            const record: Record<string, unknown> = { _key: i };
                            r.columns.forEach((col, j) => {
                              record[col] = row[j];
                            });
                            return record;
                          })}
                          columns={r.columns.map((col) => ({
                            title: col,
                            dataIndex: col,
                            key: col,
                            ellipsis: true,
                          }))}
                          pagination={false}
                          size="small"
                          scroll={{ x: true }}
                          style={{ marginTop: 8 }}
                        />
                      )}
                    </div>
                  ) : (
                    <div>
                      <Text type="danger">
                        <CloseCircleOutlined style={{ marginRight: 4 }} />
                        Failed
                      </Text>
                      {r.error && (
                        <Paragraph
                          type="danger"
                          style={{ fontSize: 11, marginTop: 4, marginBottom: 0 }}
                          ellipsis={{ rows: 3, expandable: true }}
                        >
                          {r.error}
                        </Paragraph>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>

          {/* Diff Summary */}
          {diff && (
            <div style={{ marginTop: 12 }}>
              <Title level={5}>Diff</Title>
              <Tag
                color={
                  diff.status === "MATCH" ? "green"
                  : diff.status === "MISMATCH" ? "orange"
                  : "red"
                }
                icon={
                  diff.status === "MATCH" ? <CheckCircleOutlined />
                  : diff.status === "MISMATCH" ? <MinusCircleOutlined />
                  : <CloseCircleOutlined />
                }
              >
                {diff.status}
              </Tag>
              {diff.row_diff !== 0 && (
                <div style={{ marginTop: 4 }}>
                  <Text type="warning">
                    Row diff: {diff.row_diff > 0 ? "+" : ""}{diff.row_diff}
                  </Text>
                </div>
              )}
              {diff.column_diff.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <Text type="warning">Column diffs:</Text>
                  {diff.column_diff.map((c, i) => (
                    <Tag key={i} color="orange" style={{ display: "block", marginTop: 2 }}>
                      {c}
                    </Tag>
                  ))}
                </div>
              )}
              {diff.value_diffs.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <Text type="warning">
                    {diff.value_diffs.length} value difference(s)
                  </Text>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* No execution yet */}
      {!executionResult && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">Click "Run Node" to execute this node</Text>
        </div>
      )}
    </Card>
  );
}
