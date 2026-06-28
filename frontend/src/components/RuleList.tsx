/**
 * RuleList — Displays the list of rules applied during SQL rewrite.
 *
 * Each rule shows:
 *   - Name (e.g., "TOP → LIMIT")
 *   - Description (Chinese explanation)
 *   - Per-rule confidence badge
 */
import { Typography, Progress, Empty } from "antd";
import { CheckCircleOutlined } from "@ant-design/icons";
import type { AppliedRule } from "../api/sqlRewrite";

const { Text } = Typography;

interface RuleListProps {
  rules: AppliedRule[];
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.9) return "#52c41a";
  if (confidence >= 0.7) return "#1677ff";
  if (confidence >= 0.5) return "#fa8c16";
  return "#ff4d4f";
}

export default function RuleList({ rules }: RuleListProps) {
  if (rules.length === 0) {
    return (
      <Empty
        image={
          <CheckCircleOutlined
            style={{ fontSize: 40, color: "#52c41a" }}
          />
        }
        description="无需改写 — SQL 在目标数据库中完全兼容"
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rules.map((rule, idx) => (
        <div
          key={idx}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 14px",
            background: "#fafafa",
            borderRadius: 8,
            borderLeft: `3px solid ${confidenceColor(rule.confidence)}`,
            gap: 12,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text strong style={{ fontSize: 13, display: "block" }}>
              {rule.name}
            </Text>
            {rule.description && (
              <Text
                type="secondary"
                style={{ fontSize: 12, display: "block", marginTop: 2 }}
              >
                {rule.description}
              </Text>
            )}
          </div>
          <div style={{ width: 80, flexShrink: 0 }}>
            <Progress
              percent={Math.round(rule.confidence * 100)}
              size="small"
              strokeColor={confidenceColor(rule.confidence)}
              trailColor="#f0f0f0"
              format={(pct) => `${pct}%`}
              style={{ margin: 0 }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
