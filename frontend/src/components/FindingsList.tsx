/**
 * FindingsList — Displays compatibility findings grouped by type/severity.
 *
 * Each finding shows the issue, affected database, severity badge, and detail.
 */
import { Card, Tag, Typography, Collapse, Empty } from "antd";
import {
  BugOutlined,
  ThunderboltOutlined,
  FileSearchOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import type { Finding } from "../api/sqlScore";

const { Text, Paragraph } = Typography;

interface FindingsListProps {
  findings: Finding[];
}

const TYPE_CONFIG: Record<
  string,
  { icon: React.ReactNode; label: string; color: string }
> = {
  syntax: {
    icon: <BugOutlined />,
    label: "语法问题",
    color: "#722ed1",
  },
  execution: {
    icon: <ThunderboltOutlined />,
    label: "执行问题",
    color: "#fa8c16",
  },
  result: {
    icon: <FileSearchOutlined />,
    label: "结果差异",
    color: "#1677ff",
  },
  risk: {
    icon: <SafetyOutlined />,
    label: "风险提示",
    color: "#ff4d4f",
  },
};

const SEVERITY_COLORS: Record<string, string> = {
  low: "green",
  medium: "blue",
  high: "orange",
  critical: "red",
};

export default function FindingsList({ findings }: FindingsListProps) {
  if (findings.length === 0) {
    return (
      <Card
        styles={{ body: { padding: 48 } }}
        style={{ borderRadius: 12 }}
      >
        <Empty description="未发现兼容性问题 — SQL 在各数据库中兼容良好" />
      </Card>
    );
  }

  // Group findings by type
  const grouped: Record<string, Finding[]> = {};
  for (const f of findings) {
    if (!grouped[f.type]) {
      grouped[f.type] = [];
    }
    grouped[f.type].push(f);
  }

  const typeOrder = ["syntax", "execution", "result", "risk"];

  const collapseItems = typeOrder
    .filter((type) => grouped[type]?.length > 0)
    .map((type) => {
      const config = TYPE_CONFIG[type] || TYPE_CONFIG.syntax;
      const typeFindings = grouped[type];

      return {
        key: type,
        label: (
          <span>
            <span style={{ color: config.color, marginRight: 8 }}>
              {config.icon}
            </span>
            <Text strong>{config.label}</Text>
            <Tag style={{ marginLeft: 8 }}>{typeFindings.length}</Tag>
          </span>
        ),
        children: (
          <div>
            {typeFindings.map((f, idx) => (
              <div
                key={idx}
                style={{
                  padding: "12px 0",
                  borderBottom:
                    idx < typeFindings.length - 1
                      ? "1px solid #f0f0f0"
                      : "none",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    marginBottom: 4,
                  }}
                >
                  <Tag color={SEVERITY_COLORS[f.severity] || "default"}>
                    {f.severity.toUpperCase()}
                  </Tag>
                  <Tag>{f.db.toUpperCase()}</Tag>
                  <Text style={{ flex: 1, lineHeight: "24px" }}>
                    {f.issue}
                  </Text>
                </div>
                {f.detail && (
                  <Paragraph
                    type="secondary"
                    style={{
                      margin: "4px 0 0 0",
                      fontSize: 12,
                      paddingLeft: 4,
                    }}
                  >
                    {f.detail}
                  </Paragraph>
                )}
              </div>
            ))}
          </div>
        ),
      };
    });

  return (
    <Card
      title={
        <span>
          <FileSearchOutlined style={{ marginRight: 8 }} />
          兼容性发现 ({findings.length} 项)
        </span>
      }
      styles={{ body: { padding: "0 16px 8px" } }}
      style={{ borderRadius: 12 }}
    >
      <Collapse
        ghost
        defaultActiveKey={typeOrder.filter((t) => grouped[t]?.length > 0)}
        items={collapseItems}
      />
    </Card>
  );
}
