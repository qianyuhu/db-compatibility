/**
 * ConfidenceBadge — Shows the overall rewrite confidence as a color-coded badge.
 *
 * Colors:
 *   ≥ 90% → green (high confidence)
 *   ≥ 70% → blue (medium confidence)
 *   ≥ 50% → orange (low confidence)
 *   < 50% → red (needs manual review)
 */
import { Tag } from "antd";
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";

interface ConfidenceBadgeProps {
  confidence: number; // 0.0 - 1.0
}

const CONFIDENCE_CONFIG: Record<
  string,
  { color: string; icon: React.ReactNode; label: string }
> = {
  high: {
    color: "#52c41a",
    icon: <CheckCircleOutlined />,
    label: "高置信度",
  },
  medium: {
    color: "#1677ff",
    icon: <ExclamationCircleOutlined />,
    label: "中等置信度",
  },
  low: {
    color: "#fa8c16",
    icon: <WarningOutlined />,
    label: "低置信度",
  },
  review: {
    color: "#ff4d4f",
    icon: <CloseCircleOutlined />,
    label: "需人工审核",
  },
};

function getLevel(confidence: number): string {
  if (confidence >= 0.9) return "high";
  if (confidence >= 0.7) return "medium";
  if (confidence >= 0.5) return "low";
  return "review";
}

export default function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const pct = Math.round(confidence * 100);
  const level = getLevel(confidence);
  const config = CONFIDENCE_CONFIG[level];

  return (
    <Tag
      color={config.color}
      style={{
        fontSize: 14,
        padding: "4px 16px",
        fontWeight: 600,
        borderRadius: 20,
      }}
    >
      {config.icon}
      <span style={{ marginLeft: 6 }}>
        {config.label} — {pct}%
      </span>
    </Tag>
  );
}
