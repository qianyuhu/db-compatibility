import { useState } from "react";
import {
  Card,
  Button,
  Select,
  Typography,
  Space,
  Alert,
  Spin,
  Collapse,
  Tag,
  Row,
  Col,
  Statistic,
  message,
  Checkbox,
} from "antd";
import {
  RocketOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import PhaseSteps from "../components/PhaseSteps";
import {
  runMigration,
  type MigrationPipelineResponse,
} from "../api/business";

const ALL_PHASES = [
  { label: "Schema", value: "schema" },
  { label: "Data", value: "data" },
  { label: "Validation", value: "validation" },
  { label: "Report", value: "report" },
];

export default function MigrationDashboard() {
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [selectedPhases, setSelectedPhases] = useState<string[]>(["schema", "data", "validation", "report"]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MigrationPipelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRunMigration = async () => {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await runMigration(sourceDb, targetDb, selectedPhases);
      setResult(res);
      if (res.overall_status === "success") {
        message.success("🎉 迁移流水线全部完成，双库完全一致！");
      } else if (res.overall_status === "partial") {
        message.warning("⚠️ 迁移流水线部分完成，存在警告");
      } else {
        message.error("❌ 迁移流水线失败");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      message.error(`迁移失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "success":
        return <CheckCircleOutlined style={{ color: "#52c41a" }} />;
      case "partial":
        return <WarningOutlined style={{ color: "#faad14" }} />;
      case "failed":
        return <CloseCircleOutlined style={{ color: "#ff4d4f" }} />;
      default:
        return null;
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <RocketOutlined /> ERP Migration Pipeline
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        一键触发完整迁移流水线：Schema → Data → Validation → Report
      </Typography.Paragraph>

      {/* Configuration */}
      <Card size="small" style={{ marginBottom: 24 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Typography.Text strong>源库 (Source): </Typography.Text>
            <Select value={sourceDb} onChange={setSourceDb} style={{ width: 140 }}>
              <Select.Option value="mssql">MSSQL</Select.Option>
              <Select.Option value="kingbasees">KingbaseES</Select.Option>
              <Select.Option value="dm8">DM8</Select.Option>
            </Select>
          </Col>
          <Col>
            <Typography.Text strong>→</Typography.Text>
          </Col>
          <Col>
            <Typography.Text strong>目标库 (Target): </Typography.Text>
            <Select value={targetDb} onChange={setTargetDb} style={{ width: 140 }}>
              <Select.Option value="kingbasees">KingbaseES</Select.Option>
              <Select.Option value="dm8">DM8</Select.Option>
              <Select.Option value="mssql">MSSQL</Select.Option>
            </Select>
          </Col>
          <Col flex="auto" />
          <Col>
            <Checkbox.Group
              options={ALL_PHASES}
              value={selectedPhases}
              onChange={(values) => setSelectedPhases(values as string[])}
            />
          </Col>
        </Row>

        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col>
            <Button
              type="primary"
              size="large"
              icon={<RocketOutlined />}
              loading={loading}
              onClick={handleRunMigration}
              danger
            >
              执行完整迁移
            </Button>
          </Col>
          <Col>
            <Button
              size="large"
              icon={<PlayCircleOutlined />}
              loading={loading}
              onClick={handleRunMigration}
            >
              仅验证
            </Button>
          </Col>
          <Col>
            <Button
              size="large"
              icon={<ReloadOutlined />}
              onClick={() => {
                setResult(null);
                setError(null);
              }}
              disabled={loading}
            >
              清空结果
            </Button>
          </Col>
        </Row>
      </Card>

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin size="large" description="迁移流水线运行中..." />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <Alert
          type="error"
          message="迁移失败"
          description={error}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      {/* Results */}
      {result && !loading && (
        <>
          {/* Overall Status */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="总体状态"
                  value={result.overall_status.toUpperCase()}
                  valueStyle={{
                    color:
                      result.overall_status === "success"
                        ? "#52c41a"
                        : result.overall_status === "partial"
                          ? "#faad14"
                          : "#ff4d4f",
                  }}
                  prefix={getStatusIcon(result.overall_status)}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="阶段数"
                  value={`${result.phases.length} / 4`}
                  suffix="完成"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="总耗时"
                  value={result.total_time_ms / 1000}
                  suffix="秒"
                  precision={2}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="警告"
                  value={result.warnings.length}
                  valueStyle={{ color: result.warnings.length > 0 ? "#faad14" : "#52c41a" }}
                />
              </Card>
            </Col>
          </Row>

          {/* Pipeline Steps */}
          <Card title="Pipeline Progress" style={{ marginBottom: 24 }}>
            <PhaseSteps phases={result.phases} overallStatus={result.overall_status} />
          </Card>

          {/* Phase Details */}
          <Card title="Phase Details">
            <Collapse
              items={result.phases.map((phase) => ({
                key: phase.name,
                label: (
                  <Space>
                    {getStatusIcon(phase.status)}
                    <Typography.Text strong>{phase.name}</Typography.Text>
                    <Tag
                      color={
                        phase.status === "success"
                          ? "green"
                          : phase.status === "failed"
                            ? "red"
                            : "default"
                      }
                    >
                      {phase.status}
                    </Tag>
                    <Typography.Text type="secondary">
                      {(phase.elapsed_ms / 1000).toFixed(2)}s
                    </Typography.Text>
                  </Space>
                ),
                children: (
                  <div>
                    {phase.error && (
                      <Alert
                        type="error"
                        message={phase.error}
                        style={{ marginBottom: 8 }}
                      />
                    )}
                    <pre
                      style={{
                        background: "#f6f8fa",
                        padding: 12,
                        borderRadius: 6,
                        fontSize: 12,
                        maxHeight: 300,
                        overflow: "auto",
                      }}
                    >
                      {JSON.stringify(phase.detail, null, 2)}
                    </pre>
                  </div>
                ),
              }))}
            />
          </Card>

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <Card title="Warnings" style={{ marginTop: 16 }}>
              {result.warnings.map((w, i) => (
                <Alert
                  key={i}
                  type="warning"
                  message={w}
                  style={{ marginBottom: 8 }}
                  showIcon
                />
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
