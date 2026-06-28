/**
 * SqlRewrite — SQL Cross-Database Rewrite Engine page.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────┐
 *   │  Toolbar: [Source DB] [Target DB] [REWRITE]     │
 *   ├─────────────────────────────────────────────────┤
 *   │  SQL Editor (input)                             │
 *   ├─────────────────────────────────────────────────┤
 *   │  RewritePanel (original ↓ rewritten)            │
 *   ├─────────────────────────────────────────────────┤
 *   │  ConfidenceBadge + RuleList                     │
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
} from "antd";
import {
  SwapOutlined,
  ClearOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import RewritePanel from "../components/RewritePanel";
import RuleList from "../components/RuleList";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { rewriteSql, type RewriteResponse } from "../api/sqlRewrite";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text } = Typography;

type DbType = "mssql" | "kingbasees" | "dm8";

const DEFAULT_SQL = `-- SQL 跨数据库改写示例
-- 输入 MSSQL 方言 SQL，自动改写为目标数据库语法
SELECT TOP 10
  id,
  name,
  ISNULL(description, 'N/A') AS description,
  price
FROM [products]
WHERE is_active = 1
  AND GETDATE() > created_at
ORDER BY created_at DESC`;

export default function SqlRewrite() {
  const [sourceDb, setSourceDb] = useState<DbType>("mssql");
  const [targetDb, setTargetDb] = useState<DbType>("kingbasees");
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<RewriteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // Backend connectivity check
  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handleSourceDbChange = useCallback((value: DbType) => {
    setSourceDb(value);
    setResult(null);
    setError(null);
  }, []);

  const handleTargetDbChange = useCallback((value: DbType) => {
    setTargetDb(value);
    setResult(null);
    setError(null);
  }, []);

  const handleRewrite = useCallback(async () => {
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
      const res = await rewriteSql({
        sql: sql.trim(),
        source_db: sourceDb,
        target_db: targetDb,
      });
      setResult(res);

      const ruleCount = res.rules_applied.length;
      const pct = Math.round(res.confidence * 100);
      if (ruleCount > 0) {
        message.success(
          `改写完成 — 应用 ${ruleCount} 条规则，置信度 ${pct}%`,
        );
      } else {
        message.info("SQL 无需改写，在目标数据库中完全兼容");
      }
    } catch (err) {
      const errMsg = `请求失败: ${String(err)}`;
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

  // Prevent selecting same source and target
  const targetOptions = [
    { value: "mssql", label: "MSSQL", disabled: sourceDb === "mssql" },
    {
      value: "kingbasees",
      label: "KingbaseES",
      disabled: sourceDb === "kingbasees",
    },
    { value: "dm8", label: "DM8", disabled: sourceDb === "dm8" },
  ];

  const sourceOptions = [
    { value: "mssql", label: "MSSQL" },
    { value: "kingbasees", label: "KingbaseES" },
    { value: "dm8", label: "DM8" },
  ];

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
            <SwapOutlined style={{ marginRight: 8 }} />
            SQL Rewrite Engine
          </Title>
          <Text type="secondary">
            输入源数据库方言 SQL → 自动改写为目标数据库语法
          </Text>
        </div>
        <Tag
          color={
            backendOnline
              ? "green"
              : backendOnline === false
                ? "red"
                : "default"
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
              onChange={handleSourceDbChange}
              style={{ width: 140 }}
              options={sourceOptions}
            />
          </div>

          <SwapOutlined
            style={{ fontSize: 16, color: "#1677ff", margin: "0 4px" }}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Text strong>目标数据库:</Text>
            <Select
              value={targetDb}
              onChange={handleTargetDbChange}
              style={{ width: 140 }}
              options={targetOptions}
            />
          </div>

          <Divider orientation="vertical" />

          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleRewrite}
            loading={loading}
            size="middle"
          >
            执行改写 (Ctrl+Enter)
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
        <SqlEditor value={sql} onChange={setSql} onExecute={handleRewrite} />
      </Card>

      {/* Results area */}
      <Spin spinning={loading} description="正在分析 SQL 并执行改写...">
        {result === null && error === null ? (
          <Card styles={{ body: { padding: 48 } }} style={{ borderRadius: 12 }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <SwapOutlined
                style={{ fontSize: 48, color: "#d9d9d9", marginBottom: 16 }}
              />
              <br />
              <Text type="secondary">
                输入 SQL，选择源数据库和目标数据库，点击「执行改写」查看转换结果
              </Text>
            </div>
          </Card>
        ) : error ? (
          <Card styles={{ body: { padding: 24 } }} style={{ borderRadius: 12 }}>
            <Text type="danger">{error}</Text>
          </Card>
        ) : result ? (
          <>
            {/* Main rewrite panel + confidence/rules */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col xs={24} lg={16}>
                <Card
                  styles={{ body: { padding: 16 } }}
                  style={{ borderRadius: 12 }}
                >
                  <RewritePanel
                    originalSql={result.original_sql}
                    rewrittenSql={result.rewritten_sql}
                    sourceDb={result.source_db}
                    targetDb={result.target_db}
                  />
                </Card>
              </Col>
              <Col xs={24} lg={8}>
                {/* Confidence */}
                <Card
                  styles={{ body: { padding: "20px 24px" } }}
                  style={{ borderRadius: 12, marginBottom: 16 }}
                >
                  <Text
                    strong
                    style={{ display: "block", marginBottom: 12, fontSize: 14 }}
                  >
                    改写置信度
                  </Text>
                  <ConfidenceBadge confidence={result.confidence} />
                </Card>

                {/* Warnings */}
                {result.warnings.length > 0 && (
                  <Card
                    title="⚠️ 警告"
                    size="small"
                    styles={{
                      body: { padding: "8px 16px" },
                      header: { borderBottom: "none", paddingBottom: 0 },
                    }}
                    style={{ borderRadius: 12, marginBottom: 16 }}
                  >
                    {result.warnings.map((w, i) => (
                      <Text
                        key={i}
                        type="warning"
                        style={{
                          fontSize: 12,
                          display: "block",
                          marginBottom: 4,
                        }}
                      >
                        {w}
                      </Text>
                    ))}
                  </Card>
                )}
              </Col>
            </Row>

            {/* Applied Rules */}
            <Card
              title={
                <span>
                  📋 应用的改写规则
                  {result.rules_applied.length > 0 && (
                    <Tag
                      style={{ marginLeft: 8 }}
                      color="#1677ff"
                    >
                      {result.rules_applied.length} 条
                    </Tag>
                  )}
                </span>
              }
              styles={{ body: { padding: "16px 24px" } }}
              style={{ borderRadius: 12 }}
            >
              <RuleList rules={result.rules_applied} />
            </Card>
          </>
        ) : null}
      </Spin>

      {/* Footer */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Rewrite Engine • Phase 2 Step 3 •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
