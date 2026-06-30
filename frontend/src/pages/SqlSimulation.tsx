/**
 * SqlSimulation — SQL Migration Simulation Engine page.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │  Toolbar: [Source DB] → [Target DB]  [RUN SIMULATION]       │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │  SQL Editor (input)                                         │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │  ┌─────────────────────────────────────────────────────────┐│
 *   │  │  MIGRATION SIMULATION REPORT                            ││
 *   │  │  Equivalence Score: 98.2%  ●●●●●●●●○○  SAFE            ││
 *   │  ├─────────────────────────────────────────────────────────┤│
 *   │  │  DATA IMPACT                    │  QUERY BEHAVIOR        ││
 *   │  │  - Orders table: LOW DRIFT     │  - JOIN change: +3.2%  ││
 *   │  │  - Users table: STABLE         │  - NULL semantics: ⚠   ││
 *   │  ├─────────────────────────────────────────────────────────┤│
 *   │  │  FAILURE POINTS                                         ││
 *   │  │  [NULL_COMPARISON] users.created_at  MEDIUM             ││
 *   │  │  Mitigation: ...                                        ││
 *   │  ├─────────────────────────────────────────────────────────┤│
 *   │  │  FINAL VERDICT: SAFE TO RUN WITH MONITORING             ││
 *   │  └─────────────────────────────────────────────────────────┘│
 *   └─────────────────────────────────────────────────────────────┘
 */
import { useState, useCallback, useEffect } from "react";
import {
  Button,
  Space,
  Card,
  Typography,
  Divider,
  Spin,
  message,
  Tag,
  Select,
  Row,
  Col,
  Statistic,
  Progress,
  Alert,
  Table,
  Descriptions,
  Tooltip,
} from "antd";
import {
  PlayCircleOutlined,
  ClearOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  QuestionCircleOutlined,
  BugOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  ApiOutlined,
  ArrowRightOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import {
  simulateMigration,
  type SimulationResponse,
  type RiskLevel,
  type SimulationVerdict,
  type FailureType,
  type DriftLevel,
  type FailurePoint,
} from "../api/sqlSimulation";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text, Paragraph } = Typography;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SQL = `-- SQL 迁移仿真示例
-- 仿真从 MSSQL 迁移到 KingbaseES 后的执行行为
SELECT TOP 10
  u.id,
  u.name,
  ISNULL(u.phone, 'N/A') AS phone,
  GETDATE() AS query_time
FROM [users] u
INNER JOIN orders o ON u.id = o.user_id
WHERE u.is_active = 1
ORDER BY o.created_at DESC`;

const RISK_CONFIG: Record<RiskLevel, { color: string; label: string; icon: React.ReactNode }> = {
  NONE: { color: "#52c41a", label: "无风险", icon: <CheckCircleOutlined /> },
  LOW: { color: "#1677ff", label: "低风险", icon: <QuestionCircleOutlined /> },
  MEDIUM: { color: "#fa8c16", label: "中风险", icon: <WarningOutlined /> },
  HIGH: { color: "#ff4d4f", label: "高风险", icon: <CloseCircleOutlined /> },
  CRITICAL: { color: "#cf1322", label: "严重", icon: <BugOutlined /> },
};

const VERDICT_CONFIG: Record<SimulationVerdict, { color: string; label: string; desc: string; icon: React.ReactNode }> = {
  SAFE_TO_EXECUTE: {
    color: "#52c41a",
    label: "安全执行",
    desc: "SQL 可安全迁移到目标数据库执行，无需额外监控",
    icon: <CheckCircleOutlined />,
  },
  SAFE_TO_EXECUTE_WITH_MONITORING: {
    color: "#1677ff",
    label: "监控下安全执行",
    desc: "SQL 可迁移，但建议在测试环境验证并监控首次生产执行",
    icon: <SafetyCertificateOutlined />,
  },
  NEEDS_MANUAL_REVIEW: {
    color: "#fa8c16",
    label: "需要人工审查",
    desc: "存在潜在风险点，建议 DBA 审查后再执行",
    icon: <WarningOutlined />,
  },
  HIGH_RISK_DO_NOT_EXECUTE: {
    color: "#ff4d4f",
    label: "高风险 — 禁止执行",
    desc: "存在严重兼容性问题，需要手动重写 SQL 后再尝试",
    icon: <CloseCircleOutlined />,
  },
};

