"use client";

/**
 * SemanticLayerPanel — three-tab management interface for:
 *  1. Schema Annotations — table + column business descriptions injected into schema
 *  2. Knowledge Store    — metric definitions, synonyms, join rules (per connection)
 *  3. Benchmarks         — gold questions for SQL quality regression testing
 */

import React, { useCallback, useEffect, useState } from "react";
import { API_BASE as BASE } from "@/lib/config";

// ── Fetch helpers ──────────────────────────────────────────────────────────────

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

function put(path: string, body: unknown)    { return apiFetch(path, { method: "PUT",    body: JSON.stringify(body) }); }
function post(path: string, body: unknown)   { return apiFetch(path, { method: "POST",   body: JSON.stringify(body) }); }
function del(path: string)                   { return apiFetch(path, { method: "DELETE" }); }

// ═══════════════════════════════════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════════════════════════════════

// ── Shared UI primitives ──────────────────────────────────────────────────────

function TabBar({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 2, borderBottom: "1px solid var(--border-0, #2a2a2a)", paddingBottom: 0, marginBottom: 16 }}>
      {tabs.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          style={{
            padding: "6px 14px",
            fontSize: 12,
            fontWeight: active === t ? 600 : 400,
            color: active === t ? "var(--blue4, #60a5fa)" : "var(--t3, #888)",
            background: "none",
            border: "none",
            borderBottom: active === t ? "2px solid var(--blue4, #60a5fa)" : "2px solid transparent",
            cursor: "pointer",
            transition: "color 0.15s",
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: "var(--t2, #bbb)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{title}</span>
      {action}
    </div>
  );
}

function Btn({ children, onClick, variant = "default", disabled }: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "default" | "danger" | "ghost";
  disabled?: boolean;
}) {
  const colors: Record<string, React.CSSProperties> = {
    default: { background: "var(--blue4, #3b82f6)", color: "#fff" },
    danger:  { background: "transparent", color: "var(--red4, #f87171)", border: "1px solid var(--red4, #f87171)" },
    ghost:   { background: "transparent", color: "var(--t3, #888)", border: "1px solid var(--border-0, #2a2a2a)" },
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        fontSize: 11, padding: "4px 10px", borderRadius: 5, cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1, border: "none", ...colors[variant],
      }}
    >
      {children}
    </button>
  );
}

function Input({ value, onChange, placeholder, multiline }: {
  value: string; onChange: (v: string) => void; placeholder?: string; multiline?: boolean;
}) {
  const base: React.CSSProperties = {
    width: "100%", fontSize: 12, padding: "6px 8px", borderRadius: 5,
    background: "var(--bg-1, #1a1a1a)", border: "1px solid var(--border-0, #2a2a2a)",
    color: "var(--t1, #e5e5e5)", outline: "none", resize: "vertical",
    boxSizing: "border-box",
  };
  if (multiline)
    return <textarea rows={3} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} style={base} />;
  return <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} style={base} />;
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      style={{ fontSize: 12, padding: "5px 8px", borderRadius: 5, background: "var(--bg-1, #1a1a1a)", border: "1px solid var(--border-0, #2a2a2a)", color: "var(--t1, #e5e5e5)", outline: "none" }}>
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function ErrorMsg({ msg }: { msg: string }) {
  if (!msg) return null;
  return <p style={{ fontSize: 11, color: "var(--red4, #f87171)", marginTop: 6 }}>{msg}</p>;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div style={{ padding: "32px 0", textAlign: "center", color: "var(--t4, #555)", fontSize: 12 }}>
      {text}
    </div>
  );
}

// ── Tag list (comma-separated) ────────────────────────────────────────────────

function tagList(s: string): string[] { return s.split(",").map(t => t.trim()).filter(Boolean); }

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 1: Annotations
// ═══════════════════════════════════════════════════════════════════════════════

interface TableAnnotations {
  description?: string;
  columns?: Record<string, { description?: string }>;
}

