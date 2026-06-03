"use client";

/**
 * AddDataPanel — Databricks-style "Add data" experience as a right-side panel.
 *
 * Slides in from the right (not a full-screen overlay). Presents the connector
 * registry (`/connectors/types`) with real brand logos, a "Files" section for
 * uploads, and category-grouped connector cards. Picking a source reveals a
 * dynamic config form built from that connector's `fields`.
 */

import { useEffect, useMemo, useState } from "react";
import { addConnection, getConnectorTypes, type ConnectorTypeInfo } from "@/lib/api";
import { BrandLogo, brandColor } from "@/components/BrandLogos";

// ── Display metadata per connector ────────────────────────────────────────────

const META: Record<string, { label: string; blurb: string; badge?: string }> = {
  duckdb:       { label: "DuckDB",       blurb: "Local analytical database file" },
  postgres:     { label: "PostgreSQL",   blurb: "Connect to a Postgres database" },
  bigquery:     { label: "BigQuery",     blurb: "Google Cloud data warehouse" },
  snowflake:    { label: "Snowflake",    blurb: "Cloud data warehouse" },
  mysql:        { label: "MySQL",        blurb: "Connect to a MySQL database" },
  local_upload: { label: "Create or modify table", blurb: "Upload CSV, Parquet, Excel or JSON to create a table" },
  s3:           { label: "Amazon S3",    blurb: "Object storage bucket" },
  federated:    { label: "Federated",    blurb: "Combine existing connections" },
  stripe:       { label: "Stripe",       blurb: "Payments & billing data", badge: "Preview" },
  hubspot:      { label: "HubSpot",      blurb: "CRM & marketing data" },
  salesforce:   { label: "Salesforce",   blurb: "CRM objects & pipelines" },
  confluence:   { label: "Confluence",   blurb: "Team wiki & knowledge" },
  notion:       { label: "Notion",       blurb: "Docs & databases" },
};

const CATEGORY_ORDER: Array<{ id: string; label: string }> = [
  { id: "built-in",   label: "Databases" },
  { id: "warehouse",  label: "Data warehouses" },
  { id: "api",        label: "Applications" },
];

const meta = (t: string) => META[t] ?? { label: t, blurb: "" };

// ── Cards ──────────────────────────────────────────────────────────────────────

function LogoBox({ type, size = 36 }: { type: string; size?: number }) {
  const c = brandColor(type);
  return (
    <span style={{ width: size, height: size, borderRadius: 8, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
      background: `color-mix(in srgb, ${c} 12%, var(--bg-2))`, border: `1px solid color-mix(in srgb, ${c} 26%, transparent)` }}>
      <BrandLogo type={type} size={Math.round(size * 0.56)} />
    </span>
  );
}

function FileTile({ info, onClick }: { info: ConnectorTypeInfo; onClick: () => void }) {
  const m = meta(info.type);
  return (
    <button onClick={onClick}
      style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16, borderRadius: 10, cursor: "pointer",
        background: "var(--bg-1)", border: "1px solid var(--b1)", textAlign: "left", transition: "all .12s", width: "100%" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = brandColor(info.type); (e.currentTarget as HTMLElement).style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"; }}
    >
      <LogoBox type={info.type} size={34} />
      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{m.label}</span>
      <span style={{ fontSize: 11.5, color: "var(--t3)", lineHeight: 1.45 }}>{m.blurb}</span>
    </button>
  );
}

