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
import { SqlResultTable } from "@/components/AugTable";
import { useSchema } from "@/lib/schema-context";
import { compactNumber, isNumericType } from "@/lib/format";
import { bare, schemaOf } from "@/lib/tableName";
import {
  getCatalogTree, getConnections, addConnection, deleteConnection,
  testConnection, sampleTable, getSchemaRich, getTableColumns, getExplorationFindings,
  deleteConnectionSchema, deleteConnectionTable,
  alterColumn, getConnectionSettings, updateConnectionSettings,
  type CatalogTree, type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo,
  type Connection, type SchemaTable, type SchemaColumn, type TableSample,
  type TableColumn, type DistributionProfile, type RichSchema,
} from "@/lib/api";
import { ERDiagram } from "@/components/ERDiagram";
import { SchemaShape } from "@/components/SchemaShape";
import { VolumesPanel, PermissionsPanel } from "@/components/catalog/MetastorePanels";
import { GlossaryPanel } from "@/components/catalog/GlossaryPanel";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { SchemaPanel } from "@/components/SchemaPanel";
import { DocumentUploader } from "@/components/DocumentUploader";
import { AddDataPanel } from "@/components/AddDataPanel";
import { ResizableSplit } from "@/components/ResizableSplit";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRows(n: number | string | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (isNaN(num)) return "—";
  return compactNumber(num, 1);
}

const TYPE_OPTIONS = [
  "VARCHAR", "TEXT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
  "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "BOOLEAN",
  "DATE", "TIMESTAMP", "TIME", "TIMESTAMPTZ", "INTERVAL",
  "BLOB", "JSON", "UUID",
];

function typeColor(t: string): string {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT"))                  return "var(--blue4)";
  if (u.includes("BIGINT") || u.includes("INT"))                    return "var(--vio4)";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "var(--grn4)";
  if (u.includes("DATE") || u.includes("TIME"))                     return "var(--amb4)";
  if (u.includes("BOOL"))                                           return "var(--grn4)";
  return "var(--t2)";
}

// ── Distribution mini-viz (shared with exploration) ──────────────────────────

const DIST_SHAPE_PILL: Record<string, { label: string; bg: string; text: string; border: string; barColor: string }> = {
  fraction_0_1: { label: "0–1 ratio",    bg: "var(--grn1)", text: "var(--grn4)", border: "var(--grn2)", barColor: "var(--grn2)" },
  normal:       { label: "Normal",        bg: "var(--blue1)", text: "var(--blue4)", border: "var(--blue2)", barColor: "var(--blue2)" },
  concentrated: { label: "Concentrated", bg: "var(--vio1)", text: "var(--vio4)", border: "var(--vio2)", barColor: "var(--vio2)" },
  skewed_right: { label: "Right-skewed", bg: "var(--amb1)", text: "var(--amb4)", border: "var(--amb2)", barColor: "var(--amb2)" },
  skewed_left:  { label: "Left-skewed",  bg: "var(--amb1)", text: "var(--amb4)", border: "var(--amb2)", barColor: "var(--amb2)" },
  uniform:      { label: "Uniform",      bg: "var(--grn1)", text: "var(--grn4)", border: "var(--grn2)", barColor: "var(--grn2)" },
  bimodal:      { label: "Bimodal",      bg: "var(--red1)", text: "var(--red4)", border: "var(--red2)", barColor: "var(--red2)" },
};

function miniBarHeights(shape: string): number[] {
  switch (shape) {
    case "normal":       return [4, 8, 22, 24, 16, 6];
    case "fraction_0_1": return [6, 14, 24, 16, 8, 4];
    case "concentrated": return [3, 10, 24, 18, 8, 3];
    case "skewed_right": return [24, 20, 14, 8, 4, 2];
    case "skewed_left":  return [2, 4, 8, 14, 20, 24];
    case "uniform":      return [20, 22, 22, 21, 20, 21];
    case "bimodal":      return [20, 8, 4, 8, 22, 16];
    default:             return [10, 14, 18, 16, 12, 8];
  }
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return compactNumber(n, 1);
}

/** Compact per-column distribution strip shown under a column row in Catalog. */
function ColumnDistribution({ d }: { d: DistributionProfile }) {
  const pill = DIST_SHAPE_PILL[d.shape] ?? { label: d.shape, bg: "var(--bg-1)", text: "var(--t3)", border: "var(--b1)", barColor: "var(--b2)" };
  const barH = miniBarHeights(d.shape);
  const maxH = Math.max(...barH);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "6px 16px 8px 30px", background: "var(--bg-0)", borderBottom: "0.5px solid var(--b0)" }}>
      {/* mini histogram */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 1.5, height: 24, width: 64, flexShrink: 0 }}>
        {barH.map((h, i) => (
          <div key={i} style={{ flex: 1, height: `${h}px`, background: h >= maxH * 0.6 ? pill.barColor : "var(--b2)", borderRadius: "2px 2px 0 0" }} />
        ))}
      </div>
      {/* percentiles */}
      <div style={{ display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 11 }}>
        {([["p25", d.p25], ["p50", d.p50], ["p75", d.p75], ["mean", d.mean]] as const).map(([label, value]) => (
          <div key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ color: "var(--t3)", letterSpacing: "0.04em" }}>{label}</span>
            <span style={{ color: label === "p50" || label === "mean" ? "var(--t1)" : "var(--t2)" }}>{fmtNum(value)}</span>
          </div>
        ))}
        {d.min != null && d.max != null && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <span style={{ color: "var(--t3)", letterSpacing: "0.04em" }}>range</span>
            <span style={{ color: "var(--t2)" }}>{fmtNum(d.min)}–{fmtNum(d.max)}</span>
          </div>
        )}
      </div>
      {/* shape pill */}
      <span style={{ marginLeft: "auto", fontSize: 11, padding: "1px 8px", borderRadius: 4, whiteSpace: "nowrap", background: pill.bg, color: pill.text, border: `0.5px solid ${pill.border}` }}>
        {pill.label}
      </span>
    </div>
  );
}