function AnnotationsTab({ connId }: { connId: string }) {
  const [data, setData]       = useState<Record<string, TableAnnotations>>({});
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");

  // Edit form state
  const [editingTable, setEditingTable]   = useState<string | null>(null);
  const [editingColumn, setEditingColumn] = useState<string | null>(null);
  const [editDesc, setEditDesc]           = useState("");
  const [saving, setSaving]               = useState(false);

  // New annotation form
  const [newTable, setNewTable]   = useState("");
  const [newCol, setNewCol]       = useState("");
  const [newDesc, setNewDesc]     = useState("");
  const [addErr, setAddErr]       = useState("");

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try {
      const d = await apiFetch(`/semantic/${connId}/annotations`);
      setData(d);
    } catch (e: unknown) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [connId]);

  useEffect(() => { load(); }, [load]);

  async function saveEdit() {
    if (!editingTable) return;
    setSaving(true);
    try {
      if (editingColumn) {
        await put(`/semantic/${connId}/annotations/column/${editingTable}/${editingColumn}`, { description: editDesc });
      } else {
        await put(`/semantic/${connId}/annotations/table/${editingTable}`, { description: editDesc });
      }
      setEditingTable(null); setEditingColumn(null); setEditDesc("");
      await load();
    } catch (e: unknown) { setErr(String(e)); }
    finally { setSaving(false); }
  }

  async function deleteAnnotation(table: string, column?: string) {
    try {
      if (column) {
        await del(`/semantic/${connId}/annotations/column/${table}/${column}`);
      } else {
        await del(`/semantic/${connId}/annotations/table/${table}`);
      }
      await load();
    } catch (e: unknown) { setErr(String(e)); }
  }

  async function addAnnotation() {
    if (!newTable.trim()) { setAddErr("Table name is required"); return; }
    if (!newDesc.trim())  { setAddErr("Description is required"); return; }
    setAddErr("");
    try {
      if (newCol.trim()) {
        await put(`/semantic/${connId}/annotations/column/${newTable.trim()}/${newCol.trim()}`, { description: newDesc.trim() });
      } else {
        await put(`/semantic/${connId}/annotations/table/${newTable.trim()}`, { description: newDesc.trim() });
      }
      setNewTable(""); setNewCol(""); setNewDesc("");
      await load();
    } catch (e: unknown) { setAddErr(String(e)); }
  }

  const tables = Object.keys(data);

  return (
    <div>
      {/* Add new */}
      <div style={{ background: "var(--bg-1, #1a1a1a)", border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 8, padding: 14, marginBottom: 20 }}>
        <SectionHeader title="Add Annotation" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
          <Input value={newTable} onChange={setNewTable} placeholder="Table name *" />
          <Input value={newCol}   onChange={setNewCol}   placeholder="Column name (optional)" />
        </div>
        <Input value={newDesc} onChange={setNewDesc} placeholder="Business description *" multiline />
        <ErrorMsg msg={addErr} />
        <div style={{ marginTop: 8 }}>
          <Btn onClick={addAnnotation}>Add</Btn>
        </div>
      </div>

      {/* List */}
      {loading && <p style={{ color: "var(--t4)", fontSize: 12 }}>Loading…</p>}
      <ErrorMsg msg={err} />
      {!loading && tables.length === 0 && <EmptyState text="No annotations yet. Add one above to enrich the schema context sent to the AI." />}

      {tables.map(table => (
        <div key={table} style={{ marginBottom: 16, border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 8, overflow: "hidden" }}>
          {/* Table row */}
          <div style={{ padding: "8px 12px", background: "var(--bg-1, #181818)", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>TABLE: {table}</span>
            {data[table]?.description && (
              <span style={{ fontSize: 11, color: "var(--t3)", flex: 2 }}>{data[table].description}</span>
            )}
            <Btn variant="ghost" onClick={() => { setEditingTable(table); setEditingColumn(null); setEditDesc(data[table]?.description ?? ""); }}>Edit</Btn>
            <Btn variant="danger" onClick={() => deleteAnnotation(table)}>Delete</Btn>
          </div>

          {/* Column rows */}
          {Object.entries(data[table]?.columns ?? {}).map(([col, colData]) => (
            <div key={col} style={{ padding: "6px 12px 6px 24px", borderTop: "1px solid var(--border-0, #2a2a2a)", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--t2)", minWidth: 120 }}>{col}</span>
              <span style={{ fontSize: 11, color: "var(--t3)", flex: 1 }}>{colData.description}</span>
              <Btn variant="ghost" onClick={() => { setEditingTable(table); setEditingColumn(col); setEditDesc(colData.description ?? ""); }}>Edit</Btn>
              <Btn variant="danger" onClick={() => deleteAnnotation(table, col)}>Delete</Btn>
            </div>
          ))}
        </div>
      ))}

      {/* Inline edit modal */}
      {editingTable && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={e => { if (e.target === e.currentTarget) { setEditingTable(null); setEditingColumn(null); } }}>
          <div style={{ background: "var(--bg-0, #111)", border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 10, padding: 20, width: 420 }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--t1)" }}>
              Edit {editingColumn ? `${editingTable}.${editingColumn}` : `TABLE: ${editingTable}`}
            </p>
            <Input value={editDesc} onChange={setEditDesc} placeholder="Business description" multiline />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Btn onClick={saveEdit} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
              <Btn variant="ghost" onClick={() => { setEditingTable(null); setEditingColumn(null); }}>Cancel</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 2: Knowledge Store
// ═══════════════════════════════════════════════════════════════════════════════

interface KnowledgeEntry {
  id: string;
  title: string;
  body: string;
  kind: string;
  tags: string[];
  connection_id: string;
}

const KNOWLEDGE_KINDS = [
  { value: "metric",  label: "Metric Definition" },
  { value: "synonym", label: "Synonym" },
  { value: "rule",    label: "Business Rule" },
  { value: "join",    label: "Join Guidance" },
  { value: "note",    label: "Note" },
];

const KIND_BADGE: Record<string, string> = {
  metric:  "#3b82f6", synonym: "#8b5cf6", rule: "#f59e0b", join: "#10b981", note: "#6b7280",
};

const EMPTY_ENTRY = { id: "", title: "", body: "", kind: "note", tags: "" };

function KnowledgeTab({ connId }: { connId: string }) {
  const [entries, setEntries]     = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading]     = useState(false);
  const [err, setErr]             = useState("");
  const [editId, setEditId]       = useState<string | null>(null);
  const [form, setForm]           = useState(EMPTY_ENTRY);
  const [saving, setSaving]       = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try { setEntries(await apiFetch(`/semantic/${connId}/knowledge`)); }
    catch (e: unknown) { setErr(String(e)); }
    finally { setLoading(false); }
  }, [connId]);

  useEffect(() => { load(); }, [load]);

  function startAdd() { setEditId("__new__"); setForm(EMPTY_ENTRY); }
  function startEdit(e: KnowledgeEntry) {
    setEditId(e.id);
    setForm({ id: e.id, title: e.title, body: e.body, kind: e.kind, tags: e.tags.join(", ") });
  }

  async function saveEntry() {
    if (!form.title.trim() || !form.body.trim()) { setErr("Title and body are required"); return; }
    setSaving(true);
    try {
      const payload = { id: form.id || undefined, title: form.title, body: form.body, kind: form.kind, tags: tagList(form.tags) };
      if (editId === "__new__") {
        await post(`/semantic/${connId}/knowledge`, payload);
      } else {
        await put(`/semantic/${connId}/knowledge/${editId}`, payload);
      }
      setEditId(null); await load();
    } catch (e: unknown) { setErr(String(e)); }
    finally { setSaving(false); }
  }

  async function deleteEntry(id: string) {
    try { await del(`/semantic/${connId}/knowledge/${id}`); await load(); }
    catch (e: unknown) { setErr(String(e)); }
  }

  async function rebuildIndex() {
    setRebuilding(true);
    try {
      const r = await post(`/semantic/${connId}/knowledge/rebuild-index`, {});
      alert(`Re-indexed ${r.indexed} entries.`);
    } catch (e: unknown) { setErr(String(e)); }
    finally { setRebuilding(false); }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <Btn onClick={startAdd}>+ Add Entry</Btn>
        <Btn variant="ghost" onClick={rebuildIndex} disabled={rebuilding}>{rebuilding ? "Rebuilding…" : "Rebuild Vector Index"}</Btn>
      </div>

      {loading && <p style={{ fontSize: 12, color: "var(--t4)" }}>Loading…</p>}
      <ErrorMsg msg={err} />
      {!loading && entries.length === 0 && (
        <EmptyState text="No knowledge entries yet. Add metric definitions, synonyms, or join rules to improve AI query quality." />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {entries.map(e => (
          <div key={e.id} style={{ border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 8, padding: "10px 14px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 10, background: KIND_BADGE[e.kind] ?? "#6b7280", color: "#fff", fontWeight: 600, marginTop: 1, whiteSpace: "nowrap" }}>
                {e.kind}
              </span>
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", margin: 0 }}>{e.title}</p>
                <p style={{ fontSize: 11, color: "var(--t3)", margin: "3px 0 0", lineHeight: 1.5 }}>{e.body}</p>
                {e.tags.length > 0 && (
                  <p style={{ fontSize: 10, color: "var(--t4)", marginTop: 4 }}>{e.tags.map(t => `#${t}`).join(" ")}</p>
                )}
              </div>
              <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                <Btn variant="ghost" onClick={() => startEdit(e)}>Edit</Btn>
                <Btn variant="danger" onClick={() => deleteEntry(e.id)}>Delete</Btn>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Edit/Add modal */}
      {editId !== null && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={e => { if (e.target === e.currentTarget) setEditId(null); }}>
          <div style={{ background: "var(--bg-0, #111)", border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 10, padding: 20, width: 480 }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--t1)" }}>
              {editId === "__new__" ? "New Knowledge Entry" : "Edit Entry"}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Input value={form.title} onChange={v => setForm(f => ({ ...f, title: v }))} placeholder="Title / name *" />
              <Input value={form.body} onChange={v => setForm(f => ({ ...f, body: v }))} placeholder="Definition or rule *" multiline />
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Select value={form.kind} onChange={v => setForm(f => ({ ...f, kind: v }))} options={KNOWLEDGE_KINDS} />
                <Input value={form.tags} onChange={v => setForm(f => ({ ...f, tags: v }))} placeholder="Tags (comma-separated)" />
              </div>
            </div>
            <ErrorMsg msg={err} />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Btn onClick={saveEntry} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
              <Btn variant="ghost" onClick={() => setEditId(null)}>Cancel</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 3: Benchmarks
// ═══════════════════════════════════════════════════════════════════════════════

interface BenchmarkCase {
  id: string;
  question: string;
  expected_cols: string[];
  must_contain: string[];
  must_not_contain: string[];
  notes: string;
}

interface CaseResult {
  case_id: string;
  question: string;
  passed: boolean;
  generated_sql: string;
  actual_cols: string[];
  failures: string[];
  error: string;
}

interface BenchmarkRun {
  total: number;
  passed: number;
  failed: number;
  score: number;
  results: CaseResult[];
}

const EMPTY_CASE = { id: "", question: "", expected_cols: "", must_contain: "", must_not_contain: "", notes: "" };

function BenchmarksTab({ connId }: { connId: string }) {
  const [cases, setCases]       = useState<BenchmarkCase[]>([]);
  const [loading, setLoading]   = useState(false);
  const [err, setErr]           = useState("");
  const [editId, setEditId]     = useState<string | null>(null);
  const [form, setForm]         = useState(EMPTY_CASE);
  const [saving, setSaving]     = useState(false);
  const [running, setRunning]   = useState(false);
  const [runResult, setRunResult] = useState<BenchmarkRun | null>(null);
  const [expandedResult, setExpandedResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try { setCases(await apiFetch(`/semantic/${connId}/benchmarks`)); }
    catch (e: unknown) { setErr(String(e)); }
    finally { setLoading(false); }
  }, [connId]);

  useEffect(() => { load(); }, [load]);

  async function saveCase() {
    if (!form.question.trim()) { setErr("Question is required"); return; }
    setSaving(true);
    const payload = {
      id: form.id || undefined,
      question: form.question,
      expected_cols:    form.expected_cols.split(",").map(s => s.trim()).filter(Boolean),
      must_contain:     form.must_contain.split(",").map(s => s.trim()).filter(Boolean),
      must_not_contain: form.must_not_contain.split(",").map(s => s.trim()).filter(Boolean),
      notes: form.notes,
    };
    try {
      if (editId === "__new__") {
        await post(`/semantic/${connId}/benchmarks`, payload);
      } else {
        await put(`/semantic/${connId}/benchmarks/${editId}`, payload);
      }
      setEditId(null); await load();
    } catch (e: unknown) { setErr(String(e)); }
    finally { setSaving(false); }
  }

  async function deleteCase(id: string) {
    try { await del(`/semantic/${connId}/benchmarks/${id}`); await load(); }
    catch (e: unknown) { setErr(String(e)); }
  }

  async function runBenchmarks() {
    setRunning(true); setRunResult(null); setErr("");
    try {
      const r = await post(`/semantic/${connId}/benchmarks/run`, {});
      setRunResult(r);
    } catch (e: unknown) { setErr(String(e)); }
    finally { setRunning(false); }
  }

  function startEdit(c: BenchmarkCase) {
    setEditId(c.id);
    setForm({
      id: c.id, question: c.question,
      expected_cols: c.expected_cols.join(", "),
      must_contain: c.must_contain.join(", "),
      must_not_contain: c.must_not_contain.join(", "),
      notes: c.notes,
    });
  }

  const resultMap: Record<string, CaseResult> = {};
  if (runResult) for (const r of runResult.results) resultMap[r.case_id] = r;

  return (
    <div>
      {/* Run summary */}
      {runResult && (
        <div style={{ marginBottom: 20, padding: "12px 16px", borderRadius: 8, background: "var(--bg-1)", border: `1px solid ${runResult.failed === 0 ? "#10b981" : "#f59e0b"}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: runResult.failed === 0 ? "#10b981" : "#f59e0b" }}>
              {runResult.score}%
            </span>
            <span style={{ fontSize: 12, color: "var(--t2)" }}>
              {runResult.passed}/{runResult.total} cases passed
              {runResult.failed > 0 && <span style={{ color: "#f87171" }}> · {runResult.failed} failed</span>}
            </span>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <Btn onClick={() => { setEditId("__new__"); setForm(EMPTY_CASE); }}>+ Add Case</Btn>
        <Btn variant="ghost" onClick={runBenchmarks} disabled={running || cases.length === 0}>
          {running ? "Running…" : "▶ Run All"}
        </Btn>
      </div>

      {loading && <p style={{ fontSize: 12, color: "var(--t4)" }}>Loading…</p>}
      <ErrorMsg msg={err} />
      {!loading && cases.length === 0 && (
        <EmptyState text="No benchmark cases. Add gold questions to detect SQL regressions automatically." />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {cases.map(c => {
          const res = resultMap[c.id];
          return (
            <div key={c.id} style={{
              border: `1px solid ${res ? (res.passed ? "#10b98133" : "#f87171aa") : "var(--border-0, #2a2a2a)"}`,
              borderRadius: 8, padding: "10px 14px",
            }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                {res && (
                  <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 10, background: res.passed ? "#10b981" : "#ef4444", color: "#fff", fontWeight: 600, marginTop: 2, whiteSpace: "nowrap" }}>
                    {res.passed ? "PASS" : "FAIL"}
                  </span>
                )}
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)", margin: 0 }}>{c.question}</p>
                  {c.notes && <p style={{ fontSize: 11, color: "var(--t4)", margin: "3px 0 0" }}>{c.notes}</p>}
                  {/* Failure details */}
                  {res && !res.passed && (
                    <div style={{ marginTop: 6 }}>
                      {res.failures.map((f, i) => (
                        <p key={i} style={{ fontSize: 11, color: "#f87171", margin: "2px 0" }}>• {f}</p>
                      ))}
                      {res.error && <p style={{ fontSize: 11, color: "#f87171", margin: "2px 0" }}>Error: {res.error}</p>}
                      <button
                        style={{ fontSize: 10, color: "var(--t4)", background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 4 }}
                        onClick={() => setExpandedResult(expandedResult === c.id ? null : c.id)}
                      >
                        {expandedResult === c.id ? "▲ hide SQL" : "▼ show generated SQL"}
                      </button>
                      {expandedResult === c.id && (
                        <pre style={{ fontSize: 10, color: "var(--t3)", marginTop: 6, background: "var(--bg-1)", padding: "8px", borderRadius: 5, overflow: "auto", maxHeight: 200 }}>
                          {res.generated_sql}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <Btn variant="ghost" onClick={() => startEdit(c)}>Edit</Btn>
                  <Btn variant="danger" onClick={() => deleteCase(c.id)}>Delete</Btn>
                </div>
              </div>
              {/* Constraints badges */}
              <div style={{ marginTop: 6, paddingLeft: res ? 0 : 0, display: "flex", flexWrap: "wrap", gap: 4 }}>
                {c.expected_cols.map(col => (
                  <span key={col} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "#3b82f620", color: "#60a5fa" }}>col:{col}</span>
                ))}
                {c.must_contain.map(s => (
                  <span key={s} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "#10b98120", color: "#6ee7b7" }}>✓ {s}</span>
                ))}
                {c.must_not_contain.map(s => (
                  <span key={s} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "#ef444420", color: "#fca5a5" }}>✗ {s}</span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Edit/Add modal */}
      {editId !== null && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={e => { if (e.target === e.currentTarget) setEditId(null); }}>
          <div style={{ background: "var(--bg-0, #111)", border: "1px solid var(--border-0, #2a2a2a)", borderRadius: 10, padding: 20, width: 520 }}>
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "var(--t1)" }}>
              {editId === "__new__" ? "New Benchmark Case" : "Edit Case"}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Input value={form.question} onChange={v => setForm(f => ({ ...f, question: v }))} placeholder="Natural-language question *" />
              <Input value={form.expected_cols}    onChange={v => setForm(f => ({ ...f, expected_cols: v }))}    placeholder="Expected columns (comma-separated, optional)" />
              <Input value={form.must_contain}     onChange={v => setForm(f => ({ ...f, must_contain: v }))}     placeholder="SQL must contain (comma-separated, e.g. NULLIF, RANK)" />
              <Input value={form.must_not_contain} onChange={v => setForm(f => ({ ...f, must_not_contain: v }))} placeholder="SQL must NOT contain (e.g. AVG(" />
              <Input value={form.notes}            onChange={v => setForm(f => ({ ...f, notes: v }))}            placeholder="Notes / what this case verifies" />
            </div>
            <ErrorMsg msg={err} />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Btn onClick={saveCase} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
              <Btn variant="ghost" onClick={() => setEditId(null)}>Cancel</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main Panel
// ═══════════════════════════════════════════════════════════════════════════════

const TABS = ["Annotations", "Knowledge", "Benchmarks"];

export function SemanticLayerPanel({ connectionId }: { connectionId: string }) {
  const [activeTab, setActiveTab] = useState<string>("Annotations");

  if (!connectionId) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t4)", fontSize: 13 }}>
        Select a connection to manage its semantic layer.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "16px 24px 0", borderBottom: "1px solid var(--border-0, #2a2a2a)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 4 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)", margin: 0 }}>Semantic Layer</h2>
          <span style={{ fontSize: 11, color: "var(--t4)" }}>connection: {connectionId}</span>
        </div>
        <p style={{ fontSize: 11, color: "var(--t4)", margin: "0 0 12px" }}>
          Business descriptions, metric definitions, and SQL quality benchmarks — injected directly into every AI prompt.
        </p>
        <TabBar tabs={TABS} active={activeTab} onChange={setActiveTab} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "auto", padding: "0 24px 24px" }}>
        <div style={{ paddingTop: 16 }}>
          {activeTab === "Annotations" && <AnnotationsTab connId={connectionId} />}
          {activeTab === "Knowledge"   && <KnowledgeTab   connId={connectionId} />}
          {activeTab === "Benchmarks"  && <BenchmarksTab  connId={connectionId} />}
        </div>
      </div>
    </div>
  );
}
