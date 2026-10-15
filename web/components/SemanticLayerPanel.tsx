"use client";

/**
 * The Semantic Layer — a connection's declared meaning, in five tabs, redone to `aughor-v2/CLARITY.md` (2026-10-12):
 *  1. Metrics     — governed definitions: what is approved and measured, what waits for review (the landing tab;
 *                   `MetricsPanel`)
 *  2. Annotations — what a table or column means, read into every prompt
 *  3. Knowledge   — business facts: metric definitions, synonyms, join rules, notes
 *  4. Benchmarks  — questions with rules for the SQL they should get, run to catch a regression
 *  5. Import      — the intake lane (PX-3): bring knowledge in from files, sheets, wikis or usage, review the plan,
 *                   accept per object, export back
 *
 * One row carries the tabs and, at its right end, the scope — connection › dataset (› table, where a tab reads one);
 * each tab is a page of cards below it. Every tab reads first: a form opens only when a person asks for one.
 *
 * The active tab deep-links as `?semtab=` — the shell's URL sync preserves params it does not own, so this survives
 * its rewrites (§3.14's "a door ships with its deep link").
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { Card, Chip, Empty, MUTED, NUM, Page, ROW, RULE } from "@/components/clarity/kit";
import { IntakePanel } from "@/components/intake/IntakePanel";
import { MetricsPanel } from "@/components/MetricsPanel";
import { FoldLine, Sql, ToolsMenu } from "@/components/semantic/parts";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { Input as UiInput } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { TabStrip } from "@/components/ui/tab-strip";
import { Textarea } from "@/components/ui/textarea";
import { type RichSchema } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { countNoun, formatCount } from "@/lib/format";
import { useRichSchema } from "@/lib/schema-context";
import { defaultSchema, rememberSchema } from "@/lib/schemaChoice";

// ── Fetch helpers ──────────────────────────────────────────────────────────────────────────────────────────────────

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`${getApiBase()}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

function put(path: string, body: unknown)    { return apiFetch(path, { method: "PUT",    body: JSON.stringify(body) }); }
function post(path: string, body: unknown)   { return apiFetch(path, { method: "POST",   body: JSON.stringify(body) }); }
function del(path: string)                   { return apiFetch(path, { method: "DELETE" }); }

// ── Shared pieces ──────────────────────────────────────────────────────────────────────────────────────────────────

function Input({ value, onChange, placeholder, multiline, hint, mono, label }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
  multiline?: boolean; hint?: string; mono?: boolean; label?: string;
}) {
  const mono_ = mono ? { fontFamily: "var(--font-mono)" } : undefined;
  const field = multiline
    ? <Textarea rows={3} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} aria-label={label}
        style={{ width: "100%", ...mono_ }} />
    : <UiInput value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} aria-label={label}
        style={{ width: "100%", ...mono_ }} />;
  if (!label && !hint) return field;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      {label && <label className="aug-fs-xs" style={{ color: "var(--t2)" }}>{label}</label>}
      {field}
      {hint && <span className="aug-fs-xs" style={MUTED}>{hint}</span>}
    </div>
  );
}

function Select({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label?: string;
}) {
  return (
    <SelectField value={value} onChange={e => onChange(e.target.value)} aria-label={label}>
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </SelectField>
  );
}

function ErrorMsg({ msg }: { msg: string }) {
  if (!msg) return null;
  return <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "6px 0 0" }}>{msg}</p>;
}

/** The one line under a card's label that says what the tab is for. */
function Subtitle({ children }: { children: ReactNode }) {
  return <p className="aug-fs-sm" style={{ ...MUTED, margin: "-2px 0 10px" }}>{children}</p>;
}

/** A form a person asked for, in a dialog: its name, its fields, Save and Cancel. */
function FormDialog({ open, title, onClose, onSave, saving, error, width = "480px", children }: {
  open: boolean; title: string; onClose: () => void; onSave: () => void; saving: boolean; error: string;
  width?: string; children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose(); }}>
      <DialogContent maxWidth={width} aria-describedby={undefined}>
        <DialogTitle>{title}</DialogTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{children}</div>
        <ErrorMsg msg={error} />
        <div style={ROW}>
          <Button size="sm" onClick={onSave} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** A row's two tools: Edit, and Delete. */
