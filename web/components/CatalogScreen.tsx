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

import { useEffect, useRef, useState } from "react";
import {
  getCatalogTree, getConnections, addConnection, deleteConnection,
  testConnection, sampleTable, getSchemaRich,
  type CatalogTree, type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo,
  type Connection, type SchemaTable, type SchemaColumn, type TableSample,
} from "@/lib/api";
import { ExplorationBadge } from "@/components/ExplorationBadge";

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
  return "#9a9ba4";
}

const CONN_TAG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  duckdb:   { label: "DuckDB",   color: "#fbbf24", bg: "#1e1a0e", border: "#3a2e0a" },
  postgres: { label: "Postgres", color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
};
const connMeta = (t: string) => CONN_TAG[t] ?? { label: t, color: "#9a9ba4", bg: "#1a1a22", border: "#2a2a35" };

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
    <div style={{ padding: "16px 20px 12px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "#11171d" }}>
      {breadcrumb && (
        <p style={{ fontSize: 10, color: "#3e3f4a", marginBottom: 6 }}>
          {breadcrumb}
        </p>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "#6a6b75", display: "flex", alignItems: "center" }}>{icon}</span>
        <span style={{ fontSize: 16, fontWeight: 600, color: "#e8e6e1", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {name}
        </span>
        {tag}
      </div>
      {meta && <p style={{ fontSize: 10, color: "#4a4b57", marginTop: 4 }}>{meta}</p>}
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
    <div style={{ display: "flex", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, padding: "0 8px", background: "#11171d" }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            fontSize: 12, padding: "8px 12px", cursor: "pointer", border: "none",
            background: "transparent", fontFamily: "inherit",
            color: active === t.id ? "#e8e6e1" : "#4a4b57",
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
      padding: "16px 16px", overflowY: "auto", background: "#11171d",
    }}>
      <p style={{ fontSize: 11, fontWeight: 600, color: "#6a6b75", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.07em" }}>
        {title}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rows.map(r => (
          <div key={String(r.label)}>
            <p style={{ fontSize: 10, color: "#3e3f4a", marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.06em" }}>{r.label}</p>
            <div style={{ fontSize: 11, color: "#9a9ba4" }}>{r.value}</div>
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
        style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "#3e3f4a", pointerEvents: "none" }}>
        <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
      </svg>
      <input
        value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        style={{ fontSize: 11, padding: "5px 8px 5px 26px", borderRadius: 4, background: "#111115", border: "0.5px solid #1e1f24", color: "#8a8b94", outline: "none", width: 220 }}
      />
    </div>
  );
}

// ── Icons ─────────────────────────────────────────────────────────────────────

const IcoSection = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.3" opacity=".5" />
    <circle cx="8" cy="8" r="2.5" fill="currentColor" opacity=".4" />
  </svg>
);

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
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: active ? "#5a9af7" : "#4a4b57" }}>
    <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".8" />
    <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".5" />
    <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".3" />
  </svg>
);

const Chevron = ({ open }: { open: boolean }) => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
    style={{ flexShrink: 0, transition: "transform .15s", transform: open ? "rotate(90deg)" : "rotate(0deg)", color: "#3e3f4a" }}>
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

  const S: React.CSSProperties = { width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4, background: "#111115", border: "0.5px solid #2a2b35", color: "#c8c7c3", outline: "none", fontFamily: "inherit" };
  const L: React.CSSProperties = { fontSize: 10, color: "#4a4b57", marginBottom: 3, display: "block" };

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoad(true);
    try { await addConnection(name, type, dsn, schema || undefined); onSave(); }
    catch (ex: unknown) { setErr((ex as Error).message); }
    finally { setLoad(false); }
  };

  return (
    <form onSubmit={handle} style={{ padding: "10px 12px", background: "#11171d", borderBottom: "0.5px solid #1e1f24", display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ fontSize: 11, fontWeight: 500, color: "#9a9ba4" }}>New connection</p>
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
        <label style={L}>Schema <span style={{ color: "#2e2f37" }}>(optional)</span></label>
        <input style={{ ...S, fontFamily: "var(--font-mono)" }} placeholder={type === "postgres" ? "public" : "main"} value={schema} onChange={e => setSchema(e.target.value)} />
      </div>
      {err && <p style={{ fontSize: 10, color: "#f87171" }}>{err}</p>}
      <div style={{ display: "flex", gap: 6 }}>
        <button type="submit" disabled={loading} style={{ flex: 1, fontSize: 11, padding: "5px 0", borderRadius: 4, cursor: "pointer", background: "#1a2030", color: "#7ba8f7", border: "0.5px solid #2a3050", opacity: loading ? .5 : 1 }}>
          {loading ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} style={{ fontSize: 11, padding: "5px 10px", borderRadius: 4, cursor: "pointer", background: "transparent", color: "#4a4b57", border: "0.5px solid #1e1f24" }}>Cancel</button>
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
      <span style={{ fontSize: 10, color: "#3e3f4a" }}>Loading sample data…</span>
    </div>
  );
  if (error) return <div style={{ padding: 24, fontSize: 11, color: "#f87171", textAlign: "center" }}>{error}</div>;
  if (!data || data.rows.length === 0) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 11, color: "#3e3f4a" }}>No rows returned.</span>
    </div>
  );

  const MAX_CELL = 40;
  const clamp = (v: string | null) => {
    if (v === null) return <span style={{ color: "#2e2f37", fontStyle: "italic", fontSize: 10 }}>null</span>;
    return v.length > MAX_CELL ? v.slice(0, MAX_CELL) + "…" : v;
  };

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <table style={{ borderCollapse: "collapse", minWidth: "100%", fontSize: 11, fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr style={{ background: "#11171d", position: "sticky", top: 0, zIndex: 1 }}>
            {data.columns.map(col => (
              <th key={col} style={{ padding: "6px 12px", textAlign: "left", whiteSpace: "nowrap", borderBottom: "0.5px solid #1e1f24", borderRight: "0.5px solid #111115", fontSize: 10, color: "#5a5b62", fontWeight: 600, letterSpacing: "0.04em" }}>
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
                <td key={ci} style={{ padding: "5px 12px", color: cell === null ? "#2e2f37" : "#9a9ba4", whiteSpace: "nowrap", borderRight: "0.5px solid #111115" }}>
                  {clamp(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: "5px 12px", borderTop: "0.5px solid #1e1f24", fontSize: 10, color: "#3e3f4a", background: "#11171d" }}>
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
            <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "#11171d" }}>
              <FilterBox value={colFilter} onChange={setColFilter} placeholder="Filter columns…" />
            </div>

            {/* Column header */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#11171d", flexShrink: 0 }}>
              {["Column", "Type", ""].map(h => (
                <span key={h} style={{ fontSize: 10, color: "#3e3f4a", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600 }}>{h}</span>
              ))}
            </div>

            {/* Column rows */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {loading && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 32, gap: 8 }}>
                  <div style={{ width: 14, height: 14, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
                  <span style={{ fontSize: 10, color: "#3e3f4a" }}>Loading columns…</span>
                </div>
              )}
              {!loading && filteredCols.length === 0 && (
                <p style={{ padding: "20px 16px", fontSize: 11, color: "#3e3f4a" }}>
                  {q ? "No columns match." : "Column details unavailable."}
                </p>
              )}
              {!loading && filteredCols.map((col, i) => (
                <div key={col.name}
                  style={{ display: "grid", gridTemplateColumns: "1fr 110px 40px", padding: "6px 16px", borderBottom: "0.5px solid #111115", alignItems: "center", background: "transparent" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1218"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <span style={{ width: 6, height: 6, borderRadius: 2, flexShrink: 0, background: typeColor(col.type), opacity: 0.7 }} />
                    <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "#c8c7c3", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.name}</span>
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
                  <button onClick={() => onAsk(sel.table.name, sel.connId)} style={{ fontSize: 10, padding: "4px 10px", borderRadius: 4, cursor: "pointer", background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050", width: "100%", textAlign: "left" as const }}>
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
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "#11171d", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, color: "#4a4b57" }}>First 200 rows</span>
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
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "#11171d" }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter tables…" />
          </div>

          {/* Table header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#11171d", flexShrink: 0 }}>
            {["Name", "Rows", ""].map(h => (
              <span key={h} style={{ fontSize: 10, color: "#3e3f4a", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, textAlign: h === "Rows" ? "right" as const : "left" as const }}>{h}</span>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {tables.length === 0 && (
              <p style={{ padding: "20px 16px", fontSize: 11, color: "#3e3f4a" }}>{q ? "No tables match." : "No tables found."}</p>
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
                <span style={{ fontSize: 11, color: "#4a4b57", textAlign: "right" }}>{fmtRows(t.row_count)}</span>
                {onAsk && (
                  <button
                    onClick={e => { e.stopPropagation(); onAsk(t.name, sel.connId); }}
                    style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "#3e3f4a", border: "0.5px solid #1e1f24", justifySelf: "end" as const }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#7ba8f7"; (e.currentTarget as HTMLElement).style.background = "#1a1e2e"; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#3e3f4a"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
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

function CatalogDetailPanel({ sel, onSelectSchema }: {
  sel:            Extract<Sel, { level: "catalog" }>;
  onSelectSchema: (schema: CatalogSchemaInfo) => void;
}) {
  const [filter, setFilter] = useState("");
  const { entry } = sel;
  const cm = connMeta(entry.conn_type);
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
        tabs={[{ id: "schemas", label: `Schemas  ${entry.schemas.length}` }]}
        active="schemas"
        onChange={() => {}}
      />

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main: schema list */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Filter row */}
          <div style={{ padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, background: "#11171d" }}>
            <FilterBox value={filter} onChange={setFilter} placeholder="Filter schemas…" />
          </div>

          {/* Schema header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 60px 60px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#11171d", flexShrink: 0 }}>
            {["Name", "Tables", ""].map((h, i) => (
              <span key={h + i} style={{ fontSize: 10, color: "#3e3f4a", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, textAlign: h === "Tables" ? "right" as const : "left" as const }}>{h}</span>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {schemas.length === 0 && (
              <p style={{ padding: "20px 16px", fontSize: 11, color: "#3e3f4a" }}>{q ? "No schemas match." : "No schemas found."}</p>
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
                      <p style={{ fontSize: 10, color: "#3e3f4a", marginTop: 1 }}>{schRows > 0 ? fmtRows(schRows) + " rows" : ""}</p>
                    </div>
                  </div>
                  <span style={{ fontSize: 11, color: "#4a4b57", textAlign: "right" }}>{sc.tables.length}</span>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ color: "#2e2f37", justifySelf: "end" as const }}>
                    <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </div>
              );
            })}
          </div>
        </div>

        {/* About sidebar */}
        <AboutSidebar
          title="About this catalog"
          rows={[
            { label: "Type",    value: <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 3, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}` }}>{cm.label}</span> },
            { label: "Schemas", value: String(entry.schemas.length) },
            { label: "Tables",  value: String(totalTables) },
            { label: "Total rows", value: totalRows > 0 ? fmtRows(totalRows) : "—" },
            ...(entry.builtin ? [{ label: "Source", value: "Built-in sample catalog" }] : []),
            ...(!entry.builtin ? [{ label: "Explorer", value: <ExplorationBadge connectionId={entry.conn_id} /> }] : []),
          ]}
        />
      </div>
    </div>
  );
}

// ── Right: Empty state ────────────────────────────────────────────────────────

function EmptyDetail() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 40 }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ color: "#1e1f24" }}>
        <ellipse cx="24" cy="14" rx="18" ry="7" stroke="currentColor" strokeWidth="2" />
        <path d="M6 14v20c0 3.9 8.1 7 18 7s18-3.1 18-7V14" stroke="currentColor" strokeWidth="2" fill="none" />
        <path d="M6 24c0 3.9 8.1 7 18 7s18-3.1 18-7" stroke="currentColor" strokeWidth="2" opacity=".5" />
      </svg>
      <div style={{ textAlign: "center" }}>
        <p style={{ fontSize: 14, fontWeight: 500, color: "#3e3f4a", marginBottom: 6 }}>Select an item to view details</p>
        <p style={{ fontSize: 12, color: "#2e2f37", lineHeight: 1.6 }}>
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
        display: "flex", alignItems: "center", gap: 5,
        padding: `4px 8px 4px ${8 + depth * 14}px`,
        cursor: "pointer", userSelect: "none",
        background: isSelected ? "#111820" : "transparent",
        borderLeft: `2px solid ${isSelected ? "#2D72D2" : "transparent"}`,
        transition: "background .08s", minWidth: 0,
      }}
      onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "#0f1014"; }}
      onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      {hasChildren ? (
        <span onClick={e => { e.stopPropagation(); onToggle?.(); }} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
          <Chevron open={!!isOpen} />
        </span>
      ) : <span style={{ width: 10, flexShrink: 0 }} />}

      <span style={{ color: isSelected ? "#5a9af7" : "#6a6b75", display: "flex", alignItems: "center" }}>{icon}</span>

      <span style={{
        fontSize: 12, flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        color: isSelected ? "#e8e6e1" : "#c8c7c3", fontWeight: isSelected ? 500 : 400,
      }}>
        {label}
      </span>

      {badge}

      {count != null && (
        <span style={{ fontSize: 9, color: "#3e3f4a", flexShrink: 0 }}>
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
  const q = search.toLowerCase();

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
        <div key={`sec-${section.id}`} style={{ padding: "10px 10px 4px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <IcoSection />
            <span style={{ fontSize: 10, fontWeight: 600, color: "#4a4b57", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              {section.label}
            </span>
          </div>
          {section.id === "connections" && (
            <button onClick={() => setAdding(v => !v)}
              style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "#4a4b57", border: "0.5px solid #1e1f24" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#9a9ba4"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#4a4b57"; }}
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
        nodes.push(<p key="empty" style={{ fontSize: 10, color: "#2e2f37", padding: "6px 12px 10px" }}>No connections yet.</p>);
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
              icon={<IcoCatalog color={cm.color} />}
              label={entry.name}
              badge={<span style={{ fontSize: 8, padding: "1px 4px", borderRadius: 2, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}`, flexShrink: 0 }}>{cm.label}</span>}
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
                  style={{ fontSize: 8, padding: "2px 5px", borderRadius: 2, cursor: "pointer", background: "#1a1a22", color: testRes[entry.conn_id] === true ? "#34d399" : testRes[entry.conn_id] === false ? "#f87171" : "#4a4b57", border: "0.5px solid #2a2b35" }}>
                  {testing === entry.conn_id ? "…" : testRes[entry.conn_id] === true ? "✓" : testRes[entry.conn_id] === false ? "✗" : "Test"}
                </button>
                <button onClick={e => { e.stopPropagation(); handleDelete(entry.conn_id); }}
                  style={{ fontSize: 8, padding: "2px 5px", borderRadius: 2, cursor: "pointer", background: pendingDel === entry.conn_id ? "#2a1414" : "#1a1a22", color: pendingDel === entry.conn_id ? "#f87171" : "#4a4b57", border: `0.5px solid ${pendingDel === entry.conn_id ? "#3e2020" : "#2a2b35"}` }}>
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
                onClick={() => setSel({ level: "table", connId: entry.conn_id, schemaName: schema.name, table })}
              />
            );
          });
        });
      });
    });
    return nodes;
  };

  const renderDetail = () => {
    if (!sel) return <EmptyDetail />;
    if (sel.level === "table") return <TableDetailPanel sel={sel} onAsk={onChatWithTable} />;
    if (sel.level === "schema") return (
      <SchemaDetailPanel sel={sel}
        onSelectTable={t => setSel({ level: "table", connId: sel.connId, schemaName: sel.schemaName, table: t })}
        onAsk={onChatWithTable}
      />
    );
    if (sel.level === "catalog") return (
      <CatalogDetailPanel sel={sel}
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
      <div style={{ width: 260, borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-1)", flexShrink: 0 }}>
        {/* Top bar */}
        <div style={{ display: "flex", alignItems: "center", padding: "10px 12px 8px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.06em", flex: 1 }}>Catalog</span>
          <button onClick={loadTree} title="Refresh"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "transparent", color: "#3e3f4a", border: "0.5px solid #1e1f24", padding: 0 }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "#9a9ba4"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "#3e3f4a"}
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
            style={{ position: "absolute", left: 18, top: "50%", transform: "translateY(-50%)", color: "#3e3f4a", pointerEvents: "none" }}>
            <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
          </svg>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search catalog…"
            style={{ width: "100%", fontSize: 11, padding: "4px 8px 4px 24px", borderRadius: 4, background: "#111115", border: "0.5px solid #1e1f24", color: "#6e6f78", outline: "none" }} />
        </div>

        {/* Tree body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 0 12px" }}>
          {treeLoading && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 24, gap: 8 }}>
              <div style={{ width: 14, height: 14, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
              <span style={{ fontSize: 10, color: "#3e3f4a" }}>Loading catalog…</span>
            </div>
          )}
          {!treeLoading && renderTree()}
        </div>
      </div>

      {/* ── Right: Detail panel ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {renderDetail()}
      </div>

    </div>
  );
}
