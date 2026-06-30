/**
 * DiffVisualization — 3-Layer SQL Diff display component.
 *
 * Layer 1: Summary View (status, row count, column types, data match, timing)
 * Layer 2: Field-Level Diff Table (column-by-column comparison)
 * Layer 3: Row-Level Diff Deep Dive (individual row differences)
 * Explanation Panel: Auto-generated root cause analysis
 */

import { Collapse, Tag, Typography, Table, Alert, Card, Row, Col, Tooltip, Badge } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  InfoCircleOutlined,
  BulbOutlined,
} from "@ant-design/icons";
import type {
  ThreeLayerDiff,
  Layer1Summary,
  Layer2FieldDiff,
  Layer3RowDiff,
  DiffExplanation,
} from "../api/business";

// =========================================================================
// Helpers
// =========================================================================

function severityColor(severity: string): string {
  switch (severity) {
    case "low":
      return "#52c41a";
    case "medium":
      return "#faad14";
    case "high":
      return "#ff4d4f";
    default:
      return "#8c8c8c";
  }
}

function categoryTag(category: string): { color: string; label: string } {
  const map: Record<string, { color: string; label: string }> = {
    precision: { color: "cyan", label: "精度" },
    type_mapping: { color: "blue", label: "类型映射" },
    collation: { color: "purple", label: "排序规则" },
    null_handling: { color: "red", label: "NULL 处理" },
    rewrite: { color: "orange", label: "SQL 重写" },
    casing: { color: "geekblue", label: "大小写" },
    boolean: { color: "gold", label: "Boolean" },
    column_missing_in_source: { color: "magenta", label: "源库缺失" },
    column_missing_in_target: { color: "magenta", label: "目标库缺失" },
    value_mismatch: { color: "volcano", label: "值不匹配" },
    unknown: { color: "default", label: "未知" },
  };
  return map[category] ?? { color: "default", label: category };
}

// =========================================================================
// Layer 1: Summary
// =========================================================================

interface Layer1ViewProps {
  layer1: Layer1Summary;
  sourceDb: string;
  targetDb: string;
}