const CONN_TAG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  duckdb:       { label: "DuckDB",      color: "#fbbf24", bg: "var(--amb1)", border: "var(--amb2)" },
  postgres:     { label: "Postgres",    color: "var(--blue4)", bg: "var(--blue1)", border: "var(--blue2)" },
  bigquery:     { label: "BigQuery",    color: "var(--grn4)", bg: "var(--grn1)", border: "var(--grn2)" },
  snowflake:    { label: "Snowflake",   color: "var(--blue4)", bg: "var(--blue1)", border: "var(--blue2)" },
  mysql:        { label: "MySQL",       color: "var(--amb4)", bg: "var(--amb1)", border: "var(--amb2)" },
  local_upload: { label: "Files",       color: "var(--vio4)", bg: "var(--vio1)", border: "var(--vio2)" },
  s3:           { label: "S3",          color: "var(--amb4)", bg: "var(--amb1)", border: "var(--amb2)" },
  federated:    { label: "Federated",   color: "var(--grn4)", bg: "var(--grn1)", border: "var(--grn2)" },
  stripe:       { label: "Stripe",      color: "var(--blue4)", bg: "var(--blue1)", border: "var(--blue2)" },
  hubspot:      { label: "HubSpot",     color: "var(--amb4)", bg: "var(--amb1)", border: "var(--amb2)" },
  salesforce:   { label: "Salesforce",  color: "var(--cyn4)", bg: "var(--cyn1)", border: "var(--cyn2)" },
  confluence:   { label: "Confluence",  color: "var(--blue4)", bg: "var(--blue1)", border: "var(--blue2)" },
  notion:       { label: "Notion",      color: "var(--t2)", bg: "var(--bg-1)", border: "var(--b2)" },
};

// ── Connector action panel (sync / upload / knowledge-sync) ───────────────────

import { API_BASE as BASE_API } from "@/lib/config";

const _SYNCABLE      = ["stripe", "hubspot", "salesforce", "s3"];
const _KNOWLEDGE     = ["confluence", "notion"];
const _FILE_UPLOAD   = ["local_upload"];

/** Per-connection opt-in for the Briefing workspace. Opt-out by default (enabled
 *  unless turned off here); persisted via connection settings. */
