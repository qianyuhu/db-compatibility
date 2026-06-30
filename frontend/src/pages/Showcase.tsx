import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Tag,
  Spin,
  Alert,
  Typography,
  Row,
  Col,
  Collapse,
  Segmented,
  Space,
  Descriptions,
  Empty,
  Badge,
  message,
} from "antd";
import {
  PlayCircleOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  CodeOutlined,
} from "@ant-design/icons";
import SideBySideResult from "../components/SideBySideResult";
import DiffTable from "../components/DiffTable";
import type { SceneListItem, SceneResult } from "../api/showcase";
import { fetchScenes, executeScene, resetShowcase } from "../api/showcase";
import { healthCheck } from "../api/sqlDemo";

const { Title, Text, Paragraph } = Typography;

// =========================================================================
// Color constants (matching backend DB_COLORS)
// =========================================================================

const DB_CONFIG: Record<string, { label: string; color: string }> = {
  mssql: { label: "MSSQL", color: "#1677ff" },
  kingbasees: { label: "KingbaseES", color: "#52c41a" },
  dm8: { label: "DM8", color: "#fa8c16" },
};

const TYPE_COLORS: Record<string, string> = {
  SQL: "#1677ff",
  API: "#52c41a",
  ORM: "#fa8c16",
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  SQL: <CodeOutlined />,
  API: <ApiOutlined />,
  ORM: <ThunderboltOutlined />,
};

// =========================================================================
// Component
// =========================================================================

