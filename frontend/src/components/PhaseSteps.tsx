import { Steps, Tag, Typography } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import type { MigrationPhaseSummary } from "../api/business";

interface Props {
  phases: MigrationPhaseSummary[];
  overallStatus: string;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircleOutlined style={{ color: "#52c41a" }} />,
  partial: <CheckCircleOutlined style={{ color: "#faad14" }} />,
  failed: <CloseCircleOutlined style={{ color: "#ff4d4f" }} />,
  pending: <ClockCircleOutlined style={{ color: "#d9d9d9" }} />,
  running: <LoadingOutlined style={{ color: "#1677ff" }} />,
};

const STATUS_COLOR: Record<string, string> = {
  success: "green",
  partial: "orange",
  failed: "red",
  pending: "default",
  running: "blue",
};

export default function PhaseSteps({ phases, overallStatus }: Props) {
  if (phases.length === 0) {
    return (
      <Typography.Text type="secondary">
        等待迁移流水线启动...
      </Typography.Text>
    );
  }

  const current =
    phases.findIndex((p) => p.status === "running" || p.status === "pending") ??
    phases.length;

  const items = phases.map((phase) => ({
    title: phase.name,
    description: (
      <div>
        <Tag color={STATUS_COLOR[phase.status] || "default"}>
          {phase.status.toUpperCase()}
        </Tag>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          {phase.elapsed_ms > 0 ? `${(phase.elapsed_ms / 1000).toFixed(1)}s` : ""}
        </Typography.Text>
        {phase.error && (
          <Typography.Text type="danger" style={{ fontSize: 11, display: "block" }}>
            {phase.error}
          </Typography.Text>
        )}
      </div>
    ),
    icon: STATUS_ICON[phase.status] || STATUS_ICON.pending,
  }));

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Typography.Text strong>Pipeline Status: </Typography.Text>
        <Tag
          color={
            overallStatus === "success"
              ? "green"
              : overallStatus === "partial"
                ? "orange"
                : overallStatus === "failed"
                  ? "red"
                  : "default"
          }
        >
          {overallStatus.toUpperCase()}
        </Tag>
      </div>

      <Steps
        direction="vertical"
        size="small"
        current={current}
        items={items}
      />
    </div>
  );
}
