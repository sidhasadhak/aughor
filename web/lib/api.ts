const BASE = "http://localhost:8000";

export interface Connection {
  id: string;
  name: string;
  conn_type: string;
  dsn_preview: string;
  schema_name: string | null;
  builtin: boolean;
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

export async function addConnection(
  name: string,
  conn_type: string,
  dsn: string,
  schema_name?: string,
): Promise<{ id: string; message: string; test_result: string }> {
  const res = await fetch(`${BASE}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, conn_type, dsn, schema_name: schema_name || null }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Failed to add connection");
  }
  return res.json();
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

export async function getSchema(id: string): Promise<string> {
  const res = await fetch(`${BASE}/connections/${id}/schema`);
  if (!res.ok) throw new Error("Failed to fetch schema");
  const data = await res.json();
  return data.schema as string;
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

export async function deleteMetric(name: string): Promise<void> {
  await fetch(`${BASE}/metrics/${encodeURIComponent(name)}`, { method: "DELETE" });
}

// ── Ontology ──────────────────────────────────────────────────────────────────

export interface ComputedProperty {
  id: string;
  label: string;
  formula_sql: string;
  unit: string;
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
  created_at_col: string | null;
  default_filters: string[];
  exclude_when: string[];
  computed_properties: ComputedProperty[];
}

export interface ConnectionSettings {
  ontology_refresh_hours: number | null;
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

export async function rebuildOntology(connectionId: string): Promise<{ ok: boolean; generated_at: string; entities: number }> {
  const res = await fetch(`${BASE}/ontology/rebuild?connection_id=${encodeURIComponent(connectionId)}`, { method: "POST" });
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
  business_rules_enforced: string[];
  returns: string;
  source_table: string;
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
  schema_fingerprint: string;
  generated_at: string;
  enriched: boolean;
  entities: Record<string, OntologyEntity>;
  relationships: Record<string, OntologyRelationship>;
  metrics: Record<string, OntologyMetric>;
  actions: Record<string, OntologyAction>;
}

export async function getOntology(connectionId: string): Promise<OntologyGraph> {
  const res = await fetch(`${BASE}/ontology?connection_id=${encodeURIComponent(connectionId)}`);
  if (!res.ok) throw new Error("Ontology not available for this connection");
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
  completed_at: string | null;
  error: string | null;
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
}

export interface DomainInsights {
  insights: ExplorationInsight[];
  queries_used: number;
  budget_cap: number;
  angles_covered: string[];
}

export async function getDomainInsights(connectionId: string): Promise<Record<string, DomainInsights>> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/domains`);
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

export interface ExplorationFindings {
  connection_id: string;
  phase: string;
  null_meanings: Record<string, NullMeaning>;
  join_verifications: JoinVerification[];
  lifecycle_maps: Record<string, LifecycleMap>;
  distributions: Record<string, DistributionProfile>;
  insights: ExplorationInsight[];
}

export async function getExplorationFindings(connectionId: string): Promise<ExplorationFindings> {
  const res = await fetch(`${BASE}/exploration/${encodeURIComponent(connectionId)}/findings`);
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
    materializer_hit_rate: number | null;
    ibis_usage_rate: number | null;
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
