/**
 * CFG Execution Workbench — Interactive CFG visualization and step debugger.
 *
 * 4-panel layout:
 *   Left:    SP / IR / CFG / Trace tabs
 *   Center:  React Flow graph canvas with draggable nodes
 *   Right:   Execution Inspector (node details + DB results + diff)
 *   Bottom:  Execution Timeline
 *
 * Core interactions:
 *   - Click node → inspect in right panel
 *   - "Run Node" → execute selected node against all 3 DBs
 *   - "Run All" → sequential execution with breakpoint support
 *   - Path highlighting (true_branch=green, false_branch=gray)
 *   - Replay execution trace
 */

import { useState, useCallback, useRef } from "react";
import {
  Card,
  Button,
  Select,
  Tag,
  Spin,
  Alert,
  Row,
  Col,
  Typography,
  Tabs,
  Space,
  Divider,
  Empty,
  Input,
  Tooltip,
} from "antd";
import {
  PlayCircleOutlined,
  StepForwardOutlined,
  ReloadOutlined,
  BugOutlined,
  PauseCircleOutlined,
  CodeOutlined,
  ApartmentOutlined,
  NodeIndexOutlined,
  HistoryOutlined,
} from "@ant-design/icons";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type ConnectionLineType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import SqlEditor from "../components/SqlEditor";
import { cfgNodeTypes } from "../components/cfg/CfgNodes";
import CfgEdge from "../components/cfg/CfgEdge";
import ExecutionInspector from "../components/cfg/ExecutionInspector";
import ExecutionTimeline from "../components/cfg/ExecutionTimeline";
import {
  compileSP,
  executeNode as apiExecuteNode,
  executeAllNodes,
  getTrace,
  type UIGraphModel,
  type UINode,
  type UIEdge as UIEdgeType,
  type NodeExecutionResult,
  type ExecuteNodeResponse,
} from "../api/cfgWorkbench";

const { Title, Text, Paragraph } = Typography;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DB_OPTIONS = [
  { value: "mssql", label: "MSSQL (SQL Server)", color: "#1677ff" },
  { value: "kingbasees", label: "KingbaseES (金仓)", color: "#52c41a" },
  { value: "dm8", label: "DM8 (达梦)", color: "#fa8c16" },
];

const DEFAULT_ALL_DBS = ["mssql", "kingbasees", "dm8"];

const DEFAULT_TSQL = `CREATE PROCEDURE check_stock
    @product_id INT,
    @min_qty INT
AS
BEGIN
    DECLARE @current_qty INT;
    SET @current_qty = 0;
    SELECT @current_qty = quantity FROM inventory WHERE product_id = @product_id;
    IF @current_qty < @min_qty
    BEGIN
        SELECT 'Low stock' AS status;
    END
    ELSE
    BEGIN
        SELECT 'OK' AS status;
    END
END`;

const edgeTypes = { default: CfgEdge };

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

/** Convert UIGraphModel to React Flow nodes. O(n) via pre-computed block map. */
function toFlowNodes(uiNodes: UINode[]): Node[] {
  const SPACING_Y = 120;
  const SPACING_X = 220;

  // Pre-compute block_id → ordered node list for O(1) lookup
  const byBlock = new Map<number, UINode[]>();
  for (const n of uiNodes) {
    const list = byBlock.get(n.block_id);
    if (list) {
      list.push(n);
    } else {
      byBlock.set(n.block_id, [n]);
    }
  }

  // Build position index for each node within its block
  const posInBlock = new Map<string, number>();
  for (const [, blockNodes] of byBlock) {
    blockNodes.forEach((n, i) => {
      posInBlock.set(n.id, i);
    });
  }

  return uiNodes.map((n) => {
    const col = n.block_id * SPACING_X;
    const row = (posInBlock.get(n.id) ?? 0) * SPACING_Y;

    return {
      id: n.id,
      type: n.type,
      position: { x: col + 50, y: row + 50 },
      data: { ...n },
    };
  });
}

