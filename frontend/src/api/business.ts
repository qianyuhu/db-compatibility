/**
 * Business API client — ERP 业务操作端点。
 */

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// =========================================================================
// Types
// =========================================================================

export interface SingleResult {
  success: boolean;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  db_type: string;
  execution_time_ms: number;
  error: string | null;
  suggestion: string | null;
}

export interface BusinessOperationResponse {
  operation: string;
  source_db: string;
  target_db: string;
  generated_sql_source: string;
  generated_sql_target: string | null;
  source_result: SingleResult;
  target_result: SingleResult;
  kernel_analysis: Record<string, unknown> | null;
  equal: boolean;
  diff_detail: { field: string; source: unknown; target: unknown }[];
  execution_time_ms: number;
  success: boolean;
}

export interface OrderItemInput {
  product_code: string;
  quantity: number;
  unit_price: number;
}

export interface OrderCreateRequest {
  customer_code: string;
  items: OrderItemInput[];
  notes?: string | null;
  source_db?: string;
  target_db?: string;
}

export interface StockQueryRequest {
  product_code?: string | null;
  warehouse_id?: string | null;
  stock_status?: "low" | "normal" | "all" | null;
  keyword?: string | null;
  source_db?: string;
  target_db?: string;
}

export interface StockAdjustRequest {
  product_code: string;
  delta: number;
  reason?: string;
  source_db?: string;
  target_db?: string;
}

export interface MigrationPhaseSummary {
  name: string;
  status: string;
  detail: Record<string, unknown>;
  error: string | null;
  elapsed_ms: number;
}

export interface MigrationPipelineResponse {
  source_db: string;
  target_db: string;
  phases: MigrationPhaseSummary[];
  overall_status: string;
  total_time_ms: number;
  warnings: string[];
}

// =========================================================================
// API Calls
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

export async function createOrder(
  request: OrderCreateRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/orders", {
    customer_code: request.customer_code,
    items: request.items,
    notes: request.notes || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function listCustomerOrders(
  customerId: number,
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/orders/list", {
    customer_id: customerId,
    source_db: sourceDb,
    target_db: targetDb,
  });
}

