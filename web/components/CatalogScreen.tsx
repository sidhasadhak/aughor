"use client";

/**
 * CatalogScreen — Unity Catalog-style 4-level hierarchy
 *
 *  Section (Sample Catalog / My Connections)
 *    └── Catalog  (one per connection)
 *          └── Schema  (ecommerce / public / analytics …)
 *                └── Table
 *
 * Left panel  : collapsible tree navigator (260 px)
 * Right panel : detail view that adapts per level
 *
 *   Catalog  → header | tabs (Overview) | schema-list + About sidebar
 *   Schema   → header | tabs (Tables)   | table-list  + About sidebar
 *   Table    → header | tabs (Overview / Sample Data) | columns + About sidebar
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSchema } from "@/lib/schema-context";
import {
  getCatalogTree, getConnections, addConnection, deleteConnection,
  testConnection, sampleTable, getSchemaRich,
  type CatalogTree, type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo,
  type Connection, type SchemaTable, type SchemaColumn, type TableSample,
} from "@/lib/api";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { SchemaPanel } from "@/components/SchemaPanel";
import { DocumentUploader } from "@/components/DocumentUploader";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRows(n: number | string | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (isNaN(num)) return "—";
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000)     return Math.round(num / 1_000) + "K";
  return num.toLocaleString();
}

function typeColor(t: string): string {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT"))                  return "#7ba8f7";
  if (u.includes("BIGINT") || u.includes("INT"))                    return "#c084fc";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "#4ade80";
  if (u.includes("DATE") || u.includes("TIME"))                     return "#f97316";
  if (u.includes("BOOL"))                                           return "#4ade80";
  return "var(--t2)";
}

const CONN_TAG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  duckdb:       { label: "DuckDB",      color: "#fbbf24", bg: "#1e1a0e", border: "#3a2e0a" },
  postgres:     { label: "Postgres",    color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
  bigquery:     { label: "BigQuery",    color: "#4ade80", bg: "#0e1e14", border: "#1a3a24" },
  snowflake:    { label: "Snowflake",   color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
  mysql:        { label: "MySQL",       color: "#f97316", bg: "#1e160e", border: "#3a2a0a" },
  local_upload: { label: "Files",       color: "#c084fc", bg: "#1a1228", border: "#2e1a48" },
  s3:           { label: "S3",          color: "#f59e0b", bg: "#1e1808", border: "#3a2e08" },
  federated:    { label: "Federated",   color: "#34d399", bg: "#0e1e18", border: "#1a3a28" },
  stripe:       { label: "Stripe",      color: "#818cf8", bg: "#14142a", border: "#2a2a50" },
  hubspot:      { label: "HubSpot",     color: "#f97316", bg: "#1e160e", border: "#3a2a0a" },
  salesforce:   { label: "Salesforce",  color: "#38bdf8", bg: "#0e1a1e", border: "#1a3040" },
  confluence:   { label: "Confluence",  color: "#60a5fa", bg: "#121a2a", border: "#1e2e48" },
  notion:       { label: "Notion",      color: "#d4d4d8", bg: "#1a1a1a", border: "#2e2e2e" },
};

// ── Connector action panel (sync / upload / knowledge-sync) ───────────────────

import { API_BASE as BASE_API } from "@/lib/config";

const _SYNCABLE      = ["stripe", "hubspot", "salesforce", "s3"];
const _KNOWLEDGE     = ["confluence", "notion"];
const _FILE_UPLOAD   = ["local_upload"];

function ConnectorActions({ connId, connType }: { connId: string; connType: string }) {
  const [status, setStatus]   = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [files,   setFiles]   = useState<Array<{ filename: string; table_name: string; size_bytes: number }>>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = (typeof document !== "undefined") ? { current: null as HTMLInputElement | null } : { current: null };

  const isSyncable    = _SYNCABLE.includes(connType);
  const isKnowledge   = _KNOWLEDGE.includes(connType);
  const isFileUpload  = _FILE_UPLOAD.includes(connType);

  useEffect(() => {
    if (isSyncable || isKnowledge) {
      const endpoint = isKnowledge
        ? `${BASE_API}/connections/${connId}/knowledge-sync/status`
        : `${BASE_API}/connections/${connId}/sync-status`;
      fetch(endpoint).then(r => r.json())
        .then(d => setStatus(d.last_sync ? `Last sync: ${new Date(d.last_sync).toLocaleString()}` : "Never synced"))
        .catch(() => setStatus(null));
    }
    if (isFileUpload) {
      fetch(`${BASE_API}/connections/${connId}/files`).then(r => r.json())
        .then(d => setFiles(d.files ?? []))
        .catch(() => {});
    }
  }, [connId, connType, isSyncable, isKnowledge, isFileUpload]);

  const handleSync = async () => {
    setSyncing(true);
    const endpoint = isKnowledge
      ? `${BASE_API}/connections/${connId}/knowledge-sync`
      : `${BASE_API}/connections/${connId}/sync`;
    try {
      await fetch(endpoint, { method: "POST" });
      setStatus("Sync triggered — running in background…");
    } catch {
      setStatus("Sync failed");
    }
    setSyncing(false);
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const resp = await fetch(`${BASE_API}/connections/${connId}/files`, { method: "POST", body: form });
      if (resp.ok) {
        const fresh = await fetch(`${BASE_API}/connections/${connId}/files`).then(r => r.json());
        setFiles(fresh.files ?? []);
      }
    } catch { /* silent */ }
    setUploading(false);
  };

  const handleDelete = async (filename: string) => {
    await fetch(`${BASE_API}/connections/${connId}/files/${encodeURIComponent(filename)}`, { method: "DELETE" });
    setFiles(f => f.filter(x => x.filename !== filename));
  };

  if (!isSyncable && !isKnowledge && !isFileUpload) return null;

  const BtnStyle: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: 6,
    padding: "5px 12px", borderRadius: 4, fontSize: 11, fontWeight: 500,
    cursor: syncing || uploading ? "not-allowed" : "pointer",
    background: "var(--blue1, #152B50)", border: "1px solid var(--blue2, #1A3A6E)",
    color: "var(--blue5, #88BAFF)", transition: "all .12s",
    opacity: syncing || uploading ? 0.5 : 1,
  };

  return (
    <div style={{ padding: "12px 16px", borderTop: "0.5px solid #1e1f24" }}>
      {(isSyncable || isKnowledge) && (
        <div style={{ marginBottom: 10 }}>
          <button style={BtnStyle} onClick={handleSync} disabled={syncing}>
            {syncing ? "⏳ Syncing…" : isKnowledge ? "📚 Knowledge Sync" : "🔄 Sync Now"}
          </button>
          {status && <p style={{ fontSize: 11, color: "var(--t4)", marginTop: 6 }}>{status}</p>}
        </div>
      )}
      {isFileUpload && (
        <div>
          <label style={{ ...BtnStyle, cursor: uploading ? "not-allowed" : "pointer" }}>
            {uploading ? "Uploading…" : "+ Upload CSV / Parquet / Excel"}
            <input
              type="file"
              accept=".csv,.tsv,.parquet,.parq,.xlsx,.xls,.json"
              style={{ display: "none" }}
              disabled={uploading}
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); }}
            />
          </label>
          {files.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
              {files.map(f => (
                <div key={f.filename} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--t2)" }}>
                  <span style={{ fontFamily: "var(--font-mono, monospace)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.filename}</span>
                  <span style={{ color: "var(--t4)", fontSize: 11 }}>{Math.round(f.size_bytes / 1024)}KB</span>
                  <button onClick={() => handleDelete(f.filename)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", padding: 0, fontSize: 12 }} title="Remove">✕</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
const connMeta = (t: string) => CONN_TAG[t] ?? { label: t, color: "var(--t2)", bg: "#1a1a22", border: "#2a2a35" };

// ── Selection type ────────────────────────────────────────────────────────────

type Sel =
  | { level: "table";   connId: string; schemaName: string; table: CatalogTableInfo }
  | { level: "schema";  connId: string; schemaName: string; entry: CatalogSchemaInfo }
  | { level: "catalog"; connId: string; entry: CatalogEntry }
  | null;

// ── Shared layout primitives ──────────────────────────────────────────────────

/** The right-panel header bar — icon, name, type tag */
function DetailHeader({
  icon, name, tag, breadcrumb, meta,
}: {
  icon:       React.ReactNode;
  name:       string;
  tag?:       React.ReactNode;
  breadcrumb?: string;
  meta?:       string;
}) {
  return (
    <div style={{ padding: "16px 20px 12px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "var(--bg-0)" }}>
      {breadcrumb && (
        <p style={{ fontSize: 11, color: "var(--t4)", marginBottom: 6 }}>
          {breadcrumb}
        </p>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "var(--t3)", display: "flex", alignItems: "center" }}>{icon}</span>
        <span style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {name}
        </span>
        {tag}
      </div>
      {meta && <p style={{ fontSize: 11, color: "var(--t4)", marginTop: 4 }}>{meta}</p>}
    </div>
  );
}

/** Tab bar used by all detail panels */
function TabBar({ tabs, active, onChange }: {
  tabs:    { id: string; label: string }[];
  active:  string;
  onChange:(id: string) => void;
}) {
  return (
    <div style={{ display: "flex", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, padding: "0 8px", background: "var(--bg-0)" }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            fontSize: 12, padding: "8px 12px", cursor: "pointer", border: "none",
            background: "transparent", fontFamily: "inherit",
            color: active === t.id ? "var(--t1)" : "var(--t4)",
            borderBottom: `2px solid ${active === t.id ? "#3d6bff" : "transparent"}`,
            transition: "color .1s",
            marginBottom: -1,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** "About this X" sidebar card used in all three detail panels */
function AboutSidebar({ title, rows }: {
  title: string;
  rows:  { label: string; value: React.ReactNode }[];
}) {
  return (
    <div style={{
      width: 220, flexShrink: 0, borderLeft: "0.5px solid #1e1f24",
      padding: "16px 16px", overflowY: "auto", background: "var(--bg-0)",
    }}>
      <p style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.07em" }}>
        {title}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rows.map(r => (
          <div key={String(r.label)}>
            <p style={{ fontSize: 11, color: "var(--t4)", marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.06em" }}>{r.label}</p>
            <div style={{ fontSize: 11, color: "var(--t2)" }}>{r.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Inline search box used inside tab bodies */
function FilterBox({ value, onChange, placeholder }: { value: string; onChange:(v:string)=>void; placeholder?: string }) {
  return (
    <div style={{ position: "relative", flexShrink: 0 }}>
      <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
        style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "var(--t4)", pointerEvents: "none" }}>
        <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
      </svg>
      <input
        value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        style={{ fontSize: 11, padding: "5px 8px 5px 26px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid #1e1f24", color: "var(--t2)", outline: "none", width: 220 }}
      />
    </div>
  );
}

// ── Icons ─────────────────────────────────────────────────────────────────────

const IcoCatalog = ({ color = "currentColor" }: { color?: string }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <ellipse cx="8" cy="5" rx="6" ry="2.5" stroke={color} strokeWidth="1.2" />
    <path d="M2 5v6c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5" stroke={color} strokeWidth="1.2" fill="none" />
    <path d="M2 8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" stroke={color} strokeWidth="1.2" opacity=".5" />
  </svg>
);

const IcoSchema = ({ color = "currentColor", size = 14 }: { color?: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <path d="M2 3h5v5H2z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".6" />
    <path d="M9 3h5v5H9z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".4" />
    <path d="M5.5 10.5h5v2.5h-5z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".35" />
  </svg>
);

const IcoTable = ({ active = false, size = 14 }: { active?: boolean; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: active ? "var(--blue4)" : "var(--t4)" }}>
    <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".8" />
    <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".5" />
    <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".3" />
  </svg>
);

const Chevron = ({ open }: { open: boolean }) => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
    style={{ flexShrink: 0, transition: "transform .15s", transform: open ? "rotate(90deg)" : "rotate(0deg)", color: "var(--t4)" }}>
    <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// ── Add-connection inline form ────────────────────────────────────────────────

function AddConnForm({ onSave, onCancel }: { onSave: () => void; onCancel: () => void }) {
  const [name, setName]     = useState("");
  const [type, setType]     = useState("postgres");
  const [dsn, setDsn]       = useState("");
  const [schema, setSchema] = useState("");
  const [err, setErr]       = useState("");
  const [loading, setLoad]  = useState(false);

  const S: React.CSSProperties = { width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid #2a2b35", color: "#c8c7c3", outline: "none", fontFamily: "inherit" };
  const L: React.CSSProperties = { fontSize: 11, color: "var(--t4)", marginBottom: 3, display: "block" };

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoad(true);
    try { await addConnection(name, type, dsn, schema || undefined); onSave(); }
    catch (ex: unknown) { setErr((ex as Error).message); }
    finally { setLoad(false); }
  };

  return (
    <form onSubmit={handle} style={{ padding: "10px 12px", background: "var(--bg-0)", borderBottom: "0.5px solid #1e1f24", display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ fontSize: 11, fontWeight: 500, color: "var(--t2)" }}>New connection</p>
      <div><label style={L}>Name</label><input style={S} placeholder="My database" value={name} onChange={e => setName(e.target.value)} required /></div>
      <div>
        <label style={L}>Type</label>
        <select style={{ ...S, cursor: "pointer" }} value={type} onChange={e => setType(e.target.value)}>
          <option value="postgres">PostgreSQL</option>
          <option value="duckdb">DuckDB file</option>
        </select>
      </div>
      <div>
        <label style={L}>{type === "postgres" ? "Connection string" : "File path"}</label>
        <input style={{ ...S, fontFamily: "var(--font-mono)" }} placeholder={type === "postgres" ? "postgresql://user:pass@host/db" : "/path/to/file.duckdb"} value={dsn} onChange={e => setDsn(e.target.value)} required />
      </div>
      <div>
        <label style={L}>Schema <span style={{ color: "var(--b0)" }}>(optional)</span></label>
        <input style={{ ...S, fontFamily: "var(--font-mono)" }} placeholder={type === "postgres" ? "public" : "main"} value={schema} onChange={e => setSchema(e.target.value)} />
      </div>
      {err && <p style={{ fontSize: 11, color: "#f87171" }}>{err}</p>}
      <div style={{ display: "flex", gap: 6 }}>
        <button type="submit" disabled={loading} style={{ flex: 1, fontSize: 11, padding: "5px 0", borderRadius: 4, cursor: "pointer", background: "#1a2030", color: "#7ba8f7", border: "0.5px solid #2a3050", opacity: loading ? .5 : 1 }}>
          {loading ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} style={{ fontSize: 11, padding: "5px 10px", borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid #1e1f24" }}>Cancel</button>
      </div>
    </form>
  );
}

// ── Sample grid ───────────────────────────────────────────────────────────────

function SampleGrid({ connId, tableName, schemaName }: { connId: string; tableName: string; schemaName?: string }) {
  const [data, setData]    = useState<TableSample | null>(null);
  const [loading, setLoad] = useState(false);
  const [error, setErr]    = useState<string | null>(null);
  const fetched = useRef(false);

  useEffect(() => { setData(null); setErr(null); fetched.current = false; }, [connId, tableName, schemaName]);
  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    setLoad(true);
    sampleTable(connId, tableName, 200, schemaName)
      .then(d => setData(d))
      .catch(e => setErr((e as Error).message))
      .finally(() => setLoad(false));
  }, [connId, tableName, schemaName]);

  if (loading) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 8 }}>
      <div style={{ width: 16, height: 16, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
      <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading sample data…</span>
    </div>
  );
  if (error) return <div style={{ padding: 24, fontSize: 11, color: "#f87171", textAlign: "center" }}>{error}</div>;
  if (!data || data.rows.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 11, color: "var(--t4)" }}>No rows returned.</span>
    </div>
  );

  const MAX_CELL = 40;
  const clamp = (v: string | null) => {
    if (v === null) return <span style={{ color: "var(--b0)", fontStyle: "italic", fontSize: 11 }}>null</span>;
    return v.length > MAX_CELL ? v.slice(0, MAX_CELL) + "…" : v;
  };

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <table style={{ borderCollapse: "collapse", minWidth: "100%", fontSize: 11, fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr style={{ background: "var(--bg-0)", position: "sticky", top: 0, zIndex: 1 }}>
            {data.columns.map(col => (
              <th key={col} style={{ padding: "6px 12px", textAlign: "left", whiteSpace: "nowrap", borderBottom: "0.5px solid #1e1f24", borderRight: "0.5px solid #111115", fontSize: 11, color: "#5a5b62", fontWeight: 600, letterSpacing: "0.04em" }}>
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, ri) => (
            <tr key={ri} style={{ borderBottom: "0.5px solid #111115" }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
            >
              {row.map((cell, ci) => (
                <td key={ci} style={{ padding: "5px 12px", color: cell === null ? "var(--b0)" : "var(--t2)", whiteSpace: "nowrap", borderRight: "0.5px solid #111115" }}>
                  {clamp(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: "5px 12px", borderTop: "0.5px solid #1e1f24", fontSize: 11, color: "var(--t4)", background: "var(--bg-0)" }}>
        {data.rows.length} row{data.rows.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

// ── Right: TABLE detail ───────────────────────────────────────────────────────

type TableTab = "overview" | "sample";

function TableDetailPanel({ sel, onAsk }: {
  sel:   Extract<Sel, { level: "table" }>;
  onAsk?: (table: string, connId: string) => void;
}) {
  const [tab, setTab]           = useState<TableTab>("overview");
  const [colFilter, setColFilter] = useState("");
  const [richTable, setRich]    = useState<SchemaTable | null>(null);
  const [loading, setLoad]      = useState(false);
  const cm = connMeta(""); // not shown in table detail

  // Fetch column detail (rich schema) when table changes
  useEffect(() => {
    setTab("overview"); setColFilter(""); setRich(null);
    setLoad(true);
    getSchemaRich(sel.connId)
      .then(s => setRich(s.tables.find(t => t.name === sel.table.name) ?? null))
      .catch(() => setRich(null))
      .finally(() => setLoad(false));
  }, [sel.connId, sel.schemaName, sel.table.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const cols = richTable?.columns ?? [];
  const q    = colFilter.toLowerCase();
  const filteredCols = q ? cols.filter(c => c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q)) : cols;
  const fkCount = cols.filter(c => c.is_fk).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <DetailHeader
        icon={<IcoTable active size={16} />}
        name={sel.table.name}
        breadcrumb={`${sel.connId}  ›  ${sel.schemaName}`}
        meta={`${fmtRows(sel.table.row_count)} rows · ${cols.length || "…"} columns${fkCount ? ` · ${fkCount} FK` : ""}`}
      />

      <TabBar
        tabs={[{ id: "overview", label: "Overview" }, { id: "sample", label: "Sample Data" }]}
        active={tab}
        onChange={id => setTab(id as TableTab)}
      />

      {/* ── Overview tab ── */}
      {tab === "overview" && (
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          {/* Main: column list */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* Filter row */}
            <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "var(--bg-0)" }}>
              <FilterBox value={colFilter} onChange={setColFilter} placeholder="Filter columns…" />
            </div>

            {/* Column header */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "var(--bg-0)", flexShrink: 0 }}>
              {["Column", "Type", ""].map(h => (
                <span key={h} style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600 }}>{h}</span>
              ))}
            </div>

            {/* Column rows */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {loading && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 32, gap: 8 }}>
                  <div style={{ width: 14, height: 14, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading columns…</span>
                </div>
              )}
              {!loading && filteredCols.length === 0 && (
                <p style={{ padding: "20px 16px", fontSize: 11, color: "var(--t4)" }}>
                  {q ? "No columns match." : "Column details unavailable."}
                </p>
              )}
              {!loading && filteredCols.map((col, i) => (
                <div key={col.name}
                  style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "6px 16px", borderBottom: "0.5px solid #111115", alignItems: "center", background: "transparent" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1218"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }} title={col.description || ""}>
                    <span style={{ width: 6, height: 6, borderRadius: 2, flexShrink: 0, background: typeColor(col.type), opacity: 0.7 }} />
                    <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "#c8c7c3", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.name}</span>
                    {col.description && (
                      <span style={{ fontSize: 11, color: "#5a5e6a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>{col.description}</span>
                    )}
                  </div>
                  <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: typeColor(col.type) }}>{col.type}</span>
                  {col.is_fk
                    ? <span style={{ fontSize: 9, padding: "2px 5px", borderRadius: 3, background: "#1a1e2e", color: "#3d6bff", border: "0.5px solid #2a3050" }}>FK</span>
                    : <span />
                  }
                </div>
              ))}
            </div>
          </div>

          {/* About sidebar */}
          <AboutSidebar
            title="About this table"
            rows={[
              { label: "Rows",    value: fmtRows(sel.table.row_count) },
              { label: "Columns", value: String(cols.length || "…") },
              { label: "Schema",  value: <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{sel.schemaName}</span> },
              { label: "FK columns", value: fkCount > 0 ? String(fkCount) : "—" },
              ...(onAsk ? [{
                label: "Actions",
                value: (
                  <button onClick={() => onAsk(sel.table.name, sel.connId)} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 4, cursor: "pointer", background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050", width: "100%", textAlign: "left" as const }}>
                    Ask about this table →
                  </button>
                ),
              }] : []),
            ]}
          />
        </div>
      )}

      {/* ── Sample Data tab ── */}
      {tab === "sample" && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "var(--bg-0)", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>First 200 rows</span>
          </div>
          <SampleGrid connId={sel.connId} tableName={sel.table.name} schemaName={sel.schemaName} />
        </div>
      )}
    </div>
  );
}

// ── Right: SCHEMA detail ──────────────────────────────────────────────────────

type SchemaTab = "tables";

function SchemaDetailPanel({ sel, onSelectTable, onAsk }: {
  sel:           Extract<Sel, { level: "schema" }>;
  onSelectTable: (table: CatalogTableInfo) => void;
  onAsk?:        (table: string, connId: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const { entry } = sel;
  const q = filter.toLowerCase();
  const tables = q ? entry.tables.filter(t => t.name.toLowerCase().includes(q)) : entry.tables;
  const totalRows = entry.tables.reduce((s, t) => s + (Number(t.row_count) || 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <DetailHeader
        icon={<IcoSchema color="#5a7fa8" size={16} />}
        name={entry.name}
        breadcrumb={sel.connId}
        meta={`${entry.tables.length} table${entry.tables.length !== 1 ? "s" : ""}`}
      />

      <TabBar
        tabs={[{ id: "tables", label: `Tables  ${entry.tables.length}` }]}
        active="tables"
        onChange={() => {}}
      />

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main: table list */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Filter row */}
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "var(--bg-0)" }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter tables…" />
          </div>

          {/* Table header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "var(--bg-0)", flexShrink: 0 }}>
            {["Name", "Rows", ""].map(h => (
              <span key={h} style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, textAlign: h === "Rows" ? "right" as const : "left" as const }}>{h}</span>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {tables.length === 0 && (
              <p style={{ padding: "20px 16px", fontSize: 11, color: "var(--t4)" }}>{q ? "No tables match." : "No tables found."}</p>
            )}
            {tables.map((t, i) => (
              <div key={t.name}
                onClick={() => onSelectTable(t)}
                style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", padding: "8px 16px", borderBottom: "0.5px solid #111115", cursor: "pointer", alignItems: "center", background: "transparent" }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1218"}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <IcoTable size={12} />
                  <span style={{ fontSize: 12, color: "#c8c7c3", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name}</span>
                </div>
                <span style={{ fontSize: 11, color: "var(--t4)", textAlign: "right" }}>{fmtRows(t.row_count)}</span>
                {onAsk && (
                  <button
                    onClick={e => { e.stopPropagation(); onAsk(t.name, sel.connId); }}
                    style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid #1e1f24", justifySelf: "end" as const }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#7ba8f7"; (e.currentTarget as HTMLElement).style.background = "#1a1e2e"; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t4)"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >Ask →</button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* About sidebar */}
        <AboutSidebar
          title="About this schema"
          rows={[
            { label: "Tables",     value: String(entry.tables.length) },
            { label: "Total rows", value: totalRows > 0 ? fmtRows(totalRows) : "—" },
            { label: "Catalog",    value: <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{sel.connId}</span> },
          ]}
        />
      </div>
    </div>
  );
}

// ── Right: CATALOG detail ─────────────────────────────────────────────────────

type CatalogTab = "schemas";

function CatalogDetailPanel({ sel, onSelectSchema, conn }: {
  sel:            Extract<Sel, { level: "catalog" }>;
  onSelectSchema: (schema: CatalogSchemaInfo) => void;
  conn?:          Connection;
}) {
  const [filter, setFilter] = useState("");
  const [tab, setTab]       = useState<"overview" | "knowledge">("overview");
  const { entry } = sel;
  const cm = connMeta(entry.conn_type);
  const effTab = entry.builtin && tab === "knowledge" ? "overview" : tab;
  const q = filter.toLowerCase();
  const schemas = q ? entry.schemas.filter(s => s.name.toLowerCase().includes(q) || s.tables.some(t => t.name.toLowerCase().includes(q))) : entry.schemas;
  const totalTables = entry.schemas.reduce((s, sc) => s + sc.tables.length, 0);
  const totalRows   = entry.schemas.reduce((s, sc) => s + sc.tables.reduce((a, t) => a + (Number(t.row_count) || 0), 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <DetailHeader
        icon={<IcoCatalog color={cm.color} />}
        name={entry.name}
        tag={
          <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 3, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}`, flexShrink: 0 }}>
            {cm.label}
          </span>
        }
        meta={`${entry.schemas.length} schema${entry.schemas.length !== 1 ? "s" : ""}  ·  ${totalTables} table${totalTables !== 1 ? "s" : ""}`}
      />

      <TabBar
        tabs={[
          { id: "overview", label: `Overview  ${entry.schemas.length}` },
          ...(entry.builtin ? [] : [{ id: "knowledge", label: "Knowledge" }]),
        ]}
        active={effTab}
        onChange={id => setTab(id as "overview" | "knowledge")}
      />

      {effTab === "knowledge" ? (
        <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>
          <p style={{ fontSize: 12, color: "var(--t2)", marginBottom: 16, maxWidth: 560, lineHeight: 1.5 }}>
            Upload documents (PDFs, reports, runbooks) to give Aughor institutional knowledge
            about <span style={{ color: "var(--t1)", fontWeight: 500 }}>{entry.name}</span>. This
            grounds Quick and Agentic answers in your team&rsquo;s own context.
          </p>
          <DocumentUploader />
        </div>
      ) : (
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main: schema list (Overview tab) */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Filter row */}
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "var(--bg-0)" }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter schemas…" />
          </div>

          {/* Schema header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "var(--bg-0)", flexShrink: 0 }}>
            {["Name", "Tables", ""].map((h, i) => (
              <span key={h + i} style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, textAlign: h === "Tables" ? "right" as const : "left" as const }}>{h}</span>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {schemas.length === 0 && (
              <p style={{ padding: "20px 16px", fontSize: 11, color: "var(--t4)" }}>{q ? "No schemas match." : "No schemas found."}</p>
            )}
            {schemas.map((sc, i) => {
              const schRows = sc.tables.reduce((s, t) => s + (Number(t.row_count) || 0), 0);
              return (
                <div key={sc.name}
                  onClick={() => onSelectSchema(sc)}
                  style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px", padding: "10px 16px", borderBottom: "0.5px solid #111115", cursor: "pointer", alignItems: "center", background: "transparent" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1218"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <IcoSchema color="#5a7fa8" size={14} />
                    <div>
                      <p style={{ fontSize: 12, fontWeight: 500, color: "#c8c7c3" }}>{sc.name}</p>
                      <p style={{ fontSize: 11, color: "var(--t4)", marginTop: 1 }}>{schRows > 0 ? fmtRows(schRows) + " rows" : ""}</p>
                    </div>
                  </div>
                  <span style={{ fontSize: 11, color: "var(--t4)", textAlign: "right" }}>{sc.tables.length}</span>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ color: "var(--b0)", justifySelf: "end" as const }}>
                    <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </div>
              );
            })}
          </div>
        </div>

        {/* About sidebar + connector actions */}
        <div style={{ display: "flex", flexDirection: "column", flexShrink: 0, overflow: "hidden" }}>
          <AboutSidebar
            title="About this catalog"
            rows={[
              { label: "Type",    value: <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 3, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}` }}>{cm.label}</span> },
              ...(conn && !entry.builtin ? [{ label: "Status", value: <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--grn4)" }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--grn4)" }} />Active</span> }] : []),
              ...(conn?.dsn_preview ? [{ label: "DSN", value: <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--t2)", wordBreak: "break-all" as const }}>{conn.dsn_preview}</span> }] : []),
              ...(conn && !entry.builtin ? [{ label: "Default schema", value: <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{conn.schema_name || "default"}</span> }] : []),
              { label: "Schemas", value: String(entry.schemas.length) },
              { label: "Tables",  value: String(totalTables) },
              { label: "Total rows", value: totalRows > 0 ? fmtRows(totalRows) : "—" },
              ...(entry.builtin ? [{ label: "Source", value: "Built-in sample catalog" }] : []),
              ...(!entry.builtin ? [{ label: "Explorer", value: <ExplorationBadge connectionId={entry.conn_id} /> }] : []),
            ]}
          />
          <ConnectorActions connId={entry.conn_id} connType={entry.conn_type} />
        </div>
      </div>
      )}
    </div>
  );
}

// ── Right: Catalog home (Suggested / Favorites / Recents) ──────────────────────

const FAVS_KEY    = "aug.catalog.favs";
const RECENTS_KEY = "aug.catalog.recents";

interface FlatItem {
  key:        string;
  name:       string;
  type:       "Catalog" | "Schema" | "Table";
  path:       string;
  reason:     string;
  rows:       number | null;
  connId:     string;
  schemaName?: string;
  tableName?:  string;
}

function readLS(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}
function writeLS(key: string, v: string[]) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* noop */ } }
function pushRecent(key: string) {
  const cur = readLS(RECENTS_KEY).filter(k => k !== key);
  writeLS(RECENTS_KEY, [key, ...cur].slice(0, 15));
}

function flattenTree(tree: CatalogTree | null): FlatItem[] {
  if (!tree) return [];
  const out: FlatItem[] = [];
  tree.sections.forEach(sec => sec.entries.forEach(cat => {
    const totT = cat.schemas.reduce((s, x) => s + x.tables.length, 0);
    out.push({ key: `${cat.conn_id}::`, name: cat.name, type: "Catalog", path: sec.label,
      reason: `${cat.schemas.length} schema${cat.schemas.length !== 1 ? "s" : ""} · ${totT} table${totT !== 1 ? "s" : ""}`, rows: null, connId: cat.conn_id });
    cat.schemas.forEach(sc => {
      out.push({ key: `${cat.conn_id}:${sc.name}:`, name: sc.name, type: "Schema", path: cat.name,
        reason: `${sc.tables.length} table${sc.tables.length !== 1 ? "s" : ""}`, rows: null, connId: cat.conn_id, schemaName: sc.name });
      sc.tables.forEach(t => {
        out.push({ key: `${cat.conn_id}:${sc.name}:${t.name}`, name: t.name, type: "Table", path: `${cat.name}.${sc.name}`,
          reason: t.row_count != null ? `${fmtRows(t.row_count)} rows` : "Table", rows: t.row_count, connId: cat.conn_id, schemaName: sc.name, tableName: t.name });
      });
    });
  }));
  return out;
}

const typeIcon = (t: FlatItem["type"]) =>
  t === "Catalog" ? <IcoCatalog color="var(--t2)" /> :
  t === "Schema"  ? <IcoSchema color="#5a7fa8" size={15} /> :
                    <IcoTable size={15} />;

function CatalogHomePanel({ tree, onPick }: { tree: CatalogTree | null; onPick: (it: FlatItem) => void }) {
  const [view, setView]     = useState<"suggested" | "favorites" | "recents">("suggested");
  const [filter, setFilter] = useState("");
  const [favs, setFavs]       = useState<string[]>([]);
  const [recents, setRecents] = useState<string[]>([]);
  useEffect(() => { setFavs(readLS(FAVS_KEY)); setRecents(readLS(RECENTS_KEY)); }, []);

  const all   = useMemo(() => flattenTree(tree), [tree]);
  const byKey = useMemo(() => Object.fromEntries(all.map(i => [i.key, i])), [all]);

  const toggleFav = (k: string) => setFavs(prev => {
    const n = prev.includes(k) ? prev.filter(x => x !== k) : [k, ...prev];
    writeLS(FAVS_KEY, n);
    return n;
  });

  let items: FlatItem[];
  if (view === "favorites")    items = favs.map(k => byKey[k]).filter(Boolean);
  else if (view === "recents") items = recents.map(k => byKey[k]).filter(Boolean);
  else {
    const tables  = all.filter(i => i.type === "Table").sort((a, b) => (b.rows || 0) - (a.rows || 0));
    const schemas = all.filter(i => i.type === "Schema");
    const cats    = all.filter(i => i.type === "Catalog");
    items = [...tables.slice(0, 14), ...schemas.slice(0, 6), ...cats].slice(0, 26);
  }
  const q = filter.toLowerCase();
  if (q) items = items.filter(i => i.name.toLowerCase().includes(q) || i.path.toLowerCase().includes(q));

  const chips: { id: typeof view; label: string; icon: React.ReactNode }[] = [
    { id: "suggested", label: "Suggested", icon: <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M8 1.5a4.5 4.5 0 0 0-2.7 8.1c.4.3.7.8.7 1.4v.5h4v-.5c0-.6.3-1.1.7-1.4A4.5 4.5 0 0 0 8 1.5Z"/><path d="M6 14h4M6.5 15.5h3" strokeLinecap="round"/></svg> },
    { id: "favorites", label: "Favorites", icon: <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.2L8 11.6 4.2 13.5l.7-4.2-3.1-3 4.3-.6z"/></svg> },
    { id: "recents",   label: "Recents",   icon: <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="6.3"/><path d="M8 4.5V8l2.5 1.5" strokeLinecap="round" strokeLinejoin="round"/></svg> },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>
      {/* Header */}
      <div style={{ padding: "20px 28px 0", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <span style={{ color: "var(--t2)", display: "flex" }}><IcoCatalog color="var(--t2)" /></span>
          <h1 style={{ fontSize: 22, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.01em" }}>Catalog</h1>
        </div>

        {/* Chips + filter */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 2 }}>
          <div style={{ display: "flex", gap: 8 }}>
            {chips.map(c => {
              const on = view === c.id;
              return (
                <button key={c.id} onClick={() => setView(c.id)}
                  style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 500, padding: "6px 14px", borderRadius: 999, cursor: "pointer",
                    background: on ? "rgba(45,114,210,0.13)" : "transparent",
                    color: on ? "var(--blue5)" : "var(--t2)",
                    border: `1px solid ${on ? "rgba(45,114,210,0.45)" : "var(--b1)"}`, transition: "all .1s" }}
                  onMouseEnter={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "var(--b2)"; }}
                  onMouseLeave={e => { if (!on) (e.currentTarget as HTMLElement).style.borderColor = "var(--b1)"; }}
                >
                  <span style={{ display: "flex" }}>{c.icon}</span>{c.label}
                </button>
              );
            })}
          </div>
          <FilterBox value={filter} onChange={setFilter} placeholder="Filter…" />
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 16px 24px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1.6fr) 120px", padding: "7px 12px", borderBottom: "0.5px solid var(--b1)", position: "sticky", top: 0, background: "var(--bg-0)", zIndex: 1 }}>
          {["Name", view === "suggested" ? "Reason for suggestion" : "Location", "Type"].map(h => (
            <span key={h} style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</span>
          ))}
        </div>

        {items.length === 0 ? (
          <p style={{ fontSize: 12.5, color: "var(--t3)", padding: "28px 12px", lineHeight: 1.6 }}>
            {view === "favorites" ? "No favorites yet. Hover a row and tap the star to pin it here."
              : view === "recents" ? "No recent items yet. Open a table to see it here."
              : "No catalog items found. Add a connection to get started."}
          </p>
        ) : items.map(it => {
          const fav = favs.includes(it.key);
          return (
            <div key={it.key + view} onClick={() => onPick(it)}
              className="aug-home-row"
              style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1.6fr) 120px", alignItems: "center",
                padding: "10px 12px", borderBottom: "0.5px solid var(--b0)", cursor: "pointer", borderRadius: 4 }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                <span style={{ display: "flex", flexShrink: 0 }}>{typeIcon(it.type)}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--blue5)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
                  <div style={{ fontSize: 11, color: "var(--t3)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>{it.path}</div>
                </div>
              </div>
              <span style={{ fontSize: 12.5, color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {view === "suggested" ? it.reason : it.path}
              </span>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 12.5, color: "var(--t2)" }}>{it.type}</span>
                <button onClick={e => { e.stopPropagation(); toggleFav(it.key); }} title={fav ? "Unfavorite" : "Favorite"}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 2, color: fav ? "var(--amb4)" : "var(--t4)", display: "flex" }}
                  onMouseEnter={e => { if (!fav) (e.currentTarget as HTMLElement).style.color = "var(--t2)"; }}
                  onMouseLeave={e => { if (!fav) (e.currentTarget as HTMLElement).style.color = "var(--t4)"; }}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill={fav ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.2L8 11.6 4.2 13.5l.7-4.2-3.1-3 4.3-.6z"/></svg>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Right: Empty state ────────────────────────────────────────────────────────

function EmptyDetail() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 40 }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ color: "var(--b0)" }}>
        <ellipse cx="24" cy="14" rx="18" ry="7" stroke="currentColor" strokeWidth="2" />
        <path d="M6 14v20c0 3.9 8.1 7 18 7s18-3.1 18-7V14" stroke="currentColor" strokeWidth="2" fill="none" />
        <path d="M6 24c0 3.9 8.1 7 18 7s18-3.1 18-7" stroke="currentColor" strokeWidth="2" opacity=".5" />
      </svg>
      <div style={{ textAlign: "center" }}>
        <p style={{ fontSize: 14, fontWeight: 500, color: "var(--t4)", marginBottom: 6 }}>Select an item to view details</p>
        <p style={{ fontSize: 12, color: "var(--b0)", lineHeight: 1.6 }}>
          Click a catalog, schema, or table<br />in the tree to explore it
        </p>
      </div>
    </div>
  );
}

// ── Tree node ─────────────────────────────────────────────────────────────────

function TreeRow({
  depth, icon, label, badge, count, isOpen, isSelected, hasChildren, onClick, onToggle,
}: {
  depth:       number;
  icon:        React.ReactNode;
  label:       string;
  badge?:      React.ReactNode;
  count?:      number;
  isOpen?:     boolean;
  isSelected?: boolean;
  hasChildren?: boolean;
  onClick?:    () => void;
  onToggle?:   () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 7,
        padding: `6px 10px 6px ${10 + depth * 15}px`,
        cursor: "pointer", userSelect: "none",
        background: isSelected ? "rgba(45,114,210,0.11)" : "transparent",
        borderLeft: `2px solid ${isSelected ? "#2D72D2" : "transparent"}`,
        transition: "background .08s", minWidth: 0,
      }}
      onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)"; }}
      onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      {hasChildren ? (
        <span onClick={e => { e.stopPropagation(); onToggle?.(); }} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
          <Chevron open={!!isOpen} />
        </span>
      ) : <span style={{ width: 10, flexShrink: 0 }} />}

      <span style={{ color: isSelected ? "var(--blue4)" : "var(--t3)", display: "flex", alignItems: "center" }}>{icon}</span>

      <span style={{
        fontSize: 13, flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        color: isSelected ? "var(--t1)" : "#c5c8cd", fontWeight: isSelected ? 500 : 400,
      }}>
        {label}
      </span>

      {badge}

      {count != null && (
        <span style={{ fontSize: 9, color: "var(--t4)", flexShrink: 0 }}>
          {count}
        </span>
      )}
    </div>
  );
}

// ── Main CatalogScreen ────────────────────────────────────────────────────────

interface Props {
  connections:      Connection[];
  selectedConn:     string;
  onSelect:         (id: string) => void;
  onDeleteConn:     (conn: Connection) => void;
  onChatWithTable?: (table: string, connId: string) => void;
}

export function CatalogScreen({ connections, selectedConn, onSelect, onDeleteConn, onChatWithTable }: Props) {
  const { refresh: refreshSchema } = useSchema();
  const [tree, setTree]         = useState<CatalogTree | null>(null);
  const [treeLoading, setTreeL] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["section:samples", "catalog:samples"]));
  const [sel, setSel]           = useState<Sel>(null);
  const [adding, setAdding]     = useState(false);
  const [search, setSearch]     = useState("");
  const [hovConn, setHovConn]   = useState<string | null>(null);
  const [pendingDel, setPDel]   = useState<string | null>(null);
  const [testing, setTesting]   = useState<string | null>(null);
  const [testRes, setTestRes]   = useState<Record<string, boolean>>({});
  const [showERD, setShowERD]   = useState(false);
  const q = search.toLowerCase();
  const selConn = connections.find(c => c.id === selectedConn);

  const loadTree = () => {
    setTreeL(true);
    getCatalogTree()
      .then(t => {
        setTree(t);
        const uc = t.sections.find(s => s.id === "connections");
        if (uc && uc.entries.length > 0) {
          const first = uc.entries[0];
          setExpanded(prev => {
            const n = new Set(prev);
            n.add(`catalog:${first.conn_id}`);
            if (first.schemas.length === 1) n.add(`schema:${first.conn_id}:${first.schemas[0].name}`);
            return n;
          });
        }
      })
      .catch(err => console.error("[CatalogScreen] tree load failed:", err))
      .finally(() => setTreeL(false));
  };

  useEffect(() => { loadTree(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (key: string) => setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const isOpen = (key: string) => expanded.has(key);

  const handleDelete = (id: string) => {
    if (pendingDel !== id) {
      setPDel(id);
      setTimeout(() => setPDel(p => p === id ? null : p), 3000);
      return;
    }
    setPDel(null);
    const conn = connections.find(c => c.id === id);
    if (conn) onDeleteConn(conn);
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try { const r = await testConnection(id); setTestRes(p => ({ ...p, [id]: r.ok })); }
    catch { setTestRes(p => ({ ...p, [id]: false })); }
    finally { setTesting(null); }
  };

  const matches = (s: string) => !q || s.toLowerCase().includes(q);

  const renderTree = () => {
    if (!tree) return null;
    const nodes: React.ReactNode[] = [];

    tree.sections.forEach(section => {
      nodes.push(
        <div key={`sec-${section.id}`} style={{ padding: "14px 12px 5px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 10.5, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.09em" }}>
              {section.label}
            </span>
          </div>
          {section.id === "connections" && (
            <button onClick={() => setAdding(v => !v)}
              style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid #1e1f24" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--t2)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t4)"; }}
            >
              <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 1v10M1 6h10" /></svg>
              Add
            </button>
          )}
        </div>
      );

      if (section.id === "connections" && adding) {
        nodes.push(<AddConnForm key="add-form" onSave={() => { setAdding(false); loadTree(); }} onCancel={() => setAdding(false)} />);
      }
      if (section.entries.length === 0 && section.id === "connections") {
        nodes.push(<p key="empty" style={{ fontSize: 11, color: "var(--b0)", padding: "6px 12px 10px" }}>No connections yet.</p>);
      }

      section.entries.forEach(entry => {
        const catalogKey = `catalog:${entry.conn_id}`;
        const catOpen    = isOpen(catalogKey);
        const cm         = connMeta(entry.conn_type);
        const isSamples  = entry.conn_id === "samples";
        const catMatch   = matches(entry.name) || entry.schemas.some(sc => matches(sc.name) || sc.tables.some(t => matches(t.name)));
        if (!catMatch) return;

        nodes.push(
          <div key={catalogKey} style={{ position: "relative" }}
            onMouseEnter={() => setHovConn(entry.conn_id)}
            onMouseLeave={() => setHovConn(null)}
          >
            <TreeRow
              depth={0}
              icon={<IcoCatalog color="var(--t2)" />}
              label={entry.name}
              badge={<span style={{ fontSize: 9.5, fontWeight: 500, padding: "1px 6px", borderRadius: 4, background: "var(--bg-3)", color: "var(--t3)", border: "0.5px solid var(--b1)", flexShrink: 0, letterSpacing: "0.01em" }}>{cm.label}</span>}
              count={entry.schemas.reduce((s, sc) => s + sc.tables.length, 0) || undefined}
              isOpen={catOpen}
              isSelected={sel?.level === "catalog" && sel.connId === entry.conn_id}
              hasChildren={entry.schemas.length > 0}
              onClick={() => { setSel({ level: "catalog", connId: entry.conn_id, entry }); onSelect(entry.conn_id); }}
              onToggle={() => toggle(catalogKey)}
            />
            {!isSamples && hovConn === entry.conn_id && (
              <div style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", display: "flex", gap: 4, zIndex: 2 }}>
                <button onClick={e => { e.stopPropagation(); handleTest(entry.conn_id); }} disabled={testing === entry.conn_id}
                  style={{ fontSize: 8, padding: "2px 5px", borderRadius: 2, cursor: "pointer", background: "#1a1a22", color: testRes[entry.conn_id] === true ? "#34d399" : testRes[entry.conn_id] === false ? "#f87171" : "var(--t4)", border: "0.5px solid #2a2b35" }}>
                  {testing === entry.conn_id ? "…" : testRes[entry.conn_id] === true ? "✓" : testRes[entry.conn_id] === false ? "✗" : "Test"}
                </button>
                <button onClick={e => { e.stopPropagation(); handleDelete(entry.conn_id); }}
                  style={{ fontSize: 8, padding: "2px 5px", borderRadius: 2, cursor: "pointer", background: pendingDel === entry.conn_id ? "#2a1414" : "#1a1a22", color: pendingDel === entry.conn_id ? "#f87171" : "var(--t4)", border: `0.5px solid ${pendingDel === entry.conn_id ? "#3e2020" : "#2a2b35"}` }}>
                  {pendingDel === entry.conn_id ? "Confirm" : "×"}
                </button>
              </div>
            )}
          </div>
        );

        if (!catOpen) return;

        entry.schemas.forEach(schema => {
          const schemaKey = `schema:${entry.conn_id}:${schema.name}`;
          const schOpen   = isOpen(schemaKey);
          const schMatch  = matches(entry.name) || matches(schema.name) || schema.tables.some(t => matches(t.name));
          if (!schMatch) return;

          nodes.push(
            <TreeRow key={schemaKey} depth={1}
              icon={<IcoSchema color="#5a7fa8" />}
              label={schema.name}
              count={schema.tables.length}
              isOpen={schOpen}
              isSelected={sel?.level === "schema" && sel.connId === entry.conn_id && sel.schemaName === schema.name}
              hasChildren={schema.tables.length > 0}
              onClick={() => setSel({ level: "schema", connId: entry.conn_id, schemaName: schema.name, entry: schema })}
              onToggle={() => toggle(schemaKey)}
            />
          );

          if (!schOpen) return;

          schema.tables.forEach(table => {
            if (!matches(table.name) && !matches(schema.name) && !matches(entry.name)) return;
            const tableKey = `table:${entry.conn_id}:${schema.name}:${table.name}`;
            const isSel = sel?.level === "table" && sel.connId === entry.conn_id && sel.schemaName === schema.name && sel.table.name === table.name;

            nodes.push(
              <TreeRow key={tableKey} depth={2}
                icon={<IcoTable active={isSel} />}
                label={table.name}
                isSelected={isSel}
                hasChildren={false}
                onClick={() => { pushRecent(`${entry.conn_id}:${schema.name}:${table.name}`); setSel({ level: "table", connId: entry.conn_id, schemaName: schema.name, table }); }}
              />
            );
          });
        });
      });
    });
    return nodes;
  };

  const renderDetail = () => {
    if (!sel) return (
      <CatalogHomePanel tree={tree} onPick={it => {
        setExpanded(p => { const n = new Set(p); n.add(`catalog:${it.connId}`); if (it.schemaName) n.add(`schema:${it.connId}:${it.schemaName}`); return n; });
        onSelect(it.connId);
        const cat = tree?.sections.flatMap(s => s.entries).find(e => e.conn_id === it.connId);
        if (!cat) return;
        if (it.type === "Table" && it.schemaName && it.tableName) {
          const sc = cat.schemas.find(s => s.name === it.schemaName);
          const tb = sc?.tables.find(t => t.name === it.tableName);
          if (tb) { pushRecent(it.key); setSel({ level: "table", connId: it.connId, schemaName: it.schemaName, table: tb }); }
        } else if (it.type === "Schema" && it.schemaName) {
          const sc = cat.schemas.find(s => s.name === it.schemaName);
          if (sc) setSel({ level: "schema", connId: it.connId, schemaName: it.schemaName, entry: sc });
        } else {
          setSel({ level: "catalog", connId: it.connId, entry: cat });
        }
      }} />
    );
    if (sel.level === "table") return <TableDetailPanel sel={sel} onAsk={onChatWithTable} />;
    if (sel.level === "schema") return (
      <SchemaDetailPanel sel={sel}
        onSelectTable={t => setSel({ level: "table", connId: sel.connId, schemaName: sel.schemaName, table: t })}
        onAsk={onChatWithTable}
      />
    );
    if (sel.level === "catalog") return (
      <CatalogDetailPanel sel={sel}
        conn={connections.find(c => c.id === sel.connId)}
        onSelectSchema={sc => {
          setSel({ level: "schema", connId: sel.connId, schemaName: sc.name, entry: sc });
          setExpanded(p => { const n = new Set(p); n.add(`schema:${sel.connId}:${sc.name}`); return n; });
        }}
      />
    );
    return <EmptyDetail />;
  };

  return (
    <div style={{ display: "flex", flexDirection: "row", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>

      {/* ── Left: Tree navigator ── */}
      <div style={{ width: 340, borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-1)", flexShrink: 0 }}>
        {/* Top bar */}
        <div style={{ display: "flex", alignItems: "center", padding: "10px 12px 8px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, gap: 8 }}>
          <button onClick={() => setSel(null)} title="Catalog home"
            style={{ fontSize: 12, fontWeight: 600, color: sel ? "var(--t3)" : "var(--t1)", textTransform: "uppercase", letterSpacing: "0.06em", flex: 1, textAlign: "left", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: "inherit" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t1)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = sel ? "var(--t3)" : "var(--t1)"}
          >Catalog</button>
          <button
            onClick={() => setShowERD(v => !v)}
            title={showERD ? "Table view" : "ERD view"}
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: showERD ? "#1a1e2e" : "transparent", color: showERD ? "var(--blue4)" : "var(--t4)", border: showERD ? "0.5px solid #2a3050" : "0.5px solid #1e1f24", padding: 0, marginRight: 4, fontSize: 9, fontWeight: 700, letterSpacing: "0.02em" }}
          >
            ERD
          </button>
          <button onClick={() => { loadTree(); refreshSchema(); }} title="Refresh schema"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid #1e1f24", padding: 0 }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t2)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "var(--t4)"}
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 4.5A7 7 0 0 1 14 8" /><path d="M15 11.5A7 7 0 0 1 2 8" />
              <polyline points="1 1 1 5 5 5" /><polyline points="15 15 15 11 11 11" />
            </svg>
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: "8px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, position: "relative" }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
            style={{ position: "absolute", left: 18, top: "50%", transform: "translateY(-50%)", color: "var(--t4)", pointerEvents: "none" }}>
            <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
          </svg>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search catalog…"
            style={{ width: "100%", fontSize: 11, padding: "4px 8px 4px 24px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid #1e1f24", color: "#6e6f78", outline: "none" }} />
        </div>

        {/* Tree body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 0 12px" }}>
          {treeLoading && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 24, gap: 8 }}>
              <div style={{ width: 14, height: 14, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
              <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading catalog…</span>
            </div>
          )}
          {!treeLoading && renderTree()}
        </div>
      </div>

      {/* ── Right: Detail panel or ERD ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {showERD
          ? <SchemaPanel connId={selectedConn} connName={selConn?.name} />
          : renderDetail()
        }
      </div>

    </div>
  );
}
