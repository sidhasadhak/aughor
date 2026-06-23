"use client";

/**
 * Catalog Explorer — Business Glossary (Databricks-style "Comments").
 *
 * Surfaces the institutional knowledge the agent already uses (table/column
 * descriptions) as editable comments on a table. View + edit the table comment and
 * each column's comment; values/caveats (set elsewhere) show read-only for context.
 * Wires to /glossary (GET) and /glossary/{table}[/{column}] (PUT).
 *
 * The glossary is keyed by bare table name (a global store), so pass the bare name.
 */
import { useEffect, useState } from "react";
import {
  getGlossary, updateTableGlossary, updateColumnGlossary,
  type GlossaryTable,
} from "@/lib/api";

function EditableComment({ value, placeholder, onSave }: {
  value: string; placeholder: string; onSave: (v: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(value); }, [value]);

  if (!editing) {
    return (
      <div onClick={() => setEditing(true)}
        style={{ fontSize: 12, lineHeight: 1.5, cursor: "text", padding: "4px 6px", borderRadius: 4,
          color: value ? "var(--t2)" : "var(--t4)", border: "1px solid transparent" }}
        onMouseEnter={e => (e.currentTarget.style.border = "1px solid var(--b1)")}
        onMouseLeave={e => (e.currentTarget.style.border = "1px solid transparent")}>
        {value || placeholder}
      </div>
    );
  }
  const save = async () => {
    setBusy(true);
    try { await onSave(draft.trim()); setEditing(false); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <textarea className="aug-input" autoFocus value={draft} disabled={busy}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save(); if (e.key === "Escape") setEditing(false); }}
        style={{ fontSize: 12, lineHeight: 1.5, minHeight: 54, resize: "vertical", width: "100%" }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button className="aug-btn aug-btn-sm aug-btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        <button className="aug-btn aug-btn-sm" disabled={busy} onClick={() => { setDraft(value); setEditing(false); }}>Cancel</button>
        <span style={{ fontSize: 10, color: "var(--t4)", alignSelf: "center" }}>⌘↵ to save · Esc to cancel</span>
      </div>
    </div>
  );
}

export function GlossaryPanel({ table, columns }: { table: string; columns: string[] }) {
  const [entry, setEntry] = useState<GlossaryTable>({});
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    getGlossary()
      .then(g => setEntry((g.tables ?? {})[table] ?? {}))
      .catch(() => setEntry({}))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [table]);

  if (loading) return <p style={{ padding: 20, fontSize: 12, color: "var(--t4)" }}>Loading…</p>;

  const colEntry = (c: string) => (entry.columns ?? {})[c] ?? {};

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
      {/* table-level comment */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, marginBottom: 6 }}>Table comment</div>
        <EditableComment value={entry.description ?? ""} placeholder="Add a comment to describe this table…"
          onSave={async v => { await updateTableGlossary(table, v); load(); }} />
        {(entry.grain || (entry.joins && entry.joins.length > 0)) && (
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--t4)", display: "flex", flexDirection: "column", gap: 3 }}>
            {entry.grain && <span><b style={{ color: "var(--t3)" }}>Grain:</b> {entry.grain}</span>}
            {entry.joins?.map((j, i) => <span key={i} style={{ fontFamily: "var(--mono, monospace)" }}>{j}</span>)}
          </div>
        )}
      </div>

      {/* column comments */}
      <div style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, marginBottom: 4 }}>Columns</div>
      {columns.length === 0 && <p style={{ fontSize: 12, color: "var(--t4)" }}>No columns.</p>}
      {columns.map(c => {
        const ce = colEntry(c);
        return (
          <div key={c} style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "9px 0", borderBottom: "0.5px solid var(--b0)", alignItems: "start" }}>
            <div style={{ minWidth: 0 }}>
              <span style={{ fontSize: 12, color: "var(--t1)", fontWeight: 500 }}>{c}</span>
              {ce.values && <div style={{ fontSize: 10, color: "var(--t4)", marginTop: 2 }}>values: {ce.values}</div>}
              {ce.caveats && <div style={{ fontSize: 10, color: "var(--amb4)", marginTop: 2 }}>⚠ {ce.caveats}</div>}
            </div>
            <EditableComment value={ce.description ?? ""} placeholder="Add a comment…"
              onSave={async v => { await updateColumnGlossary(table, c, v); load(); }} />
          </div>
        );
      })}
    </div>
  );
}