function RowTools({ onEdit, onDelete, what }: { onEdit: () => void; onDelete: () => void; what: string }) {
  return (
    <span style={{ ...ROW, flexWrap: "nowrap", gap: 4, flexShrink: 0 }}>
      <Button size="xs" variant="ghost" onClick={onEdit} aria-label={`Edit ${what}`}>Edit</Button>
      <Button size="xs" variant="ghost" onClick={onDelete} aria-label={`Delete ${what}`} style={{ color: "var(--red4)" }}>Delete</Button>
    </span>
  );
}

// ── Tag list (comma-separated) ─────────────────────────────────────────────────────────────────────────────────────

function tagList(s: string): string[] { return s.split(",").map(t => t.trim()).filter(Boolean); }

// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
// Annotations
// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

interface TableAnnotations {
  description?: string;
  columns?: Record<string, { description?: string }>;
}

function AnnotationsTab({ connId, scopeTable }: { connId: string; scopeTable: string }) {
  const [data, setData]       = useState<Record<string, TableAnnotations>>({});
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");
  /** The read failed: said, with Retry — never shown as "No annotations yet". */
  const [readErr, setReadErr] = useState("");

  // Edit form state
  const [editingTable, setEditingTable]   = useState<string | null>(null);
  const [editingColumn, setEditingColumn] = useState<string | null>(null);
  const [editDesc, setEditDesc]           = useState("");
  const [saving, setSaving]               = useState(false);

  // New annotation form — behind "Add annotation"
  const [adding, setAdding]       = useState(false);
  const [newTable, setNewTable]   = useState("");
  const [newCol, setNewCol]       = useState("");
  const [newDesc, setNewDesc]     = useState("");
  const [addErr, setAddErr]       = useState("");

  // Prefill the table field from the active scope selection
  useEffect(() => { if (scopeTable) setNewTable(scopeTable); }, [scopeTable]);

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try {
      const d = await apiFetch(`/semantic/${connId}/annotations`);
      setData(d); setReadErr("");
    } catch (e: unknown) {
      setReadErr(e instanceof Error ? e.message : String(e));
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
      setNewTable(""); setNewCol(""); setNewDesc(""); setAdding(false);
      await load();
    } catch (e: unknown) { setAddErr(String(e)); }
  }

  const allTables = Object.keys(data);
  const tables = scopeTable ? allTables.filter(t => t === scopeTable) : allTables;
  const columns = tables.reduce((n, t) => n + Object.keys(data[t]?.columns ?? {}).length, 0);

  return (
    <Page testId="semantic-annotations">
      <Card label="Annotations" testId="annotations" right={<>
        {tables.length > 0 && <span style={NUM}>{`${countNoun(tables.length, "table")} · ${countNoun(columns, "column")}`}</span>}
        <Button size="xs" variant="ghost" onClick={() => setAdding(true)} disabled={adding}><Icon name="plus" size={12} />Add annotation</Button>
      </>}>
        <Subtitle>What a table or column means in your business — read into every prompt, so answers use your words.</Subtitle>

        {adding && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "10px 0 14px" }} data-testid="annotation-new">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
              <Input value={newTable} onChange={setNewTable} label="Table *" placeholder="e.g. subscriptions" />
              <Input value={newCol} onChange={setNewCol} label="Column" placeholder="e.g. plan_type — blank for the whole table" />
            </div>
            <Input value={newDesc} onChange={setNewDesc} label="Business description *" multiline
              placeholder="e.g. One row per active subscription. plan_type is one of free / pro / enterprise; cancelled rows are excluded from this table."
              hint="What it represents, its grain (one row per…), and any gotchas." />
            <ErrorMsg msg={addErr} />
            <div style={ROW}>
              <Button size="sm" onClick={addAnnotation}>Add</Button>
              <Button size="sm" variant="ghost" onClick={() => { setAdding(false); setAddErr(""); }}>Cancel</Button>
            </div>
          </div>
        )}

        {loading && <Loading what="tables" />}
        <ErrorMsg msg={err} />
        {readErr && <ReadFailed what="the annotations" error={readErr} onRetry={load} />}
        {!loading && !readErr && tables.length === 0 && (
          <Empty>{scopeTable ? `No annotations for ${scopeTable} yet.` : "No annotations yet."}</Empty>
        )}

        {tables.map((table, i) => (
          <div key={table} data-testid="annotation-table" style={{ padding: "8px 0", ...(i ? RULE : {}) }}>
            <div style={{ ...ROW, flexWrap: "nowrap", gap: 12 }}>
              <span className="aug-fs-chrome" style={{ fontFamily: "var(--font-mono)", color: "var(--t1)", fontWeight: 500, flexShrink: 0 }}>{table}</span>
              <span className="aug-fs-sm" style={{ flex: 1, minWidth: 0, color: data[table]?.description ? "var(--t2)" : "var(--t3)" }}>
                {data[table]?.description || "no description of the table"}
              </span>
              <RowTools what={table}
                onEdit={() => { setEditingTable(table); setEditingColumn(null); setEditDesc(data[table]?.description ?? ""); }}
                onDelete={() => deleteAnnotation(table)} />
            </div>
            {Object.entries(data[table]?.columns ?? {}).map(([col, colData]) => (
              <div key={col} style={{ ...ROW, flexWrap: "nowrap", gap: 12, padding: "4px 0 0 18px" }}>
                <span className="aug-fs-sm" style={{ fontFamily: "var(--font-mono)", color: "var(--t2)", minWidth: 120, flexShrink: 0 }}>{col}</span>
                <span className="aug-fs-sm" style={{ flex: 1, minWidth: 0, color: "var(--t2)" }}>{colData.description}</span>
                <RowTools what={`${table}.${col}`}
                  onEdit={() => { setEditingTable(table); setEditingColumn(col); setEditDesc(colData.description ?? ""); }}
                  onDelete={() => deleteAnnotation(table, col)} />
              </div>
            ))}
          </div>
        ))}
      </Card>

      <FormDialog open={!!editingTable} title={`Edit ${editingColumn ? `${editingTable}.${editingColumn}` : editingTable ?? ""}`}
        onClose={() => { setEditingTable(null); setEditingColumn(null); }} onSave={saveEdit} saving={saving} error="" width="440px">
        <Input value={editDesc} onChange={setEditDesc} placeholder="Business description" multiline />
      </FormDialog>
    </Page>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
