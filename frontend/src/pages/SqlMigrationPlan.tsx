/**
 * SqlMigrationPlan — SQL Migration Decision Engine page.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────┐
 *   │  Toolbar: [Source DB] → [Target DB] [GENERATE PLAN]    │
 *   ├─────────────────────────────────────────────────────────┤
 *   │  SQL Editor (input)                                     │
 *   ├─────────────────────────────────────────────────────────┤
 *   │  Migration Summary Card                                 │
 *   │  Risk: MEDIUM  │  Score: 85  │  Confidence: 93%         │
 *   ├─────────────────────────────────────────────────────────┤
 *   │  Impact Analysis  │  Migration Plan (steps)             │
 *   │  - tables          │  1. rewrite TOP → LIMIT    [AUTO]  │
 *   │  - functions       │  2. rewrite GETDATE → NOW  [AUTO]  │
 *   │  - hotspots        │  3. validate execution   [MANUAL]  │
 *   ├─────────────────────────────────────────────────────────┤
 *   │  Rewritten SQL (side-by-side)                           │
 *   └─────────────────────────────────────────────────────────┘
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
  Badge,
  Timeline,
} from "antd";
import {
  RocketOutlined,
  ClearOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  QuestionCircleOutlined,
  BugOutlined,
  TableOutlined,
  FunctionOutlined,
  CodeOutlined,
  ToolOutlined,
  ArrowRightOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import {
  getMigrationPlan,
  type MigrationPlanResponse,
  type RiskLevel,
  type Recommendation,
  type StepAction,
} from "../api/sqlMigration";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text, Paragraph } = Typography;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SQL = `-- SQL 迁移评估示例
-- 评估从 MSSQL 迁移到 KingbaseES 的可行性
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

const RECOMMENDATION_CONFIG: Record<Recommendation, { color: string; label: string; desc: string }> = {
  SAFE_AUTO_MIGRATION: {
    color: "#52c41a",
    label: "安全自动迁移",
    desc: "SQL 可安全自动改写，建议在测试环境验证后直接迁移",
  },
  NEED_REVIEW: {
    color: "#fa8c16",
    label: "需要人工审查",
    desc: "存在部分需要人工确认的改写，建议 DBA 审查后再执行迁移",
  },
  HIGH_RISK: {
    color: "#ff4d4f",
    label: "高风险",
    desc: "存在不兼容语法，需要手动重写 SQL 后才能迁移",
  },
};

const ACTION_CONFIG: Record<StepAction, { color: string; label: string }> = {
  rewrite_sql: { color: "#1677ff", label: "改写" },
  validate_execution: { color: "#52c41a", label: "验证" },
  manual_review: { color: "#fa8c16", label: "审查" },
  test_recommended: { color: "#722ed1", label: "测试" },
  update_schema: { color: "#eb2f96", label: "DDL" },
  verify_results: { color: "#13c2c2", label: "校验" },
};

const DB_OPTIONS = [
  { value: "mssql", label: "MSSQL" },
  { value: "kingbasees", label: "KingbaseES" },
  { value: "dm8", label: "DM8" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SqlMigrationPlan() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [result, setResult] = useState<MigrationPlanResponse | null>(null);
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

  const handleGenerate = useCallback(async () => {
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
      const res = await getMigrationPlan({
        sql: sql.trim(),
        source_db: sourceDb,
        target_db: targetDb,
      });
      setResult(res);

      if (res.recommendation === "SAFE_AUTO_MIGRATION") {
        message.success(`迁移评估完成 — 安全自动迁移 (评分 ${res.estimated_score})`);
      } else if (res.recommendation === "NEED_REVIEW") {
        message.warning(`迁移需要人工审查 (评分 ${res.estimated_score})`);
      } else {
        message.error(`迁移高风险 — 需要手动重写 (评分 ${res.estimated_score})`);
      }
    } catch (err) {
      const errMsg = `评估失败: ${String(err)}`;
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

  // Prevent same source/target
  const targetOptions = DB_OPTIONS.map((opt) => ({
    ...opt,
    disabled: opt.value === sourceDb,
  }));

  // ------------------------------------------------------------------
  // Render: Summary Card
  // ------------------------------------------------------------------

  function renderSummary(result: MigrationPlanResponse) {
    const rec = RECOMMENDATION_CONFIG[result.recommendation];
    const risk = RISK_CONFIG[result.risk_level];
    const scoreColor =
      result.estimated_score > 85 ? "#52c41a" :
      result.estimated_score >= 70 ? "#fa8c16" : "#ff4d4f";

    return (
      <Card
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "20px 24px" } }}
      >
        <Row gutter={[24, 16]} align="middle">
          {/* Recommendation badge */}
          <Col xs={24} md={6}>
            <div style={{ textAlign: "center" }}>
              <Tag
                color={rec.color}
                style={{ fontSize: 14, padding: "6px 16px", marginBottom: 8 }}
              >
                {rec.label}
              </Tag>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {rec.desc}
              </Text>
            </div>
          </Col>

          {/* Score gauge */}
          <Col xs={12} md={5}>
            <div style={{ textAlign: "center" }}>
              <Progress
                type="dashboard"
                percent={result.estimated_score}
                size={80}
                strokeColor={scoreColor}
                format={(pct) => (
                  <span style={{ fontSize: 18, fontWeight: 700, color: scoreColor }}>
                    {pct}
                  </span>
                )}
              />
              <br />
              <Text type="secondary" style={{ fontSize: 11 }}>兼容性评分</Text>
            </div>
          </Col>

          {/* Stats */}
          <Col xs={12} md={5}>
            <Space orientation="vertical" size={4}>
              <Statistic
                title="风险等级"
                value={risk.label}
                valueStyle={{ color: risk.color, fontSize: 18 }}
                prefix={risk.icon}
              />
              <Statistic
                title="置信度"
                value={`${Math.round(result.confidence * 100)}%`}
                valueStyle={{ fontSize: 16 }}
              />
            </Space>
          </Col>

          {/* Feasibility */}
          <Col xs={12} md={4}>
            <Space orientation="vertical" size={4}>
              <Statistic
                title="迁移可行"
                value={result.migration_feasible ? "是 ✓" : "否 ✗"}
                valueStyle={{
                  color: result.migration_feasible ? "#52c41a" : "#ff4d4f",
                  fontSize: 18,
                }}
              />
              <Statistic
                title="预估工作量"
                value={result.plan.estimated_effort}
                valueStyle={{ fontSize: 16 }}
              />
            </Space>
          </Col>

          {/* Steps summary */}
          <Col xs={12} md={4}>
            <Space orientation="vertical" size={4}>
              <Statistic
                title="自动步骤"
                value={result.plan.automatic_steps}
                valueStyle={{ color: "#1677ff", fontSize: 16 }}
                suffix={`/ ${result.plan.total_steps}`}
              />
              <Statistic
                title="手动步骤"
                value={result.plan.manual_steps}
                valueStyle={{ color: "#fa8c16", fontSize: 16 }}
              />
            </Space>
          </Col>
        </Row>

        {result.warnings.length > 0 && (
          <Alert
            title="警告"
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
  // Render: Impact Analysis
  // ------------------------------------------------------------------

  function renderImpact(result: MigrationPlanResponse) {
    const { impact } = result;

    return (
      <Card
        title={
          <span>
            <ToolOutlined style={{ marginRight: 8 }} />
            Impact Analysis — 影响分析
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "16px 24px" } }}
      >
        <Row gutter={[16, 16]}>
          {/* Tables */}
          <Col xs={24} md={8}>
            <Card size="small" styles={{ body: { padding: 12 } }}>
              <Text strong>
                <TableOutlined style={{ marginRight: 6 }} />
                表 ({impact.tables.length})
              </Text>
              <div style={{ marginTop: 8 }}>
                {impact.tables.length > 0 ? (
                  impact.tables.map((t) => (
                    <Tag
                      key={t}
                      color={impact.critical_tables.includes(t) ? "red" : "blue"}
                      style={{ marginBottom: 4 }}
                    >
                      {t}
                      {impact.critical_tables.includes(t) && " ⚠"}
                    </Tag>
                  ))
                ) : (
                  <Text type="secondary">无</Text>
                )}
              </div>
              {impact.critical_tables.length > 0 && (
                <Alert
                  title={`${impact.critical_tables.length} 个关键表需要关注`}
                  type="warning"
                  showIcon
                  style={{ marginTop: 8, fontSize: 12 }}
                />
              )}
            </Card>
          </Col>

          {/* Functions */}
          <Col xs={24} md={8}>
            <Card size="small" styles={{ body: { padding: 12 } }}>
              <Text strong>
                <FunctionOutlined style={{ marginRight: 6 }} />
                函数 ({impact.functions.length})
              </Text>
              <div style={{ marginTop: 8 }}>
                {impact.functions.length > 0 ? (
                  impact.functions.map((f) => (
                    <Tag key={f} color="orange" style={{ marginBottom: 4 }}>
                      {f}
                    </Tag>
                  ))
                ) : (
                  <Text type="secondary">无</Text>
                )}
              </div>
            </Card>
          </Col>

          {/* Hotspots */}
          <Col xs={24} md={8}>
            <Card size="small" styles={{ body: { padding: 12 } }}>
              <Text strong>
                <BugOutlined style={{ marginRight: 6 }} />
                风险热点 ({impact.risk_hotspots.length})
              </Text>
              <div style={{ marginTop: 8 }}>
                {impact.risk_hotspots.length > 0 ? (
                  impact.risk_hotspots.map((h, i) => (
                    <Tag key={i} color="red" style={{ marginBottom: 4 }}>
                      {h}
                    </Tag>
                  ))
                ) : (
                  <Text type="secondary">无风险热点</Text>
                )}
              </div>
            </Card>
          </Col>
        </Row>

        {/* Join chains */}
        {impact.join_chains.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Text strong>JOIN 链风险:</Text>
            {impact.join_chains.map((jc, i) => {
              const risk = RISK_CONFIG[jc.risk_level];
              return (
                <div key={i} style={{ marginTop: 4 }}>
                  <Tag color={risk.color}>{risk.label}</Tag>
                  <Text style={{ fontSize: 12 }}>{jc.description}</Text>
                </div>
              );
            })}
          </div>
        )}

        {/* Stats row */}
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              总对象: {impact.total_objects}
            </Text>
          </Col>
          <Col span={8}>
            <Text style={{ fontSize: 12, color: "#ff4d4f" }}>
              高风险: {impact.high_risk_count}
            </Text>
          </Col>
          <Col span={8}>
            <Text style={{ fontSize: 12, color: "#fa8c16" }}>
              中风险: {impact.medium_risk_count}
            </Text>
          </Col>
        </Row>
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Migration Plan Steps
  // ------------------------------------------------------------------

  function renderPlan(result: MigrationPlanResponse) {
    const { plan } = result;

    return (
      <Card
        title={
          <span>
            <RocketOutlined style={{ marginRight: 8 }} />
            Migration Plan — 迁移计划
            <Tag style={{ marginLeft: 8 }} color={plan.estimated_effort === "LOW" ? "green" : plan.estimated_effort === "MEDIUM" ? "orange" : "red"}>
              工作量: {plan.estimated_effort}
            </Tag>
            <Tag color="blue">{plan.automatic_steps} 自动</Tag>
            <Tag color="orange">{plan.manual_steps} 手动</Tag>
          </span>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
        styles={{ body: { padding: "16px 24px" } }}
      >
        <Timeline
          items={plan.steps.map((step) => {
            const actionCfg = ACTION_CONFIG[step.action];
            const dotColor = step.automatic ? "#1677ff" : "#fa8c16";

            return {
              dot: (
                <Badge
                  color={dotColor}
                  count={step.step}
                  style={{ fontWeight: 700 }}
                />
              ),
              children: (
                <div>
                  <Space>
                    <Tag color={actionCfg.color}>{actionCfg.label}</Tag>
                    <Text strong>{step.description}</Text>
                    <Tag color={step.automatic ? "blue" : "orange"}>
                      {step.automatic ? "自动" : "手动"}
                    </Tag>
                  </Space>
                  {step.detail && (
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {step.detail}
                      </Text>
                    </div>
                  )}
                </div>
              ),
            };
          })}
        />
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Render: Rewritten SQL
  // ------------------------------------------------------------------

  function renderRewrittenSql(result: MigrationPlanResponse) {
    if (!result.rewritten_sql) return null;

    return (
      <Card
        title={
          <span>
            <CodeOutlined style={{ marginRight: 8 }} />
            改写后的 SQL
            <Tag style={{ marginLeft: 8 }} color="green">
              {result.target_db}
            </Tag>
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
            fontFamily:
              "'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace",
          }}
        >
          {result.rewritten_sql}
        </Paragraph>

        <div style={{ marginTop: 12, textAlign: "right" }}>
          <Button
            icon={<CodeOutlined />}
            onClick={() => {
              if (result.rewritten_sql) {
                navigator.clipboard.writeText(result.rewritten_sql);
                message.success("已复制改写后的 SQL");
              }
            }}
          >
            复制改写后的 SQL
          </Button>
        </div>
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
            <RocketOutlined style={{ marginRight: 8 }} />
            SQL Migration Plan
          </Title>
          <Text type="secondary">
            综合诊断 + 改写 + 评分 → 生成迁移可行性评估和分步计划
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
            icon={<RocketOutlined />}
            onClick={handleGenerate}
            loading={loading}
            size="middle"
          >
            生成迁移计划 (Ctrl+Enter)
          </Button>
          <Button
            icon={<ClearOutlined />}
            onClick={handleClear}
            disabled={!result && !error}
          >
            清空结果
          </Button>
        </Space>
      </Card>

      {/* SQL Editor */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: 0 } }}>
        <SqlEditor value={sql} onChange={setSql} onExecute={handleGenerate} />
      </Card>

      {/* Results area */}
      <Spin spinning={loading} description="正在分析 SQL 并生成迁移计划...">
        {result === null && error === null ? (
          <Card styles={{ body: { padding: 48 } }} style={{ borderRadius: 12 }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <RocketOutlined
                style={{ fontSize: 48, color: "#d9d9d9", marginBottom: 16 }}
              />
              <br />
              <Text type="secondary">
                输入 SQL，选择源数据库和目标数据库，点击「生成迁移计划」评估迁移可行性
              </Text>
            </div>
          </Card>
        ) : error ? (
          <Card styles={{ body: { padding: 24 } }} style={{ borderRadius: 12 }}>
            <Text type="danger">{error}</Text>
          </Card>
        ) : result ? (
          <>
            {/* Summary */}
            {renderSummary(result)}

            {/* Impact + Plan side by side on larger screens */}
            <Row gutter={16}>
              <Col xs={24} lg={12}>
                {renderImpact(result)}
              </Col>
              <Col xs={24} lg={12}>
                {renderPlan(result)}
              </Col>
            </Row>

            {/* Rewritten SQL */}
            {renderRewrittenSql(result)}
          </>
        ) : null}
      </Spin>

      {/* Footer */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Migration Decision Engine • Phase 3 Step 1 •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