function Layer1View({ layer1, sourceDb, targetDb }: Layer1ViewProps) {
  const checkItems = [
    {
      label: "Row Count",
      match: layer1.row_count_match,
      icon: layer1.row_count_match ? (
        <CheckCircleOutlined style={{ color: "#52c41a" }} />
      ) : (
        <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
      ),
    },
    {
      label: "Column Type",
      match: layer1.column_type_match,
      icon: layer1.column_type_match ? (
        <CheckCircleOutlined style={{ color: "#52c41a" }} />
      ) : (
        <WarningOutlined style={{ color: "#faad14" }} />
      ),
    },
    {
      label: "Data Match",
      match: layer1.data_match,
      icon: layer1.data_match ? (
        <CheckCircleOutlined style={{ color: "#52c41a" }} />
      ) : (
        <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
      ),
    },
    {
      label: "Execution Time",
      match: layer1.execution_time_match,
      icon: layer1.execution_time_match ? (
        <CheckCircleOutlined style={{ color: "#52c41a" }} />
      ) : (
        <WarningOutlined style={{ color: "#faad14" }} />
      ),
    },
  ];

  return (
    <div>
      {/* Status badge */}
      <div style={{ marginBottom: 16 }}>
        <Tag
          color={
            layer1.status === "MATCH"
              ? "green"
              : layer1.status === "DIFF"
                ? "red"
                : "gold"
          }
          style={{ fontSize: 16, padding: "4px 16px" }}
        >
          {layer1.status === "MATCH"
            ? "✓ MATCH"
            : layer1.status === "DIFF"
              ? "✗ DIFF"
              : "⚠ ERROR"}
        </Tag>
        {layer1.total_diffs > 0 && (
          <Typography.Text type="secondary" style={{ marginLeft: 12 }}>
            {layer1.total_diffs} difference{layer1.total_diffs > 1 ? "s" : ""} found
          </Typography.Text>
        )}
      </div>

      {/* Summary checks */}
      <Row gutter={[16, 8]}>
        {checkItems.map((item) => (
          <Col span={6} key={item.label}>
            <Card size="small" bordered>
              <div style={{ textAlign: "center" }}>
                {item.icon}
                <div style={{ marginTop: 4 }}>
                  <Typography.Text
                    strong
                    style={{
                      color: item.match ? "#52c41a" : "#ff4d4f",
                    }}
                  >
                    {item.match ? "✓" : "✗"} {item.label}
                  </Typography.Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* Summary text */}
      <pre
        style={{
          background: "#f6f8fa",
          padding: 12,
          borderRadius: 6,
          fontSize: 13,
          marginTop: 12,
          marginBottom: 0,
          lineHeight: 1.8,
        }}
      >
        {layer1.summary_text}
      </pre>
    </div>
  );
}

// =========================================================================
// Layer 2: Field-Level Diff Table
// =========================================================================

interface Layer2ViewProps {
  layer2: Layer2FieldDiff[];
}

function Layer2View({ layer2 }: Layer2ViewProps) {
  const mismatchCount = layer2.filter((d) => !d.match).length;

  return (
    <div>
      {mismatchCount > 0 && (
        <Typography.Text type="warning" style={{ display: "block", marginBottom: 12 }}>
          <WarningOutlined /> {mismatchCount} column mismatch{ mismatchCount > 1 ? "es" : ""}
        </Typography.Text>
      )}

      <Table<Layer2FieldDiff>
        dataSource={layer2}
        rowKey="field_name"
        pagination={false}
        size="small"
        columns={[
          {
            title: "Field",
            dataIndex: "field_name",
            key: "field_name",
            width: 180,
            render: (name: string) => (
              <Typography.Text code>{name}</Typography.Text>
            ),
          },
          {
            title: "Source",
            dataIndex: "source_value",
            key: "source_value",
            render: (val: string) => (
              <Typography.Text style={{ color: "#1677ff", fontFamily: "monospace" }}>
                {val}
              </Typography.Text>
            ),
          },
          {
            title: "Target",
            dataIndex: "target_value",
            key: "target_value",
            render: (val: string) => (
              <Typography.Text style={{ color: "#52c41a", fontFamily: "monospace" }}>
                {val}
              </Typography.Text>
            ),
          },
          {
            title: "Status",
            dataIndex: "match",
            key: "match",
            width: 100,
            align: "center",
            render: (match: boolean, record: Layer2FieldDiff) =>
              match ? (
                <CheckCircleOutlined style={{ color: "#52c41a" }} />
              ) : (
                <Tooltip title={record.category}>
                  <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
                </Tooltip>
              ),
          },
        ]}
      />
    </div>
  );
}

// =========================================================================
// Layer 3: Row-Level Diff Deep Dive
// =========================================================================

interface Layer3ViewProps {
  layer3: Layer3RowDiff[];
  sourceDb: string;
  targetDb: string;
}

function Layer3View({ layer3, sourceDb, targetDb }: Layer3ViewProps) {
  if (layer3.length === 0) {
    return (
      <Typography.Text type="secondary">No row-level differences found.</Typography.Text>
    );
  }

  return (
    <div>
      <Typography.Text style={{ display: "block", marginBottom: 12 }}>
        Showing {layer3.length} row-level difference{layer3.length > 1 ? "s" : ""}:
      </Typography.Text>

      {layer3.map((diff, idx) => (
        <Card
          key={`${diff.row_index}-${diff.field_name}-${idx}`}
          size="small"
          style={{ marginBottom: 8 }}
          title={
            <span>
              <Tag color="red">Row #{diff.row_index + 1}</Tag>
              <Typography.Text code>{diff.field_name}</Typography.Text>
            </span>
          }
        >
          <Row gutter={16}>
            <Col span={12}>
              <div
                style={{
                  background: "#e6f4ff",
                  padding: 8,
                  borderRadius: 4,
                  fontFamily: "monospace",
                  fontSize: 13,
                }}
              >
                <Typography.Text type="secondary">
                  {sourceDb.toUpperCase()}:
                </Typography.Text>{" "}
                <Typography.Text strong>
                  {JSON.stringify(diff.source_value)}
                </Typography.Text>
              </div>
            </Col>
            <Col span={12}>
              <div
                style={{
                  background: "#f6ffed",
                  padding: 8,
                  borderRadius: 4,
                  fontFamily: "monospace",
                  fontSize: 13,
                }}
              >
                <Typography.Text type="secondary">
                  {targetDb.toUpperCase()}:
                </Typography.Text>{" "}
                <Typography.Text strong>
                  {JSON.stringify(diff.target_value)}
                </Typography.Text>
              </div>
            </Col>
          </Row>

          {/* Highlight difference */}
          <div style={{ marginTop: 8, textAlign: "center" }}>
            <Typography.Text
              style={{
                color: "#1677ff",
                fontFamily: "monospace",
              }}
            >
              {JSON.stringify(diff.source_value)}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ margin: "0 8px" }}>
              →
            </Typography.Text>
            <Typography.Text
              style={{
                color: "#52c41a",
                fontFamily: "monospace",
              }}
            >
              {JSON.stringify(diff.target_value)}
            </Typography.Text>
          </div>

          {/* Inline explanation */}
          {diff.explanation && (
            <Alert
              type="info"
              title={
                <span>
                  <BulbOutlined /> {diff.explanation.reason}
                </span>
              }
              style={{ marginTop: 8 }}
              showIcon={false}
            />
          )}
        </Card>
      ))}
    </div>
  );
}

// =========================================================================
// Explanation Panel
// =========================================================================

