/**
 * SQL Migration API client — communicates with the FastAPI backend.
 *
 * POST /api/sql/migrate/plan — migration feasibility assessment and plan.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Recommendation =
  | "SAFE_AUTO_MIGRATION"
  | "NEED_REVIEW"
  | "HIGH_RISK";

export type RiskLevel = "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type StepAction =
  | "rewrite_sql"
  | "validate_execution"
  | "manual_review"
  | "test_recommended"
  | "update_schema"
  | "verify_results";

export interface MigrationPlanRequest {
  sql: string;
  source_db: string;
  target_db: string;
}

export interface JoinChainRisk {
  chain: string[];
  risk_level: RiskLevel;
  description: string;
}

export interface ImpactAnalysis {
  tables: string[];
  critical_tables: string[];
  functions: string[];
  risk_hotspots: string[];
  join_chains: JoinChainRisk[];
  total_objects: number;
  high_risk_count: number;
  medium_risk_count: number;
}

export interface MigrationStep {
  step: number;
  action: StepAction;
  description: string;
  detail: string | null;
  automatic: boolean;
}

export interface MigrationPlan {
  steps: MigrationStep[];
  estimated_effort: string;
  total_steps: number;
  automatic_steps: number;
  manual_steps: number;
}

export interface MigrationPlanResponse {
  migration_feasible: boolean;
  risk_level: RiskLevel;
  confidence: number;
  recommendation: Recommendation;
  estimated_score: number;
  source_db: string;
  target_db: string;
  original_sql: string;
  rewritten_sql: string | null;
  impact: ImpactAnalysis;
  plan: MigrationPlan;
  warnings: string[];
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

export async function getMigrationPlan(
  request: MigrationPlanRequest,
): Promise<MigrationPlanResponse> {
  const res = await fetch(`${API_BASE}/api/sql/migrate/plan`, {
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
