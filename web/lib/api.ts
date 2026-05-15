const BASE = "http://localhost:8000";

export interface Connection {
  id: string;
  name: string;
  conn_type: string;
  dsn_preview: string;
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
  dsn: string
): Promise<{ id: string; message: string; test_result: string }> {
  const res = await fetch(`${BASE}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, conn_type, dsn }),
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