/** Convert UIEdge list to React Flow edges. */
function toFlowEdges(uiEdges: UIEdgeType[]): Edge[] {
  return uiEdges.map((e) => {
    // Determine source handle based on edge type
    const sourceHandle =
      e.edge_type === "true_branch" ? "true"
      : e.edge_type === "false_branch" ? "false"
      : undefined;

    return {
      id: e.id,
      source: e.from_id,
      target: e.to_id,
      sourceHandle,
      type: "default",
      data: {
        edge_type: e.edge_type,
        label: e.label,
        condition: e.condition,
      },
      animated: e.edge_type === "true_branch" || e.edge_type === "loop_back",
      style: {
        stroke: e.edge_type === "true_branch" || e.edge_type === "loop_back" ? "#52c41a"
              : e.edge_type === "false_branch" ? "#ff4d4f"
              : "#8c8c8c",
        strokeWidth: e.edge_type === "sequential" ? 1.5 : 2,
        strokeDasharray: e.edge_type === "false_branch" ? "4 4"
                       : e.edge_type === "true_branch" || e.edge_type === "loop_back" ? "8 4"
                       : undefined,
      },
    };
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CfgWorkbench() {
  // --- State ---
  const [tsql, setTsql] = useState(DEFAULT_TSQL);
  const [targetDbs, setTargetDbs] = useState<string[]>([...DEFAULT_ALL_DBS]);
  const [graphModel, setGraphModel] = useState<UIGraphModel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [executionResults, setExecutionResults] = useState<Map<string, NodeExecutionResult>>(new Map());
  const [timelineEntries, setTimelineEntries] = useState<
    { nodeId: string; status: string; executionTimeMs: number }[]
  >([]);
  const [activeTab, setActiveTab] = useState("tsql");
  const [breakpoints, setBreakpoints] = useState<Set<string>>(new Set());
  const sessionIdRef = useRef<string>("");

  // React Flow state
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // --- Compile ---
  const handleCompile = useCallback(async () => {
    setCompiling(true);
    setLoadError(null);
    try {
      const res = await compileSP(tsql, targetDbs);
      if (!res.success) {
        setLoadError(res.errors.join("; "));
        setGraphModel(null);
        return;
      }
      if (!res.graph_model) {
        setLoadError("No graph model returned");
        return;
      }
      setGraphModel(res.graph_model);

      // Convert to React Flow format
      const nodes = toFlowNodes(res.graph_model.nodes);
      const edges = toFlowEdges(res.graph_model.edges);
      setFlowNodes(nodes);
      setFlowEdges(edges);

      // Reset execution state
      setExecutionResults(new Map());
      setTimelineEntries([]);
      setSelectedNodeId(null);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : "Compile failed");
    } finally {
      setCompiling(false);
    }
  }, [tsql, targetDbs, setFlowNodes, setFlowEdges]);

  // --- Execute single node ---
  const handleExecuteNode = useCallback(async (nodeId?: string) => {
    const targetId = nodeId || selectedNodeId;
    if (!targetId) return;

    // Find the node in the graph model
    const node = graphModel?.nodes.find((n) => n.id === targetId);
    if (!node) return;

    setExecuting(true);

    // Update node to "running" state
    updateNodeStatus(targetId, "running");

    // Add to timeline
    setTimelineEntries((prev) => [
      ...prev,
      { nodeId: targetId, status: "running", executionTimeMs: 0 },
    ]);

    try {
      const res = await apiExecuteNode(node, targetDbs);

      // Update results map
      setExecutionResults((prev) => {
        const next = new Map(prev);
        next.set(targetId, {
          node_id: res.node_id,
          status: res.status,
          results: res.results,
          diff: res.diff,
          execution_time_ms: res.execution_time_ms,
        });
        return next;
      });

      // Update node status
      updateNodeStatus(targetId, res.status);

      // Update timeline
      setTimelineEntries((prev) =>
        prev.map((e) =>
          e.nodeId === targetId && e.status === "running"
            ? { ...e, status: res.status, executionTimeMs: res.execution_time_ms }
            : e,
        ),
      );
    } catch (err: unknown) {
      updateNodeStatus(targetId, "failed");
      setTimelineEntries((prev) =>
        prev.map((e) =>
          e.nodeId === targetId && e.status === "running"
            ? { ...e, status: "failed", executionTimeMs: 0 }
            : e,
        ),
      );
    } finally {
      setExecuting(false);
    }
  }, [selectedNodeId, graphModel, targetDbs]);

  // --- Execute all ---
  const handleExecuteAll = useCallback(async () => {
    if (!graphModel) return;
    setExecuting(true);

    try {
      const res = await executeAllNodes(graphModel, targetDbs, [...breakpoints]);
      sessionIdRef.current = res.session_id;

      // Update all results
      const newResults = new Map(executionResults);
      const newTimeline: { nodeId: string; status: string; executionTimeMs: number }[] = [];

      for (const r of res.results) {
        newResults.set(r.node_id, {
          node_id: r.node_id,
          status: r.status,
          results: r.results,
          diff: r.diff,
          execution_time_ms: r.execution_time_ms,
        });
        updateNodeStatus(r.node_id, r.status);
        newTimeline.push({
          nodeId: r.node_id,
          status: r.status,
          executionTimeMs: r.execution_time_ms,
        });
      }

      setExecutionResults(newResults);
      setTimelineEntries(newTimeline);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : "Execute all failed");
    } finally {
      setExecuting(false);
    }
  }, [graphModel, targetDbs, breakpoints, executionResults]);

  // --- Replay ---
  const handleReplay = useCallback(async () => {
    if (!sessionIdRef.current) return;

    try {
      const res = await getTrace(sessionIdRef.current);
      const trace = res.trace as Record<string, unknown>;

      // Reset all nodes to pending
      setFlowNodes((nds) =>
        nds.map((n) => ({
          ...n,
          data: { ...n.data, status: "pending" },
        })),
      );

      // Animate through events
      const events = (trace.events as Array<Record<string, unknown>>) || [];
      for (let i = 0; i < events.length; i++) {
        const evt = events[i];
        const nodeId = evt.node_id as string;
        const eventType = evt.event_type as string;

        await new Promise((resolve) => setTimeout(resolve, 300));

        if (eventType === "node_started") {
          updateNodeStatus(nodeId, "running");
        } else if (eventType === "node_finished") {
          updateNodeStatus(nodeId, "success");
        } else if (eventType === "node_failed") {
          updateNodeStatus(nodeId, "failed");
        }
      }
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : "Replay failed");
    }
  }, [setFlowNodes]);

  // --- Toggle breakpoint ---
  const handleToggleBreakpoint = useCallback((nodeId: string) => {
    setBreakpoints((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  // --- Update node status in React Flow ---
  const updateNodeStatus = useCallback(
    (nodeId: string, status: string) => {
      setFlowNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, status } } : n,
        ),
      );
    },
    [setFlowNodes],
  );

  // --- Node click → select for inspection ---
  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [],
  );

  // --- Timeline click → jump to node ---
  const handleTimelineClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  // --- Get selected node object ---
  const selectedNode = graphModel?.nodes.find((n) => n.id === selectedNodeId) || null;
  const selectedResult = selectedNodeId ? executionResults.get(selectedNodeId) || null : null;

  // --- Reset all ---
  const handleReset = useCallback(() => {
    setExecutionResults(new Map());
    setTimelineEntries([]);
    setFlowNodes((nds) =>
      nds.map((n) => ({ ...n, data: { ...n.data, status: "pending" } })),
    );
    setSelectedNodeId(null);
    setBreakpoints(new Set());
  }, [setFlowNodes]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 50px)", overflow: "hidden" }}>
      {/* Toolbar */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid #f0f0f0",
          background: "#fff",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          flexShrink: 0,
        }}
      >
        <Title level={5} style={{ margin: 0, whiteSpace: "nowrap" }}>
          <ApartmentOutlined style={{ marginRight: 6 }} />
          CFG Workbench
        </Title>

        <Button
          type="primary"
          icon={<CodeOutlined />}
          onClick={handleCompile}
          loading={compiling}
        >
          Compile
        </Button>

        <Divider type="vertical" />

        <Button
          icon={<PlayCircleOutlined />}
          onClick={() => handleExecuteNode()}
          loading={executing}
          disabled={!selectedNodeId}
        >
          Run Node
        </Button>

        <Button
          icon={<StepForwardOutlined />}
          onClick={handleExecuteAll}
          loading={executing}
          disabled={!graphModel}
        >
          Run All
        </Button>

        <Button
          icon={<HistoryOutlined />}
          onClick={handleReplay}
          disabled={!sessionIdRef.current}
        >
          Replay
        </Button>

        <Button icon={<ReloadOutlined />} onClick={handleReset}>
          Reset
        </Button>

        <Divider type="vertical" />

        <Space size={4}>
          <Text type="secondary" style={{ fontSize: 12 }}>Targets:</Text>
          <Select
            mode="multiple"
            value={targetDbs}
            onChange={setTargetDbs}
            style={{ minWidth: 260 }}
            size="small"
            options={DB_OPTIONS.map((o) => ({
              value: o.value,
              label: (
                <span>
                  <Tag color={o.color} style={{ marginRight: 4 }}>{o.value}</Tag>
                  {o.label}
                </span>
              ),
            }))}
          />
        </Space>

        {breakpoints.size > 0 && (
          <Tag icon={<BugOutlined />} color="orange">
            {breakpoints.size} breakpoint(s)
          </Tag>
        )}
      </div>

      {/* Error banner */}
      {loadError && (
        <Alert
          type="error"
          message={loadError}
          closable
          onClose={() => setLoadError(null)}
          style={{ margin: "0 16px", marginTop: 8, flexShrink: 0 }}
        />
      )}

      {/* Main 3-column layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Left sidebar — tabs */}
        <div
          style={{
            width: 300,
            flexShrink: 0,
            borderRight: "1px solid #f0f0f0",
            background: "#fafafa",
            overflow: "auto",
          }}
        >
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
            style={{ padding: "0 8px" }}
            items={[
              {
                key: "tsql",
                label: "T-SQL",
                children: (
                  <SqlEditor
                    value={tsql}
                    onChange={setTsql}
                    onExecute={handleCompile}
                  />
                ),
              },
              {
                key: "ir",
                label: "IR",
                children: (
                  <div style={{ padding: 8, fontSize: 12, fontFamily: "monospace" }}>
                    {graphModel ? (
                      <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                        {JSON.stringify(
                          {
                            procedure_name: graphModel.procedure_name,
                            nodes: graphModel.nodes.map((n) => ({
                              id: n.id,
                              type: n.type,
                              block: n.block_id,
                              ir_type: n.source.ir_node_type,
                            })),
                            edges: graphModel.edges.map((e) => ({
                              from: e.from_id,
                              to: e.to_id,
                              type: e.edge_type,
                              label: e.label,
                            })),
                          },
                          null,
                          2,
                        )}
                      </pre>
                    ) : (
                      <Empty description="Compile first" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    )}
                  </div>
                ),
              },
              {
                key: "cfg",
                label: "CFG",
                children: (
                  <div style={{ padding: 8 }}>
                    {graphModel ? (
                      <div>
                        <Paragraph type="secondary" style={{ fontSize: 12 }}>
                          {graphModel.nodes.length} nodes, {graphModel.edges.length} edges
                        </Paragraph>
                        {graphModel.nodes.map((n) => (
                          <div
                            key={n.id}
                            onClick={() => {
                              handleToggleBreakpoint(n.id);
                              setSelectedNodeId(n.id);
                            }}
                            style={{
                              padding: "4px 8px",
                              marginBottom: 4,
                              borderRadius: 4,
                              border: selectedNodeId === n.id ? "2px solid #1677ff" : "1px solid #e8e8e8",
                              background: breakpoints.has(n.id) ? "#fff7e6" : "#fff",
                              cursor: "pointer",
                              fontSize: 12,
                              fontFamily: "monospace",
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                            }}
                          >
                            <Tag
                              color={breakpoints.has(n.id) ? "orange" : "default"}
                              style={{ margin: 0, fontSize: 10, cursor: "pointer" }}
                              onClick={(e: React.MouseEvent) => {
                                e.stopPropagation();
                                handleToggleBreakpoint(n.id);
                              }}
                            >
                              {breakpoints.has(n.id) ? "●" : "○"}
                            </Tag>
                            <Text style={{ fontSize: 11 }}>{n.id}</Text>
                            <Tag style={{ margin: 0, fontSize: 10 }}>{n.type}</Tag>
                            <Text type="secondary" style={{ fontSize: 10, flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
                              {n.label.slice(0, 40)}
                            </Text>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <Empty description="Compile first" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    )}
                  </div>
                ),
              },
              {
                key: "trace",
                label: "Trace",
                children: (
                  <div style={{ padding: 8 }}>
                    {timelineEntries.length > 0 ? (
                      timelineEntries.map((e, i) => (
                        <div key={i} style={{ marginBottom: 4, fontSize: 12 }}>
                          <Tag
                            color={
                              e.status === "success" ? "green"
                              : e.status === "failed" ? "red"
                              : e.status === "running" ? "blue"
                              : "default"
                            }
                          >
                            {e.status}
                          </Tag>
                          <Text code>{e.nodeId}</Text>
                          {e.executionTimeMs > 0 && (
                            <Text type="secondary"> {e.executionTimeMs.toFixed(0)}ms</Text>
                          )}
                        </div>
                      ))
                    ) : (
                      <Empty description="No execution trace" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>

        {/* Center — CFG Graph Canvas */}
        <div style={{ flex: 1, position: "relative", background: "#f9f9f9" }}>
          <Spin spinning={compiling} tip="Compiling...">
            {flowNodes.length > 0 ? (
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={handleNodeClick}
                nodeTypes={cfgNodeTypes}
                edgeTypes={edgeTypes}
                fitView
                attributionPosition="bottom-left"
                connectionLineType={"smoothstep" as ConnectionLineType}
                minZoom={0.1}
                maxZoom={2}
                defaultEdgeOptions={{
                  type: "default",
                }}
              >
                <Background color="#e8e8e8" gap={20} />
                <Controls />
                <MiniMap
                  nodeStrokeWidth={3}
                  pannable
                  zoomable
                  style={{ borderRadius: 4 }}
                />
              </ReactFlow>
            ) : (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                }}
              >
                <Empty description="Enter T-SQL and click Compile to visualize the CFG" />
              </div>
            )}
          </Spin>
        </div>

        {/* Right — Execution Inspector */}
        <div
          style={{
            width: 400,
            flexShrink: 0,
            borderLeft: "1px solid #f0f0f0",
            background: "#fff",
            overflow: "auto",
          }}
        >
          <ExecutionInspector
            selectedNode={selectedNode}
            executionResult={selectedResult}
            targetDbs={targetDbs}
          />
        </div>
      </div>

      {/* Bottom — Execution Timeline */}
      <div
        style={{
          flexShrink: 0,
          borderTop: "1px solid #f0f0f0",
          background: "#fff",
        }}
      >
        <ExecutionTimeline
          entries={timelineEntries}
          onNodeClick={handleTimelineClick}
        />
      </div>
    </div>
  );
}