function BriefingsToggle({ connId }: { connId: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [saving, setSaving]   = useState(false);

  useEffect(() => {
    let alive = true;
    getConnectionSettings(connId)
      .then(s => { if (alive) setEnabled(s.briefings_enabled !== false); })
      .catch(() => { if (alive) setEnabled(true); });
    return () => { alive = false; };
  }, [connId]);

  const toggle = async () => {
    if (enabled === null || saving) return;
    const next = !enabled;
    setEnabled(next);
    setSaving(true);
    try { await updateConnectionSettings(connId, { briefings_enabled: next }); }
    catch { setEnabled(!next); }
    finally { setSaving(false); }
  };

  return (
    <div style={{ padding: "12px 16px", borderTop: "0.5px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>Briefings</div>
        <div style={{ fontSize: 11, color: "var(--t3)" }}>Show this connection in the Briefing workspace.</div>
      </div>
      <button
        role="switch"
        aria-checked={enabled === true}
        aria-label="Enable briefings for this connection"
        disabled={enabled === null || saving}
        onClick={toggle}
        style={{
          flexShrink: 0, width: 38, height: 22, borderRadius: 11, position: "relative", padding: 0,
          cursor: enabled === null ? "default" : "pointer", border: "none",
          background: enabled ? "var(--blue3)" : "var(--bg-3)", transition: "background .15s", opacity: saving ? 0.6 : 1,
        }}
      >
        <span style={{
          position: "absolute", top: 2, left: enabled ? 18 : 2, width: 18, height: 18, borderRadius: "50%",
          background: "var(--bg-0)", transition: "left .15s",
        }} />
      </button>
    </div>
  );
}

function ConnectorActions({ connId, connType }: { connId: string; connType: string }) {
  const [status, setStatus]   = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [files,   setFiles]   = useState<Array<{ filename: string; table_name: string; size_bytes: number }>>([]);
  const [uploading, setUploading] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);
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

  const handleRestoreSamples = async () => {
    setRestoreMsg("Restoring…");
    try {
      const r = await fetch(`${BASE_API}/connections/${connId}/restore-samples`, { method: "POST" });
      setRestoreMsg(r.ok ? "Sample data restored — refresh to see it." : "Restore failed.");
    } catch {
      setRestoreMsg("Restore failed.");
    }
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
    <div style={{ padding: "12px 16px", borderTop: "0.5px solid var(--b1)" }}>
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
          <button onClick={handleRestoreSamples}
            style={{ marginTop: 10, background: "none", border: "none", cursor: "pointer", color: "var(--t4)", padding: 0, fontSize: 11, textDecoration: "underline" }}
            title="Re-add the bundled sample schemas you previously removed">
            Restore sample data
          </button>
          {restoreMsg && <p style={{ fontSize: 11, color: "var(--t4)", marginTop: 6 }}>{restoreMsg}</p>}
        </div>
      )}
    </div>
  );
}
const connMeta = (t: string) => CONN_TAG[t] ?? { label: t, color: "var(--t2)", bg: "var(--bg-1)", border: "var(--b2)" };

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
    <div style={{ padding: "16px 20px 12px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, background: "var(--bg-0)" }}>
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
    <div style={{ display: "flex", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, padding: "0 8px", background: "var(--bg-0)" }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            fontSize: 12, padding: "8px 12px", cursor: "pointer", border: "none",
            background: "transparent", fontFamily: "inherit",
            color: active === t.id ? "var(--t1)" : "var(--t4)",
            borderBottom: `2px solid ${active === t.id ? "var(--blue4)" : "transparent"}`,
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
      width: 220, flexShrink: 0, borderLeft: "0.5px solid var(--b1)",
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
        style={{ fontSize: 11, padding: "5px 8px 5px 26px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid var(--b1)", color: "var(--t2)", outline: "none", width: 220 }}
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

  const S: React.CSSProperties = { width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid var(--b2)", color: "var(--t1)", outline: "none", fontFamily: "inherit" };
  const L: React.CSSProperties = { fontSize: 11, color: "var(--t4)", marginBottom: 3, display: "block" };

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoad(true);
    try { await addConnection(name, type, dsn, schema || undefined); onSave(); }
    catch (ex: unknown) { setErr((ex as Error).message); }
    finally { setLoad(false); }
  };

  return (
    <form onSubmit={handle} style={{ padding: "10px 12px", background: "var(--bg-0)", borderBottom: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", gap: 8 }}>
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
        <label style={L}>Schema <span style={{ color: "var(--t4)" }}>(optional)</span></label>
        <input style={{ ...S, fontFamily: "var(--font-mono)" }} placeholder={type === "postgres" ? "public" : "main"} value={schema} onChange={e => setSchema(e.target.value)} />
      </div>
      {err && <p style={{ fontSize: 11, color: "var(--red4)" }}>{err}</p>}
      <div style={{ display: "flex", gap: 6 }}>
        <button type="submit" disabled={loading} style={{ flex: 1, fontSize: 11, padding: "5px 0", borderRadius: 4, cursor: "pointer", background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)", opacity: loading ? .5 : 1 }}>
          {loading ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} style={{ fontSize: 11, padding: "5px 10px", borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid var(--b1)" }}>Cancel</button>
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
      .then(d => {
        // Three distinct states: execution error ≠ empty table ≠ data.
        if (d.error) setErr(d.error);
        else setData(d);
      })
      .catch(e => setErr(`Could not load sample: ${(e as Error).message}`))
      .finally(() => setLoad(false));
  }, [connId, tableName, schemaName]);

  if (loading) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 8 }}>
      <div style={{ width: 16, height: 16, border: "2px solid var(--b2)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
      <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading sample data…</span>
    </div>
  );
  if (error) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ maxWidth: 460, textAlign: "center" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--red4)", marginBottom: 4 }}>Sample unavailable</div>
        <div style={{ fontSize: 11, color: "var(--t3)", wordBreak: "break-word" }}>{error}</div>
      </div>
    </div>
  );
  if (!data || data.rows.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 11, color: "var(--t4)" }}>Table is empty — no rows to display.</span>
    </div>
  );

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 12 }}>
      <SqlResultTable columns={data.columns} rows={data.rows as unknown[][]} maxHeight={520} />
      <div style={{ padding: "5px 4px", fontSize: 11, color: "var(--t4)" }}>
        {data.rows.length} row{data.rows.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

// ── Right: TABLE detail ───────────────────────────────────────────────────────

type TableTab = "overview" | "sample" | "comments";

function TableDetailPanel({ sel, onAsk, onRemoved }: {
  sel:   Extract<Sel, { level: "table" }>;
  onAsk?: (table: string, connId: string) => void;
  onRemoved?: () => void;
}) {
  const [tab, setTab]           = useState<TableTab>("overview");
  const [colFilter, setColFilter] = useState("");
  const [richTable, setRich]    = useState<SchemaTable | null>(null);
  const [baseCols, setBaseCols] = useState<TableColumn[]>([]);
  const [loading, setLoad]      = useState(false);
  const [distMap, setDistMap]   = useState<Record<string, DistributionProfile>>({});
  const [expandedCols, setExpandedCols] = useState<Set<string>>(new Set());
  const [editingCol, setEditingCol]   = useState<string | null>(null);
  const [editType, setEditType]       = useState("");
  const [alterBusy, setAlterBusy]     = useState(false);

  // Fetch column detail when table changes. The authoritative column list comes
  // from the reliable per-table reader (same path as Sample Data); the heavy
  // whole-connection rich schema only layers on FK flags + descriptions.
  useEffect(() => {
    setTab("overview"); setColFilter(""); setRich(null); setBaseCols([]); setExpandedCols(new Set());
    setLoad(true);
    getTableColumns(sel.connId, sel.table.name, sel.schemaName)
      .then(setBaseCols)
      .catch(err => { console.error("[Catalog] getTableColumns failed:", err); setBaseCols([]); })
      .finally(() => setLoad(false));
    getSchemaRich(sel.connId)
      .then(s => setRich(s.tables.find(t => t.name === sel.table.name) ?? null))
      .catch(err => { console.error("[Catalog] getSchemaRich failed:", err); setRich(null); });
  }, [sel.connId, sel.schemaName, sel.table.name]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch column distributions (exploration profiling) for this table
  useEffect(() => {
    setDistMap({});
    getExplorationFindings(sel.connId)
      .then(f => {
        const m: Record<string, DistributionProfile> = {};
        // The explorer keys distributions as "<table>:<column>", where <table>
        // may be schema-qualified (e.g. "public.orders") while the catalog tree
        // exposes the bare table name. Match leniently on the final segment.
        const target = bare(sel.table.name);
        for (const [key, d] of Object.entries(f.distributions ?? {})) {
          const sep = key.lastIndexOf(":");
          if (sep < 0) continue;
          const tbl = key.slice(0, sep);
          const col = key.slice(sep + 1);
          if (bare(tbl) === target && col && d.shape !== "unknown") m[col] = d;
        }
        setDistMap(m);
      })
      .catch(() => setDistMap({}));
  }, [sel.connId, sel.table.name]);

  // Unify: authoritative per-table columns, enriched with rich-schema FK/desc.
  const enrichMap = new Map((richTable?.columns ?? []).map(c => [c.name, c]));
  const cols: SchemaColumn[] = baseCols.length
    ? baseCols.map(b => {
        const e = enrichMap.get(b.name);
        const overrideType = b.type?.trim?.() ? b.type : undefined;
        return { ...(e ?? {}), name: b.name, type: overrideType ?? e?.type ?? "" } as SchemaColumn;
      })
    : (richTable?.columns ?? []);
  const q    = colFilter.toLowerCase();
  const filteredCols = q ? cols.filter(c => c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q)) : cols;
  const fkCount = cols.filter(c => c.is_fk).length;
  // Distributions (p25/p50/mean/…) only make sense for numeric columns. Gate on the
  // column's *live* declared type — so a VARCHAR id never shows numeric percentiles,
  // and saving a column's type to VARCHAR immediately hides its (stale) distribution.
  const numericDist = (c: SchemaColumn) => (isNumericType(c.type) ? distMap[c.name] : undefined);
  const distCount = cols.filter(numericDist).length;
  const toggleCol = (name: string) => setExpandedCols(prev => { const n = new Set(prev); n.has(name) ? n.delete(name) : n.add(name); return n; });

  const handleSave = async (colName: string) => {
    if (!editType.trim() || editType.trim() === (cols.find(c => c.name === colName)?.type ?? "")) {
      setEditingCol(null);
      return;
    }
    setAlterBusy(true);
    try {
      const res = await alterColumn(sel.connId, sel.table.name, colName, editType.trim(), sel.schemaName);
      // Refresh columns and rich schema so both are in sync
      const [refreshed, rich] = await Promise.all([
        getTableColumns(sel.connId, sel.table.name, sel.schemaName),
        getSchemaRich(sel.connId).then(s => s.tables.find(t => t.name === sel.table.name) ?? null).catch(() => null),
      ]);
      setBaseCols(refreshed);
      if (rich) setRich(rich);
      // Be honest when the change is a display-only override (connector can't ALTER).
      if (res && res.applied === false && res.message) alert(res.message);
    } catch (e) {
      alert((e as Error).message || "Failed to alter column");
    } finally {
      setAlterBusy(false);
      setEditingCol(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <DetailHeader
        icon={<IcoTable active size={16} />}
        name={sel.table.name}
        breadcrumb={`${sel.connId}  ›  ${sel.schemaName}`}
        meta={`${fmtRows(sel.table.row_count)} rows · ${cols.length || "…"} columns${fkCount ? ` · ${fkCount} FK` : ""}`}
      />

      <TabBar
        tabs={[{ id: "overview", label: "Overview" }, { id: "sample", label: "Sample Data" }, { id: "comments", label: "Comments" }]}
        active={tab}
        onChange={id => setTab(id as TableTab)}
      />

      {/* ── Comments (glossary) tab ── */}
      {tab === "comments" && (
        <GlossaryPanel table={bare(sel.table.name)} columns={cols.map(c => c.name)} />
      )}

      {/* ── Overview tab ── */}
      {tab === "overview" && (
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          {/* Main: column list */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* Filter row */}
            <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, background: "var(--bg-0)", display: "flex", alignItems: "center", gap: 10 }}>
              <FilterBox value={colFilter} onChange={setColFilter} placeholder="Filter columns…" />
              {distCount > 0 && (
                <span style={{ fontSize: 11, color: "var(--t4)" }}>{distCount} profiled · click a column for its distribution</span>
              )}
              {onAsk && (
                <button onClick={() => onAsk(sel.table.name, sel.connId)}
                  style={{ marginLeft: "auto", fontSize: 11, padding: "4px 11px", borderRadius: 4, cursor: "pointer", background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)", whiteSpace: "nowrap" }}>
                  Ask about this table →
                </button>
              )}
              {onRemoved && (
                <button onClick={async () => {
                  if (!confirm(`Remove table "${sel.table.name}" from the workspace? This drops the table and deletes its uploaded file.`)) return;
                  try { await deleteConnectionTable(sel.connId, sel.table.name, sel.schemaName); onRemoved(); }
                  catch (e) { alert((e as Error).message); }
                }}
                  style={{ marginLeft: onAsk ? 0 : "auto", fontSize: 11, padding: "4px 11px", borderRadius: 4, cursor: "pointer", background: "var(--red1)", color: "var(--red4)", border: "0.5px solid var(--red2)", whiteSpace: "nowrap" }}>
                  Remove
                </button>
              )}
            </div>

            {/* Column header */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "5px 16px", borderBottom: "0.5px solid var(--b1)", background: "var(--bg-0)", flexShrink: 0 }}>
              {["Column", "Type", ""].map(h => (
                <span key={h} style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600 }}>{h}</span>
              ))}
            </div>

            {/* Column rows */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {loading && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 32, gap: 8 }}>
                  <div style={{ width: 14, height: 14, border: "2px solid var(--b2)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading columns…</span>
                </div>
              )}
              {!loading && filteredCols.length === 0 && (
                <p style={{ padding: "20px 16px", fontSize: 11, color: "var(--t4)" }}>
                  {q ? "No columns match." : "Column details unavailable."}
                </p>
              )}
              {!loading && filteredCols.map((col) => {
                const dist = numericDist(col);
                const open = expandedCols.has(col.name);
                return (
                <div key={col.name}>
                  <div
                    onClick={dist ? () => toggleCol(col.name) : undefined}
                    style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "6px 16px", borderBottom: "0.5px solid var(--b0)", alignItems: "center", background: open ? "var(--bg-0)" : "transparent", cursor: dist ? "pointer" : "default" }}
                    onMouseEnter={e => { if (!open) (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"; }}
                    onMouseLeave={e => { if (!open) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }} title={col.description || ""}>
                      {dist
                        ? <span style={{ flexShrink: 0, display: "flex" }}><Chevron open={open} /></span>
                        : <span style={{ width: 6, height: 6, borderRadius: 2, flexShrink: 0, background: typeColor(col.type), opacity: 0.7 }} />}
                      <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.name}</span>
                      {col.description && (
                        <span style={{ fontSize: 11, color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>{col.description}</span>
                      )}
                    </div>
                    {editingCol === col.name ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <select
                          value={editType}
                          onChange={e => setEditType(e.target.value)}
                          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); handleSave(col.name); } if (e.key === "Escape") { setEditingCol(null); } }}
                          autoFocus
                          style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: typeColor(editType), background: "var(--bg-0)", border: "0.5px solid var(--blue2)", borderRadius: 3, padding: "2px 5px", width: 110, outline: "none", cursor: "pointer" }}
                        >
                          {TYPE_OPTIONS.map(t => (
                            <option key={t} value={t} style={{ background: "var(--bg-0)", color: "var(--t1)" }}>{t}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => handleSave(col.name)}
                          disabled={alterBusy}
                          style={{ fontSize: 9, padding: "1px 4px", borderRadius: 3, background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)", cursor: "pointer" }}
                        >Save</button>
                      </div>
                    ) : (
                      <span
                        onClick={() => { setEditingCol(col.name); setEditType(col.type); }}
                        title="Click to edit type"
                        style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: typeColor(col.type || "--"), cursor: "pointer", borderBottom: "1px dashed var(--b2)" }}
                      >{col.type || "—"}</span>
                    )}
                    {col.is_fk
                      ? <span style={{ fontSize: 9, padding: "2px 5px", borderRadius: 3, background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)" }}>FK</span>
                      : <span />
                    }
                  </div>
                  {dist && open && <ColumnDistribution d={dist} />}
                </div>
              ); })}
            </div>
          </div>
        </div>
      )}

      {/* ── Sample Data tab ── */}
      {tab === "sample" && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, background: "var(--bg-0)", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>First 200 rows</span>
          </div>
          <SampleGrid connId={sel.connId} tableName={sel.table.name} schemaName={sel.schemaName} />
        </div>
      )}
    </div>
  );
}