const FAILURE_TYPE_CONFIG: Record<FailureType, { color: string; label: string }> = {
  NULL_COMPARISON: { color: "#fa8c16", label: "NULL 比较" },
  PAGINATION_SHIFT: { color: "#1677ff", label: "分页偏移" },
  TIMEZONE_DRIFT: { color: "#722ed1", label: "时区漂移" },
  JOIN_MULTIPLICITY_CHANGE: { color: "#eb2f96", label: "JOIN 基数" },
  FUNCTION_SEMANTIC_CHANGE: { color: "#13c2c2", label: "函数语义" },
  TYPE_CAST_ISSUE: { color: "#2f54eb", label: "类型转换" },
  COLLATION_MISMATCH: { color: "#a0d911", label: "排序规则" },
  AGGREGATION_INSTABILITY: { color: "#f5222d", label: "聚合不稳定" },
};

const DRIFT_CONFIG: Record<DriftLevel, { color: string; label: string }> = {
  STABLE: { color: "#52c41a", label: "稳定" },
  LOW_DRIFT: { color: "#1677ff", label: "低漂移" },
  MODERATE_DRIFT: { color: "#fa8c16", label: "中等漂移" },
  HIGH_DRIFT: { color: "#ff4d4f", label: "高漂移" },
};

const SEVERITY_CONFIG: Record<RiskLevel, { color: string; label: string }> = {
  NONE: { color: "#52c41a", label: "无" },
  LOW: { color: "#1677ff", label: "低" },
  MEDIUM: { color: "#fa8c16", label: "中" },
  HIGH: { color: "#ff4d4f", label: "高" },
  CRITICAL: { color: "#cf1322", label: "严重" },
};

