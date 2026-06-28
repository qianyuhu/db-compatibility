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
  Alert,
  Row,
  Col,
} from "antd";
import {
  PlayCircleOutlined,
  ClearOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import SqlEditor from "../components/SqlEditor";
import SideBySideResult from "../components/SideBySideResult";
import DiffTable from "../components/DiffTable";
import {
  compareSql,
  healthCheck,
  type CompareResponse,
} from "../api/sqlDemo";

const { Title, Text } = Typography;

type DbType = "mssql" | "kingbasees" | "dm8";

const DB_LABELS: Record<string, string> = {
  mssql: "MSSQL",
  kingbasees: "KingbaseES",
  dm8: "DM8",
};

const DB_COLORS: Record<string, string> = {
  mssql: "#1677ff",
  kingbasees: "#52c41a",
  dm8: "#fa8c16",
};

const COMPARE_PAIRS: { label: string; value: DbType[] }[] = [
  { label: "MSSQL ↔ KingbaseES", value: ["mssql", "kingbasees"] },
  { label: "MSSQL ↔ DM8", value: ["mssql", "dm8"] },
  { label: "KingbaseES ↔ DM8", value: ["kingbasees", "dm8"] },
  { label: "全部 (三库)", value: ["mssql", "kingbasees", "dm8"] },
];

const DEFAULT_SQL = `-- 跨库兼容性对比 SQL
-- 提示：选择不同的对比组合来测试兼容性
SELECT TOP 10 name, object_id, create_date
FROM sys.tables
ORDER BY name`;

export default function SqlCompare() {
  const [selectedPair, setSelectedPair] = useState<DbType[]>([
    "mssql",
    "kingbasees",
  ]);
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // 后端连通性检查
  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handlePairChange = useCallback((value: DbType[]) => {
    if (value.length >= 2) {
      setSelectedPair(value);
      setResult(null);
    }
  }, []);

  const handleExecute = useCallback(async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }
    if (selectedPair.length < 2) {
      message.warning("请至少选择 2 个数据库进行对比");
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const res = await compareSql({
        sql: sql.trim(),
        db_types: selectedPair,
      });
      setResult(res);

      const allSuccess = Object.values(res.results).every((r) => r.success);
      if (allSuccess) {
        const hasDiff =
          res.diff.row_count_diff ||
          res.diff.column_diff ||
          res.diff.value_diff.length > 0;

        if (hasDiff) {
          message.warning("对比完成 — 检测到差异");
        } else {
          message.success("对比完成 — 各库返回结果一致");
        }
      } else {
        message.error("部分数据库执行失败，请查看详情");
      }
    } catch (err) {
      message.error(`网络请求失败: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [sql, selectedPair]);

  const handleClear = useCallback(() => {
    setResult(null);
  }, []);

  const dbTypes = selectedPair;

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 16px" }}>
      {/* 页头 */}
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
            SQL Compare Mode
          </Title>
          <Text type="secondary">
            同一 SQL 多库并行执行 • Schema / Row Count / Value 三维度差异分析
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

      {/* 工具栏 */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: "12px 16px" } }}
      >
        <Space wrap size="middle">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Text strong>对比组合:</Text>
            <Select
              mode="multiple"
              value={selectedPair}
              onChange={handlePairChange}
              style={{ minWidth: 340 }}
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
            icon={<PlayCircleOutlined />}
            onClick={handleExecute}
            loading={loading}
            size="middle"
          >
            执行对比 (Ctrl+Enter)
          </Button>
          <Button
            icon={<ClearOutlined />}
            onClick={handleClear}
            disabled={!result}
          >
            清空结果
          </Button>
        </Space>

        {/* 快速选择 */}
        <div style={{ marginTop: 8 }}>
          <Space size={4} wrap>
            <Text type="secondary" style={{ fontSize: 12 }}>
              快速选择:
            </Text>
            {COMPARE_PAIRS.map((pair) => (
              <Tag
                key={pair.label}
                style={{ cursor: "pointer" }}
                color={
                  pair.value.length === selectedPair.length &&
                  pair.value.every((v) => selectedPair.includes(v))
                    ? "blue"
                    : undefined
                }
                onClick={() => handlePairChange(pair.value)}
              >
                {pair.label}
              </Tag>
            ))}
          </Space>
        </div>
      </Card>

      {/* SQL 编辑器 */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: 0 } }}>
        <SqlEditor value={sql} onChange={setSql} onExecute={handleExecute} />
      </Card>

      {/* SQL 改写建议 */}
      {result && result.rewrites.length > 0 && (
        <Alert
          type="info"
          showIcon
          message="💡 SQL 方言改写建议"
          description={
            <div>
              {result.rewrites.map((rw, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{ marginTop: 8 }}
                  styles={{ body: { padding: 12 } }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 6,
                    }}
                  >
                    <Tag color={DB_COLORS[rw.db_type] || "default"}>
                      {DB_LABELS[rw.db_type] || rw.db_type}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {rw.reason}
                    </Text>
                  </div>
                  <Row gutter={12}>
                    <Col span={12}>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        原始:
                      </Text>
                      <pre
                        style={{
                          margin: "4px 0 0",
                          padding: 8,
                          background: "#fff2f0",
                          borderRadius: 4,
                          fontSize: 12,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-all",
                        }}
                      >
                        {rw.original}
                      </pre>
                    </Col>
                    <Col span={12}>
                      <Text style={{ fontSize: 11, color: "#389e0d" }}>
                        建议:
                      </Text>
                      <pre
                        style={{
                          margin: "4px 0 0",
                          padding: 8,
                          background: "#f6ffed",
                          borderRadius: 4,
                          fontSize: 12,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-all",
                          cursor: "pointer",
                        }}
                        onClick={() => {
                          setSql(rw.suggested);
                          message.info("已填入改写后的 SQL");
                        }}
                      >
                        {rw.suggested}
                      </pre>
                    </Col>
                  </Row>
                </Card>
              ))}
            </div>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 对比结果 */}
      <Spin spinning={loading} description="正在并行执行查询...">
        {result === null ? (
          <Card styles={{ body: { padding: 48 } }}>
            <div style={{ textAlign: "center", color: "#bfbfbf" }}>
              <Text type="secondary">
                输入 SQL 语句，选择 2-3 个目标数据库，点击「执行对比」查看差异分析
              </Text>
            </div>
          </Card>
        ) : (
          <>
            {/* 并排结果 */}
            <Card
              size="small"
              title="📋 执行结果（并排对比）"
              style={{ marginBottom: 16 }}
              styles={{ body: { padding: 12 } }}
            >
              <Row gutter={16}>
                {dbTypes.map((db, idx) => (
                  <Col
                    key={db}
                    span={dbTypes.length === 2 ? 12 : 8}
                    style={{ marginBottom: idx < dbTypes.length ? 0 : 16 }}
                  >
                    <SideBySideResult
                      dbLabel={DB_LABELS[db]}
                      color={DB_COLORS[db]}
                      result={result.results[db]}
                    />
                  </Col>
                ))}
              </Row>
            </Card>

            {/* Diff Panel */}
            <Card
              size="small"
              title="🔬 Diff 分析面板"
              style={{ marginBottom: 16 }}
              styles={{ body: { padding: 12 } }}
            >
              <DiffTable diff={result.diff} />
            </Card>
          </>
        )}
      </Spin>

      {/* 页脚 */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          SQL Compatibility Analysis System • Phase 2 Transition •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