export default function Showcase() {
  const [scenes, setScenes] = useState<SceneListItem[]>([]);
  const [activeCategory, setActiveCategory] = useState<string>("SQL");
  const [results, setResults] = useState<Record<string, SceneResult>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [expandedScene, setExpandedScene] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [resetting, setResetting] = useState(false);

  // Load scenes on mount
  useEffect(() => {
    healthCheck().then(setBackendOnline);
    fetchScenes().then(setScenes);
  }, []);

  // Execute a scene
  const handleExecute = useCallback(
    async (sceneId: string) => {
      setLoading((prev) => ({ ...prev, [sceneId]: true }));
      setExpandedScene(sceneId);

      try {
        const result = await executeScene(sceneId);
        setResults((prev) => ({ ...prev, [sceneId]: result }));
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
      } catch (_err: unknown) {
        message.error(`场景 ${sceneId} 执行失败`);
      } finally {
        setLoading((prev) => ({ ...prev, [sceneId]: false }));
      }
    },
    [],
  );

  // Reset all DB data
  const handleReset = useCallback(async () => {
    setResetting(true);
    try {
      const res = await resetShowcase();
      if (res.success) {
        message.success("三库数据已重置");
      } else {
        const failed = Object.entries(res.results)
          .filter(([, r]) => !r.success)
          .map(([db]) => db)
          .join(", ");
        message.warning(`部分数据库重置失败: ${failed || "未知"}`);
      }
      // Clear all results after reset
      setResults({});
      setExpandedScene(null);
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
    } catch (_err: unknown) {
      message.error("数据重置失败，检查后端连接");
    } finally {
      setResetting(false);
    }
  }, []);

  // Filter scenes by active category
  const filteredScenes = scenes.filter((s) => s.type === activeCategory);

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px" }}>
      {/* ================================================================ */}
      {/* Header                                                          */}
      {/* ================================================================ */}
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
            🎬 迁移能力展示中心
          </Title>
          <Text type="secondary">
            Migration Capability Showcase — 多数据库迁移能力可视化演示
          </Text>
        </div>
        <Space>
          {backendOnline !== null && (
            <Badge
              status={backendOnline ? "success" : "error"}
              text={backendOnline ? "后端在线" : "后端离线"}
            />
          )}
          <Button
            icon={<ReloadOutlined />}
            onClick={handleReset}
            loading={resetting}
            danger
          >
            重置数据
          </Button>
        </Space>
      </div>

      {/* ================================================================ */}
      {/* Category Tabs                                                   */}
      {/* ================================================================ */}
      <Segmented
        value={activeCategory}
        onChange={(val) => setActiveCategory(val as string)}
        options={[
          { label: "🔍 SQL 场景", value: "SQL" },
          { label: "🔗 API 场景", value: "API" },
          { label: "⚡ ORM 场景", value: "ORM" },
        ]}
        size="large"
        style={{ marginBottom: 24 }}
      />

      {/* ================================================================ */}
      {/* Scene Cards Grid                                                */}
      {/* ================================================================ */}
      {filteredScenes.length === 0 ? (
        <Empty description="暂无场景数据" />
      ) : (
        <Row gutter={[16, 16]}>
          {filteredScenes.map((scene) => {
            const sceneResult = results[scene.scene_id];
            const isExpanded = expandedScene === scene.scene_id;
            const isLoading = loading[scene.scene_id];
            const isExecuted = !!sceneResult;

            return (
              <Col xs={24} lg={12} xl={8} key={scene.scene_id}>
                <Card
                  hoverable
                  style={{
                    height: "100%",
                    borderColor: isExpanded
                      ? TYPE_COLORS[scene.type]
                      : undefined,
                    borderWidth: isExpanded ? 2 : 1,
                  }}
                  onClick={() =>
                    setExpandedScene(
                      isExpanded ? null : scene.scene_id,
                    )
                  }
                  title={
                    <Space>
                      <Tag color={TYPE_COLORS[scene.type]}>
                        {TYPE_ICONS[scene.type]} {scene.type}
                      </Tag>
                      <Text strong>{scene.scene_name}</Text>
                    </Space>
                  }
                  extra={
                    <Button
                      type="primary"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      loading={isLoading}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleExecute(scene.scene_id);
                      }}
                    >
                      执行场景
                    </Button>
                  }
                >
                  <Paragraph
                    type="secondary"
                    style={{ marginBottom: 8 }}
                    ellipsis={{ rows: 2 }}
                  >
                    {scene.description}
                  </Paragraph>

                  {/* Tags */}
                  {scene.tags.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {scene.tags.map((tag) => (
                        <Tag key={tag} style={{ marginBottom: 4 }}>
                          {tag}
                        </Tag>
                      ))}
                    </div>
                  )}

                  {/* Brief insight preview */}
                  {scene.migration_insight && (
                    <Paragraph
                      type="secondary"
                      style={{
                        fontSize: 12,
                        marginBottom: 0,
                        padding: 8,
                        background: "#f6f8fa",
                        borderRadius: 4,
                      }}
                      ellipsis={{ rows: 1 }}
                    >
                      💡 {scene.migration_insight}
                    </Paragraph>
                  )}
                </Card>

                {/* ======================================================== */}
                {/* Expanded Result Panel                                   */}
                {/* ======================================================== */}
                {isExpanded && (
                  <Card
                    style={{
                      marginTop: 12,
                      borderColor: TYPE_COLORS[scene.type],
                    }}
                  >
                    {isLoading ? (
                      <div style={{ textAlign: "center", padding: 40 }}>
                        <Spin size="large" tip="正在三库并行执行..." />
                      </div>
                    ) : !isExecuted ? (
                      <Empty description="点击「执行场景」查看三库对比结果" />
                    ) : sceneResult.status === "error" ? (
                      <Alert
                        type="error"
                        message="场景执行失败"
                        description={
                          sceneResult.error || "未知错误"
                        }
                        showIcon
                      />
                    ) : (
                      <ShowcaseResultView
                        result={sceneResult}
                        scene={scene}
                      />
                    )}
                  </Card>
                )}
              </Col>
            );
          })}
        </Row>
      )}
    </div>
  );
}

// =========================================================================
// Result View Sub-component
// =========================================================================

