import { API_BASE as BASE } from "./config";
import { installUpsellInterceptor } from "./upsell";
import { installApprovalInterceptor } from "./approval";

// Screen every API response for HTTP 402 (capability_locked) → app-wide upsell modal,
// and HTTP 428 (approval_required) → app-wide approval modal. Idempotent, client-only;
// installed when the API layer first loads, so every fetch call site is covered.
installUpsellInterceptor();
installApprovalInterceptor();

export interface Connection {
  id: string;
  name: string;
  conn_type: string;
  dsn_preview: string;
  schema_name: string | null;
  builtin: boolean;
  /** Whether this connection is opted into Briefings (opt-out: true unless disabled). */
  briefings_enabled?: boolean;
}

export interface TestResult {
  ok: boolean;
  message: string;
}

export async function getConnections(): Promise<Connection[]> {
  const res = await fetch(`${BASE}/connections`);
  if (!res.ok) throw new Error("Failed to fetch connections");
  return res.json();
}

// ── Capabilities (commercial tier gating) ──────────────────────────────────
export interface Capabilities {
  tier: "free" | "pro" | "enterprise" | string;
  capabilities: string[];
}

/** The active tier + granted capabilities (defaults to enterprise = everything on). */
export async function getCapabilities(connectionId?: string): Promise<Capabilities> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${BASE}/capabilities${q}`);
  if (!res.ok) return { tier: "enterprise", capabilities: [] };  // fail-open: never block UI
  return res.json();
}

// ── Business / Industry Profile ─────────────────────────────────────────────
export interface NorthStarMetric {
  name: string;
  definition: string;
  maps_to: string;
  why_it_matters: string;
  unit_or_range: string;
  value_sql: string;
  chart_sql?: string;
}
export interface BusinessProfileResponse {
  available: boolean;
  profile?: {
    industry: string;
    business_model: string;
    summary: string;
    north_star_metrics: NorthStarMetric[];
    key_questions: string[];
    confidence: number;
    currency_code?: string;   // ISO 4217 the business reports in (drives €/£/$ figures)
  };
}

/** Display symbol for an ISO currency code (mirrors backend triage.currency_symbol). */
export function currencySymbol(code?: string | null): string {
  if (!code) return "$";
  const map: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥", INR: "₹" };
  return map[code.toUpperCase()] ?? `${code.toUpperCase()} `;
}
export async function getBusinessProfile(connectionId: string, schema?: string): Promise<BusinessProfileResponse> {
  const q = schema ? `&schema_name=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${BASE}/business-profile?connection_id=${encodeURIComponent(connectionId)}${q}`);
  if (!res.ok) return { available: false };
  return res.json();
}

// ── Workspaces ─────────────────────────────────────────────────────────────
// The top-level scope (Databricks-style): a named grouping of connections.
// Connections, Canvases and intelligence are all viewed through the lens of
// the currently-selected Workspace.
export interface Workspace {
  id: string;
  name: string;
  description: string;
  connection_ids: string[];
  is_default: boolean;
  settings_override?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${BASE}/workspaces`);
  if (!res.ok) throw new Error("Failed to fetch workspaces");
  return res.json();
}

export async function getWorkspace(id: string): Promise<Workspace> {
  const res = await fetch(`${BASE}/workspaces/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("Failed to fetch workspace");
  return res.json();
}

// ── Org / workspace settings (identity, localization, appearance) ──────────────
export interface OrgSettings {
  company_name: string;
  website: string;
  hq_location: string;
  industry: string;
  currency_code: string;
  timezone: string;
  date_format: string;
  fiscal_year_start_month: number;
  chart_palette: string;
}

export async function getOrgSettings(): Promise<OrgSettings> {
  const res = await fetch(`${BASE}/org-settings`);
  if (!res.ok) throw new Error("Failed to fetch org settings");
  return res.json();
}

export async function updateOrgSettings(settings: OrgSettings): Promise<OrgSettings> {
  const res = await fetch(`${BASE}/org-settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to update org settings");
  }
  return res.json();
}

/** Agent Context surface (P2): re-derive the working context after a scope edit. */
export interface RescopeResult {
  manifest: { tables: string[]; table_count: number; estimated_tokens: number; joins: { from: string; to: string; kind: string }[] };
  all_tables: string[];
  full_tokens: number;
  scoped_tokens: number;
  token_delta: number;
}

export async function rescopeContext(connectionId: string, keep: string[]): Promise<RescopeResult> {
  const res = await fetch(`${BASE}/investigations/context/rescope`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, keep }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to rescope context");
  }
  return res.json();
}

/** Editable plan gate (P3): resume a paused investigation, keeping only the chosen
 * sub-questions. Returns the SSE Response so the caller can stream the resumed run. */
export function resumeInvestigationPlan(invId: string, keepSubquestions: number[]): Promise<Response> {
  return fetch(`${BASE}/investigations/${encodeURIComponent(invId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: "plan approved", keep_subquestions: keepSubquestions }),
  });
}

/** Resume a clarify_pending pause with the metric reading the user chose (P4). */
export function resumeInvestigationClarify(invId: string, clarifyChoice: string): Promise<Response> {
  return fetch(`${BASE}/investigations/${encodeURIComponent(invId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: "clarify answered", clarify_choice: clarifyChoice }),
  });
}

/** Reject a pending plan — cancel the paused investigation outright. */
export async function cancelInvestigation(invId: string): Promise<void> {
  await fetch(`${BASE}/investigations/${encodeURIComponent(invId)}/cancel`, { method: "POST" });
}

/** Best-effort capture: the user drilled ("explore this fact") an overview card. Feeds the
 *  per-connection notability prior the next tour reads back (backend overview.drills).
 *  Fire-and-forget — a failed capture must never disrupt the drill it accompanies. */
export function recordOverviewDrill(
  connectionId: string,
  opts: { canvasId?: string; lens?: string; table?: string } = {},
): void {
  try {
    void fetch(`${BASE}/overview/drill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        connection_id: connectionId,
        canvas_id: opts.canvasId ?? null,
        lens: opts.lens ?? "",
        table: opts.table ?? "",
      }),
    }).catch(() => {});
  } catch {
    /* ignore — capture is best-effort */
  }
}

/** Action-approval audit + allowlist (P4, AI-FDE Pillar B). */
export interface ApprovalAuditEvent {
  seq?: number; at?: string; action: string; risk: string; decision: string;
  scope: string; actor: string; detail?: string;
}
export interface AllowlistEntry { action: string; scope: string; by?: string; at?: string; allowed?: boolean }

export async function getApprovalsAudit(limit = 100): Promise<ApprovalAuditEvent[]> {
  const res = await fetch(`${BASE}/approvals/audit?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch approvals audit");
  return res.json();
}
export async function getAllowlist(): Promise<AllowlistEntry[]> {
  const res = await fetch(`${BASE}/approvals/allowlist`);
  if (!res.ok) throw new Error("Failed to fetch allowlist");
  return res.json();
}
export async function revokeApproval(action: string, scope: string): Promise<void> {
  const res = await fetch(`${BASE}/approvals/revoke`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, scope }),
  });
  if (!res.ok) throw new Error("Failed to revoke approval");
}

/** Record a human verdict on an investigation finding (Bet 0 — ground-truth capture). */
export async function recordVerdict(input: {
  verdict: "accept" | "correct" | "reject";
  connectionId?: string;
  investigationId?: string;
  headline?: string;
  note?: string;
}): Promise<void> {
  const res = await fetch(`${BASE}/verify/verdict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      verdict: input.verdict,
      connection_id: input.connectionId ?? "",
      investigation_id: input.investigationId ?? "",
      headline: input.headline ?? "",
      note: input.note ?? "",
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to record verdict");
  }
}

export async function getEffectiveSettings(workspaceId?: string): Promise<OrgSettings> {
  const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${BASE}/org-settings/effective${q}`);
  if (!res.ok) throw new Error("Failed to fetch effective settings");
  return res.json();
}

export async function createWorkspace(
  name: string,
  connection_ids: string[] = [],
  description = "",
): Promise<Workspace> {
  const res = await fetch(`${BASE}/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, connection_ids, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to create workspace");
  }
  return res.json();
}

export async function updateWorkspace(
  id: string,
  patch: { name?: string; description?: string; connection_ids?: string[]; settings_override?: Record<string, unknown> },
): Promise<Workspace> {
  const res = await fetch(`${BASE}/workspaces/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to update workspace");
  }
  return res.json();
}

export async function deleteWorkspace(id: string): Promise<void> {
  const res = await fetch(`${BASE}/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to delete workspace");
  }
}

export async function addConnection(
  name: string,
  conn_type: string,
  dsn: string,
  schema_name?: string,
  meta?: Record<string, string>,
): Promise<{ id: string; message: string; test_result: string }> {
  const res = await fetch(`${BASE}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, conn_type, dsn: dsn || "", schema_name: schema_name || null, meta: meta || {} }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Failed to add connection");
  }
  return res.json();
}

export interface ConnectorTypeInfo {
  type: string;
  dsn_preview: string;
  category: string;
  fields: Array<{ key: string; label: string; placeholder: string; secret: boolean }>;
}

export async function getConnectorTypes(): Promise<ConnectorTypeInfo[]> {
  const res = await fetch(`${BASE}/connectors/types`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.types ?? [];
}

export async function createFederatedConnection(
  name: string,
  connectionIds: string[],
): Promise<{ id: string; message: string; test_result: string }> {
  const res = await fetch(`${BASE}/connections/federate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, connection_ids: connectionIds }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Federation failed");
  }
  return res.json();
}

export async function triggerSync(
  connId: string,
  incremental = true,
): Promise<{ message: string }> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/sync?incremental=${incremental}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error("Sync trigger failed");
  return res.json();
}

export async function getSyncStatus(connId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/sync-status`);
  if (!res.ok) return {};
  return res.json();
}

export interface ImportOptions {
  tableName?: string;
  schema?: string;
  columnTypes?: Record<string, string>;
}

export async function uploadFileToConnection(
  connId: string,
  file: File,
  opts: ImportOptions = {},
): Promise<{ table_name: string; schema?: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  if (opts.tableName) form.append("table_name", opts.tableName);
  if (opts.schema) form.append("schema", opts.schema);
  if (opts.columnTypes && Object.keys(opts.columnTypes).length > 0)
    form.append("column_types", JSON.stringify(opts.columnTypes));
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/files`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export interface BulkUploadResult {
  filename: string;
  table_name?: string;
  status: "ok" | "error";
  error?: string;
}

export interface BulkUploadResponse {
  schema: string;
  results: BulkUploadResult[];
  added: number;
  failed: number;
}

export async function bulkUploadFilesToConnection(
  connId: string,
  files: File[],
  schema: string,
): Promise<BulkUploadResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (schema) form.append("schema", schema);
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/files/bulk`,
    { method: "POST", body: form },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Bulk upload failed");
  }
  return res.json();
}

export interface ColumnAnalysis {
  name: string;
  detected_type: string;
  suggested_type: string | null;
}

export interface FileAnalysis {
  filename: string;
  columns: ColumnAnalysis[];
  preview: { columns: string[]; rows: (string | null)[][] };
  row_count: number;
  suggested_table_name: string;
}

export async function analyzeConnectionFile(
  connId: string,
  file: File,
): Promise<FileAnalysis> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/files/analyze`,
    { method: "POST", body: form },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Analyze failed");
  }
  return res.json();
}

export interface ConnectionFile {
  filename: string;
  table_name: string;
  schema: string;
  size_bytes: number;
  extension: string;
  column_types?: Record<string, string>;
}

export async function listConnectionFiles(connId: string): Promise<ConnectionFile[]> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/files`);
  if (!res.ok) return [];
  const data = await res.json().catch(() => ({ files: [] }));
  return data.files ?? [];
}

export async function deleteConnectionFile(
  connId: string,
  filename: string,
  schema = "main",
): Promise<void> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/files/${encodeURIComponent(filename)}?schema=${encodeURIComponent(schema)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error("Delete failed");
}

export async function listConnectionSchemas(connId: string): Promise<string[]> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/schemas`);
  if (!res.ok) return ["main"];
  const data = await res.json().catch(() => ({ schemas: ["main"] }));
  return data.schemas ?? ["main"];
}

export async function createConnectionSchema(connId: string, name: string): Promise<string> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/schemas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Schema create failed");
  }
  const data = await res.json();
  return data.schema;
}

/** Remove an entire schema (dataset) from a workspace connection — drops its tables,
 *  backing files, and derived profile/exploration. */
export async function deleteConnectionSchema(connId: string, schema: string): Promise<void> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/schemas/${encodeURIComponent(schema)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Schema remove failed");
  }
}

/** Remove a single table from a workspace connection — drops it + its backing file(s). */
export async function deleteConnectionTable(connId: string, table: string, schema = "main"): Promise<void> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}?schema=${encodeURIComponent(schema)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Table remove failed");
  }
}

export async function testConnection(id: string): Promise<TestResult> {
  const res = await fetch(`${BASE}/connections/${id}/test`, { method: "POST" });
  if (!res.ok) throw new Error("Test request failed");
  return res.json();
}

export async function deleteConnection(id: string): Promise<void> {
  await fetch(`${BASE}/connections/${id}`, { method: "DELETE" });
}

// ── Rich schema types ─────────────────────────────────────────────────────────

export interface SchemaColumn {
  name: string;
  type: string;
  is_fk: boolean;
  description?: string;
}

export interface SchemaTable {
  name: string;
  row_count: string | null;
  columns: SchemaColumn[];
}

export interface SchemaJoin {
  t1: string;
  c1: string;
  t2: string;
  c2: string;
  match: "exact" | "inferred";
}

export interface SchemaWarning {
  level: "warn" | "info";
  message: string;
}

export interface RichSchema {
  tables: SchemaTable[];
  joins: SchemaJoin[];
  isolated: string[];
  warnings: SchemaWarning[];
}

export async function getSchemaRich(id: string): Promise<RichSchema> {
  const res = await fetch(`${BASE}/connections/${id}/schema/rich`);
  if (!res.ok) throw new Error("Failed to fetch rich schema");
  return res.json();
}

export interface TableSample {
  columns: string[];
  rows: (string | null)[][];
  row_count?: number;
  /** Execution error — distinguishes "fetch failed" from a genuinely empty table. */
  error?: string | null;
}

export async function sampleTable(
  connId: string,
  table: string,
  limit = 100,
  schema?: string,
): Promise<TableSample> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (schema) params.set("schema", schema);
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/sample?${params}`,
  );
  if (!res.ok) throw new Error(`Failed to sample table "${table}"`);
  return res.json();
}

