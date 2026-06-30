/**
 * Execution Timeline — bottom panel showing node execution order.
 *
 * Horizontal scrollable list of executed nodes with timing and status.
 * Click a node to jump to it in the graph.
 */

import { Tag, Typography } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";

const { Text } = Typography;

interface TimelineEntry {
  nodeId: string;
  status: string;
  executionTimeMs: number;
}

interface ExecutionTimelineProps {
  entries: TimelineEntry[];
  onNodeClick: (nodeId: string) => void;
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  success: <CheckCircleOutlined style={{ color: "#52c41a" }} />,
  failed: <CloseCircleOutlined style={{ color: "#ff4d4f" }} />,
  running: <ClockCircleOutlined style={{ color: "#1677ff" }} />,
  paused: <PauseCircleOutlined style={{ color: "#fa8c16" }} />,
  skipped: <PauseCircleOutlined style={{ color: "#8c8c8c" }} />,
  pending: <ClockCircleOutlined style={{ color: "#d9d9d9" }} />,
};

export default function ExecutionTimeline({
  entries,
  onNodeClick,
}: ExecutionTimelineProps) {
  if (entries.length === 0) {
    return (
      <div style={{ padding: "8px 16px", color: "#8c8c8c", fontSize: 13 }}>
        No nodes executed yet. Click a node and press "Run Node" to start.
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        overflowX: "auto",
        padding: "8px 16px",
        whiteSpace: "nowrap",
      }}
    >
      {entries.map((entry, i) => (
        <div key={`${entry.nodeId}-${i}`} style={{ display: "flex", alignItems: "center", gap: 0 }}>
          {/* Connector arrow (not for first item) */}
          {i > 0 && (
            <Text type="secondary" style={{ fontSize: 18, margin: "0 4px" }}>
              →
            </Text>
          )}

          {/* Node badge */}
          <div
            onClick={() => onNodeClick(entry.nodeId)}
            style={{
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 6,
              border: "1px solid #e8e8e8",
              background: "#fff",
              transition: "box-shadow 0.2s",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 8px rgba(0,0,0,0.1)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow = "";
            }}
          >
            {STATUS_ICONS[entry.status] || STATUS_ICONS.pending}
            <Tag style={{ margin: 0, fontSize: 11 }}>{entry.nodeId}</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {entry.executionTimeMs > 0
                ? `${entry.executionTimeMs.toFixed(0)}ms`
                : ""}
            </Text>
          </div>
        </div>
      ))}
    </div>
  );
}
