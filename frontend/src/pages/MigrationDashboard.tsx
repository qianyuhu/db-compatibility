import { useState, useCallback, useEffect } from "react";
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
  Divider,
  Table,
  Tooltip,
  Input,
  Progress,
  Badge,
} from "antd";
import {
  RocketOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  BugOutlined,
  ExperimentOutlined,
  ThunderboltOutlined,
  DashboardOutlined,
  CodeOutlined,
} from "@ant-design/icons";
import PhaseSteps from "../components/PhaseSteps";
import SideBySideResult from "../components/SideBySideResult";
import DiffVisualization from "../components/DiffVisualization";
import {
  runMigration,
  verifyMigration,
  validateSql,
  getAllowedTables,
  runSandboxTests,
  resetSandbox,
  getSandboxCases,
  analyzeMigrationRisk,
  preflightRisk,
  getRiskCoverage,
  startExecutionLoop,
  getExecutionState,
  applySingleFix,
  getExecutionReport,
  resetExecutionLoop,
  type MigrationPipelineResponse,
  type VerificationResponse,
  type TableVerificationResult,
  type SqlValidationResult,
  type ThreeLayerDiff,
  type SandboxRunResponse,
  type SandboxCasesResponse,
  type TestCaseResult,
  type TestCaseMeta,
  type RiskScore,
  type ConfidenceScore,
  type CoverageReport,
  type CriticalIssue,
  type RiskIntelligenceResponse,
  type DimensionRisk,
  type MigrationIssue,
  type ExecutionLoopState,
  type ExecutionReport,
  type FixResult,
} from "../api/business";
import {
  analyzeCompatibility,
  type CompatibilityAnalysisResponse,
  type FeatureDetection,
  type DimensionScore,
} from "../api/sqlCompat";

// =========================================================================
// Constants
// =========================================================================

const ALL_PHASES = [
  { label: "Schema", value: "schema" },
  { label: "Data", value: "data" },
  { label: "Validation", value: "validation" },
  { label: "Report", value: "report" },
];

interface PredefinedQuery {
  key: string;
  label: string;
  description: string;
  sql: string;
}

const PREDEFINED_QUERIES: PredefinedQuery[] = [
  {
    key: "customer_count",
    label: "Customer Count",
    description: "验证客户表行数",
    sql: "SELECT COUNT(*) AS cnt FROM customers",
  },
  {
    key: "order_aggregation",
    label: "Order Aggregation",
    description: "按状态聚合订单金额",
    sql: "SELECT status, COUNT(*) AS order_count, SUM(total_amount) AS total FROM orders GROUP BY status ORDER BY status",
  },
  {
    key: "inventory_sum",
    label: "Inventory Sum",
    description: "按仓库聚合库存总量",
    sql: "SELECT warehouse, SUM(quantity) AS total_qty, COUNT(*) AS products FROM inventory GROUP BY warehouse ORDER BY warehouse",
  },
  {
    key: "product_sales",
    label: "Product Sales JOIN",
    description: "产品销售额排行（JOIN 三表）",
    sql: "SELECT p.code, p.name, SUM(oi.subtotal) AS total_sales, SUM(oi.quantity) AS units FROM order_items oi JOIN products p ON oi.product_id = p.id JOIN orders o ON oi.order_id = o.id WHERE o.status != 'CANCELLED' GROUP BY p.code, p.name ORDER BY total_sales DESC",
  },
  {
    key: "customer_orders",
    label: "Customer Order Summary",
    description: "客户订单汇总（LEFT JOIN）",
    sql: "SELECT c.code, c.name, COUNT(o.id) AS total_orders, COALESCE(SUM(o.total_amount), 0) AS total_spent FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.code, c.name ORDER BY total_spent DESC",
  },
];

// =========================================================================
// Helpers
// =========================================================================

const STATUS_CONFIG: Record<
  string,
  { color: string; icon: React.ReactNode; label: string }
> = {
  PASS: {
    color: "#52c41a",
    icon: <CheckCircleOutlined style={{ color: "#52c41a" }} />,
    label: "PASS",
  },
  FAIL: {
    color: "#ff4d4f",
    icon: <CloseCircleOutlined style={{ color: "#ff4d4f" }} />,
    label: "FAIL",
  },
  ERROR: {
    color: "#faad14",
    icon: <WarningOutlined style={{ color: "#faad14" }} />,
    label: "ERROR",
  },
};

function getStatusIcon(status: string) {
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
}

// =========================================================================
// Component
// =========================================================================