export interface TableColumn {
  name: string;
  type: string;
}

/** Reliable per-table column list — same lightweight path as the sample reader. */
export async function getTableColumns(
  connId: string,
  table: string,
  schema?: string,
): Promise<TableColumn[]> {
  const params = new URLSearchParams();
  if (schema) params.set("schema", schema);
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/columns?${params}`,
  );
  if (!res.ok) return [];
  const data = await res.json().catch(() => ({ columns: [] }));
  return data.columns ?? [];
}

export async function alterColumn(
  connId: string,
  table: string,
  column: string,
  newType: string,
  schema?: string,
): Promise<{ ok: boolean; applied?: boolean; override_only?: boolean; message?: string; error?: string }> {
  const params = new URLSearchParams();
  if (schema) params.set("schema", schema);
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/alter-column?${params}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ column, new_type: newType }),
    },
  );
  if (!res.ok) {
    const err = await res.text().catch(() => "Failed to alter column");
    throw new Error(err);
  }
  return res.json();
}

// ── Catalog tree ──────────────────────────────────────────────────────────────

export interface CatalogTableInfo {
  name: string;
  row_count: number | null;
}

export interface CatalogSchemaInfo {
  name: string;
  tables: CatalogTableInfo[];
}

export interface CatalogEntry {
  conn_id: string;
  name: string;
  conn_type: string;
  builtin: boolean;
  schemas: CatalogSchemaInfo[];
}

export interface CatalogSection {
  id: string;
  label: string;
  entries: CatalogEntry[];
}

export interface CatalogTree {
  sections: CatalogSection[];
}

export async function getCatalogTree(workspaceId?: string): Promise<CatalogTree> {
  const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${BASE}/catalog/tree${qs}`);
  if (!res.ok) throw new Error("Failed to fetch catalog tree");
  return res.json();
}

export async function getSchema(id: string): Promise<string> {
  const res = await fetch(`${BASE}/connections/${id}/schema`);
  if (!res.ok) throw new Error("Failed to fetch schema");
  const data = await res.json();
  return data.schema as string;
}

export async function refreshSchemaCache(id: string): Promise<void> {
  const res = await fetch(`${BASE}/connections/${id}/schema/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh schema cache");
}

export async function getSchemaDiagram(id: string): Promise<string> {
  const res = await fetch(`${BASE}/connections/${id}/schema/mermaid`);
  if (!res.ok) throw new Error("Failed to fetch schema diagram");
  const data = await res.json();
  return data.diagram as string;
}

// ── Metrics Catalog ───────────────────────────────────────────────────────────

export interface Metric {
  name: string;
  label: string;
  sql: string;
  tables: string[];
  dimensions: string[];
  filters: string[];
  unit: string | null;
  caveats: string | null;
  target_value: number | null;
  warning_threshold: number | null;
  critical_threshold: number | null;
  target_period: string | null;
  benchmark_source: string | null;
  // Governance fields (M21)
  owner: string | null;
  freshness_sla: string | null;
  freshness_check_sql: string | null;
  quality_tests: string[];
  lineage: string[];
  wrong_usage_examples: string[];
  approved_by: string | null;
  approved_at: string | null;
  // Governance lifecycle (B-8) — backend-owned; optional so editor forms needn't set them.
  status?: string;
  version?: number;
  proposed_by?: string | null;
  proposed_at?: string | null;
}

export interface MetricAuditEntry {
  metric: string;
  action: string;
  actor: string;
  from: string;
  to: string;
  version: number;
  at: string;
}

export interface QualityTestResult {
  test_sql: string;
  passed: boolean;
  error: string | null;
}

export interface MetricValidationResult {
  metric: string;
  passed: boolean;
  results: QualityTestResult[];
  message: string;
}

export interface MetricFreshnessResult {
  metric: string;
  latest_data_at: string | null;
  sla: string | null;
  ok: boolean;
  message: string;
}

export type HealthStatus = "green" | "yellow" | "red" | "unknown";

export interface ScorecardItem {
  name: string;
  label: string;
  current: number | null;
  target: number | null;
  variance: number | null;
  status: HealthStatus;
  unit: string | null;
  target_period: string | null;
  benchmark_source: string | null;
}

export async function getHealthScorecard(connId: string): Promise<ScorecardItem[]> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/health-scorecard`);
  if (!res.ok) return [];
  return res.json();
}

export async function getMetrics(): Promise<Metric[]> {
  const res = await fetch(`${BASE}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}

export async function createMetric(m: Omit<Metric, never>): Promise<Metric> {
  const res = await fetch(`${BASE}/metrics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(m),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Failed to create metric");
  }
  return res.json();
}

export async function updateMetric(name: string, m: Metric): Promise<Metric> {
  const res = await fetch(`${BASE}/metrics/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(m),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Failed to update metric");
  }
  return res.json();
}

export async function deleteMetric(name: string, sql?: string): Promise<void> {
  // Pass the formula to delete a single grain when a name has several definitions;
  // omit it to remove every entry sharing the name.
  const q = sql ? `?sql=${encodeURIComponent(sql)}` : "";
  await fetch(`${BASE}/metrics/${encodeURIComponent(name)}${q}`, { method: "DELETE" });
}

/** B-8 — drive a metric through its governance lifecycle (propose/approve/reject/deprecate). */
export async function transitionMetric(name: string, action: string, actor: string): Promise<{ metric: Metric; audit: MetricAuditEntry }> {
  const res = await fetch(`${BASE}/metrics/${encodeURIComponent(name)}/transition`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, actor }),
  });
  if (!res.ok) {
    const detail = await res.json().then(d => d?.detail).catch(() => null);
    throw new Error(detail || "Transition failed");
  }
  return res.json();
}

/** B-8 — the governance audit trail for a metric (newest first). */
export async function getMetricAudit(name: string): Promise<MetricAuditEntry[]> {
  const res = await fetch(`${BASE}/metrics/${encodeURIComponent(name)}/audit`);
  if (!res.ok) return [];
  return (await res.json()).audit ?? [];
}

export async function validateMetric(name: string, connId: string): Promise<MetricValidationResult> {
  const res = await fetch(
    `${BASE}/metrics/${encodeURIComponent(name)}/validate?conn_id=${encodeURIComponent(connId)}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Validation failed");
  }
  return res.json();
}

export async function getMetricFreshness(name: string, connId: string): Promise<MetricFreshnessResult> {
  const res = await fetch(
    `${BASE}/metrics/${encodeURIComponent(name)}/freshness?conn_id=${encodeURIComponent(connId)}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Freshness check failed");
  }
  return res.json();
}

// ── Ontology ──────────────────────────────────────────────────────────────────

export interface ComputedProperty {
  id: string;
  label: string;
  formula_sql: string;
  unit: string;
}

// OE-1: first-class typed property on an entity (mirrors Palantir Property)
export interface EntityProperty {
  name: string;
  display_name: string;
  data_type: string;
  semantic_type: string;
  description: string;
  is_primary_key: boolean;
  is_foreign_key: boolean;
  is_nullable: boolean;
  null_rate: number;
  null_meaning: string;          // from phase-3 exploration
  is_derived: boolean;
  value_interpretation: string;
  unit: string;
  sample_values: string[];
  // OE-4: distribution stats (numeric columns)
  distribution_shape: string;
  p25: number | null;
  p50: number | null;
  p75: number | null;
}

// OE-2: named composable filter over entity rows (mirrors Palantir Object Set)
export interface ObjectSet {
  id: string;
  display_name: string;
  description: string;
  filter_sql: string;
  is_default: boolean;
  source: "lifecycle" | "exploration" | "manual";
}

// OE-3: typed parameter extracted from {placeholder} tokens in sql_template
export interface ActionParameter {
  name: string;
  display_name: string;
  data_type: string;
  required: boolean;
  description: string;
  default_value: string | null;
}

// OE-6: shared structural shape implemented by multiple entity types
export interface OntologyInterface {
  id: string;
  display_name: string;
  description: string;
  property_patterns: string[];
  implementing_entities: string[];
}

export interface OntologyEntity {
  id: string;
  display_name: string;
  description: string;
  source_tables: string[];
  identity_key: string;
  grain_verified: boolean;
  domain: string | null;
  entity_type: "reference_data" | "business_object" | "event" | "standalone";
  has_lifecycle: boolean;
  lifecycle_column: string | null;
  lifecycle_states: string[];
  terminal_states: string[];
  active_filter: string | null;
  object_sets: Record<string, ObjectSet>;         // OE-2
  created_at_col: string | null;
  default_filters: string[];
  exclude_when: string[];
  properties: Record<string, EntityProperty>;     // OE-1
  computed_properties: ComputedProperty[];
  exploration_insights: string[];                 // OE-4
  implements: string[];                           // OE-6: interface ids
}

export interface ConnectionSettings {
  ontology_refresh_hours: number | null;
  briefings_enabled?: boolean | null;
}

export async function getConnectionSettings(id: string): Promise<ConnectionSettings> {
  const res = await fetch(`${BASE}/connections/${id}/settings`);
  if (!res.ok) return { ontology_refresh_hours: null };
  return res.json();
}

export async function updateConnectionSettings(
  id: string,
  settings: Partial<ConnectionSettings>,
): Promise<ConnectionSettings> {
  const res = await fetch(`${BASE}/connections/${id}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error("Failed to update connection settings");
  return res.json();
}

export async function rebuildOntology(connectionId: string, schemaName?: string): Promise<{ ok: boolean; generated_at: string; entities: number }> {
  const qs = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) qs.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/rebuild?${qs}`, { method: "POST" });
  if (!res.ok) throw new Error("Ontology rebuild failed");
  return res.json();
}

export interface OntologyRelationship {
  id: string;
  from_entity: string;
  to_entity: string;
  verb: string;
  cardinality: "1:1" | "1:N" | "N:1" | "N:N";
  join_sql: string;
  from_table: string;
  from_col: string;
  to_table: string;
  to_col: string;
  join_confidence: "exact" | "inferred" | "verified";
  nullable: boolean;
}

export interface OntologyAction {
  id: string;
  display_name: string;
  description: string;
  entity: string;
  action_type: "filter" | "compute" | "traverse" | "aggregate" | "validate";
  sql_template: string;
  parameters: ActionParameter[];                 // OE-3
  business_rules_enforced: string[];
  returns: string;
  source_table: string;
  origin?: "structural" | "learned" | "manual";  // learned skills carry these
  usage_count?: number;
}

export interface OntologyMetric {
  id: string;
  display_name: string;
  description: string;
  entity: string;
  formula_sql: string;
  grain: string;
  unit: string;
  tables: string[];
  known_divergent_calculations: string[];
}

export interface OntologyGraph {
  connection_id: string;
  schema_name: string;
  schema_fingerprint: string;
  generated_at: string;
  enriched: boolean;
  entities: Record<string, OntologyEntity>;
  relationships: Record<string, OntologyRelationship>;
  metrics: Record<string, OntologyMetric>;
  actions: Record<string, OntologyAction>;
  interfaces: Record<string, OntologyInterface>;  // OE-6
}

export async function getOntology(connectionId: string, schemaName?: string): Promise<OntologyGraph> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${BASE}/ontology?${q}`);
  if (!res.ok) throw new Error("Ontology not available for this connection");
  return res.json();
}

// ── Duplicate-entity detection + merge (Borrow 5) ─────────────────────────────

export interface DuplicateEntityRef { id: string; display_name: string; source_tables: string[] }
export interface DuplicateCluster { entities: DuplicateEntityRef[]; similarity: number }

export async function getDuplicateEntities(
  connectionId: string, schemaName?: string, threshold?: number,
): Promise<DuplicateCluster[]> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  if (threshold != null) q.set("threshold", String(threshold));
  const res = await fetch(`${BASE}/ontology/duplicate-entities?${q}`);
  if (!res.ok) throw new Error("Failed to load duplicate suggestions");
  return (await res.json()).clusters ?? [];
}

export async function mergeOntologyEntities(
  connectionId: string, mergeIds: string[], canonicalId: string, schemaName?: string,
): Promise<{ merged_into: string; removed: string[]; entity_count: number }> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/entities/merge?${q}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ merge_ids: mergeIds, canonical_id: canonicalId }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Merge failed");
  }
  return res.json();
}

