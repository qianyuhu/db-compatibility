/**
 * SQL Diagnostics API client — communicates with the FastAPI backend.
 *
 * POST /api/sql/diagnose — object-level cross-DB compatibility analysis.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RiskLevel = "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface DiagnoseRequest {
  sql: string;
  db_types: string[];
}

export interface TableDiagnostic {
  name: string;
  alias: string | null;
  risk: RiskLevel;
  issues: string[];
  db_compatibility: Record<string, boolean>;
}

export interface ColumnDiagnostic {
  name: string;
  column: string;
  table_ref: string | null;
  risk: RiskLevel;
  issues: string[];
  db_compatibility: Record<string, boolean>;
}

export interface FunctionDiagnostic {
  name: string;
  raw: string;
  risk: RiskLevel;
  issues: string[];
  db_compatibility: Record<string, boolean>;
  has_rewrite_rule: boolean;
}

export interface JoinDiagnostic {
  join_type: string;
  table: string;
  alias: string | null;
  condition: string | null;
  risk: RiskLevel;
  issues: string[];
  db_compatibility: Record<string, boolean>;
}

export interface RiskSummary {
  NONE: number;
  LOW: number;
  MEDIUM: number;
  HIGH: number;
  CRITICAL: number;
}

export interface DiagnoseSummary {
  total_objects: number;
  tables: RiskSummary;
  columns: RiskSummary;
  functions: RiskSummary;
  joins: RiskSummary;
}

export interface DiagnoseResponse {
  sql: string;
  db_types: string[];
  tables: TableDiagnostic[];
  columns: ColumnDiagnostic[];
  functions: FunctionDiagnostic[];
  joins: JoinDiagnostic[];
  summary: DiagnoseSummary;
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

export async function diagnoseSql(
  request: DiagnoseRequest,
): Promise<DiagnoseResponse> {
  const res = await fetch(`${API_BASE}/api/sql/diagnose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  return res.json();
}
