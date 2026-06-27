/**
 * SQL Score API client — communicates with POST /api/sql/score endpoint.
 */
import { API_BASE } from "./sqlDemo";

export interface ScoreRequest {
  sql: string;
  db_types: ("mssql" | "kingbasees" | "dm8")[];
}

export interface ScoreBreakdown {
  syntax: number;
  execution: number;
  result: number;
  risk: number;
}

export interface Finding {
  type: "syntax" | "execution" | "result" | "risk";
  db: string;
  issue: string;
  severity: "low" | "medium" | "high" | "critical";
  detail: string | null;
}

export interface ScoreResponse {
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  breakdown: ScoreBreakdown;
  findings: Finding[];
  suggestions: string[];
  db_count: number;
  execution_time_ms: number;
}

export async function scoreSql(request: ScoreRequest): Promise<ScoreResponse> {
  const res = await fetch(`${API_BASE}/api/sql/score`, {
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
