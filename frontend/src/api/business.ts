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
  product_code: string;
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
    product_code: request.product_code,
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
  execution_time_ms: number;
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
