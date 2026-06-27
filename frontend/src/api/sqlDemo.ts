/**
 * SQL Demo API client — communicates with the FastAPI backend.
 */

const API_BASE = "http://localhost:8000";

export interface ExecuteRequest {
  db_type: "mssql" | "kingbasees" | "dm8";
  sql: string;
  params?: Record<string, unknown>;
}

export interface ExecuteResponse {
  success: boolean;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  db_type: string;
  execution_time_ms: number;
  error: string | null;
  suggestion: string | null;
}

export async function executeSql(
  request: ExecuteRequest,
): Promise<ExecuteResponse> {
  const res = await fetch(`${API_BASE}/api/sql/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    const text = await res.text();
    return {
      success: false,
      columns: [],
      rows: [],
      row_count: 0,
      db_type: request.db_type,
      execution_time_ms: 0,
      error: `HTTP ${res.status}: ${text}`,
      suggestion: "检查后端服务是否正常运行",
    };
  }

  return res.json();
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// =========================================================================
// SQL Compare API
// =========================================================================

export interface CompareRequest {
  sql: string;
  db_types: ("mssql" | "kingbasees" | "dm8")[];
}

export interface SingleResult {
  success: boolean;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  execution_time_ms: number;
  error: string | null;
  suggestion: string | null;
}

export interface ColumnDiff {
  db_type: string;
  columns: string[];
  missing_from_others: string[];
}

export interface ValueDiffItem {
  row_index: number;
  column: string;
  values: Record<string, unknown>;
}

export interface DiffResult {
  row_count_diff: boolean;
  row_count_details: Record<string, number>;
  column_diff: boolean;
  column_details: ColumnDiff[];
  value_diff: ValueDiffItem[];
}

export interface SqlRewrite {
  original: string;
  db_type: string;
  suggested: string;
  reason: string;
}

export interface CompareResponse {
  results: Record<string, SingleResult>;
  diff: DiffResult;
  rewrites: SqlRewrite[];
}

export async function compareSql(
  request: CompareRequest,
): Promise<CompareResponse> {
  const res = await fetch(`${API_BASE}/api/sql/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    return {
      results: {},
      diff: {
        row_count_diff: false,
        row_count_details: {},
        column_diff: false,
        column_details: [],
        value_diff: [],
      },
      rewrites: [],
    };
  }

  return res.json();
}