export async function queryStock(
  request: StockQueryRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/inventory/query", {
    product_code: request.product_code || null,
    warehouse_id: request.warehouse_id || null,
    stock_status: request.stock_status || null,
    keyword: request.keyword || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function adjustStock(
  request: StockAdjustRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/inventory/adjust", {
    product_code: request.product_code,
    delta: request.delta,
    reason: request.reason || "",
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function runMigration(
  sourceDb = "mssql",
  targetDb = "kingbasees",
  phases?: string[],
): Promise<MigrationPipelineResponse> {
  return apiPost<MigrationPipelineResponse>("/api/business/migrate/run", {
    source_db: sourceDb,
    target_db: targetDb,
    phases: phases || null,
  });
}

// =========================================================================
// Customer (Master Data)
// =========================================================================

export interface CustomerCreateRequest {
  code: string;
  name: string;
  contact?: string | null;
  phone?: string | null;
  email?: string | null;
  is_active?: boolean;
  source_db?: string;
  target_db?: string;
}

export interface CustomerListRequest {
  code?: string | null;
  name?: string | null;
  source_db?: string;
  target_db?: string;
}

export async function listCustomers(
  request: CustomerListRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/customers/list", {
    code: request.code || null,
    name: request.name || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function createCustomer(
  request: CustomerCreateRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/customers/create", {
    code: request.code,
    name: request.name,
    contact: request.contact || null,
    phone: request.phone || null,
    email: request.email || null,
    is_active: request.is_active ?? true,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

// =========================================================================
// Product (Master Data)
// =========================================================================

export interface ProductCreateRequest {
  code: string;
  name: string;
  price: number;
  is_active?: boolean;
  source_db?: string;
  target_db?: string;
}

export interface ProductListRequest {
  code?: string | null;
  name?: string | null;
  source_db?: string;
  target_db?: string;
}

export async function listProducts(
  request: ProductListRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/products/list", {
    code: request.code || null,
    name: request.name || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function createProduct(
  request: ProductCreateRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/products/create", {
    code: request.code,
    name: request.name,
    price: request.price,
    is_active: request.is_active ?? true,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

// =========================================================================
// Complex Report Queries
// =========================================================================

export interface SalesReportRequest {
  date_from?: string | null;
  date_to?: string | null;
  source_db?: string;
  target_db?: string;
}

export interface InventoryReportRequest {
  warehouse?: string | null;
  source_db?: string;
  target_db?: string;
}

export interface CustomerOrderReportRequest {
  customer_code?: string | null;
  source_db?: string;
  target_db?: string;
}

export async function runSalesReport(
  request: SalesReportRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/reports/sales", {
    date_from: request.date_from || null,
    date_to: request.date_to || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function runInventoryReport(
  request: InventoryReportRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/reports/inventory", {
    warehouse: request.warehouse || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

export async function runCustomerOrderReport(
  request: CustomerOrderReportRequest,
): Promise<BusinessOperationResponse> {
  return apiPost<BusinessOperationResponse>("/api/business/reports/customer-orders", {
    customer_code: request.customer_code || null,
    source_db: request.source_db || "mssql",
    target_db: request.target_db || "kingbasees",
  });
}

// =========================================================================
// Verification — 数据一致性验证
// =========================================================================

export interface TableVerificationResult {
  table_name: string;
  source_count: number | null;
  target_count: number | null;
  source_error: string | null;
  target_error: string | null;
  status: "PASS" | "FAIL" | "ERROR";
  source_time_ms: number;
  target_time_ms: number;
}

export interface VerificationResponse {
  source_db: string;
  target_db: string;
  tables: TableVerificationResult[];
  all_match: boolean;
  match_count: number;
  total_tables: number;
  verified: boolean;
  total_time_ms: number;
}

export interface SqlValidationResult {
  sql: string;
  source_result: SingleResult;
  target_result: SingleResult;
  equal: boolean;
  diff_detail: { field: string; source: unknown; target: unknown }[];
  enhanced_diff: ThreeLayerDiff | null;
  execution_time_ms: number;
}

// =========================================================================
// 3-Layer Diff Types
// =========================================================================

export interface Layer1Summary {
  status: "MATCH" | "DIFF" | "ERROR";
  row_count_match: boolean;
  column_type_match: boolean;
  data_match: boolean;
  execution_time_match: boolean;
  total_diffs: number;
  summary_text: string;
}

export interface Layer2FieldDiff {
  field_name: string;
  source_value: string;
  target_value: string;
  match: boolean;
  category: string;
}

export interface DiffExplanation {
  field_or_row: string;
  reason: string;
  possible_causes: string[];
  category: string;
  severity: "low" | "medium" | "high";
}

export interface Layer3RowDiff {
  row_index: number;
  field_name: string;
  source_value: unknown;
  target_value: unknown;
  explanation: DiffExplanation | null;
}

export interface ThreeLayerDiff {
  layer1: Layer1Summary;
  layer2: Layer2FieldDiff[];
  layer3: Layer3RowDiff[];
  explanations: DiffExplanation[];
}

export async function verifyMigration(
  sourceDb = "mssql",
  targetDb = "kingbasees",
  tables?: string[],
): Promise<VerificationResponse> {
  return apiPost<VerificationResponse>("/api/business/migrate/verify", {
    source_db: sourceDb,
    target_db: targetDb,
    tables: tables || null,
  });
}

export async function validateSql(
  sql: string,
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<SqlValidationResult> {
  return apiPost<SqlValidationResult>("/api/business/migrate/validate-sql", {
    sql,
    source_db: sourceDb,
    target_db: targetDb,
  });
}

export async function getAllowedTables(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/business/migrate/tables`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// =========================================================================
// Migration Sandbox Test Harness
// =========================================================================

export interface TestCaseMeta {
  id: string;
  name: string;
  category: string;
  description: string;
  expected_status: string;
  tags: string[];
  known_issues: string[];
}

export interface TestCaseResult {
  test_id: string;
  test_name: string;
  category: string;
  status: "PASS" | "FAIL" | "ERROR" | "SKIPPED";
  source_db: string;
  target_db: string;
  source_execution_time_ms: number;
  target_execution_time_ms: number;
  total_time_ms: number;
  row_count_match: boolean | null;
  data_match: boolean | null;
  column_match: boolean | null;
  diff_summary: string;
  error_message: string | null;
  known_issues: string[];
  diff_detail: { field: string; source: string; target: string; category: string }[];
  enhanced_diff: ThreeLayerDiff | null;
}

export interface CategorySummary {
  total: number;
  passed: number;
  failed: number;
  errors: number;
}

export interface SandboxReport {
  source_db: string;
  target_db: string;
  total_tests: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  success_rate: number;
  total_time_ms: number;
  results: TestCaseResult[];
  seed_results: Record<string, unknown>;
  summary_by_category: Record<string, CategorySummary>;
}

export interface SandboxRunResponse {
  source_db: string;
  target_db: string;
  seed_results: Record<string, {
    success: boolean;
    tables_seeded: Record<string, number>;
    error: string | null;
    elapsed_ms: number;
  }>;
  report: SandboxReport;
  total_time_ms: number;
}

export interface SandboxResetResponse {
  source_db: string;
  target_db: string;
  seed_results: Record<string, {
    success: boolean;
    tables_seeded: Record<string, number>;
    error: string | null;
    elapsed_ms: number;
  }>;
}

export interface SandboxCasesResponse {
  total: number;
  cases: TestCaseMeta[];
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function runSandboxTests(
  sourceDb = "mssql",
  targetDb = "kingbasees",
  filters?: { test_ids?: string; tags?: string; categories?: string },
): Promise<SandboxRunResponse> {
  const params = new URLSearchParams();
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  if (filters?.test_ids) params.set("test_ids", filters.test_ids);
  if (filters?.tags) params.set("tags", filters.tags);
  if (filters?.categories) params.set("categories", filters.categories);
  const res = await fetch(`${API_BASE}/api/migration/test/run?${params}`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function resetSandbox(
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<SandboxResetResponse> {
  const params = new URLSearchParams();
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  const res = await fetch(`${API_BASE}/api/migration/test/reset?${params}`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getSandboxReport(): Promise<{ available: boolean; report?: SandboxRunResponse }> {
  return apiGet("/api/migration/test/report");
}

export async function getSandboxCases(): Promise<SandboxCasesResponse> {
  return apiGet("/api/migration/test/cases");
}

// =========================================================================
// Migration Risk Intelligence
// =========================================================================

export interface DimensionRisk {
  name: string;
  raw_score: number;
  weight: number;
  weighted_score: number;
  deductions: string[];
  risk_level: string;
}

export interface RiskScore {
  total_score: number;
  risk_level: string;
  risk_tags: string[];
  summary: string;
  dimensions: DimensionRisk[];
}

export interface CoverageDimension {
  name: string;
  tested: number;
  total: number;
  percentage: number;
  covered_items: string[];
  missing_items: string[];
}

export interface CoverageReport {
  sql_coverage: CoverageDimension;
  api_coverage: CoverageDimension;
  orm_coverage: CoverageDimension;
  overall_coverage: number;
  critical_gaps: string[];
}

export interface ConfidenceScore {
  total_score: number;
  pass_rate_score: number;
  coverage_score: number;
  risk_penalty: number;
  level: string;
  recommendation: string;
  blockers: string[];
}

export interface CriticalIssue {
  test_id: string;
  test_name: string;
  category: string;
  severity: string;
  description: string;
  root_cause: string;
  possible_fixes: string[];
}

export interface RiskIntelligenceResponse {
  source?: string;
  risk_score: RiskScore | null;
  confidence_score: ConfidenceScore | null;
  coverage_report: CoverageReport | null;
  critical_issues: CriticalIssue[] | null;
  migration_readiness: string;
  top_risks: string[];
  total_time_ms?: number;
}

export interface PreflightRiskResponse {
  source_db: string;
  target_db: string;
  total_test_cases: number;
  estimated_sql_risk: number;
  rewrite_required_count: number;
  known_issue_count: number;
  coverage: CoverageReport;
  estimated_readiness: string;
}

export async function analyzeMigrationRisk(
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<RiskIntelligenceResponse> {
  const params = new URLSearchParams();
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  return apiGet(`/api/migration/test/risk/analyze?${params}`);
}

export async function preflightRisk(
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<PreflightRiskResponse> {
  const params = new URLSearchParams();
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  return apiGet(`/api/migration/test/risk/preflight?${params}`);
}

export async function getRiskCoverage(): Promise<CoverageReport> {
  return apiGet("/api/migration/test/risk/coverage");
}

// =========================================================================
// Migration Execution Loop — Continuous Fix Engine (Phase 3)
// =========================================================================

export interface FixStrategy {
  fix_type: string;
  issue_id: string;
  description: string;
  steps: string[];
  original_sql: string;
  rewritten_sql: string;
  rewrite_rules: string[];
  source_type: string;
  target_type: string;
  type_mapping_rule: string;
  estimated_success_probability: number;
  affected_test_count: number;
  is_reversible: boolean;
}

export interface FixResult {
  issue_id: string;
  fix_type: string;
  success: boolean;
  message: string;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  re_run_results: Array<{ test_id: string; test_name: string; status: string }>;
  elapsed_ms: number;
}

export interface MigrationIssue {
  issue_id: string;
  issue_type: string;  // SQL_REWRITE | SCHEMA_MAPPING | DATA_PRECISION | ORM_BEHAVIOR | API_CONTRACT
  severity: string;     // LOW | MEDIUM | HIGH | BLOCKER
  status: string;       // NEW → IDENTIFIED → FIXING → FIXED → VERIFIED → RESOLVED → REGRESSED
  test_id: string;
  test_name: string;
  source_db: string;
  target_db: string;
  table_name: string;
  field_name: string;
  description: string;
  root_cause: string;
  diff_detail: Record<string, unknown>;
  fix_strategy: FixStrategy | null;
  fix_attempts: number;
  affected_test_ids: string[];
  detected_at: string;
  fixed_at: string;
  verified_at: string;
}

export interface LoopIteration {
  iteration: number;
  phase: string;
  tests_run: number;
  tests_passed: number;
  tests_failed: number;
  issues_detected: number;
  issues_fixed: number;
  issues_verified: number;
  elapsed_ms: number;
  summary: string;
}

export interface ExecutionLoopState {
  source_db: string;
  target_db: string;
  phase: string;
  current_iteration: number;
  max_iterations: number;
  consecutive_clean_runs: number;
  is_stabilized: boolean;
  issue_stats: {
    total: number;
    open: number;
    fixed: number;
    verified: number;
    resolved: number;
    regressed: number;
  };
  total_fix_attempts: number;
  successful_fixes: number;
  failed_fixes: number;
  iterations: LoopIteration[];
  issues: MigrationIssue[];
  total_time_ms: number;
}

export interface ExecutionReport {
  executive_summary: {
    source_db: string;
    target_db: string;
    total_iterations: number;
    phase: string;
    recommendation: string;
  };
  test_summary: {
    total_tests: number;
    passed: number;
    partial_success: number;
    failed: number;
    errors: number;
    success_rate: number;
  };
  issue_summary: {
    total_issues: number;
    issues_resolved: number;
    issues_in_progress: number;
    issues_regressed: number;
  };
  fix_summary: {
    fixes_applied: number;
    fixes_succeeded: number;
    fixes_failed: number;
  };
  iterations: LoopIteration[];
  issues: MigrationIssue[];
  fix_results: FixResult[];
  remaining_blockers: string[];
  total_time_ms: number;
}

export interface StartLoopResponse {
  success: boolean;
  message: string;
  report?: ExecutionReport;
  state?: ExecutionLoopState;
}

export interface ExecStateResponse {
  available: boolean;
  message?: string;
  state?: ExecutionLoopState;
}

export interface SingleFixResponse {
  success: boolean;
  message: string;
  fix_result?: FixResult;
  issue?: MigrationIssue;
}

export interface ExecReportResponse {
  available: boolean;
  message?: string;
  report?: ExecutionReport;
}

export async function startExecutionLoop(
  sourceDb = "mssql",
  targetDb = "kingbasees",
  maxIterations = 10,
): Promise<StartLoopResponse> {
  const params = new URLSearchParams();
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  params.set("max_iterations", String(maxIterations));
  const res = await fetch(`${API_BASE}/api/migration/test/exec/start?${params}`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getExecutionState(): Promise<ExecStateResponse> {
  return apiGet("/api/migration/test/exec/state");
}

export async function applySingleFix(
  issueId: string,
  sourceDb = "mssql",
  targetDb = "kingbasees",
): Promise<SingleFixResponse> {
  const params = new URLSearchParams();
  params.set("issue_id", issueId);
  params.set("source_db", sourceDb);
  params.set("target_db", targetDb);
  const res = await fetch(`${API_BASE}/api/migration/test/exec/fix?${params}`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getExecutionReport(): Promise<ExecReportResponse> {
  return apiGet("/api/migration/test/exec/report");
}

export async function resetExecutionLoop(): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/migration/test/exec/reset`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}