export default function MigrationDashboard() {
  // ---- Pipeline State (独立于验证状态) ----
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [selectedPhases, setSelectedPhases] = useState<string[]>([
    "schema",
    "data",
    "validation",
    "report",
  ]);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [pipelineResult, setPipelineResult] =
    useState<MigrationPipelineResponse | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  // ---- Verification State (独立于 pipeline state — P2b) ----
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyLoadingMap, setVerifyLoadingMap] = useState<
    Record<string, boolean>
  >({});
  const [verifyResult, setVerifyResult] =
    useState<VerificationResponse | null>(null);

  // ---- SQL Validation State ----
  const [sqlLoading, setSqlLoading] = useState<Record<string, boolean>>({});
  const [sqlResults, setSqlResults] = useState<
    Record<string, SqlValidationResult>
  >({});
  const [expandedSql, setExpandedSql] = useState<string | null>(null);

  // ---- Allowed tables (fetched from backend — P2c) ----
  const [allowedTables, setAllowedTables] = useState<string[]>([]);

  useEffect(() => {
    getAllowedTables()
      .then(setAllowedTables)
      .catch(() => {
        // Fallback if backend unreachable
        setAllowedTables([
          "customers",
          "products",
          "orders",
          "order_items",
          "inventory",
        ]);
      });
  }, []);

  // =========================================================================
  // Execution Loop State
  // =========================================================================

  const [execLoopLoading, setExecLoopLoading] = useState(false);
  const [execLoopState, setExecLoopState] = useState<ExecutionLoopState | null>(null);
  const [execLoopReport, setExecLoopReport] = useState<ExecutionReport | null>(null);

  const handleStartExecutionLoop = useCallback(async () => {
    setExecLoopLoading(true);
    try {
      const result = await startExecutionLoop(sourceDb, targetDb, 10);
      if (result.success && result.report) {
        setExecLoopReport(result.report);
        message.success(
          `执行循环完成: ${result.report.executive_summary.phase} — ${result.report.executive_summary.recommendation.slice(0, 80)}`
        );
      } else {
        message.warning(result.message);
      }
      // Refresh state
      const stateResult = await getExecutionState();
      if (stateResult.available && stateResult.state) {
        setExecLoopState(stateResult.state);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`执行循环失败: ${msg}`);
    } finally {
      setExecLoopLoading(false);
    }
  }, [sourceDb, targetDb]);

  const handleRefreshExecState = useCallback(async () => {
    try {
      const result = await getExecutionState();
      if (result.available && result.state) {
        setExecLoopState(result.state);
      }
    } catch {
      // Ignore refresh errors
    }
  }, []);

  const handleResetExecLoop = useCallback(async () => {
    try {
      await resetExecutionLoop();
      setExecLoopState(null);
      setExecLoopReport(null);
      message.success("执行循环状态已重置");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`重置失败: ${msg}`);
    }
  }, []);

  const handleApplyExecFix = useCallback(async (issueId: string) => {
    try {
      const result = await applySingleFix(issueId, sourceDb, targetDb);
      if (result.success) {
        message.success(`修复成功: ${result.message}`);
      } else {
        message.warning(`修复失败: ${result.message}`);
      }
      // Refresh state
      await handleRefreshExecState();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`应用修复失败: ${msg}`);
    }
  }, [sourceDb, targetDb, handleRefreshExecState]);

  // =========================================================================
  // Pipeline Actions
  // =========================================================================

  const handleRunMigration = async () => {
    setPipelineLoading(true);
    setPipelineResult(null);
    setPipelineError(null);
    try {
      const res = await runMigration(sourceDb, targetDb, selectedPhases);
      setPipelineResult(res);
      if (res.overall_status === "success") {
        message.success(
          "🎉 迁移流水线全部完成！请运行下方数据验证确认一致性。",
        );
      } else if (res.overall_status === "partial") {
        message.warning("⚠️ 迁移流水线部分完成，存在警告");
      } else {
        message.error("❌ 迁移流水线失败");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPipelineError(msg);
      message.error(`迁移失败: ${msg}`);
    } finally {
      setPipelineLoading(false);
    }
  };

  // P2b: 仅验证不再清除 pipeline 结果 — 两个状态独立维护
  const handleVerifyOnly = async () => {
    setPipelineLoading(true);
    setPipelineError(null);
    try {
      const res = await runMigration(sourceDb, targetDb, [
        "validation",
        "report",
      ]);
      setPipelineResult(res);
      if (res.overall_status === "success") {
        message.success("验证完成，请查看下方验证面板确认数据一致性。");
      } else {
        message.warning("验证完成，但存在警告");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setPipelineError(msg);
      message.error(`验证失败: ${msg}`);
    } finally {
      setPipelineLoading(false);
    }
  };

  // =========================================================================
  // Verification Actions
  // =========================================================================

  const handleVerifyData = useCallback(async () => {
    setVerifyLoading(true);
    try {
      const res = await verifyMigration(sourceDb, targetDb);
      setVerifyResult(res);
      if (res.verified) {
        message.success(
          `✅ 全部 ${res.total_tables} 张表数据一致，迁移验证通过！`
        );
      } else {
        message.warning(
          `⚠️ ${res.match_count}/${res.total_tables} 张表一致，${res.total_tables - res.match_count} 张表存在差异`
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`验证失败: ${msg}`);
    } finally {
      setVerifyLoading(false);
    }
  }, [sourceDb, targetDb]);

  // P2a: 每表独立的 loading 状态
  const handleReVerifyTable = useCallback(
    async (tableName: string) => {
      setVerifyLoadingMap((prev) => ({ ...prev, [tableName]: true }));
      try {
        const res = await verifyMigration(sourceDb, targetDb, [tableName]);
        // Merge single-table result into existing full result
        setVerifyResult((prev) => {
          if (!prev) return res;
          const existingTables = prev.tables.filter(
            (t) => t.table_name !== tableName,
          );
          const merged = [...existingTables, ...res.tables].sort(
            (a, b) =>
              allowedTables.indexOf(a.table_name) -
              allowedTables.indexOf(b.table_name),
          );
          const matchCount = merged.filter(
            (t) => t.status === "PASS",
          ).length;
          return {
            ...res,
            tables: merged,
            match_count: matchCount,
            total_tables: merged.length,
            all_match: matchCount === merged.length,
            verified: matchCount === merged.length,
          };
        });
        const tableResult = res.tables[0];
        if (tableResult?.status === "PASS") {
          message.success(`${tableName} — ✅ PASS`);
        } else {
          message.warning(`${tableName} — ${tableResult?.status}`);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        message.error(`验证 ${tableName} 失败: ${msg}`);
      } finally {
        setVerifyLoadingMap((prev) => ({ ...prev, [tableName]: false }));
      }
    },
    [sourceDb, targetDb, allowedTables],
  );

  // =========================================================================
  // SQL Validation Actions
  // =========================================================================

  const handleRunValidationSql = useCallback(
    async (query: PredefinedQuery) => {
      setSqlLoading((prev) => ({ ...prev, [query.key]: true }));
      try {
        const res = await validateSql(query.sql, sourceDb, targetDb);
        setSqlResults((prev) => ({ ...prev, [query.key]: res }));
        setExpandedSql(query.key);
        if (res.equal) {
          message.success(`${query.label} — ✅ 双库结果一致`);
        } else {
          message.warning(
            `${query.label} — ⚠️ 双库结果存在 ${res.diff_detail.length} 处差异`,
          );
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        message.error(`${query.label} 执行失败: ${msg}`);
      } finally {
        setSqlLoading((prev) => ({ ...prev, [query.key]: false }));
      }
    },
    [sourceDb, targetDb],
  );

  const handleClearAll = () => {
    setPipelineResult(null);
    setPipelineError(null);
    setVerifyResult(null);
    setSqlResults({});
    setExpandedSql(null);
  };

  // =========================================================================
  // Derived State
  // =========================================================================

  const pipelineExecutionSuccess =
    pipelineResult?.overall_status === "success";
  const dataVerified = verifyResult?.verified ?? false;
  const truthStatus: "VERIFIED" | "NOT_VERIFIED" | "NOT_CHECKED" =
    dataVerified
      ? "VERIFIED"
      : verifyResult
        ? "NOT_VERIFIED"
        : "NOT_CHECKED";

  // =========================================================================
  // Render
  // =========================================================================

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <RocketOutlined /> ERP Migration Pipeline
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Database Migration Truth & Verification Console — 执行迁移 + 验证实际数据一致性
      </Typography.Paragraph>

      {/* ================================================================ */}
      {/* Configuration */}
      {/* ================================================================ */}
      <Card size="small" style={{ marginBottom: 24 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Typography.Text strong>源库 (Source): </Typography.Text>
            <Select
              value={sourceDb}
              onChange={setSourceDb}
              style={{ width: 140 }}
            >
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
            <Select
              value={targetDb}
              onChange={setTargetDb}
              style={{ width: 140 }}
            >
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
              loading={pipelineLoading}
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
              loading={pipelineLoading}
              onClick={handleVerifyOnly}
            >
              仅验证
            </Button>
          </Col>
          <Col>
            <Button
              size="large"
              icon={<ReloadOutlined />}
              onClick={handleClearAll}
              disabled={pipelineLoading}
            >
              清空结果
            </Button>
          </Col>
        </Row>
      </Card>

      {/* ================================================================ */}
      {/* Loading */}
      {/* ================================================================ */}
      {pipelineLoading && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin size="large" description="迁移流水线运行中..." />
        </div>
      )}

      {/* ================================================================ */}
      {/* Error */}
      {/* ================================================================ */}
      {pipelineError && !pipelineLoading && (
        <Alert
          type="error"
          title="迁移失败"
          description={pipelineError}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      {/* ================================================================ */}
      {/* Pipeline Results */}
      {/* ================================================================ */}
      {pipelineResult && !pipelineLoading && (
        <>
          {/* Overall Status — split into Execution + Data Verified */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={4}>
              <Card>
                <Statistic
                  title="总体状态"
                  value={pipelineResult.overall_status.toUpperCase()}
                  valueStyle={{
                    color:
                      pipelineResult.overall_status === "success"
                        ? "#52c41a"
                        : pipelineResult.overall_status === "partial"
                          ? "#faad14"
                          : "#ff4d4f",
                  }}
                  prefix={getStatusIcon(pipelineResult.overall_status)}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="阶段数"
                  value={`${pipelineResult.phases.length} / 4`}
                  suffix="完成"
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="总耗时"
                  value={pipelineResult.total_time_ms / 1000}
                  suffix="秒"
                  precision={2}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card>
                <Statistic
                  title="警告"
                  value={pipelineResult.warnings.length}
                  valueStyle={{
                    color:
                      pipelineResult.warnings.length > 0
                        ? "#faad14"
                        : "#52c41a",
                  }}
                />
              </Card>
            </Col>
            {/* Execution Success — standalone indicator */}
            <Col span={4}>
              <Card>
                <Statistic
                  title="Execution Success"
                  value={
                    pipelineExecutionSuccess
                      ? "✔ SUCCESS"
                      : "⚠ PARTIAL/FAILED"
                  }
                  valueStyle={{
                    color: pipelineExecutionSuccess ? "#52c41a" : "#faad14",
                    fontSize: 14,
                  }}
                />
              </Card>
            </Col>
            {/* Data Verified — standalone indicator */}
            <Col span={4}>
              <Card>
                <Statistic
                  title="Data Verified"
                  value={
                    truthStatus === "VERIFIED"
                      ? "✔ VERIFIED"
                      : truthStatus === "NOT_VERIFIED"
                        ? "❌ NOT VERIFIED"
                        : "⚠ NOT CHECKED"
                  }
                  valueStyle={{
                    color:
                      truthStatus === "VERIFIED"
                        ? "#52c41a"
                        : truthStatus === "NOT_VERIFIED"
                          ? "#ff4d4f"
                          : "#faad14",
                    fontSize: 14,
                  }}
                />
              </Card>
            </Col>
          </Row>

          {/* Pipeline Steps */}
          <Card title="Pipeline Progress" style={{ marginBottom: 24 }}>
            <PhaseSteps
              phases={pipelineResult.phases}
              overallStatus={pipelineResult.overall_status}
            />

            {/* Truth Verification Status — inline under final step */}
            <Divider style={{ margin: "16px 0" }} />
            <Row align="middle" justify="space-between">
              <Col>
                <Space>
                  <SafetyCertificateOutlined
                    style={{
                      fontSize: 18,
                      color:
                        truthStatus === "VERIFIED"
                          ? "#52c41a"
                          : truthStatus === "NOT_VERIFIED"
                            ? "#ff4d4f"
                            : "#faad14",
                    }}
                  />
                  <Typography.Text strong>
                    Truth Verification Status:
                  </Typography.Text>
                  <Tag
                    color={
                      truthStatus === "VERIFIED"
                        ? "green"
                        : truthStatus === "NOT_VERIFIED"
                          ? "red"
                          : "gold"
                    }
                    style={{ fontSize: 14, padding: "4px 16px" }}
                  >
                    {truthStatus === "VERIFIED"
                      ? "✔ VERIFIED — 所有表数据一致"
                      : truthStatus === "NOT_VERIFIED"
                        ? "❌ NOT VERIFIED — 存在数据差异"
                        : "⚠ NOT CHECKED — 请运行下方数据验证"}
                  </Tag>
                </Space>
              </Col>
              <Col>
                <Button
                  type="primary"
                  icon={<SafetyCertificateOutlined />}
                  onClick={handleVerifyData}
                  loading={verifyLoading}
                >
                  {verifyResult ? "重新验证全部" : "运行数据验证"}
                </Button>
              </Col>
            </Row>
          </Card>

          {/* Phase Details */}
          <Card title="Phase Details">
            <Collapse
              items={pipelineResult.phases.map((phase) => ({
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
                        title={phase.error}
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
          {pipelineResult.warnings.length > 0 && (
            <Card title="Warnings" style={{ marginTop: 16 }}>
              {pipelineResult.warnings.map((w, i) => (
                <Alert
                  key={i}
                  type="warning"
                  title={w}
                  style={{ marginBottom: 8 }}
                  showIcon
                />
              ))}
            </Card>
          )}
        </>
      )}

      {/* ================================================================ */}
      {/* Section 2: Actual Database Verification Panel */}
      {/* ================================================================ */}
      <Divider style={{ margin: "32px 0 24px" }} />
      <Card
        title={
          <Space>
            <SearchOutlined />
            <span>Actual Database Verification</span>
            <Tag color="blue">直接验证双库实际数据</Tag>
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<SafetyCertificateOutlined />}
            onClick={handleVerifyData}
            loading={verifyLoading}
          >
            验证全部表
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          对每张业务表执行 <code>SELECT COUNT(*)</code> 在{" "}
          {sourceDb.toUpperCase()} 和 {targetDb.toUpperCase()}{" "}
          上，对比行数判断实际数据是否一致。
        </Typography.Paragraph>

        <Table<TableVerificationResult>
          dataSource={verifyResult?.tables ?? []}
          rowKey="table_name"
          loading={verifyLoading}
          pagination={false}
          size="middle"
          locale={{
            emptyText: verifyLoading
              ? "验证中..."
              : "尚未运行验证 — 点击上方按钮开始",
          }}
          columns={[
            {
              title: "Table Name",
              dataIndex: "table_name",
              key: "table_name",
              width: 150,
              render: (name: string) => (
                <Typography.Text code style={{ fontSize: 13 }}>
                  {name}
                </Typography.Text>
              ),
            },
            {
              title: `${sourceDb.toUpperCase()} Count`,
              dataIndex: "source_count",
              key: "source_count",
              width: 150,
              align: "center" as const,
              render: (
                val: number | null,
                record: TableVerificationResult,
              ) =>
                record.source_error ? (
                  <Tooltip title={record.source_error}>
                    <Tag color="red">ERROR</Tag>
                  </Tooltip>
                ) : (
                  <Typography.Text strong>{val ?? "—"}</Typography.Text>
                ),
            },
            {
              title: `${targetDb.toUpperCase()} Count`,
              dataIndex: "target_count",
              key: "target_count",
              width: 150,
              align: "center" as const,
              render: (
                val: number | null,
                record: TableVerificationResult,
              ) =>
                record.target_error ? (
                  <Tooltip title={record.target_error}>
                    <Tag color="red">ERROR</Tag>
                  </Tooltip>
                ) : (
                  <Typography.Text strong>{val ?? "—"}</Typography.Text>
                ),
            },
            {
              title: "Status",
              dataIndex: "status",
              key: "status",
              width: 120,
              align: "center" as const,
              render: (status: string) => {
                const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.ERROR;
                return (
                  <Tag
                    color={
                      cfg.color === "#52c41a"
                        ? "green"
                        : cfg.color === "#ff4d4f"
                          ? "red"
                          : "gold"
                    }
                  >
                    {cfg.icon} {cfg.label}
                  </Tag>
                );
              },
            },
            {
              title: "Actions",
              key: "actions",
              width: 120,
              align: "center" as const,
              render: (_: unknown, record: TableVerificationResult) => (
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={verifyLoadingMap[record.table_name] ?? false}
                  onClick={() => handleReVerifyTable(record.table_name)}
                >
                  Re-Verify
                </Button>
              ),
            },
          ]}
        />

        {/* Summary footer */}
        {verifyResult && (
          <Alert
            type={verifyResult.verified ? "success" : "warning"}
            title={
              verifyResult.verified ? (
                <span>
                  <CheckCircleOutlined /> 全部 {verifyResult.total_tables}{" "}
                  张表数据一致 — 迁移数据已通过验证
                </span>
              ) : (
                <span>
                  <WarningOutlined /> {verifyResult.match_count} /{" "}
                  {verifyResult.total_tables} 张表一致
                  {verifyResult.total_tables - verifyResult.match_count >
                    0 && (
                    <span>
                      ，{" "}
                      <Typography.Text type="danger">
                        {verifyResult.total_tables -
                          verifyResult.match_count}{" "}
                        张表存在差异
                      </Typography.Text>
                    </span>
                  )}
                </span>
              )
            }
            description={
              <Typography.Text type="secondary">
                总耗时: {verifyResult.total_time_ms}ms
              </Typography.Text>
            }
            style={{ marginTop: 16 }}
            showIcon={false}
          />
        )}
      </Card>

      {/* ================================================================ */}
      {/* Section 3: SQL Re-Execution Validation Panel */}
      {/* ================================================================ */}
      <Card
        title={
          <Space>
            <BugOutlined />
            <span>SQL Re-Execution Validation</span>
            <Tag color="purple">手动验证关键业务 SQL</Tag>
          </Space>
        }
        style={{ marginTop: 24 }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          在 {sourceDb.toUpperCase()} 和 {targetDb.toUpperCase()}{" "}
          上分别执行关键业务查询，对比结果确认 SQL 兼容性。
        </Typography.Paragraph>

        {PREDEFINED_QUERIES.map((query) => {
          const sqlResult = sqlResults[query.key];
          const isRunning = sqlLoading[query.key];

          return (
            <Card
              key={query.key}
              size="small"
              style={{ marginBottom: 12 }}
              type={
                sqlResult?.equal ? "inner" : undefined
              }
              title={
                <Space>
                  <Typography.Text strong>{query.label}</Typography.Text>
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 12 }}
                  >
                    {query.description}
                  </Typography.Text>
                  {sqlResult && (
                    <Tag color={sqlResult.equal ? "green" : "red"}>
                      {sqlResult.equal ? "MATCH" : "DIFF"}
                    </Tag>
                  )}
                </Space>
              }
              extra={
                <Space>
                  <Button
                    size="small"
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={isRunning}
                    onClick={() => handleRunValidationSql(query)}
                  >
                    Run
                  </Button>
                </Space>
              }
            >
              {/* SQL display */}
              <pre
                style={{
                  background: "#1e1e1e",
                  color: "#d4d4d4",
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                  marginBottom: sqlResult ? 12 : 0,
                  overflow: "auto",
                  maxHeight: 80,
                }}
              >
                {query.sql}
              </pre>

              {/* Results */}
              {sqlResult && (
                <>
                  <Alert
                    type={sqlResult.equal ? "success" : "warning"}
                    title={
                      sqlResult.equal ? (
                        <span>
                          <CheckCircleOutlined /> 双库执行结果一致 —{" "}
                          {sourceDb.toUpperCase()}:{" "}
                          {sqlResult.source_result.row_count} rows,{" "}
                          {targetDb.toUpperCase()}:{" "}
                          {sqlResult.target_result.row_count} rows
                        </span>
                      ) : (
                        <span>
                          <CloseCircleOutlined /> 双库结果存在{" "}
                          {sqlResult.diff_detail.length} 处差异
                        </span>
                      )
                    }
                    style={{ marginBottom: 12 }}
                    showIcon={false}
                  />

                  {/* 3-Layer Diff Visualization */}
                  {!sqlResult.equal && sqlResult.enhanced_diff && (
                    <Card
                      size="small"
                      title={
                        <span>
                          <BugOutlined /> 差异分析（3-Layer Diff）
                        </span>
                      }
                      style={{ marginBottom: 12 }}
                    >
                      <DiffVisualization
                        enhancedDiff={sqlResult.enhanced_diff}
                        sourceDb={sourceDb}
                        targetDb={targetDb}
                      />
                    </Card>
                  )}

                  {/* Raw side-by-side fallback */}
                  {(!sqlResult.enhanced_diff || sqlResult.equal) && (
                    <Row gutter={16}>
                      <Col span={12}>
                        <Card
                          title={
                            <Tag color="blue">
                              {sourceDb.toUpperCase()} (源库)
                            </Tag>
                          }
                          size="small"
                        >
                          <SideBySideResult
                            dbLabel={sourceDb}
                            color="blue"
                            result={sqlResult.source_result}
                          />
                        </Card>
                      </Col>
                      <Col span={12}>
                        <Card
                          title={
                            <Tag color="green">
                              {targetDb.toUpperCase()} (目标库)
                            </Tag>
                          }
                          size="small"
                        >
                          <SideBySideResult
                            dbLabel={targetDb}
                            color="green"
                            result={sqlResult.target_result}
                          />
                        </Card>
                      </Col>
                    </Row>
                  )}

                  {/* Show raw diff_detail when no enhanced diff */}
                  {!sqlResult.equal && !sqlResult.enhanced_diff && sqlResult.diff_detail.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <Typography.Text strong type="danger">
                        Raw Diff Detail ({sqlResult.diff_detail.length}):
                      </Typography.Text>
                      {sqlResult.diff_detail.map((diff, i) => (
                        <Alert
                          key={i}
                          type="warning"
                          title={
                            <span>
                              <strong>{diff.field}:</strong>{" "}
                              <span style={{ color: "#1677ff" }}>
                                {sourceDb.toUpperCase()}={JSON.stringify(diff.source)}
                              </span>
                              {" ≠ "}
                              <span style={{ color: "#52c41a" }}>
                                {targetDb.toUpperCase()}={JSON.stringify(diff.target)}
                              </span>
                            </span>
                          }
                          style={{ marginTop: 8 }}
                          showIcon={false}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </Card>
          );
        })}
      </Card>

      {/* ================================================================ */}
      {/* Section 4: SQL Compatibility Analysis Panel */}
      {/* ================================================================ */}
      <Card
        title={
          <Space>
            <RocketOutlined />
            <span>SQL Compatibility Analysis</span>
            <Tag color="geekblue">SQL Compatibility Engine</Tag>
          </Space>
        }
        style={{ marginTop: 24 }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          输入 SQL 语句，分析其在 {sourceDb.toUpperCase()} → {targetDb.toUpperCase()}{" "}
          之间的兼容性：分类 → 重写 → 评分 → 可选执行。
        </Typography.Paragraph>

        <CompactCompatAnalyzer
          sourceDb={sourceDb}
          targetDb={targetDb}
        />
      </Card>

      {/* ================================================================ */}
      {/* Section 5: Migration Sandbox Test Harness */}
      {/* ================================================================ */}
      <Card
        title={
          <Space>
            <ExperimentOutlined />
            <span>Migration Sandbox Test Harness</span>
            <Tag color="purple">NEW</Tag>
          </Space>
        }
        style={{ marginTop: 24 }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          基于固定数据集的确定性迁移验证框架。重置沙箱 → 执行测试用例 → 双库对比 → 生成报告。
        </Typography.Paragraph>

        <SandboxTestPanel
          sourceDb={sourceDb}
          targetDb={targetDb}
        />
      </Card>

      {/* ================================================================ */}
      {/* Section 6: Migration Risk Intelligence Panel */}
      {/* ================================================================ */}
      <Card
        title={
          <Space>
            <SafetyCertificateOutlined />
            <span>Migration Risk Intelligence</span>
            <Tag color="volcano">Risk Engine</Tag>
          </Space>
        }
        style={{ marginTop: 24 }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          将测试结果转化为量化风险评估：风险评分 → 置信度 → 覆盖分析 → 迁移就绪判定
        </Typography.Paragraph>

        <RiskIntelligencePanel
          sourceDb={sourceDb}
          targetDb={targetDb}
        />
      </Card>

      {/* ================================================================ */}
      {/* Section 7: Migration Execution Loop Monitor */}
      {/* ================================================================ */}
      <Card
        title={
          <Space>
            <ExperimentOutlined spin={execLoopLoading} />
            <span>Migration Execution Loop Monitor</span>
            <Badge
              status={execLoopState?.is_stabilized ? "success" : execLoopState ? "processing" : "default"}
              text={execLoopState?.is_stabilized ? "已稳定" : execLoopState ? execLoopState.phase : "未启动"}
            />
          </Space>
        }
        style={{ marginTop: 24 }}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          🟢 持续执行与自动修复引擎：运行 → 检测 → 分类 → 修复 → 重跑 → 验证 → 继续。系统永不阻断执行。
        </Typography.Paragraph>

        <ExecutionLoopPanel
          sourceDb={sourceDb}
          targetDb={targetDb}
          loading={execLoopLoading}
          state={execLoopState}
          report={execLoopReport}
          onStart={handleStartExecutionLoop}
          onRefresh={() => handleRefreshExecState()}
          onReset={handleResetExecLoop}
          onApplyFix={handleApplyExecFix}
        />
      </Card>
    </div>
  );
}

// =========================================================================
// Compact Compatibility Analyzer (inline in dashboard)
// =========================================================================

interface CompactCompatAnalyzerProps {
  sourceDb: string;
  targetDb: string;
}

function CompactCompatAnalyzer({ sourceDb, targetDb }: CompactCompatAnalyzerProps) {
  const [sql, setSql] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompatibilityAnalysisResponse | null>(null);
  const [executeMode, setExecuteMode] = useState(false);

  const handleAnalyze = async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await analyzeCompatibility({
        sql: sql.trim(),
        source_db: sourceDb,
        target_db: targetDb,
        execute: executeMode,
      });
      setResult(res);
      if (res.score) {
        message.success(`兼容性评分: ${res.score.total_score} / 100`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`分析失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const FEATURE_CATEGORY_MAP: Record<string, { color: string; label: string }> = {
    SELECT: { color: "green", label: "SELECT" },
    JOIN: { color: "blue", label: "JOIN" },
    GROUP_BY: { color: "cyan", label: "GROUP BY" },
    WINDOW_FUNCTION: { color: "purple", label: "WINDOW" },
    SUBQUERY: { color: "orange", label: "SUBQUERY" },
    LIMIT_TOP: { color: "gold", label: "LIMIT/TOP" },
    MERGE_UPSERT: { color: "red", label: "MERGE" },
    DATE_FUNCTIONS: { color: "magenta", label: "DATE FUNC" },
    CTE: { color: "geekblue", label: "CTE" },
    UNION: { color: "lime", label: "UNION" },
    AGGREGATION: { color: "volcano", label: "AGG" },
    ORDER_BY: { color: "default", label: "ORDER BY" },
    DISTINCT: { color: "default", label: "DISTINCT" },
  };

  return (
    <div>
      {/* SQL Input + Execute toggle */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col flex="auto">
          <Input.TextArea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            placeholder="输入 SQL 语句进行分析..."
            rows={3}
            style={{ fontFamily: "monospace", fontSize: 13 }}
          />
        </Col>
        <Col>
          <Space orientation="vertical">
            <Button
              type="primary"
              icon={<RocketOutlined />}
              loading={loading}
              onClick={handleAnalyze}
            >
              分析兼容性
            </Button>
            <Checkbox
              checked={executeMode}
              onChange={(e) => setExecuteMode(e.target.checked)}
            >
              执行双库对比
            </Checkbox>
          </Space>
        </Col>
      </Row>

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: 20 }}>
          <Spin description="分析中..." />
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div>
          {/* Score card row */}
          {result.score && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card size="small" style={{ textAlign: "center" }}>
                  <Typography.Text type="secondary">兼容性评分</Typography.Text>
                  <div style={{ fontSize: 36, fontWeight: "bold", color: result.score.total_score >= 85 ? "#52c41a" : result.score.total_score >= 70 ? "#faad14" : "#ff4d4f" }}>
                    {result.score.total_score}
                  </div>
                  <Typography.Text type="secondary">/ 100</Typography.Text>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" style={{ textAlign: "center" }}>
                  <Typography.Text type="secondary">风险等级</Typography.Text>
                  <div style={{ marginTop: 8 }}>
                    <Tag color={result.score.overall_risk === "NONE" ? "green" : result.score.overall_risk === "LOW" ? "cyan" : result.score.overall_risk === "MEDIUM" ? "orange" : result.score.overall_risk === "HIGH" ? "red" : "red"}>
                      {result.score.overall_risk}
                    </Tag>
                  </div>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" style={{ textAlign: "center" }}>
                  <Typography.Text type="secondary">复杂度</Typography.Text>
                  <div style={{ marginTop: 8 }}>
                    <Tag color={result.classification?.complexity === "simple" ? "green" : result.classification?.complexity === "medium" ? "orange" : "red"}>
                      {result.classification?.complexity || "—"}
                    </Tag>
                  </div>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" style={{ textAlign: "center" }}>
                  <Typography.Text type="secondary">耗时</Typography.Text>
                  <div style={{ fontSize: 20, fontWeight: "bold", marginTop: 4 }}>
                    {result.total_time_ms}ms
                  </div>
                </Card>
              </Col>
            </Row>
          )}

          {/* Dimension scores */}
          {result.score && result.score.dimensions.length > 0 && (
            <Collapse
              size="small"
              style={{ marginBottom: 12 }}
              items={[
                {
                  key: "dimensions",
                  label: (
                    <span>
                      <Typography.Text strong>📊 评分维度详情</Typography.Text>
                    </span>
                  ),
                  children: (
                    <Table<DimensionScore>
                      dataSource={result.score.dimensions}
                      rowKey="name"
                      pagination={false}
                      size="small"
                      columns={[
                        { title: "维度", dataIndex: "name", key: "name", width: 120 },
                        {
                          title: "得分",
                          dataIndex: "percentage",
                          key: "percentage",
                          width: 80,
                          align: "center",
                          render: (pct: number) => (
                            <Typography.Text
                              strong
                              style={{ color: pct >= 80 ? "#52c41a" : pct >= 50 ? "#faad14" : "#ff4d4f" }}
                            >
                              {pct.toFixed(0)}%
                            </Typography.Text>
                          ),
                        },
                        {
                          title: "权重",
                          dataIndex: "weight",
                          key: "weight",
                          width: 60,
                          align: "center",
                          render: (w: number) => `${(w * 100).toFixed(0)}%`,
                        },
                        {
                          title: "扣分原因",
                          dataIndex: "deductions",
                          key: "deductions",
                          render: (deductions: string[]) =>
                            deductions.length > 0 ? (
                              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                                {deductions.map((d, i) => (
                                  <li key={i}>{d}</li>
                                ))}
                              </ul>
                            ) : (
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                无扣分
                              </Typography.Text>
                            ),
                        },
                      ]}
                    />
                  ),
                },
              ]}
            />
          )}

          {/* Rewritten SQL */}
          {result.rewritten_sql && result.rewritten_sql !== result.original_sql && (
            <Card size="small" title="🔄 Rewritten SQL" style={{ marginBottom: 12 }}>
              <Row gutter={16}>
                <Col span={12}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    原始 SQL ({sourceDb.toUpperCase()})
                  </Typography.Text>
                  <pre style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 8, borderRadius: 4, fontSize: 12, overflow: "auto", maxHeight: 100 }}>
                    {result.original_sql}
                  </pre>
                </Col>
                <Col span={12}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    改写 SQL ({targetDb.toUpperCase()})
                  </Typography.Text>
                  <pre style={{ background: "#1e1e1e", color: "#52c41a", padding: 8, borderRadius: 4, fontSize: 12, overflow: "auto", maxHeight: 100 }}>
                    {result.rewritten_sql}
                  </pre>
                </Col>
              </Row>
            </Card>
          )}

          {/* Classification features */}
          {result.classification && result.classification.features.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong style={{ display: "block", marginBottom: 8 }}>
                🔍 检测到的 SQL 特性:
              </Typography.Text>
              <Space wrap>
                {result.classification.categories.map((cat) => {
                  const cfg = FEATURE_CATEGORY_MAP[cat] ?? { color: "default", label: cat };
                  return (
                    <Tag key={cat} color={cfg.color}>
                      {cfg.label}
                    </Tag>
                  );
                })}
              </Space>

              {/* Feature detail table */}
              <Table<FeatureDetection>
                dataSource={result.classification.features}
                rowKey="category"
                pagination={false}
                size="small"
                style={{ marginTop: 8 }}
                columns={[
                  { title: "特性", dataIndex: "category", key: "category", width: 150 },
                  { title: "数量", dataIndex: "count", key: "count", width: 60, align: "center" },
                  {
                    title: "详情",
                    dataIndex: "details",
                    key: "details",
                    render: (details: string[]) => details.join(", "),
                  },
                  {
                    title: "风险",
                    dataIndex: "risk",
                    key: "risk",
                    width: 80,
                    align: "center",
                    render: (risk: string) => {
                      const colors: Record<string, string> = {
                        none: "default",
                        low: "green",
                        medium: "orange",
                        high: "red",
                        blocker: "red",
                      };
                      return <Tag color={colors[risk] || "default"}>{risk.toUpperCase()}</Tag>;
                    },
                  },
                ]}
              />
            </div>
          )}

          {/* Risk tags */}
          {result.score && result.score.risk_tags.length > 0 && result.score.risk_tags[0] !== "NONE" && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>🏷️ 风险标签: </Typography.Text>
              <Space wrap>
                {result.score.risk_tags.map((tag) => (
                  <Tag key={tag} color={tag === "BLOCKER" ? "red" : tag === "HIGH" ? "orange" : tag === "MEDIUM" ? "gold" : "green"}>
                    {tag}
                  </Tag>
                ))}
              </Space>
            </div>
          )}

          {/* Execution result */}
          {result.execution_result && (
            <Card size="small" title="⚡ 双库执行结果" style={{ marginBottom: 12 }}>
              <Row gutter={16}>
                <Col span={12}>
                  <Typography.Text>{sourceDb.toUpperCase()} (源库): </Typography.Text>
                  <Typography.Text strong style={{ color: result.execution_result.source_success ? "#52c41a" : "#ff4d4f" }}>
                    {result.execution_result.source_success ? "✓ 成功" : "✗ 失败"} · {String(result.execution_result.source_row_count ?? 0)} rows
                  </Typography.Text>
                </Col>
                <Col span={12}>
                  <Typography.Text>{targetDb.toUpperCase()} (目标库): </Typography.Text>
                  <Typography.Text strong style={{ color: result.execution_result.target_success ? "#52c41a" : "#ff4d4f" }}>
                    {result.execution_result.target_success ? "✓ 成功" : "✗ 失败"} · {String(result.execution_result.target_row_count ?? 0)} rows
                  </Typography.Text>
                </Col>
              </Row>
              <Alert
                type={result.execution_result.equal ? "success" : "warning"}
                title={result.execution_result.equal ? "双库结果一致 ✅" : "双库结果存在差异 ⚠️"}
                style={{ marginTop: 8 }}
                showIcon={false}
              />
            </Card>
          )}

          {/* Enhanced diff (if any) */}
          {result.enhanced_diff && (
            <Card size="small" title="🔬 差异详情 (3-Layer Diff)" style={{ marginBottom: 12 }}>
              <DiffVisualization
                enhancedDiff={result.enhanced_diff as unknown as ThreeLayerDiff}
                sourceDb={sourceDb}
                targetDb={targetDb}
              />
            </Card>
          )}

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <Alert
              type="warning"
              title="分析警告"
              description={result.warnings.join("; ")}
              style={{ marginTop: 8 }}
              showIcon
            />
          )}
        </div>
      )}
    </div>
  );
}

// =========================================================================
// Sandbox Test Harness Panel
// =========================================================================

interface SandboxTestPanelProps {
  sourceDb: string;
  targetDb: string;
}

function SandboxTestPanel({ sourceDb, targetDb }: SandboxTestPanelProps) {
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [runningSingle, setRunningSingle] = useState<string | null>(null);
  const [report, setReport] = useState<SandboxRunResponse | null>(null);
  const [cases, setCases] = useState<TestCaseMeta[]>([]);
  const [casesLoaded, setCasesLoaded] = useState(false);
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());
  const [filterTag, setFilterTag] = useState<string | null>(null);

  useEffect(() => {
    getSandboxCases()
      .then((data) => {
        setCases(data.cases);
        setCasesLoaded(true);
      })
      .catch(() => {
        message.warning("无法加载测试用例列表");
      });
  }, []);

  const handleRunAll = useCallback(async () => {
    setLoading(true);
    try {
      const result = await runSandboxTests(sourceDb, targetDb);
      setReport(result);
      message.success(
        `测试完成: ${result.report.passed}/${result.report.total_tests} 通过 (${result.report.success_rate}%)`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`测试运行失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [sourceDb, targetDb]);

  const handleRunSmoke = useCallback(async () => {
    setLoading(true);
    try {
      const result = await runSandboxTests(sourceDb, targetDb, { tags: "smoke" });
      setReport(result);
      message.success(
        `烟雾测试完成: ${result.report.passed}/${result.report.total_tests} 通过`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`测试运行失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [sourceDb, targetDb]);

  const handleRunSingle = useCallback(async (testId: string) => {
    setRunningSingle(testId);
    try {
      const result = await runSandboxTests(sourceDb, targetDb, { test_ids: testId });
      setReport(result);
      const tc = result.report.results[0];
      if (tc) {
        message.success(`[${tc.status}] ${tc.test_name}`);
        setExpandedResults((prev) => new Set([...prev, testId]));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`测试运行失败: ${msg}`);
    } finally {
      setRunningSingle(null);
    }
  }, [sourceDb, targetDb]);

  const handleReset = useCallback(async () => {
    setResetting(true);
    try {
      await resetSandbox(sourceDb, targetDb);
      message.success("沙箱数据已重置");
      setReport(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`重置失败: ${msg}`);
    } finally {
      setResetting(false);
    }
  }, [sourceDb, targetDb]);

  const toggleExpand = useCallback((testId: string) => {
    setExpandedResults((prev) => {
      const next = new Set(prev);
      if (next.has(testId)) {
        next.delete(testId);
      } else {
        next.add(testId);
      }
      return next;
    });
  }, []);

  const filteredCases = filterTag
    ? cases.filter((c) => c.tags.includes(filterTag))
    : cases;

  const allTags = Array.from(new Set(cases.flatMap((c) => c.tags))).sort();

  const CATEGORY_COLORS: Record<string, string> = {
    schema: "default",
    sql_crud: "blue",
    sql_aggregation: "cyan",
    sql_join: "geekblue",
    sql_edge: "orange",
  };

  const STATUS_ICON: Record<string, React.ReactNode> = {
    PASS: <CheckCircleOutlined style={{ color: "#52c41a" }} />,
    FAIL: <CloseCircleOutlined style={{ color: "#ff4d4f" }} />,
    ERROR: <WarningOutlined style={{ color: "#faad14" }} />,
    SKIPPED: <span style={{ color: "#999" }}>—</span>,
  };

  const seedOk = report?.seed_results
    ? Object.values(report.seed_results).every((s) => s.success)
    : null;

  return (
    <div>
      {/* Action Bar */}
      <Space wrap style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleRunAll}
          loading={loading}
          size="large"
        >
          Run All Tests ({cases.length} cases)
        </Button>
        <Button
          icon={<PlayCircleOutlined />}
          onClick={handleRunSmoke}
          loading={loading}
        >
          Run Smoke Tests
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={handleReset}
          loading={resetting}
          danger
        >
          Reset Sandbox
        </Button>
        <Divider orientation="vertical" />
        <Select
          placeholder="Filter by tag"
          value={filterTag}
          onChange={setFilterTag}
          allowClear
          style={{ minWidth: 140 }}
          options={allTags.map((t) => ({ value: t, label: t }))}
        />
      </Space>

      {/* Seed Status */}
      {report && (
        <Alert
          type={seedOk ? "success" : seedOk === false ? "error" : "info"}
          title={
            seedOk
              ? "沙箱数据已就绪（MSSQL + KingbaseES 双库种子数据一致）"
              : seedOk === false
                ? "沙箱数据种子失败"
                : "沙箱状态未知"
          }
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}

      {/* Summary Stats */}
      {report && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="成功率"
                value={report.report.success_rate}
                suffix="%"
                valueStyle={{
                  color: report.report.success_rate >= 90 ? "#52c41a" : "#faad14",
                }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="通过"
                value={report.report.passed}
                valueStyle={{ color: "#52c41a" }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="失败"
                value={report.report.failed}
                valueStyle={{
                  color: report.report.failed > 0 ? "#ff4d4f" : undefined,
                }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="错误"
                value={report.report.errors}
                valueStyle={{
                  color: report.report.errors > 0 ? "#faad14" : undefined,
                }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="总数"
                value={report.report.total_tests}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="耗时"
                value={report.total_time_ms / 1000}
                suffix="s"
                precision={1}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Category Breakdown */}
      {report && Object.keys(report.report.summary_by_category).length > 0 && (
        <Card size="small" title="按类别统计" style={{ marginBottom: 16 }}>
          <Row gutter={[8, 8]}>
            {Object.entries(report.report.summary_by_category).map(([cat, summary]) => (
              <Col key={cat} xs={12} sm={8} md={6} lg={4}>
                <Card size="small" style={{ textAlign: "center" }}>
                  <Tag color={CATEGORY_COLORS[cat] || "default"}>{cat}</Tag>
                  <div style={{ marginTop: 4 }}>
                    <span style={{ color: "#52c41a", fontWeight: "bold" }}>
                      {summary.passed}
                    </span>
                    {" / "}
                    <span style={{ color: summary.failed > 0 ? "#ff4d4f" : undefined }}>
                      {summary.failed}
                    </span>
                    {" / "}
                    <span>{summary.total}</span>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* Failure Drilldown */}
      {report && report.report.failed > 0 && (
        <Alert
          type="warning"
          title={`失败详情 (${report.report.failed} 项)`}
          description={
            <div>
              {report.report.results
                .filter((r) => r.status === "FAIL")
                .map((r) => (
                  <div key={r.test_id} style={{ marginBottom: 8 }}>
                    <Tag color="error">FAIL</Tag>
                    <strong>{r.test_name}</strong>
                    <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                      {r.diff_summary}
                    </Typography.Text>
                    {r.error_message && (
                      <div style={{ marginTop: 4, color: "#ff4d4f" }}>
                        错误: {r.error_message}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          }
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}

      {/* Test Case List */}
      <Card
        size="small"
        title={
          <Space>
            <CodeOutlined />
            <span>
              测试用例
              {casesLoaded && ` (${filteredCases.length} cases)`}
            </span>
          </Space>
        }
      >
        {!casesLoaded ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <Spin />
          </div>
        ) : (
          <div style={{ maxHeight: 600, overflow: "auto" }}>
            {filteredCases.map((tc) => {
              const result: TestCaseResult | undefined = report?.report.results.find(
                (r) => r.test_id === tc.id
              );
              const isExpanded = expandedResults.has(tc.id);
              const isRunning = runningSingle === tc.id;

              return (
                <Card
                  key={tc.id}
                  size="small"
                  style={{ marginBottom: 8 }}
                  title={
                    <Space size="small">
                      {result ? STATUS_ICON[result.status] : <span style={{ color: "#999" }}>○</span>}
                      <Tag color={CATEGORY_COLORS[tc.category] || "default"}>
                        {tc.category}
                      </Tag>
                      <strong>{tc.name}</strong>
                      {result && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {result.total_time_ms.toFixed(0)}ms
                        </Typography.Text>
                      )}
                    </Space>
                  }
                  extra={
                    <Space size="small">
                      {tc.tags.map((t) => (
                        <Tag key={t} style={{ fontSize: 10 }}>{t}</Tag>
                      ))}
                      <Button
                        size="small"
                        type="primary"
                        icon={<PlayCircleOutlined />}
                        loading={isRunning}
                        onClick={() => handleRunSingle(tc.id)}
                      >
                        Run
                      </Button>
                      {result && (
                        <Button
                          size="small"
                          type="link"
                          onClick={() => toggleExpand(tc.id)}
                        >
                          {isExpanded ? "收起" : "详情"}
                        </Button>
                      )}
                    </Space>
                  }
                >
                  <Typography.Paragraph
                    type="secondary"
                    style={{ margin: 0, fontSize: 13 }}
                  >
                    {tc.description}
                  </Typography.Paragraph>

                  {tc.known_issues.length > 0 && (
                    <Alert
                      type="info"
                      title="已知差异"
                      description={tc.known_issues.join("; ")}
                      style={{ marginTop: 8, fontSize: 12 }}
                      showIcon
                    />
                  )}

                  {result && isExpanded && (
                    <div style={{ marginTop: 12 }}>
                      <Row gutter={8} style={{ marginBottom: 12 }}>
                        <Col span={8}>
                          <Typography.Text strong>行数匹配: </Typography.Text>
                          {result.row_count_match === null ? (
                            <Tag>N/A</Tag>
                          ) : result.row_count_match ? (
                            <Tag color="success">✅ 匹配</Tag>
                          ) : (
                            <Tag color="error">❌ 不一致</Tag>
                          )}
                        </Col>
                        <Col span={8}>
                          <Typography.Text strong>数据匹配: </Typography.Text>
                          {result.data_match === null ? (
                            <Tag>N/A</Tag>
                          ) : result.data_match ? (
                            <Tag color="success">✅ 一致</Tag>
                          ) : (
                            <Tag color="error">❌ 差异</Tag>
                          )}
                        </Col>
                        <Col span={8}>
                          <Typography.Text strong>列匹配: </Typography.Text>
                          {result.column_match === null ? (
                            <Tag>N/A</Tag>
                          ) : result.column_match ? (
                            <Tag color="success">✅ 一致</Tag>
                          ) : (
                            <Tag color="error">❌ 不一致</Tag>
                          )}
                        </Col>
                      </Row>

                      <Row gutter={8} style={{ marginBottom: 12 }}>
                        <Col span={8}>
                          <Typography.Text type="secondary">
                            MSSQL: {result.source_execution_time_ms.toFixed(0)}ms
                          </Typography.Text>
                        </Col>
                        <Col span={8}>
                          <Typography.Text type="secondary">
                            {targetDb.toUpperCase()}: {result.target_execution_time_ms.toFixed(0)}ms
                          </Typography.Text>
                        </Col>
                      </Row>

                      {result.diff_summary && (
                        <Alert
                          type={result.status === "PASS" ? "success" : "warning"}
                          title="差异摘要"
                          description={result.diff_summary}
                          style={{ marginBottom: 12 }}
                          showIcon
                        />
                      )}

                      {result.error_message && (
                        <Alert
                          type="error"
                          title="执行错误"
                          description={result.error_message}
                          style={{ marginBottom: 12 }}
                          showIcon
                        />
                      )}

                      {result.diff_detail.length > 0 && (
                        <Table
                          size="small"
                          pagination={false}
                          dataSource={result.diff_detail.map((d, i) => ({
                            ...d,
                            key: i,
                          }))}
                          columns={[
                            { title: "字段", dataIndex: "field", key: "field", width: 140 },
                            {
                              title: `源值 (${sourceDb.toUpperCase()})`,
                              dataIndex: "source",
                              key: "source",
                              render: (v: string) => (
                                <Typography.Text code style={{ fontSize: 11 }}>
                                  {v}
                                </Typography.Text>
                              ),
                            },
                            {
                              title: `目标值 (${targetDb.toUpperCase()})`,
                              dataIndex: "target",
                              key: "target",
                              render: (v: string) => (
                                <Typography.Text code style={{ fontSize: 11 }}>
                                  {v}
                                </Typography.Text>
                              ),
                            },
                            {
                              title: "类别",
                              dataIndex: "category",
                              key: "category",
                              width: 100,
                              render: (c: string) => <Tag>{c}</Tag>,
                            },
                          ]}
                          style={{ marginBottom: 12 }}
                        />
                      )}

                      {result.enhanced_diff && (
                        <Card size="small" title="3-Layer Diff">
                          <DiffVisualization
                            enhancedDiff={result.enhanced_diff as unknown as ThreeLayerDiff}
                            sourceDb={sourceDb}
                            targetDb={targetDb}
                          />
                        </Card>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

// =========================================================================
// Risk Intelligence Panel
// =========================================================================

interface RiskIntelligencePanelProps {
  sourceDb: string;
  targetDb: string;
}

function RiskIntelligencePanel({ sourceDb, targetDb }: RiskIntelligencePanelProps) {
  const [loading, setLoading] = useState(false);
  const [riskData, setRiskData] = useState<RiskIntelligenceResponse | null>(null);
  const [coverageData, setCoverageData] = useState<CoverageReport | null>(null);
  const [preflightData, setPreflightData] = useState<Record<string, unknown> | null>(null);

  const handleAnalyze = useCallback(async () => {
    setLoading(true);
    try {
      const result = await analyzeMigrationRisk(sourceDb, targetDb);
      setRiskData(result);
      message.success(
        `风险分析完成: ${result.migration_readiness} (风险评分: ${result.risk_score?.total_score ?? "N/A"})`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`风险分析失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [sourceDb, targetDb]);

  const handlePreflight = useCallback(async () => {
    setLoading(true);
    try {
      const result = await preflightRisk(sourceDb, targetDb);
      setPreflightData(result as unknown as Record<string, unknown>);
      message.success(`预检完成: ${result.estimated_readiness}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`预检失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [sourceDb, targetDb]);

  const handleCoverage = useCallback(async () => {
    try {
      const result = await getRiskCoverage();
      setCoverageData(result);
      message.success(`覆盖分析完成: ${result.overall_coverage}%`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      message.error(`覆盖分析失败: ${msg}`);
    }
  }, []);

  const riskGaugeColor = (score: number) => {
    if (score <= 20) return "#52c41a";
    if (score <= 40) return "#73d13d";
    if (score <= 60) return "#faad14";
    if (score <= 80) return "#ff7a45";
    return "#ff4d4f";
  };

  const confidenceColor = (score: number) => {
    if (score >= 80) return "#52c41a";
    if (score >= 60) return "#1677ff";
    if (score >= 40) return "#faad14";
    return "#ff4d4f";
  };

  const readinessBadge: Record<string, { color: string; text: string }> = {
    SAFE: { color: "green", text: "可直接迁移" },
    LOW_RISK: { color: "cyan", text: "低风险" },
    MEDIUM_RISK: { color: "gold", text: "中等风险" },
    HIGH_RISK: { color: "orange", text: "高风险" },
    BLOCKER: { color: "red", text: "存在阻断" },
  };

  return (
    <div>
      {/* Action Bar */}
      <Space wrap style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          onClick={handleAnalyze}
          loading={loading}
          size="large"
        >
          Run Full Risk Analysis
        </Button>
        <Button icon={<SearchOutlined />} onClick={handlePreflight} loading={loading}>
          Pre-Flight Check
        </Button>
        <Button onClick={handleCoverage}>
          Coverage Analysis
        </Button>
      </Space>

      {/* Risk Intelligence Dashboard */}
      {riskData && riskData.risk_score && (
        <div>
          {/* Top Row: Risk + Confidence + Readiness + Coverage Gauges */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card size="small" style={{ textAlign: "center" }}>
                <Typography.Text type="secondary">Risk Score</Typography.Text>
                <div style={{ margin: "12px 0" }}>
                  <Progress
                    type="dashboard"
                    percent={riskData.risk_score.total_score}
                    strokeColor={riskGaugeColor(riskData.risk_score.total_score)}
                    format={(pct) => (
                      <div>
                        <div style={{ fontSize: 28, fontWeight: "bold" }}>{pct}</div>
                        <div style={{ fontSize: 12, color: riskGaugeColor(riskData.risk_score.total_score) }}>
                          {riskData.risk_score?.risk_level}
                        </div>
                      </div>
                    )}
                    size={140}
                  />
                </div>
              </Card>
            </Col>

            <Col span={6}>
              <Card size="small" style={{ textAlign: "center" }}>
                <Typography.Text type="secondary">Confidence</Typography.Text>
                <div style={{ margin: "12px 0" }}>
                  <Progress
                    type="dashboard"
                    percent={riskData.confidence_score?.total_score ?? 0}
                    strokeColor={confidenceColor(riskData.confidence_score?.total_score ?? 0)}
                    format={(pct) => (
                      <div>
                        <div style={{ fontSize: 28, fontWeight: "bold" }}>{pct}</div>
                        <div style={{ fontSize: 12 }}>
                          {riskData.confidence_score?.level ?? "N/A"}
                        </div>
                      </div>
                    )}
                    size={140}
                  />
                </div>
              </Card>
            </Col>

            <Col span={6}>
              <Card size="small" style={{ textAlign: "center", height: "100%" }}>
                <Typography.Text type="secondary">Migration Readiness</Typography.Text>
                <div style={{ marginTop: 24 }}>
                  <Tag
                    color={readinessBadge[riskData.migration_readiness]?.color || "default"}
                    style={{ fontSize: 18, padding: "8px 16px" }}
                  >
                    {readinessBadge[riskData.migration_readiness]?.text || riskData.migration_readiness}
                  </Tag>
                </div>
                <div style={{ marginTop: 12 }}>
                  <Badge
                    status={
                      (riskData.confidence_score?.total_score ?? 0) >= 70 ? "success" : "error"
                    }
                    text={
                      (riskData.confidence_score?.total_score ?? 0) >= 70
                        ? "Production-Ready"
                        : "Not Recommended"
                    }
                  />
                </div>
              </Card>
            </Col>

            <Col span={6}>
              <Card size="small" style={{ textAlign: "center" }}>
                <Typography.Text type="secondary">Coverage</Typography.Text>
                <div style={{ margin: "12px 0" }}>
                  <Progress
                    type="dashboard"
                    percent={riskData.coverage_report?.overall_coverage ?? 0}
                    strokeColor={{ "0%": "#1677ff", "100%": "#52c41a" }}
                    format={(pct) => (
                      <div>
                        <div style={{ fontSize: 28, fontWeight: "bold" }}>{pct}%</div>
                        <div style={{ fontSize: 12 }}>Overall</div>
                      </div>
                    )}
                    size={140}
                  />
                </div>
              </Card>
            </Col>
          </Row>

          {/* Risk Dimension Breakdown */}
          <Card size="small" title="Risk Dimension Breakdown" style={{ marginBottom: 16 }}>
            {riskData.risk_score.dimensions.map((dim: DimensionRisk) => (
              <div key={dim.name} style={{ marginBottom: 12 }}>
                <Row align="middle" gutter={8}>
                  <Col span={5}>
                    <Typography.Text strong>{dim.name}</Typography.Text>
                    <Typography.Text type="secondary" style={{ marginLeft: 4 }}>
                      (×{dim.weight})
                    </Typography.Text>
                  </Col>
                  <Col span={13}>
                    <Tooltip
                      title={
                        dim.deductions.length > 0
                          ? `Deductions: ${dim.deductions.join("; ")}`
                          : "No deductions"
                      }
                    >
                      <Progress
                        percent={dim.raw_score}
                        strokeColor={riskGaugeColor(dim.raw_score)}
                        format={(pct) => `${pct}%`}
                        status={dim.raw_score > 60 ? "exception" : "active"}
                      />
                    </Tooltip>
                  </Col>
                  <Col span={6}>
                    <Space size="small">
                      <Typography.Text type="secondary">
                        Weighted: {dim.weighted_score}
                      </Typography.Text>
                      <Tag
                        color={
                          dim.risk_level === "SAFE" ? "green" :
                          dim.risk_level === "LOW" ? "cyan" :
                          dim.risk_level === "MEDIUM" ? "gold" :
                          dim.risk_level === "HIGH" ? "orange" : "red"
                        }
                      >
                        {dim.risk_level}
                      </Tag>
                    </Space>
                  </Col>
                </Row>
              </div>
            ))}
          </Card>

          {/* Coverage Detail */}
          {riskData.coverage_report && (
            <Card size="small" title="Coverage Detail" style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                {(["sql_coverage", "api_coverage", "orm_coverage"] as const).map((key) => {
                  const dim = riskData.coverage_report![key];
                  if (!dim) return null;
                  return (
                    <Col span={8} key={key}>
                      <Card size="small" style={{ textAlign: "center" }}>
                        <Typography.Text strong>{dim.name}</Typography.Text>
                        <div style={{ margin: "8px 0" }}>
                          <Progress
                            percent={dim.percentage}
                            strokeColor={{ "0%": "#ff4d4f", "50%": "#faad14", "100%": "#52c41a" }}
                            format={(pct) => `${pct?.toFixed(0)}%`}
                          />
                        </div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {dim.tested} / {dim.total} covered
                        </Typography.Text>
                        {dim.missing_items.length > 0 && (
                          <div style={{ marginTop: 8, textAlign: "left" }}>
                            <Typography.Text type="danger" style={{ fontSize: 11 }}>
                              Missing: {dim.missing_items.slice(0, 3).join(", ")}
                            </Typography.Text>
                          </div>
                        )}
                      </Card>
                    </Col>
                  );
                })}
              </Row>
            </Card>
          )}

          {/* Confidence Breakdown */}
          {riskData.confidence_score && (
            <Card size="small" title="Confidence Formula" style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                <Col span={6}>
                  <Card size="small" style={{ textAlign: "center" }}>
                    <Statistic
                      title="Pass Rate"
                      value={riskData.confidence_score.pass_rate_score}
                      suffix="pts"
                      valueStyle={{ color: "#52c41a" }}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>(40% weight)</Typography.Text>
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small" style={{ textAlign: "center" }}>
                    <Statistic
                      title="Coverage"
                      value={riskData.confidence_score.coverage_score}
                      suffix="pts"
                      valueStyle={{ color: "#1677ff" }}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>(35% weight)</Typography.Text>
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small" style={{ textAlign: "center" }}>
                    <Statistic
                      title="Risk Penalty"
                      value={riskData.confidence_score.risk_penalty}
                      suffix="pts"
                      valueStyle={{ color: "#ff4d4f" }}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>(25% penalty)</Typography.Text>
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small" style={{ textAlign: "center" }}>
                    <Statistic
                      title="Final Confidence"
                      value={riskData.confidence_score.total_score}
                      suffix="pts"
                      valueStyle={{
                        color: confidenceColor(riskData.confidence_score.total_score),
                        fontWeight: "bold",
                      }}
                    />
                  </Card>
                </Col>
              </Row>

              {riskData.confidence_score.recommendation && (
                <Alert
                  type={
                    riskData.confidence_score.level === "HIGH" ? "success" :
                    riskData.confidence_score.level === "MEDIUM" ? "warning" : "error"
                  }
                  title={riskData.confidence_score.recommendation}
                  style={{ marginTop: 12 }}
                  showIcon
                />
              )}
            </Card>
          )}

          {/* Top 5 Risks */}
          {riskData.top_risks.length > 0 && (
            <Card size="small" title="Top 5 Critical Risks" style={{ marginBottom: 16 }}>
              {riskData.top_risks.map((risk: string, idx: number) => (
                <Alert
                  key={idx}
                  type={idx === 0 ? "error" : "warning"}
                  title={risk}
                  style={{ marginBottom: 8 }}
                  showIcon
                />
              ))}
            </Card>
          )}

          {/* Critical Issues Table */}
          {riskData.critical_issues && riskData.critical_issues.length > 0 && (
            <Card size="small" title="Critical Issues">
              <Table
                size="small"
                pagination={false}
                dataSource={riskData.critical_issues.map((ci: CriticalIssue, i: number) => ({
                  ...ci,
                  key: i,
                }))}
                columns={[
                  {
                    title: "Severity",
                    dataIndex: "severity",
                    key: "severity",
                    width: 90,
                    render: (s: string) => (
                      <Tag
                        color={
                          s === "BLOCKER" ? "red" :
                          s === "HIGH" ? "orange" :
                          s === "MEDIUM" ? "gold" : "blue"
                        }
                      >
                        {s}
                      </Tag>
                    ),
                  },
                  { title: "Test", dataIndex: "test_name", key: "test_name", width: 180 },
                  { title: "Category", dataIndex: "category", key: "category", width: 90 },
                  {
                    title: "Description",
                    dataIndex: "description",
                    key: "description",
                    ellipsis: true,
                  },
                  {
                    title: "Root Cause",
                    dataIndex: "root_cause",
                    key: "root_cause",
                    ellipsis: true,
                  },
                ]}
                style={{ marginTop: 8 }}
              />
            </Card>
          )}
        </div>
      )}

      {/* Preflight Results */}
      {preflightData && !riskData && (
        <Card size="small" title="Pre-Flight Results" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="Est. SQL Risk" value={preflightData.estimated_sql_risk as number} suffix="/100" />
            </Col>
            <Col span={6}>
              <Statistic title="Rewrites Needed" value={preflightData.rewrite_required_count as number} />
            </Col>
            <Col span={6}>
              <Statistic title="Known Issues" value={preflightData.known_issue_count as number} />
            </Col>
            <Col span={6}>
              <Statistic title="Est. Readiness" value={preflightData.estimated_readiness as string} />
            </Col>
          </Row>
        </Card>
      )}

      {/* Coverage Standalone */}
      {coverageData && !riskData && (
        <Card size="small" title="Coverage Analysis" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            {(["sql_coverage", "api_coverage", "orm_coverage"] as const).map((key) => {
              const dim = coverageData[key];
              if (!dim) return null;
              return (
                <Col span={8} key={key}>
                  <Card size="small" style={{ textAlign: "center" }}>
                    <Typography.Text strong>{dim.name}</Typography.Text>
                    <Progress
                      percent={dim.percentage}
                      strokeColor={{ "0%": "#ff4d4f", "50%": "#faad14", "100%": "#52c41a" }}
                      format={(pct) => `${pct?.toFixed(0)}%`}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {dim.tested} / {dim.total}
                    </Typography.Text>
                    {dim.missing_items.length > 0 && (
                      <div style={{ marginTop: 4 }}>
                        {dim.missing_items.slice(0, 4).map((item) => (
                          <Tag key={item} color="error" style={{ fontSize: 10, marginBottom: 2 }}>
                            {item}
                          </Tag>
                        ))}
                      </div>
                    )}
                  </Card>
                </Col>
              );
            })}
          </Row>
          {coverageData.critical_gaps.length > 0 && (
            <Alert
              type="warning"
              title="Critical Coverage Gaps"
              description={coverageData.critical_gaps.join("; ")}
              style={{ marginTop: 12 }}
              showIcon
            />
          )}
        </Card>
      )}

      {/* Empty State */}
      {!riskData && !preflightData && !coverageData && !loading && (
        <Alert
          type="info"
          title="Click a button above to start risk analysis"
          description={
            <div>
              <p><strong>Full Risk Analysis</strong>: Run complete tests + multi-dimensional risk scoring + confidence assessment</p>
              <p><strong>Pre-Flight Check</strong>: Estimate risk from test definitions only (no DB execution)</p>
              <p><strong>Coverage Analysis</strong>: Analyze test coverage and identify blind spots</p>
            </div>
          }
          showIcon
        />
      )}
    </div>
  );
}

// =========================================================================
// Execution Loop Monitor Panel
// =========================================================================

interface ExecutionLoopPanelProps {
  sourceDb: string;
  targetDb: string;
  loading: boolean;
  state: ExecutionLoopState | null;
  report: ExecutionReport | null;
  onStart: () => void;
  onRefresh: () => void;
  onReset: () => void;
  onApplyFix: (issueId: string) => void;
}

function ExecutionLoopPanel({
  sourceDb,
  targetDb,
  loading,
  state,
  report,
  onStart,
  onRefresh,
  onReset,
  onApplyFix,
}: ExecutionLoopPanelProps) {
  const [fixingIds, setFixingIds] = useState<Set<string>>(new Set());

  const handleFix = async (issueId: string) => {
    setFixingIds((prev) => new Set(prev).add(issueId));
    try {
      await onApplyFix(issueId);
    } finally {
      setFixingIds((prev) => {
        const next = new Set(prev);
        next.delete(issueId);
        return next;
      });
    }
  };

  // Issue lifecycle color mapping
  const statusColor = (status: string): string => {
    const map: Record<string, string> = {
      NEW: "blue",
      IDENTIFIED: "orange",
      FIXING: "processing",
      FIXED: "cyan",
      VERIFIED: "green",
      RESOLVED: "success",
      REGRESSED: "red",
    };
    return map[status] || "default";
  };

  const severityColor = (severity: string): string => {
    const map: Record<string, string> = {
      LOW: "green",
      MEDIUM: "orange",
      HIGH: "red",
      BLOCKER: "#ff0000",
    };
    return map[severity] || "default";
  };

  const issueTypeLabel = (type: string): string => {
    const map: Record<string, string> = {
      SQL_REWRITE: "SQL",
      SCHEMA_MAPPING: "Schema",
      DATA_PRECISION: "Data",
      ORM_BEHAVIOR: "ORM",
      API_CONTRACT: "API",
    };
    return map[type] || type;
  };

  const phaseStatus = (phase: string): "success" | "processing" | "warning" | "default" => {
    if (phase === "STABILIZED") return "success";
    if (phase === "MAX_ITERATIONS") return "warning";
    if (phase === "INIT") return "default";
    return "processing";
  };

  // Issue stats from state
  const stats = state?.issue_stats || null;
  const issues = state?.issues || report?.issues || [];

  return (
    <div>
      {/* 操作按钮 */}
      <Space wrap style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={loading}
          onClick={onStart}
        >
          启动执行循环
        </Button>
        <Button icon={<ReloadOutlined />} onClick={onRefresh} disabled={loading}>
          刷新状态
        </Button>
        <Button
          danger
          icon={<CloseCircleOutlined />}
          onClick={onReset}
          disabled={loading || !state}
        >
          重置循环
        </Button>
      </Space>

      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" />
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 12 }}>
            执行循环运行中... 检测 → 分类 → 生成修复策略 → 应用修复 → 重跑受影响测试 → 验证
          </Typography.Text>
        </div>
      )}

      {/* 状态概览 */}
      {state && !loading && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="当前阶段"
                  value={state.phase}
                  valueStyle={{ fontSize: 16 }}
                  prefix={
                    <Badge status={phaseStatus(state.phase)} />
                  }
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="迭代次数"
                  value={state.current_iteration}
                  suffix={`/ ${state.max_iterations}`}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="连续无问题轮数"
                  value={state.consecutive_clean_runs}
                  valueStyle={{ color: state.is_stabilized ? "#52c41a" : undefined }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="是否已稳定"
                  value={state.is_stabilized ? "✅ 已稳定" : "⏳ 未稳定"}
                  valueStyle={{
                    color: state.is_stabilized ? "#52c41a" : "#faad14",
                    fontSize: 18,
                  }}
                />
              </Card>
            </Col>
          </Row>

          {/* 问题生命周期统计 */}
          {stats && (
            <Card size="small" title="问题生命周期" style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                {[
                  { label: "总计", value: stats.total, color: "#1890ff" },
                  { label: "待处理", value: stats.open, color: "#fa8c16" },
                  { label: "已修复", value: stats.fixed, color: "#13c2c2" },
                  { label: "已验证", value: stats.verified, color: "#52c41a" },
                  { label: "已解决", value: stats.resolved, color: "#389e0d" },
                  { label: "已回归", value: stats.regressed, color: "#ff4d4f" },
                ].map((item) => (
                  <Col span={4} key={item.label}>
                    <Statistic
                      title={item.label}
                      value={item.value}
                      valueStyle={{ color: item.color, fontSize: 20 }}
                    />
                  </Col>
                ))}
              </Row>
            </Card>
          )}

          {/* 修复进度 */}
          <Card size="small" title="修复进度" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="尝试修复次数" value={state.total_fix_attempts} />
              </Col>
              <Col span={8}>
                <Statistic
                  title="修复成功"
                  value={state.successful_fixes}
                  valueStyle={{ color: "#52c41a" }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="修复失败"
                  value={state.failed_fixes}
                  valueStyle={{ color: state.failed_fixes > 0 ? "#ff4d4f" : undefined }}
                />
              </Col>
            </Row>
          </Card>

          {/* 问题列表表格 */}
          {issues.length > 0 && (
            <Card size="small" title={`问题列表 (${issues.length})`} style={{ marginBottom: 16 }}>
              <Table
                dataSource={issues.map((issue, idx) => ({ ...issue, key: idx }))}
                size="small"
                pagination={{ pageSize: 5 }}
                columns={[
                  {
                    title: "状态",
                    dataIndex: "status",
                    width: 110,
                    render: (s: string) => {
                      const statusText: Record<string, string> = {
                        NEW: "新建",
                        IDENTIFIED: "已识别",
                        FIXING: "修复中",
                        FIXED: "已修复",
                        VERIFIED: "已验证",
                        RESOLVED: "已解决",
                        REGRESSED: "已回归",
                      };
                      return <Badge status={statusColor(s) as "success" | "processing"} text={statusText[s] || s} />;
                    },
                  },
                  {
                    title: "类型",
                    dataIndex: "issue_type",
                    width: 80,
                    render: (t: string) => {
                      const typeText: Record<string, string> = {
                        SQL_REWRITE: "SQL改写",
                        SCHEMA_MAPPING: "Schema映射",
                        DATA_PRECISION: "数据精度",
                        ORM_BEHAVIOR: "ORM行为",
                        API_CONTRACT: "API契约",
                      };
                      return <Tag>{typeText[t] || t}</Tag>;
                    },
                  },
                  {
                    title: "严重程度",
                    dataIndex: "severity",
                    width: 80,
                    render: (s: string) => {
                      const sevText: Record<string, string> = {
                        LOW: "低",
                        MEDIUM: "中",
                        HIGH: "高",
                        BLOCKER: "阻断",
                      };
                      return <Tag color={severityColor(s)}>{sevText[s] || s}</Tag>;
                    },
                  },
                  {
                    title: "测试用例",
                    dataIndex: "test_name",
                    ellipsis: true,
                    width: 160,
                  },
                  {
                    title: "问题描述",
                    dataIndex: "description",
                    ellipsis: true,
                  },
                  {
                    title: "修复次数",
                    dataIndex: "fix_attempts",
                    width: 80,
                    align: "center" as const,
                  },
                  {
                    title: "操作",
                    key: "action",
                    width: 80,
                    render: (_: unknown, record: MigrationIssue) => {
                      const canFix = ["NEW", "IDENTIFIED", "FIXING", "REGRESSED"].includes(record.status);
                      const isFixing = fixingIds.has(record.issue_id);
                      return canFix ? (
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          loading={isFixing}
                          onClick={() => handleFix(record.issue_id)}
                        >
                          修复
                        </Button>
                      ) : (
                        <Tag color={statusColor(record.status)}>
                          {{ NEW: "新建", IDENTIFIED: "已识别", FIXING: "修复中", FIXED: "已修复", VERIFIED: "已验证", RESOLVED: "已解决", REGRESSED: "已回归" }[record.status] || record.status}
                        </Tag>
                      );
                    },
                  },
                ]}
              />
            </Card>
          )}

          {/* 循环迭代历史 */}
          {state.iterations && state.iterations.length > 0 && (
            <Card size="small" title={`循环迭代历史 (${state.iterations.length})`} style={{ marginBottom: 16 }}>
              <Table
                dataSource={state.iterations.map((it, idx) => ({ ...it, key: idx }))}
                size="small"
                pagination={{ pageSize: 5 }}
                columns={[
                  { title: "轮次", dataIndex: "iteration", width: 50 },
                  { title: "阶段", dataIndex: "phase", width: 120, render: (p: string) => <Tag>{p}</Tag> },
                  { title: "执行测试数", dataIndex: "tests_run", width: 90, align: "center" as const },
                  {
                    title: "通过",
                    dataIndex: "tests_passed",
                    width: 60,
                    align: "center" as const,
                    render: (v: number, r: Record<string, unknown>) => (
                      <span style={{ color: v === (r.tests_run as number) ? "#52c41a" : undefined }}>{v}</span>
                    ),
                  },
                  {
                    title: "失败",
                    dataIndex: "tests_failed",
                    width: 60,
                    align: "center" as const,
                    render: (v: number) => (
                      <span style={{ color: v > 0 ? "#ff4d4f" : "#52c41a" }}>{v}</span>
                    ),
                  },
                  { title: "检测到问题", dataIndex: "issues_detected", width: 100, align: "center" as const },
                  { title: "已修复问题", dataIndex: "issues_fixed", width: 100, align: "center" as const },
                  { title: "摘要", dataIndex: "summary", ellipsis: true },
                ]}
              />
            </Card>
          )}

          {/* 报告摘要 */}
          {report && (
            <Alert
              type={report.executive_summary.phase === "STABILIZED" ? "success" : "warning"}
              title={
                report.executive_summary.phase === "STABILIZED"
                  ? "✅ 执行循环已稳定"
                  : `⚠️ 循环阶段: ${report.executive_summary.phase}`
              }
              description={
                <div>
                  <p>{report.executive_summary.recommendation}</p>
                  <Space wrap>
                    <Tag>通过测试: {report.test_summary.passed}/{report.test_summary.total_tests}</Tag>
                    <Tag color="blue">部分成功: {report.test_summary.partial_success}</Tag>
                    <Tag color="green">已解决问题: {report.issue_summary.issues_resolved}</Tag>
                    <Tag color="orange">进行中: {report.issue_summary.issues_in_progress}</Tag>
                    {report.issue_summary.issues_regressed > 0 && (
                      <Tag color="red">已回归: {report.issue_summary.issues_regressed}</Tag>
                    )}
                    <Tag>修复成功/总数: {report.fix_summary.fixes_succeeded}/{report.fix_summary.fixes_applied}</Tag>
                  </Space>
                  {report.remaining_blockers.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <Typography.Text strong type="danger">剩余阻断问题:</Typography.Text>
                      <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                        {report.remaining_blockers.map((b, i) => (
                          <li key={i}><Typography.Text type="danger">{b}</Typography.Text></li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              }
              showIcon
            />
          )}
        </>
      )}

      {/* 空状态 */}
      {!state && !loading && (
        <Alert
          type="info"
          title="执行循环尚未启动"
          description={
            <div>
              <p><strong>启动执行循环</strong>：运行完整的 检测 → 分类 → 修复 → 重跑 → 验证 闭环流程</p>
              <p>🟢 <strong>系统永不阻断执行</strong> — 每个失败自动转化为可追踪、可修复的问题</p>
              <p>📊 <strong>监控内容</strong>：问题生命周期、修复进度、循环迭代历史、系统稳定状态</p>
              <p>💡 <strong>使用步骤</strong>：</p>
              <ol>
                <li>点击 <strong>"启动执行循环"</strong> 按钮开始自动检测与修复</li>
                <li>观察 <strong>"问题列表"</strong> 表格，点击单个问题的 <strong>"修复"</strong> 按钮手动触发修复</li>
                <li>查看 <strong>"循环迭代历史"</strong> 了解每轮检测/修复结果</li>
                <li>当 <strong>"是否已稳定"</strong> 显示绿色 ✅，表示系统达到稳定状态</li>
                <li>使用 <strong>"刷新状态"</strong> 获取最新进展；使用 <strong>"重置循环"</strong> 清空重新开始</li>
              </ol>
            </div>
          }
          showIcon
        />
      )}
    </div>
  );
}