// ── Right: SCHEMA detail ──────────────────────────────────────────────────────

type SchemaTab = "tables" | "erd" | "shape";

function SchemaDetailPanel({ sel, onSelectTable, onAsk, connName, onRemoved }: {
  sel:           Extract<Sel, { level: "schema" }>;
  onSelectTable: (table: CatalogTableInfo) => void;
  onAsk?:        (table: string, connId: string) => void;
  connName?:     string;
  onRemoved?:    () => void;
}) {
  const [filter, setFilter] = useState("");
  const [tab, setTab]       = useState<SchemaTab>("tables");
  const [erdSchema, setErdSchema] = useState<RichSchema | null>(null);
  const [erdLoading, setErdLoading] = useState(false);
  const [erdError, setErdError]   = useState<string | null>(null);
  const { entry } = sel;
  const q = filter.toLowerCase();
  const tables = q ? entry.tables.filter(t => t.name.toLowerCase().includes(q)) : entry.tables;
  const totalRows = entry.tables.reduce((s, t) => s + (Number(t.row_count) || 0), 0);

  // Fetch rich schema and filter to the selected schema's tables
  useEffect(() => {
    if (tab !== "erd") return;
    setErdLoading(true);
    setErdError(null);
    getSchemaRich(sel.connId)
      .then(full => {
        // The rich schema reports fully-qualified names (bakehouse.media_reviews)
        // while the catalog entry lists bare names (media_reviews). Matching them
        // directly filters a multi-schema connection's ERD down to nothing
        // ("No tables found"). Match on the bare last segment, scoped to this
        // schema, and keep the original qualified names so the diagram's internal
        // table↔join matching stays consistent.
        const allowed = new Set(entry.tables.map(t => bare(t.name)));
        const inSchema = (n: string) => {
          const s = schemaOf(n);
          const schemaOk = !s || s === entry.name.toLowerCase();
          return schemaOk && allowed.has(bare(n));
        };
        const filtered: RichSchema = {
          tables: full.tables.filter(t => inSchema(t.name)),
          joins: full.joins.filter(j => inSchema(j.t1) && inSchema(j.t2)),
          isolated: full.isolated?.filter(n => inSchema(n)) ?? [],
          warnings: full.warnings ?? [],
        };
        setErdSchema(filtered);
      })
      .catch(() => setErdError("Failed to load schema diagram"))
      .finally(() => setErdLoading(false));
  }, [sel.connId, entry.name, tab, entry.tables]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <DetailHeader
        icon={<IcoSchema color="var(--blue3)" size={16} />}
        name={entry.name}
        breadcrumb={sel.connId}
        meta={`${entry.tables.length} table${entry.tables.length !== 1 ? "s" : ""}`}
      />

      <TabBar
        tabs={[
          { id: "tables", label: `Tables  ${entry.tables.length}` },
          { id: "erd", label: "ERD" },
          { id: "shape", label: "Schema Shape" },
        ]}
        active={tab}
        onChange={id => setTab(id as SchemaTab)}
      />

      {tab === "shape" ? (
        <div style={{ flex: 1, overflow: "hidden", minWidth: 0, display: "flex", flexDirection: "column" }}>
          <SchemaShape connectionId={sel.connId} schemaTables={entry.tables.map(t => t.name)} />
        </div>
      ) : tab === "erd" ? (
        <div style={{ flex: 1, overflow: "hidden", minWidth: 0 }}>
          {erdLoading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", gap: 8 }}>
              <div style={{ width: 14, height: 14, border: "2px solid var(--b2)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
              <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading diagram…</span>
            </div>
          ) : erdError ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>{erdError}</span>
            </div>
          ) : erdSchema ? (
            <ERDiagram schema={erdSchema} />
          ) : null}
        </div>
      ) : (
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main: table list */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Filter row */}
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, background: "var(--bg-0)", display: "flex", alignItems: "center", gap: 10 }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter tables…" />
            {onRemoved && entry.name.toLowerCase() !== "main" && (
              <button onClick={async () => {
                if (!confirm(`Remove the entire "${entry.name}" schema from the workspace? This drops all ${entry.tables.length} table(s), their files, and this dataset's saved intelligence (profile + exploration).`)) return;
                try { await deleteConnectionSchema(sel.connId, entry.name); onRemoved(); }
                catch (e) { alert((e as Error).message); }
              }}
                style={{ marginLeft: "auto", fontSize: 11, padding: "4px 11px", borderRadius: 4, cursor: "pointer", background: "var(--red1)", color: "var(--red4)", border: "0.5px solid var(--red2)", whiteSpace: "nowrap" }}>
                Remove schema
              </button>
            )}
          </div>

          {/* Table header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", padding: "5px 16px", borderBottom: "0.5px solid var(--b1)", background: "var(--bg-0)", flexShrink: 0 }}>
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
                style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", padding: "8px 16px", borderBottom: "0.5px solid var(--b0)", cursor: "pointer", alignItems: "center", background: "transparent" }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <IcoTable size={12} />
                  <span style={{ fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name}</span>
                </div>
                <span style={{ fontSize: 11, color: "var(--t4)", textAlign: "right" }}>{fmtRows(t.row_count)}</span>
                {onAsk && (
                  <button
                    onClick={e => { e.stopPropagation(); onAsk(t.name, sel.connId); }}
                    style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid var(--b1)", justifySelf: "end" as const }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--blue4)"; (e.currentTarget as HTMLElement).style.background = "var(--blue1)"; }}
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
            ...(sel.connId !== "samples" ? [{ label: "Explorer", value: <ExplorationBadge connectionId={sel.connId} /> }] : []),
          ]}
        />
      </div>
      )}
    </div>
  );
}

// ── Right: CATALOG detail ─────────────────────────────────────────────────────

type CatalogTab = "schemas";

function CatalogDetailPanel({ sel, onSelectSchema, conn, onTest, onDelete, testing, testResult }: {
  sel:            Extract<Sel, { level: "catalog" }>;
  onSelectSchema: (schema: CatalogSchemaInfo) => void;
  conn?:          Connection;
  onTest?:        (id: string) => void;
  onDelete?:      (id: string) => void;
  testing?:       boolean;
  testResult?:    boolean;
}) {
  const [filter, setFilter] = useState("");
  const [tab, setTab]       = useState<"overview" | "knowledge" | "volumes" | "permissions">("overview");
  const [confirmDel, setConfirmDel] = useState(false);
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
        meta={`${entry.schemas.length} schema${entry.schemas.length !== 1 ? "s" : ""}  ·  ${totalTables} table${totalTables !== 1 ? "s" : ""}`}
      />

      <TabBar
        tabs={[
          { id: "overview", label: `Overview  ${entry.schemas.length}` },
          { id: "volumes", label: "Volumes" },
          { id: "permissions", label: "Permissions" },
          ...(entry.builtin ? [] : [{ id: "knowledge", label: "Knowledge" }]),
        ]}
        active={effTab}
        onChange={id => setTab(id as "overview" | "knowledge" | "volumes" | "permissions")}
      />

      {effTab === "volumes" ? (
        <VolumesPanel catalogId={entry.conn_id} />
      ) : effTab === "permissions" ? (
        <PermissionsPanel catalogId={entry.conn_id} />
      ) : effTab === "knowledge" ? (
        <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>
          <p style={{ fontSize: 12, color: "var(--t2)", marginBottom: 16, maxWidth: 560, lineHeight: 1.5 }}>
            Upload documents (PDFs, reports, runbooks) to give Aughor institutional knowledge
            about <span style={{ color: "var(--t1)", fontWeight: 500 }}>{entry.name}</span>. This
            grounds Quick and Agentic answers in your team&rsquo;s own context.
          </p>
          <DocumentUploader />
        </div>
      ) : (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Main: schema list (Overview tab) */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }}>
          {/* Filter row */}
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, background: "var(--bg-0)" }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter schemas…" />
          </div>

          {/* Schema header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px", padding: "5px 16px", borderBottom: "0.5px solid var(--b1)", background: "var(--bg-0)", flexShrink: 0 }}>
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
                  style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px", padding: "10px 16px", borderBottom: "0.5px solid var(--b0)", cursor: "pointer", alignItems: "center", background: "transparent" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bg-1)"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                    <IcoSchema color="var(--blue3)" size={14} />
                    <div>
                      <p style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>{sc.name}</p>
                      <p style={{ fontSize: 11, color: "var(--t4)", marginTop: 1 }}>{schRows > 0 ? fmtRows(schRows) + " rows" : ""}</p>
                    </div>
                  </div>
                  <span style={{ fontSize: 11, color: "var(--t4)", textAlign: "right" }}>{sc.tables.length}</span>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ color: "var(--t4)", justifySelf: "end" as const }}>
                    <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer: briefings opt-in (all real connections) + connector actions + management */}
        {entry.conn_id !== "samples" && (
          <div style={{ flexShrink: 0, background: "var(--bg-0)" }}>
          <BriefingsToggle connId={entry.conn_id} />
          {!entry.builtin && (
          <>
          <ConnectorActions connId={entry.conn_id} connType={entry.conn_type} />

          {/* Connection management actions (test / remove) */}
          {conn && (
            <div style={{ padding: "12px 16px", borderTop: "0.5px solid var(--b1)", display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
              <button onClick={() => onTest?.(entry.conn_id)} disabled={testing}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: testing ? "not-allowed" : "pointer",
                  background: "var(--bg-1)", border: `0.5px solid ${testResult === true ? "var(--grn2)" : testResult === false ? "var(--red2)" : "var(--b2)"}`,
                  color: testResult === true ? "var(--grn4)" : testResult === false ? "var(--red4)" : "var(--t2)", opacity: testing ? 0.6 : 1 }}>
                {testing ? "Testing…" : testResult === true ? "✓ Connection OK" : testResult === false ? "✗ Failed" : "Test connection"}
              </button>
              <button onClick={() => setConfirmDel(true)}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                  background: "transparent", border: "0.5px solid var(--red2)", color: "var(--red4)" }}>
                Remove connection
              </button>

              {/* Confirmation popup */}
              {confirmDel && (
                <>
                  <div onClick={() => setConfirmDel(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", zIndex: 300 }} />
                  <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", zIndex: 301, width: 340,
                    background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: 8, padding: 20, boxShadow: "0 24px 64px rgba(0,0,0,.6)" }}>
                    <p style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 8 }}>Remove connection?</p>
                    <p style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5, marginBottom: 18 }}>
                      <span style={{ color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{entry.name}</span> will be disconnected and removed from your catalog. This cannot be undone.
                    </p>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                      <button onClick={() => setConfirmDel(false)}
                        style={{ fontSize: 12, padding: "6px 14px", borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "0.5px solid var(--b1)" }}>Cancel</button>
                      <button onClick={() => { setConfirmDel(false); onDelete?.(entry.conn_id); }}
                        style={{ fontSize: 12, padding: "6px 14px", borderRadius: 4, cursor: "pointer", background: "var(--red1)", color: "var(--red4)", border: "0.5px solid var(--red2)", fontWeight: 500 }}>Remove</button>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
          </>
          )}
          </div>
        )}
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
  t === "Schema"  ? <IcoSchema color="var(--blue3)" size={15} /> :
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
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ color: "var(--t4)" }}>
        <ellipse cx="24" cy="14" rx="18" ry="7" stroke="currentColor" strokeWidth="2" />
        <path d="M6 14v20c0 3.9 8.1 7 18 7s18-3.1 18-7V14" stroke="currentColor" strokeWidth="2" fill="none" />
        <path d="M6 24c0 3.9 8.1 7 18 7s18-3.1 18-7" stroke="currentColor" strokeWidth="2" opacity=".5" />
      </svg>
      <div style={{ textAlign: "center" }}>
        <p style={{ fontSize: 14, fontWeight: 500, color: "var(--t4)", marginBottom: 6 }}>Select an item to view details</p>
        <p style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.6 }}>
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
        borderLeft: `2px solid ${isSelected ? "var(--blue3)" : "transparent"}`,
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
        color: isSelected ? "var(--t1)" : "var(--t2)", fontWeight: isSelected ? 500 : 400,
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
  /** Active workspace — scopes the catalog tree to its connections' schemas. */
  workspaceId?:     string;
}

