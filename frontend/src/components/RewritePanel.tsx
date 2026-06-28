/**
 * RewritePanel — Side-by-side display of original vs rewritten SQL.
 *
 * Shows:
 *   - Original SQL (top, with source DB label)
 *   - Down arrow separator
 *   - Rewritten SQL (bottom, with target DB label)
 */
import { Typography, Tag } from "antd";
import { ArrowDownOutlined } from "@ant-design/icons";

const { Text, Paragraph } = Typography;

const DB_LABELS: Record<string, { label: string; color: string }> = {
  mssql: { label: "MSSQL", color: "#1677ff" },
  kingbasees: { label: "KingbaseES", color: "#52c41a" },
  dm8: { label: "DM8", color: "#fa8c16" },
};

interface RewritePanelProps {
  originalSql: string;
  rewrittenSql: string;
  sourceDb: string;
  targetDb: string;
}

export default function RewritePanel({
  originalSql,
  rewrittenSql,
  sourceDb,
  targetDb,
}: RewritePanelProps) {
  const source = DB_LABELS[sourceDb] || { label: sourceDb, color: "#8c8c8c" };
  const target = DB_LABELS[targetDb] || { label: targetDb, color: "#8c8c8c" };

  return (
    <div>
      {/* Original SQL */}
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          border: "1px solid #e8e8e8",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "8px 16px",
            background: "#fafafa",
            borderBottom: "1px solid #e8e8e8",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Text strong style={{ fontSize: 13 }}>
            原始 SQL
          </Text>
          <Tag color={source.color} style={{ margin: 0 }}>
            {source.label}
          </Tag>
        </div>
        <div style={{ padding: 16 }}>
          <Paragraph
            code
            style={{
              margin: 0,
              fontSize: 13,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#f5f5f5",
              padding: 12,
              borderRadius: 6,
              fontFamily:
                "'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace",
            }}
          >
            {originalSql}
          </Paragraph>
        </div>
      </div>

      {/* Arrow */}
      <div style={{ textAlign: "center", padding: "12px 0" }}>
        <ArrowDownOutlined
          style={{ fontSize: 20, color: "#1677ff" }}
        />
        <Text
          type="secondary"
          style={{ display: "block", fontSize: 11, marginTop: 2 }}
        >
          改写
        </Text>
      </div>

      {/* Rewritten SQL */}
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          border: "1px solid #e8e8e8",
          overflow: "hidden",
          boxShadow:
            rewrittenSql !== originalSql
              ? "0 0 0 2px rgba(82, 196, 26, 0.15)"
              : undefined,
        }}
      >
        <div
          style={{
            padding: "8px 16px",
            background: "#fafafa",
            borderBottom: "1px solid #e8e8e8",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Text strong style={{ fontSize: 13 }}>
            改写结果
          </Text>
          <Tag color={target.color} style={{ margin: 0 }}>
            {target.label}
          </Tag>
        </div>
        <div style={{ padding: 16 }}>
          <Paragraph
            code
            style={{
              margin: 0,
              fontSize: 13,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#f6ffed",
              padding: 12,
              borderRadius: 6,
              fontFamily:
                "'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace",
              border: "1px solid #d9f7be",
            }}
          >
            {rewrittenSql}
          </Paragraph>
        </div>
      </div>
    </div>
  );
}
