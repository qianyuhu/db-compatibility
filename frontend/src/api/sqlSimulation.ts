/**
 * SQL Simulation API client — communicates with the FastAPI backend.
 *
 * POST /api/sql/migrate/simulate — migration execution simulation.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SimulationVerdict =
  | "SAFE_TO_EXECUTE"
  | "SAFE_TO_EXECUTE_WITH_MONITORING"
  | "NEEDS_MANUAL_REVIEW"
  | "HIGH_RISK_DO_NOT_EXECUTE";

export type RiskLevel = "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type FailureType =
  | "NULL_COMPARISON"
  | "PAGINATION_SHIFT"
  | "TIMEZONE_DRIFT"
  | "JOIN_MULTIPLICITY_CHANGE"
  | "FUNCTION_SEMANTIC_CHANGE"
  | "TYPE_CAST_ISSUE"
  | "COLLATION_MISMATCH"
  | "AGGREGATION_INSTABILITY";

export type DriftLevel = "STABLE" | "LOW_DRIFT" | "MODERATE_DRIFT" | "HIGH_DRIFT";

export interface SimulationRequest {
  sql: string;
  source_db: string;
  target_db: string;
  rewritten_sql?: string;
}

export interface FailurePoint {
  type: FailureType;
  location: string;
  severity: RiskLevel;
  description: string;
  mitigation: string | null;
}

export interface TableDrift {
  table: string;
  drift: DriftLevel;
  expected_variance: string;
  reason: string;
}

export interface RowLevelDiff {
  expected_variance: string;
  affected_tables: string[];
  table_drifts: TableDrift[];
  description: string;
}

export interface QueryBehavior {
  join_cardinality_shift: string | null;
  null_semantics_change: boolean;
  aggregation_stability: string;
  ordering_stability: string;
  type_coercion_changes: string[];
}

export interface SimulationResult {
  row_level_diff: RowLevelDiff;
  query_behavior: QueryBehavior;
  failure_points: FailurePoint[];
}

export interface EquivalenceDetail {
  ast_match: boolean;
  function_mapping_consistent: boolean;
  column_mapping_preserved: boolean;
  issues: string[];
}

export interface CardinalityEstimate {
  original_estimated_rows: number;
  rewritten_estimated_rows: number;
  variance_pct: number;
  join_graph_tables: string[];
  description: string;
}

export interface ExecutionModel {
  equivalence: EquivalenceDetail;
  cardinality: CardinalityEstimate;
}

export interface SimulationResponse {
  equivalence_score: number;
  risk_level: RiskLevel;
  simulation: SimulationResult;
  execution_model: ExecutionModel;
  recommendation: SimulationVerdict;
  source_db: string;
  target_db: string;
  original_sql: string;
  rewritten_sql: string | null;
  warnings: string[];
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

export async function simulateMigration(
  request: SimulationRequest,
): Promise<SimulationResponse> {
  const res = await fetch(`${API_BASE}/api/sql/migrate/simulate`, {
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
