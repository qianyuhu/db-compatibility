/**
 * SQL Intelligence Kernel Dashboard — unified entry point for all 5 engines.
 *
 * Single SQL input → shared semantic context → all engines run in parallel.
 * Results displayed in a dashboard grid: Overview, Diagnostics, Rewrite,
 * Migration, Simulation.
 */

import { useState, useCallback } from "react";
import {
  Card,
  Button,
  Select,
  Tag,
  Spin,
  Alert,
  Row,
  Col,
  Descriptions,
  Statistic,
  Progress,
  Table,
  Timeline,
  Checkbox,
  Space,
  Typography,
  Badge,
  Divider,
} from "antd";
import {
  DashboardOutlined,
  BugOutlined,
  ThunderboltOutlined,
  RocketOutlined,
  PlayCircleOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import { analyzeKernel, type EngineName, type KernelResponse, type KernelDecision } from "../api/sqlKernel";

const { Title, Text, Paragraph } = Typography;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DB_OPTIONS = [
  { value: "mssql", label: "MSSQL (SQL Server 2022)", color: "#1677ff" },
  { value: "kingbasees", label: "KingbaseES (人大金仓)", color: "#52c41a" },
  { value: "dm8", label: "DM8 (达梦)", color: "#fa8c16" },
];

const ENGINE_OPTIONS: { key: EngineName; label: string; icon: React.ReactNode; desc: string }[] = [
  { key: "diagnostics", label: "Diagnostics", icon: <BugOutlined />, desc: "对象级兼容性诊断" },
  { key: "rewrite", label: "Rewrite", icon: <ThunderboltOutlined />, desc: "SQL 方言自动改写" },
  { key: "migration", label: "Migration", icon: <RocketOutlined />, desc: "迁移可行性 + 分步计划" },
  { key: "simulation", label: "Simulation", icon: <PlayCircleOutlined />, desc: "执行行为预测 + 风险裁决" },
];

const DEFAULT_ENGINES: EngineName[] = ["diagnostics", "rewrite", "migration", "simulation"];

const DEFAULT_SQL = `SELECT TOP 10 id, name, GETDATE() AS current_time
FROM [users]
WHERE ISNULL(status, 0) = 1
ORDER BY created_at DESC`;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SqlKernel() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [engines, setEngines] = useState<EngineName[]>([...DEFAULT_ENGINES]);
  const [result, setResult] = useState<KernelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await analyzeKernel({
        sql,
        source_db: sourceDb,
        target_db: targetDb,
        engines: engines.length > 0 ? engines : undefined,
      });
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [sql, sourceDb, targetDb, engines]);

  const handleEngineToggle = useCallback((engine: EngineName, checked: boolean) => {
    setEngines((prev) =>
      checked ? [...prev, engine] : prev.filter((e) => e !== engine),
    );
  }, []);

  // ------------------------------------------------------------------
  // Render helpers
  // ------------------------------------------------------------------

  const renderToolbar = () => (
    <div style={{ marginBottom: 16 }}>
      <Row gutter={[16, 12]} align="middle">
        <Col>
          <span style={{ fontWeight: 600, marginRight: 8 }}>源数据库:</span>
          <Select
            value={sourceDb}
            onChange={setSourceDb}
            style={{ width: 240 }}
            options={DB_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
        </Col>
        <Col>
          <Text type="secondary" style={{ fontSize: 18 }}>
            →
          </Text>
        </Col>
        <Col>
          <span style={{ fontWeight: 600, marginRight: 8 }}>目标数据库:</span>
          <Select
            value={targetDb}
            onChange={setTargetDb}
            style={{ width: 240 }}
            options={DB_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
        </Col>
        <Col flex="auto" />
        <Col>
          <Button
            type="primary"
            icon={<DashboardOutlined />}
            onClick={handleAnalyze}
            loading={loading}
            size="large"
          >
            Analyze All
          </Button>
        </Col>
      </Row>
      <div style={{ marginTop: 12, display: "flex", gap: 16, flexWrap: "wrap" }}>
        {ENGINE_OPTIONS.map((opt) => (
          <Checkbox
            key={opt.key}
            checked={engines.includes(opt.key)}
            onChange={(e) => handleEngineToggle(opt.key, e.target.checked)}
          >
            <Space size={4}>
              {opt.icon}
              <Text>{opt.label}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                ({opt.desc})
              </Text>
            </Space>
          </Checkbox>
        ))}
      </div>
    </div>
  );

  const renderDecisionPanel = () => {
    if (!result?.decision) return null;
    const d = result.decision as KernelDecision;

    const recConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
      SAFE: { color: "#52c41a", icon: <CheckCircleOutlined />, label: "安全迁移" },
      REVIEW: { color: "#fa8c16", icon: <WarningOutlined />, label: "需要审查" },
      BLOCK: { color: "#ff4d4f", icon: <CloseCircleOutlined />, label: "阻止迁移" },
    };
    const rc = recConfig[d.recommendation] || { color: "#d9d9d9", icon: null, label: d.recommendation };

    const pathConfig: Record<string, { color: string; label: string }> = {
      DIRECT: { color: "#52c41a", label: "直接执行" },
      AUTO_REWRITE: { color: "#1677ff", label: "自动改写" },
      PARTIAL: { color: "#fa8c16", label: "部分自动 + 人工" },
      MANUAL: { color: "#ff4d4f", label: "手动迁移" },
    };
    const pc = pathConfig[d.migration_path] || { color: "#d9d9d9", label: d.migration_path };

    const confidencePct = Math.round(d.confidence * 100);
    const scoreColor = d.score >= 85 ? "#52c41a" : d.score >= 70 ? "#fa8c16" : "#ff4d4f";

    return (
      <Card
        title={
          <span>
            <Tag color={rc.color} style={{ fontSize: 16, padding: "4px 16px", marginRight: 12 }}>
              {rc.icon} {rc.label}
            </Tag>
            <Text type="secondary">Migration Decision</Text>
          </span>
        }
        style={{ borderLeft: `4px solid ${rc.color}`, marginBottom: 16 }}
      >
        <Row gutter={[24, 16]} align="middle">
          {/* Confidence Gauge */}
          <Col span={6} style={{ textAlign: "center" }}>
            <Progress
              type="dashboard"
              percent={confidencePct}
              size={100}
              format={() => `${confidencePct}%`}
              status={confidencePct >= 80 ? "success" : confidencePct >= 50 ? "normal" : "exception"}
            />
            <div style={{ marginTop: 4 }}>
              <Text type="secondary">综合置信度</Text>
            </div>
          </Col>

          {/* Key Metrics */}
          <Col span={10}>
            <Descriptions column={1} size="small" colon={false}>
              <Descriptions.Item label="Migration Path">
                <Tag color={pc.color}>{pc.label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Score">
                <Text strong style={{ color: scoreColor, fontSize: 18 }}>{d.score.toFixed(0)}</Text>
                <Text type="secondary"> / 100</Text>
              </Descriptions.Item>
              <Descriptions.Item label="Rewrites Applied">
                <Text>{d.rewrite_rules_applied} rules</Text>
                <Text type="secondary"> (confidence: {(d.rewrite_confidence * 100).toFixed(0)}%)</Text>
              </Descriptions.Item>
              <Descriptions.Item label="Simulation Verdict">
                <Text>{d.simulation_verdict?.replace(/_/g, " ") || "N/A"}</Text>
              </Descriptions.Item>
            </Descriptions>
          </Col>

          {/* Risks Summary */}
          <Col span={8}>
            <Text strong>Risk Summary</Text>
            <div style={{ marginTop: 8 }}>
              <Row gutter={[8, 4]}>
                {d.risk_counts?.CRITICAL > 0 && (
                  <Col span={12}><Tag color="magenta">CRITICAL: {d.risk_counts.CRITICAL}</Tag></Col>
                )}
                {d.risk_counts?.HIGH > 0 && (
                  <Col span={12}><Tag color="red">HIGH: {d.risk_counts.HIGH}</Tag></Col>
                )}
                {d.risk_counts?.MEDIUM > 0 && (
                  <Col span={12}><Tag color="orange">MEDIUM: {d.risk_counts.MEDIUM}</Tag></Col>
                )}
                {d.risk_counts?.LOW > 0 && (
                  <Col span={12}><Tag color="blue">LOW: {d.risk_counts.LOW}</Tag></Col>
                )}
                {Object.values(d.risk_counts || {}).every((v) => v === 0) && (
                  <Col span={24}><Tag color="green">No Risks</Tag></Col>
                )}
              </Row>
            </div>

            {d.blocking_issues.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Text type="danger" strong>Blocking Issues:</Text>
                {d.blocking_issues.slice(0, 3).map((issue, i) => (
                  <div key={i} style={{ fontSize: 12, color: "#ff4d4f", marginTop: 2 }}>
                    • {issue}
                  </div>
                ))}
              </div>
            )}

            {d.primary_risks.length > 0 && d.blocking_issues.length === 0 && (
              <div style={{ marginTop: 12 }}>
                <Text type="warning" strong>Primary Risks:</Text>
                {d.primary_risks.slice(0, 3).map((risk, i) => (
                  <div key={i} style={{ fontSize: 12, color: "#fa8c16", marginTop: 2 }}>
                    • {risk}
                  </div>
                ))}
              </div>
            )}
          </Col>
        </Row>

        {/* Execution Strategy */}
        {d.execution_strategy && (
          <Alert
            type={d.recommendation === "SAFE" ? "success" : d.recommendation === "REVIEW" ? "warning" : "error"}
            title="Execution Strategy"
            description={<pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>{d.execution_strategy}</pre>}
            style={{ marginTop: 16 }}
          />
        )}

        {/* Explanation */}
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{d.explanation}</Text>
        </div>
      </Card>
    );
  };

  const renderOverview = () => {
    if (!result) return null;

    const diag = result.diagnostics as Record<string, unknown> | null;
    const rewrite = result.rewrite as Record<string, unknown> | null;
    const migration = result.migration as Record<string, unknown> | null;
    const simulation = result.simulation as Record<string, unknown> | null;

    const summary = (diag?.summary as Record<string, unknown>) || {};
    const totalObjects = (summary.total_objects as number) || 0;
    const rewriteApplied = ((rewrite?.rules_applied as unknown[]) || []).length;
    const rewriteConf = ((rewrite?.confidence as number) || 0) * 100;
    const migrationScore = (migration?.estimated_score as number) || 0;
    const simScore = ((simulation?.equivalence_score as number) || 0) * 100;
    const simVerdict = (simulation?.recommendation as string) || "N/A";

    const verdictColor: Record<string, string> = {
      SAFE_TO_EXECUTE: "#52c41a",
      SAFE_TO_EXECUTE_WITH_MONITORING: "#1677ff",
      NEEDS_MANUAL_REVIEW: "#fa8c16",
      HIGH_RISK_DO_NOT_EXECUTE: "#ff4d4f",
    };

    return (
      <Card title="📊 Overview" size="small">
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Statistic title="Objects Analyzed" value={totalObjects} suffix="objects" />
          </Col>
          <Col span={6}>
            <Statistic
              title="Rewrite Rules"
              value={rewriteApplied}
              suffix={`applied (${rewriteConf.toFixed(0)}% conf)`}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="Migration Score"
              value={migrationScore}
              suffix="/ 100"
              valueStyle={{ color: migrationScore >= 85 ? "#52c41a" : migrationScore >= 70 ? "#fa8c16" : "#ff4d4f" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="Equivalence Score"
              value={simScore.toFixed(0)}
              suffix="%"
              valueStyle={{ color: simScore >= 95 ? "#52c41a" : simScore >= 88 ? "#1677ff" : simScore >= 70 ? "#fa8c16" : "#ff4d4f" }}
            />
          </Col>
        </Row>
        {simulation && (
          <div style={{ marginTop: 16 }}>
            <Tag color={verdictColor[simVerdict] || "default"} style={{ fontSize: 14, padding: "4px 12px" }}>
              {simVerdict.replace(/_/g, " ")}
            </Tag>
            <Text type="secondary" style={{ marginLeft: 12 }}>
              Risk: {(simulation?.risk_level as string) || "N/A"}
            </Text>
          </div>
        )}
        {result.warnings.length > 0 && (
          <Alert
            type="warning"
            showIcon
            title="Warnings"
            description={result.warnings.join("; ")}
            style={{ marginTop: 12 }}
          />
        )}
      </Card>
    );
  };

  const renderDiagnostics = () => {
    if (!result?.diagnostics) return null;
    const diag = result.diagnostics as Record<string, unknown>;
    const summary = (diag.summary as Record<string, unknown>) || {};
    const tables = (diag.tables as unknown[]) || [];
    const functions = (diag.functions as unknown[]) || [];
    const joins = (diag.joins as unknown[]) || [];

    const riskCounts = (category: string) => {
      const cat = summary[category] as Record<string, number> | undefined;
      if (!cat) return { NONE: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
      return {
        NONE: cat.NONE || 0,
        LOW: cat.LOW || 0,
        MEDIUM: cat.MEDIUM || 0,
        HIGH: cat.HIGH || 0,
        CRITICAL: cat.CRITICAL || 0,
      };
    };

    const fnRisks = riskCounts("functions");
    const tableRisks = riskCounts("tables");

    const columns = [
      { title: "Category", dataIndex: "category", key: "category" },
      { title: "NONE", dataIndex: "NONE", key: "NONE", render: (v: number) => <Tag color="green">{v}</Tag> },
      { title: "LOW", dataIndex: "LOW", key: "LOW", render: (v: number) => <Tag color="blue">{v}</Tag> },
      { title: "MEDIUM", dataIndex: "MEDIUM", key: "MEDIUM", render: (v: number) => <Tag color="orange">{v}</Tag> },
      { title: "HIGH", dataIndex: "HIGH", key: "HIGH", render: (v: number) => <Tag color="red">{v}</Tag> },
      { title: "CRITICAL", dataIndex: "CRITICAL", key: "CRITICAL", render: (v: number) => <Badge count={v} overflowCount={99} /> },
    ];

    const dataSource = [
      { key: "tables", category: "Tables", ...tableRisks },
      { key: "functions", category: "Functions", ...fnRisks },
      { key: "columns", category: "Columns", ...riskCounts("columns") },
      { key: "joins", category: "Joins", ...riskCounts("joins") },
    ];

    return (
      <Card title={<><BugOutlined /> Diagnostics</>} size="small">
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Total Objects">{summary.total_objects as number}</Descriptions.Item>
          <Descriptions.Item label="Tables Found">{tables.length}</Descriptions.Item>
          <Descriptions.Item label="Functions Found">{functions.length}</Descriptions.Item>
          <Descriptions.Item label="Joins Found">{joins.length}</Descriptions.Item>
        </Descriptions>
        <Table
          dataSource={dataSource}
          columns={columns}
          pagination={false}
          size="small"
          style={{ marginTop: 12 }}
        />
      </Card>
    );
  };

  const renderRewrite = () => {
    if (!result?.rewrite) return null;
    const rewrite = result.rewrite as Record<string, unknown>;
    const rules = (rewrite.rules_applied as unknown[]) || [];
    const rewrittenSql = rewrite.rewritten_sql as string;
    const confidence = ((rewrite.confidence as number) || 0) * 100;

    return (
      <Card title={<><ThunderboltOutlined /> Rewrite</>} size="small">
        <Row gutter={16}>
          <Col span={12}>
            <Statistic
              title="Rules Applied"
              value={rules.length}
              suffix={rules.length === 0 ? "(no changes needed)" : "rules"}
            />
          </Col>
          <Col span={12}>
            <Progress
              type="circle"
              percent={Math.round(confidence)}
              size={60}
              status={confidence >= 90 ? "success" : confidence >= 70 ? "normal" : "exception"}
            />
          </Col>
        </Row>
        {rules.length > 0 && (
          <Timeline
            style={{ marginTop: 12 }}
            items={rules.map((r: unknown) => {
              const rule = r as Record<string, unknown>;
              return {
                color: (rule.confidence as number) >= 0.9 ? "green" : "orange",
                children: (
                  <span>
                    <Text strong>{rule.name as string}</Text>
                    <br />
                    <Text type="secondary">{rule.description as string}</Text>
                  </span>
                ),
              };
            })}
          />
        )}
        {rewrittenSql && rewrittenSql !== result.original_sql && (
          <Card size="small" style={{ marginTop: 12, background: "#f6ffed" }}>
            <Text type="secondary" style={{ fontSize: 12 }}>Rewritten SQL:</Text>
            <pre style={{ margin: 0, fontSize: 13, whiteSpace: "pre-wrap" }}>{rewrittenSql}</pre>
          </Card>
        )}
      </Card>
    );
  };

  const renderMigration = () => {
    if (!result?.migration) return null;
    const migration = result.migration as Record<string, unknown>;
    const feasible = migration.migration_feasible as boolean;
    const score = migration.estimated_score as number;
    const rec = migration.recommendation as string;
    const risk = migration.risk_level as string;
    const plan = migration.plan as Record<string, unknown>;
    const impact = migration.impact as Record<string, unknown>;
    const steps = (plan?.steps as unknown[]) || [];

    const recColor: Record<string, string> = {
      SAFE_AUTO_MIGRATION: "#52c41a",
      NEED_REVIEW: "#fa8c16",
      HIGH_RISK: "#ff4d4f",
    };

    return (
      <Card title={<><RocketOutlined /> Migration Plan</>} size="small">
        <Row gutter={16}>
          <Col span={8}>
            <Statistic
              title="Feasibility"
              value={feasible ? "Feasible" : "Not Feasible"}
              valueStyle={{ color: feasible ? "#52c41a" : "#ff4d4f" }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="Score"
              value={score}
              suffix="/ 100"
              valueStyle={{ color: score >= 85 ? "#52c41a" : score >= 70 ? "#fa8c16" : "#ff4d4f" }}
            />
          </Col>
          <Col span={8}>
            <Tag color={recColor[rec] || "default"} style={{ fontSize: 13 }}>{rec?.replace(/_/g, " ")}</Tag>
            <br />
            <Text type="secondary">Risk: {risk}</Text>
          </Col>
        </Row>
        {impact && (
          <Descriptions column={2} size="small" style={{ marginTop: 12 }}>
            <Descriptions.Item label="Critical Tables">
              {((impact.critical_tables as unknown[]) || []).length || 0}
            </Descriptions.Item>
            <Descriptions.Item label="High Risk Objects">
              {impact.high_risk_count as number || 0}
            </Descriptions.Item>
            <Descriptions.Item label="Hotspots">
              {((impact.hotspots as unknown[]) || []).length || 0}
            </Descriptions.Item>
            <Descriptions.Item label="Medium Risk">
              {impact.medium_risk_count as number || 0}
            </Descriptions.Item>
          </Descriptions>
        )}
        {steps.length > 0 && (
          <Timeline
            style={{ marginTop: 12 }}
            items={steps.map((s: unknown) => {
              const step = s as Record<string, unknown>;
              return {
                color: step.automatic ? "green" : "blue",
                children: (
                  <span>
                    <Text strong>Step {step.step as number}: {step.description as string}</Text>
                    <br />
                    <Text type="secondary">{step.detail as string}</Text>
                    {step.automatic ? <Tag color="green" style={{ marginLeft: 8 }}>AUTO</Tag> : <Tag color="blue" style={{ marginLeft: 8 }}>MANUAL</Tag>}
                  </span>
                ),
              };
            })}
          />
        )}
      </Card>
    );
  };

  const renderSimulation = () => {
    if (!result?.simulation) return null;
    const sim = result.simulation as Record<string, unknown>;
    const score = ((sim.equivalence_score as number) || 0) * 100;
    const risk = sim.risk_level as string;
    const verdict = sim.recommendation as string;
    const execModel = sim.execution_model as Record<string, unknown>;
    const simulation = sim.simulation as Record<string, unknown>;
    const rowDiff = simulation?.row_level_diff as Record<string, unknown>;
    const queryBeh = simulation?.query_behavior as Record<string, unknown>;
    const failures = (simulation?.failure_points as unknown[]) || [];
    const tableDrifts = (rowDiff?.table_drifts as unknown[]) || [];

    const verdictConfig: Record<string, { color: string; icon: React.ReactNode }> = {
      SAFE_TO_EXECUTE: { color: "#52c41a", icon: <CheckCircleOutlined /> },
      SAFE_TO_EXECUTE_WITH_MONITORING: { color: "#1677ff", icon: <SyncOutlined /> },
      NEEDS_MANUAL_REVIEW: { color: "#fa8c16", icon: <WarningOutlined /> },
      HIGH_RISK_DO_NOT_EXECUTE: { color: "#ff4d4f", icon: <CloseCircleOutlined /> },
    };
    const vc = verdictConfig[verdict] || { color: "#d9d9d9", icon: null };

    const driftColor: Record<string, string> = {
      STABLE: "green",
      LOW_DRIFT: "blue",
      MODERATE_DRIFT: "orange",
      HIGH_DRIFT: "red",
    };

    const severityColor: Record<string, string> = {
      NONE: "green",
      LOW: "blue",
      MEDIUM: "orange",
      HIGH: "red",
      CRITICAL: "magenta",
    };

    return (
      <Card title={<><PlayCircleOutlined /> Simulation</>} size="small">
        <Row gutter={16}>
          <Col span={12}>
            <Progress
              type="dashboard"
              percent={Math.round(score)}
              format={() => `${score.toFixed(0)}%`}
              status={score >= 95 ? "success" : score >= 70 ? "normal" : "exception"}
            />
          </Col>
          <Col span={12}>
            <Statistic title="Verdict" value={verdict?.replace(/_/g, " ")} />
            <Tag color={vc.color} icon={vc.icon} style={{ marginTop: 8 }}>
              Risk: {risk}
            </Tag>
          </Col>
        </Row>
        <Divider />
        {execModel && (
          <Descriptions column={2} size="small">
            <Descriptions.Item label="AST Match">
              {(execModel.equivalence as Record<string, unknown>)?.ast_match ? (
                <Tag color="green">Yes</Tag>
              ) : <Tag color="red">No</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Function Mapping">
              {(execModel.equivalence as Record<string, unknown>)?.function_mapping_consistent ? (
                <Tag color="green">Consistent</Tag>
              ) : <Tag color="orange">Issues</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Original Rows">
              {(execModel.cardinality as Record<string, unknown>)?.original_estimated_rows as number}
            </Descriptions.Item>
            <Descriptions.Item label="Rewritten Rows">
              {(execModel.cardinality as Record<string, unknown>)?.rewritten_estimated_rows as number}
            </Descriptions.Item>
          </Descriptions>
        )}
        {queryBeh && (
          <Descriptions column={1} size="small" style={{ marginTop: 12 }}>
            <Descriptions.Item label="NULL Semantics">
              {queryBeh.null_semantics_change ? <Tag color="orange">Changed</Tag> : <Tag color="green">Same</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Aggregation">
              <Tag>{queryBeh.aggregation_stability as string}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Ordering">
              <Tag>{queryBeh.ordering_stability as string}</Tag>
            </Descriptions.Item>
          </Descriptions>
        )}
        {tableDrifts.length > 0 && (
          <>
            <Text strong style={{ display: "block", marginTop: 12 }}>Table Drifts:</Text>
            {tableDrifts.map((td: unknown, i: number) => {
              const d = td as Record<string, unknown>;
              return (
                <Tag key={i} color={driftColor[d.drift as string] || "default"}>
                  {d.table as string}: {d.drift as string} ({d.expected_variance as string})
                </Tag>
              );
            })}
          </>
        )}
        {failures.length > 0 && (
          <>
            <Text strong style={{ display: "block", marginTop: 12 }}>
              Failure Points ({failures.length}):
            </Text>
            <Table
              dataSource={failures.map((f: unknown, i: number) => {
                const fp = f as Record<string, unknown>;
                return {
                  key: i,
                  type: fp.type as string,
                  location: fp.location as string,
                  severity: fp.severity as string,
                  description: fp.description as string,
                };
              })}
              columns={[
                { title: "Type", dataIndex: "type", key: "type", width: 120 },
                { title: "Location", dataIndex: "location", key: "location", width: 100 },
                {
                  title: "Severity",
                  dataIndex: "severity",
                  key: "severity",
                  width: 90,
                  render: (v: string) => <Tag color={severityColor[v] || "default"}>{v}</Tag>,
                },
                { title: "Description", dataIndex: "description", key: "description" },
              ]}
              pagination={false}
              size="small"
            />
          </>
        )}
      </Card>
    );
  };

  // ------------------------------------------------------------------
  // Main render
  // ------------------------------------------------------------------

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: "0 auto" }}>
      <Title level={3}>
        <DashboardOutlined style={{ marginRight: 8 }} />
        SQL Intelligence Dashboard
      </Title>
      <Paragraph type="secondary">
        统一语义上下文 → 5 引擎并行分析。所有引擎共享同一份 SQL 解析结果，零重复解析。
      </Paragraph>

      <SqlEditor value={sql} onChange={setSql} onExecute={handleAnalyze} />

      <div style={{ marginTop: 16 }}>
        {renderToolbar()}
      </div>

      {error && (
        <Alert type="error" title="Analysis Failed" description={error} showIcon style={{ marginBottom: 16 }} />
      )}

      <Spin spinning={loading} description="正在分析...">

        {result && (
          <div style={{ marginTop: 16 }}>
            {renderDecisionPanel()}
            {renderOverview()}

            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              {result.diagnostics && (
                <Col span={12}>
                  {renderDiagnostics()}
                </Col>
              )}
              {result.rewrite && (
                <Col span={12}>
                  {renderRewrite()}
                </Col>
              )}
              {result.migration && (
                <Col span={12}>
                  {renderMigration()}
                </Col>
              )}
              {result.simulation && (
                <Col span={12}>
                  {renderSimulation()}
                </Col>
              )}
            </Row>

            {result.rewritten_sql && (
              <Card size="small" style={{ marginTop: 16, background: "#f0f5ff" }}>
                <Text type="secondary">Rewritten SQL (target: {result.target_db}):</Text>
                <pre style={{ margin: "8px 0 0", fontSize: 13, whiteSpace: "pre-wrap", background: "#fff", padding: 12, borderRadius: 6 }}>
                  {result.rewritten_sql}
                </pre>
              </Card>
            )}
          </div>
        )}

        {!result && !loading && !error && (
          <div style={{ textAlign: "center", padding: 60, color: "#8c8c8c" }}>
            <DashboardOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <br />
            <Text type="secondary">
              输入 SQL 并选择源/目标数据库后点击 "Analyze All" 开始分析
            </Text>
          </div>
        )}

      </Spin>
    </div>
  );
}
