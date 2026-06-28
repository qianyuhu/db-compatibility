/**
 * SQL Kernel API client — unified entry point for all SQL intelligence engines.
 *
 * POST /api/sql/kernel/analyze — run selected engines against a SQL statement.
 * All engines share a single SQLSemanticContext built once from the raw SQL.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EngineName =
  | "diagnostics"
  | "rewrite"
  | "score"
  | "migration"
  | "simulation";

export interface KernelRequest {
  sql: string;
  source_db: string;
  target_db: string;
  engines?: EngineName[];
  rewritten_sql?: string;
}

export interface KernelDecision {
  recommendation: "SAFE" | "REVIEW" | "BLOCK";
  confidence: number;
  migration_path: "DIRECT" | "AUTO_REWRITE" | "PARTIAL" | "MANUAL";
  primary_risks: string[];
  blocking_issues: string[];
  aggregated_severity: string;
  risk_counts: Record<string, number>;
  execution_strategy: string;
  explanation: string;
  score: number;
  rewrite_confidence: number;
  rewrite_rules_applied: number;
  simulation_verdict: string;
  source_db: string;
  target_db: string;
  original_sql: string;
  rewritten_sql: string | null;
  engines_consulted: string[];
  warnings: string[];
}

export interface KernelResponse {
  source_db: string;
  target_db: string;
  original_sql: string;
  rewritten_sql: string | null;
  diagnostics: Record<string, unknown> | null;
  rewrite: Record<string, unknown> | null;
  score: Record<string, unknown> | null;
  migration: Record<string, unknown> | null;
  simulation: Record<string, unknown> | null;
  decision: KernelDecision | null;
  engines_run: string[];
  total_time_ms: number;
  warnings: string[];
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

export async function analyzeKernel(
  request: KernelRequest,
): Promise<KernelResponse> {
  const res = await fetch(`${API_BASE}/api/sql/kernel/analyze`, {
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
