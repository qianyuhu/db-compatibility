/**
 * SQL Rewrite API client — communicates with POST /api/sql/rewrite endpoint.
 */
import { API_BASE } from "./sqlDemo";

export interface RewriteRequest {
  sql: string;
  source_db: "mssql" | "kingbasees" | "dm8";
  target_db: "mssql" | "kingbasees" | "dm8";
}

export interface AppliedRule {
  name: string;
  description: string;
  confidence: number;
}

export interface RewriteResponse {
  original_sql: string;
  rewritten_sql: string;
  source_db: string;
  target_db: string;
  rules_applied: AppliedRule[];
  confidence: number;
  warnings: string[];
}

export async function rewriteSql(
  request: RewriteRequest,
): Promise<RewriteResponse> {
  const res = await fetch(`${API_BASE}/api/sql/rewrite`, {
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