// Knowledge
// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

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
const KIND_WORD: Record<string, string> = Object.fromEntries(KNOWLEDGE_KINDS.map(k => [k.value, k.label.toLowerCase()]));

// Per-kind sample text so users see exactly what a good entry looks like.
const KIND_HINTS: Record<string, { title: string; body: string; hint: string }> = {
  metric:  { title: "Monthly Recurring Revenue (MRR)",
             body: "SUM(amount) FILTER (WHERE status = 'active') over the subscriptions table, grouped by month. Excludes trials and one-off charges.",
             hint: "Define the formula in words or SQL so the AI computes it consistently." },
  synonym: { title: "“Revenue” means net bookings",
             body: "When a user says revenue, churn, or ARR, map it to: net bookings = gross_amount − refunds. Do not use gross_amount alone.",
             hint: "Map the words your team uses to the columns/metrics they actually mean." },
  rule:    { title: "Always exclude test accounts",
             body: "Every query against orders/customers must filter is_test = false. Internal accounts have email ending in @acme.dev.",
             hint: "A business rule the AI must always honor when querying." },
  join:    { title: "orders → customers join",
             body: "JOIN customers ON orders.customer_id = customers.id. One customer has many orders. Never join on email.",
             hint: "Tell the AI the correct keys and cardinality so it joins safely." },
  note:    { title: "Fiscal year starts in February",
             body: "Our fiscal year runs Feb 1 – Jan 31. “FY2026” = Feb 2025 through Jan 2026. Use this for all year-over-year analysis.",
             hint: "Any other context that helps the AI reason about your data." },
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
  const [note, setNote]           = useState("");
  /** The read failed: said, with Retry — never shown as "No knowledge entries yet". */
  const [readErr, setReadErr]     = useState("");

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try { setEntries(await apiFetch(`/semantic/${connId}/knowledge`)); setReadErr(""); }
    catch (e: unknown) { setReadErr(e instanceof Error ? e.message : String(e)); }
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
      setEditId(null); setErr(""); await load();
    } catch (e: unknown) { setErr(String(e)); }
    finally { setSaving(false); }
  }

  async function deleteEntry(id: string) {
    try { await del(`/semantic/${connId}/knowledge/${id}`); await load(); }
    catch (e: unknown) { setErr(String(e)); }
  }

  async function rebuildIndex() {
    setRebuilding(true); setNote("");
    try {
      const r = await post(`/semantic/${connId}/knowledge/rebuild-index`, {});
      setNote(`Re-indexed ${countNoun(Number(r.indexed) || 0, "entry", "entries")}.`);
    } catch (e: unknown) { setErr(String(e)); }
    finally { setRebuilding(false); }
  }

  return (
    <Page testId="semantic-knowledge">
      <Card label="Knowledge" testId="knowledge" right={<>
        {entries.length > 0 && <span style={NUM}>{countNoun(entries.length, "entry", "entries")}</span>}
        <Button size="xs" variant="ghost" onClick={startAdd}><Icon name="plus" size={12} />Add entry</Button>
        <ToolsMenu testId="knowledge-tools" items={[
          { label: rebuilding ? "Rebuilding…" : "Rebuild the search index", onSelect: rebuildIndex, disabled: rebuilding,
            title: "Re-reads every entry into the index answers retrieve them from" },
        ]} />
      </>}>
        <Subtitle>Business facts — metric definitions, synonyms, join rules — the most relevant read into each answer.</Subtitle>
        {note && <p className="aug-fs-sm" style={{ color: "var(--grn4)", margin: "0 0 8px" }}>{note}</p>}
        {loading && <Loading what="glossary entries" />}
        {editId === null && <ErrorMsg msg={err} />}
        {readErr && <ReadFailed what="the knowledge entries" error={readErr} onRetry={load} />}
        {!loading && !readErr && entries.length === 0 && <Empty>No knowledge entries yet.</Empty>}

        {entries.map((e, i) => (
          <div key={e.id} data-testid="knowledge-entry" style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", gap: 12,
            padding: "8px 0", ...(i ? RULE : {}) }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={ROW}>
                <span className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{e.title}</span>
                <Chip>{KIND_WORD[e.kind] ?? e.kind}</Chip>
                {e.tags.map(t => <span key={t} className="aug-fs-xs" style={MUTED}>#{t}</span>)}
              </div>
              <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "2px 0 0", lineHeight: 1.5 }}>{e.body}</p>
            </div>
            <RowTools what={e.title} onEdit={() => startEdit(e)} onDelete={() => deleteEntry(e.id)} />
          </div>
        ))}
      </Card>

      <FormDialog open={editId !== null} title={editId === "__new__" ? "New knowledge entry" : "Edit entry"}
        onClose={() => { setEditId(null); setErr(""); }} onSave={saveEntry} saving={saving} error={err}>
        <Input value={form.title} onChange={v => setForm(f => ({ ...f, title: v }))} label="Title / name *"
          placeholder={KIND_HINTS[form.kind].title} hint="A short name the AI can match the user's question against" />
        <Input value={form.body} onChange={v => setForm(f => ({ ...f, body: v }))} label="Definition or rule *" multiline
          mono={form.kind === "metric" || form.kind === "join"}
          placeholder={KIND_HINTS[form.kind].body} hint={KIND_HINTS[form.kind].hint} />
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 8, alignItems: "start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label className="aug-fs-xs" style={{ color: "var(--t2)" }}>Kind</label>
            <Select value={form.kind} onChange={v => setForm(f => ({ ...f, kind: v }))} options={KNOWLEDGE_KINDS} label="Kind" />
          </div>
          <Input value={form.tags} onChange={v => setForm(f => ({ ...f, tags: v }))} label="Tags"
            placeholder="e.g. revenue, finance, north-star" hint="Comma-separated — helps grouping & retrieval" />
        </div>
      </FormDialog>
    </Page>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