function ShowcaseResultView({
  result,
  scene,
}: {
  result: SceneResult;
  scene: SceneListItem;
}) {
  const totalTime = result.execution_time_ms;
  const dbTypes = Object.keys(result.results);
  const allSuccess = dbTypes.every(
    (db) => result.results[db]?.success,
  );
  const hasDiff =
    result.diff.row_count_diff ||
    result.diff.column_diff ||
    result.diff.value_diff.length > 0;

  return (
    <div>
      {/* Status Bar */}
      <Descriptions
        size="small"
        column={3}
        style={{ marginBottom: 16 }}
        items={[
          {
            key: "status",
            label: "执行状态",
            children: allSuccess ? (
              <Tag icon={<CheckCircleOutlined />} color="success">
                全部成功
              </Tag>
            ) : (
              <Tag icon={<CloseCircleOutlined />} color="error">
                部分失败
              </Tag>
            ),
          },
          {
            key: "diff_status",
            label: "差异状态",
            children: hasDiff ? (
              <Tag color="warning">发现差异</Tag>
            ) : (
              <Tag color="success">完全一致</Tag>
            ),
          },
          {
            key: "time",
            label: "总耗时",
            children: (
              <Text type="secondary">{totalTime}ms</Text>
            ),
          },
        ]}
      />

      {/* Diff Summary Alert */}
      {result.diff_summary && (
        <Alert
          type={hasDiff ? "warning" : "success"}
          message={result.diff_summary}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Three-column Side-by-Side Results */}
      <Title level={5} style={{ marginBottom: 12 }}>
        📊 三库执行结果对比
      </Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {dbTypes.map((dbType) => (
          <Col xs={24} md={8} key={dbType}>
            <SideBySideResult
              dbLabel={DB_CONFIG[dbType]?.label ?? dbType}
              color={DB_CONFIG[dbType]?.color ?? "#999"}
              result={result.results[dbType]}
            />
          </Col>
        ))}
      </Row>

      {/* ORM SQL Display (only for ORM scenes) */}
      {result.orm_sql_generated &&
        Object.keys(result.orm_sql_generated).length > 0 && (
          <>
            <Title level={5} style={{ marginBottom: 12 }}>
              🔧 ORM 生成 SQL (各数据库方言)
            </Title>
            <Collapse
              size="small"
              style={{ marginBottom: 16 }}
              items={Object.entries(result.orm_sql_generated).map(
                ([dbType, sql]) => ({
                  key: dbType,
                  label: (
                    <Tag color={DB_CONFIG[dbType]?.color}>
                      {DB_CONFIG[dbType]?.label ?? dbType}
                    </Tag>
                  ),
                  children: (
                    <pre
                      style={{
                        background: "#1e1e1e",
                        color: "#d4d4d4",
                        padding: 16,
                        borderRadius: 6,
                        fontSize: 13,
                        overflow: "auto",
                        maxHeight: 300,
                        margin: 0,
                      }}
                    >
                      {sql}
                    </pre>
                  ),
                }),
              )}
            />
          </>
        )}

      {/* Diff Details */}
      <Title level={5} style={{ marginBottom: 12 }}>
        🔍 差异详情
      </Title>
      <DiffTable diff={result.diff} />

      {/* Key Differences */}
      {scene.key_differences.length > 0 && (
        <Alert
          type="info"
          message="⚠️ 已知差异点"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {scene.key_differences.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          }
          showIcon
          style={{ marginTop: 16 }}
        />
      )}

      {/* Migration Insight */}
      {result.migration_insight && (
        <Alert
          type="success"
          message="💡 迁移洞察 (Migration Insight)"
          description={
            <Paragraph
              style={{ margin: 0, whiteSpace: "pre-wrap" }}
            >
              {result.migration_insight}
            </Paragraph>
          }
          showIcon
          style={{ marginTop: 12 }}
        />
      )}
    </div>
  );
}
