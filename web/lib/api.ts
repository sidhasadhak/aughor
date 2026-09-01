import type { EvalBasis } from "./agentEval";
import { getApiBase } from "./config";
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
  const res = await fetch(`${getApiBase()}/connections`);
  if (!res.ok) throw new Error("Failed to fetch connections");
  return res.json();
}

export interface DemoSeedResult {
  /** The demo connection's id — present whether or not this call created it. */
  id: string;
  /** True when this call wrote the dataset; false when it already existed. */
  seeded: boolean;
  message: string;
}

/** Provision the bundled demo dataset and return its connection.
 *
 *  Nothing is seeded on boot, so a fresh install has no data at all — this is the
 *  in-app half of `aughor seed`, for the user who never opens a terminal. Idempotent:
 *  calling it when the demo already exists returns the connection with `seeded: false`
 *  and leaves the data alone. */
export async function seedDemoConnection(): Promise<DemoSeedResult> {
  const res = await fetch(`${getApiBase()}/connections/demo`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to load the demo dataset");
  return res.json();
}

// ── Capabilities (commercial tier gating) ──────────────────────────────────
export interface Capabilities {
  tier: "free" | "pro" | "enterprise" | string;
  capabilities: string[];
  roles?: string[];
  /** Whether tenants are distinguishable (per-request identity is enforced).
   *  Per-org controls are hidden without it — with one org, an "org override" can
   *  only restate the deployment config, so offering it is a second place to
   *  configure the same thing. */
  multi_tenant?: boolean;
}

/** The active tier + granted capabilities (defaults to enterprise = everything on). */
export async function getCapabilities(connectionId?: string): Promise<Capabilities> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${getApiBase()}/capabilities${q}`);
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
  const res = await fetch(`${getApiBase()}/business-profile?connection_id=${encodeURIComponent(connectionId)}${q}`);
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
  /** What this workspace can actually see: membership ∪ explicit catalog grants,
   *  resolved by the backend's own visibility gate. The picker filters on THIS —
   *  filtering on `connection_ids` alone hid granted catalogs the API served. */
  accessible_connection_ids?: string[];
  is_default: boolean;
  settings_override?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${getApiBase()}/workspaces`);
  if (!res.ok) throw new Error("Failed to fetch workspaces");
  return res.json();
}

export async function getWorkspace(id: string): Promise<Workspace> {
  const res = await fetch(`${getApiBase()}/workspaces/${encodeURIComponent(id)}`);
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
  /** CA-5 — land on the conversation instead of the workbench. */
  chat_first_home: boolean;
}

export async function getOrgSettings(): Promise<OrgSettings> {
  const res = await fetch(`${getApiBase()}/org-settings`);
  if (!res.ok) throw new Error("Failed to fetch org settings");
  return res.json();
}

export async function updateOrgSettings(settings: OrgSettings): Promise<OrgSettings> {
  const res = await fetch(`${getApiBase()}/org-settings`, {
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

// ── Org-scoped BYOK (CI-5b) — the org's own provider keys + per-role models ────
export interface OrgLLMConfig {
  configured: boolean;
  backend: string;
  models: Record<string, string>;
  keys_set: Record<string, boolean>;          // USABLE — a stored key that cannot be decrypted is false
  keys_state?: Record<string, "set" | "unset" | "unreadable">;
  updated_at: string;
}

export interface OrgLLMPatch {
  backend?: string;
  models?: Record<string, string>;
  keys?: Record<string, string>;
  allow_paid?: boolean;
}

export async function getOrgLLM(): Promise<OrgLLMConfig> {
  const res = await fetch(`${getApiBase()}/org-settings/llm`);
  if (!res.ok) throw new Error("Failed to fetch org model settings");
  return res.json();
}

export async function updateOrgLLM(patch: OrgLLMPatch): Promise<OrgLLMConfig> {
  const res = await fetch(`${getApiBase()}/org-settings/llm`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to update org model settings");
  }
  return res.json();
}

export async function clearOrgLLM(): Promise<OrgLLMConfig> {
  const res = await fetch(`${getApiBase()}/org-settings/llm`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to clear org model settings");
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
  const res = await fetch(`${getApiBase()}/investigations/context/rescope`, {
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
  return fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: "plan approved", keep_subquestions: keepSubquestions }),
  });
}

/** Resume a clarify_pending pause with the metric reading the user chose (P4). */
export function resumeInvestigationClarify(invId: string, clarifyChoice: string): Promise<Response> {
  return fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: "clarify answered", clarify_choice: clarifyChoice }),
  });
}

/** Reject a pending plan — cancel the paused investigation outright. */
export async function cancelInvestigation(invId: string): Promise<void> {
  await fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/cancel`, { method: "POST" });
}

/** FL-1b — cancel the deep run behind a still-loading turn, if it has one.
 *  A deep run executes as a KERNEL JOB (K1): aborting the HTTP stream stops the
 *  watching, not the work, so stop/interrupt must also cancel the job. Lives
 *  here — the backend-contract mirror — so callers need not name the backend's
 *  frozen `investigation` spelling (the vocabulary ratchet's rule); best-effort,
 *  like the reject path above. */
export function cancelActiveDeepRun(
  turn: { investigationId?: string | null } | null | undefined,
): void {
  const id = turn?.investigationId;
  if (id) void cancelInvestigation(id).catch(() => { /* best-effort */ });
}

/** Best-effort capture: the user drilled ("explore this fact") an overview card. Feeds the
 *  per-connection notability prior the next tour reads back (backend overview.drills).
 *  Fire-and-forget — a failed capture must never disrupt the drill it accompanies. */
export function recordOverviewDrill(
  connectionId: string,
  opts: { canvasId?: string; lens?: string; table?: string } = {},
): void {
  try {
    void fetch(`${getApiBase()}/overview/drill`, {
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
  const res = await fetch(`${getApiBase()}/approvals/audit?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch approvals audit");
  return res.json();
}
export async function getAllowlist(): Promise<AllowlistEntry[]> {
  const res = await fetch(`${getApiBase()}/approvals/allowlist`);
  if (!res.ok) throw new Error("Failed to fetch allowlist");
  return res.json();
}
export async function revokeApproval(action: string, scope: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/approvals/revoke`, {
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
  /** S3 fix-it: the SQL that produced the judged answer + an optional human fix —
   *  the structural payload the closed loop reads back into planning. */
  sqlSource?: string;
  correctedSql?: string;
}): Promise<void> {
  const res = await fetch(`${getApiBase()}/verify/verdict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      verdict: input.verdict,
      connection_id: input.connectionId ?? "",
      investigation_id: input.investigationId ?? "",
      headline: input.headline ?? "",
      note: input.note ?? "",
      sql_source: input.sqlSource ?? "",
      corrected_sql: input.correctedSql ?? "",
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to record verdict");
  }
}

/** G2 governed tags, read path (S1/J13): the governance axis rendered on entity
 *  pages. `securable` format is `table:catalog.schema.name`. */
export interface GovernedTag {
  securable: string;
  key: string;
  value: string;
  set_by: string;
  set_at: string;
  source: string;
}

export async function listGovernedTags(opts: { key?: string; securablePrefix?: string } = {}): Promise<GovernedTag[]> {
  const qs = new URLSearchParams();
  if (opts.key) qs.set("key", opts.key);
  if (opts.securablePrefix) qs.set("securable_prefix", opts.securablePrefix);
  const res = await fetch(`${getApiBase()}/governance/tags?${qs.toString()}`);
  if (!res.ok) throw new Error("Failed to list governed tags");
  return res.json();
}

/** S5 cited memory — a remembered reading with its citation (who settled it,
 *  when, how often served). Revocable one row at a time. */
export interface RememberedReading {
  id: string;
  connection_id: string;
  subject: string;
  resolved_reading: string;
  resolution_source: string;
  resolved_sql?: string | null;
  created_at: string;
  last_used_at?: string | null;
  use_count: number;
}

