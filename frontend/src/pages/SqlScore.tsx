/**
 * SqlScore — SQL Compatibility Score Engine page.
 *
 * Layout:
 *   ┌─────────────────────────────────────────┐
 *   │  Toolbar: DB Selector + [RUN SCORE]     │
 *   ├─────────────────────────────────────────┤
 *   │  SQL Editor                             │
 *   ├──────────────┬──────────────────────────┤
 *   │  Score Card  │  Radar Chart             │
 *   ├──────────────┴──────────────────────────┤
 *   │  Findings List                          │
 *   ├─────────────────────────────────────────┤
 *   │  Suggestions Panel                      │
 *   └─────────────────────────────────────────┘
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
  ExperimentOutlined,
  ClearOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import ScoreCard from "../components/ScoreCard";
import RadarChart from "../components/RadarChart";
import FindingsList from "../components/FindingsList";
import SuggestionPanel from "../components/SuggestionPanel";
import { scoreSql, type ScoreResponse } from "../api/sqlScore";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text } = Typography;

type DbType = "mssql" | "kingbasees" | "dm8";

const DEFAULT_SQL = `-- SQL 兼容性评分测试
-- 系统将评估此 SQL 在各数据库中的兼容性
SELECT TOP 10 id, name, price, created_at
FROM products
WHERE is_active = 1
ORDER BY created_at DESC`;

export default function SqlScore() {
  const [selectedDbs, setSelectedDbs] = useState<DbType[]>([
    "mssql",
    "kingbasees",
  ]);
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // Backend connectivity check
  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handleDbChange = useCallback((value: DbType[]) => {
    if (value.length >= 1) {
      setSelectedDbs(value);
      setResult(null);
      setError(null);
    }
  }, []);

  const handleExecute = useCallback(async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }
    if (selectedDbs.length === 0) {
      message.warning("请选择至少 1 个数据库");
      return;
    }

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await scoreSql({
        sql: sql.trim(),
        db_types: selectedDbs,
      });
      setResult(res);

      if (res.score >= 90) {
        message.success(`评分完成 — ${res.score}/100 (${res.level})`);
      } else if (res.score >= 70) {
        message.warning(`评分完成 — ${res.score}/100 (${res.level})`);
      } else {
        message.error(`评分完成 — ${res.score}/100 (${res.level})`);
      }
    } catch (err) {
      const errMsg = `请求失败: ${String(err)}`;
      setError(errMsg);
      message.error(errMsg);
    } finally {
      setLoading(false);
    }
  }, [sql, selectedDbs]);

  const handleClear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

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
            <ExperimentOutlined style={{ marginRight: 8 }} />
            SQL Compatibility Score
          </Title>
          <Text type="secondary">
            输入 SQL → 多库执行 → 四维评分（语法·执行·结果·风险）→ 改写建议
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
              value={selectedDbs}
              onChange={handleDbChange}
              style={{ minWidth: 280 }}
              maxCount={3}
              options={[
                { value: "mssql", label: "MSSQL" },
                { value: "kingbasees", label: "KingbaseES" },
                { value: "dm8", label: "DM8" },
              ]}
            />
          </div>
          <Divider orientation="vertical" />
          <Button
            type="primary"
            icon={<TrophyOutlined />}
            onClick={handleExecute}
            loading={loading}
            size="middle"
          >
            运行评分 (Ctrl+Enter)
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
        <SqlEditor value={sql} onChange={setSql} onExecute={handleExecute} />
      </Card>

      {/* Results area */}
      <Spin spinning={loading} description="正在执行 SQL 并计算兼容性评分...">
        {result === null && error === null ? (
          <Card styles={{ body: { padding: 48 } }} style={{ borderRadius: 12 }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <ExperimentOutlined
                style={{ fontSize: 48, color: "#d9d9d9", marginBottom: 16 }}
              />
              <br />
              <Text type="secondary">
                输入 SQL，选择目标数据库，点击「运行评分」查看兼容性分析
              </Text>
            </div>
          </Card>
        ) : error ? (
          <Card styles={{ body: { padding: 24 } }} style={{ borderRadius: 12 }}>
            <Text type="danger">{error}</Text>
          </Card>
        ) : result ? (
          <>
            {/* Score Card + Radar Chart */}
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col xs={24} lg={14}>
                <ScoreCard
                  score={result.score}
                  level={result.level}
                  breakdown={result.breakdown}
                  dbCount={result.db_count}
                  executionTimeMs={result.execution_time_ms}
                />
              </Col>
              <Col xs={24} lg={10}>
                <Card
                  title="📊 维度雷达图"
                  styles={{ body: { padding: "8px" } }}
                  style={{ borderRadius: 12, height: "100%" }}
                >
                  <RadarChart breakdown={result.breakdown} score={result.score} size={260} />
                </Card>
              </Col>
            </Row>

            {/* Findings */}
            <div style={{ marginBottom: 16 }}>
              <FindingsList findings={result.findings} />
            </div>

            {/* Suggestions */}
            <SuggestionPanel suggestions={result.suggestions} />
          </>
        ) : null}
      </Spin>

      {/* Footer */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Compatibility Score Engine • Phase 2 Step 2 •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