export async function patchOntologyEntity(
  connectionId: string,
  entityId: string,
  overrides: Partial<Pick<OntologyEntity, "description" | "active_filter" | "default_filters" | "exclude_when" | "lifecycle_states" | "terminal_states">>,
): Promise<OntologyEntity> {
  const res = await fetch(
    `${BASE}/ontology/entities/${encodeURIComponent(entityId)}?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(overrides) },
  );
  if (!res.ok) throw new Error("Failed to update entity");
  return res.json();
}

export async function patchOntologyAction(
  connectionId: string,
  actionId: string,
  overrides: Partial<Pick<OntologyAction, "description" | "sql_template" | "business_rules_enforced" | "returns">>,
): Promise<OntologyAction> {
  const res = await fetch(
    `${BASE}/ontology/actions/${encodeURIComponent(actionId)}?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(overrides) },
  );
  if (!res.ok) throw new Error("Failed to update action");
  return res.json();
}

// ── Learned Skills (agent procedural memory) ──────────────────────────────────
// Skills ARE OntologyActions with origin='learned' + a usage_count. The backend
// crystallizes them from finished investigations and the ontology overlay re-enters
// them into the planner's action set; this surface lets a human review + manage them.

export interface AutonomyLevel {
  connection_id: string;
  level: number;                 // 0 manual · 1 assisted · 2 supervised · 3 autonomous
  label: string;
  signals?: Record<string, unknown>;
  reason?: string;
  usage_count?: number;          // present on the per-skill variant
}

export async function getLearnedSkills(connectionId: string, schemaName?: string): Promise<OntologyAction[]> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/skills?${q}`);
  if (!res.ok) throw new Error("Failed to load learned skills");
  return (await res.json()).skills ?? [];
}

// Crystallize a CANDIDATE skill from a finished investigation (not persisted — the UI
// confirms, then calls saveLearnedSkill). 422 when the run isn't skill-worthy.
export async function proposeLearnedSkill(
  invId: string, connectionId: string, schemaName?: string,
): Promise<OntologyAction> {
  const q = new URLSearchParams({ inv_id: invId, connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/skills/propose?${q}`, { method: "POST" });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Run is not skill-worthy");
  }
  return (await res.json()).candidate as OntologyAction;
}

export async function saveLearnedSkill(
  action: OntologyAction, connectionId: string, schemaName?: string,
): Promise<{ ok: boolean; schema_name: string; id: string }> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/skills?${q}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Skill rejected (SQL not read-only or failed dry-run)");
  }
  return res.json();
}

export async function activateLearnedSkill(
  actionId: string, connectionId: string, schemaName?: string,
): Promise<{ ok: boolean; usage_count: number; autonomy: AutonomyLevel }> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/skills/${encodeURIComponent(actionId)}/use?${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Learned skill not found");
  return res.json();
}

export async function deleteLearnedSkill(
  actionId: string, connectionId: string, schemaName?: string,
): Promise<void> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${BASE}/ontology/skills/${encodeURIComponent(actionId)}?${q}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete learned skill");
}

export async function getAutonomy(connectionId: string): Promise<AutonomyLevel> {
  const q = new URLSearchParams({ connection_id: connectionId });
  const res = await fetch(`${BASE}/ontology/autonomy?${q}`);
  if (!res.ok) return { connection_id: connectionId, level: 0, label: "manual" };
  return res.json();
}

// ── Proactive Schema Explorer ─────────────────────────────────────────────────

export interface ExplorationStatus {
  connection_id: string;
  phase: string;
  paused: boolean;
  tables_total: number;
  columns_total: number;
  joins_total: number;
  null_meanings_resolved: number;
  joins_verified: number;
  lifecycles_mapped: number;
  distributions_profiled: number;
  insights_found: number;
  queries_executed: number;
  facts_discovered: number;
  started_at: string | null;
  first_insight_at: string | null;        // B-6: time-to-first-insight milestone
  first_insight_seconds: number | null;   // elapsed start→first insight, the KPI
  completed_at: string | null;
  error: string | null;
  /** {schema: phase} for the aggregate of a multi-schema connection — lets the
   *  Activity strip say WHICH run each phase belongs to. */
  per_schema?: Record<string, string> | null;
}

export async function getExplorationStatus(connectionId: string): Promise<ExplorationStatus> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/status`);
  if (!res.ok) throw new Error("Exploration status not available");
  return res.json();
}

// ── Exploration findings ──────────────────────────────────────────────────────

export interface NullMeaning {
  meaning: string;
  business_rule: string | null;
  evidence_sql: string | null;
  null_rate?: number;
}

export interface JoinVerification {
  key: string;
  from_table: string;
  from_col: string;
  to_table: string;
  to_col: string;
  orphan_count: number;
  fk_distinct: number;
  pk_distinct: number;
  verified: boolean;
  cardinality: string;
}

export interface LifecycleMap {
  status_column: string;
  states: string[];
  terminal_states: string[];
  active_states: string[];
  transitions: { from: string; to: string; n: number }[];
}

export interface DistributionProfile {
  shape: string;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  pct_zero: number | null;
  min: number | null;
  max: number | null;
  mean: number | null;
  col_type?: string;
}

export interface ExplorationInsight {
  id: string;
  domain: string;
  angle: string;
  entities_involved: string[];
  dimensions: string[];
  measures: string[];
  finding: string;
  sql: string;
  confidence: number;
  novelty: number;
  generated_at: string;
  canvas_id?: string | null;
  promoted_to_org?: boolean;
  promotion_confidence?: number;
  /** Origin schema, set only on the "All schemas" aggregate — disambiguates findings whose
   *  per-schema ids collide (e.g. each schema's pinned questions start at pinned__0). */
  source_schema?: string;
  /** Briefing-triage annotations (stamped by the /domains endpoint): `impact` is the
   *  ranking score; `plausibility` flags a finding the trust gate distrusts. */
  impact?: number;
  plausibility?: "implausible" | "confound" | null;
}

/** Stable identity for a finding across the aggregate union, where bare `id`s collide. */
export function insightKey(ins: { id: string; source_schema?: string }): string {
  return ins.source_schema ? `${ins.source_schema}::${ins.id}` : ins.id;
}

export interface DomainInsights {
  insights: ExplorationInsight[];
  queries_used: number;
  budget_cap: number;
  angles_covered: string[];
}

export async function getDomainInsights(connectionId: string, schema?: string): Promise<Record<string, DomainInsights>> {
  const params = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/domains${params}`);
  if (!res.ok) throw new Error("Failed to fetch domain insights");
  return res.json();
}

export async function extendDomainBudget(connectionId: string, domain: string): Promise<{ ok: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connectionId)}/domains/${encodeURIComponent(domain)}/extend`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to extend domain budget");
  return res.json();
}

export async function getCanvasDomainInsights(canvasId: string): Promise<Record<string, DomainInsights>> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/domains`);
  if (!res.ok) throw new Error("Failed to fetch canvas domain insights");
  return res.json();
}

export async function extendCanvasDomainBudget(canvasId: string, domain: string): Promise<{ ok: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/domains/${encodeURIComponent(domain)}/extend`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to extend canvas domain budget");
  return res.json();
}

export async function promoteCanvasInsight(canvasId: string, insightId: string): Promise<{ promoted: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/insights/${encodeURIComponent(insightId)}/promote`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to promote insight");
  return res.json();
}

export async function promoteConnectionInsight(connectionId: string, insightId: string): Promise<{ promoted: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connectionId)}/insights/${encodeURIComponent(insightId)}/promote`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to promote insight");
  return res.json();
}

// ── Dashboard cards (briefing cockpit — user-authored KPI/chart/watch cards) ──

export interface DashboardCardRefresh {
  cadence: string;
  last_run: string;
  last_value: number | null;
  prev_value: number | null;
  history: number[];
}

export interface DashboardCard {
  id: string;
  connection_id: string;
  scope: string;
  scope_ref: string;
  source: string;
  kind: string;
  title: string;
  sql: string;
  query_ref: string | null;
  render: Record<string, unknown>;
  refresh: DashboardCardRefresh;
  thresholds: Record<string, unknown>;
  provenance: { insight_id: string; origin_finding_id: string; receipt_ref: string };
  links: string[];
  body: string;
  author: string;
  created_at: string;
  updated_at: string;
}

export interface CardRunResult {
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  caveats: string[];
  error: string | null;
  refresh: DashboardCardRefresh;
}

/** Pin a briefing finding as a dashboard card (Door 1). The backend re-runs the finding's
 *  SQL through the guard battery and refuses (throws) if it errors — a bad number is never
 *  pinned. */
export async function pinInsightToDashboard(
  connectionId: string,
  insightId: string,
  opts: { scope?: string; scopeRef?: string; schema?: string; kind?: string; title?: string } = {},
): Promise<{ card: DashboardCard; preview: { columns: string[]; rows: string[][]; row_count: number }; caveats: string[] }> {
  const res = await fetch(`${BASE}/cards/pin-insight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connection_id: connectionId,
      insight_id: insightId,
      scope: opts.scope ?? "connection",
      scope_ref: opts.scopeRef ?? connectionId,
      schema: opts.schema,
      kind: opts.kind ?? "kpi",
      title: opts.title,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to pin to dashboard"));
  }
  return res.json();
}

/** Pin a Query-Builder query as a dashboard card (Door 2). The backend re-runs the
 *  user-authored SQL through the guard battery and refuses (throws) if it errors or is
 *  BLOCKED — the same trust gate as Door 1, now on hand-written SQL. `render` is the opaque
 *  Chart spec the card draws with; `kind` (kpi/chart) is derived server-side from the shape. */
export async function pinQueryToDashboard(
  connectionId: string,
  sql: string,
  title: string,
  opts: { scope?: string; scopeRef?: string; schema?: string; render?: Record<string, unknown>; queryRef?: string } = {},
): Promise<{ card: DashboardCard; preview: { columns: string[]; rows: string[][]; row_count: number }; caveats: string[] }> {
  const res = await fetch(`${BASE}/cards/pin-query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connection_id: connectionId,
      sql,
      title,
      scope: opts.scope ?? "connection",
      scope_ref: opts.scopeRef ?? connectionId,
      schema: opts.schema,
      render: opts.render ?? {},
      query_ref: opts.queryRef,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to pin to dashboard"));
  }
  return res.json();
}

export async function listDashboardCards(
  opts: { connectionId?: string; scope?: string; scopeRef?: string } = {},
): Promise<DashboardCard[]> {
  const q = new URLSearchParams();
  if (opts.connectionId) q.set("connection_id", opts.connectionId);
  if (opts.scope) q.set("scope", opts.scope);
  if (opts.scopeRef) q.set("scope_ref", opts.scopeRef);
  const res = await fetch(`${BASE}/cards?${q.toString()}`);
  if (!res.ok) throw new Error("Failed to list dashboard cards");
  return res.json();
}

/** Recompute a card's value now (guard-on-read). Returns the current result + the rolling
 *  last/prev value for a delta. */
export async function runDashboardCard(cardId: string): Promise<CardRunResult> {
  const res = await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/run`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh dashboard card");
  return res.json();
}

export async function deleteDashboardCard(cardId: string): Promise<void> {
  await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}`, { method: "DELETE" });
}

/** Graduate a KPI/watch card to a scheduled Monitor (Slice 4 — watch → alert): its guarded SQL
 *  becomes a recurring threshold check and the thresholds are recorded back on the card. */
export async function graduateCard(
  cardId: string,
  thresholds: { warning_threshold?: number | null; critical_threshold?: number | null; threshold_direction?: string },
): Promise<{ card: DashboardCard }> {
  const res = await fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/graduate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(thresholds),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to set alert"));
  }
  return res.json();
}

/** Card↔finding `relates_to` edges for the argument-graph lens (Slice 4): links this
 *  connection's pinned cards to the given graph findings by deterministic SQL-signature overlap.
 *  Live (reflects the current cockpit). Returns card nodes + edges to merge onto the graph. */
export async function fetchCardRelations(
  connectionId: string,
  opts: { schema?: string; findingIds: string[] },
): Promise<{ nodes: ArgumentGraphNode[]; edges: ArgumentGraphEdge[] }> {
  const res = await fetch(`${BASE}/cards/relations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connection_id: connectionId,
      schema: opts.schema,
      finding_ids: opts.findingIds,
    }),
  });
  if (!res.ok) return { nodes: [], edges: [] };   // best-effort: relations never block the graph
  return res.json();
}

export async function dismissCanvasInsight(canvasId: string, insightId: string, reason: string): Promise<{ dismissed: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/insights/${encodeURIComponent(insightId)}/dismiss`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }
  );
  if (!res.ok) throw new Error("Failed to dismiss insight");
  return res.json();
}

export async function dismissConnectionInsight(connectionId: string, insightId: string, reason: string): Promise<{ dismissed: boolean }> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connectionId)}/insights/${encodeURIComponent(insightId)}/dismiss`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }
  );
  if (!res.ok) throw new Error("Failed to dismiss insight");
  return res.json();
}

export async function resumeCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/resume`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to resume canvas exploration");
  return res.json();
}

export async function stopCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop canvas exploration");
  return res.json();
}

export async function restartCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/restart`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to restart canvas exploration");
  return res.json();
}

export async function getCanvasExplorationStatus(canvasId: string): Promise<ExplorationStatus> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/status`);
  if (!res.ok) throw new Error("Failed to fetch canvas exploration status");
  return res.json();
}

export async function triggerCanvasDomainIntelligence(canvasId: string): Promise<{ ok: boolean; reason?: string }> {
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/trigger-intel`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger canvas domain intelligence");
  return res.json();
}

