/**
 * API client for the CFG Workbench endpoints.
 *
 * Endpoints:
 *   POST /api/cfg/compile       — Compile T-SQL → UIGraphModel
 *   POST /api/cfg/execute-node  — Execute a single CFG node
 *   POST /api/cfg/execute-all   — Execute all nodes
 *   GET  /api/cfg/trace/:id     — Get execution trace
 *   WS   /api/cfg/ws/:id        — WebSocket event stream
 */

/** Base URL for REST API calls. */
export const API_BASE =
  import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UINodeSource {
  ir_node_type: string;
  sql_text: string;
  condition: string;
  target: string;
  expression: string;
  procedure_name: string;
  variable_name: string;
}

export interface UINode {
  id: string;
  block_id: number;
  type: "sql" | "if" | "while" | "exec" | "assign" | "return" | "transaction" | "variable";
  label: string;
  source: UINodeSource;
  status: "pending" | "running" | "success" | "failed" | "skipped";
}

export interface UIEdge {
  id: string;
  from_id: string;
  to_id: string;
  edge_type: "sequential" | "true_branch" | "false_branch" | "loop_back";
  condition: string | null;
  label: string;
}

export interface UIGraphModel {
  procedure_name: string;
  nodes: UINode[];
  edges: UIEdge[];
  entry_node_id: string;
  exit_node_ids: string[];
  original_tsql: string;
}

export interface DBResult {
  db_type: string;
  success: boolean;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  execution_time_ms: number;
  error: string | null;
}

export interface ExecutionDiff {
  row_diff: number;
  column_diff: string[];
  value_diffs: Record<string, unknown>[];
  status: "MATCH" | "MISMATCH" | "ERROR";
}

export interface NodeExecutionResult {
  node_id: string;
  status: string;
  results: Record<string, DBResult>;
  diff: ExecutionDiff | null;
  execution_time_ms: number;
}

export interface CompileResponse {
  success: boolean;
  graph_model: UIGraphModel | null;
  errors: string[];
  procedure_name: string;
  token_count: number;
  block_count: number;
  ir_node_count: number;
}

export interface ExecuteNodeResponse {
  node_id: string;
  status: string;
  results: Record<string, DBResult>;
  diff: ExecutionDiff | null;
  execution_time_ms: number;
}

export interface ExecuteAllResponse {
  session_id: string;
  results: ExecuteNodeResponse[];
  trace: Record<string, unknown>;
}

export interface TraceResponse {
  session_id: string;
  trace: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** Compile a T-SQL stored procedure and return the CFG graph model. */
export async function compileSP(
  tsql: string,
  targetDbs: string[] = ["mssql", "kingbasees", "dm8"],
): Promise<CompileResponse> {
  const res = await fetch(`${API_BASE}/api/cfg/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tsql, target_dbs: targetDbs }),
  });
  if (!res.ok) {
    throw new Error(`Compile failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<CompileResponse>;
}

/** Execute a single CFG node against all target databases. */
export async function executeNode(
  node: UINode,
  targetDbs: string[] = ["mssql", "kingbasees", "dm8"],
): Promise<ExecuteNodeResponse> {
  const res = await fetch(`${API_BASE}/api/cfg/execute-node`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node, target_dbs: targetDbs }),
  });
  if (!res.ok) {
    throw new Error(`Execute node failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<ExecuteNodeResponse>;
}

/** Execute all nodes in a graph model sequentially. */
export async function executeAllNodes(
  graphModel: UIGraphModel,
  targetDbs: string[] = ["mssql", "kingbasees", "dm8"],
  breakpoints: string[] = [],
): Promise<ExecuteAllResponse> {
  const res = await fetch(`${API_BASE}/api/cfg/execute-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph_model: graphModel,
      target_dbs: targetDbs,
      breakpoints,
    }),
  });
  if (!res.ok) {
    throw new Error(`Execute all failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<ExecuteAllResponse>;
}

/** Get the execution trace for a session (for replay). */
export async function getTrace(sessionId: string): Promise<TraceResponse> {
  const res = await fetch(`${API_BASE}/api/cfg/trace/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Get trace failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<TraceResponse>;
}

/** Build the WebSocket URL for real-time execution events. */
export function getWsUrl(sessionId: string): string {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/api/cfg/ws/${sessionId}`;
}
