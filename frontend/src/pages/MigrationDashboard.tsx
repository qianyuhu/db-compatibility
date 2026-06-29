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
} from "@ant-design/icons";
import PhaseSteps from "../components/PhaseSteps";
import SideBySideResult from "../components/SideBySideResult";
import {
  runMigration,
  verifyMigration,
  validateSql,
  getAllowedTables,
  type MigrationPipelineResponse,
  type VerificationResponse,
  type TableVerificationResult,
  type SqlValidationResult,
} from "../api/business";

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
          `✅ 全部 ${res.totalTables} 张表数据一致，迁移验证通过！`,
        );
      } else {
        message.warning(
          `⚠️ ${res.matchCount}/${res.totalTables} 张表一致，${res.totalTables - res.matchCount} 张表存在差异`,
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
          message="迁移失败"
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
          {pipelineResult.warnings.length > 0 && (
            <Card title="Warnings" style={{ marginTop: 16 }}>
              {pipelineResult.warnings.map((w, i) => (
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
            message={
              verifyResult.verified ? (
                <span>
                  <CheckCircleOutlined /> 全部 {verifyResult.total_tables}{" "}
                  张表数据一致 — 迁移数据已通过验证
                </span>
              ) : (
                <span>
                  <WarningOutlined /> {verifyResult.matchCount} /{" "}
                  {verifyResult.total_tables} 张表一致
                  {verifyResult.total_tables - verifyResult.matchCount >
                    0 && (
                    <span>
                      ，{" "}
                      <Typography.Text type="danger">
                        {verifyResult.total_tables -
                          verifyResult.matchCount}{" "}
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
                sqlResult
                  ? sqlResult.equal
                    ? "inner"
                    : "default"
                  : "default"
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
                    message={
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
                </>
              )}
            </Card>
          );
        })}
      </Card>
    </div>
  );
}