export async function getCanvasExplorationEpisodes(canvasId: string, phase = "", limit = 300): Promise<ExplorationEpisode[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (phase) params.set("phase", phase);
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/episodes?${params}`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export interface ExplorationFindings {
  connection_id: string;
  phase: string;
  null_meanings: Record<string, NullMeaning>;
  join_verifications: JoinVerification[];
  lifecycle_maps: Record<string, LifecycleMap>;
  distributions: Record<string, DistributionProfile>;
  insights: ExplorationInsight[];
}

export async function getExplorationFindings(connectionId: string, schema?: string): Promise<ExplorationFindings> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/findings${q}`);
  if (!res.ok) throw new Error("Failed to fetch exploration findings");
  return res.json();
}

// ── Exploration episodes (live reasoning trace) ───────────────────────────────

export interface ExplorationEpisode {
  episode_id: string;
  connection_id: string;
  phase: string;
  ts: number;
  think: string;
  sql: string;
  observation: string;
}

export async function stopExploration(connectionId: string): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop exploration");
  return res.json();
}

export async function resumeExploration(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/resume`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to resume exploration");
  return res.json();
}

export async function restartExploration(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/restart`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to restart exploration");
  return res.json();
}

export interface RetryQueryResult {
  ok: boolean;
  corrected_sql: string;
  explanation: string;
  rows: string[][];
  columns: string[];
  row_count?: number;
  error?: string;
}

export async function retryQuery(
  connectionId: string,
  sql: string,
  error: string,
  hint = "",
  domain = "",
): Promise<RetryQueryResult> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/retry-query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql, error, hint, domain }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Retry failed");
  }
  return res.json();
}

// ── Fix-and-save (persist a repaired errored query) ────────────────────────────

export interface FixSaveResult {
  ok: boolean;
  stored: boolean;
  corrected_sql: string;
  explanation?: string;
  rows?: string[][];
  columns?: string[];
  reason?: string;
  error?: string;
  insight?: { id: string; domain: string; angle: string; finding: string; unverified: boolean; verification_note: string };
}

export interface FixEpisodeInput {
  sql: string;
  error: string;
  think?: string;
  phase?: string;
}

export interface FixAllResult {
  summary: { total: number; fixed: number; saved: number; flagged: number; failed: number };
  results: Array<FixSaveResult & { sql: string }>;
}

/** Repair an errored episode and, on success, SAVE it (heal episode + store a finding
 *  through the same Phase-8 guards). Unlike retryQuery this persists. */
export async function fixEpisode(
  connectionId: string,
  ep: FixEpisodeInput,
  hint = "",
  canvasId = "",
): Promise<FixSaveResult> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/fix-episode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql: ep.sql, error: ep.error, think: ep.think ?? "", phase: ep.phase ?? "domain_intel", hint, canvas_id: canvasId }),
  });
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? "fix-and-save failed"); }
  return res.json();
}

/** Repair-and-save a batch — ONLY the episodes provided (the client passes the set
 *  currently visible under its filter). Never starts the explorer or generates new queries. */
export async function fixAll(
  connectionId: string,
  episodes: FixEpisodeInput[],
  hint = "",
  canvasId = "",
): Promise<FixAllResult> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/fix-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      episodes: episodes.map(e => ({ sql: e.sql, error: e.error, think: e.think ?? "", phase: e.phase ?? "domain_intel" })),
      hint, canvas_id: canvasId,
    }),
  });
  if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? "fix-all failed"); }
  return res.json();
}

export async function getExplorationEpisodes(
  connectionId: string,
  phase = "domain_intel",
  limit = 100,
): Promise<ExplorationEpisode[]> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connectionId)}/episodes?phase=${encodeURIComponent(phase)}&limit=${limit}`,
  );
  if (!res.ok) return [];
  return res.json();
}

// ── Dev stats ─────────────────────────────────────────────────────────────────

export interface DevStats {
  uptime_seconds: number;
  counters: Record<string, number>;
  timings: Record<string, { total_ms: number; count: number; avg_ms: number }>;
  derived: {
    rag_hit_rate: number | null;
    sql_correction_success_rate: number | null;
  };
}

export async function getDevStats(): Promise<DevStats> {
  const res = await fetch(`${BASE}/dev/stats`);
  if (!res.ok) throw new Error("Failed to fetch dev stats");
  return res.json();
}

export async function resetDevStats(): Promise<void> {
  await fetch(`${BASE}/dev/stats/reset`, { method: "POST" });
}

export async function getConnectionFreshness(connId: string): Promise<{ freshness: string | null; source: string | null }> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/freshness`);
  if (!res.ok) return { freshness: null, source: null };
  return res.json();
}

// ── Entity lifecycle counts ───────────────────────────────────────────────────

export interface LifecycleCount {
  state: string;
  count: number;
}

export async function getEntityLifecycleCounts(
  connectionId: string,
  entityId: string,
): Promise<LifecycleCount[]> {
  const res = await fetch(
    `${BASE}/ontology/entities/${encodeURIComponent(entityId)}/lifecycle-counts?connection_id=${encodeURIComponent(connectionId)}`,
  );
  if (!res.ok) return [];
  return res.json();
}

// ── Outcome Tracking ──────────────────────────────────────────────────────────

export type RecStatus = "accepted" | "rejected" | "implemented" | "verified" | "dismissed";

export interface RecOutcome {
  id: string;
  inv_id: string;
  rec_index: number;
  rec_text: string;
  status: RecStatus;
  metric_name: string | null;
  metric_before: number | null;
  metric_after: number | null;
  created_at: string;
  updated_at: string;
}

export async function logOutcome(
  invId: string,
  recIndex: number,
  recText: string,
  status: RecStatus,
  opts?: { metric_name?: string; metric_before?: number; metric_after?: number },
): Promise<RecOutcome> {
  const res = await fetch(
    `${BASE}/investigations/${encodeURIComponent(invId)}/recommendations/${recIndex}/outcome`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rec_text: recText, status, ...opts }),
    },
  );
  if (!res.ok) throw new Error("Failed to log outcome");
  return res.json();
}

export async function getInvestigationOutcomes(invId: string): Promise<RecOutcome[]> {
  const res = await fetch(`${BASE}/investigations/${encodeURIComponent(invId)}/outcomes`);
  if (!res.ok) return [];
  return res.json();
}

// ── Document Ingestion ────────────────────────────────────────────────────────

export interface DocumentEntry {
  doc_id: string;
  filename: string;
  title: string;
  chunk_count: number;
  uploaded_at: string;
}

export async function listDocuments(): Promise<DocumentEntry[]> {
  const res = await fetch(`${BASE}/documents`);
  if (!res.ok) return [];
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentEntry> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/documents/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${BASE}/documents/${encodeURIComponent(docId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete failed");
}

// ── Process Map ───────────────────────────────────────────────────────────────

export interface ProcessNode {
  state: string;
  count: number;
  is_terminal: boolean;
}

export interface ProcessEdge {
  from_state: string;
  to_state: string;
  count: number;
  rate: number;
}

export interface ProcessMap {
  entity_id: string;
  display_name: string;
  lifecycle_column: string;
  nodes: ProcessNode[];
  edges: ProcessEdge[];
  total_records: number;
  has_transitions: boolean;
}

export async function getProcessMap(connId: string, entityId: string): Promise<ProcessMap | null> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/process-map/${encodeURIComponent(entityId)}`,
  );
  if (!res.ok) return null;
  return res.json();
}

// ── Causal Graph ──────────────────────────────────────────────────────────────

export interface CausalEdge {
  id: string;
  from_signal: string;
  to_signal: string;
  from_entity: string | null;
  to_entity: string | null;
  weight: number;
  confirmed_by: string[];
  conn_id: string;
  created_at: string;
  updated_at: string;
}

export async function getCausalGraph(connId: string): Promise<CausalEdge[]> {
  const res = await fetch(
    `${BASE}/connections/${encodeURIComponent(connId)}/causal-graph`,
  );
  if (!res.ok) return [];
  return res.json();
}

// ── Canvas ────────────────────────────────────────────────────────────────────

export interface CanvasScope {
  connection_id: string;
  schema_name: string | null;
  tables: string[];
}

export interface Canvas {
  id: string;
  name: string;
  description: string;
  scopes: CanvasScope[];
  is_legacy: boolean;
  created_at: string;
  updated_at: string;
  /** Most recent investigation/chat timestamp for this canvas (null if never used). */
  last_activity?: string | null;
}

export async function getCanvases(workspaceId?: string): Promise<Canvas[]> {
  const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${BASE}/canvases${qs}`);
  if (!res.ok) throw new Error("Failed to fetch canvases");
  return res.json();
}

/** Extract a readable message from a FastAPI error body, whose `detail`
 *  may be a string OR an array of validation-error objects. */
function fastApiError(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map(d => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

export async function createCanvas(
  name: string,
  description: string,
  scopes: CanvasScope[],
): Promise<Canvas> {
  // The backend expects a single, flat scope on the request body
  // (connection_id / schema_name / tables), not a `scopes` array.
  const s = scopes[0] ?? { connection_id: "", schema_name: null, tables: [] };
  const res = await fetch(`${BASE}/canvases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      description,
      connection_id: s.connection_id,
      schema_name: s.schema_name,
      tables: s.tables,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to create canvas"));
  }
  return res.json();
}

export async function updateCanvas(
  id: string,
  patch: { name?: string; description?: string; scopes?: CanvasScope[] },
): Promise<Canvas> {
  // Backend UpdateCanvasRequest takes a flat { name, description, tables }.
  const body: { name?: string; description?: string; tables?: string[] } = {};
  if (patch.name !== undefined) body.name = patch.name;
  if (patch.description !== undefined) body.description = patch.description;
  if (patch.scopes !== undefined) body.tables = patch.scopes[0]?.tables ?? [];
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to update canvas"));
  }
  return res.json();
}

// ── Saved queries ─────────────────────────────────────────────────────────────
// Persist a Query Builder query (SQL + visual builder spec) so it survives reloads.

export interface SavedQuery {
  id: string;
  connection_id: string;
  name: string;
  sql: string;
  /** Opaque visual-builder state (primaryTable, joins, dims, measures, filters, orderBy, limit). */
  spec: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export async function listSavedQueries(connectionId?: string): Promise<SavedQuery[]> {
  const qs = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${BASE}/saved-queries${qs}`);
  if (!res.ok) throw new Error("Failed to fetch saved queries");
  return res.json();
}

export async function createSavedQuery(
  connectionId: string, name: string, sql: string, spec: Record<string, unknown>,
): Promise<SavedQuery> {
  const res = await fetch(`${BASE}/saved-queries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, name, sql, spec }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to save query"));
  }
  return res.json();
}

export async function updateSavedQuery(
  id: string, patch: { name?: string; sql?: string; spec?: Record<string, unknown> },
): Promise<SavedQuery> {
  const res = await fetch(`${BASE}/saved-queries/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Failed to update saved query"));
  }
  return res.json();
}

export async function deleteSavedQuery(id: string): Promise<void> {
  const res = await fetch(`${BASE}/saved-queries/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete saved query");
}

// ── Measure grains (additivity) ─────────────────────────────────────────────
// Per-unit vs per-line classification for a connection's measure columns — powers the
// Query Builder's grain-misuse warnings (SUM a per-unit price without ×quantity = under-count).

export interface MeasureGrains {
  grains: Record<string, "per_unit" | "per_line">;   // keyed by lower-case column name
  quantity_cols: string[];
}

export async function getMeasureGrains(connId: string): Promise<MeasureGrains> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/measure-grains`);
  if (!res.ok) throw new Error("Failed to fetch measure grains");
  return res.json();
}

/** Distinct non-null values for a column — powers the filter-value picker. */
export async function getColumnDistinct(
  connId: string, table: string, column: string, schema?: string, limit = 200,
): Promise<{ values: (string | null)[]; truncated: boolean }> {
  const qs = new URLSearchParams({ table, column, limit: String(limit) });
  if (schema) qs.set("schema", schema);
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connId)}/distinct?${qs.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch distinct values");
  return res.json();
}

/** LLM-inferred Canvas name + description from the scoped tables' schema. */
export async function suggestCanvasName(
  connectionId: string,
  tables: string[],
): Promise<{ name: string; description: string }> {
  const res = await fetch(`${BASE}/canvases/suggest-name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, tables }),
  });
  if (!res.ok) throw new Error(fastApiError(await res.json().catch(() => ({})), "Failed to suggest name"));
  return res.json();
}

/** Per-Canvas plain-English instructions (distinct from connection-level). */
export async function getCanvasInstructions(canvasId: string): Promise<string> {
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(canvasId)}/instructions`);
  if (!res.ok) return "";
  const d = await res.json().catch(() => ({ text: "" }));
  return d.text ?? "";
}

export async function putCanvasInstructions(canvasId: string, text: string): Promise<void> {
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(canvasId)}/instructions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(fastApiError(await res.json().catch(() => ({})), "Failed to save instructions"));
}

export async function deleteCanvas(id: string): Promise<void> {
  await fetch(`${BASE}/canvases/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getCanvasSchema(id: string): Promise<string> {
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(id)}/schema`);
  if (!res.ok) throw new Error("Failed to fetch canvas schema");
  const data = await res.json();
  return (data as { schema: string }).schema;
}

