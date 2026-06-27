/**
 * SuggestionPanel — Display actionable migration suggestions.
 *
 * Each suggestion is a card with syntax highlighting hints.
 * If no suggestions, shows a green success message.
 */
import { Card, Tag, Typography, Empty } from "antd";
import { BulbOutlined, CheckCircleOutlined } from "@ant-design/icons";

const { Text } = Typography;

interface SuggestionPanelProps {
  suggestions: string[];
}

export default function SuggestionPanel({ suggestions }: SuggestionPanelProps) {
  if (suggestions.length === 0) {
    return (
      <Card
        styles={{ body: { padding: 48 } }}
        style={{ borderRadius: 12 }}
      >
        <Empty
          image={
            <CheckCircleOutlined
              style={{ fontSize: 48, color: "#52c41a" }}
            />
          }
          description="无需改写建议 — SQL 在各数据库中兼容良好"
        />
      </Card>
    );
  }

  // Categorize suggestions by DB
  const categorized: Record<string, string[]> = {};
  for (const s of suggestions) {
    // Try to extract DB prefix like "[mssql]" or "[kingbasees]"
    const match = s.match(/^\[(\w+)\]\s*(.+)/);
    if (match) {
      const db = match[1];
      const msg = match[2];
      if (!categorized[db]) categorized[db] = [];
      categorized[db].push(msg);
    } else {
      if (!categorized["general"]) categorized["general"] = [];
      categorized["general"].push(s);
    }
  }

  const DB_LABELS: Record<string, string> = {
    mssql: "MSSQL",
    kingbasees: "KingbaseES",
    dm8: "DM8",
    general: "通用",
  };

  const DB_COLORS: Record<string, string> = {
    mssql: "#1677ff",
    kingbasees: "#52c41a",
    dm8: "#fa8c16",
    general: "#8c8c8c",
  };

  return (
    <Card
      title={
        <span>
          <BulbOutlined style={{ marginRight: 8, color: "#faad14" }} />
          改写建议 ({suggestions.length} 条)
        </span>
      }
      styles={{ body: { padding: "12px 16px" } }}
      style={{ borderRadius: 12 }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {Object.entries(categorized).map(([db, msgs]) =>
          msgs.map((msg, idx) => (
            <div
              key={`${db}-${idx}`}
              style={{
                padding: "10px 14px",
                background: "#fafafa",
                borderRadius: 8,
                borderLeft: `3px solid ${DB_COLORS[db] || "#8c8c8c"}`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 4,
                }}
              >
                <Tag
                  color={DB_COLORS[db] || "default"}
                  style={{ fontSize: 11, margin: 0 }}
                >
                  {DB_LABELS[db] || db}
                </Tag>
              </div>
              <Text style={{ fontSize: 13, lineHeight: "20px" }}>{msg}</Text>
            </div>
          )),
        )}
      </div>
    </Card>
  );
}