interface ExplanationPanelProps {
  explanations: DiffExplanation[];
}

function ExplanationPanel({ explanations }: ExplanationPanelProps) {
  if (explanations.length === 0) {
    return (
      <Typography.Text type="secondary">No explanations available.</Typography.Text>
    );
  }

  return (
    <div>
      {explanations.map((exp, idx) => (
        <Alert
          key={idx}
          type={
            exp.severity === "high"
              ? "error"
              : exp.severity === "medium"
                ? "warning"
                : "info"
          }
          title={
            <div>
              <div style={{ marginBottom: 4 }}>
                <Badge color={severityColor(exp.severity)} text="" />
                <Tag color={categoryTag(exp.category).color}>
                  {categoryTag(exp.category).label}
                </Tag>
                <Typography.Text strong>{exp.reason}</Typography.Text>
              </div>
              {exp.possible_causes.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Possible Causes:
                  </Typography.Text>
                  {exp.possible_causes.map((cause, ci) => (
                    <div key={ci} style={{ fontSize: 12, marginLeft: 8 }}>
                      {cause}
                    </div>
                  ))}
                </div>
              )}
            </div>
          }
          style={{ marginBottom: 8 }}
          showIcon={false}
        />
      ))}
    </div>
  );
}

// =========================================================================
// Main Component
// =========================================================================

interface DiffVisualizationProps {
  enhancedDiff: ThreeLayerDiff | null;
  sourceDb: string;
  targetDb: string;
}

export default function DiffVisualization({
  enhancedDiff,
  sourceDb,
  targetDb,
}: DiffVisualizationProps) {
  if (!enhancedDiff) {
    return (
      <Alert
        type="info"
        title="No enhanced diff data available"
        description="The diff analysis could not be computed. See raw diff_detail for basic comparison."
        showIcon
      />
    );
  }

  const { layer1, layer2, layer3, explanations } = enhancedDiff;

  const collapseItems = [
    {
      key: "layer1",
      label: (
        <span>
          <InfoCircleOutlined style={{ marginRight: 8 }} />
          <Typography.Text strong>🟢 Layer 1 — Summary View</Typography.Text>
          {layer1 && (
            <Tag
              color={layer1.status === "MATCH" ? "green" : "red"}
              style={{ marginLeft: 8 }}
            >
              {layer1.status}
            </Tag>
          )}
        </span>
      ),
      children: layer1 ? (
        <Layer1View layer1={layer1} sourceDb={sourceDb} targetDb={targetDb} />
      ) : (
        <Typography.Text type="secondary">No summary data.</Typography.Text>
      ),
    },
    {
      key: "layer2",
      label: (
        <span>
          <InfoCircleOutlined style={{ marginRight: 8 }} />
          <Typography.Text strong>🟡 Layer 2 — Field-Level Diff Table</Typography.Text>
          {layer2 && (
            <Tag
              color={layer2.some((d) => !d.match) ? "orange" : "green"}
              style={{ marginLeft: 8 }}
            >
              {layer2.filter((d) => !d.match).length} mismatches
            </Tag>
          )}
        </span>
      ),
      children: layer2 ? (
        <Layer2View layer2={layer2} />
      ) : (
        <Typography.Text type="secondary">No field-level data.</Typography.Text>
      ),
    },
    {
      key: "layer3",
      label: (
        <span>
          <InfoCircleOutlined style={{ marginRight: 8 }} />
          <Typography.Text strong>🔴 Layer 3 — Row-Level Diff (Deep Dive)</Typography.Text>
          {layer3 && (
            <Tag color={layer3.length > 0 ? "red" : "green"} style={{ marginLeft: 8 }}>
              {layer3.length} rows
            </Tag>
          )}
        </span>
      ),
      children: layer3 ? (
        <Layer3View
          layer3={layer3}
          sourceDb={sourceDb}
          targetDb={targetDb}
        />
      ) : (
        <Typography.Text type="secondary">No row-level data.</Typography.Text>
      ),
    },
    {
      key: "explanations",
      label: (
        <span>
          <BulbOutlined style={{ marginRight: 8 }} />
          <Typography.Text strong>🧠 Explanation Panel</Typography.Text>
          {explanations && (
            <Tag
              color={explanations.length > 0 ? "purple" : "default"}
              style={{ marginLeft: 8 }}
            >
              {explanations.length} insight{explanations.length !== 1 ? "s" : ""}
            </Tag>
          )}
        </span>
      ),
      children: explanations ? (
        <ExplanationPanel explanations={explanations} />
      ) : (
        <Typography.Text type="secondary">No explanations.</Typography.Text>
      ),
    },
  ];

  return (
    <Collapse
      items={collapseItems}
      defaultActiveKey={layer3 && layer3.length > 0 ? ["layer3"] : ["layer1"]}
      style={{ marginTop: 12 }}
    />
  );
}
