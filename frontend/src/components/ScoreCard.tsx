/**
 * ScoreCard — Displays the overall compatibility score with level badge.
 *
 * Design: Large circular score with color-coded level indicator and
 * weighted breakdown summary.
 */
import { Card, Typography, Tag, Flex, Progress } from "antd";
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import type { ScoreBreakdown } from "../api/sqlScore";

const { Title, Text } = Typography;

interface ScoreCardProps {
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  breakdown: ScoreBreakdown;
  dbCount: number;
  executionTimeMs: number;
}

const LEVEL_CONFIG: Record<
  string,
  { color: string; icon: React.ReactNode; label: string }
> = {
  LOW: {
    color: "#52c41a",
    icon: <CheckCircleOutlined />,
    label: "Low Risk — 兼容性良好",
  },
  MEDIUM: {
    color: "#1677ff",
    icon: <ExclamationCircleOutlined />,
    label: "Medium Risk — 需要注意",
  },
  HIGH: {
    color: "#fa8c16",
    icon: <WarningOutlined />,
    label: "High Risk — 显著迁移成本",
  },
  CRITICAL: {
    color: "#ff4d4f",
    icon: <CloseCircleOutlined />,
    label: "Critical — 重大不兼容",
  },
};

const DIMENSION_LABELS: Record<string, string> = {
  syntax: "语法兼容",
  execution: "执行成功",
  result: "结果一致",
  risk: "风险评估",
};

const SCORE_COLOR = (score: number): string => {
  if (score >= 90) return "#52c41a";
  if (score >= 70) return "#1677ff";
  if (score >= 50) return "#fa8c16";
  return "#ff4d4f";
};

export default function ScoreCard({
  score,
  level,
  breakdown,
  dbCount,
  executionTimeMs,
}: ScoreCardProps) {
  const config = LEVEL_CONFIG[level] || LEVEL_CONFIG.MEDIUM;
  const color = SCORE_COLOR(score);

  return (
    <Card
      styles={{ body: { padding: "24px 32px" } }}
      style={{ borderRadius: 12, overflow: "hidden" }}
    >
      {/* Header: Score + Level */}
      <Flex align="center" gap={24} style={{ marginBottom: 24 }}>
        {/* Circular score indicator */}
        <div style={{ position: "relative", width: 120, height: 120 }}>
          <Progress
            type="circle"
            percent={score}
            format={() => (
              <span style={{ fontSize: 28, fontWeight: 700, color }}>
                {Math.round(score)}
              </span>
            )}
            size={120}
            strokeColor={color}
            trailColor="#f0f0f0"
            strokeWidth={8}
          />
        </div>

        <div style={{ flex: 1 }}>
          <Flex align="center" gap={8} style={{ marginBottom: 8 }}>
            <Title level={3} style={{ margin: 0 }}>
              Compatibility Score
            </Title>
            <Tag
              color={config.color}
              style={{ fontSize: 14, padding: "2px 12px", fontWeight: 600 }}
            >
              {level}
            </Tag>
          </Flex>
          <Text type="secondary" style={{ fontSize: 14 }}>
            <span style={{ color: config.color, marginRight: 4 }}>
              {config.icon}
            </span>
            {config.label}
          </Text>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              评估 {dbCount} 个数据库 • 耗时 {executionTimeMs.toFixed(0)}ms
            </Text>
          </div>
        </div>
      </Flex>

      {/* Dimension breakdown bars */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "12px 24px",
          padding: "16px 0",
          borderTop: "1px solid #f0f0f0",
        }}
      >
        {(Object.keys(breakdown) as (keyof ScoreBreakdown)[]).map((dim) => (
          <div key={dim}>
            <Flex justify="space-between" style={{ marginBottom: 4 }}>
              <Text style={{ fontSize: 13 }}>
                {DIMENSION_LABELS[dim] || dim}
              </Text>
              <Text strong style={{ fontSize: 13, color: SCORE_COLOR(breakdown[dim]) }}>
                {Math.round(breakdown[dim])}%
              </Text>
            </Flex>
            <Progress
              percent={breakdown[dim]}
              showInfo={false}
              size="small"
              strokeColor={SCORE_COLOR(breakdown[dim])}
              trailColor="#f5f5f5"
            />
          </div>
        ))}
      </div>

      {/* Weight note */}
      <Text
        type="secondary"
        style={{ fontSize: 11, display: "block", marginTop: 12 }}
      >
        权重: 语法 30% | 执行 30% | 结果 25% | 风险 15%
      </Text>
    </Card>
  );
}
