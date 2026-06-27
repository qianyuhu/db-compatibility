import { Alert, Typography } from "antd";

interface Props {
  error: string;
  suggestion?: string | null;
}

export default function ErrorPanel({ error, suggestion }: Props) {
  return (
    <Alert
      type="error"
      showIcon
      message={
        <Typography.Text strong style={{ color: "#cf1322" }}>
          执行失败
        </Typography.Text>
      }
      description={
        <div>
          <Typography.Paragraph
            code
            style={{
              marginTop: 8,
              padding: 12,
              background: "#fff2f0",
              borderRadius: 4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {error}
          </Typography.Paragraph>
          {suggestion && (
            <Typography.Paragraph
              type="secondary"
              style={{ marginTop: 8, fontStyle: "italic" }}
            >
              💡 {suggestion}
            </Typography.Paragraph>
          )}
        </div>
      }
      style={{ marginTop: 8 }}
    />
  );
}