export interface CanvasHistoryItem {
  id: string;
  question: string;
  status: string;
  started_at: string;
  kind?: string;
  connection_id?: string;
}

export interface CanvasArtifact {
  id: string;
  canvas_id: string;
  kind: string;
  title: string;
  description: string;
  sql: string;
  question: string;
  created_at: string;
}

export async function getCanvasArtifacts(canvasId: string): Promise<CanvasArtifact[]> {
  const res = await fetch(BASE + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts");
  if (!res.ok) throw new Error("Failed to fetch artifacts");
  const data = await res.json();
  return data.artifacts ?? [];
}

export async function createCanvasArtifact(
  canvasId: string,
  payload: Omit<CanvasArtifact, "id" | "canvas_id" | "created_at">,
): Promise<CanvasArtifact> {
  const res = await fetch(BASE + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create artifact");
  return res.json();
}

export async function deleteCanvasArtifact(canvasId: string, artifactId: string): Promise<void> {
  const res = await fetch(BASE + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts/" + encodeURIComponent(artifactId), {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete artifact");
}

export async function getCanvasHistory(id: string, limit = 20): Promise<CanvasHistoryItem[]> {
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(id)}/history?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return (data as { investigations: CanvasHistoryItem[] }).investigations ?? [];
}

// ── Playbook (referenced items surfaced in chat/investigation) ────────────────
export interface PlaybookRef {
  id: string;
  recommendation: string;
  trigger_condition: string;
  status: string;
  tags: string[];
  historical_success_rate: number;
  source_kb_id: string | null;
}

export async function deletePlaybookEntry(id: string): Promise<void> {
  const res = await fetch(`${BASE}/playbook/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to remove playbook item");
}

/** Edit just the recommendation text of a playbook item (preserves the rest). */
export async function editPlaybookRecommendation(id: string, recommendation: string): Promise<void> {
  const cur = await fetch(`${BASE}/playbook/${encodeURIComponent(id)}`).then(r => (r.ok ? r.json() : null));
  if (!cur) throw new Error("Playbook item not found");
  const body = {
    trigger_metric: cur.trigger_metric, trigger_condition: cur.trigger_condition,
    trigger_operator: cur.trigger_operator ?? "any", trigger_value: cur.trigger_value ?? 0,
    recommendation, expected_impact: cur.expected_impact ?? "",
    typical_timeline: cur.typical_timeline ?? "", owner_role: cur.owner_role ?? "",
    tags: cur.tags ?? [], status: cur.status ?? "active", source_kb_id: cur.source_kb_id ?? null,
  };
  const res = await fetch(`${BASE}/playbook/${encodeURIComponent(id)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update playbook item");
}

/** Remove a single history line item (an investigation, or a whole chat session). */
export async function deleteInvestigation(id: string): Promise<void> {
  const res = await fetch(`${BASE}/investigations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to remove history item");
}

export async function getCanvasRecents(id: string, limit = 10): Promise<Array<{ question: string; status: string; created_at: string }>> {
  const res = await fetch(`${BASE}/canvases/${encodeURIComponent(id)}/recents?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return (data as { recents: Array<{ question: string; status: string; created_at: string }> }).recents ?? [];
}

// ── M3 / M11 — Direct Query Runner ───────────────────────────────────────────

export interface DirectQueryResult {
  columns: string[];
  rows: string[][];
  row_count: number;
  duration_ms: number;
  sql: string;
  cached: boolean;
  error: string | null;
  receipt_id?: string | null;   // WP-10: signed provenance → GET /receipt/{id}
}

export async function runDirectQuery(
  connId: string,
  sql: string,
  limit = 500,
  opts: { useCache?: boolean; useBulk?: boolean } = {},
): Promise<DirectQueryResult> {
  const res = await fetch(`${BASE}/query/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conn_id: connId,
      sql,
      limit,
      use_cache: opts.useCache ?? false,
      use_bulk: opts.useBulk ?? false,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Query failed");
  }
  return res.json();
}

// ── Semantic operators over a result's text columns (filter/extract/top_k/aggregate) ──

export interface SemanticField { name: string; description?: string }

export interface SemanticOpRequest {
  operator: "filter" | "extract" | "top_k" | "aggregate";
  column: string;
  predicate?: string;            // filter
  fields?: SemanticField[];      // extract
  criterion?: string;            // top_k
  k?: number;                    // top_k
  instruction?: string;          // aggregate
  out_column?: string;           // aggregate
  limit?: number;
  max_rows?: number;
  override_cap?: boolean;
}

export interface SemanticOpResult {
  columns: string[];
  rows: string[][];
  row_count: number;
  sql: string;
  error: string | null;
  operator: string;
  column: string;
  input_rows: number;
  output_rows: number;
  truncated: boolean;
  notes: string[];
  llm_calls: number;
}

export async function runSemanticOp(connId: string, sql: string, op: SemanticOpRequest): Promise<SemanticOpResult> {
  const res = await fetch(`${BASE}/query/semantic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conn_id: connId, sql, ...op }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Semantic step failed");
  }
  return res.json();
}

export interface BuildSqlMeasure {
  expr: string;
  alias: string;
}

export interface BuildSqlFilter {
  col: string;
  op: string;
  val: string;
}

export async function buildQuerySql(params: {
  table: string;
  dimensions: string[];
  measures: BuildSqlMeasure[];
  filters: BuildSqlFilter[];
  order_by: string;
  limit: number;
}): Promise<{ sql: string }> {
  const res = await fetch(`${BASE}/query/build-sql`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "SQL build failed");
  }
  return res.json();
}

// Query Builder Layer-3 — reverse-compile raw SQL into the builder's chips.
export interface DecompiledQuery {
  ok: boolean;
  reason?: string;
  primary_table?: string;
  joins?: { table: string; alias: string | null; side: string; on: string }[];
  dimensions?: { col: string; table: string; transform: string | null; alias: string | null }[];
  measures?: { agg: string; col: string; table: string; alias: string | null; customExpr: string }[];
  filters?: { col: string; table: string; op: string; val: string }[];
  unmapped_filters?: string[];
  order_by?: string;
  limit?: number;
  having?: string;
}

export async function decompileSql(sql: string, dialect = "duckdb"): Promise<DecompiledQuery> {
  const res = await fetch(`${BASE}/query/decompile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql, dialect }),
  });
  if (!res.ok) return { ok: false, reason: "Decompile request failed" };
  return res.json();
}

// On-demand governed validation of an answer's query (the guard battery, re-run live).
export interface QueryValidation {
  passed: boolean;
  issue_count: number;
  fanout_hits: string[];
  join_warnings: { table_a: string; col_a: string; table_b: string; col_b: string; overlap: number }[];
  filter_warnings: { table: string; column: string; literal: string; op: string; suggestion: string }[];
}

export async function validateQuery(connId: string, sql: string): Promise<QueryValidation> {
  const res = await fetch(`${BASE}/query/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conn_id: connId, sql }),
  });
  if (!res.ok) throw new Error("Validation failed");
  return res.json();
}