// Benchmarks
// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

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
  /** The read failed: said, with Retry — never shown as "No questions yet". */
  const [readErr, setReadErr]   = useState("");

  const load = useCallback(async () => {
    if (!connId) return;
    setLoading(true);
    try { setCases(await apiFetch(`/semantic/${connId}/benchmarks`)); setReadErr(""); }
    catch (e: unknown) { setReadErr(e instanceof Error ? e.message : String(e)); }
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
      setEditId(null); setErr(""); await load();
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
    <Page testId="semantic-benchmarks">
      <Card label="Benchmarks" testId="benchmarks" right={<>
        {cases.length > 0 && <span style={NUM}>{countNoun(cases.length, "question")}</span>}
        <Chip title="Each question asks the model for its SQL, then runs it on the warehouse">1 model call per question</Chip>
        <Button size="xs" variant="ghost" onClick={() => { setEditId("__new__"); setForm(EMPTY_CASE); }}>
          <Icon name="plus" size={12} />Add question
        </Button>
        <Button size="xs" variant="secondary" onClick={runBenchmarks} disabled={running || cases.length === 0}>
          <Icon name="run" size={12} />{running ? "Running…" : "Run all"}
        </Button>
      </>}>
        <Subtitle>Questions with rules for the SQL they should get — run them after a change to catch a regression.</Subtitle>

        {runResult && (
          <div style={{ ...ROW, padding: "0 0 10px" }} data-testid="benchmark-score">
            <span className="aug-fs-display" style={{ ...NUM, fontWeight: 600, color: runResult.failed === 0 ? "var(--grn4)" : "var(--amb4)" }}>
              {runResult.score}%
            </span>
            <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{`${formatCount(runResult.passed)} of ${formatCount(runResult.total)} passed`}</span>
            {runResult.failed > 0 && <Chip tone="down">{`${formatCount(runResult.failed)} failed`}</Chip>}
          </div>
        )}

        {loading && <Loading what="test questions" />}
        {editId === null && <ErrorMsg msg={err} />}
        {readErr && <ReadFailed what="the benchmark questions" error={readErr} onRetry={load} />}
        {!loading && !readErr && cases.length === 0 && <Empty>No questions yet.</Empty>}

        {cases.map((c, i) => {
          const res = resultMap[c.id];
          return (
            <div key={c.id} data-testid="benchmark-case" style={{ padding: "8px 0", ...(i ? RULE : {}) }}>
              <div style={{ ...ROW, flexWrap: "nowrap", alignItems: "flex-start", gap: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={ROW}>
                    {res && <Chip tone={res.passed ? "up" : "down"}>{res.passed ? "✓ passed" : "✕ failed"}</Chip>}
                    <span className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{c.question}</span>
                  </div>
                  {c.notes && <p className="aug-fs-sm" style={{ ...MUTED, margin: "2px 0 0" }}>{c.notes}</p>}
                  {(c.expected_cols.length + c.must_contain.length + c.must_not_contain.length) > 0 && (
                    <div style={{ ...ROW, gap: 4, marginTop: 6 }}>
                      {c.expected_cols.map(col => <Chip key={`col-${col}`} tone="accent" title="A column the answer should return">{`returns ${col}`}</Chip>)}
                      {c.must_contain.map(s => <Chip key={`has-${s}`} tone="up" title="The SQL must contain it">{`✓ ${s}`}</Chip>)}
                      {c.must_not_contain.map(s => <Chip key={`not-${s}`} tone="down" title="The SQL must never contain it">{`✕ ${s}`}</Chip>)}
                    </div>
                  )}
                  {res && !res.passed && (
                    <div style={{ marginTop: 6 }}>
                      {res.failures.map((f, j) => (
                        <p key={j} className="aug-fs-sm" style={{ color: "var(--red4)", margin: "2px 0" }}>• {f}</p>
                      ))}
                      {res.error && <p className="aug-fs-sm" style={{ color: "var(--red4)", margin: "2px 0" }}>Error: {res.error}</p>}
                      <FoldLine open={expandedResult === c.id} onToggle={() => setExpandedResult(expandedResult === c.id ? null : c.id)}>
                        The SQL it got
                      </FoldLine>
                      {expandedResult === c.id && <div style={{ marginTop: 6 }}><Sql>{res.generated_sql}</Sql></div>}
                    </div>
                  )}
                </div>
                <RowTools what={c.question} onEdit={() => startEdit(c)} onDelete={() => deleteCase(c.id)} />
              </div>
            </div>
          );
        })}
      </Card>

      <FormDialog open={editId !== null} title={editId === "__new__" ? "New benchmark question" : "Edit question"} width="520px"
        onClose={() => { setEditId(null); setErr(""); }} onSave={saveCase} saving={saving} error={err}>
        <Input value={form.question} onChange={v => setForm(f => ({ ...f, question: v }))} label="Question *"
          placeholder="e.g. What was our refund rate by month last year?"
          hint="A real question you'd ask in chat — the AI will generate SQL for it and we check the result." />
        <Input value={form.expected_cols}    onChange={v => setForm(f => ({ ...f, expected_cols: v }))} label="Expected columns" mono
          placeholder="e.g. month, refund_rate"
          hint="Comma-separated columns the answer should return. Optional." />
        <Input value={form.must_contain}     onChange={v => setForm(f => ({ ...f, must_contain: v }))} label="SQL must contain" mono
          placeholder="e.g. NULLIF, GROUP BY"
          hint="Comma-separated snippets that must appear — e.g. NULLIF to guard divide-by-zero." />
        <Input value={form.must_not_contain} onChange={v => setForm(f => ({ ...f, must_not_contain: v }))} label="SQL must NOT contain" mono
          placeholder="e.g. is_test = true, SELECT *"
          hint="Comma-separated snippets that should never appear — catches common mistakes." />
        <Input value={form.notes}            onChange={v => setForm(f => ({ ...f, notes: v }))} label="Notes"
          placeholder="e.g. Refund rate must divide refunds by paid orders, not order count."
          hint="What this case verifies — for your team's reference." />
      </FormDialog>
    </Page>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
// The panel
// ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

// Metrics leads: it is the governed answer to "what does this number mean", and the one tab whose contents the AI
// reuses in every chart and answer. It was third, behind two tabs of annotation, so the definitions a connection already
// carried were the last thing anyone saw.
const TABS = ["Metrics", "Annotations", "Knowledge", "Benchmarks", "Import"];
//: The landing tab, and the one that carries no `?semtab=`. Derived from TABS so reordering the array cannot leave the
//: default pointing at a tab that moved.
const DEFAULT_TAB = TABS[0];

// ── Scope (connection › dataset › table) ───────────────────────────────────────────────────────────────────────────

interface ConnOption { id: string; name: string }

/** Which connection's meaning this is — any connection, not only the app's chosen one — then its dataset, and its table
 *  where the tab reads one (Annotations). */
function Scope({
  connections, activeConn, schemas, tables, scopeSchema, scopeTable, onConn, onSchema, onTable, loading, withTable,
}: {
  connections: ConnOption[];
  activeConn: string;
  schemas: string[]; tables: string[];
  scopeSchema: string; scopeTable: string;
  onConn: (v: string) => void;
  onSchema: (v: string) => void; onTable: (v: string) => void;
  loading: boolean;
  withTable: boolean;
}) {
  const arrow = <span aria-hidden className="aug-fs-sm" style={MUTED}>›</span>;
  return (
    <span data-testid="semantic-scope" style={{ ...ROW, flexWrap: "nowrap", gap: 6 }}>
      <Select value={activeConn} onChange={onConn} label="Connection"
        options={connections.length
          ? connections.map(c => ({ value: c.id, label: c.name }))
          : [{ value: activeConn, label: activeConn }]} />
      {schemas.length > 1 && (
        <>
          {arrow}
          <Select value={scopeSchema} onChange={onSchema} label="Dataset"
            options={[{ value: "", label: "All schemas" }, ...schemas.map(s => ({ value: s, label: s }))]} />
        </>
      )}
      {withTable && (
        <>
          {arrow}
          <Select value={scopeTable} onChange={onTable} label="Table"
            options={[{ value: "", label: loading ? "Loading…" : tables.length ? "All tables" : "No tables loaded" },
              ...tables.map(t => ({ value: t, label: t }))]} />
        </>
      )}
    </span>
  );
}

export function SemanticLayerPanel({ connectionId, connName, connections = [] }: {
  connectionId: string; connName?: string; connections?: ConnOption[];
}) {
  // The tab deep-links as ?semtab= (lowercased). Read once at mount; written on change via replaceState — the shell's
  // URL sync starts from location.search and only touches its own params, so semtab survives its rewrites.
  const [activeTab, setActiveTab] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_TAB;
    const want = new URLSearchParams(window.location.search).get("semtab") ?? "";
    return TABS.find(t => t.toLowerCase() === want.toLowerCase()) ?? DEFAULT_TAB;
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (activeTab === DEFAULT_TAB) params.delete("semtab");
    else params.set("semtab", activeTab.toLowerCase());
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, [activeTab]);
  const [scopeSchema, setScopeSchema] = useState("");
  const [scopeTable, setScopeTable]   = useState("");

  // The semantic layer is an ORG-level surface: the active connection here is independent of the app's globally-
  // selected connection. It defaults to the current selection but the user can browse any connection's semantic layer.
  const [activeConn, setActiveConn] = useState(connectionId);
  // The shell's connection is the workspace's: when it changes — a workspace switch, a reselect — this panel follows
  // it; its own picker still moves within the workspace. Until 2026-10-15 it filled only an EMPTY choice, so a panel
  // visited on one workspace kept that connection after a switch: the cockpit on LuxExperience, the Metrics tab still
  // on Workspace's sixteen rows, and the scope's picker blank because its connection was no longer in the list.
  useEffect(() => { if (connectionId) setActiveConn(connectionId); }, [connectionId]);

  // Fetch the rich schema for whichever connection is active in this panel.
  const [schema, setSchema] = useState<RichSchema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const { schema: sharedSchema, loading: sharedLoading } = useRichSchema(activeConn);
  useEffect(() => {
    // Mirrors the shared per-connection cache into this panel's existing state, so every consumer below is untouched.
    // The cancelled-flag dance is gone with the fetch that needed it — the cache owns request lifecycle now.
    setSchema(sharedSchema);
    setSchemaLoading(sharedLoading);
  }, [activeConn, sharedSchema, sharedLoading]);

  // Reset table/schema scope whenever the connection changes
  useEffect(() => { setScopeSchema(""); setScopeTable(""); }, [activeConn]);

  // Derive schema/table options from the live rich schema. Tables named "schema.table" are split so the schema grain is
  // selectable.
  const { schemas, tables } = useMemo(() => {
    const names = (schema?.tables ?? []).map(t => t.name);
    const schemaSet = new Set<string>();
    for (const n of names) { if (n.includes(".")) schemaSet.add(n.split(".")[0]); }
    const sortedSchemas = [...schemaSet].sort();
    const filtered = scopeSchema
      ? names.filter(n => n.startsWith(`${scopeSchema}.`))
      : names;
    return { schemas: sortedSchemas, tables: [...filtered].sort() };
  }, [schema, scopeSchema]);

  // Reset table selection if it falls outside the chosen schema
  useEffect(() => {
    if (scopeTable && !tables.includes(scopeTable)) setScopeTable("");
  }, [tables, scopeTable]);

  // Each dataset has its own metrics. "All schemas" on a connection of several lists EVERY dataset's, each row saying
  // which (the user, 2026-10-07: "when I select all schemas … all the metrics across all the schemas of the selected
  // connection should be displayed") — it used to quietly show one dataset, the last one chosen, under a banner saying so.
  const metricsSchema = scopeSchema || (schemas.length > 1 ? "*" : defaultSchema(activeConn, schemas));
  useEffect(() => { if (scopeSchema) rememberSchema(activeConn, scopeSchema); }, [activeConn, scopeSchema]);

  if (!activeConn) {
    return (
      <Page testId="semantic-layer">
        <Empty>No connections yet — add one to manage its semantic layer.</Empty>
      </Page>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}
      data-testid="semantic-layer">
      <TabStrip label="Semantic layer views" value={activeTab} onChange={setActiveTab}
        style={{ padding: "10px 22px 0", flexShrink: 0 }}
        tabs={TABS.map(t => ({ id: t, label: t }))}
        trailing={
          <Scope
            connections={connections.length ? connections : (connName ? [{ id: activeConn, name: connName }] : [])}
            activeConn={activeConn}
            schemas={schemas} tables={tables}
            scopeSchema={scopeSchema} scopeTable={scopeTable}
            onConn={setActiveConn}
            onSchema={setScopeSchema} onTable={setScopeTable}
            loading={schemaLoading}
            withTable={activeTab === "Annotations"}
          />
        } />

      {/* Content — keyed on activeConn so each tab reloads when the scope changes */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }} key={activeConn}>
        {activeTab === "Metrics"     && <MetricsPanel connId={activeConn} schema={metricsSchema || undefined} datasets={schemas} />}
        {activeTab === "Annotations" && <AnnotationsTab connId={activeConn} scopeTable={scopeTable} />}
        {activeTab === "Knowledge"   && <KnowledgeTab   connId={activeConn} />}
        {activeTab === "Benchmarks"  && <BenchmarksTab  connId={activeConn} />}
        {activeTab === "Import"      && (
          <Page testId="semantic-import"><IntakePanel connId={activeConn} schema={scopeSchema} /></Page>
        )}
      </div>
    </div>
  );
}