const DB_OPTIONS = [
  { value: "mssql", label: "MSSQL" },
  { value: "kingbasees", label: "KingbaseES" },
  { value: "dm8", label: "DM8" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SqlSimulation() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handleSourceChange = useCallback((value: string) => {
    setSourceDb(value);
    setResult(null);
    setError(null);
  }, []);

  const handleTargetChange = useCallback((value: string) => {
    setTargetDb(value);
    setResult(null);
    setError(null);
  }, []);

  const handleSimulate = useCallback(async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }
    if (sourceDb === targetDb) {
      message.warning("源数据库和目标数据库不能相同");
      return;
    }

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await simulateMigration({
        sql: sql.trim(),
        source_db: sourceDb,
        target_db: targetDb,
      });
      setResult(res);

      if (res.recommendation === "SAFE_TO_EXECUTE") {
        message.success(`仿真完成 — 可以安全执行 (等价评分 ${Math.round(res.equivalence_score * 100)}%)`);
      } else if (res.recommendation === "SAFE_TO_EXECUTE_WITH_MONITORING") {
        message.success(`仿真完成 — 建议监控下执行 (等价评分 ${Math.round(res.equivalence_score * 100)}%)`);
      } else if (res.recommendation === "NEEDS_MANUAL_REVIEW") {
        message.warning(`仿真完成 — 需要人工审查 (等价评分 ${Math.round(res.equivalence_score * 100)}%)`);
      } else {
        message.error(`仿真完成 — 高风险，不建议执行 (等价评分 ${Math.round(res.equivalence_score * 100)}%)`);
      }
    } catch (err) {
      const errMsg = `仿真失败: ${String(err)}`;
      setError(errMsg);
      message.error(errMsg);
    } finally {
      setLoading(false);
    }
  }, [sql, sourceDb, targetDb]);

  const handleClear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  const targetOptions = DB_OPTIONS.map((opt) => ({
    ...opt,
    disabled: opt.value === sourceDb,
  }));

  // ------------------------------------------------------------------
  // Render: Report Header (Equivalence Score + Verdict)
  // ------------------------------------------------------------------

  function renderReportHeader(result: SimulationResponse) {
    const verdict = VERDICT_CONFIG[result.recommendation];
    const risk = RISK_CONFIG[result.risk_level];
    const scorePct = Math.round(result.equivalence_score * 100);
    const scoreColor =
      scorePct >= 95 ? "#52c41a" : scorePct >= 88 ? "#1677ff" : scorePct >= 70 ? "#fa8c16" : "#ff4d4f";

    return (
      <Card
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "20px 24px" } }}
      >
        <Row gutter={[24, 16]} align="middle">
          {/* Score gauge */}
          <Col xs={24} md={6} style={{ textAlign: "center" }}>
            <Progress
              type="dashboard"
              percent={scorePct}
              size={100}
              strokeColor={scoreColor}
              format={(pct) => (
                <span style={{ fontSize: 20, fontWeight: 700, color: scoreColor }}>
                  {pct}%
                </span>
              )}
            />
            <br />
            <Text type="secondary" style={{ fontSize: 11 }}>
              等价性评分
            </Text>
          </Col>

          {/* Risk & Verdict */}
          <Col xs={24} md={10}>
            <Space orientation="vertical" size={8}>
              <div>
                <Tag
                  color={verdict.color}
                  style={{ fontSize: 14, padding: "6px 16px", marginBottom: 8 }}
                >
                  {verdict.icon} {verdict.label}
                </Tag>
              </div>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {verdict.desc}
              </Text>
              <div style={{ marginTop: 4 }}>
                <Tag color={risk.color}>{risk.icon} 风险: {risk.label}</Tag>
                <Tag color={result.execution_model.equivalence.ast_match ? "green" : "red"}>
                  AST: {result.execution_model.equivalence.ast_match ? "匹配 ✓" : "不匹配 ✗"}
                </Tag>
                <Tag color={result.execution_model.equivalence.function_mapping_consistent ? "green" : "red"}>
                  函数: {result.execution_model.equivalence.function_mapping_consistent ? "一致 ✓" : "不一致 ✗"}
                </Tag>
              </div>
            </Space>
          </Col>

          {/* Stats */}
          <Col xs={24} md={8}>
            <Row gutter={[16, 8]}>
              <Col span={12}>
                <Statistic
                  title="失败点"
                  value={result.simulation.failure_points.length}
                  valueStyle={{
                    color: result.simulation.failure_points.length > 0 ? "#fa8c16" : "#52c41a",
                    fontSize: 18,
                  }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="漂移表"
                  value={result.simulation.row_level_diff.affected_tables.length}
                  valueStyle={{
                    color: result.simulation.row_level_diff.affected_tables.length > 0 ? "#fa8c16" : "#52c41a",
                    fontSize: 18,
                  }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="NULL 语义变化"
                  value={result.simulation.query_behavior.null_semantics_change ? "有 ⚠" : "无 ✓"}
                  valueStyle={{
                    color: result.simulation.query_behavior.null_semantics_change ? "#fa8c16" : "#52c41a",
                    fontSize: 14,
                  }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="聚合稳定性"
                  value={result.simulation.query_behavior.aggregation_stability}
                  valueStyle={{
                    color: result.simulation.query_behavior.aggregation_stability === "HIGH" ? "#52c41a" : "#fa8c16",
                    fontSize: 14,
                  }}
                />
              </Col>
            </Row>
          </Col>
        </Row>

        {/* Warnings */}
        {result.warnings.length > 0 && (
          <Alert
            title="仿真警告"
            description={result.warnings.join("；")}
            type="warning"
            showIcon
            style={{ marginTop: 16 }}
          />
        )}
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Data Impact (Row-level drift + Table drifts)
  // ------------------------------------------------------------------

  function renderDataImpact(result: SimulationResponse) {
    const { row_level_diff } = result.simulation;
    const driftColumns = [
      {
        title: "表名",
        dataIndex: "table",
        key: "table",
        render: (name: string) => <Text code>{name}</Text>,
      },
      {
        title: "漂移等级",
        dataIndex: "drift",
        key: "drift",
        width: 120,
        render: (d: DriftLevel) => {
          const cfg = DRIFT_CONFIG[d];
          return <Tag color={cfg.color}>{cfg.label}</Tag>;
        },
      },
      {
        title: "预期方差",
        dataIndex: "expected_variance",
        key: "expected_variance",
        width: 100,
      },
      {
        title: "原因",
        dataIndex: "reason",
        key: "reason",
        ellipsis: true,
      },
    ];

    return (
      <Card
        title={
          <span>
            <ApiOutlined style={{ marginRight: 8 }} />
            DATA IMPACT — 数据影响
            <Tag style={{ marginLeft: 8 }} color={row_level_diff.affected_tables.length > 0 ? "orange" : "green"}>
              {row_level_diff.expected_variance}
            </Tag>
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "16px 24px" } }}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 13 }}>
          {row_level_diff.description}
        </Paragraph>

        {row_level_diff.table_drifts.length > 0 ? (
          <Table
            dataSource={row_level_diff.table_drifts.map((td, i) => ({ ...td, key: i }))}
            columns={driftColumns}
            pagination={false}
            size="small"
            style={{ marginTop: 8 }}
          />
        ) : (
          <Text type="secondary">无表级数据漂移</Text>
        )}
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Query Behavior
  // ------------------------------------------------------------------

  function renderQueryBehavior(result: SimulationResponse) {
    const { query_behavior } = result.simulation;

    return (
      <Card
        title={
          <span>
            <ThunderboltOutlined style={{ marginRight: 8 }} />
            QUERY BEHAVIOR — 查询行为
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "16px 24px" } }}
      >
        <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered>
          <Descriptions.Item
            label={
              <Tooltip title="JOIN 操作后的预期行数变化">
                <span><InfoCircleOutlined style={{ marginRight: 4 }} />JOIN 基数变化</span>
              </Tooltip>
            }
          >
            {query_behavior.join_cardinality_shift ? (
              <Tag color="blue">{query_behavior.join_cardinality_shift}</Tag>
            ) : (
              <Tag color="green">无变化</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item
            label={
              <Tooltip title="NULL 比较语义是否因数据库而不同">
                <span><InfoCircleOutlined style={{ marginRight: 4 }} />NULL 语义变化</span>
              </Tooltip>
            }
          >
            {query_behavior.null_semantics_change ? (
              <Tag color="orange">⚠ 有变化</Tag>
            ) : (
              <Tag color="green">无变化</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item
            label={
              <Tooltip title="SUM/AVG/COUNT 等聚合函数结果的一致性">
                <span><InfoCircleOutlined style={{ marginRight: 4 }} />聚合稳定性</span>
              </Tooltip>
            }
          >
            <Tag
              color={
                query_behavior.aggregation_stability === "HIGH"
                  ? "green"
                  : query_behavior.aggregation_stability === "MEDIUM"
                    ? "orange"
                    : "red"
              }
            >
              {query_behavior.aggregation_stability}
            </Tag>
          </Descriptions.Item>

          <Descriptions.Item
            label={
              <Tooltip title="ORDER BY 和窗口函数的结果排序一致性">
                <span><InfoCircleOutlined style={{ marginRight: 4 }} />排序稳定性</span>
              </Tooltip>
            }
          >
            <Tag
              color={
                query_behavior.ordering_stability === "HIGH"
                  ? "green"
                  : query_behavior.ordering_stability === "MEDIUM"
                    ? "orange"
                    : "red"
              }
            >
              {query_behavior.ordering_stability}
            </Tag>
          </Descriptions.Item>

          {query_behavior.type_coercion_changes.length > 0 && (
            <Descriptions.Item label="类型转换变化" span={2}>
              {query_behavior.type_coercion_changes.map((tc, i) => (
                <Tag key={i} color="purple" style={{ marginBottom: 4 }}>
                  {tc}
                </Tag>
              ))}
            </Descriptions.Item>
          )}
        </Descriptions>

        {/* Cardinality estimate details */}
        <Card
          size="small"
          style={{ marginTop: 12, background: "#fafafa" }}
          styles={{ body: { padding: 12 } }}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ExperimentOutlined style={{ marginRight: 4 }} />
            基数估算: {result.execution_model.cardinality.description}
          </Text>
        </Card>
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Failure Points
  // ------------------------------------------------------------------

  function renderFailurePoints(result: SimulationResponse) {
    const { failure_points } = result.simulation;

    const columns = [
      {
        title: "类型",
        dataIndex: "type",
        key: "type",
        width: 150,
        render: (t: FailureType) => {
          const cfg = FAILURE_TYPE_CONFIG[t];
          return <Tag color={cfg.color}>{cfg.label}</Tag>;
        },
      },
      {
        title: "位置",
        dataIndex: "location",
        key: "location",
        width: 200,
        render: (loc: string) => <Text code style={{ fontSize: 12 }}>{loc}</Text>,
      },
      {
        title: "严重程度",
        dataIndex: "severity",
        key: "severity",
        width: 100,
        render: (s: RiskLevel) => {
          const cfg = SEVERITY_CONFIG[s];
          return <Tag color={cfg.color}>{cfg.label}</Tag>;
        },
      },
      {
        title: "描述",
        dataIndex: "description",
        key: "description",
        ellipsis: true,
      },
      {
        title: "缓解建议",
        dataIndex: "mitigation",
        key: "mitigation",
        ellipsis: true,
        render: (m: string | null) =>
          m ? (
            <Text type="success" style={{ fontSize: 12 }}>
              {m}
            </Text>
          ) : (
            <Text type="secondary">—</Text>
          ),
      },
    ];

    return (
      <Card
        title={
          <span>
            <BugOutlined style={{ marginRight: 8 }} />
            FAILURE POINTS — 失败点预测
            <Tag
              style={{ marginLeft: 8 }}
              color={failure_points.length > 0 ? "red" : "green"}
            >
              {failure_points.length} 个
            </Tag>
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "16px 24px" } }}
      >
        {failure_points.length > 0 ? (
          <Table
            dataSource={failure_points.map((fp, i) => ({ ...fp, key: i }))}
            columns={columns}
            pagination={false}
            size="small"
            expandable={{
              expandedRowRender: (record: FailurePoint) => (
                <div style={{ padding: "8px 16px" }}>
                  <Paragraph style={{ margin: 0, fontSize: 13, whiteSpace: "pre-wrap" }}>
                    {record.description}
                  </Paragraph>
                </div>
              ),
              rowExpandable: () => true,
            }}
          />
        ) : (
          <div style={{ textAlign: "center", padding: 24 }}>
            <CheckCircleOutlined style={{ fontSize: 24, color: "#52c41a", marginBottom: 8 }} />
            <br />
            <Text type="secondary">未检测到潜在失败点 — SQL 迁移风险很低</Text>
          </div>
        )}
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Final Verdict
  // ------------------------------------------------------------------

  function renderVerdict(result: SimulationResponse) {
    const verdict = VERDICT_CONFIG[result.recommendation];

    return (
      <Card
        style={{
          borderRadius: 12,
          marginBottom: 16,
          borderLeft: `4px solid ${verdict.color}`,
          background: `${verdict.color}08`,
        }}
        styles={{ body: { padding: "20px 24px" } }}
      >
        <Row align="middle" gutter={16}>
          <Col>
            <span style={{ fontSize: 32 }}>{verdict.icon}</span>
          </Col>
          <Col flex="auto">
            <Title level={4} style={{ margin: 0, color: verdict.color }}>
              Final Verdict: {verdict.label}
            </Title>
            <Paragraph style={{ margin: "4px 0 0 0", color: "#666" }}>
              {verdict.desc}
            </Paragraph>
          </Col>
          <Col>
            <Space orientation="vertical" size={4} style={{ textAlign: "right" }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                等价评分: <strong>{Math.round(result.equivalence_score * 100)}%</strong>
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {result.source_db.toUpperCase()} → {result.target_db.toUpperCase()}
              </Text>
            </Space>
          </Col>
        </Row>
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Rewritten SQL
  // ------------------------------------------------------------------

  function renderRewrittenSql(result: SimulationResponse) {
    if (!result.rewritten_sql) return null;

    return (
      <Card
        title={
          <span>
            <ExperimentOutlined style={{ marginRight: 8 }} />
            改写后的 SQL（仿真对象）
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: 16 } }}
      >
        <Paragraph
          code
          style={{
            margin: 0,
            fontSize: 13,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            background: "#f6ffed",
            padding: 16,
            borderRadius: 8,
            border: "1px solid #d9f7be",
            fontFamily: "'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace",
          }}
        >
          {result.rewritten_sql}
        </Paragraph>
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Main render
  // ------------------------------------------------------------------

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 16px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <PlayCircleOutlined style={{ marginRight: 8 }} />
            SQL Migration Simulation
          </Title>
          <Text type="secondary">
            仿真迁移后的 SQL 在目标数据库的执行行为 — 等价性、数据漂移、失败点预测
          </Text>
        </div>
        <Tag
          color={
            backendOnline ? "green" : backendOnline === false ? "red" : "default"
          }
        >
          {backendOnline
            ? "后端在线"
            : backendOnline === false
              ? "后端离线"
              : "检测中..."}
        </Tag>
      </div>

      <Divider style={{ margin: "0 0 24px 0" }} />

      {/* Toolbar */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: "12px 16px" } }}
      >
        <Space wrap size="middle">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Text strong>源数据库:</Text>
            <Select
              value={sourceDb}
              onChange={handleSourceChange}
              style={{ width: 140 }}
              options={DB_OPTIONS}
            />
          </div>

          <ArrowRightOutlined style={{ fontSize: 16, color: "#1677ff" }} />

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Text strong>目标数据库:</Text>
            <Select
              value={targetDb}
              onChange={handleTargetChange}
              style={{ width: 140 }}
              options={targetOptions}
            />
          </div>

          <Divider orientation="vertical" />

          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleSimulate}
            loading={loading}
            size="middle"
          >
            运行仿真 (Ctrl+Enter)
          </Button>
          <Button
            icon={<ClearOutlined />}
            onClick={handleClear}
            disabled={!result && !error}
          >
            清空结果
          </Button>
          <Tooltip title="仿真会调用自动改写引擎获取改写后 SQL，然后进行等价性检查、数据漂移分析和失败点预测">
            <InfoCircleOutlined style={{ color: "#999" }} />
          </Tooltip>
        </Space>
      </Card>

      {/* SQL Editor */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: 0 } }}>
        <SqlEditor value={sql} onChange={setSql} onExecute={handleSimulate} />
      </Card>

      {/* Results area */}
      <Spin spinning={loading} description="正在仿真 SQL 迁移执行行为...">
        {result === null && error === null ? (
          <Card styles={{ body: { padding: 48 } }} style={{ borderRadius: 12 }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <PlayCircleOutlined
                style={{ fontSize: 48, color: "#d9d9d9", marginBottom: 16 }}
              />
              <br />
              <Text type="secondary">
                输入 SQL，选择源和目标数据库，点击「运行仿真」评估迁移后的执行行为
              </Text>
            </div>
          </Card>
        ) : error ? (
          <Card styles={{ body: { padding: 24 } }} style={{ borderRadius: 12 }}>
            <Text type="danger">{error}</Text>
          </Card>
        ) : result ? (
          <>
            {/* Report Header: Score + Verdict */}
            {renderReportHeader(result)}

            {/* Data Impact + Query Behavior side by side */}
            <Row gutter={16}>
              <Col xs={24} lg={12}>
                {renderDataImpact(result)}
              </Col>
              <Col xs={24} lg={12}>
                {renderQueryBehavior(result)}
              </Col>
            </Row>

            {/* Failure Points */}
            {renderFailurePoints(result)}

            {/* Final Verdict */}
            {renderVerdict(result)}

            {/* Rewritten SQL */}
            {renderRewrittenSql(result)}
          </>
        ) : null}
      </Spin>

      {/* Footer */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Migration Simulation Engine • Phase 3 Step 2 •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