// Lightweight feedback/remember signal on a chat answer (journaled to the ledger).
export async function sendChatFeedback(connId: string, turnId: string, verdict: "helpful" | "unhelpful", note = ""): Promise<void> {
  await fetch(`${BASE}/chat/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conn_id: connId, turn_id: turnId, verdict, note }),
  }).catch(() => {});
}

// ── Evidence Ledger ────────────────────────────────────────────────────────────

export interface EvidenceClaim {
  id: string;
  investigation_id: string;
  hypothesis_id: string | null;
  claim_text: string;
  sql_source: string | null;
  metric_used: string | null;
  data_freshness: string | null;
  confidence: number;
  created_at: string;
  owner_feedback: "validated" | "disputed" | "needs_context" | null;
  feedback_note: string | null;
  downstream_recommendations: string[];
  outcome_status: "acted_on" | "superseded" | "archived" | null;
}

export async function getEvidenceClaims(invId: string): Promise<EvidenceClaim[]> {
  const res = await fetch(`${BASE}/investigations/${invId}/evidence`);
  if (!res.ok) return [];
  return res.json();
}

/** Recent evidence claims across a scope (connection, optionally a canvas), newest-first. */
export async function getRecentEvidenceClaims(
  connectionId: string,
  canvasId?: string,
  limit = 50,
): Promise<EvidenceClaim[]> {
  const params = new URLSearchParams({ connection_id: connectionId, limit: String(limit) });
  if (canvasId) params.set("canvas_id", canvasId);
  const res = await fetch(`${BASE}/investigations/evidence/recent?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function submitClaimFeedback(
  invId: string,
  claimId: string,
  feedback: "validated" | "disputed" | "needs_context",
  note?: string,
): Promise<EvidenceClaim> {
  const res = await fetch(`${BASE}/investigations/${invId}/evidence/${claimId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback, note }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Feedback submission failed");
  }
  return res.json();
}

// ── Monitors ──────────────────────────────────────────────────────────────────

export interface MonitorDef {
  id: string;
  conn_id: string;
  name: string;
  metric_name: string | null;
  custom_sql: string | null;
  reanchor_window: boolean;
  check_cron: string;
  alert_on: "threshold_cross" | "trend_reversal" | "anomaly" | "segment_drift" | "data_freshness" | "any_change";
  warning_threshold: number | null;
  critical_threshold: number | null;
  threshold_direction: "below" | "above";
  sigma_threshold: number;
  history_days: number;
  dimension_column: string | null;
  freshness_table: string | null;
  freshness_column: string | null;
  freshness_sla_hours: number;
  drift_p_threshold: number | null;
  grace_period_hours: number;
  notification_channel: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MonitorAlert {
  id: string;
  monitor_id: string;
  monitor_name: string;
  conn_id: string;
  metric_name: string | null;
  triggered_at: string;
  alert_on: string;
  severity: "warning" | "critical" | "info";
  current_value: number | null;
  previous_value: number | null;
  threshold: number | null;
  message: string;
  /** WP-1b (`monitors.guarded`) — deterministic correctness finding on the monitor's
   *  SQL (id-arithmetic / fan-out); the alert fired but its value may be mis-computed. */
  caveat?: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
}

export interface DigestSection {
  title: string;
  items: string[];
}

export interface DigestResult {
  conn_id: string;
  period: string;
  generated_at: string;
  sections: DigestSection[];
  alert_count: number;
  critical_count: number;
  markdown: string;
}

export async function getMonitors(connId?: string, workspaceId?: string): Promise<MonitorDef[]> {
  const qs = new URLSearchParams();
  if (connId) qs.set("conn_id", connId);
  if (workspaceId) qs.set("workspace_id", workspaceId);
  const q = qs.toString();
  const res = await fetch(`${BASE}/monitors${q ? `?${q}` : ""}`);
  if (!res.ok) throw new Error("Failed to fetch monitors");
  return res.json();
}

export async function createMonitor(data: Partial<MonitorDef> & { conn_id: string; name: string }): Promise<MonitorDef> {
  const res = await fetch(`${BASE}/monitors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create monitor");
  return res.json();
}

export async function updateMonitor(id: string, data: Partial<MonitorDef>): Promise<MonitorDef> {
  const res = await fetch(`${BASE}/monitors/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update monitor");
  return res.json();
}

export async function deleteMonitor(id: string): Promise<void> {
  const res = await fetch(`${BASE}/monitors/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete monitor");
}

export async function triggerMonitor(id: string): Promise<MonitorAlert | { fired: false }> {
  const res = await fetch(`${BASE}/monitors/${id}/trigger`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger monitor");
  return res.json();
}

export async function getMonitorAlerts(monitorId: string, limit = 50): Promise<MonitorAlert[]> {
  const res = await fetch(`${BASE}/monitors/${monitorId}/alerts?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function getAllAlerts(connId?: string, limit = 100, workspaceId?: string): Promise<MonitorAlert[]> {
  const qs = new URLSearchParams();
  if (connId) qs.set("conn_id", connId);
  qs.set("limit", String(limit));
  if (workspaceId) qs.set("workspace_id", workspaceId);
  const res = await fetch(`${BASE}/alerts?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function acknowledgeAlert(alertId: string): Promise<MonitorAlert> {
  const res = await fetch(`${BASE}/alerts/${alertId}/acknowledge`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to acknowledge alert");
  return res.json();
}

export async function getDigest(connId: string, period: "week" | "day" = "week"): Promise<DigestResult> {
  const res = await fetch(`${BASE}/monitors/digest?conn_id=${connId}&period=${period}`);
  if (!res.ok) throw new Error("Failed to fetch digest");
  return res.json();
}

// ── Action Hub triggers + finding share ─────────────────────────────────────────

export interface ActionTrigger {
  id: string;
  name: string;
  type: "webhook" | "slack" | "jira";
  url: string;
  headers: Record<string, string>;
  enabled: boolean;
  channel?: string | null;
  project?: string | null;
  issue_type?: string | null;
}

export async function getActionTriggers(): Promise<ActionTrigger[]> {
  const res = await fetch(`${BASE}/actions/triggers`);
  if (!res.ok) throw new Error("Failed to fetch action triggers");
  const data = await res.json();
  return data.triggers ?? [];
}

export interface SendFindingResult {
  status: "ok" | "failed" | "timeout";
  http_status: number | null;
  error: string | null;
}

/** Share a finding (Briefing/Hub insight) to a configured Action Hub trigger. */
export async function sendFindingToTrigger(
  triggerId: string,
  body: { text: string; metric_name?: string; headline?: string; source_id?: string },
): Promise<SendFindingResult> {
  const res = await fetch(`${BASE}/actions/triggers/${encodeURIComponent(triggerId)}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to share finding");
  return res.json();
}

// ── Scheduled Brief subscriptions ───────────────────────────────────────────────

export interface BriefSubscription {
  id: string;
  conn_id: string;
  name: string;
  period: "week" | "day";
  send_cron: string;
  trigger_id: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_sent_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export async function getBriefSubscriptions(connId?: string): Promise<BriefSubscription[]> {
  const qs = connId ? `?conn_id=${encodeURIComponent(connId)}` : "";
  const res = await fetch(`${BASE}/briefs/subscriptions${qs}`);
  if (!res.ok) throw new Error("Failed to fetch brief subscriptions");
  const data = await res.json();
  return data.subscriptions ?? [];
}

export async function createBriefSubscription(
  body: { conn_id: string; name: string; trigger_id: string; period?: "week" | "day"; send_cron?: string; enabled?: boolean },
): Promise<BriefSubscription> {
  const res = await fetch(`${BASE}/briefs/subscriptions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed to create brief subscription");
  return res.json();
}

export async function updateBriefSubscription(
  id: string,
  body: { conn_id: string; name: string; trigger_id: string; period?: "week" | "day"; send_cron?: string; enabled?: boolean },
): Promise<BriefSubscription> {
  const res = await fetch(`${BASE}/briefs/subscriptions/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update brief subscription");
  return res.json();
}

export async function deleteBriefSubscription(id: string): Promise<void> {
  const res = await fetch(`${BASE}/briefs/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete brief subscription");
}

export interface BriefDeliveryResult {
  status: "ok" | "failed" | "timeout";
  http_status: number | null;
  error: string | null;
  summary: string | null;
  markdown: string | null;
}

export async function testBriefSubscription(id: string): Promise<BriefDeliveryResult> {
  const res = await fetch(`${BASE}/briefs/subscriptions/${encodeURIComponent(id)}/test`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to test brief subscription");
  return res.json();
}

// ── Org Intelligence ──────────────────────────────────────────────────────────

export interface OrgInsight {
  id: string;
  insight_id: string;
  canvas_id: string;
  text: string;
  domain: string;
  angle: string;
  novelty: number;
  promoted_by: string;
  promoted_at: string;
}

export async function getOrgIntelligence(connectionId?: string, schema?: string): Promise<OrgInsight[]> {
  const qs = new URLSearchParams();
  if (connectionId) qs.set("connection_id", connectionId);
  if (schema) qs.set("schema", schema);
  const res = await fetch(`${BASE}/org-intelligence${qs.size ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error("Failed to fetch org intelligence");
  return res.json();
}

export async function deleteOrgInsight(id: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/org-intelligence/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete org insight");
  return res.json();
}

// ── Schema Shape (M23b) ───────────────────────────────────────────────────────

export interface TableProfileData {
  table: string;
  row_count: number;
  grain_column: string | null;
  grain_verified: boolean;
  primary_timestamp: string | null;
  date_range: [string, string] | null;
  freshness_lag_hours: number | null;
  computed_at: string;
}

export interface ColumnProfileData {
  table: string;
  column: string;
  dtype: string;
  semantic_type: string;
  null_rate: number;
  distinct_count: number;
  is_low_cardinality: boolean;
  value_range: [string | number, string | number] | null;
  top_values: string[] | null;
  is_fk: boolean;
}

export interface SchemaProfile {
  available: boolean;
  tables: TableProfileData[];
  columns: ColumnProfileData[];
}

export async function getSchemaProfile(connectionId: string): Promise<SchemaProfile> {
  const res = await fetch(`${BASE}/connections/${encodeURIComponent(connectionId)}/schema/profile`);
  if (!res.ok) throw new Error("Failed to fetch schema profile");
  return res.json();
}

// ── Pattern Library (M23c) ────────────────────────────────────────────────────

export interface Pattern {
  id: string;
  type: "angle" | "entity" | "convergence";
  title: string;
  description: string;
  domains: string[];
  evidence_count: number;
  novelty: number;
  entities: string[];
  angles?: string[];
  high_novelty_count?: number;
  example_findings: string[];
  computed_at: string;
}

export interface PatternsResponse {
  patterns: Pattern[];
  count: number;
}

export async function getPatterns(connectionId: string, refresh = false, schema?: string): Promise<PatternsResponse> {
  const q = new URLSearchParams();
  if (refresh) q.set("refresh", "true");
  if (schema) q.set("schema", schema);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const url = `${BASE}/exploration/${encodeURIComponent(connectionId)}/patterns${qs}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch patterns");
  return res.json();
}

/** Patterns scoped to a Canvas's curated tables (Hub scope consistency). */
export async function getCanvasPatterns(canvasId: string, refresh = false): Promise<PatternsResponse> {
  const qs = refresh ? "?refresh=true" : "";
  const res = await fetch(`${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/patterns${qs}`);
  if (!res.ok) throw new Error("Failed to fetch canvas patterns");
  return res.json();
}

// ── Briefing Narrative (M24b) ─────────────────────────────────────────────────

export interface BriefingCitation {
  ref: string;          // "1", "2", "3" — matches [N] in narrative text
  insight_id: string;
  domain: string;
  angle: string;
  finding: string;
}

/** A candidate finding the trust gate kept out of the brief — surfaced as an audit trail.
 *  severity 'implausible' = suppressed (impossible number); 'confound' = demoted (anti-causal). */
export interface HeldBackSignal {
  finding: string;
  domain: string;
  severity: "implausible" | "confound";
  reason: string;
}

/** The briefing's narrative layer made structural (Slice 3 — argument-graph lens). Nodes are the
 *  verdict + the impact-ranked drivers; edges are the explorer's OWN typed relationships
 *  (supports from the ranking; chain/tension/confound/concentration/share from composition;
 *  explains_why from drills). Built deterministically server-side; the frontend only renders it. */
export type ArgumentEdgeType =
  | "supports" | "chain" | "tension" | "confound" | "concentration" | "share" | "explains_why"
  | "relates_to"   // card ↔ finding (Slice 4 — wires the cockpit into the graph)
  | "related";     // finding ↔ finding, densify: a shared join key (structural, not validated)

export interface ArgumentGraphNode {
  id: string;
  kind: "verdict" | "finding" | "card";
  title: string;
  domain: string;
  angle: string;
  impact: number;
  plausibility: "implausible" | "confound" | null;
  has_sql: boolean;
  composition_type: string | null;
  is_driver: boolean;
  cited: boolean;
}

export interface ArgumentGraphEdge {
  source: string;
  target: string;
  type: ArgumentEdgeType;
  /** Optional per-edge label (e.g. the shared join key on a `related` edge). */
  label?: string;
}

export interface ArgumentGraph {
  nodes: ArgumentGraphNode[];
  edges: ArgumentGraphEdge[];
}

export interface BriefingNarrativeResponse {
  narrative: string;
  headline_theme: string;
  citations: BriefingCitation[];
  held_back?: HeldBackSignal[];
  /** The argument-graph projection of this brief (verdict + drivers + typed edges). */
  graph?: ArgumentGraph;
  currency_code?: string;
  generated_at: string | null;
  available: boolean;
}

export async function generateBriefingNarrative(
  connectionId: string,
  refresh = false,
  schema?: string,
  workspaceId?: string,
): Promise<BriefingNarrativeResponse> {
  const q = new URLSearchParams();
  if (refresh) q.set("refresh", "true");
  if (schema) q.set("schema", schema);
  if (workspaceId) q.set("workspace_id", workspaceId);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const url = `${BASE}/exploration/${encodeURIComponent(connectionId)}/briefing${qs}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate briefing narrative");
  return res.json();
}

/** Canvas-scoped briefing — reflects only the canvas's curated tables, not the whole
 *  connection. Mirrors generateBriefingNarrative but hits the canvas endpoint. */
export async function generateCanvasBriefingNarrative(
  canvasId: string,
  refresh = false,
  workspaceId?: string,
): Promise<BriefingNarrativeResponse> {
  const q = new URLSearchParams();
  if (refresh) q.set("refresh", "true");
  if (workspaceId) q.set("workspace_id", workspaceId);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const url = `${BASE}/exploration/canvas/${encodeURIComponent(canvasId)}/briefing${qs}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate canvas briefing narrative");
  return res.json();
}

// ── Report export (PDF / PowerPoint) ────────────────────────────────────────────

/** Download URL for a stored investigation's export. `narrate` prepends an
 *  LLM-authored executive summary (best-effort). */
export function investigationExportUrl(invId: string, fmt: "pdf" | "pptx", narrate = false): string {
  const q = new URLSearchParams({ format: fmt });
  if (narrate) q.set("narrate", "true");
  return `${BASE}/investigations/${encodeURIComponent(invId)}/export?${q.toString()}`;
}

/** Trigger a browser download of an investigation export. The endpoint replies
 *  with Content-Disposition: attachment, so the file saves without navigating. */
export function downloadInvestigationExport(invId: string, fmt: "pdf" | "pptx", narrate = false): void {
  const a = document.createElement("a");
  a.href = investigationExportUrl(invId, fmt, narrate);
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ── LLM inference provider config (Settings → Inference) ────────────────────────

/** The vended capability profile for one role's bound model (PLATFORM_ARCHITECTURE.md §5b). */
export interface LlmCapability {
  cache_mode: "explicit_breakpoint" | "auto_prefix" | "auto_prefix_unverified" | "none";
  tooling: "native_tools" | "none";
  structured_output: "native" | "instructor_emulated";
  token_accounting: "exact" | "estimated";
  max_context: number;
  privacy_class: "local" | "private_endpoint" | "public_api";  // governs what context may be sent
  cost: "per_token" | "flat" | "unknown";
}

export interface LlmConfig {
  backend: string;
  models: Record<string, string>;          // effective coder/narrator/fast
  base_urls: Record<string, string>;       // effective ollama/lmstudio
  keys_set: Record<string, boolean>;        // groq/together/anthropic — set or not (never the value)
  capabilities: Record<string, LlmCapability>;  // per-role vended profile (§5b)
  models_set: Record<string, string>;       // explicit overrides on disk
  base_urls_set: Record<string, string>;
  backends: string[];
  needs_key: string[];
  local_backends: string[];
  default_models: Record<string, Record<string, string>>;
}

export interface LlmConfigPatch {
  backend?: string;
  models?: Record<string, string>;
  base_urls?: Record<string, string>;
  keys?: Record<string, string>;
}

export async function getLlmConfig(): Promise<LlmConfig> {
  const res = await fetch(`${BASE}/llm/config`);
  if (!res.ok) throw new Error("Failed to load inference config");
  return res.json();
}

export async function setLlmConfig(patch: LlmConfigPatch): Promise<LlmConfig> {
  const res = await fetch(`${BASE}/llm/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Failed to save inference config");
  }
  return res.json();
}

export async function testLlmConfig(backend?: string, model?: string): Promise<{ ok: boolean; backend: string; model?: string; error?: string }> {
  const res = await fetch(`${BASE}/llm/config/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, model }),
  });
  return res.json();
}

export interface CacheProbeResult {
  ok: boolean;
  backend: string;
  model: string;
  verdict?: "reuse_active" | "no_reuse" | "inconclusive";
  ratio?: number;                 // warm/cold latency ratio
  cache_mode?: string | null;     // the measured mode persisted to the capability
  warm_median_ms?: number | null;
  cold_median_ms?: number | null;
  error?: string;
}

/** Measure prefix-cache reuse for the active binding and persist the verdict (§5b.3). */
export async function cacheProbe(role?: string, rounds?: number): Promise<CacheProbeResult> {
  const res = await fetch(`${BASE}/llm/config/cache-probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, rounds }),
  });
  return res.json();
}

// ── Explorer Control ────────────────────────────────────────────────────────────

export interface ExplorerStatus {
  connection_id: string;
  phase: string;
  paused: boolean;
  tables_total: number;
  columns_total: number;
  joins_total: number;
  null_meanings_resolved: number;
  joins_verified: number;
  lifecycles_mapped: number;
  distributions_profiled: number;
  insights_found: number;
  queries_executed: number;
  facts_discovered: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  /** True when Phase-8 domain intelligence was skipped because its prerequisite
   *  ontology could not be built — distinguishes "couldn't generate" from "never ran". */
  domain_intel_skipped?: boolean;
  domain_intel_note?: string | null;
  /** {schema: phase} for the 'All schemas' aggregate of a multi-schema connection. */
  per_schema?: Record<string, string> | null;
}

export async function getExplorerStatus(connectionId: string, schema?: string): Promise<ExplorerStatus> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/status${q}`);
  if (!res.ok) throw new Error("Failed to fetch explorer status");
  return res.json();
}

export async function startExplorer(connectionId: string, schema?: string): Promise<{ ok: boolean; reason?: string }> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/start${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to start explorer");
  return res.json();
}

export async function stopExplorer(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop explorer");
  return res.json();
}

export async function restartExplorer(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/restart`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to restart explorer");
  return res.json();
}

export async function resetExplorer(connectionId: string): Promise<{ ok: boolean; reset: boolean }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/reset`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to reset explorer");
  return res.json();
}

export async function triggerDomainIntelligence(connectionId: string): Promise<{ ok: boolean; reason?: string }> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/trigger-intel`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger domain intelligence");
  return res.json();
}

// ── Platform monitoring ───────────────────────────────────────────────────────

export interface PlatformMetrics {
  uptime_seconds: number;
  counters: Record<string, number>;
  timings: Record<string, { total_ms: number; count: number; avg_ms: number }>;
  derived: {
    rag_hit_rate: number | null;
    sql_correction_success_rate: number | null;
  };
}

export async function getPlatformMetrics(): Promise<PlatformMetrics> {
  const res = await fetch(`${BASE}/dev/stats`);
  if (!res.ok) throw new Error("Failed to fetch platform metrics");
  return res.json();
}

export interface AuditStats {
  total: number;
  blocked: number;
  allowed: number;
  pii_redactions: number;
  by_connection: Record<string, { total: number; blocked: number }>;
}

export async function getAuditStats(connectionId?: string): Promise<AuditStats> {
  const params = new URLSearchParams();
  if (connectionId) params.set("connection_id", connectionId);
  const res = await fetch(`${BASE}/security/audit/stats?${params}`);
  if (!res.ok) throw new Error("Failed to fetch audit stats");
  return res.json();
}

/** The explorer's own derivation of a finding, captured at emit time and carried
 *  inside the finding artifact's payload. Lets the Evidence drawer render the full
 *  trace (question → grounded cells → reasoning → structural ground) with zero
 *  recompute, instead of re-running a deep analysis to reconstruct it. */
export interface FindingDossier {
  dossier_version: number;
  question: string;
  sql: string;
  finding: string;
  rationale: string;
  result_cells: string;                                    // bounded, de-duped numeric evidence
  grounding: { grounded: boolean; checked: number; ungrounded: string[] };
  structural_ctx: {
    null_meanings: Record<string, { meaning?: string; business_rule?: string; evidence_sql?: string }>;
    joins: { from_table: string; from_col: string; to_table: string; to_col: string; orphan_count: number; verified: boolean; cardinality: string }[];
    lifecycles: Record<string, { status_column?: string; states?: string[]; terminal_states?: string[]; active_states?: string[] }>;
    distributions: Record<string, { shape?: string; p50?: number; pct_zero?: number }>;
  };
  generated_at: string;
  data_fingerprint: string | null;
  // Added post-emit: the briefing's "why it matters" framing (P5), and the last
  // live re-validation stamp/status (P4).
  narrative?: string;
  revalidated_at?: string;
  revalidation?: "confirmed" | "drifted" | "error";
}

/** Per-run compute a job/answer spent (R1). Honest signals only — tokens · calls ·
 *  queries · rows · time. No fabricated $ (see docs/MOTHERDUCK_LEARNINGS.md). */
export interface RunCost {
  llm_calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  query_count?: number;
  rows_returned?: number;
  llm_ms?: number;
  query_ms?: number;
}

// Per-run receipts stamped on the answer's Trust Receipt (Wave 1 · E4 learning, E3 activations).
export interface LearningReceiptPayload {
  readings_reused: number;
  corrections_applied: number;
  by_source: Record<string, number>;
  resolutions_crystallized: number;
  trusted_program_replayed: number;
}
export interface ActivationReceiptEntry { capability: string; reason: string; count: number }

export interface InsightReceipt {
  artifact: { id: string; kind: string; version: number; created_at: string; payload: Record<string, unknown> & { dossier?: FindingDossier; learning?: LearningReceiptPayload; activations?: ActivationReceiptEntry[] } };
  lineage: { relation: string; ref: string; detail: string | null }[];
  job: { id: string; kind: string; state: string; started_at: string | null; finished_at: string | null; metrics?: RunCost | null } | null;
  cost?: RunCost | null;
}

// ── The Fleet: kernel jobs as named agents (R2) ──────────────────────────────

export interface FleetAgent { agent: string; blurb: string; icon: string }

export interface FleetJob {
  id: string;
  kind: string;
  state: string;            // PENDING | RUNNING | SUCCEEDED | FAILED | CANCELLED | PAUSED
  conn_id: string | null;
  canvas_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  agent: FleetAgent;
  title: string;
  cost: RunCost | null;
  duration_ms: number | null;
}

export async function getJobs(params?: { state?: string; conn_id?: string; kind?: string; limit?: number }): Promise<FleetJob[]> {
  const q = new URLSearchParams();
  if (params?.state) q.set("state", params.state);
  if (params?.conn_id) q.set("conn_id", params.conn_id);
  if (params?.kind) q.set("kind", params.kind);
  if (params?.limit) q.set("limit", String(params.limit));
  const res = await fetch(`${BASE}/jobs${q.toString() ? `?${q}` : ""}`);
  if (!res.ok) return [];
  return res.json();
}

export async function getJobLogs(jobId: string): Promise<{ seq: number; at: string; kind: string; payload: unknown }[]> {
  const res = await fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/logs`);
  if (!res.ok) return [];
  return res.json();
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; cancelled: boolean }> {
  const res = await fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  if (!res.ok) return { job_id: jobId, cancelled: false };
  return res.json();
}

// ── Agent registry + governance: manage the fleet (Phase 0) ──────────────────

export interface AgentGovernance { enabled: boolean; token_budget: number | null; time_budget_s: number | null; model?: string | null }
export interface AgentSpend { runs: number; total_tokens: number; query_count: number }
export interface AgentRosterEntry {
  id: string; name: string; role: string; goal: string;
  lane: "background" | "interactive";
  job_kinds: string[]; tools: string[]; icon: string; reserved: boolean;
  default_budget: { token_budget: number | null; time_budget_s: number | null };
  governance: AgentGovernance;
  spend: AgentSpend;
}

export async function getAgents(workspaceId?: string): Promise<AgentRosterEntry[]> {
  const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${BASE}/agents${q}`);
  if (!res.ok) return [];
  return res.json();
}

export async function patchAgent(
  agentId: string,
  body: { enabled?: boolean; token_budget?: number; time_budget_s?: number; model?: string; workspace_id?: string },
): Promise<{ agent_id: string; governance: AgentGovernance } | null> {
  const res = await fetch(`${BASE}/agents/${encodeURIComponent(agentId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) return null;
  return res.json();
}

/** Live re-validation of a finding's dossier — re-runs the stored SQL and re-grounds
 *  the claim. `confirmed` = numbers still hold; `drifted` = a number moved. */
export interface RevalidateResult {
  status: "confirmed" | "drifted" | "error";
  grounded?: boolean;
  checked?: number;
  ungrounded?: string[];
  stored_cells?: string;
  fresh_cells?: string;
  cells_changed?: boolean;
  row_count?: number;
  error?: string;
  revalidated_at?: string;
}

export async function revalidateInsight(connId: string, insightId: string): Promise<RevalidateResult> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connId)}/insights/${encodeURIComponent(insightId)}/revalidate`,
    { method: "POST" },
  );
  if (!res.ok) return { status: "error", error: `HTTP ${res.status}` };
  return res.json();
}

/** K3 Trust Receipt — provenance for a finding (404 if it predates tracking). */
export async function getInsightReceipt(connId: string, insightId: string): Promise<InsightReceipt | null> {
  const res = await fetch(
    `${BASE}/exploration/${encodeURIComponent(connId)}/insights/${encodeURIComponent(insightId)}/receipt`,
  );
  if (!res.ok) return null;
  return res.json();
}

// ── "Show the receipt" — ground a specific briefing number against live result cells ──

export interface GroundedNumeral {
  text: string;
  value: number;
  enforce: boolean;
  grounded: boolean;
  matched_cell: number | null;
}

export interface GroundingReceipt {
  insight_id: string;
  finding: string;
  sql: string;
  numerals: GroundedNumeral[];
  columns: string[];
  sample_rows: string[][];
  error?: string;
}

/** Re-run a cited finding's query and ground a specific number ("show the receipt").
 *  `text` is the exact token clicked in the brief; omit to ground the whole finding.
 *  `insightIds` (all citations) lets the backend find the number's TRUE source, not just
 *  the nearest citation. */
export async function groundBriefingNumber(
  connId: string,
  insightId: string,
  opts: { text?: string; schema?: string; insightIds?: string[] } = {},
): Promise<GroundingReceipt> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connId)}/briefing/ground`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      insight_id: insightId,
      insight_ids: opts.insightIds ?? [],
      text: opts.text ?? "",
      schema: opts.schema ?? null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Grounding failed");
  }
  return res.json();
}

/** K3-wide Trust Receipt for a chat or ADA answer (404 if it predates receipts). */
export async function getAnswerReceipt(kind: "chat" | "ada", connId: string, id: string): Promise<InsightReceipt | null> {
  const res = await fetch(
    `${BASE}/${kind}/${encodeURIComponent(connId)}/${encodeURIComponent(id)}/receipt`,
  );
  if (!res.ok) return null;
  return res.json();
}

// ── WP-10: the unified public Trust Receipt (GET /receipt/{id}) ─────────────────
export interface PublicReceiptGuard { name: string; fired: boolean; action: string; caveat: string }
export interface PublicReceiptSql { sql: string; label: string; duration_ms: number | null; row_count: number | null }
export interface PublicReceipt {
  receipt_version: number;
  id: string;
  created_at: string | null;
  mode: string;                         // quick | deep | builder | explore | monitor | brief
  question: string;
  headline: string;
  connection: { id: string | null; name: string | null; dialect: string | null };
  executed_sql: PublicReceiptSql[];
  input_tables: string[];
  guards: PublicReceiptGuard[];          // each names a guard that FIRED, with its action
  caveats: string[];
  metrics: {
    used: string[];
    drifted: { metric: string; detail: string | null }[];
    available: string[];
    proposed: { metric: string; detail: string | null }[];
  };
  confidence: { level: string | null; capped_by: string | null };
  data_trust: { window: string | null; coverage_notes: string | null };
  model: { role: string; id: string | null };
  cost: Record<string, number | string> | null;
  signature: string;                     // HMAC — server-issued proof
}

/** Resolve any answer's receipt id into the one signed public contract. 404 → null. */
export async function getPublicReceipt(receiptId: string): Promise<PublicReceipt | null> {
  const res = await fetch(`${BASE}/receipt/${encodeURIComponent(receiptId)}`);
  if (!res.ok) return null;
  return res.json();
}

// ── Metastore: Volumes (the governed unstructured tier) ─────────────────────────

export interface MetastoreVolume {
  id: string;
  org_id: string;
  catalog_id: string;
  name: string;
  full_name: string;
  created_at: string;
  updated_at: string;
}

export interface MetastoreVolumeObject {
  id: string;
  org_id: string;
  volume_id: string;
  path: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  extracted_text: string | null;
  created_at: string;
}

export async function listVolumes(catalogId: string): Promise<MetastoreVolume[]> {
  const res = await fetch(`${BASE}/metastore/catalogs/${encodeURIComponent(catalogId)}/volumes`);
  if (!res.ok) throw new Error("Failed to list volumes");
  return (await res.json()).volumes ?? [];
}

export async function createVolume(catalogId: string, name: string): Promise<MetastoreVolume> {
  const res = await fetch(`${BASE}/metastore/catalogs/${encodeURIComponent(catalogId)}/volumes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Failed to create volume"); }
  return res.json();
}

export async function listVolumeObjects(volumeId: string): Promise<MetastoreVolumeObject[]> {
  const res = await fetch(`${BASE}/metastore/volumes/${encodeURIComponent(volumeId)}/objects`);
  if (!res.ok) throw new Error("Failed to list objects");
  return (await res.json()).objects ?? [];
}

export async function uploadVolumeObject(volumeId: string, file: File): Promise<MetastoreVolumeObject> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/metastore/volumes/${encodeURIComponent(volumeId)}/objects`, { method: "POST", body: form });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Upload failed"); }
  return res.json();
}

export function volumeObjectContentUrl(volumeId: string, objectId: string): string {
  return `${BASE}/metastore/volumes/${encodeURIComponent(volumeId)}/objects/${encodeURIComponent(objectId)}/content`;
}

export async function deleteVolumeObject(volumeId: string, objectId: string): Promise<void> {
  const res = await fetch(`${BASE}/metastore/volumes/${encodeURIComponent(volumeId)}/objects/${encodeURIComponent(objectId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete failed");
}

// ── Metastore: Grants (explicit catalog access for a workspace) ─────────────────

export async function listWorkspaceGrants(workspaceId: string): Promise<string[]> {
  const res = await fetch(`${BASE}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants`);
  if (!res.ok) throw new Error("Failed to list grants");
  return (await res.json()).catalogs ?? [];
}

export async function grantWorkspaceCatalog(workspaceId: string, catalogId: string): Promise<string[]> {
  const res = await fetch(`${BASE}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalog_id: catalogId }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Grant failed"); }
  return (await res.json()).catalogs ?? [];
}

export async function revokeWorkspaceCatalog(workspaceId: string, catalogId: string): Promise<string[]> {
  const res = await fetch(`${BASE}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants/${encodeURIComponent(catalogId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Revoke failed");
  return (await res.json()).catalogs ?? [];
}

// ── Business Glossary (institutional knowledge: table/column descriptions) ───────

export interface GlossaryColumn { description?: string; values?: string; caveats?: string; }
export interface GlossaryTable {
  description?: string;
  grain?: string;
  joins?: string[];
  columns?: Record<string, GlossaryColumn>;
}
export interface Glossary { tables?: Record<string, GlossaryTable>; }

export async function getGlossary(): Promise<Glossary> {
  const res = await fetch(`${BASE}/glossary`);
  if (!res.ok) return { tables: {} };
  return res.json();
}

/** Partial table-level glossary patch. Every field the agent reads at query time:
 *  description + grain + joins all flow into the schema context via apply_glossary(). */
export async function updateTableGlossary(
  table: string,
  patch: { description?: string; grain?: string; joins?: string[] },
): Promise<void> {
  const res = await fetch(`${BASE}/glossary/${encodeURIComponent(table)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to save table comment");
}

/** Partial column-level glossary patch (description + known values + caveats). */
export async function updateColumnGlossary(
  table: string,
  column: string,
  patch: { description?: string; values?: string; caveats?: string },
): Promise<void> {
  const res = await fetch(`${BASE}/glossary/${encodeURIComponent(table)}/${encodeURIComponent(column)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to save column comment");
}

// ── Playbook (Governed Dives): version history ──────────────────────────────────

export interface PlaybookVersion {
  entry_id: string;
  version: number;
  receipt: string;
  saved_at: string;
  content: Record<string, unknown>;
}

export async function getPlaybookVersions(entryId: string): Promise<PlaybookVersion[]> {
  const res = await fetch(`${BASE}/playbook/${encodeURIComponent(entryId)}/versions`);
  if (!res.ok) return [];
  return res.json();
}

// ── Post-processing transforms (PoP / share / rolling / cumulative) ─────────────

export type PostprocOp = "pop" | "contribution" | "rolling" | "cumulative";

export async function applyPostproc(
  columns: string[], rows: unknown[][], op: PostprocOp, valueCol: string,
  window = 3, agg: "mean" | "sum" | "min" | "max" = "mean",
): Promise<{ columns: string[]; rows: unknown[][] }> {
  const res = await fetch(`${BASE}/query/postproc`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ columns, rows, op, value_col: valueCol, window, agg }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Transform failed"); }
  return res.json();
}

// ── System feature flags (runtime override > env) ───────────────────────────────

export type CapabilityState = "on" | "off" | "auto";
export interface SystemFlag {
  value: boolean;
  source: "runtime" | "env";
  env_var: string;
  label: string;
  description: string;
  // Capabilities Auto-mode (Wave 1 · E3) — present on every flag:
  state?: CapabilityState;          // effective tri-state
  override?: boolean | null;        // the runtime override, or null when following env/Auto-mode
  auto_eligible?: boolean;          // a self-gating guard the master Auto-mode can run
  trigger?: string;                 // (auto-eligible only) the deterministic trigger, in words
}

export async function getSystemFlags(): Promise<Record<string, SystemFlag>> {
  const res = await fetch(`${BASE}/system/flags`);
  if (!res.ok) return {};
  return res.json();
}

export async function setSystemFlag(name: string, value: boolean): Promise<SystemFlag | null> {
  const res = await fetch(`${BASE}/system/flags/${encodeURIComponent(name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
  });
  if (!res.ok) return null;
  return res.json();
}
/** Set a capability's tri-state — "auto" clears the override so it follows the Auto-mode master. */
export async function setCapabilityState(name: string, state: CapabilityState): Promise<SystemFlag | null> {
  const res = await fetch(`${BASE}/system/flags/${encodeURIComponent(name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state }),
  });
  if (!res.ok) return null;
  return res.json();
}

// ── RBAC (roles & permissions) ──────────────────────────────────────────────

export interface MyAccess {
  user_id: string | null;
  org_id: string;
  roles: string[];
  permissions: string[];
}

export interface RoleInfo {
  name: string;
  description: string;
  permissions: string[];
}

export interface RoleAssignment {
  org_id: string;
  user_id: string;
  role: string;
  created_at: string;
  updated_at: string;
}

/** The caller's effective identity, roles and permissions (for gating admin UI). */
export async function getMyAccess(): Promise<MyAccess | null> {
  const res = await fetch(`${BASE}/rbac/me`);
  if (!res.ok) return null;
  return res.json();
}

/** The built-in role catalogue + the permissions each grants. */
export async function getRoleCatalogue(): Promise<RoleInfo[]> {
  const res = await fetch(`${BASE}/rbac/roles`);
  if (!res.ok) return [];
  return res.json();
}

/** The org's role roster. Returns null when the caller can't manage roles (403). */
export async function getRoleAssignments(): Promise<RoleAssignment[] | null> {
  const res = await fetch(`${BASE}/rbac/assignments`);
  if (res.status === 403) return null;
  if (!res.ok) return [];
  return res.json();
}

export async function assignRole(userId: string, role: string): Promise<RoleAssignment | null> {
  const res = await fetch(`${BASE}/rbac/assignments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, role }),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function revokeRole(userId: string, role: string): Promise<boolean> {
  const q = `user_id=${encodeURIComponent(userId)}&role=${encodeURIComponent(role)}`;
  const res = await fetch(`${BASE}/rbac/assignments?${q}`, { method: "DELETE" });
  if (!res.ok) return false;
  const data = await res.json();
  return !!data.removed;
}

// ── Specialist packs (Domain Expertise Packs) ───────────────────────────────────

export interface PackSummary {
  id: string;
  name?: string;
  status?: string;
  version?: number;
  domains?: string[];
  metrics?: number;
  roles?: number;
  evals?: number;
  ok: boolean;
  errors?: string[];
  warnings?: string[];
  error?: string;
}

export async function getPacks(): Promise<{ enabled: boolean; packs: PackSummary[] }> {
  const res = await fetch(`${BASE}/packs`);
  if (!res.ok) return { enabled: false, packs: [] };
  return res.json();
}

export interface BindingCandidateDTO {
  role: string; table?: string | null; column?: string | null;
  value?: string | null; confidence: number; evidence: string; bound: boolean;
}

export async function proposePackBindings(
  packId: string, connectionId: string, schema?: string, businessModel = "",
): Promise<{ fully_groundable: boolean; groundable_roles: number; total: number; proposals: Record<string, BindingCandidateDTO> }> {
  const res = await fetch(`${BASE}/packs/${encodeURIComponent(packId)}/propose-bindings`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, schema, business_model: businessModel }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "propose failed");
  return res.json();
}

export async function bindPack(
  packId: string, connectionId: string, bindings: Record<string, unknown>, schema?: string, version = 1,
): Promise<{ verified: boolean; missing?: string[]; dry_run_errors?: string[] }> {
  const res = await fetch(`${BASE}/packs/${encodeURIComponent(packId)}/bind`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, bindings, schema, version }),
  });
  if (!res.ok) throw new Error("bind failed");
  return res.json();
}

export async function evaluatePack(
  packId: string, connectionId: string, schema?: string,
): Promise<{ can_activate: boolean; pass_rate: number | null; reasons: string[];
            results: { question: string; passed: boolean; detail: string }[];
            deployed: boolean; verified: boolean }> {
  const res = await fetch(`${BASE}/packs/${encodeURIComponent(packId)}/evaluate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, schema }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "evaluate failed");
  return res.json();
}

export interface PackDeltaDTO {
  id: number; kind: string; target: string; content: string; confidence: number; status: string;
}

export async function getPackDeltas(packId: string, status = "proposed"): Promise<PackDeltaDTO[]> {
  const res = await fetch(`${BASE}/packs/${encodeURIComponent(packId)}/deltas?status=${status}`);
  if (!res.ok) return [];
  return res.json();
}

export async function setPackDeltaStatus(deltaId: number, status: "accepted" | "dismissed"): Promise<boolean> {
  const res = await fetch(`${BASE}/packs/deltas/${deltaId}/status`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
  });
  return res.ok;
}

// ── User-defined agents (flag `agents.user_defined`) ──────────────────────────
// CRUD over /agents/custom — the domain personas ("Gems on governed data").
// GETs fail soft (routes 404 when the flag is off → empty roster, no error UI).

export interface UserAgent {
  id: string;
  name: string;
  instructions: string;
  connection_id: string;
  schema_scope: string;
  doc_ids: string[];
  pack_ids: string[];
  owner: string;
  enabled: boolean;
  last_eval: { passed: number; total: number; at: string } | null;
  created_at: string;
  updated_at: string;
}

export async function listUserAgents(): Promise<UserAgent[]> {
  const res = await fetch(`${BASE}/agents/custom`);
  if (!res.ok) return [];
  return res.json();
}

export async function createUserAgent(body: {
  name: string; instructions?: string; connection_id?: string; schema_scope?: string;
  doc_ids?: string[]; pack_ids?: string[];
}): Promise<UserAgent> {
  const res = await fetch(`${BASE}/agents/custom`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `create agent failed (${res.status})`);
  return res.json();
}

export async function patchUserAgent(agentId: string, body: {
  name?: string; instructions?: string; connection_id?: string; schema_scope?: string;
  doc_ids?: string[]; pack_ids?: string[]; enabled?: boolean;
}): Promise<UserAgent> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `update agent failed (${res.status})`);
  return res.json();
}

export async function deleteUserAgent(agentId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
  return res.ok;
}

// ── Measured agents: golden questions + evaluation ────────────────────────────

export interface AgentGolden {
  id: string;
  agent_id: string;
  question: string;
  reference_sql: string;
  created_at: string;
}

export interface AgentEvalResult {
  passed: number;
  total: number;
  at: string;
  duration_ms?: number;
  per_question: { golden_id: string; question: string; passed: boolean; error: string }[];
}

export async function listAgentGoldens(agentId: string): Promise<AgentGolden[]> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}/goldens`);
  if (!res.ok) return [];
  return res.json();
}

export async function createAgentGolden(agentId: string, body: {
  question: string; reference_sql: string;
}): Promise<AgentGolden> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}/goldens`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `add golden failed (${res.status})`);
  return res.json();
}

export async function deleteAgentGolden(agentId: string, goldenId: string): Promise<boolean> {
  const res = await fetch(
    `${BASE}/agents/custom/${encodeURIComponent(agentId)}/goldens/${encodeURIComponent(goldenId)}`,
    { method: "DELETE" });
  return res.ok;
}

export async function evaluateUserAgent(agentId: string): Promise<AgentEvalResult> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}/evaluate`, {
    method: "POST",
  });
  if (!res.ok) throw new Error((await res.text()) || `evaluate failed (${res.status})`);
  return res.json();
}

// ── Observability: per-agent run history + optional MLflow trace stats ─────────
// The Agent Workspace overview. Run history always populates (from the history
// store); trace_stats is null when obs.mlflow is off — the overview degrades to
// history-only (the workspace works without a running MLflow server).

export interface AgentRunSummary {
  id: string;
  question: string;
  connection_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  headline: string | null;
  query_count: number;
  agent_id: string;
}

export interface AgentTraceStats {
  trace_count: number;
  error_count: number;
  total_tokens: number;
  total_cost: number;
  latency_p50_ms: number | null;
  latency_p90_ms: number | null;
}

export interface AgentObservability {
  agent_id: string;
  run_count: number;
  runs: AgentRunSummary[];
  trace_stats: AgentTraceStats | null;
}

export async function getAgentObservability(agentId: string): Promise<AgentObservability | null> {
  const res = await fetch(`${BASE}/agents/custom/${encodeURIComponent(agentId)}/observability`);
  if (!res.ok) return null;
  return res.json();
}

// ── Learning / Memory layer (Wave 1 · E4) ───────────────────────────────────
// The closed loop's accumulation, made visible: ambiguity-ledger burn-down, the
// verdict acceptance economy, and trusted-asset counts/lists. See routers/learning.py.
export interface LearningSummary {
  connection_id: string | null;
  ledger: { resolutions: number; by_source: Record<string, number>; served_total: number };
  verdicts: { counts: Record<string, number>; total: number; acceptance_rate: number | null };
  trusted: { queries: number; programs: number };
}

export interface TrustedAssets {
  queries: { id: string; question: string; note?: string; tables?: string[]; tags?: string[] }[];
  programs: {
    id: string; question: string; use_count: number;
    verified_at?: string; last_used_at?: string | null; plan_source?: string;
  }[];
}

/** The Memory-layer headline (org-wide, or one connection). Null on failure — the panel degrades. */
export async function getLearningSummary(connectionId?: string): Promise<LearningSummary | null> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${BASE}/learning/summary${q}`);
  if (!res.ok) return null;
  return res.json();
}

/** The trusted assets themselves — curated queries + replayable programs. */
export async function getTrustedAssets(connectionId?: string): Promise<TrustedAssets | null> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${BASE}/learning/trusted${q}`);
  if (!res.ok) return null;
  return res.json();
}

// ── Grounding-context receipt (Rec 5) ───────────────────────────────────────
// The input-side twin of the Trust Receipt: the exact grounding blocks the SQL
// writer was given for a question. See routers/investigations.py GET /ask/context.
export interface GroundingBlock { key: string; title: string; present: boolean; content: string }
export interface GroundingReceipt {
  receipt: { question: string; connection_id: string; blocks: GroundingBlock[]; present_count: number };
  markdown: string;
}

/** The grounding a question would receive on a connection. Null when the receipt
 *  is disabled (flag ask.context_receipt off → 404) or on any failure — the
 *  affordance simply hides. Fetched lazily on demand: it runs real retrievers. */
export async function getGroundingContext(connectionId: string, question: string): Promise<GroundingReceipt | null> {
  const qs = `?connection=${encodeURIComponent(connectionId)}&question=${encodeURIComponent(question)}`;
  const res = await fetch(`${BASE}/ask/context${qs}`);
  if (!res.ok) return null;
  return res.json();
}