export async function listRememberedReadings(connectionId?: string): Promise<RememberedReading[]> {
  const qs = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${getApiBase()}/learning/resolutions${qs}`);
  if (!res.ok) throw new Error("Failed to list remembered readings");
  return res.json();
}

export async function revokeRememberedReading(resId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/learning/resolutions/${encodeURIComponent(resId)}`,
                          { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to revoke reading");
}

/** K5 — write a human overlay annotation on a table (merged onto reads by K3;
 *  never mutates source). Column/row targeting optional. */
export async function annotateTable(connectionId: string, input: {
  table: string; body: string; column?: string; keyColumn?: string; rowKey?: string;
  kind?: "annotation" | "correction";
}): Promise<{ id: string; target: string }> {
  const res = await fetch(
    `${getApiBase()}/kinetic-actions/annotate?connection_id=${encodeURIComponent(connectionId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        table: input.table, body: input.body, column: input.column ?? "",
        key_column: input.keyColumn ?? "", row_key: input.rowKey ?? "",
        kind: input.kind ?? "annotation",
      }),
    });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to annotate");
  }
  return res.json();
}

export async function getEffectiveSettings(workspaceId?: string): Promise<OrgSettings> {
  const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${getApiBase()}/org-settings/effective${q}`);
  if (!res.ok) throw new Error("Failed to fetch effective settings");
  return res.json();
}

export async function createWorkspace(
  name: string,
  connection_ids: string[] = [],
  description = "",
): Promise<Workspace> {
  const res = await fetch(`${getApiBase()}/workspaces`, {
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
  const res = await fetch(`${getApiBase()}/workspaces/${encodeURIComponent(id)}`, {
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
  const res = await fetch(`${getApiBase()}/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
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
  const res = await fetch(`${getApiBase()}/connections`, {
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
  /** Whether this connector's driver is importable on the server answering the
   *  request. Optional so an older backend still renders — an absent field means
   *  "unknown", which the UI treats as available rather than greying out the
   *  entire picker against a server that simply hasn't been redeployed. */
  available?: boolean;
  /** Module names the connector imports that are missing there. */
  missing?: string[];
}

export async function getConnectorTypes(): Promise<ConnectorTypeInfo[]> {
  const res = await fetch(`${getApiBase()}/connectors/types`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.types ?? [];
}

export async function createFederatedConnection(
  name: string,
  connectionIds: string[],
): Promise<{ id: string; message: string; test_result: string }> {
  const res = await fetch(`${getApiBase()}/connections/federate`, {
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/sync?incremental=${incremental}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error("Sync trigger failed");
  return res.json();
}

export async function getSyncStatus(connId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/sync-status`);
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
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/files`, {
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/files/bulk`,
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
  /** Set when the column holds numbers wearing formatting — '₹1,099', '64%', '24,269'.
   *  Carries WHY the text column is about to become a number, so the review row can say
   *  it rather than showing an unexplained type change. */
  detected_format: { kind: string; unit: string; example: string | null } | null;
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/files/analyze`,
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
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/files`);
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/files/${encodeURIComponent(filename)}?schema=${encodeURIComponent(schema)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error("Delete failed");
}

export async function listConnectionSchemas(connId: string): Promise<string[]> {
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/schemas`);
  if (!res.ok) return ["main"];
  const data = await res.json().catch(() => ({ schemas: ["main"] }));
  return data.schemas ?? ["main"];
}

export async function createConnectionSchema(connId: string, name: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/schemas`, {
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/schemas/${encodeURIComponent(schema)}`,
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}?schema=${encodeURIComponent(schema)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Table remove failed");
  }
}

export async function testConnection(id: string): Promise<TestResult> {
  const res = await fetch(`${getApiBase()}/connections/${id}/test`, { method: "POST" });
  if (!res.ok) throw new Error("Test request failed");
  return res.json();
}

export async function deleteConnection(id: string): Promise<void> {
  await fetch(`${getApiBase()}/connections/${id}`, { method: "DELETE" });
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
  const res = await fetch(`${getApiBase()}/connections/${id}/schema/rich`);
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/sample?${params}`,
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/columns?${params}`,
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/tables/${encodeURIComponent(table)}/alter-column?${params}`,
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
  const res = await fetch(`${getApiBase()}/catalog/tree${qs}`);
  if (!res.ok) throw new Error("Failed to fetch catalog tree");
  return res.json();
}

export async function getSchema(id: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/connections/${id}/schema`);
  if (!res.ok) throw new Error("Failed to fetch schema");
  const data = await res.json();
  return data.schema as string;
}

export async function refreshSchemaCache(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/connections/${id}/schema/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh schema cache");
}

export async function getSchemaDiagram(id: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/connections/${id}/schema/mermaid`);
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
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/health-scorecard`);
  if (!res.ok) return [];
  return res.json();
}

export async function getMetrics(): Promise<Metric[]> {
  const res = await fetch(`${getApiBase()}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}

export async function createMetric(m: Omit<Metric, never>): Promise<Metric> {
  const res = await fetch(`${getApiBase()}/metrics`, {
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
  const res = await fetch(`${getApiBase()}/metrics/${encodeURIComponent(name)}`, {
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
  await fetch(`${getApiBase()}/metrics/${encodeURIComponent(name)}${q}`, { method: "DELETE" });
}

/** B-8 — drive a metric through its governance lifecycle (propose/approve/reject/deprecate). */
export async function transitionMetric(name: string, action: string, actor: string): Promise<{ metric: Metric; audit: MetricAuditEntry }> {
  const res = await fetch(`${getApiBase()}/metrics/${encodeURIComponent(name)}/transition`, {
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
  const res = await fetch(`${getApiBase()}/metrics/${encodeURIComponent(name)}/audit`);
  if (!res.ok) return [];
  return (await res.json()).audit ?? [];
}

export async function validateMetric(name: string, connId: string): Promise<MetricValidationResult> {
  const res = await fetch(
    `${getApiBase()}/metrics/${encodeURIComponent(name)}/validate?conn_id=${encodeURIComponent(connId)}`,
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
    `${getApiBase()}/metrics/${encodeURIComponent(name)}/freshness?conn_id=${encodeURIComponent(connId)}`,
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

// OE-1: first-class typed property on an entity — the semantic label on a column
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

// OE-2: a segment — a saved, named filter over one entity's rows
export interface Segment {
  id: string;
  display_name: string;
  description: string;
  filter_sql: string;
  is_default: boolean;
  source: "lifecycle" | "exploration" | "manual";
}

// OE-3: typed parameter extracted from {placeholder} tokens in sql_template. Shared by
// QueryTemplate.parameters and a declared write action's params — hence the name.
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
  // OE-2. The backend also emits a deprecated `object_sets` copy of this for one
  // release; read `segments`.
  segments: Record<string, Segment>;
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
  const res = await fetch(`${getApiBase()}/connections/${id}/settings`);
  if (!res.ok) return { ontology_refresh_hours: null };
  return res.json();
}

export async function updateConnectionSettings(
  id: string,
  settings: Partial<ConnectionSettings>,
): Promise<ConnectionSettings> {
  const res = await fetch(`${getApiBase()}/connections/${id}/settings`, {
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
  const res = await fetch(`${getApiBase()}/ontology/rebuild?${qs}`, { method: "POST" });
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

// A reusable, governed SQL template over one entity (read-only). The wire keys stay
// `actions` / `action_type` — those are the frozen persisted contract.
export interface QueryTemplate {
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
  actions: Record<string, QueryTemplate>;
  interfaces: Record<string, OntologyInterface>;  // OE-6
}

export async function getOntology(connectionId: string, schemaName?: string): Promise<OntologyGraph> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/ontology?${q}`);
  if (!res.ok) throw new Error("Ontology not available for this connection");
  return res.json();
}

// ── Connection knowledge graph (Wave C4 — GET /graph) ─────────────────────────

export interface CGProvenance { source: string; measured: number | null; note: string }
/** Wave P2 — how we know it, derived at read time from provenance (never stored). */
export type CGWarrantClass = "measured" | "human" | "declared" | "derived" | "inferred";
export interface CGWarrant { warrant: CGWarrantClass; detail: string; label: string }
export interface CGNode {
  id: string; kind: string; label: string; summary: string;
  tags: string[]; provenance: CGProvenance; data: Record<string, unknown>;
  warrant?: CGWarrant;
}
export interface CGEdge {
  id: string; kind: string; from_id: string; to_id: string;
  provenance: CGProvenance; label: string;
  warrant?: CGWarrant;
}
export interface CGDomain { label: string; tables: string[]; table_count: number }
export interface CGDomainEdge { from: string; to: string; count: number }
export type CGStaleness = "fresh" | "dirty" | "stale" | "unknown";
export interface ConnectionGraph {
  org_id: string; connection_id: string; schema_name: string;
  structural_fingerprint: string; version: number;
  nodes: Record<string, CGNode>;
  edges: Record<string, CGEdge>;
  counts: Record<string, number>;
  domains: CGDomain[];
  domain_edges: CGDomainEdge[];
  staleness: CGStaleness;
}

/** The connection knowledge graph for the anti-hairball surface (Wave C4). */
export async function getConnectionGraph(connectionId: string, schemaName?: string): Promise<ConnectionGraph> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/graph?${q}`);
  if (!res.ok) throw new Error("Knowledge graph not available for this connection");
  return res.json();
}

// ── The graph's honesty scorecard (Wave P2 — GET /graph/audit) ────────────────

export interface CGContentDrift {
  drifted: boolean;
  reason: string;
  missing: Record<string, number>;
  [k: string]: unknown;
}
export interface GraphAudit {
  connection_id: string;
  schema_name: string;
  graph_version: number;
  order: CGWarrantClass[];
  labels: Record<CGWarrantClass, string>;
  meanings: Record<CGWarrantClass, string>;
  nodes: Record<CGWarrantClass, number>;
  edges: Record<CGWarrantClass, number>;
  edges_by_kind: Record<string, Record<CGWarrantClass, number>>;
  totals: { nodes: number; edges: number; joins: number };
  /** The headline: how many `joins_on` edges were probed against the data. Joins are
   *  where a warrant is a real choice and a wrong one fabricates rows. */
  joins_measured_share: number;
  /** The whole-graph share, kept for completeness — never the headline, because
   *  provenance links can never be measured and dominate the denominator. */
  edge_grounded_share: number;
  staleness: CGStaleness;
  drift: CGContentDrift | null;
}

/** Warrant mix + staleness + content drift in one call — the three honesty signals
 *  are only meaningful together (Wave P2). */
export async function getGraphAudit(connectionId: string, schemaName?: string): Promise<GraphAudit> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/graph/audit?${q}`);
  if (!res.ok) throw new Error("Graph audit not available");
  return res.json();
}

// ── Node standing (Wave P3 — GET /graph/trust) ────────────────────────────────

export type CGStanding = "confirmed" | "contested" | "disputed" | "corroborated" | "unchecked";
export interface NodeTrust {
  node_id: string;
  standing: CGStanding;
  findings: number;
  contested: number;
  stale: number;
  accepts: number;
  rejects: number;
  detail: string;
  meaning: string;
}
export interface TrustSidecar {
  connection_id: string;
  nodes: Record<string, NodeTrust>;
  meanings: Record<CGStanding, string>;
  by_standing: Record<CGStanding, number>;
  scored_nodes: number;
  verdicts_seen: number;
  /** False ⇒ nobody has recorded a verdict on this connection yet. Stated as a field so
   *  a reader does not have to infer it from a row of zeros. */
  human_signal: boolean;
}

/** What standing each node has earned — a read-time sidecar, never stored (Wave P3). */
export async function getGraphTrust(connectionId: string, schemaName?: string): Promise<TrustSidecar> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/graph/trust?${q}`);
  if (!res.ok) throw new Error("Trust sidecar not available");
  return res.json();
}

// ── What depends on a node (Wave P4 — GET /graph/lineage) ─────────────────────

export interface GraphDependent {
  node_id: string;
  kind: string;
  label: string;
  depth: number;
  via: string;
  /** The expression in THIS node that references the subject — the line that would
   *  break. Empty when the node records no expression (never a guess). */
  site: string;
  site_kind: "sql" | "formula" | "citation" | "";
  site_line: number;
}
export interface GraphLineage {
  connection_id: string;
  node_id: string;
  label: string;
  root: string;
  truncated: boolean;
  counts_by_kind: Record<string, number>;
  summary: string;
  dependents: GraphDependent[];
}

/** What breaks if this table or metric changes — reported, never deleted (Wave P4). */
export async function getGraphLineage(
  connectionId: string, opts: { nodeId?: string; table?: string; schemaName?: string },
): Promise<GraphLineage> {
  const p = new URLSearchParams({ connection_id: connectionId });
  if (opts.nodeId) p.set("node_id", opts.nodeId);
  if (opts.table) p.set("table", opts.table);
  if (opts.schemaName) p.set("schema_name", opts.schemaName);
  const res = await fetch(`${getApiBase()}/graph/lineage?${p.toString()}`);
  if (!res.ok) throw new Error("Lineage not available");
  return res.json();
}

// ── The graph's review queue (Wave P5 — GET /graph/review) ────────────────────

export type CGCheckKind = "probe_join" | "ask" | "review_finding" | "define" | "rebuild";
export interface GraphReviewItem {
  id: string;
  type: "graph_behind" | "unprobed_join" | "contested_finding" | "ungrounded_finding"
      | "undocumented_hub" | "isolated_table";
  question: string;
  why: string;
  subject_id: string;
  subject_label: string;
  check: CGCheckKind;
  /** How many other nodes depend on the thing in doubt — the ranking key, shown so the
   *  reader can see why an item is near the top. Never an invented severity score. */
  depends: number;
  detail: Record<string, unknown>;
}
export interface GraphReview {
  connection_id: string;
  schema_name: string;
  graph_version: number;
  items: GraphReviewItem[];
  /** How many items are in `items` (after the server's limit). */
  total: number;
  /** How many existed BEFORE the limit — a queue that renders 50 over a warehouse with
   *  300 would under-report the very thing it exists to report. */
  total_found: number;
  truncated: boolean;
  by_type: Record<string, number>;
}

/** What the graph knows it cannot vouch for — deterministic, ranked by consequence. */
export async function getGraphReview(connectionId: string, schemaName?: string): Promise<GraphReview> {
  const q = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/graph/review?${q}`);
  if (!res.ok) throw new Error("Graph review not available");
  return res.json();
}

// ── The connection tour (Wave C5 — GET /graph/tour) ───────────────────────────

export interface TourStep {
  order: number;
  node_id: string;
  kind: string;                 // "table" | "metric"
  label: string;
  connects_to: string | null;
  connects_to_label: string;
  connection: string;           // deterministic reason ("joins Order Line", …)
  why: string;                  // deterministic significance
  narration: string;            // LLM connective narration (may be empty)
}
export interface ConnectionTour {
  connection_id: string;
  schema_name: string;
  generated_at: string;
  narrated: boolean;
  steps: TourStep[];
}

/** The topology-ordered connection tour (Wave C5). */
export async function getConnectionTour(connectionId: string, schemaName?: string): Promise<ConnectionTour> {
  const base = schemaName
    ? `connection_id=${encodeURIComponent(connectionId)}&schema_name=${encodeURIComponent(schemaName)}`
    : `connection_id=${encodeURIComponent(connectionId)}`;
  const res = await fetch(`${getApiBase()}/graph/tour?${base}`);
  if (!res.ok) throw new Error("Connection tour not available");
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
  const res = await fetch(`${getApiBase()}/ontology/duplicate-entities?${q}`);
  if (!res.ok) throw new Error("Failed to load duplicate suggestions");
  return (await res.json()).clusters ?? [];
}

export async function mergeOntologyEntities(
  connectionId: string, mergeIds: string[], canonicalId: string, schemaName?: string,
): Promise<{ merged_into: string; removed: string[]; entity_count: number }> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/entities/merge?${q}`, {
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
    `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(overrides) },
  );
  if (!res.ok) throw new Error("Failed to update entity");
  return res.json();
}

export async function patchQueryTemplate(
  connectionId: string,
  actionId: string,
  overrides: Partial<Pick<QueryTemplate, "description" | "sql_template" | "business_rules_enforced" | "returns">>,
): Promise<QueryTemplate> {
  const res = await fetch(
    `${getApiBase()}/ontology/actions/${encodeURIComponent(actionId)}?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(overrides) },
  );
  if (!res.ok) throw new Error("Failed to update action");
  return res.json();
}

// ── Learned Skills (agent procedural memory) ──────────────────────────────────
// Skills ARE QueryTemplates with origin='learned' + a usage_count. The backend
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

export async function getLearnedSkills(connectionId: string, schemaName?: string): Promise<QueryTemplate[]> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/skills?${q}`);
  if (!res.ok) throw new Error("Failed to load learned skills");
  return (await res.json()).skills ?? [];
}

// ── Ontology proposals — the review inbox for what the engine and the conversation
// propose (metric gaps from the self-improving loop; column/table notes an agent staged
// with evidence — ontology/agent_notes.py). A person accepts or dismisses; nothing here
// changes context until they do. Until 2026-08-15 this endpoint had NO web consumer, so
// "the human is the reviewer" had no surface to review on.
export interface OntologyProposal {
  id: string;
  kind: string;                       // "metric" | "column_note" | "table_note"
  target_id: string;
  entity: string;
  proposed_fields: Record<string, unknown>;
  reason: string;
  support: number;
  evidence: Array<Record<string, unknown>>;
  status: string;                     // pending | accepted | dismissed
  first_seen: string;
  last_seen: string;
}

export async function getOntologyProposals(connectionId: string, schemaName?: string): Promise<OntologyProposal[]> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/recommendations?${q}`);
  if (!res.ok) throw new Error("Failed to load ontology proposals");
  return (await res.json()).recommendations ?? [];
}

export async function acceptOntologyProposal(recId: string, connectionId: string, schemaName?: string): Promise<Record<string, unknown>> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/recommendations/${encodeURIComponent(recId)}/accept?${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to accept proposal");
  return res.json();
}

export async function dismissOntologyProposal(recId: string, connectionId: string, schemaName?: string): Promise<void> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/recommendations/${encodeURIComponent(recId)}/dismiss?${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to dismiss proposal");
}

// Crystallize a CANDIDATE skill from a finished investigation (not persisted — the UI
// confirms, then calls saveLearnedSkill). 422 when the run isn't skill-worthy.
export async function proposeLearnedSkill(
  invId: string, connectionId: string, schemaName?: string,
): Promise<QueryTemplate> {
  const q = new URLSearchParams({ inv_id: invId, connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/skills/propose?${q}`, { method: "POST" });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Run is not skill-worthy");
  }
  return (await res.json()).candidate as QueryTemplate;
}

export async function saveLearnedSkill(
  action: QueryTemplate, connectionId: string, schemaName?: string,
): Promise<{ ok: boolean; schema_name: string; id: string }> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/skills?${q}`, {
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
  const res = await fetch(`${getApiBase()}/ontology/skills/${encodeURIComponent(actionId)}/use?${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Learned skill not found");
  return res.json();
}

export async function deleteLearnedSkill(
  actionId: string, connectionId: string, schemaName?: string,
): Promise<void> {
  const q = new URLSearchParams({ connection_id: connectionId });
  if (schemaName) q.set("schema_name", schemaName);
  const res = await fetch(`${getApiBase()}/ontology/skills/${encodeURIComponent(actionId)}?${q}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete learned skill");
}

export async function getAutonomy(connectionId: string): Promise<AutonomyLevel> {
  const q = new URLSearchParams({ connection_id: connectionId });
  const res = await fetch(`${getApiBase()}/ontology/autonomy?${q}`);
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/status`);
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

/** Collision-proof identity for a finding — use this (NOT `insightKey` or a bare `.id`) as the
 *  React key and the client-side dedup identity for any list of ExplorationInsights.
 *
 *  `insightKey` (source_schema::id) is NOT unique for the meta-domains ("Key Questions" /
 *  "Synthesis"): their findings reuse bare ids like `pinned__4` / `synth__chain__1` — some as
 *  TRUE duplicates (same id AND text, e.g. a pinned question aggregated across schemas), some as
 *  DISTINCT findings that merely share an id. Folding the finding text in disambiguates the
 *  id-collisions; running the list through `dedupeInsights` first drops the true duplicates. Doing
 *  both is what stops React's "two children with the same key" warning at the finding lists. */
export function insightUid(ins: { id: string; source_schema?: string; finding: string }): string {
  return `${insightKey(ins)}|${ins.finding}`;
}

/** Drop repeated findings (first occurrence wins), keyed by `insightUid`. */
export function dedupeInsights<T extends { id: string; source_schema?: string; finding: string }>(list: T[]): T[] {
  const seen = new Set<string>();
  return list.filter(i => { const k = insightUid(i); if (seen.has(k)) return false; seen.add(k); return true; });
}

/** Dedup every domain's findings in a domain→insights map. Apply this once at the fetch
 *  boundary so every downstream surface (counts, lists, keys) sees the same de-duplicated
 *  findings — the meta-domains ("Key Questions" / "Synthesis") arrive with the same finding
 *  repeated (aggregated across schemas). */
export function dedupeDomainInsights<D extends { insights: { id: string; source_schema?: string; finding: string }[] }>(
  map: Record<string, D>,
): Record<string, D> {
  return Object.fromEntries(Object.entries(map).map(([k, d]) => [k, { ...d, insights: dedupeInsights(d.insights) }]));
}

export interface DomainInsights {
  insights: ExplorationInsight[];
  queries_used: number;
  budget_cap: number;
  angles_covered: string[];
}

export async function getDomainInsights(connectionId: string, schema?: string): Promise<Record<string, DomainInsights>> {
  const params = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/domains${params}`);
  if (!res.ok) throw new Error("Failed to fetch domain insights");
  return res.json();
}

export async function extendDomainBudget(connectionId: string, domain: string): Promise<{ ok: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/domains/${encodeURIComponent(domain)}/extend`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to extend domain budget");
  return res.json();
}

export async function getCanvasDomainInsights(canvasId: string): Promise<Record<string, DomainInsights>> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/domains`);
  if (!res.ok) throw new Error("Failed to fetch canvas domain insights");
  return res.json();
}

export async function extendCanvasDomainBudget(canvasId: string, domain: string): Promise<{ ok: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/domains/${encodeURIComponent(domain)}/extend`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to extend canvas domain budget");
  return res.json();
}

export async function promoteCanvasInsight(canvasId: string, insightId: string): Promise<{ promoted: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/findings/${encodeURIComponent(insightId)}/promote`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to promote insight");
  return res.json();
}

export async function promoteConnectionInsight(connectionId: string, insightId: string): Promise<{ promoted: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/findings/${encodeURIComponent(insightId)}/promote`,
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
  const res = await fetch(`${getApiBase()}/cards/pin-insight`, {
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
  const res = await fetch(`${getApiBase()}/cards/pin-query`, {
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
  const res = await fetch(`${getApiBase()}/cards?${q.toString()}`);
  if (!res.ok) throw new Error("Failed to list dashboard cards");
  return res.json();
}

/** Update a pinned card in place — the seam used to persist a chart's display config into
 *  `card.render`. `PUT /cards/{id}` has existed since the cockpit shipped but had no client,
 *  so every edit to a pinned chart was lost on unmount. */
export async function updateDashboardCard(cardId: string, card: DashboardCard): Promise<DashboardCard> {
  const res = await fetch(`${getApiBase()}/cards/${encodeURIComponent(cardId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(card),
  });
  if (!res.ok) throw new Error("Failed to update dashboard card");
  return res.json();
}

/** Saved chart display configs for a scope, as `{target_id: config}` — one fetch per brief.
 *  For charts that are NOT pinned cards (ledger rows, digest tiles, KPI trends) and therefore
 *  have no `render` blob of their own. `scopeKey` matches the briefing's stamp. */
export async function getVizConfigs(scopeKey: string): Promise<Record<string, Record<string, unknown>>> {
  const res = await fetch(`${getApiBase()}/viz-configs?scope_key=${encodeURIComponent(scopeKey)}`);
  if (!res.ok) return {};                     // best-effort: display prefs never block a render
  return res.json();
}

/** Persist one card-less chart's display config. An empty `config` resets it. */
export async function saveVizConfig(
  scopeKey: string, targetId: string, config: Record<string, unknown>,
): Promise<void> {
  await fetch(`${getApiBase()}/viz-configs`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope_key: scopeKey, target_id: targetId, config }),
  });
}

/** Recompute a card's value now (guard-on-read). Returns the current result + the rolling
 *  last/prev value for a delta. */
export async function runDashboardCard(cardId: string): Promise<CardRunResult> {
  const res = await fetch(`${getApiBase()}/cards/${encodeURIComponent(cardId)}/run`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh dashboard card");
  return res.json();
}

export async function deleteDashboardCard(cardId: string): Promise<void> {
  await fetch(`${getApiBase()}/cards/${encodeURIComponent(cardId)}`, { method: "DELETE" });
}

/** The cockpit layout (position + size per card) the reader arranged — saved SERVER-SIDE and
 *  account-keyed, so any device/login shows the same arrangement. */
export type CockpitLayout = Record<string, { x: number; y: number; w: number; h: number }>;

export async function getCockpitLayout(connectionId: string): Promise<CockpitLayout> {
  try {
    const res = await fetch(`${getApiBase()}/cards/layout?connection_id=${encodeURIComponent(connectionId)}`);
    return res.ok ? await res.json() : {};
  } catch { return {}; }
}

export async function saveCockpitLayout(connectionId: string, layout: CockpitLayout): Promise<void> {
  await fetch(`${getApiBase()}/cards/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, layout }),
  }).catch(() => {});
}

/** Graduate a KPI/watch card to a scheduled Monitor (Slice 4 — watch → alert): its guarded SQL
 *  becomes a recurring threshold check and the thresholds are recorded back on the card. */
export async function graduateCard(
  cardId: string,
  thresholds: { warning_threshold?: number | null; critical_threshold?: number | null; threshold_direction?: string },
): Promise<{ card: DashboardCard }> {
  const res = await fetch(`${getApiBase()}/cards/${encodeURIComponent(cardId)}/graduate`, {
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

export async function dismissCanvasInsight(canvasId: string, insightId: string, reason: string): Promise<{ dismissed: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/findings/${encodeURIComponent(insightId)}/dismiss`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }
  );
  if (!res.ok) throw new Error("Failed to dismiss insight");
  return res.json();
}

export async function dismissConnectionInsight(connectionId: string, insightId: string, reason: string): Promise<{ dismissed: boolean }> {
  const res = await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/findings/${encodeURIComponent(insightId)}/dismiss`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }
  );
  if (!res.ok) throw new Error("Failed to dismiss insight");
  return res.json();
}

export async function resumeCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/resume`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to resume canvas exploration");
  return res.json();
}

export async function stopCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop canvas exploration");
  return res.json();
}

export async function restartCanvasExploration(canvasId: string): Promise<{ status: string }> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/restart`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to restart canvas exploration");
  return res.json();
}

export async function getCanvasExplorationStatus(canvasId: string): Promise<ExplorationStatus> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/status`);
  if (!res.ok) throw new Error("Failed to fetch canvas exploration status");
  return res.json();
}

export async function triggerCanvasDomainIntelligence(canvasId: string): Promise<{ ok: boolean; reason?: string }> {
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/trigger-intel`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger canvas domain intelligence");
  return res.json();
}

export async function getCanvasExplorationEpisodes(canvasId: string, phase = "", limit = 300): Promise<ExplorationEpisode[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (phase) params.set("phase", phase);
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/episodes?${params}`);
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/findings${q}`);
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop exploration");
  return res.json();
}

export async function resumeExploration(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/resume`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to resume exploration");
  return res.json();
}

export async function restartExploration(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/restart`, { method: "POST" });
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/retry-query`, {
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/fix-episode`, {
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/fix-all`, {
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
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/episodes?phase=${encodeURIComponent(phase)}&limit=${limit}`,
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
  const res = await fetch(`${getApiBase()}/dev/stats`);
  if (!res.ok) throw new Error("Failed to fetch dev stats");
  return res.json();
}

export async function resetDevStats(): Promise<void> {
  await fetch(`${getApiBase()}/dev/stats/reset`, { method: "POST" });
}

export async function getConnectionFreshness(connId: string): Promise<{ freshness: string | null; source: string | null }> {
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/freshness`);
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
    `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}/lifecycle-counts?connection_id=${encodeURIComponent(connectionId)}`,
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
    `${getApiBase()}/investigations/${encodeURIComponent(invId)}/recommendations/${recIndex}/outcome`,
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
  const res = await fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/outcomes`);
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

/** What the knowledge plane can actually do right now — see `aughor/knowledge/health.py`.
 *  Exists because an empty search result had four possible causes and one appearance. */
export interface KnowledgeStatus {
  /** A search can run AND there is something to search. Stricter than "no error": a
   *  working embedder over an empty corpus is healthy and useless. */
  ready: boolean;
  /** "" when ready; otherwise which of the four it is. */
  reason: string;
  documents: number;
  /** What the STORE holds — the only number that answers "how much can be searched".
   *  The per-document `chunk_count` below is the registry's CLAIM, and they differ. */
  chunks: number;
  /** `dim` is PROBED from the live embedder, never declared, so it is absent when the
   *  probe could not run. `stored_dim` appears only when the index disagrees with it —
   *  which is the one state where nothing can be indexed OR searched. */
  embedder: {
    backend?: string; model: string; endpoint: string; ok: boolean;
    dim?: number; stored_dim?: number; error?: string; why?: string;
  };
  store: { ok: boolean; backend: string; chunks?: number; why?: string };
  consistency: {
    ok: boolean;
    orphan_documents: number;
    orphan_chunks: number;
    orphans: string[];
    mismatched_documents: Record<string, { registry: number; store: number }>;
    listed_chunks_present: number;
  };
}

export async function getKnowledgeStatus(): Promise<KnowledgeStatus | null> {
  const res = await fetch(`${getApiBase()}/knowledge/status`);
  if (!res.ok) return null;
  return res.json();
}

export async function listDocuments(): Promise<DocumentEntry[]> {
  const res = await fetch(`${getApiBase()}/documents`);
  if (!res.ok) return [];
  return res.json();
}

/** How a document is cut up. Every field defaults to the value the corpus was indexed
 *  under, so an omitted setting is the previous behaviour and not a new one. */
export interface ChunkSettings {
  delimiter: string;
  max_chars: number;
  overlap_chars: number;
  min_chars: number;
  collapse_whitespace: boolean;
  strip_urls_emails: boolean;
}

export interface ChunkPreview {
  total_chunks: number;
  shown: number;
  characters: number;
  settings: ChunkSettings;
  chunks: { index: number; characters: number; tokens_estimate: number; text: string }[];
}

/** Chunk a document and show the result WITHOUT indexing it — no embedder, no writes.
 *  The alternative to seeing is upload, look at a number, delete, try again. */
export async function previewDocumentChunks(
  file: File, settings?: Partial<ChunkSettings>,
): Promise<ChunkPreview> {
  const form = new FormData();
  form.append("file", file);
  if (settings && Object.keys(settings).length) form.append("chunk_settings", JSON.stringify(settings));
  const res = await fetch(`${getApiBase()}/documents/preview`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Preview failed");
  }
  return res.json();
}

export async function uploadDocument(
  file: File, settings?: Partial<ChunkSettings>,
): Promise<DocumentEntry> {
  const form = new FormData();
  form.append("file", file);
  if (settings && Object.keys(settings).length) form.append("chunk_settings", JSON.stringify(settings));
  const res = await fetch(`${getApiBase()}/documents/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/documents/${encodeURIComponent(docId)}`, { method: "DELETE" });
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/process-map/${encodeURIComponent(entityId)}`,
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
    `${getApiBase()}/connections/${encodeURIComponent(connId)}/causal-graph`,
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
  const res = await fetch(`${getApiBase()}/canvases${qs}`);
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
  const res = await fetch(`${getApiBase()}/canvases`, {
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
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(id)}`, {
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
  const res = await fetch(`${getApiBase()}/saved-queries${qs}`);
  if (!res.ok) throw new Error("Failed to fetch saved queries");
  return res.json();
}

// ── Quick Fix (SE-5a) ─────────────────────────────────────────────────────────

export interface QuickFix {
  /** "" when the model proposed nothing — see `changed`. */
  proposed_sql: string;
  rationale: string;
  changed: boolean;
  /** The deterministic classifier's read on the failure, independent of the model. */
  diagnosis: string;
}

/** Ask for a proposed repair. The server never executes it and never applies it. */
export async function quickFixSql(connId: string, sql: string, error: string): Promise<QuickFix> {
  const res = await fetch(`${getApiBase()}/query/quickfix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conn_id: connId, sql, error }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Quick fix failed"));
  }
  return res.json();
}

// ── Saved-query versions (SE-4 J) ─────────────────────────────────────────────

export interface SavedQueryVersion {
  version: number;
  state: string;
  created_at: string;
  name: string;
  sql: string;
  spec: Record<string, unknown>;
}

/** One field-level change between two versions. `path` is a dotted/indexed location
 *  (`spec.filters[0].op`), which is why this is not a text diff. */
export interface SavedQueryChange {
  kind: "add" | "delete" | "change" | "move";
  path: string;
  before: unknown;
  after: unknown;
}

export async function listSavedQueryVersions(queryId: string): Promise<SavedQueryVersion[]> {
  const res = await fetch(`${getApiBase()}/saved-queries/${encodeURIComponent(queryId)}/versions`);
  if (!res.ok) throw new Error("Failed to fetch version history");
  return (await res.json()).versions ?? [];
}

export async function diffSavedQueryVersion(
  queryId: string, version: number, against?: number,
): Promise<{ from_version: number; to_version: number; changes: SavedQueryChange[] }> {
  const qs = against !== undefined ? `?against=${against}` : "";
  const res = await fetch(
    `${getApiBase()}/saved-queries/${encodeURIComponent(queryId)}/versions/${version}/diff${qs}`);
  if (!res.ok) throw new Error("Failed to diff versions");
  return res.json();
}

export async function restoreSavedQuery(queryId: string, version: number): Promise<SavedQuery> {
  const res = await fetch(
    `${getApiBase()}/saved-queries/${encodeURIComponent(queryId)}/restore`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(fastApiError(err, "Restore failed"));
  }
  return (await res.json()).query;
}

export async function createSavedQuery(
  connectionId: string, name: string, sql: string, spec: Record<string, unknown>,
): Promise<SavedQuery> {
  const res = await fetch(`${getApiBase()}/saved-queries`, {
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
  const res = await fetch(`${getApiBase()}/saved-queries/${encodeURIComponent(id)}`, {
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
  const res = await fetch(`${getApiBase()}/saved-queries/${encodeURIComponent(id)}`, { method: "DELETE" });
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
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/measure-grains`);
  if (!res.ok) throw new Error("Failed to fetch measure grains");
  return res.json();
}

/** Distinct non-null values for a column — powers the filter-value picker. */
export async function getColumnDistinct(
  connId: string, table: string, column: string, schema?: string, limit = 200,
): Promise<{ values: (string | null)[]; truncated: boolean }> {
  const qs = new URLSearchParams({ table, column, limit: String(limit) });
  if (schema) qs.set("schema", schema);
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connId)}/distinct?${qs.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch distinct values");
  return res.json();
}

/** LLM-inferred Canvas name + description from the scoped tables' schema. */
export async function suggestCanvasName(
  connectionId: string,
  tables: string[],
): Promise<{ name: string; description: string }> {
  const res = await fetch(`${getApiBase()}/canvases/suggest-name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, tables }),
  });
  if (!res.ok) throw new Error(fastApiError(await res.json().catch(() => ({})), "Failed to suggest name"));
  return res.json();
}

/** Per-Canvas plain-English instructions (distinct from connection-level). */
export async function getCanvasInstructions(canvasId: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(canvasId)}/instructions`);
  if (!res.ok) return "";
  const d = await res.json().catch(() => ({ text: "" }));
  return d.text ?? "";
}

export async function putCanvasInstructions(canvasId: string, text: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(canvasId)}/instructions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(fastApiError(await res.json().catch(() => ({})), "Failed to save instructions"));
}

export async function deleteCanvas(id: string): Promise<void> {
  await fetch(`${getApiBase()}/canvases/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function getCanvasSchema(id: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(id)}/schema`);
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
  const res = await fetch(getApiBase() + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts");
  if (!res.ok) throw new Error("Failed to fetch artifacts");
  const data = await res.json();
  return data.artifacts ?? [];
}

export async function createCanvasArtifact(
  canvasId: string,
  payload: Omit<CanvasArtifact, "id" | "canvas_id" | "created_at">,
): Promise<CanvasArtifact> {
  const res = await fetch(getApiBase() + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create artifact");
  return res.json();
}

export async function deleteCanvasArtifact(canvasId: string, artifactId: string): Promise<void> {
  const res = await fetch(getApiBase() + "/canvases/" + encodeURIComponent(canvasId) + "/artifacts/" + encodeURIComponent(artifactId), {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete artifact");
}

export async function getCanvasHistory(id: string, limit = 20): Promise<CanvasHistoryItem[]> {
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(id)}/history?limit=${limit}`);
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
  const res = await fetch(`${getApiBase()}/playbook/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to remove playbook item");
}

/** Edit just the recommendation text of a playbook item (preserves the rest). */
export async function editPlaybookRecommendation(id: string, recommendation: string): Promise<void> {
  const cur = await fetch(`${getApiBase()}/playbook/${encodeURIComponent(id)}`).then(r => (r.ok ? r.json() : null));
  if (!cur) throw new Error("Playbook item not found");
  const body = {
    trigger_metric: cur.trigger_metric, trigger_condition: cur.trigger_condition,
    trigger_operator: cur.trigger_operator ?? "any", trigger_value: cur.trigger_value ?? 0,
    recommendation, expected_impact: cur.expected_impact ?? "",
    typical_timeline: cur.typical_timeline ?? "", owner_role: cur.owner_role ?? "",
    tags: cur.tags ?? [], status: cur.status ?? "active", source_kb_id: cur.source_kb_id ?? null,
  };
  const res = await fetch(`${getApiBase()}/playbook/${encodeURIComponent(id)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update playbook item");
}

/** Remove a single history line item (an investigation, or a whole chat session). */
export async function deleteInvestigation(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/investigations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to remove history item");
}

export async function getCanvasRecents(id: string, limit = 10): Promise<Array<{ question: string; status: string; created_at: string }>> {
  const res = await fetch(`${getApiBase()}/canvases/${encodeURIComponent(id)}/recents?limit=${limit}`);
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
  const res = await fetch(`${getApiBase()}/query/run`, {
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

// ── SE-1 — the Query workbench's typed run (format:"typed", SE-0's contract) ──────
//
// A separate function from runDirectQuery rather than a flag on it: the two return
// DIFFERENT shapes (typed columns, truncation honesty, caveats), and collapsing them
// behind one signature would make every caller re-narrow the result. The legacy shape
// stays exactly as it was for the visual builder.

export interface TypedColumn {
  name: string;
  /** Normalised type name from the backend (`norm_type`) — drives alignment. */
  type: string;
}

export interface TypedQueryResult {
  columns: string[];
  columns_typed: TypedColumn[];
  /** Cells are JSON-safe; a real SQL NULL arrives as null, distinct from "". */
  rows: (string | number | boolean | null)[][];
  row_count: number;
  /** True when the server's n+1 probe row proved there is more beyond the limit. */
  truncated: boolean;
  duration_ms: number;
  sql: string;
  cached: boolean;
  error: string | null;
  receipt_id?: string | null;
  caveats?: string[];
  format: "typed";
}

/** Thrown when the user cancelled the run — distinct from a query that failed, because
 *  it is not a fault and must not be reported as one. */
export class QueryCancelled extends Error {
  constructor() { super("Query cancelled."); this.name = "QueryCancelled"; }
}

export async function runWorkbenchQuery(
  connId: string,
  sql: string,
  limit = 500,
  /** SE-4 H: values for the statement's `:name` parameters. Sent as a FIELD, never
   *  substituted into the SQL here — client-side interpolation would hand the server a
   *  statement whose shape depends on user input, which is the one thing bind values
   *  exist to prevent. */
  params?: Record<string, unknown>,
  /** SE-3 F: abort this to cancel. Aborting the fetch closes the socket, which is
   *  the server's cancel signal — it interrupts the engine mid-statement rather
   *  than letting a runaway query finish into a response nobody will read. */
  signal?: AbortSignal,
): Promise<TypedQueryResult> {
  let res: Response;
  try {
    res = await fetch(`${getApiBase()}/query/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conn_id: connId, sql, limit,
        use_cache: false, use_bulk: false,
        format: "typed",
        // Names this surface for the audit trail and for gate_user_sql's policy.
        source: "query_workbench",
        ...(params && Object.keys(params).length ? { params } : {}),
      }),
      signal,
    });
  } catch (e) {
    // An aborted fetch rejects with AbortError. That is the user's own click coming
    // back to them, so it becomes a typed cancellation rather than "Failed to fetch".
    if (signal?.aborted || (e instanceof DOMException && e.name === "AbortError")) {
      throw new QueryCancelled();
    }
    throw e;
  }
  if (!res.ok) {
    // 499 is the server observing the same abort. It can arrive when the response
    // races the disconnect, so it means cancelled here too — never an error toast.
    if (res.status === 499) throw new QueryCancelled();
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Query failed");
  }
  return res.json();
}

// ── SE-2 — the editor's history rail, a filtered read of the audit log ───────────
//
// Not a second store: every workbench run already writes an audit row tagged with the
// surface that issued it (`source: "query_workbench"` → the log's `hypothesis_id`), so
// "my recent queries" is a filter over the record that must exist anyway. A dedicated
// history table would be a second source of truth that could disagree with the audit.

export interface AuditRecord {
  id: string;
  ts: string;
  connection_id: string;
  /** The issuing surface — `query_workbench`, `query_builder`, … (SE-0's label). */
  hypothesis_id: string;
  sql_digest: string;
  sql_full: string;
  verdict: string;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
}

export async function getQueryHistory(
  connectionId: string, limit = 40, label = "query_workbench",
): Promise<AuditRecord[]> {
  const params = new URLSearchParams({
    limit: String(limit), connection_id: connectionId, label,
  });
  const res = await fetch(`${getApiBase()}/security/audit?${params}`);
  if (!res.ok) return [];
  const data = await res.json();
  return (data as { records?: AuditRecord[] }).records ?? [];
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
  const res = await fetch(`${getApiBase()}/query/semantic`, {
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
  const res = await fetch(`${getApiBase()}/query/build-sql`, {
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
  const res = await fetch(`${getApiBase()}/query/decompile`, {
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
  /** De-duped prompt-hint STRINGS from the fan-out detector battery (Verifier.scan). */
  fanout_hits: string[];
  join_warnings: { table_a: string; col_a: string; table_b: string; col_b: string; overlap: number }[];
  filter_warnings: { table: string; column: string; literal: string; op: string; suggestion: string }[];
  // SE-2: the endpoint has always returned these three; the type simply never named
  // them, so every consumer was blind to the grain, trust and mutation verdicts.
  // Optional because older cached responses (and the tests' fixtures) omit them.
  grain_warnings?: { table: string; join_key: string; ratio: number; caveat: string }[];
  trust_findings?: Record<string, unknown>[];
  mutation_blockers?: { name: string; reason: string }[];
  /** SE-4 H — the guards could not read this query (a parameter has no value), so
   *  NOTHING was checked. Distinct from `passed: true`, and the reason `passed` is
   *  false here: an issue_count of 0 must never be rendered as a clean bill of health
   *  when zero things were looked at. */
  unchecked?: boolean;
  note?: string;
}

/** `dialect` defaults server-side to the connection's own, so callers that don't know
 *  it (the chat surface) can omit it; the SQL editor passes the resolved family. */
export async function validateQuery(
  connId: string, sql: string, dialect?: string,
  /** SE-4 H: without these the guards cannot read a parameterised query's literals,
   *  and the verdict comes back `unchecked` rather than clean. */
  params?: Record<string, unknown>,
): Promise<QueryValidation> {
  const res = await fetch(`${getApiBase()}/query/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conn_id: connId, sql,
      ...(dialect ? { dialect } : {}),
      ...(params && Object.keys(params).length ? { params } : {}),
    }),
  });
  if (!res.ok) throw new Error("Validation failed");
  return res.json();
}

// Lightweight feedback/remember signal on a chat answer (journaled to the ledger).
export async function sendChatFeedback(connId: string, turnId: string, verdict: "helpful" | "unhelpful", note = ""): Promise<void> {
  await fetch(`${getApiBase()}/chat/feedback`, {
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
  const res = await fetch(`${getApiBase()}/investigations/${invId}/evidence`);
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
  const res = await fetch(`${getApiBase()}/investigations/evidence/recent?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function submitClaimFeedback(
  invId: string,
  claimId: string,
  feedback: "validated" | "disputed" | "needs_context",
  note?: string,
): Promise<EvidenceClaim> {
  const res = await fetch(`${getApiBase()}/investigations/${invId}/evidence/${claimId}/feedback`, {
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
  /** WP-1b — deterministic correctness finding on the monitor's
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
  const res = await fetch(`${getApiBase()}/monitors${q ? `?${q}` : ""}`);
  if (!res.ok) throw new Error("Failed to fetch monitors");
  return res.json();
}

export async function createMonitor(data: Partial<MonitorDef> & { conn_id: string; name: string }): Promise<MonitorDef> {
  const res = await fetch(`${getApiBase()}/monitors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create monitor");
  return res.json();
}

export async function updateMonitor(id: string, data: Partial<MonitorDef>): Promise<MonitorDef> {
  const res = await fetch(`${getApiBase()}/monitors/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update monitor");
  return res.json();
}

export async function deleteMonitor(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/monitors/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete monitor");
}

export async function triggerMonitor(id: string): Promise<MonitorAlert | { fired: false }> {
  const res = await fetch(`${getApiBase()}/monitors/${id}/trigger`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger monitor");
  return res.json();
}

export async function getMonitorAlerts(monitorId: string, limit = 50): Promise<MonitorAlert[]> {
  const res = await fetch(`${getApiBase()}/monitors/${monitorId}/alerts?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function getAllAlerts(connId?: string, limit = 100, workspaceId?: string): Promise<MonitorAlert[]> {
  const qs = new URLSearchParams();
  if (connId) qs.set("conn_id", connId);
  qs.set("limit", String(limit));
  if (workspaceId) qs.set("workspace_id", workspaceId);
  const res = await fetch(`${getApiBase()}/alerts?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function acknowledgeAlert(alertId: string): Promise<MonitorAlert> {
  const res = await fetch(`${getApiBase()}/alerts/${alertId}/acknowledge`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to acknowledge alert");
  return res.json();
}

export async function getDigest(connId: string, period: "week" | "day" = "week"): Promise<DigestResult> {
  const res = await fetch(`${getApiBase()}/monitors/digest?conn_id=${connId}&period=${period}`);
  if (!res.ok) throw new Error("Failed to fetch digest");
  return res.json();
}

// ── Automations (Wave A) ────────────────────────────────────────────────────────
// The condition→effect engine (A2), its per-tick history (A1), and the resolve-once
// proposal inbox + standing grants (A4). Every route self-gates on `automations.engine`
// (and the inbox on `automations.proposals`) → a 404 means the plane is off.

export type ConditionKind = "schedule" | "metric" | "source_change" | "entity_appears";
/** The effect kinds a PERSON may author.
 *
 *  Narrower than the server's `Literal` on purpose: `monitor` and `agent_alert` are
 *  adopted objects the engine writes when an existing monitor or alert rule migrates onto
 *  it — the model's own docstring says they are "not authored by hand". */
export type EffectKind =
  | "investigate" | "brief" | "notify" | "kinetic_action" | "slack_post" | "subchain";

/**
 * The `config` keys each kind REQUIRES, mirroring `_CONDITION_REQUIRED` and
 * `_EFFECT_REQUIRED` in `aughor/automations/models.py`.
 *
 * Here rather than in a component for the same reason the rest of this module is here:
 * it is the backend contract spelled field-for-field, and a UI that re-states a contract
 * in its own words is a UI that drifts from it. `tests/unit/test_automation_required_keys.py`
 * asserts this object against the Python one, so the mirror cannot go stale silently —
 * which is the failure mode a hand-copied map has by default.
 */
export const AUTOMATION_REQUIRED_KEYS: Record<string, string[]> = {
  schedule: ["cron"], metric: ["monitor_id"],
  source_change: ["table"], entity_appears: ["table"],
  investigate: ["question"], brief: ["subscription_id"],
  notify: ["trigger_id"], kinetic_action: ["action_id"],
  slack_post: ["bot_id", "channel"], subchain: ["automation_id"],
};

/** A Slack bot record, tokens masked by the server (`to_safe_dict`). Never carries a
 *  usable credential — the mask is what the client renders and sends back. */
export interface SlackBotSummary {
  id: string;
  name: string;
  enabled: boolean;
  team_id: string;
  bot_user_id: string;
  /** DS-5 — the agent this bot is a door ONTO. On the wire since RC-5 (`to_safe_dict`
   *  masks only the three secrets); undeclared here until the agent map needed to ask
   *  which bots belong to an agent. */
  agent_id: string;
  connection_id: string;
}

/** B1 — the effect-kind vocabulary the canvas draws its ports from. FETCHED, never
 *  mirrored: a hand-copied vocabulary rots in the worst direction, and the server's
 *  `PUBLISHED_KEYS` is the same table `validate_chain` refuses against. */
export interface GuardOp { op: string; label: string; unary: boolean }

export interface AutomationVocabulary {
  kinds: Record<string, { publishes: string[] | null; bindable: string[] }>;
  /** W1 — every comparison the engine can make, with the word each READS as and
   *  whether it takes a second value. `unary` is what tells a form to hide the right
   *  field rather than ask for a value that is then ignored. */
  guardOps: GuardOp[];
  /** W2 — the fan-out's own vocabulary. `maxItems` is the engine's cap: a form that
   *  carried its own copy would offer a list the save then refuses, which is the drift
   *  every fetched vocabulary here exists to prevent. `itemAlias`/`itemValueKey` are
   *  how an iteration names its item (`item.value`), so a hint can say it without
   *  hardcoding the reserved word. */
  forEach: { maxItems: number; itemAlias: string; itemValueKey: string;
             publishes: string[] };
}

export async function getAutomationVocabulary(): Promise<AutomationVocabulary> {
  const res = await fetch(`${getApiBase()}/automations/vocabulary`);
  if (!res.ok) throw new Error(`Failed to load the vocabulary (${res.status})`);
  const body = await res.json();
  const fe = body.for_each ?? {};
  return {
    kinds: body.kinds ?? {},
    guardOps: body.guard_ops ?? [],
    forEach: {
      maxItems: fe.max_items ?? 0,
      itemAlias: fe.item_alias ?? "item",
      itemValueKey: fe.item_value_key ?? "value",
      publishes: fe.publishes ?? [],
    },
  };
}

/** DS-1 — one placeable thing, as the server describes it.
 *
 *  A sibling document to the vocabulary above, not part of it: that one is a closed set
 *  of constants (safe to cache for the page), while this one counts the objects on THIS
 *  deployment — bots, triggers, subscriptions, monitors — and its answer changes the
 *  moment a reader creates one. `availability` is why the palette can refuse to look the
 *  same on an install that can post to Slack and one that cannot. */
export interface AutomationPaletteEntry {
  kind: string;
  group: "trigger" | "action";
  label: string;
  description: string;
  /** An icon name from the client's own set — the server is guarded against sending one
   *  we cannot draw (`tests/unit/test_automation_palette.py`). */
  icon: string;
  /** The server's curated order within a group; the client sorts by it, then by name. */
  priority: number;
  publishes: string[] | null;
  bindable: string[];
  availability: "ready" | "needs_setup";
  /** Why it cannot be used here, in the words the reader should see. "" when ready. */
  reason: string;
}

export async function getAutomationPalette(
  connId?: string,
): Promise<AutomationPaletteEntry[]> {
  const qs = connId ? `?conn_id=${encodeURIComponent(connId)}` : "";
  const res = await fetch(`${getApiBase()}/automations/palette${qs}`);
  if (!res.ok) throw new Error(`Failed to load the palette (${res.status})`);
  const body = await res.json();
  return (body.entries ?? []) as AutomationPaletteEntry[];
}

/** DS-4 — where each step sits on the Design canvas, as `{alias: {x, y}}`.
 *
 *  Server-side and account-keyed rather than `localStorage`, for the reason the cockpit's
 *  layout settled once: an arrangement someone made on their laptop and cannot find on
 *  their desktop reads as the product having forgotten it. Its own endpoint, never a
 *  field on the automation — a view preference must not ride the record the engine
 *  reads, or a rename moves somebody's nodes. */
export type CanvasLayout = Record<string, { x: number; y: number }>;

export async function getAutomationLayout(id: string): Promise<CanvasLayout> {
  const res = await fetch(`${getApiBase()}/automations/${encodeURIComponent(id)}/layout`);
  if (!res.ok) throw new Error(`Failed to load the layout (${res.status})`);
  return ((await res.json())?.layout ?? {}) as CanvasLayout;
}

export async function saveAutomationLayout(id: string, layout: CanvasLayout): Promise<void> {
  const res = await fetch(`${getApiBase()}/automations/${encodeURIComponent(id)}/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout }),
  });
  if (!res.ok) throw new Error(`Failed to save the layout (${res.status})`);
}

/* ── VA-11 · integrations: the credential as a governed object ─────────────── */

/** One user grant, as the API returns it — token fields are DROPPED server-side
 *  (`Connection.to_safe_dict`), so this type cannot even name them. */
export interface IntegrationConnection {
  id: string;
  provider: string;
  user_id: string;
  scopes: string;
  account: string;
  token_type: string;
  expires_at: string | null;
  status: "active" | "needs_reconnect" | "revoked";
  created_at: string;
  updated_at: string;
}

export interface IntegrationProvider {
  id: string;
  name: string;
  category: string;
  blurb: string;
  /** The org registered an OAuth client — flips the card from Set up to Connect. */
  configured: boolean;
  /** The stored OAuth client id, echoed back so the Set-up form can EDIT rather than
   *  ask again. Not a secret: it travels in the browser's own address bar during the
   *  dance. Empty when the provider was never set up. */
  client_id: string;
  /** A masked preview of the stored secret ("abcd••••••"), or "". Enough to say one
   *  exists; never enough to read it. */
  secret_preview: string;
  /** The authored callback, when one was set; "" means the derived one applies. */
  redirect_uri: string;
  console_url: string;
  /** Whether the OAuth dance can complete on THIS deployment: false when the provider
   *  refuses `http://` and the callback this API would send is one. The card then routes
   *  to `alt_door` instead of offering a button that cannot work here. */
  oauth_ready: boolean;
  /** A door needing no public callback — `"slack_app"` is Slack's app + Socket Mode,
   *  which a laptop can complete. `""` when OAuth is the only way in. */
  alt_door: string;
  /** This provider REFUSES an `http://` redirect URL, localhost included — Slack says
   *  so in its own docs, Google and Microsoft accept the loopback address. The Set-up
   *  form uses it to warn BEFORE the credentials are pasted, instead of after the
   *  provider's error page. */
  https_only: boolean;
  connection: IntegrationConnection | null;
}

export async function getIntegrationsCatalog(): Promise<{
  providers: IntegrationProvider[]; redirect_uri: string;
}> {
  const res = await fetch(`${getApiBase()}/integrations/catalog`);
  if (!res.ok) throw new Error(`Failed to load the catalog (${res.status})`);
  return res.json();
}

export async function setupIntegrationApp(provider: string, body: {
  client_id: string;
  /** Blank on an update = keep the stored secret. It is encrypted at rest and masked on
   *  every read, so requiring it back would force a rotation to fix a typo elsewhere. */
  client_secret: string;
  /** Blank = derive the callback from the request, as every deployment did before this
   *  field existed. Set it when the API is REGISTERED at an address it is not currently
   *  being reached at — the case every local Slack setup lands in. */
  redirect_uri?: string;
}): Promise<{ redirect_uri: string }> {
  const res = await fetch(`${getApiBase()}/integrations/${provider}/app`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = ""; try { detail = (await res.json())?.detail ?? ""; } catch { /* non-JSON */ }
    throw new Error(detail || `Could not save the app (${res.status})`);
  }
  return res.json();
}

/** Begin the dance. The caller sends the BROWSER to `authorize_url` — a fetch cannot
 *  follow a consent screen. */
export async function beginIntegrationConnect(provider: string): Promise<string> {
  const res = await fetch(`${getApiBase()}/integrations/${provider}/connect`, { method: "POST" });
  if (!res.ok) {
    let detail = ""; try { detail = (await res.json())?.detail ?? ""; } catch { /* non-JSON */ }
    throw new Error(detail || `Could not start the connection (${res.status})`);
  }
  return (await res.json()).authorize_url;
}

export async function revokeIntegrationConnection(connId: string): Promise<{
  connection: IntegrationConnection;
  /** False ⇒ the provider offers no revocation endpoint (Microsoft): the grant must
   *  also be removed on the account's own security page, and the UI must say so. */
  provider_side: boolean;
}> {
  const res = await fetch(`${getApiBase()}/integrations/connections/${connId}/revoke`,
    { method: "POST" });
  if (!res.ok) throw new Error(`Could not revoke (${res.status})`);
  return res.json();
}

/** The Slack app manifest to paste at api.slack.com, plus the steps that follow it.
 *
 *  Rendered by the SERVER, never assembled here: the scopes and socket-mode settings have
 *  to match what the running bot actually does, and a manifest a client re-types from a
 *  README drifts from the code the first time either changes. */
export interface SlackManifest {
  manifest: Record<string, unknown>;
  instructions: string[];
}

export async function getSlackBotManifest(params: {
  name?: string; description?: string; agentId?: string; agentView?: boolean;
}): Promise<SlackManifest> {
  const qs = new URLSearchParams();
  if (params.name) qs.set("name", params.name);
  if (params.description) qs.set("description", params.description);
  if (params.agentId) qs.set("agent_id", params.agentId);
  if (params.agentView) qs.set("agent_view", "true");
  const res = await fetch(`${getApiBase()}/slack-bots/manifest?${qs.toString()}`);
  if (!res.ok) throw new Error(`Could not render the manifest (${res.status})`);
  return res.json();
}

/** Create a bot record. The server VERIFIES every credential against Slack before the
 *  record exists — a bot stored with a bad token is a socket that fails to open at 03:00
 *  with nobody watching — so a rejection here is Slack's answer, not a local guess. */
export async function createSlackBot(body: {
  name: string; agent_id?: string; connection_id?: string;
  bot_token: string; app_token: string; signing_secret: string; agent_view?: boolean;
}): Promise<SlackBotSummary> {
  const res = await fetch(`${getApiBase()}/slack-bots`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    // The server's own reason, verbatim — "invalid_auth" and "missing credential(s)" call
    // for different fixes and a generic message would hide which one happened.
    let detail = "";
    try { detail = (await res.json())?.detail ?? ""; } catch { /* non-JSON body */ }
    throw new Error(detail || `Could not create the Slack bot (${res.status})`);
  }
  return res.json();
}

/** The bots an automation may post AS. Returns [] when the plane is off (404), so a
 *  caller renders "no bots yet" rather than throwing — the same shape `getAutomations`
 *  uses for the same reason. */
/** The supervisor's key, minted server-side and returned ONCE. Every later read is a
 *  status, never a disclosure — a lost key is re-issued, not recovered. */
export async function issueSupervisorKey(): Promise<{
  key: string; env_line: string; issued_at: string;
}> {
  const res = await fetch(`${getApiBase()}/slack-bots/supervisor-key`, { method: "POST" });
  if (!res.ok) throw new Error(`Could not issue a supervisor key (${res.status})`);
  return res.json();
}

export async function getSupervisorKeyStatus(): Promise<{
  issued: boolean; issued_at: string;
}> {
  const res = await fetch(`${getApiBase()}/slack-bots/supervisor-key`);
  if (!res.ok) return { issued: false, issued_at: "" };
  return res.json();
}

export async function getSlackBots(): Promise<SlackBotSummary[]> {
  const res = await fetch(`${getApiBase()}/slack-bots`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error("Failed to fetch Slack bots");
  return (await res.json()).bots ?? [];
}

export interface AutoCondition { kind: ConditionKind; config: Record<string, unknown>; }

/** W1 — one comparison in a step's guard. Either side may be a literal or a
 *  `{"$from": "step1.answer"}` binding, resolved against the same chain context the
 *  step's params are. The operators are FETCHED (`getAutomationVocabulary`), never
 *  listed here: a picker offering an operator the engine cannot evaluate fails at
 *  09:00, on a schedule, with nobody watching. */
export interface GuardClause {
  left: unknown;
  op: string;
  right?: unknown;
}

export interface AutoEffect {
  kind: EffectKind;
  /** VA-4a — this step's name, which `{"$from": "<alias>.<key>"}` bindings point AT.
   *  Optional because the server defaults it to the step's 1-based position, and every
   *  automation written before VA-4a has none. Declared here because a client that
   *  cannot see the field is a client that drops it on save. */
  alias?: string;
  /** W1 — run this step ONLY IF the guard holds. Empty/absent = always, which is every
   *  automation written before W1.
   *
   *  Declared for the reason `alias` above is, which this repo has already paid for
   *  once: the authoring form rebuilt each effect as `{kind, config}` and silently
   *  dropped the field it could not see, unwiring the chain it had just saved. Spread,
   *  never rebuild.
   *
   *  Called **"Only if" on every surface** — the trigger node is already labelled
   *  "When" on the canvas, and two Whens in one picture is a collision a reader pays
   *  for. `when` is the wire's word; the boundary is where it is translated. */
  when?: GuardClause[];
  when_logic?: "all" | "any";
  /** W2 — run this step once per item of a list instead of exactly once. Absent = the
   *  single dispatch every automation written before W2 performs.
   *
   *  `source` is a literal list or a `{"$from": "step1.rows"}` binding, and each
   *  iteration publishes its item under the reserved alias `item` — a dict item read
   *  field-wise (`{"$from": "item.channel"}`), a scalar as `{"$from": "item.value"}`.
   *
   *  Called **"For each" on every surface**, which is also the wire's word. */
  for_each?: { source: unknown } | null;
  /** DS-6 — the route: run this step exactly when the named step's "Only if" was
   *  evaluated and did NOT hold. Empty/absent = unrouted, which is every automation
   *  written before DS-6. Declared for the reason `alias` above is: a client that
   *  cannot see the field drops it on save.
   *
   *  Called **"Otherwise" on every surface**; `else_of` is the wire's word. */
  else_of?: string;
  config: Record<string, unknown>;
}

export interface Automation {
  id: string;
  conn_id: string;
  name: string;
  description: string;
  conditions: AutoCondition[];
  condition_logic: "all" | "any";
  effects: AutoEffect[];
  fallback_effect: AutoEffect | null;
  enabled: boolean;
  paused_until: string | null;
  expires_at: string | null;
  max_retries: number;
  retry_backoff_seconds: number;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  last_status: string | null;
  /** VA-9b — the agent this whole chain RUNS AS ("" = nobody in particular). On the wire
   *  since VA-9b; undeclared here until DS-5 needed to ask which chains an agent
   *  operates. A per-STEP delegation lives on the effect's own config instead. */
  agent_id: string;
  /** DS-7 — how the steps are scheduled: `ordered` (the sequential walk, the default)
   *  or `parallel` (steps run as their arrows allow). */
  scheduling: "ordered" | "parallel";
}

export interface EffectOutcome {
  kind: string;
  target: string;
  status: string;      // executed | failed | skipped | criterion_failed | approval_required | invalid_params | dispatch_error
  message: string;
  attempts: number;
}

export interface AutomationRun {
  id: string;
  automation_id: string;
  automation_name: string;
  conn_id: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  // DS-8 — `paused` is the one NON-TERMINAL outcome: the run reached a governed write that
  // needs a human and stopped mid-chain. It ends when its proposal resolves, in this same
  // row. Readers that branch on "did it work" must not fold it in with `error`.
  outcome: "fired" | "not_fired" | "gated" | "error" | "paused";
  reason: string;
  conditions_fired: string[];
  effects: EffectOutcome[];
  fallback_used: boolean;
  error: string;
  /** DS-8 — engine-internal resume state. Present only while `outcome === "paused"`. */
  checkpoint?: Record<string, unknown>;
}

export type NewAutomation = {
  conn_id: string;
  name: string;
  description?: string;
  conditions: AutoCondition[];
  condition_logic?: "all" | "any";
  effects: AutoEffect[];
  fallback_effect?: AutoEffect | null;
  enabled?: boolean;
  paused_until?: string | null;
  expires_at?: string | null;
  max_retries?: number;
  retry_backoff_seconds?: number;
  /** DS-7 — `ordered` (default: the sequential walk) or `parallel` (steps run as
   *  their arrows allow). An authored field: every update payload must carry it, or
   *  a rename silently re-serialises a parallel chain. */
  scheduling?: "ordered" | "parallel";
};

/** List automations. Returns [] when the plane is off (404) so a caller can render the
 *  "not enabled" empty state instead of throwing. */
export async function getAutomations(connId?: string): Promise<Automation[]> {
  const qs = connId ? `?conn_id=${encodeURIComponent(connId)}` : "";
  const res = await fetch(`${getApiBase()}/automations${qs}`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error("Failed to fetch automations");
  return (await res.json()).automations;
}

export async function createAutomation(data: NewAutomation): Promise<Automation> {
  const res = await fetch(`${getApiBase()}/automations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ? "Invalid automation" : "Failed to create automation");
  return res.json();
}

export async function updateAutomation(id: string, data: NewAutomation): Promise<Automation> {
  const res = await fetch(`${getApiBase()}/automations/${id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update automation");
  return res.json();
}

export async function deleteAutomation(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/automations/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete automation");
}

export async function setAutomationEnabled(id: string, enabled: boolean): Promise<Automation> {
  const res = await fetch(`${getApiBase()}/automations/${id}/enabled?enabled=${enabled}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to toggle automation");
  return res.json();
}

export async function pauseAutomation(id: string, until: string | null): Promise<Automation> {
  const res = await fetch(`${getApiBase()}/automations/${id}/pause`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ until }),
  });
  if (!res.ok) throw new Error("Failed to pause automation");
  return res.json();
}

/** Run an automation now — through the same gates the heartbeat uses, so a gated automation
 *  returns the REASON it did nothing rather than silence. */
/** Run one automation now.
 *
 *  `runId` is DS-3's whole hinge: this request does not resolve until the chain has
 *  finished, but every step writes a span under `trace_id == run_id` while it runs — so a
 *  surface that wants to WATCH a run has to name it before asking for it. Omitted, the
 *  engine mints one exactly as before. */
export async function runAutomation(id: string, runId?: string): Promise<AutomationRun> {
  const res = await fetch(`${getApiBase()}/automations/${id}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId ?? null }),
  });
  if (!res.ok) throw new Error("Failed to run automation");
  return res.json();
}

export async function getAutomationRuns(id: string, limit = 50): Promise<AutomationRun[]> {
  const res = await fetch(`${getApiBase()}/automations/${id}/runs?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return (await res.json()).runs;
}

/** VA-4b — the automation as a graph. `run: "latest"` asks for Execution mode. */
export interface AutomationGraphNode {
  id: string; type: string; kind?: string; label: string; detail?: string;
  status?: string; message?: string; produced?: string[];
  agent_id?: string; delegated?: boolean;
  duration_ms?: number; attempts?: number; investigation_id?: string;
  fired?: string[]; at?: string;
  /** W1 — the step's guard, already rendered as sentences by the server (paths and
   *  authored literals only, never a value it read). Present on the STRUCTURE graph
   *  too: whether a step will run at all is a design fact. */
  when?: string[]; when_logic?: string;
  /** W1 — this `skipped` step was held by its own GUARD, not by missing upstream data.
   *  Same status, opposite meanings: one is the design working, the other is something
   *  breaking. */
  guarded?: boolean;
  /** DS-6 — the step whose "Only if" this one runs OTHERWISE of. A design fact like
   *  `when` above: an arm drawn without it reads as a step that always fires. */
  else_of?: string;
  /** DS-6 — this `skipped` step is a route's untaken arm: the design working, one
   *  branch over. Distinct from `guarded` (its own guard) and from a bare skip
   *  (missing upstream). */
  not_taken?: boolean;
}

export interface AutomationRunSummary {
  id: string; outcome: string; at: string;
  duration_ms: number; steps: number; failed: number;
}
export interface AutomationGraphEdge {
  from: string; to: string; type: string; label?: string;
  /** W1 — this data edge feeds a GUARD: it decides whether the step runs, rather than
   *  filling one of its fields. */
  guard?: boolean;
}
export interface AutomationGraphData {
  nodes: AutomationGraphNode[]; edges: AutomationGraphEdge[];
  mode: string; name?: string; run_missing?: boolean;
  run_outcome?: string; run_reason?: string; run_at?: string;
  agent_id?: string; runs?: AutomationRunSummary[]; run_id?: string;
  /** B2 — this graph is a PREVIEW: nothing in it happened. */
  dry_run?: boolean;
  /** DS-7 — how this automation schedules its steps, so the canvas can say it. */
  scheduling?: string;
}

/** B2 — what this design WOULD do, dispatching nothing.
 *
 *  Returns the run AND the graph, because a dry run is never stored: there is no id for
 *  `getAutomationGraph` to look up afterwards. The graph is the same shape an execution
 *  view already renders, which is the whole reason a preview returns an `AutomationRun`
 *  rather than a report of its own. */
export interface AutomationDryRun {
  run: AutomationRun;
  graph: AutomationGraphData;
}

/** Preview a DRAFT — the unsaved one in the editor. The payload is `updatePayload`'s, so
 *  a preview previews exactly what Save would send, never a second assembly of it. */
/** `until` (DS-2) stops the walk after that step — the question a person actually has
 *  while building is "what does the step I am looking at receive", and a whole-chain
 *  preview buries that answer among the others. Omitted, it is B2's whole-chain walk. */
export async function dryRunAutomationDraft(
  body: NewAutomation, until?: string,
): Promise<AutomationDryRun> {
  const qs = until ? `?until=${encodeURIComponent(until)}` : "";
  const res = await fetch(`${getApiBase()}/automations/dry-run${qs}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const parsed = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(parsed?.detail || `Dry run failed (${res.status})`);
  return parsed;
}

/** Preview a STORED automation, exactly as it sits. */
export async function dryRunAutomation(id: string): Promise<AutomationDryRun> {
  const res = await fetch(`${getApiBase()}/automations/${id}/dry-run`, { method: "POST" });
  const parsed = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(parsed?.detail || `Dry run failed (${res.status})`);
  return parsed;
}

export async function getAutomationGraph(id: string, run = ""): Promise<AutomationGraphData> {
  const qs = run ? `?run=${encodeURIComponent(run)}` : "";
  const res = await fetch(`${getApiBase()}/automations/${id}/graph${qs}`);
  if (!res.ok) throw new Error("Failed to fetch the automation graph");
  return await res.json();
}

// ── Proposal inbox + standing grants (Wave A4) ───────────────────────────────────

export interface StagedProposal {
  id: string;
  connection_id: string;
  schema_name: string;
  action_id: string;
  params: Record<string, unknown>;
  reasoning: string;
  proposer: string;
  source: string;
  status: "pending" | "accepted" | "rejected" | "executed" | "failed" | "approval_required";
  status_message: string;
  outcome: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string;
}

export interface StandingGrant {
  id: string;
  connection_id: string;
  action_id: string;
  target_arg: string;
  target_value: string;
  owner_kind: string;
  owner_id: string;
  created_by: string;
  created_at: string;
  use_count: number;
  last_used_at: string | null;
}

/** Staged proposals for a connection. [] when the inbox is off (404). */
export async function getProposals(connId: string, status?: string): Promise<StagedProposal[]> {
  const qs = new URLSearchParams({ connection_id: connId });
  if (status) qs.set("status", status);
  const res = await fetch(`${getApiBase()}/kinetic-actions/inbox?${qs}`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error("Failed to fetch proposals");
  return (await res.json()).proposals;
}

export type AcceptResult = { status: string; action_id: string; outcome: Record<string, unknown>; granted_by: string; minted_grant: string };

/** Accept a proposal → executes it exactly once (the accept is the approval). `mintGrant`
 *  also mints a target-bound standing grant for future unattended runs. Returns the outcome;
 *  a 409 (already resolved) or 422 (criterion failed) surfaces as a thrown Error with the body. */
export async function acceptProposal(id: string, actor: string, mintGrant = false): Promise<AcceptResult> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/inbox/${id}/accept`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor, mint_grant: mintGrant }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail?.message || body?.detail || `accept failed (${res.status})`);
  return body;
}

export async function rejectProposal(id: string, actor: string): Promise<boolean> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/inbox/${id}/reject`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor }),
  });
  if (!res.ok) throw new Error("Failed to reject proposal");
  return (await res.json()).rejected;
}

export async function getGrants(connId: string): Promise<StandingGrant[]> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/grants?connection_id=${encodeURIComponent(connId)}`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error("Failed to fetch grants");
  return (await res.json()).grants;
}

export async function revokeGrant(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/grants/${id}/revoke`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to revoke grant");
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
  const res = await fetch(`${getApiBase()}/actions/triggers`);
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
  const res = await fetch(`${getApiBase()}/actions/triggers/${encodeURIComponent(triggerId)}/send`, {
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
  const res = await fetch(`${getApiBase()}/briefing/subscriptions${qs}`);
  if (!res.ok) throw new Error("Failed to fetch brief subscriptions");
  const data = await res.json();
  return data.subscriptions ?? [];
}

export async function createBriefSubscription(
  body: { conn_id: string; name: string; trigger_id: string; period?: "week" | "day"; send_cron?: string; enabled?: boolean },
): Promise<BriefSubscription> {
  const res = await fetch(`${getApiBase()}/briefing/subscriptions`, {
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
  const res = await fetch(`${getApiBase()}/briefing/subscriptions/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update brief subscription");
  return res.json();
}

export async function deleteBriefSubscription(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/briefing/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" });
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
  const res = await fetch(`${getApiBase()}/briefing/subscriptions/${encodeURIComponent(id)}/test`, { method: "POST" });
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
  const res = await fetch(`${getApiBase()}/org-intelligence${qs.size ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error("Failed to fetch org intelligence");
  return res.json();
}

export async function deleteOrgInsight(id: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/org-intelligence/${encodeURIComponent(id)}`, { method: "DELETE" });
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
  /** AT-6 — quantities the table implies but does not store: the subtraction behind a 0/1
   *  flag, the span between two timestamps, the product of a price and a count. Each note
   *  already carries the support and the row count it was measured on. */
  derived_quantities?: string[] | null;
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
  /** AT-4 — what the column IS, agreed by witnesses from two or more evidence layers.
   *  Separate from `semantic_type` (how to HANDLE it) and empty far more often, which is
   *  the point. Below 0.5 the concept is a HINT — one witness — and must not be shown as a
   *  finding; `conceptIfConfident` is the only read. */
  concept?: string | null;
  concept_confidence?: number | null;
  /** One sentence per agreeing layer, each carrying the numbers it agreed on. */
  concept_evidence?: string[] | null;
  unit?: string | null;
  value_interpretation?: string | null;
}

/** The one honest read of a concept — mirrors `aughor.tools.concept.concept_of`.
 *  Reading `.concept` without its confidence is the "one witness spoke and the system
 *  believed it" failure the whole contract exists to prevent, one level up at the UI. */
export function conceptIfConfident(col: ColumnProfileData): string {
  const c = (col.concept ?? "").trim();
  const conf = col.concept_confidence ?? 0;
  return c && conf >= 0.5 ? c : "";
}

export interface SchemaProfile {
  available: boolean;
  tables: TableProfileData[];
  columns: ColumnProfileData[];
}

export async function getSchemaProfile(connectionId: string): Promise<SchemaProfile> {
  const res = await fetch(`${getApiBase()}/connections/${encodeURIComponent(connectionId)}/schema/profile`);
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
  const url = `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/patterns${qs}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch patterns");
  return res.json();
}

/** Patterns scoped to a Canvas's curated tables (Hub scope consistency). */
export async function getCanvasPatterns(canvasId: string, refresh = false): Promise<PatternsResponse> {
  const qs = refresh ? "?refresh=true" : "";
  const res = await fetch(`${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/patterns${qs}`);
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
  /** How many findings the gate held back for THIS reason (grouped server-side by
   *  (severity, reason) — a reason derives from the SQL idiom, so one bad idiom suppresses
   *  many findings identically). Absent on pre-grouping cached briefs → treat as 1. */
  count?: number;
  /** The domains this reason hit (grouped). */
  domains?: string[];
}

export interface BriefingNarrativeResponse {
  narrative: string;
  headline_theme: string;
  citations: BriefingCitation[];
  held_back?: HeldBackSignal[];
  currency_code?: string;
  generated_at: string | null;
  available: boolean;
  /** The scope this brief was generated FOR (`conn:schema`, or `canvas:<id>`). The client
   *  MUST refuse to paint a narrative whose scope_key ≠ the scope it is rendering under —
   *  otherwise a retained brief from a previous schema is undetectable. Absent on briefs
   *  cached before this field existed → the client falls back to not trusting them. */
  scope_key?: string;
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
  const url = `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/briefing${qs}`;
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
  const url = `${getApiBase()}/exploration/canvas/${encodeURIComponent(canvasId)}/briefing${qs}`;
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
  return `${getApiBase()}/investigations/${encodeURIComponent(invId)}/export?${q.toString()}`;
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
  cost: "free" | "per_token" | "flat" | "unknown";   // "free" = the `:free` tier marker
}

export interface LlmConfig {
  backend: string;
  models: Record<string, string>;          // effective coder/narrator/fast
  base_urls: Record<string, string>;       // effective ollama/lmstudio
  keys_set: Record<string, boolean>;        // groq/together/anthropic — USABLE or not (never the value)
  keys_state?: Record<string, "set" | "unset" | "unreadable">;  // "unreadable" = stored, undecryptable
  capabilities: Record<string, LlmCapability>;  // per-role vended profile (§5b)
  models_set: Record<string, string>;       // explicit overrides on disk
  base_urls_set: Record<string, string>;
  backends: string[];
  needs_key: string[];
  local_backends: string[];
  default_models: Record<string, Record<string, string>>;
  /** What the operator bound for each backend they have configured. Restored when the
   *  provider is switched, so a previous choice is not retyped; the fallback chain
   *  dispatches with the same values. Absent on a config written before this shipped. */
  models_by_backend?: Record<string, Record<string, string>>;
  /** Where calls go when the primary fails. `backend` is "" for the built-in order,
   *  "none" for no fallback, else the one chosen link; `chain` is what will actually be
   *  tried (an env pin outranks the choice); `active` is true when the primary is spent
   *  and runs are landing on the fallback right now. */
  fallback?: {
    backend: string; model: string; chain: string[]; active: boolean;
    /** AUGHOR_FALLBACK_BACKENDS is set and outranks the Settings choice. */
    env_pinned: boolean;
  };
}

export interface LlmConfigPatch {
  backend?: string;
  models?: Record<string, string>;
  base_urls?: Record<string, string>;
  keys?: Record<string, string>;
  /** {backend?, model?} — "" = built-in order, "none" = no fallback, else one backend. */
  fallback?: { backend?: string; model?: string };
  /** Free-by-default: required to bind a non-`:free` OpenRouter model. */
  allow_paid?: boolean;
}

export async function getLlmConfig(): Promise<LlmConfig> {
  const res = await fetch(`${getApiBase()}/llm/config`);
  if (!res.ok) throw new Error("Failed to load inference config");
  return res.json();
}

export interface LlmModelEntry {
  id: string;
  /** where it came from: the backend itself, our curated floor, or the user */
  source: "live" | "known" | "custom";
  label?: string;
  context?: number;
  free?: boolean;
}

export interface LlmModelCatalog {
  backend: string;
  models: LlmModelEntry[];
  custom: string[];
  live: boolean;
  live_count: number;
  /** why the live fetch failed, when it did — shown rather than hidden, so a
   *  stale fallback is never presented as though it were authoritative */
  error: string;
  defaults: Record<string, string>;
}

export async function getLlmModels(backend?: string, refresh = false): Promise<LlmModelCatalog> {
  const q = new URLSearchParams();
  if (backend) q.set("backend", backend);
  if (refresh) q.set("refresh", "true");
  const res = await fetch(`${getApiBase()}/llm/models?${q}`);
  if (!res.ok) throw new Error("Failed to load model catalogue");
  return res.json();
}

export async function addLlmModel(backend: string, model: string): Promise<{ backend: string; custom: string[] }> {
  const res = await fetch(`${getApiBase()}/llm/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, model }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Failed to add model");
  }
  return res.json();
}

export async function removeLlmModel(backend: string, model: string): Promise<{ backend: string; custom: string[] }> {
  const q = new URLSearchParams({ backend, model });
  const res = await fetch(`${getApiBase()}/llm/models?${q}`, { method: "DELETE" });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error((e as { detail?: string }).detail ?? "Failed to remove model");
  }
  return res.json();
}

export async function setLlmConfig(patch: LlmConfigPatch): Promise<LlmConfig> {
  const res = await fetch(`${getApiBase()}/llm/config`, {
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

export interface LlmTestResult {
  model: string;
  ok: boolean;
  ms?: number;
  error?: string;
  /** which roles / agents are bound to this model */
  used_by: string[];
}

export interface LlmTestReport {
  ok: boolean;
  backend: string;
  model?: string;          // the coder model — the headline
  error?: string;          // the first failure, if any
  results?: LlmTestResult[];
  tested?: number;
  failed?: number;
}

/** Test every DISTINCT model the deployment would use — all three role bindings,
 *  plus per-agent pins with `includeAgents`. Pass `model` to test just one. */
export async function testLlmConfig(
  backend?: string, model?: string, includeAgents = false,
): Promise<LlmTestReport> {
  const res = await fetch(`${getApiBase()}/llm/config/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, model, include_agents: includeAgents }),
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
  const res = await fetch(`${getApiBase()}/llm/config/cache-probe`, {
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/status${q}`);
  if (!res.ok) throw new Error("Failed to fetch explorer status");
  return res.json();
}

export async function startExplorer(connectionId: string, schema?: string): Promise<{ ok: boolean; reason?: string }> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/start${q}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to start explorer");
  return res.json();
}

export async function stopExplorer(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to stop explorer");
  return res.json();
}

export async function restartExplorer(connectionId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/restart`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to restart explorer");
  return res.json();
}

export async function resetExplorer(connectionId: string): Promise<{ ok: boolean; reset: boolean }> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/reset`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to reset explorer");
  return res.json();
}

export async function triggerDomainIntelligence(connectionId: string): Promise<{
  ok: boolean;
  reason?: string;
  /** Per-schema fan-out outcomes — a multi-schema connection reports one row per schema,
   *  and a refused schema carries its reason here (the top-level `ok` is any-schema-ok). */
  results?: { schema?: string | null; ok: boolean; reason?: string }[];
}> {
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/trigger-intel`, { method: "POST" });
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
  const res = await fetch(`${getApiBase()}/dev/stats`);
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
  const res = await fetch(`${getApiBase()}/security/audit/stats?${params}`);
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
  const res = await fetch(`${getApiBase()}/jobs${q.toString() ? `?${q}` : ""}`);
  if (!res.ok) return [];
  return res.json();
}

export async function getJobLogs(jobId: string): Promise<{ seq: number; at: string; kind: string; payload: unknown }[]> {
  const res = await fetch(`${getApiBase()}/jobs/${encodeURIComponent(jobId)}/logs`);
  if (!res.ok) return [];
  return res.json();
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; cancelled: boolean }> {
  const res = await fetch(`${getApiBase()}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
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
  backend?: string;
}

export async function getAgents(workspaceId?: string): Promise<AgentRosterEntry[]> {
  const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await fetch(`${getApiBase()}/agents${q}`);
  if (!res.ok) return [];
  return res.json();
}

export async function patchAgent(
  agentId: string,
  body: { enabled?: boolean; token_budget?: number; time_budget_s?: number; model?: string; workspace_id?: string; allow_paid?: boolean },
): Promise<{ agent_id: string; governance: AgentGovernance } | null> {
  const res = await fetch(`${getApiBase()}/agents/${encodeURIComponent(agentId)}`, {
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
    `${getApiBase()}/exploration/${encodeURIComponent(connId)}/findings/${encodeURIComponent(insightId)}/revalidate`,
    { method: "POST" },
  );
  if (!res.ok) return { status: "error", error: `HTTP ${res.status}` };
  return res.json();
}

/** K3 Trust Receipt — provenance for a finding (404 if it predates tracking). */
export async function getInsightReceipt(connId: string, insightId: string): Promise<InsightReceipt | null> {
  const res = await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connId)}/findings/${encodeURIComponent(insightId)}/receipt`,
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
  const res = await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connId)}/briefing/ground`, {
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

/** K3-wide Trust Receipt for a chat or deep-analysis answer (404 if it predates receipts).
 *  `kind` is a ROUTE SEGMENT — the `/ada/` path is a wire name, frozen. */
export async function getAnswerReceipt(kind: "chat" | "ada", connId: string, id: string): Promise<InsightReceipt | null> {
  const res = await fetch(
    `${getApiBase()}/${kind}/${encodeURIComponent(connId)}/${encodeURIComponent(id)}/receipt`,
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
  /** Wave H2 — the user-defined persona this answer ran as, or null when unbound. */
  agent: { id: string; name: string } | null;
  /** Ambiguities this connection settled earlier that this answer applied (I6). */
  resolved_readings: { reading: string; note: string }[];
  /** What the closed loop learned on this run (Wave 1·E4), or null when it ran nothing. */
  learning: LearningReceiptPayload | null;
  /** Self-gating capabilities whose trigger fired this run (Wave 1·E3). */
  activations: { capability: string; reason: string; count: number }[];
  /** Wave P1 — ids of the graph nodes the planner was shown before writing the SQL.
   *  Ids only, and signed: the labels/warrants resolve live via `getAnswerTrace`. */
  grounded_in_graph: string[];
  cost: Record<string, number | string> | null;
  signature: string;                     // HMAC — server-issued proof
}

/** Resolve any answer's receipt id into the one signed public contract. 404 → null. */
export async function getPublicReceipt(receiptId: string): Promise<PublicReceipt | null> {
  const res = await fetch(`${getApiBase()}/receipt/${encodeURIComponent(receiptId)}`);
  if (!res.ok) return null;
  return res.json();
}

// ── The answer trace (Wave P1 — GET /receipt/{id}/trace) ──────────────────────

export interface TracedNode {
  id: string;
  kind: string;
  label: string;
  summary: string;
  reason: "cited" | "read" | "metric" | "finding";
  why: string;
  /** False ⇒ the answer named it, but the graph does not (or no longer does) hold it. */
  present: boolean;
  warrant: CGWarrant | null;
}
export interface TracedEdge {
  id: string; kind: string; from_id: string; to_id: string;
  label: string; warrant: CGWarrant | null;
}
export interface AnswerTrace {
  receipt_id: string;
  available: boolean;
  reason?: string;
  connection_id?: string;
  graph_version?: number;
  nodes: TracedNode[];
  edges: TracedEdge[];
  counts?: { nodes: number; edges: number; unresolved: number };
  has_unresolved?: boolean;
}

/** The knowledge-graph subgraph one answer stands on. A separate call from the receipt:
 *  the receipt is signed and immutable, the trace resolves against the live graph. */
export async function getAnswerTrace(receiptId: string): Promise<AnswerTrace | null> {
  const res = await fetch(`${getApiBase()}/receipt/${encodeURIComponent(receiptId)}/trace`);
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
  const res = await fetch(`${getApiBase()}/metastore/catalogs/${encodeURIComponent(catalogId)}/volumes`);
  if (!res.ok) throw new Error("Failed to list volumes");
  return (await res.json()).volumes ?? [];
}

export async function createVolume(catalogId: string, name: string): Promise<MetastoreVolume> {
  const res = await fetch(`${getApiBase()}/metastore/catalogs/${encodeURIComponent(catalogId)}/volumes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Failed to create volume"); }
  return res.json();
}

export async function listVolumeObjects(volumeId: string): Promise<MetastoreVolumeObject[]> {
  const res = await fetch(`${getApiBase()}/metastore/volumes/${encodeURIComponent(volumeId)}/objects`);
  if (!res.ok) throw new Error("Failed to list objects");
  return (await res.json()).objects ?? [];
}

export async function uploadVolumeObject(volumeId: string, file: File): Promise<MetastoreVolumeObject> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${getApiBase()}/metastore/volumes/${encodeURIComponent(volumeId)}/objects`, { method: "POST", body: form });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Upload failed"); }
  return res.json();
}

export function volumeObjectContentUrl(volumeId: string, objectId: string): string {
  return `${getApiBase()}/metastore/volumes/${encodeURIComponent(volumeId)}/objects/${encodeURIComponent(objectId)}/content`;
}

export async function deleteVolumeObject(volumeId: string, objectId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/metastore/volumes/${encodeURIComponent(volumeId)}/objects/${encodeURIComponent(objectId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete failed");
}

// ── Metastore: Grants (explicit catalog access for a workspace) ─────────────────

export async function listWorkspaceGrants(workspaceId: string): Promise<string[]> {
  const res = await fetch(`${getApiBase()}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants`);
  if (!res.ok) throw new Error("Failed to list grants");
  return (await res.json()).catalogs ?? [];
}

export async function grantWorkspaceCatalog(workspaceId: string, catalogId: string): Promise<string[]> {
  const res = await fetch(`${getApiBase()}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ catalog_id: catalogId }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail ?? "Grant failed"); }
  return (await res.json()).catalogs ?? [];
}

export async function revokeWorkspaceCatalog(workspaceId: string, catalogId: string): Promise<string[]> {
  const res = await fetch(`${getApiBase()}/metastore/workspaces/${encodeURIComponent(workspaceId)}/grants/${encodeURIComponent(catalogId)}`, { method: "DELETE" });
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

/** Look up a table's glossary entry tolerantly, mirroring `semantic.glossary.lookup_table`.
 *  The store is keyed by whatever the connector's `TABLE:` header carried, so it holds BOTH
 *  bare and `schema.table` keys. Exact-first, then schema-tolerant: a qualified key only
 *  answers for its own schema, while a bare key answers for any (the pre-scoping fallback). */
export function lookupGlossaryTable(
  g: Glossary | null | undefined, table: string, schema?: string | null,
): GlossaryTable | undefined {
  const tables = g?.tables ?? {};
  const leaf = (n: string) => (n || "").split(".").pop()!.trim().replace(/"/g, "").toLowerCase();
  const schemaOf = (n: string) => {
    const parts = (n || "").split(".").map(x => x.trim().replace(/"/g, "")).filter(Boolean);
    return parts.length >= 2 ? parts[parts.length - 2].toLowerCase() : null;
  };
  const want = schema && !table.includes(".") ? `${schema}.${table}` : table;
  if (tables[want]) return tables[want];
  const wantLeaf = leaf(want), wantSchema = schemaOf(want);
  for (const [k, v] of Object.entries(tables)) {
    if (leaf(k) !== wantLeaf) continue;
    const ks = schemaOf(k);
    if (ks && wantSchema && ks !== wantSchema) continue;   // never cross schemas
    return v;
  }
  return undefined;
}

export async function getGlossary(): Promise<Glossary> {
  const res = await fetch(`${getApiBase()}/glossary`);
  if (!res.ok) return { tables: {} };
  return res.json();
}

/** Partial table-level glossary patch. Every field the agent reads at query time:
 *  description + grain + joins all flow into the schema context via apply_glossary(). */
export async function updateTableGlossary(
  table: string,
  patch: { description?: string; grain?: string; joins?: string[] },
  schema?: string | null,
): Promise<void> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${getApiBase()}/glossary/${encodeURIComponent(table)}${q}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to save table comment");
}

/** Partial column-level glossary patch (description + known values + caveats). */
export async function updateColumnGlossary(
  table: string,
  column: string,
  patch: { description?: string; values?: string; caveats?: string },
  schema?: string | null,
): Promise<void> {
  const q = schema ? `?schema=${encodeURIComponent(schema)}` : "";
  const res = await fetch(`${getApiBase()}/glossary/${encodeURIComponent(table)}/${encodeURIComponent(column)}${q}`, {
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
  const res = await fetch(`${getApiBase()}/playbook/${encodeURIComponent(entryId)}/versions`);
  if (!res.ok) return [];
  return res.json();
}

// ── Post-processing transforms (PoP / share / rolling / cumulative) ─────────────

export type PostprocOp = "pop" | "contribution" | "rolling" | "cumulative";

export async function applyPostproc(
  columns: string[], rows: unknown[][], op: PostprocOp, valueCol: string,
  window = 3, agg: "mean" | "sum" | "min" | "max" = "mean",
): Promise<{ columns: string[]; rows: unknown[][] }> {
  const res = await fetch(`${getApiBase()}/query/postproc`, {
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
  // "default" = the code default decided (no env var, no override) — distinguished from
  // "env" so a default-on flag never sends an operator hunting for a variable nobody set.
  source: "run" | "runtime" | "env" | "default";
  env_var: string;
  label: string;
  description: string;
  // Capabilities Auto-mode (Wave 1 · E3) — present on every flag:
  state?: CapabilityState;          // effective tri-state
  override?: boolean | null;        // the runtime override, or null when following env/Auto-mode
  /** Always false since flag endgame Wave 3 dissolved the Auto-mode tier. Retained
   *  for payload compatibility; nothing sets it true. */
  auto_eligible?: boolean;
  trigger?: string;                 // (auto-eligible only) the deterministic trigger, in words
  // The disposition ratchet (flag strategy §5.1) — every flag declares its kind, so the
  // Settings UI can group by it instead of rendering one flat toggle list:
  disposition?: string;             // default_on | auto | intentionally_off | experiment | …
  disposition_note?: string;        // the declared reason / exit for non-graduated kinds
}

export async function getSystemFlags(): Promise<Record<string, SystemFlag>> {
  const res = await fetch(`${getApiBase()}/system/flags`);
  if (!res.ok) return {};
  return res.json();
}

export async function setSystemFlag(name: string, value: boolean): Promise<SystemFlag | null> {
  const res = await fetch(`${getApiBase()}/system/flags/${encodeURIComponent(name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
  });
  if (!res.ok) return null;
  return res.json();
}
/** Set a capability's tri-state — "auto" clears the override so it follows the Auto-mode master. */
export async function setCapabilityState(name: string, state: CapabilityState): Promise<SystemFlag | null> {
  const res = await fetch(`${getApiBase()}/system/flags/${encodeURIComponent(name)}`, {
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
  const res = await fetch(`${getApiBase()}/rbac/me`);
  if (!res.ok) return null;
  return res.json();
}

/** The built-in role catalogue + the permissions each grants. */
export async function getRoleCatalogue(): Promise<RoleInfo[]> {
  const res = await fetch(`${getApiBase()}/rbac/roles`);
  if (!res.ok) return [];
  return res.json();
}

/** The org's role roster. Returns null when the caller can't manage roles (403). */
export async function getRoleAssignments(): Promise<RoleAssignment[] | null> {
  const res = await fetch(`${getApiBase()}/rbac/assignments`);
  if (res.status === 403) return null;
  if (!res.ok) return [];
  return res.json();
}

export async function assignRole(userId: string, role: string): Promise<RoleAssignment | null> {
  const res = await fetch(`${getApiBase()}/rbac/assignments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, role }),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function revokeRole(userId: string, role: string): Promise<boolean> {
  const q = `user_id=${encodeURIComponent(userId)}&role=${encodeURIComponent(role)}`;
  const res = await fetch(`${getApiBase()}/rbac/assignments?${q}`, { method: "DELETE" });
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
  /** Which connections this pack is for: `*`, `engine:<type>`, or a connection id.
   *  Half the reason a pack is or is not in play — status alone is the other half. */
  scope?: string[];
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
  const res = await fetch(`${getApiBase()}/packs`);
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
  const res = await fetch(`${getApiBase()}/packs/${encodeURIComponent(packId)}/propose-bindings`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_id: connectionId, schema, business_model: businessModel }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "propose failed");
  return res.json();
}

export async function bindPack(
  packId: string, connectionId: string, bindings: Record<string, unknown>, schema?: string, version = 1,
): Promise<{ verified: boolean; missing?: string[]; dry_run_errors?: string[] }> {
  const res = await fetch(`${getApiBase()}/packs/${encodeURIComponent(packId)}/bind`, {
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
  const res = await fetch(`${getApiBase()}/packs/${encodeURIComponent(packId)}/evaluate`, {
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
  const res = await fetch(`${getApiBase()}/packs/${encodeURIComponent(packId)}/deltas?status=${status}`);
  if (!res.ok) return [];
  return res.json();
}

export async function setPackDeltaStatus(deltaId: number, status: "accepted" | "dismissed"): Promise<boolean> {
  const res = await fetch(`${getApiBase()}/packs/deltas/${deltaId}/status`, {
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
  /** Fingerprint of the fields that decide how this agent answers (Wave H6). */
  config_rev: string;
  /** Whether `last_eval` is about the agent as it is configured now. */
  eval_basis: EvalBasis;
  created_at: string;
  updated_at: string;
}

export interface AgentRevision {
  version: number;
  at: string;
  config_rev: string;
  author: string;
  name: string;
  config: Record<string, unknown>;
  /** Governing fields this revision moved, in declared order.
   *
   *  `[]` on revision 1 — it is the beginning, so nothing changed. `null` when the
   *  predecessor exists but fell outside the requested window: unknown, which is NOT the
   *  same as "this edit did nothing". */
  changed: string[] | null;
}

/** VA-8 — what an agent may do with what it sees, and how much it may spend. */
export interface AgentGuardrails {
  /** `redact` is what the platform did before guardrails existed, so it is the default
   *  and an unconfigured agent is unchanged. */
  pii: "off" | "redact" | "block";
  /** Tokens, not dollars. A cost ceiling can only be applied after a call is priced,
   *  which is after it has been paid for — it could stop the NEXT run, never this one. */
  max_tokens_per_run: number | null;
}

export async function getAgentGuardrails(
  agentId: string,
): Promise<{ guardrails: AgentGuardrails; is_default: boolean; modes: { pii: string[] } } | null> {
  const res = await fetch(`${getApiBase()}/agents/custom/${agentId}/guardrails`);
  if (!res.ok) return null;
  return res.json();
}

export async function setAgentGuardrails(
  agentId: string,
  guardrails: AgentGuardrails,
): Promise<{ guardrails: AgentGuardrails } | null> {
  const res = await fetch(`${getApiBase()}/agents/custom/${agentId}/guardrails`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(guardrails),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function listAgentRevisions(
  agentId: string,
): Promise<{ current_rev: string; eval_basis: EvalBasis; revisions: AgentRevision[] }> {
  const res = await fetch(`${getApiBase()}/agents/custom/${agentId}/revisions`);
  if (!res.ok) return { current_rev: "", eval_basis: "none", revisions: [] };
  return res.json();
}

export async function restoreAgentRevision(
  agentId: string,
  version: number,
): Promise<UserAgent | null> {
  const res = await fetch(
    `${getApiBase()}/agents/custom/${agentId}/revisions/${version}/restore`,
    { method: "POST" },
  );
  if (!res.ok) return null;
  return (await res.json()).agent as UserAgent;
}

export async function listUserAgents(): Promise<UserAgent[]> {
  const res = await fetch(`${getApiBase()}/agents/custom`);
  if (!res.ok) return [];
  return res.json();
}

export async function createUserAgent(body: {
  name: string; instructions?: string; connection_id?: string; schema_scope?: string;
  doc_ids?: string[]; pack_ids?: string[];
}): Promise<UserAgent> {
  const res = await fetch(`${getApiBase()}/agents/custom`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `create agent failed (${res.status})`);
  return res.json();
}

/** A Domain Expertise Pack offered as an agent template (Wave H4). `suggested_goldens`
 *  are SUGGESTIONS, not a seeded suite: a pack cannot supply a golden's reference SQL
 *  (it does not know your schema), so each says what it still needs and the hired agent
 *  starts with a stance rather than a pass chip it did not earn. */
export interface AgentTemplate {
  pack_id: string;
  name: string;
  persona: string;
  domains: string[];
  status: string;
  instructions: string;
  suggested_goldens: { question: string; needs: string }[];
  metric_recipes: string[];
}

export async function listAgentTemplates(): Promise<AgentTemplate[]> {
  const res = await fetch(`${getApiBase()}/agents/templates`);
  if (!res.ok) return [];
  return (await res.json()).templates ?? [];
}

export async function createUserAgentFromTemplate(body: {
  pack_id: string; name?: string; connection_id?: string; schema_scope?: string;
}): Promise<{ agent: UserAgent; suggested_goldens: { question: string; needs: string }[] }> {
  const res = await fetch(`${getApiBase()}/agents/custom/from-template`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `hire from template failed (${res.status})`);
  return res.json();
}

export async function patchUserAgent(agentId: string, body: {
  name?: string; instructions?: string; connection_id?: string; schema_scope?: string;
  doc_ids?: string[]; pack_ids?: string[]; enabled?: boolean;
}): Promise<UserAgent> {
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `update agent failed (${res.status})`);
  return res.json();
}

export async function deleteUserAgent(agentId: string): Promise<boolean> {
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}`, {
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
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}/goldens`);
  if (!res.ok) return [];
  return res.json();
}

export async function createAgentGolden(agentId: string, body: {
  question: string; reference_sql: string;
}): Promise<AgentGolden> {
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}/goldens`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `add golden failed (${res.status})`);
  return res.json();
}

export async function deleteAgentGolden(agentId: string, goldenId: string): Promise<boolean> {
  const res = await fetch(
    `${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}/goldens/${encodeURIComponent(goldenId)}`,
    { method: "DELETE" });
  return res.ok;
}

export async function evaluateUserAgent(agentId: string): Promise<AgentEvalResult> {
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}/evaluate`, {
    method: "POST",
  });
  if (!res.ok) throw new Error((await res.text()) || `evaluate failed (${res.status})`);
  return res.json();
}

// ── Observability: per-agent run history + optional MLflow trace stats ─────────
// The Agent Workspace overview. Run history always populates (from the history
// store); trace_stats is null when MLflow tracing is off — the overview degrades to
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
  /** "chat" (a quick conversation, rolled up per session) or "investigation" (a deep run). */
  kind: string;
}

/** A user-defined PERSONA's model spend from the G3 usage store. Distinct from
 *  `AgentSpend` above, which is a fleet CHARTER's (Scout/Analyst) run totals — same word,
 *  different question: what kind of platform work ran, versus whose persona asked.
 *  Recording is permanent (the flag was hardwired 2026-08-01), so a zero here is a
 *  confident zero: the agent spent nothing. */
export type UserAgentSpend = {
  measured: true; calls: number; total_tokens: number;
  cost_usd: number | null; cost_is_complete: boolean; failure_rate: number | null;
};

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
  spend: UserAgentSpend;
}

export async function getAgentObservability(agentId: string): Promise<AgentObservability | null> {
  const res = await fetch(`${getApiBase()}/agents/custom/${encodeURIComponent(agentId)}/observability`);
  if (!res.ok) return null;
  return res.json();
}

// ── Learning / Memory layer (Wave 1 · E4) ───────────────────────────────────
// The closed loop's accumulation, made visible: ambiguity-ledger burn-down, the
// verdict acceptance economy, and trusted-asset counts/lists. See routers/learning.py.
export interface LearningSummary {
  connection_id: string | null;
  ledger: { resolutions: number; by_source: Record<string, number>; served_total: number };
  verdicts: { counts: Record<string, number>; total: number; acceptance_rate: number | null;
              trend?: { week: string; total: number; acceptance_rate: number }[] };
  trusted: { queries: number };
}

export interface TrustedAssets {
  queries: { id: string; question: string; note?: string; tables?: string[]; tags?: string[] }[];
}

/** The Memory-layer headline (org-wide, or one connection). Null on failure — the panel degrades. */
export async function getLearningSummary(connectionId?: string): Promise<LearningSummary | null> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${getApiBase()}/learning/summary${q}`);
  if (!res.ok) return null;
  return res.json();
}

/** The trusted assets themselves — curated queries. */
export async function getTrustedAssets(connectionId?: string): Promise<TrustedAssets | null> {
  const q = connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
  const res = await fetch(`${getApiBase()}/learning/trusted${q}`);
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
  const res = await fetch(`${getApiBase()}/ask/context${qs}`);
  if (!res.ok) return null;
  return res.json();
}

// ── Evals (Wave E) ──────────────────────────────────────────────────────────
// The consolidated eval store (E3) + evaluator library (E2) + fidelity harness
// (E4). Every route is gated on the Enterprise `eval.suite` capability, so a
// 402 here surfaces the upsell modal via the global interceptor. A run is a
// *band* (replicates + noise floor), never a single-run point — see EvalRunSummary.

export interface EvalSuite {
  id: string;
  org_id?: string;
  name: string;
  description: string;
  /** "reference" replays each case's own SQL with no model (the only API-runnable target today). */
  target: string;
  connection_id: string;
  config: Record<string, unknown>;
  created_at: string;
}

export interface EvalCase {
  id: string;
  suite_id: string;
  org_id?: string;
  question: string;
  /** The artifact the case is grounded in — for a reference target, the SQL that gets replayed. */
  artifact: string;
  expected: Record<string, unknown>;
  tags: string[];
  created_at: string;
}

/** The summary a run reduces to — `pass_rate` counts STABLE passes only (a flaky
 *  case is its own outcome, never rounded into a percentage). `accuracy` and
 *  `robustness` are null when no case declared the expectation they measure —
 *  absent, not zero. */
export interface EvalRunSummary {
  run_id: string;
  suite_id: string;
  iterations: number;
  total: number;
  stable_pass: number;
  stable_fail: number;
  flaky: number;
  pass_rate: number;
  correct: number;
  correctness_known: number;
  accuracy: number | null;
  errors: number;
  fired_counts: Record<string, number>;
  config: Record<string, unknown>;
  robustness: number | null;
}

export interface EvalRun {
  id: string;
  suite_id: string;
  org_id?: string;
  status: "running" | "succeeded" | "failed" | string;
  iterations: number;
  started_at: string;
  finished_at: string | null;
  trace_id: string;
  config: Record<string, unknown>;
  summary: Partial<EvalRunSummary>;
}

export interface EvalResult {
  run_id: string;
  case_id: string;
  iteration: number;
  passed: boolean | null;
  correct: boolean | null;
  duration_ms: number | null;
  error: string;
  /** Names of evaluators that FAILED on this case (not passed, not skipped). */
  fired: string[];
  scores: Array<{
    evaluator?: string;
    passed?: boolean;
    value?: number;
    skipped?: boolean;
    rationale?: string;
    checks?: Array<{ name?: string; ok?: boolean; severity?: string; reason?: string; detail?: string }>;
    detail?: Record<string, unknown>;
  }>;
}

export interface EvalEvaluator {
  name: string;
  severity: string;
  requires: string[];
  deterministic: boolean;
}

export async function getEvalSuites(): Promise<EvalSuite[]> {
  const res = await fetch(`${getApiBase()}/evals/suites`);
  if (!res.ok) throw new Error("Failed to fetch eval suites");
  return (await res.json()).suites;
}

export async function getEvalSuite(id: string): Promise<EvalSuite & { cases: EvalCase[] }> {
  const res = await fetch(`${getApiBase()}/evals/suites/${id}`);
  if (!res.ok) throw new Error("Failed to fetch suite");
  return res.json();
}

export async function createEvalSuite(body: {
  name: string; description?: string; target?: string;
  connection_id?: string; config?: Record<string, unknown>;
}): Promise<EvalSuite> {
  const res = await fetch(`${getApiBase()}/evals/suites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to create suite");
  return res.json();
}

export async function deleteEvalSuite(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/evals/suites/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete suite");
}

export async function addEvalCases(
  suiteId: string,
  cases: Array<{ question?: string; artifact?: string; expected?: Record<string, unknown>; tags?: string[] }>,
): Promise<{ added: number }> {
  const res = await fetch(`${getApiBase()}/evals/suites/${suiteId}/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cases }),
  });
  if (!res.ok) throw new Error("Failed to add cases");
  return res.json();
}

export async function deleteEvalCase(caseId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/evals/cases/${caseId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete case");
}

export async function runEvalSuite(
  suiteId: string,
  opts: { iterations?: number; evaluators?: string[] | null; persist?: boolean } = {},
): Promise<EvalRunSummary> {
  const res = await fetch(`${getApiBase()}/evals/suites/${suiteId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      iterations: opts.iterations ?? 1,
      evaluators: opts.evaluators ?? null,
      persist: opts.persist ?? true,
    }),
  });
  if (!res.ok) {
    // The API returns a 400 with a specific detail for a non-'reference' target or a
    // suite missing a connection — surface it rather than a generic message.
    let detail = "Failed to run suite";
    try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.json();
}

export async function getEvalRuns(suiteId?: string, limit = 50): Promise<EvalRun[]> {
  const qs = new URLSearchParams();
  if (suiteId) qs.set("suite_id", suiteId);
  qs.set("limit", String(limit));
  const res = await fetch(`${getApiBase()}/evals/runs?${qs.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return (await res.json()).runs;
}

export async function getEvalRun(runId: string): Promise<EvalRun & { results: EvalResult[] }> {
  const res = await fetch(`${getApiBase()}/evals/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function getEvaluators(): Promise<{ evaluators: EvalEvaluator[]; deterministic_count: number }> {
  const res = await fetch(`${getApiBase()}/evals/evaluators`);
  if (!res.ok) throw new Error("Failed to fetch evaluators");
  return res.json();
}

// ── Control Room (Wave CR) ────────────────────────────────────────────────────
// Views over stores that already exist. Recording is permanent, so an empty list
// under `measured: true` means nothing happened — there is no "switched off" state
// left to distinguish it from.

/** One session event row (kernel ledger `session_events`). */
export interface SessionEvent {
  seq: number;
  at: string;
  trace_id: string;
  kind: string;
  name: string | null;
  span_id: string | null;
  parent_span_id: string | null;
  ok: boolean | null;
  duration_ms: number | null;
  error_class: string | null;
  investigation_id: string | null;
  session_id: string | null;
  user_id: string | null;
  agent_id: string | null;
  conn_id: string | null;
  provider: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  row_count: number | null;
  retries: number | null;
  /** Migration 10 — which run, which agent charter, what the call was FOR, and whether the
   *  primary backend refused. `fallback` is a TRI-state: a tool_call is not a call that
   *  "did not fall back", so unknown stays null rather than arriving as a confident false. */
  job_id: string | null;
  charter_id: string | null;
  role: string | null;
  fallback: boolean | null;
  payload: Record<string, unknown> | null;
  /** Set only when the row carries prompt CONTENT (obs.prompt_capture was on). */
  content_captured?: boolean;
}

/**
 * The wire field naming the built-in agent that owned a run.
 *
 * The word the wire uses for it is retired product vocabulary — `docs/GLOSSARY.md` lists
 * the six built-ins as agents and names that word as one not to say to a user, and the
 * vocabulary ratchet enforces it across `web/`. This module is the one place exempted,
 * because it exists to spell the wire exactly. So the translation happens HERE, at the
 * boundary that already speaks both, and every surface above it addresses the field
 * through this constant and reads it through `builtinAgentOf`.
 */
export const BUILTIN_AGENT_FIELD = "charter_id" as const;

/** Which built-in agent owned this row — `analyst`, `explorer`, `watcher` — or null. */
export function builtinAgentOf(
  e: Pick<SessionEvent, typeof BUILTIN_AGENT_FIELD>,
): string | null {
  return e[BUILTIN_AGENT_FIELD] || null;
}

export interface TraceSummary {
  trace_id: string;
  started: string;
  question: string;
  events: number;
  tool_calls: number;
  llm_calls: number;
  errors: number;
  investigation_id: string | null;
  session_id: string | null;
  agent_id: string | null;
  conn_id: string | null;
  ok: boolean | null;
  duration_ms: number | null;
  /** Absent on a run recorded before the index carried these. */
  user_id?: string | null;
  ended_at?: string | null;
  /** The final response's headline — the only answer text the log keeps. */
  answer?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  /** A FLOOR, not a total: `unpriced_calls` is how many calls no rate covered, and
   *  `calls_without_usage` how many reported no tokens at all. A $0.00 with either of
   *  those non-zero means "unknown", never "free". */
  cost_usd?: number;
  unpriced_calls?: number;
  calls_without_usage?: number;
}

export interface TraceSpan {
  span_id: string;
  parent_span_id: string | null;
  name: string | null;
  seq: number;
  at: string;
  kind: string; // payload.span_kind: "node" | "tool"
  ok: boolean | null;
  duration_ms: number | null;
  error_class: string | null;
  row_count: number | null;
  children: TraceSpan[];
}

export type TraceList = {
  measured: true; recording: boolean; traces: TraceSummary[];
  /** How many runs MATCHED — not how many are on this page. */
  total?: number;
  limit?: number;
  offset?: number;
  /** How far back the fold reached. `total` is a total within this window. */
  scanned_events?: number;
};

/** Everything the trace index can be narrowed by. Applied server-side, over the whole
 *  scan window — narrowing a page in the browser looks the same to a reader and answers
 *  a different question. */
export interface TraceFilters {
  limit?: number;
  offset?: number;
  investigation_id?: string;
  agent_id?: string;
  conn_id?: string;
  /** "ok" | "error" | "running" */
  status?: string;
  user_id?: string;
  q?: string;
  since?: string;
  until?: string;
  min_duration_ms?: number;
  max_duration_ms?: number;
  min_tokens?: number;
}

/** VA-5 — one laid-out node on the waterfall. Assembled at READ time from every event
 *  the run recorded, not only from rows that happen to carry a span id: `llm_call` never
 *  carries one, so a span-keyed view omits the model entirely. */
export interface TimelineNode {
  id: string;
  seq: number;
  span_id: string | null;
  parent_span_id: string | null;
  name: string;
  /** The stored event kind. */
  event_kind: string;
  /** What to draw it as: "model" | "tool" | "frame" | "error" | "event" | "delegation". */
  kind: string;
  /** VA-5 — set only on a delegated hop: which agent ran this, and how deep. */
  delegation: {
    path: string; depth: number | null; agent_id: string; agent_name: string;
  } | null;
  at: string | null;
  ended_at: string | null;
  /** Milliseconds from the run's first event — the bar's x position. */
  offset_ms: number | null;
  duration_ms: number | null;
  ok: boolean | null;
  error_class: string | null;
  row_count: number | null;
  model: string | null;
  provider: string | null;
  role: string | null;
  fallback: boolean | null;
  usage: { prompt_tokens: number | null; completion_tokens: number | null;
           total_tokens: number | null } | null;
  depth: number;
  /** Dead time since the PREVIOUS node ended — a sequential reading, for the label drawn
   *  between two bars. Never sum these: see `idle_ms`. */
  gap_ms: number | null;
  critical: boolean;
}

export interface TraceTimeline {
  nodes: TimelineNode[];
  started_at: string | null;
  total_ms: number | null;
  span_count: number;
  model_calls: number;
  usage: Record<string, number>;
  /** Work time, over the UNION of node intervals. */
  busy_ms: number;
  /** Wall time minus busy. NOT a sum of `gap_ms` — that over-counts the moment a run
   *  does anything in parallel. */
  idle_ms: number;
  wall_ms: number;
  /** Nodes starting before the previous one ended. Non-zero means any sequential
   *  reading of this run is wrong. */
  concurrent_nodes: number;
}

export interface TraceFlowEdge {
  from: string;
  to: string;
  /** Gap since the previous node ENDED. Carried on "next" edges only — a child runs
   *  inside its parent, so a number on a "child" edge would be a duration posing as a
   *  wait. */
  latency_ms: number | null;
  /** "child" = real nesting (the edges that make a run a graph); "next" = the
   *  top-level flow between consecutive root nodes. */
  kind: "child" | "next";
}

export type TraceDetail = {
      measured: true; recording: boolean; trace_id: string; question: string;
      investigation_id: string | null; conn_id: string | null; agent_id: string | null;
      ok: boolean | null; duration_ms: number | null;
      events: SessionEvent[]; spans: TraceSpan[];
      timeline?: TraceTimeline; flow_edges?: TraceFlowEdge[];
    };

export async function getTraces(params?: TraceFilters): Promise<TraceList> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const res = await fetch(`${getApiBase()}/traces?${qs.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch traces (${res.status})`);
  return res.json();
}

export async function getTrace(traceId: string): Promise<TraceDetail | null> {
  const res = await fetch(`${getApiBase()}/traces/${encodeURIComponent(traceId)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch trace (${res.status})`);
  return res.json();
}

export type ActivityResponse =
  | { measured: true; recording: boolean; events: SessionEvent[]; kinds: Record<string, number> };

export async function getActivity(params?: {
  kind?: string; agent_id?: string; conn_id?: string; errors_only?: boolean;
  since_seq?: number; limit?: number;
}): Promise<ActivityResponse> {
  const qs = new URLSearchParams();
  if (params?.kind) qs.set("kind", params.kind);
  if (params?.agent_id) qs.set("agent_id", params.agent_id);
  if (params?.conn_id) qs.set("conn_id", params.conn_id);
  if (params?.errors_only) qs.set("errors_only", "true");
  if (params?.since_seq != null) qs.set("since_seq", String(params.since_seq));
  if (params?.limit) qs.set("limit", String(params.limit));
  const res = await fetch(`${getApiBase()}/activity?${qs.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch activity (${res.status})`);
  return res.json();
}

export interface FleetTiles {
  active_jobs: number;
  window_minutes: number;
  runs_started: number;
  runs_per_min: number;
  p95_duration_ms: number | null;
  p50_duration_ms: number | null;
  error_rate: number | null;
  failed_runs: number;
  orphaned_runs: number;
  tokens: {
    total: number; metered_runs: number; unmetered_runs: number;
    per_hour: number | null;
  };
  concurrency: { max_concurrent_jobs: number; unbounded_kinds: string[] };
  /** What every figure above LEFT OUT — the automation engine's tick, counted apart. */
  runner_runs: number;
  include_runners: boolean;
  /** True when a read filled its cap: every count in this object is then a floor, not a
   *  total. The tile says so rather than presenting a truncated number as complete. */
  truncated?: boolean;
  window: TimeWindow;
  /** Priced from the provider's own catalogue; `unpriced_calls` is why a small total is
   *  not the same as a cheap day. */
  cost: { usd: number | null; unpriced_calls: number | null; is_complete: boolean; calls: number };
}

/** A resolved window — the one time axis every panel on this surface buckets through. */
export interface TimeWindow {
  since: string;
  until: string;
  bucket_seconds: number;
  buckets: number;
  range: string;
}

/** A charter row (job-metering spend) — `kind` is the label the table must show. */
export interface FleetCharterRow {
  kind: "charter";
  id: string;
  name: string;
  role: string;
  icon: string;
  lane: string;
  enabled: boolean;
  job_kinds: string[];
  spend_source: "job_metering";
  runs: number;
  failed: number;
  orphaned: number;
  tokens: number;
  queries: number;
  metered_runs: number;
  unmetered_runs: number;
  last_run_at: string | null;
  spark: number[];
}

/** A custom-agent row (session-log spend). Same table, same columns, different source —
 *  its work is CALLS in the session log rather than jobs in the kernel, which is why the
 *  row carries `spend_source` rather than pretending the two populations are one. */
export interface FleetPersonaRow {
  kind: "persona";
  id: string;
  name: string;
  enabled: boolean;
  connection_id: string;
  last_eval: { passed: number; total: number; at?: string } | null;
  eval_basis: EvalBasis;
  spend_source: "session_log";
  spend: { measured: true; calls: number; total_tokens: number; failure_rate: number | null };
  runs: number;
  failed: number;
  orphaned: number;
  tokens: number;
  queries: number;
  metered_runs: number;
  unmetered_runs: number;
  spark: number[];
  last_run_at: string | null;
}

/** A background runner — the automation tick, eval experiments. Reported, never summed
 *  into the agents: measured 2026-08-17 the tick was 98% of all jobs. */
export interface FleetRunnerRow {
  kind: "runner";
  id: string;
  name: string;
  role: string;
  icon: string;
  lane: string;
  enabled: boolean;
  job_kinds: string[];
  spend_source: "job_metering";
  runs: number;
  failed: number;
  orphaned: number;
  tokens: number;
  queries: number;
  metered_runs: number;
  unmetered_runs: number;
  last_run_at: string | null;
  spark: number[];
}

export type FleetRow = FleetCharterRow | FleetPersonaRow;

export interface FleetOverview {
  tiles: FleetTiles;
  rows: FleetRow[];
  runners: FleetRunnerRow[];
  window: TimeWindow;
  edges: string[];
  session_log_recording: boolean;
}

export async function getFleetOverview(params?: {
  window_minutes?: number; spark_hours?: number;
  range?: string; since?: string; until?: string; include_runners?: boolean;
}): Promise<FleetOverview> {
  const qs = new URLSearchParams();
  if (params?.window_minutes) qs.set("window_minutes", String(params.window_minutes));
  if (params?.spark_hours) qs.set("spark_hours", String(params.spark_hours));
  if (params?.range) qs.set("range", params.range);
  if (params?.since) qs.set("since", params.since);
  if (params?.until) qs.set("until", params.until);
  if (params?.include_runners) qs.set("include_runners", "true");
  const res = await fetch(`${getApiBase()}/control-room/fleet?${qs.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch fleet overview (${res.status})`);
  return res.json();
}

export interface NeedsHumanRow {
  source: "kinetic_inbox" | "paused_run" | "automation_approval" | "agent_alert"
        | "automation_broken";
  id: string;
  title: string;
  connection_id: string | null;
  since: string | null;
  since_basis?: "paused_event" | "started_at";
  waiting_ms: number | null;
  /** Agent alerts only: two rows can wait the same time and not be equally urgent. */
  severity?: "info" | "warning" | "critical";
  resolve: Record<string, string>;
}

export interface NeedsHuman {
  count: number;
  sources: {
    kinetic_inbox: number;
    paused_runs: number;
    automation_approvals: number;
    agent_alerts: number;
    /** Optional because the key is newer than some deployed APIs — read it with `?? 0`
     *  rather than rendering `undefined` where a count belongs. */
    broken_automations?: number;
  };
  rows: NeedsHumanRow[];
}

export async function getNeedsHuman(limit = 100): Promise<NeedsHuman> {
  const res = await fetch(`${getApiBase()}/control-room/needs-human?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch needs-human (${res.status})`);
  return res.json();
}

// ── VA-6: agent alerts ───────────────────────────────────────────────────────────

/** One rule that fired. The numbers travel with the row because a rule is editable and
 *  an alert is a statement about a moment. */
export interface AgentAlertEvent {
  id: string;
  rule_id: string;
  rule_name: string;
  metric: string;
  severity: "info" | "warning" | "critical";
  fired_at: string;
  value: number | null;
  threshold: number | null;
  population: number;
  window_minutes: number;
  reason: string;
  delivered: boolean;
  delivery_detail: string;
  acknowledged: boolean;
}

export interface AgentAlertRule {
  id: string;
  name: string;
  metric: string;
  comparator: "gt" | "gte" | "lt" | "lte";
  threshold: number;
  window_minutes: number;
  debounce_minutes: number;
  check_cron: string;
  agent_id: string;
  charter_id: string;
  channel: string;
  severity: "info" | "warning" | "critical";
  enabled: boolean;
  last_notified_at: string | null;
}

export async function listAgentAlertRules(enabledOnly = false): Promise<AgentAlertRule[]> {
  const res = await fetch(
    `${getApiBase()}/obs/agent-alerts/rules?enabled_only=${enabledOnly}`);
  if (!res.ok) throw new Error(`Failed to fetch agent alert rules (${res.status})`);
  return (await res.json()).rules;
}

export async function listAgentAlertEvents(limit = 100): Promise<AgentAlertEvent[]> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/events?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch agent alerts (${res.status})`);
  return (await res.json()).events;
}

/** The metric vocabulary, from the server. Never hardcoded here: a picker that offers a
 *  metric the backend cannot measure is a control that silently does nothing. */
export async function getAgentAlertVocabulary(): Promise<{ metrics: string[]; comparators: string[] }> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/metrics`);
  if (!res.ok) throw new Error(`Failed to fetch alert metrics (${res.status})`);
  return res.json();
}

export async function upsertAgentAlertRule(rule: Partial<AgentAlertRule>): Promise<AgentAlertRule> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/rules`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail || `save failed (${res.status})`);
  return body;
}

export async function deleteAgentAlertRule(ruleId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/rules/${ruleId}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed (${res.status})`);
}

/** One verdict, right now. Returns whether it crossed AND the population it saw — "it did
 *  not fire" is only useful with the number behind it. */
export async function testAgentAlertRule(ruleId: string): Promise<{
  verdict: { value: number | null; matched: boolean; should_notify: boolean;
             population: number; reason: string };
  event: AgentAlertEvent | null;
}> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/rules/${ruleId}/test`,
    { method: "POST" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail || `test failed (${res.status})`);
  return body;
}

export async function acknowledgeAgentAlert(eventId: string): Promise<AgentAlertEvent> {
  const res = await fetch(`${getApiBase()}/obs/agent-alerts/events/${eventId}/ack`,
    { method: "POST" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail || `acknowledge failed (${res.status})`);
  return body;
}

// ── The shared time axis (W0) ────────────────────────────────────────────────────

/** One stack/line of a timeseries: a key, one value per bucket, and its total. */
export interface TimeSeries {
  key: string;
  label: string;
  values: number[];
  total: number;
}

export interface TimeSeriesResponse {
  measured: boolean;
  window: TimeWindow;
  edges: string[];
  group: string;
  measure: string;
  series: TimeSeries[];
  scanned: number;
  attributed: number;
  /** Share of scanned rows that carried the grouping key. A top-N built from 3% of the
   *  traffic is not a top-N, so this ships with every answer rather than on request. */
  coverage: number | null;
}

export async function getObsTimeseries(params: {
  group?: string; measure?: string; kind?: string;
  /** `jobs` counts RUNS by the charter that owns each kind (complete, derived at read
   *  time); `events` counts model CALLS by the charter stamped when they were written. */
  source?: "jobs" | "events";
  range?: string; since?: string; until?: string;
}): Promise<TimeSeriesResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, String(v));
  const res = await fetch(`${getApiBase()}/obs/timeseries?${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch timeseries (${res.status})`);
  return res.json();
}

export interface UsageSummary {
  measured: boolean;
  window: TimeWindow;
  calls: number;
  tokens: number;
  cost_usd: number;
  unpriced_calls: number;
  cost_is_complete: boolean;
  calls_without_usage: number;
  usage_coverage: number | null;
  /** Both halves of the rate: a denominator that is invisible gets read as "right now". */
  fallback: { fell_back: number; of_attributed: number; rate: number | null };
  models: Array<{
    provider: string; model: string; calls: number; total_tokens: number;
    failures: number; failure_rate: number; mean_ms: number;
    cost_usd: number; cost_is_complete: boolean; calls_without_usage: number;
  }>;
  sites: Array<{
    caller: string; calls: number; prompt_tokens: number; total_tokens: number;
    calls_without_usage: number;
  }>;
  roles: Array<{ role: string; calls: number; total_tokens: number }>;
}

export async function getUsageSummary(params?: {
  range?: string; since?: string; until?: string;
}): Promise<UsageSummary> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) if (v) qs.set(k, String(v));
  const res = await fetch(`${getApiBase()}/obs/usage-summary?${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch usage summary (${res.status})`);
  return res.json();
}

/** The drill: every ranked list on the usage surface opens exactly its own rows. */
export async function getActivityEvents(params?: {
  kind?: string; agent_id?: string; conn_id?: string; model?: string; provider?: string;
  charter?: string; job_id?: string; role?: string; trace_id?: string;
  range?: string; since?: string; until?: string; errors_only?: boolean; limit?: number;
}): Promise<{ measured: boolean; events: SessionEvent[]; kinds: Record<string, number>;
              window: TimeWindow | null }> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    qs.set(k, String(v));
  }
  const res = await fetch(`${getApiBase()}/activity?${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch activity (${res.status})`);
  return res.json();
}

export async function getAllAutomationRuns(params?: {
  conn_id?: string; limit?: number;
}): Promise<AutomationRun[]> {
  const qs = new URLSearchParams();
  if (params?.conn_id) qs.set("conn_id", params.conn_id);
  if (params?.limit) qs.set("limit", String(params.limit));
  const res = await fetch(`${getApiBase()}/automations/runs?${qs.toString()}`);
  if (res.status === 404) return []; // automations.engine off
  if (!res.ok) throw new Error(`Failed to fetch automation runs (${res.status})`);
  return (await res.json()).runs;
}

export interface InvestigationGraph {
  investigation_id: string;
  status: string;
  question: string;
  /** Wire value from the backend graph endpoint — "ada" is its spelling, frozen. */
  branch: "ada" | "explore" | "direct" | "unknown";
  topology: string[];
  phases: {
    phase_id: string; phase_name: string; phase_icon?: string;
    status: string; summary?: string; skipped_reason?: string;
  }[];
  sub_questions: unknown[];
  interrupt: {
    paused: boolean; gate: string | null; basis: string | null;
    clarify_pending: unknown;
  };
  checkpoint: { exists: boolean; step: number | null; last_writers: string[] };
  resume: { feedback: string } | null;
}

export async function getInvestigationGraph(invId: string): Promise<InvestigationGraph | null> {
  const res = await fetch(`${getApiBase()}/investigations/${encodeURIComponent(invId)}/graph`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch investigation graph (${res.status})`);
  return res.json();
}

export interface FindingVerdict {
  id: number;
  connection_id: string;
  investigation_id: string;
  verdict: string;
  note: string;
  headline: string;
  created_at: string;
}

export async function getVerdicts(connectionId?: string, limit = 50): Promise<FindingVerdict[]> {
  const qs = new URLSearchParams();
  if (connectionId) qs.set("connection_id", connectionId);
  qs.set("limit", String(limit));
  const res = await fetch(`${getApiBase()}/verify/verdicts?${qs.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch verdicts (${res.status})`);
  return res.json();
}

export interface InvestigationListRow {
  id: string;
  question: string;
  connection_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  headline: string | null;
  kind: string;
  agent_id: string;
}

export async function getInvestigationsList(limit = 50): Promise<InvestigationListRow[]> {
  const res = await fetch(`${getApiBase()}/investigations?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch investigations (${res.status})`);
  return res.json();
}

/** VA-5 — a judgement on a RUN, keyed by trace id.
 *
 *  Distinct from `recordVerdict`, which judges a FINDING and needs an investigation id:
 *  measured on this store, 256 of 263 runs have none, so that control silently did
 *  nothing on 97% of them. A quick turn is still a run somebody can call unhelpful.
 *  The vocabularies stay apart on purpose — "this run was unhelpful" is not "this
 *  finding is wrong", and merging them would teach the closed loop to read a latency
 *  complaint as a wrong answer. */
export interface TraceFeedbackItem {
  at: string;
  verdict: "helpful" | "unhelpful";
  note: string;
  by: string;
}

export interface TraceFeedback {
  trace_id: string;
  count: number;
  helpful: number;
  unhelpful: number;
  items: TraceFeedbackItem[];
}

export async function recordTraceFeedback(
  traceId: string, verdict: "helpful" | "unhelpful", note = "",
): Promise<{ ok: boolean; recorded: boolean }> {
  const res = await fetch(`${getApiBase()}/traces/${encodeURIComponent(traceId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict, note }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to record feedback");
  }
  return res.json();
}

export async function getTraceFeedback(traceId: string): Promise<TraceFeedback> {
  const res = await fetch(`${getApiBase()}/traces/${encodeURIComponent(traceId)}/feedback`);
  if (!res.ok) throw new Error(`Failed to fetch trace feedback (${res.status})`);
  return res.json();
}

/** VA-5 — the kernel journal for one run.
 *
 *  The waterfall shows what the agent DID; this shows what the run SURVIVED. A
 *  tolerated error is invisible in the waterfall by construction — the span it
 *  happened inside succeeded — so the journal is the only place it exists. */
export interface TraceLogLine {
  at: string;
  seq: number;
  kind: string;
  tolerated: boolean;
  error: string | null;
  reason: string | null;
  counter: string | null;
  payload: Record<string, unknown> | null;
}

export interface TraceLogs {
  trace_id: string;
  count: number;
  tolerated_errors: number;
  lines: TraceLogLine[];
}

export async function getTraceLogs(traceId: string, limit = 200): Promise<TraceLogs> {
  const res = await fetch(
    `${getApiBase()}/traces/${encodeURIComponent(traceId)}/logs?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch trace logs (${res.status})`);
  return res.json();
}