function ConnectorCard({ info, onClick }: { info: ConnectorTypeInfo; onClick: () => void }) {
  const m = meta(info.type);
  return (
    <button onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 11, padding: "11px 13px", borderRadius: 9, cursor: "pointer",
        background: "var(--bg-1)", border: "1px solid var(--b1)", textAlign: "left", transition: "all .12s", width: "100%" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = brandColor(info.type); (e.currentTarget as HTMLElement).style.background = "var(--bg-2)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"; }}
    >
      <LogoBox type={info.type} size={34} />
      <span style={{ minWidth: 0, flex: 1 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.label}</span>
          {m.badge && <span style={{ fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: "color-mix(in srgb, var(--blue4,#60a5fa) 16%, transparent)", color: "var(--blue4,#60a5fa)", whiteSpace: "nowrap" }}>{m.badge}</span>}
        </span>
        <span style={{ display: "block", fontSize: 11, color: "var(--t3)", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.blurb}</span>
      </span>
    </button>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────────

export function AddDataPanel({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [types, setTypes]     = useState<ConnectorTypeInfo[]>([]);
  const [search, setSearch]   = useState("");
  const [picked, setPicked]   = useState<ConnectorTypeInfo | null>(null);
  const [name, setName]       = useState("");
  const [values, setValues]   = useState<Record<string, string>>({});
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState("");

  useEffect(() => { getConnectorTypes().then(setTypes).catch(() => setTypes([])); }, []);

  // Esc to close (form first, then panel)
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") { picked ? setPicked(null) : onClose(); } };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [picked, onClose]);

  const q = search.toLowerCase();
  const visible = useMemo(
    () => types.filter(t => t.type !== "federated" && (!q || meta(t.type).label.toLowerCase().includes(q) || t.type.includes(q))),
    [types, q],
  );
  const fileSources = visible.filter(t => t.category === "file");
  const grouped = useMemo(
    () => CATEGORY_ORDER.map(cat => ({ ...cat, items: visible.filter(t => t.category === cat.id) })).filter(g => g.items.length > 0),
    [visible],
  );

  const pick = (info: ConnectorTypeInfo) => {
    setPicked(info); setError("");
    setName(meta(info.type).label);
    setValues(Object.fromEntries(info.fields.map(f => [f.key, ""])));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!picked) return;
    setSaving(true); setError("");
    try {
      const m: Record<string, string> = {};
      let dsn = ""; let schema: string | undefined;
      for (const f of picked.fields) {
        const v = (values[f.key] ?? "").trim();
        if (f.key === "dsn") dsn = v;
        else if (f.key === "schema_name") schema = v || undefined;
        else if (v) m[f.key] = v;
      }
      await addConnection(name.trim() || meta(picked.type).label, picked.type, dsn, schema, m);
      onAdded();
      onClose();
    } catch (ex: unknown) {
      setError((ex as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const S: React.CSSProperties = { width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 6, background: "var(--bg-0)", border: "1px solid var(--b1)", color: "var(--t1)", outline: "none", fontFamily: "inherit" };
  const L: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 5, display: "block", fontWeight: 500 };
  const sectionLabel: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 12, display: "flex", alignItems: "center", gap: 7 };

  return (
    <>
      <style>{`@keyframes adp-slide{from{transform:translateX(100%)}to{transform:translateX(0)}}`}</style>
      {/* Backdrop */}
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 240, background: "rgba(0,0,0,0.5)" }} />

      {/* Right panel */}
      <div style={{ position: "fixed", top: 0, right: 0, height: "100%", width: "min(560px, 94vw)", zIndex: 250,
        background: "var(--bg-0)", borderLeft: "1px solid var(--b1)", boxShadow: "-12px 0 40px rgba(0,0,0,0.35)",
        display: "flex", flexDirection: "column", animation: "adp-slide .18s cubic-bezier(.2,.7,.3,1)" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 22px", borderBottom: "1px solid var(--b1)", flexShrink: 0 }}>
          {picked ? (
            <button onClick={() => setPicked(null)} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--t3)", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 12 6 8l4-4" /></svg>
              All sources
            </button>
          ) : (
            <div>
              <h1 style={{ fontSize: 17, fontWeight: 600, color: "var(--t1)" }}>Add data</h1>
              <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 2 }}>Get started by connecting to a data source or uploading a local file.</p>
            </div>
          )}
          <button onClick={onClose} title="Close (Esc)" style={{ marginLeft: "auto", width: 28, height: 28, borderRadius: 6, cursor: "pointer", background: "transparent", border: "1px solid var(--b1)", color: "var(--t3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {!picked ? (
            <div style={{ padding: "20px 22px 40px" }}>
              {/* Search */}
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search data sources…"
                style={{ ...S, marginBottom: 24 }} />

              {/* Files */}
              {fileSources.length > 0 && (
                <div style={{ marginBottom: 26 }}>
                  <p style={sectionLabel}>Files</p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    {fileSources.map(info => <FileTile key={info.type} info={info} onClick={() => pick(info)} />)}
                  </div>
                </div>
              )}

              {/* Connectors */}
              {grouped.map(g => (
                <div key={g.id} style={{ marginBottom: 24 }}>
                  <p style={sectionLabel}>{g.label}</p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(228px, 1fr))", gap: 10 }}>
                    {g.items.map(info => <ConnectorCard key={info.type} info={info} onClick={() => pick(info)} />)}
                  </div>
                </div>
              ))}

              {visible.length === 0 && <p style={{ fontSize: 12, color: "var(--t4)" }}>No sources match.</p>}
            </div>
          ) : (
            <form onSubmit={submit} style={{ padding: "22px 22px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <LogoBox type={picked.type} size={42} />
                <div>
                  <p style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Connect {meta(picked.type).label}</p>
                  <p style={{ fontSize: 11.5, color: "var(--t3)", marginTop: 1 }}>{meta(picked.type).blurb}</p>
                </div>
              </div>

              <div>
                <label style={L}>Connection name</label>
                <input style={S} value={name} onChange={e => setName(e.target.value)} placeholder={meta(picked.type).label} required />
              </div>

              {picked.fields.length === 0 && (
                <p style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5, padding: "10px 12px", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: 6 }}>
                  No configuration needed — create the connection, then upload files from the catalog detail panel.
                </p>
              )}

              {picked.fields.map(f => (
                <div key={f.key}>
                  <label style={L}>{f.label}</label>
                  <input
                    style={{ ...S, fontFamily: f.secret || f.key === "dsn" ? "var(--font-mono)" : "inherit" }}
                    type={f.secret ? "password" : "text"}
                    placeholder={f.placeholder}
                    value={values[f.key] ?? ""}
                    onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                    required={f.key === "dsn"}
                  />
                </div>
              ))}

              {error && <p style={{ fontSize: 12, color: "#f87171" }}>{error}</p>}

              <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
                <button type="submit" disabled={saving}
                  style={{ fontSize: 13, fontWeight: 600, padding: "9px 20px", borderRadius: 6, cursor: saving ? "not-allowed" : "pointer", background: "#2563eb", color: "#fff", border: "none", opacity: saving ? 0.6 : 1 }}>
                  {saving ? "Connecting…" : "Create connection"}
                </button>
                <button type="button" onClick={() => setPicked(null)}
                  style={{ fontSize: 13, padding: "9px 16px", borderRadius: 6, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "1px solid var(--b1)" }}>Back</button>
              </div>
            </form>
          )}
        </div>
      </div>
    </>
  );
}
