"use client";

/**
 * Catalog Explorer — Business Glossary (Databricks-style "Comments").
 *
 * Surfaces the institutional knowledge the agent reads AT QUERY TIME and lets a
 * human author it. Everything here is injected into the schema context via
 * `apply_glossary()` before the investigator plans a query, so a good comment,
 * grain note, join hint, value list, or caveat directly steers the agent.
 *
 *  Table level   → description · grain · join hints
 *  Column level  → description · known values · caveats
 *
 * Wires to /glossary (GET) and /glossary/{table}[/{column}] (PUT). The glossary is
 * keyed by bare table name (a global store), so pass the bare name.
 */
import { useEffect, useState } from "react";
import {
  getGlossary, updateTableGlossary, updateColumnGlossary,
  type GlossaryTable,
} from "@/lib/api";

const LABEL: React.CSSProperties = {
  fontSize: 11, color: "var(--t4)", textTransform: "uppercase",
  letterSpacing: "0.07em", fontWeight: 600, marginBottom: 6,
};

/** Inline click-to-edit field (single value). Reused for every annotation. */
function EditableField({ value, placeholder, multiline = true, onSave }: {
  value: string; placeholder: string; multiline?: boolean; onSave: (v: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(value); }, [value]);

  if (!editing) {
    return (
      <div onClick={() => setEditing(true)}
        style={{ fontSize: 12, lineHeight: 1.5, cursor: "text", padding: "4px 6px", borderRadius: 4,
          color: value ? "var(--t2)" : "var(--t4)", border: "1px solid transparent", whiteSpace: "pre-wrap" }}
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
        onKeyDown={e => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save();
          if (e.key === "Enter" && !multiline && !e.shiftKey) { e.preventDefault(); save(); }
          if (e.key === "Escape") setEditing(false);
        }}
        style={{ fontSize: 12, lineHeight: 1.5, minHeight: multiline ? 54 : 32, resize: "vertical", width: "100%" }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button className="aug-btn aug-btn-sm aug-btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        <button className="aug-btn aug-btn-sm" disabled={busy} onClick={() => { setDraft(value); setEditing(false); }}>Cancel</button>
        <span style={{ fontSize: 10, color: "var(--t4)", alignSelf: "center" }}>⌘↵ to save · Esc to cancel</span>
      </div>
    </div>
  );
}

/** A small captioned annotation row (used for column values/caveats and table grain). */
function SubField({ caption, value, placeholder, accent, onSave }: {
  caption: string; value: string; placeholder: string; accent?: string;
  onSave: (v: string) => Promise<void>;
}) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 10, color: accent ?? "var(--t4)", fontWeight: 600, marginBottom: 1 }}>{caption}</div>
      <EditableField value={value} placeholder={placeholder} multiline={false} onSave={onSave} />
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
      {/* Why this matters — the agent reads everything below at query time. */}
      <div style={{
        fontSize: 11, color: "var(--t3)", lineHeight: 1.5, marginBottom: 16,
        padding: "8px 11px", background: "var(--bg-1)", border: "1px solid var(--b1)",
        borderRadius: 6,
      }}>
        These notes are read by the agent <b style={{ color: "var(--t2)" }}>at query time</b> — descriptions,
        grain, join hints, known values, and caveats all steer how investigations are planned.
      </div>

      {/* ── Table level ── */}
      <div style={{ marginBottom: 22 }}>
        <div style={LABEL}>Table comment</div>
        <EditableField value={entry.description ?? ""} placeholder="Describe what this table represents…"
          onSave={async v => { await updateTableGlossary(table, { description: v }); load(); }} />

        <SubField
          caption="Grain — one row per…"
          value={entry.grain ?? ""}
          placeholder="e.g. one row per order line"
          onSave={async v => { await updateTableGlossary(table, { grain: v }); load(); }}
        />

        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 10, color: "var(--t4)", fontWeight: 600, marginBottom: 1 }}>Join hints — one per line</div>
          <EditableField
            value={(entry.joins ?? []).join("\n")}
            placeholder="e.g. customers on customer_id"
            onSave={async v => {
              const joins = v.split("\n").map(s => s.trim()).filter(Boolean);
              await updateTableGlossary(table, { joins }); load();
            }}
          />
        </div>
      </div>

      {/* ── Column level ── */}
      <div style={LABEL}>Columns</div>
      {columns.length === 0 && <p style={{ fontSize: 12, color: "var(--t4)" }}>No columns.</p>}
      {columns.map(c => {
        const ce = colEntry(c);
        return (
          <div key={c} style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "10px 0", borderBottom: "0.5px solid var(--b0)", alignItems: "start" }}>
            <div style={{ minWidth: 0 }}>
              <span style={{ fontSize: 12, color: "var(--t1)", fontWeight: 500, fontFamily: "var(--font-mono)" }}>{c}</span>
            </div>
            <div>
              <EditableField value={ce.description ?? ""} placeholder="Add a comment…"
                onSave={async v => { await updateColumnGlossary(table, c, { description: v }); load(); }} />
              <SubField
                caption="Known values"
                value={ce.values ?? ""}
                placeholder="e.g. pending · paid · refunded · canceled"
                onSave={async v => { await updateColumnGlossary(table, c, { values: v }); load(); }}
              />
              <SubField
                caption="⚠ Caveats"
                value={ce.caveats ?? ""}
                placeholder="e.g. NULL until the order ships; excludes test accounts"
                accent="var(--amb4)"
                onSave={async v => { await updateColumnGlossary(table, c, { caveats: v }); load(); }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
