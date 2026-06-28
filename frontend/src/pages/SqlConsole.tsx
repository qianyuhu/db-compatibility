import { useState, useCallback, useEffect } from "react";
import { Button, Space, Card, Typography, Divider, Spin, message, Tag } from "antd";
import { PlayCircleOutlined, ClearOutlined, ApiOutlined } from "@ant-design/icons";
import DbSelector, { type DbType } from "../components/DbSelector";
import SqlEditor from "../components/SqlEditor";
import ResultTable from "../components/ResultTable";
import ErrorPanel from "../components/ErrorPanel";
import { executeSql, healthCheck, type ExecuteResponse } from "../api/sqlDemo";

const { Title, Text } = Typography;

const DEFAULT_SQL: Record<DbType, string> = {
  mssql: "-- MSSQL: 查询系统表\nSELECT TOP 10 name, object_id, create_date\nFROM sys.tables\nWHERE type = 'U'\nORDER BY name",
  kingbasees: "-- KingbaseES MSSQL Compatible\nSELECT TOP 10 * FROM sys.sysobjects WHERE type = 'U'",
  dm8: "-- DM8: 查询所有用户表\nSELECT table_name FROM user_tables FETCH FIRST 10 ROWS ONLY",
};

export default function SqlConsole() {
  const [dbType, setDbType] = useState<DbType>("mssql");
  const [sql, setSql] = useState(DEFAULT_SQL.mssql);
  const [result, setResult] = useState<ExecuteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // 检查后端连通性（首次渲染时）
  useEffect(() => {
    healthCheck().then(setBackendOnline);
  }, []);

  const handleDbChange = useCallback(
    (db: DbType) => {
      setDbType(db);
      setSql(DEFAULT_SQL[db]);
      setResult(null);
    },
    [],
  );

  const handleExecute = useCallback(async () => {
    if (!sql.trim()) {
      message.warning("请输入 SQL 语句");
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const res = await executeSql({ db_type: dbType, sql: sql.trim() });
      setResult(res);

      if (!res.success) {
        message.error("SQL 执行失败");
      } else {
        message.success(`查询完成 — 返回 ${res.row_count} 行 (${res.execution_time_ms}ms)`);
      }
    } catch (err) {
      setResult({
        success: false,
        columns: [],
        rows: [],
        row_count: 0,
        db_type: dbType,
        execution_time_ms: 0,
        error: `网络错误: ${String(err)}`,
        suggestion: "检查后端服务是否运行在 http://localhost:8000",
      });
      message.error("网络请求失败");
    } finally {
      setLoading(false);
    }
  }, [dbType, sql]);

  const handleClear = useCallback(() => {
    setResult(null);
  }, []);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px" }}>
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
            <ApiOutlined style={{ marginRight: 8 }} />
            SQL Demo Console
          </Title>
          <Text type="secondary">
            Multi-Database SQL Execution Platform — MSSQL / KingbaseES / DM8
          </Text>
        </div>
        <Tag color={backendOnline ? "green" : backendOnline === false ? "red" : "default"}>
          {backendOnline ? "后端在线" : backendOnline === false ? "后端离线" : "检测中..."}
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
          <DbSelector value={dbType} onChange={handleDbChange} />
          <Divider orientation="vertical" />
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleExecute}
            loading={loading}
            size="middle"
          >
            执行查询 (Ctrl+Enter)
          </Button>
          <Button icon={<ClearOutlined />} onClick={handleClear} disabled={!result}>
            清空结果
          </Button>
        </Space>
      </Card>

      {/* SQL 编辑器 */}
      <Card
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: 0 } }}
      >
        <SqlEditor
          value={sql}
          onChange={setSql}
          onExecute={handleExecute}
        />
      </Card>

      {/* 结果区域 */}
      <Spin spinning={loading} description="正在执行查询...">
        <Card
          styles={{ body: { padding: 16 } }}
        >
          {result === null ? (
            <div
              style={{
                textAlign: "center",
                padding: 48,
                color: "#bfbfbf",
              }}
            >
              <Text type="secondary">
                输入 SQL 语句，选择目标数据库，点击「执行查询」或按 Ctrl+Enter
              </Text>
            </div>
          ) : result.success ? (
            <ResultTable
              columns={result.columns}
              rows={result.rows}
              executionTimeMs={result.execution_time_ms}
            />
          ) : (
            <ErrorPanel error={result.error!} suggestion={result.suggestion} />
          )}
        </Card>
      </Spin>

      {/* 页脚 */}
      <Divider />
      <div style={{ textAlign: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          Phase 1 → Phase 2 Transition • SQL Compatibility Demo •{" "}
          {new Date().getFullYear()}
        </Text>
      </div>
    </div>
  );
}
