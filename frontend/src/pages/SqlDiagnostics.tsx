/**
 * SqlDiagnostics — SQL Object-Level Cross-DB Compatibility Diagnostics.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────┐
 *   │  Toolbar: [DB Types] [ANALYZE]                  │
 *   ├─────────────────────────────────────────────────┤
 *   │  SQL Editor (input)                             │
 *   ├─────────────────────────────────────────────────┤
 *   │  TABLES  |  COLUMNS  |  FUNCTIONS  |  JOINS     │
 *   │  Risk panels for each object type               │
 *   ├─────────────────────────────────────────────────┤
 *   │  Visual Map: [t1] ──→ [t2]                      │
 *   └─────────────────────────────────────────────────┘
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
  Table,
  Tooltip,
  Badge,
} from "antd";
import {
  SearchOutlined,
  ClearOutlined,
  BugOutlined,
  TableOutlined,
  FunctionOutlined,
  LinkOutlined,
  ColumnWidthOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import {
  diagnoseSql,
  type DiagnoseResponse,
  type TableDiagnostic,
  type ColumnDiagnostic,
  type FunctionDiagnostic,
  type JoinDiagnostic,
  type RiskLevel,
} from "../api/sqlDiagnostics";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text } = Typography;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SQL = `-- SQL 对象级兼容性诊断示例
-- 分析该 SQL 中各对象在目标数据库中的兼容性
SELECT TOP 10
  u.id,
  u.name,
  ISNULL(u.phone, 'N/A') AS phone,
  o.total_amount,
  GETDATE() AS query_time
FROM [users] u
INNER JOIN orders o ON u.id = o.user_id
WHERE u.is_active = 1
  AND DATEPART(YEAR, o.created_at) = 2025
ORDER BY o.created_at DESC`;

const RISK_CONFIG: Record<RiskLevel, { color: string; label: string; icon: React.ReactNode }> = {
  NONE: { color: "#52c41a", label: "兼容", icon: <CheckCircleOutlined /> },
  LOW: { color: "#1677ff", label: "低风险", icon: <QuestionCircleOutlined /> },
  MEDIUM: { color: "#fa8c16", label: "中风险", icon: <WarningOutlined /> },
  HIGH: { color: "#ff4d4f", label: "高风险", icon: <CloseCircleOutlined /> },
  CRITICAL: { color: "#cf1322", label: "严重", icon: <BugOutlined /> },
};

const DB_OPTIONS = [
  { value: "mssql", label: "MSSQL" },
  { value: "kingbasees", label: "KingbaseES" },
  { value: "dm8", label: "DM8" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SqlDiagnostics() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [dbTypes, setDbTypes] = useState<string[]>(["mssql", "kingbasees"]);
  const [result, setResult] = useState<DiagnoseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // Backend connectivity check
  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handleDbTypesChange = useCallback((values: string[]) => {
    setDbTypes(values);
    setResult(null);
    setError(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }
    if (dbTypes.length === 0) {
      message.warning("请至少选择一个目标数据库");
      return;
    }

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await diagnoseSql({
        sql: sql.trim(),
        db_types: dbTypes,
      });
      setResult(res);

      const highCount = res.summary.functions.HIGH + res.summary.functions.CRITICAL;
      if (highCount > 0) {
        message.warning(
          `诊断完成 — ${highCount} 个函数存在高/严重风险`,
        );
      } else {
        message.success(
          `诊断完成 — ${res.summary.total_objects} 个对象已分析`,
        );
      }
    } catch (err) {
      const errMsg = `分析失败: ${String(err)}`;
      setError(errMsg);
      message.error(errMsg);
    } finally {
      setLoading(false);
    }
  }, [sql, dbTypes]);

  const handleClear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  // ------------------------------------------------------------------
  // Render helpers
  // ------------------------------------------------------------------

  function riskTag(risk: RiskLevel) {
    const cfg = RISK_CONFIG[risk];
    return (
      <Tag color={cfg.color} icon={cfg.icon}>
        {cfg.label}
      </Tag>
    );
  }

  function compatBadge(compat: Record<string, boolean>) {
    return (
      <Space size={4}>
        {Object.entries(compat).map(([db, ok]) => (
          <Tag
            key={db}
            color={ok ? "green" : "red"}
            style={{ fontSize: 11, lineHeight: "18px", padding: "0 6px" }}
          >
            {db}: {ok ? "✓" : "✗"}
          </Tag>
        ))}
      </Space>
    );
  }

  // ------------------------------------------------------------------
  // Table render helpers
  // ------------------------------------------------------------------

  function renderTablesSection(tables: TableDiagnostic[]) {
    if (tables.length === 0) return null;

    const columns = [
      {
        title: "表名",
        dataIndex: "name",
        key: "name",
        render: (name: string, record: TableDiagnostic) => (
          <Space>
            <TableOutlined />
            <Text strong>{name}</Text>
            {record.alias && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                AS {record.alias}
              </Text>
            )}
          </Space>
        ),
      },
      {
        title: "风险",
        dataIndex: "risk",
        key: "risk",
        width: 120,
        render: (risk: RiskLevel) => riskTag(risk),
      },
      {
        title: "兼容性",
        key: "compat",
        width: 200,
        render: (_: unknown, record: TableDiagnostic) =>
          compatBadge(record.db_compatibility),
      },
      {
        title: "问题",
        dataIndex: "issues",
        key: "issues",
        render: (issues: string[]) =>
          issues.length > 0 ? (
            <Text type="warning" style={{ fontSize: 12 }}>
              {issues.join("; ")}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              无
            </Text>
          ),
      },
    ];

    return (
      <Table
        dataSource={tables.map((t, i) => ({ ...t, key: i }))}
        columns={columns}
        pagination={false}
        size="small"
        style={{ marginBottom: 16 }}
      />
    );
  }

  function renderColumnsSection(columns: ColumnDiagnostic[]) {
    if (columns.length === 0) return null;

    const cols = [
      {
        title: "列名",
        dataIndex: "name",
        key: "name",
        render: (name: string, record: ColumnDiagnostic) => (
          <Space>
            <ColumnWidthOutlined />
            <Text strong>{name}</Text>
            {record.table_ref && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                ({record.table_ref})
              </Text>
            )}
          </Space>
        ),
      },
      {
        title: "风险",
        dataIndex: "risk",
        key: "risk",
        width: 120,
        render: (risk: RiskLevel) => riskTag(risk),
      },
      {
        title: "问题",
        dataIndex: "issues",
        key: "issues",
        render: (issues: string[]) =>
          issues.length > 0 ? (
            <Text type="warning" style={{ fontSize: 12 }}>
              {issues.join("; ")}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>无</Text>
          ),
      },
    ];

    return (
      <Table
        dataSource={columns.map((c, i) => ({ ...c, key: i }))}
        columns={cols}
        pagination={false}
        size="small"
        style={{ marginBottom: 16 }}
      />
    );
  }

  function renderFunctionsSection(functions: FunctionDiagnostic[]) {
    if (functions.length === 0) return null;

    const cols = [
      {
        title: "函数",
        dataIndex: "raw",
        key: "raw",
        render: (raw: string, record: FunctionDiagnostic) => (
          <Space>
            <FunctionOutlined />
            <Text code style={{ fontSize: 13 }}>
              {raw}
            </Text>
            {record.has_rewrite_rule && (
              <Tag color="blue" style={{ fontSize: 10 }}>
                可改写
              </Tag>
            )}
          </Space>
        ),
      },
      {
        title: "风险",
        dataIndex: "risk",
        key: "risk",
        width: 120,
        render: (risk: RiskLevel) => riskTag(risk),
      },
      {
        title: "兼容性",
        key: "compat",
        width: 200,
        render: (_: unknown, record: FunctionDiagnostic) =>
          compatBadge(record.db_compatibility),
      },
      {
        title: "说明",
        dataIndex: "issues",
        key: "issues",
        render: (issues: string[]) =>
          issues.length > 0 ? (
            <Text type="warning" style={{ fontSize: 12 }}>
              {issues.join("; ")}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>兼容</Text>
          ),
      },
    ];

    return (
      <Table
        dataSource={functions.map((f, i) => ({ ...f, key: i }))}
        columns={cols}
        pagination={false}
        size="small"
        style={{ marginBottom: 16 }}
      />
    );
  }

  function renderJoinsSection(joins: JoinDiagnostic[]) {
    if (joins.length === 0) return null;

    const cols = [
      {
        title: "类型",
        dataIndex: "join_type",
        key: "join_type",
        width: 100,
        render: (jt: string) => (
          <Tag color="purple">
            <LinkOutlined /> {jt} JOIN
          </Tag>
        ),
      },
      {
        title: "表",
        dataIndex: "table",
        key: "table",
        render: (table: string, record: JoinDiagnostic) => (
          <Space>
            <TableOutlined />
            <Text strong>{table}</Text>
            {record.alias && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                AS {record.alias}
              </Text>
            )}
          </Space>
        ),
      },
      {
        title: "ON 条件",
        dataIndex: "condition",
        key: "condition",
        render: (cond: string | null) =>
          cond ? (
            <Text code style={{ fontSize: 12 }}>
              {cond}
            </Text>
          ) : (
            <Text type="secondary">—</Text>
          ),
      },
      {
        title: "风险",
        dataIndex: "risk",
        key: "risk",
        width: 120,
        render: (risk: RiskLevel) => riskTag(risk),
      },
    ];

    return (
      <Table
        dataSource={joins.map((j, i) => ({ ...j, key: i }))}
        columns={cols}
        pagination={false}
        size="small"
        style={{ marginBottom: 16 }}
      />
    );
  }

  function renderVisualMap(
    tables: TableDiagnostic[],
    joins: JoinDiagnostic[],
  ) {
    if (tables.length === 0) return null;

    return (
      <Card
        title={
          <span>
            <LinkOutlined style={{ marginRight: 8 }} />
            对象关系图
          </span>
        }
        size="small"
        styles={{ body: { padding: "16px 24px" } }}
        style={{ borderRadius: 12 }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexWrap: "wrap",
            gap: 24,
            padding: "16px 0",
          }}
        >
          {tables.map((table, idx) => (
            <div key={table.name} style={{ textAlign: "center" }}>
              {/* Table node */}
              <Tooltip
                title={
                  <>
                    <div>风险: {RISK_CONFIG[table.risk].label}</div>
                    {table.issues.length > 0 && (
                      <div>问题: {table.issues.join("; ")}</div>
                    )}
                  </>
                }
              >
                <div
                  style={{
                    background:
                      table.risk === "NONE"
                        ? "#f6ffed"
                        : table.risk === "LOW"
                          ? "#e6f7ff"
                          : table.risk === "MEDIUM"
                            ? "#fff7e6"
                            : "#fff2f0",
                    border: `2px solid ${RISK_CONFIG[table.risk].color}`,
                    borderRadius: 12,
                    padding: "12px 24px",
                    minWidth: 120,
                    cursor: "pointer",
                  }}
                >
                  <TableOutlined
                    style={{
                      fontSize: 20,
                      color: RISK_CONFIG[table.risk].color,
                      marginBottom: 8,
                    }}
                  />
                  <br />
                  <Text strong style={{ fontSize: 14 }}>
                    {table.name}
                  </Text>
                  <br />
                  <Badge
                    color={RISK_CONFIG[table.risk].color}
                    text={RISK_CONFIG[table.risk].label}
                    style={{ fontSize: 11, marginTop: 4 }}
                  />
                </div>
              </Tooltip>

              {/* Arrows between tables based on joins */}
              {idx < tables.length - 1 &&
                joins.some(
                  (j) =>
                    j.table === tables[idx + 1]?.name,
                ) && (
                  <div
                    style={{
                      position: "absolute",
                      marginTop: -30,
                      marginLeft: 100,
                    }}
                  >
                    <Text type="secondary" style={{ fontSize: 20 }}>
                      →
                    </Text>
                  </div>
                )}
            </div>
          ))}

          {/* Show join connectors */}
          {joins.map((join, idx) => {
            const fromTable = tables.find((t) =>
              join.condition?.toLowerCase().includes(t.name.toLowerCase()),
            );
            const toTable = tables.find(
              (t) => t.name.toLowerCase() === join.table.toLowerCase(),
            );
            if (!fromTable || !toTable || fromTable.name === toTable.name)
              return null;
            return (
              <div
                key={`join-${idx}`}
                style={{
                  textAlign: "center",
                  fontSize: 11,
                  color: "#8c8c8c",
                }}
              >
                <Tag color="purple" style={{ fontSize: 10 }}>
                  {join.join_type} JOIN
                </Tag>
                <br />
                <Text type="secondary" style={{ fontSize: 10 }}>
                  {join.condition || "—"}
                </Text>
              </div>
            );
          })}
        </div>
      </Card>
    );
  }

  function renderSummary(summary: DiagnoseResponse["summary"]) {
    const riskCounts = [
      { level: "CRITICAL" as RiskLevel, count: summary.functions.CRITICAL + summary.tables.CRITICAL },
      { level: "HIGH" as RiskLevel, count: summary.functions.HIGH + summary.tables.HIGH },
      { level: "MEDIUM" as RiskLevel, count: summary.functions.MEDIUM + summary.tables.MEDIUM },
      { level: "LOW" as RiskLevel, count: summary.functions.LOW + summary.tables.LOW },
      { level: "NONE" as RiskLevel, count: summary.functions.NONE + summary.tables.NONE },
    ].filter((r) => r.count > 0);

    return (
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {riskCounts.map(({ level, count }) => (
          <Col key={level} xs={12} sm={6} md={4} lg={3}>
            <Card
              size="small"
              styles={{ body: { padding: "12px 16px", textAlign: "center" } }}
              style={{
                borderRadius: 8,
                borderLeft: `3px solid ${RISK_CONFIG[level].color}`,
              }}
            >
              <Text
                style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: RISK_CONFIG[level].color,
                }}
              >
                {count}
              </Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {RISK_CONFIG[level].label}
              </Text>
            </Card>
          </Col>
        ))}
        <Col xs={12} sm={6} md={4} lg={3}>
          <Card
            size="small"
            styles={{ body: { padding: "12px 16px", textAlign: "center" } }}
            style={{ borderRadius: 8, borderLeft: "3px solid #8c8c8c" }}
          >
            <Text style={{ fontSize: 24, fontWeight: 700, color: "#8c8c8c" }}>
              {summary.total_objects}
            </Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>
              总计
            </Text>
          </Card>
        </Col>
      </Row>
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
            <BugOutlined style={{ marginRight: 8 }} />
            SQL Object Diagnostics
          </Title>
          <Text type="secondary">
            提取 SQL 中的表 / 列 / 函数 / JOIN → 分析跨数据库兼容性
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
            <Text strong>目标数据库:</Text>
            <Select
              mode="multiple"
              value={dbTypes}
              onChange={handleDbTypesChange}
              style={{ minWidth: 280 }}
              options={DB_OPTIONS}
              placeholder="选择目标数据库"
            />
          </div>

          <Divider orientation="vertical" />

          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleAnalyze}
            loading={loading}
            size="middle"
          >
            执行诊断 (Ctrl+Enter)
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
        <SqlEditor value={sql} onChange={setSql} onExecute={handleAnalyze} />
      </Card>

      {/* Results area */}
      <Spin spinning={loading} description="正在提取对象并分析兼容性...">
        {result === null && error === null ? (
          <Card styles={{ body: { padding: 48 } }} style={{ borderRadius: 12 }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <SearchOutlined
                style={{ fontSize: 48, color: "#d9d9d9", marginBottom: 16 }}
              />
              <br />
              <Text type="secondary">
                输入 SQL，选择目标数据库，点击「执行诊断」分析对象级兼容性
              </Text>
            </div>
          </Card>
        ) : error ? (
          <Card styles={{ body: { padding: 24 } }} style={{ borderRadius: 12 }}>
            <Text type="danger">{error}</Text>
          </Card>
        ) : result ? (
          <>
            {/* Summary cards */}
            {renderSummary(result.summary)}

            {/* TABLES */}
            {result.tables.length > 0 && (
              <Card
                title={
                  <span>
                    <TableOutlined style={{ marginRight: 8 }} />
                    TABLES ({result.tables.length})
                  </span>
                }
                styles={{ body: { padding: "12px 16px" } }}
                style={{ borderRadius: 12, marginBottom: 16 }}
              >
                {renderTablesSection(result.tables)}
              </Card>
            )}

            {/* COLUMNS */}
            {result.columns.length > 0 && (
              <Card
                title={
                  <span>
                    <ColumnWidthOutlined style={{ marginRight: 8 }} />
                    COLUMNS ({result.columns.length})
                  </span>
                }
                styles={{ body: { padding: "12px 16px" } }}
                style={{ borderRadius: 12, marginBottom: 16 }}
              >
                {renderColumnsSection(result.columns)}
              </Card>
            )}

            {/* FUNCTIONS */}
            {result.functions.length > 0 && (
              <Card
                title={
                  <span>
                    <FunctionOutlined style={{ marginRight: 8 }} />
                    FUNCTIONS ({result.functions.length})
                  </span>
                }
                styles={{ body: { padding: "12px 16px" } }}
                style={{ borderRadius: 12, marginBottom: 16 }}
              >
                {renderFunctionsSection(result.functions)}
              </Card>
            )}

            {/* JOINS */}
            {result.joins.length > 0 && (
              <Card
                title={
                  <span>
                    <LinkOutlined style={{ marginRight: 8 }} />
                    JOINS ({result.joins.length})
                  </span>
                }
                styles={{ body: { padding: "12px 16px" } }}
                style={{ borderRadius: 12, marginBottom: 16 }}
              >
                {renderJoinsSection(result.joins)}
              </Card>
            )}

            {/* Visual dependency map */}
            {renderVisualMap(result.tables, result.joins)}
          </>
        ) : null}
      </Spin>

      {/* Footer */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Object Diagnostics Engine • Phase 2.5 •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