export function CatalogScreen({ connections, selectedConn, onSelect, onDeleteConn, onChatWithTable, workspaceId }: Props) {
  const { refresh: refreshSchema } = useSchema();
  const [tree, setTree]         = useState<CatalogTree | null>(null);
  const [treeLoading, setTreeL] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["section:connections", "catalog:workspace", "schema:workspace:ecommerce"]));
  const [sel, setSel]           = useState<Sel>(null);
  const [showAddData, setShowAddData] = useState(false);
  const [search, setSearch]     = useState("");
  const [testing, setTesting]   = useState<string | null>(null);
  const [testRes, setTestRes]   = useState<Record<string, boolean>>({});
  const q = search.toLowerCase();
  const selConn = connections.find(c => c.id === selectedConn);

  const loadTree = () => {
    setTreeL(true);
    getCatalogTree(workspaceId)
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

  useEffect(() => { loadTree(); }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (key: string) => setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const isOpen = (key: string) => expanded.has(key);

  const handleDelete = (id: string) => {
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
            <button onClick={() => setShowAddData(true)}
              style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid var(--b1)" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--t2)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t4)"; }}
            >
              <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 1v10M1 6h10" /></svg>
              Add
            </button>
          )}
        </div>
      );

      if (section.entries.length === 0 && section.id === "connections") {
        nodes.push(<p key="empty" style={{ fontSize: 11, color: "var(--t4)", padding: "6px 12px 10px" }}>No connections yet.</p>);
      }

      section.entries.forEach(entry => {
        const catalogKey = `catalog:${entry.conn_id}`;
        const catOpen    = isOpen(catalogKey);
        const isSamples  = entry.conn_id === "samples";
        const catMatch   = matches(entry.name) || entry.schemas.some(sc => matches(sc.name) || sc.tables.some(t => matches(t.name)));
        if (!catMatch) return;

        void isSamples;
        nodes.push(
          <div key={catalogKey} style={{ position: "relative" }}>
            <TreeRow
              depth={0}
              icon={<IcoCatalog color="var(--t2)" />}
              label={entry.name}
              count={entry.schemas.reduce((s, sc) => s + sc.tables.length, 0) || undefined}
              isOpen={catOpen}
              isSelected={sel?.level === "catalog" && sel.connId === entry.conn_id}
              hasChildren={entry.schemas.length > 0}
              onClick={() => { setSel({ level: "catalog", connId: entry.conn_id, entry }); onSelect(entry.conn_id); toggle(catalogKey); }}
              onToggle={() => toggle(catalogKey)}
            />
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
              icon={<IcoSchema color="var(--blue3)" />}
              label={schema.name}
              count={schema.tables.length}
              isOpen={schOpen}
              isSelected={sel?.level === "schema" && sel.connId === entry.conn_id && sel.schemaName === schema.name}
              hasChildren={schema.tables.length > 0}
              onClick={() => { setSel({ level: "schema", connId: entry.conn_id, schemaName: schema.name, entry: schema }); toggle(schemaKey); }}
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
    if (sel.level === "table") return (
      <TableDetailPanel sel={sel} onAsk={onChatWithTable}
        onRemoved={() => { setSel(null); loadTree(); refreshSchema(); }}
      />
    );
    if (sel.level === "schema") return (
      <SchemaDetailPanel sel={sel}
        connName={connections.find(c => c.id === sel.connId)?.name}
        onSelectTable={t => setSel({ level: "table", connId: sel.connId, schemaName: sel.schemaName, table: t })}
        onAsk={onChatWithTable}
        onRemoved={() => { setSel(null); loadTree(); refreshSchema(); }}
      />
    );
    if (sel.level === "catalog") return (
      <CatalogDetailPanel sel={sel}
        conn={connections.find(c => c.id === sel.connId)}
        onTest={handleTest}
        onDelete={handleDelete}
        testing={testing === sel.connId}
        testResult={testRes[sel.connId]}
        onSelectSchema={sc => {
          setSel({ level: "schema", connId: sel.connId, schemaName: sc.name, entry: sc });
          setExpanded(p => { const n = new Set(p); n.add(`schema:${sel.connId}:${sc.name}`); return n; });
        }}
      />
    );
    return <EmptyDetail />;
  };

  if (showAddData) {
    return (
      <AddDataPanel
        onClose={() => setShowAddData(false)}
        onAdded={() => { loadTree(); refreshSchema(); }}
      />
    );
  }

  return (
    <div style={{ position: "relative", display: "flex", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>
      <ResizableSplit storageKey="catalog" initial={340} min={240} max={560} style={{ flex: 1, height: "100%" }}
        left={
      /* ── Left: Tree navigator ── */
      <div style={{ borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-1)", height: "100%", width: "100%" }}>
        {/* Top bar */}
        <div style={{ display: "flex", alignItems: "center", padding: "10px 12px 8px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, gap: 8 }}>
          <button onClick={() => setSel(null)} title="Catalog home"
            style={{ fontSize: 12, fontWeight: 600, color: sel ? "var(--t3)" : "var(--t1)", textTransform: "uppercase", letterSpacing: "0.06em", flex: 1, textAlign: "left", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: "inherit" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t1)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = sel ? "var(--t3)" : "var(--t1)"}
          >Catalog</button>
          <button onClick={() => setShowAddData(true)} title="Add data"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "var(--blue1)", color: "var(--blue5)", border: "0.5px solid var(--blue2)", padding: 0 }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--blue2)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "var(--blue1)"}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 1v10M1 6h10" /></svg>
          </button>
          <button onClick={() => { loadTree(); refreshSchema(); }} title="Refresh schema"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t4)", border: "0.5px solid var(--b1)", padding: 0 }}
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
        <div style={{ padding: "8px 10px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, position: "relative" }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
            style={{ position: "absolute", left: 18, top: "50%", transform: "translateY(-50%)", color: "var(--t4)", pointerEvents: "none" }}>
            <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
          </svg>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search catalog…"
            style={{ width: "100%", fontSize: 11, padding: "4px 8px 4px 24px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid var(--b1)", color: "var(--t2)", outline: "none" }} />
        </div>

        {/* Tree body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 0 12px" }}>
          {treeLoading && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 24, gap: 8 }}>
              <div style={{ width: 14, height: 14, border: "2px solid var(--b2)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
              <span style={{ fontSize: 11, color: "var(--t4)" }}>Loading catalog…</span>
            </div>
          )}
          {!treeLoading && renderTree()}
        </div>
      </div>
        }
        right={
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0, height: "100%" }}>
        {renderDetail()}
      </div>
        }
      />
    </div>
  );
}
