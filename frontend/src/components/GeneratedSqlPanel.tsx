import { Typography, Button, message } from "antd";
import { CopyOutlined } from "@ant-design/icons";

interface Props {
  sourceSql: string;
  targetSql: string | null;
  sourceDb: string;
  targetDb: string;
}

export default function GeneratedSqlPanel({
  sourceSql,
  targetSql,
  sourceDb,
  targetDb,
}: Props) {
  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success("SQL 已复制");
    } catch {
      message.error("复制失败");
    }
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <Typography.Text strong style={{ display: "block", marginBottom: 8 }}>
        📝 生成的 SQL
      </Typography.Text>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        {/* Source SQL */}
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              源库 ({sourceDb.toUpperCase()})
            </Typography.Text>
            <Button
              size="small"
              type="text"
              icon={<CopyOutlined />}
              onClick={() => handleCopy(sourceSql)}
            />
          </div>
          <pre
            style={{
              background: "#f6f8fa",
              border: "1px solid #d0d7de",
              borderRadius: 6,
              padding: 12,
              fontSize: 13,
              fontFamily: "'SF Mono', 'Monaco', 'Menlo', monospace",
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              margin: 0,
              maxHeight: 200,
            }}
          >
            {sourceSql}
          </pre>
        </div>

        {/* Target SQL */}
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              目标库 ({targetDb.toUpperCase()})
              {targetSql && targetSql !== sourceSql ? " — 已重写" : ""}
            </Typography.Text>
            {targetSql && (
              <Button
                size="small"
                type="text"
                icon={<CopyOutlined />}
                onClick={() => handleCopy(targetSql)}
              />
            )}
          </div>
          <pre
            style={{
              background: targetSql !== sourceSql ? "#fff7e6" : "#f6f8fa",
              border: "1px solid #d0d7de",
              borderRadius: 6,
              padding: 12,
              fontSize: 13,
              fontFamily: "'SF Mono', 'Monaco', 'Menlo', monospace",
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              margin: 0,
              maxHeight: 200,
            }}
          >
            {targetSql || "（与原 SQL 相同）"}
          </pre>
        </div>
      </div>
    </div>
  );
}
