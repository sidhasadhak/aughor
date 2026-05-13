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

export async function getSchema(id: string): Promise<string> {
  const res = await fetch(`${BASE}/connections/${id}/schema`);
  if (!res.ok) throw new Error("Failed to fetch schema");
  const data = await res.json();
  return data.schema as string;
}
