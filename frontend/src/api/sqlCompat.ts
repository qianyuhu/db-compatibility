/**
 * SQL Compatibility Engine API client.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// =========================================================================
// Types
// =========================================================================

export interface CompatibilityAnalysisRequest {
  sql: string;
  source_db?: string;
  target_db?: string;
  execute?: boolean;
}

export interface FeatureDetection {
  category: string;
  count: number;
  details: string[];
  risk: string;
}

export interface ClassificationResult {
  categories: string[];
  features: FeatureDetection[];
  statement_type: string;
  complexity: string;
  total_features: number;
  risk_summary: Record<string, number>;
}

export interface DimensionScore {
  name: string;
  raw_score: number;
  max_score: number;
  weight: number;
  percentage: number;
  deductions: string[];
}

export interface CompatibilityScore {
  total_score: number;
  dimensions: DimensionScore[];
  risk_tags: string[];
  overall_risk: string;
  summary: string;
  supported_features: string[];
  unsupported_features: string[];
  rewritten_features: string[];
}

export interface CompatibilityAnalysisResponse {
  original_sql: string;
  source_db: string;
  target_db: string;
  rewritten_sql: string | null;
  classification: ClassificationResult | null;
  score: CompatibilityScore | null;
  execution_result: Record<string, unknown> | null;
  enhanced_diff: Record<string, unknown> | null;
  total_time_ms: number;
  warnings: string[];
}

// =========================================================================
// API Call
// =========================================================================

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function analyzeCompatibility(
  request: CompatibilityAnalysisRequest,
): Promise<CompatibilityAnalysisResponse> {
  return apiPost<CompatibilityAnalysisResponse>("/api/sql/compat/analyze", {
    sql: request.sql,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
    execute: request.execute ?? false,
  });
}
