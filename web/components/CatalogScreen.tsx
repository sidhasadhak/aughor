"use client";

/**
 * CatalogScreen — Unity Catalog-style 4-level hierarchy
 *
 *  Section (Sample Catalog / My Connections)
 *    └── Catalog  (one per connection)
 *          └── Schema  (ecommerce / public / analytics …)
 *                └── Table
 *
 * Left panel: collapsible tree navigator
 * Right panel: detail view that adapts to selection level
 */

import { useEffect, useRef, useState } from "react";
import {
  getCatalogTree, getConnections, addConnection, deleteConnection,
  testConnection, sampleTable, getSchemaRich,
  type CatalogTree, type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo,
  type Connection, type SchemaTable, type TableSample,
} from "@/lib/api";
import { ExplorationBadge } from "@/components/ExplorationBadge";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRows(n: number | string | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (isNaN(num)) return "—";
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000)     return Math.round(num / 1_000) + "K";
  return String(num);
}

function typeColor(t: string): string {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT"))                 return "#7ba8f7";
  if (u.includes("BIGINT") || u.includes("INT"))                   return "#c084fc";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "#4ade80";
  if (u.includes("DATE") || u.includes("TIME"))                    return "#f97316";
  if (u.includes("BOOL"))                                          return "#4ade80";
  return "#9a9ba4";
}

const CONN_TAG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  duckdb:   { label: "DuckDB",   color: "#fbbf24", bg: "#1e1a0e", border: "#3a2e0a" },
  postgres: { label: "Postgres", color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
};
const connMeta = (t: string) => CONN_TAG[t] ?? { label: t, color: "#9a9ba4", bg: "#1a1a22", border: "#2a2a35" };

// ── Selection type ────────────────────────────────────────────────────────────

type Sel =
  | { level: "table";  connId: string; schemaName: string; table: CatalogTableInfo; richTable?: SchemaTable }
  | { level: "schema"; connId: string; schemaName: string; entry: CatalogSchemaInfo }
  | { level: "catalog"; connId: string; entry: CatalogEntry }
  | null;

// ── Icons ─────────────────────────────────────────────────────────────────────

const IcoSection = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.3" opacity=".5" />
    <circle cx="8" cy="8" r="2.5" fill="currentColor" opacity=".4" />
  </svg>
);

const IcoCatalog = ({ color = "currentColor" }: { color?: string }) => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <ellipse cx="8" cy="5" rx="6" ry="2.5" stroke={color} strokeWidth="1.2" />
    <path d="M2 5v6c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5" stroke={color} strokeWidth="1.2" fill="none" />
    <path d="M2 8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" stroke={color} strokeWidth="1.2" opacity=".5" />
  </svg>
);

const IcoSchema = ({ color = "currentColor" }: { color?: string }) => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <path d="M2 3h5v5H2z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".6" />
    <path d="M9 3h5v5H9z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".4" />
    <path d="M5.5 10.5h5v2.5h-5z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".35" />
  </svg>
);

const IcoTable = ({ active = false }: { active?: boolean }) => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: active ? "#5a9af7" : "#4a4b57" }}>
    <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".8" />
    <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".5" />
    <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".3" />
  </svg>
);

const Chevron = ({ open }: { open: boolean }) => (
  <svg
    width="10" height="10" viewBox="0 0 10 10" fill="none"
    style={{ flexShrink: 0, transition: "transform .15s", transform: open ? "rotate(90deg)" : "rotate(0deg)", color: "#3e3f4a" }}
  >
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

  const S: React.CSSProperties = {
    width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4,
    background: "#111115", border: "0.5px solid #2a2b35",
    color: "#c8c7c3", outline: "none", fontFamily: "inherit",
  };
  const L: React.CSSProperties = { fontSize: 10, color: "#4a4b57", marginBottom: 3, display: "block" };

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoad(true);
    try { await addConnection(name, type, dsn, schema || undefined); onSave(); }
    catch (ex: unknown) { setErr((ex as Error).message); }
    finally { setLoad(false); }
  };

  return (
    <form onSubmit={handle} style={{ padding: "10px 12px", background: "#0a0b0d", borderBottom: "0.5px solid #1e1f24", display: "flex", flexDirection: "column", gap: 8 }}>
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
        <input style={{ ...S, fontFamily: "var(--font-mono)" }}
          placeholder={type === "postgres" ? "postgresql://user:pass@host/db" : "/path/to/file.duckdb"}
          value={dsn} onChange={e => setDsn(e.target.value)} required />
      </div>
      <div>
        <label style={L}>Schema <span style={{ color: "#2e2f37" }}>(optional)</span></label>
        <input style={{ ...S, fontFamily: "var(--font-mono)" }}
          placeholder={type === "postgres" ? "public" : "main"}
          value={schema} onChange={e => setSchema(e.target.value)} />
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
  const [data, setData]     = useState<TableSample | null>(null);
  const [loading, setLoad]  = useState(false);
  const [error, setErr]     = useState<string | null>(null);
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
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 8 }}>
      <div style={{ width: 16, height: 16, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
      <span style={{ fontSize: 10, color: "#3e3f4a" }}>Loading sample…</span>
    </div>
  );
  if (error) return <div style={{ padding: 16, fontSize: 11, color: "#f87171", textAlign: "center" }}>{error}</div>;
  if (!data || data.rows.length === 0) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
      <span style={{ fontSize: 11, color: "#3e3f4a" }}>No rows returned.</span>
    </div>
  );

  const MAX_CELL = 32;
  const clamp = (v: string | null) => {
    if (v === null) return <span style={{ color: "#2e2f37", fontStyle: "italic" }}>null</span>;
    return v.length > MAX_CELL ? v.slice(0, MAX_CELL) + "…" : v;
  };

  return (
    <div style={{ flex: 1, overflow: "auto", fontSize: 10, fontFamily: "var(--font-mono)" }}>
      <table style={{ borderCollapse: "collapse", minWidth: "100%", tableLayout: "auto" }}>
        <thead>
          <tr style={{ background: "#0a0b0d", position: "sticky", top: 0, zIndex: 1 }}>
            {data.columns.map(col => (
              <th key={col} style={{ padding: "5px 10px", textAlign: "left", whiteSpace: "nowrap", borderBottom: "0.5px solid #1e1f24", borderRight: "0.5px solid #111115", fontSize: 9, color: "#4a4b57", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{col}</th>
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
                <td key={ci} style={{ padding: "4px 10px", color: cell === null ? "#2e2f37" : "#9a9ba4", whiteSpace: "nowrap", borderRight: "0.5px solid #111115" }}>
                  {clamp(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: "5px 10px", borderTop: "0.5px solid #1e1f24", fontSize: 9, color: "#3e3f4a" }}>
        {data.rows.length} row{data.rows.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

// ── Right: Table detail ───────────────────────────────────────────────────────

type DetailTab = "columns" | "sample";

function TableDetailPanel({ sel, onAsk }: {
  sel: Extract<Sel, { level: "table" }>;
  onAsk?: (table: string, connId: string) => void;
}) {
  const [tab, setTab]             = useState<DetailTab>("columns");
  const [richTable, setRich]      = useState<SchemaTable | null>(null);
  const [loadingRich, setLoadR]   = useState(false);

  // When switching to a new table, reset tab and re-fetch column detail if not cached on sel
  useEffect(() => {
    setTab("columns");
    if (sel.richTable) { setRich(sel.richTable); return; }
    // Fetch rich schema to get column details
    setRich(null); setLoadR(true);
    getSchemaRich(sel.connId)
      .then(s => {
        const found = s.tables.find(t => t.name === sel.table.name);
        setRich(found ?? null);
      })
      .catch(() => setRich(null))
      .finally(() => setLoadR(false));
  }, [sel.connId, sel.schemaName, sel.table.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const TAB = (active: boolean): React.CSSProperties => ({
    fontSize: 11, padding: "5px 12px", cursor: "pointer", border: "none",
    background: "transparent", fontFamily: "inherit",
    color: active ? "#e8e6e1" : "#4a4b57",
    borderBottom: `1.5px solid ${active ? "#3d6bff" : "transparent"}`,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "14px 16px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
          <IcoTable active />
          <span style={{ fontSize: 13, fontWeight: 500, color: "#e8e6e1", fontFamily: "var(--font-mono)" }}>{sel.table.name}</span>
        </div>
        <p style={{ fontSize: 10, color: "#3e3f4a", fontFamily: "var(--font-mono)" }}>
          {sel.schemaName} · {fmtRows(sel.table.row_count)} rows
        </p>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, paddingLeft: 4 }}>
        <button style={TAB(tab === "columns")} onClick={() => setTab("columns")}>Columns</button>
        <button style={TAB(tab === "sample")}  onClick={() => setTab("sample")}>Sample</button>
      </div>

      {/* Tab body */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {tab === "columns" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            {loadingRich && (
              <div style={{ padding: 24, display: "flex", justifyContent: "center" }}>
                <div style={{ width: 16, height: 16, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
              </div>
            )}
            {!loadingRich && !richTable && (
              <p style={{ padding: "12px 16px", fontSize: 11, color: "#3e3f4a" }}>Column details unavailable.</p>
            )}
            {!loadingRich && richTable && (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 28px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#0a0b0d", position: "sticky", top: 0, zIndex: 1 }}>
                  {["Column", "Type", ""].map(h => <span key={h} style={{ fontSize: 9, color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em" }}>{h}</span>)}
                </div>
                {richTable.columns.map(col => (
                  <div key={col.name}
                    style={{ display: "grid", gridTemplateColumns: "1fr 90px 28px", padding: "5px 16px", borderBottom: "0.5px solid #111115", alignItems: "center" }}
                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
                  >
                    <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#9a9ba4", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.name}</span>
                    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: typeColor(col.type) }}>{col.type}</span>
                    <span style={{ fontSize: 9, color: col.is_fk ? "#3d6bff" : "#2e2f37" }}>{col.is_fk ? "FK" : "—"}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
        {tab === "sample" && (
          <SampleGrid connId={sel.connId} tableName={sel.table.name} schemaName={sel.schemaName} />
        )}
      </div>

      {onAsk && (
        <div style={{ padding: "10px 16px", borderTop: "0.5px solid #1e1f24", flexShrink: 0 }}>
          <button onClick={() => onAsk(sel.table.name, sel.connId)} style={{ width: "100%", fontSize: 11, padding: "6px 0", borderRadius: 5, cursor: "pointer", background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050", fontWeight: 500 }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#1e2640"; (e.currentTarget as HTMLElement).style.borderColor = "#3d6bff"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#1a1e2e"; (e.currentTarget as HTMLElement).style.borderColor = "#2a3050"; }}
          >
            Ask about this table →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Right: Schema detail ──────────────────────────────────────────────────────

function SchemaDetailPanel({ sel, onSelectTable, onAsk }: {
  sel: Extract<Sel, { level: "schema" }>;
  onSelectTable: (table: CatalogTableInfo) => void;
  onAsk?: (table: string, connId: string) => void;
}) {
  const { entry } = sel;
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
          <IcoSchema color="#5a7fa8" />
          <span style={{ fontSize: 13, fontWeight: 500, color: "#e8e6e1", fontFamily: "var(--font-mono)" }}>{entry.name}</span>
        </div>
        <p style={{ fontSize: 10, color: "#3e3f4a" }}>{entry.tables.length} table{entry.tables.length !== 1 ? "s" : ""}</p>
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Header row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#0a0b0d", position: "sticky", top: 0 }}>
          <span style={{ fontSize: 9, color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em" }}>Table</span>
          <span style={{ fontSize: 9, color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em", textAlign: "right" }}>Rows</span>
        </div>
        {entry.tables.map(t => (
          <div key={t.name}
            onClick={() => onSelectTable(t)}
            style={{ display: "grid", gridTemplateColumns: "1fr 80px", padding: "7px 16px", borderBottom: "0.5px solid #111115", cursor: "pointer", alignItems: "center" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
              <IcoTable />
              <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#c8c7c3", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}>
              <span style={{ fontSize: 10, color: "#4a4b57", fontFamily: "var(--font-mono)" }}>{fmtRows(t.row_count)}</span>
              {onAsk && (
                <button
                  onClick={e => { e.stopPropagation(); onAsk(t.name, sel.connId); }}
                  style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "#3e3f4a", border: "0.5px solid #1e1f24" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#7ba8f7"; (e.currentTarget as HTMLElement).style.background = "#1a1e2e"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#3e3f4a"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >Ask →</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Right: Catalog detail ─────────────────────────────────────────────────────

function CatalogDetailPanel({ sel, onSelectSchema }: {
  sel: Extract<Sel, { level: "catalog" }>;
  onSelectSchema: (schema: CatalogSchemaInfo) => void;
}) {
  const { entry } = sel;
  const cm = connMeta(entry.conn_type);
  const totalTables = entry.schemas.reduce((s, sc) => s + sc.tables.length, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
          <IcoCatalog color={cm.color} />
          <span style={{ fontSize: 14, fontWeight: 500, color: "#e8e6e1" }}>{entry.name}</span>
          {entry.builtin && (
            <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: "#1a1a22", color: "#5a5b62", border: "0.5px solid #2a2a35", marginLeft: 2 }}>built-in</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 3, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}` }}>{cm.label}</span>
          <span style={{ fontSize: 10, color: "#3e3f4a" }}>{entry.schemas.length} schema{entry.schemas.length !== 1 ? "s" : ""}</span>
          <span style={{ fontSize: 10, color: "#3e3f4a" }}>{totalTables} table{totalTables !== 1 ? "s" : ""}</span>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {entry.schemas.map(sc => (
          <div key={sc.name}
            onClick={() => onSelectSchema(sc)}
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 16px", borderBottom: "0.5px solid #111115", cursor: "pointer" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
          >
            <IcoSchema color="#5a7fa8" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: 12, fontFamily: "var(--font-mono)", fontWeight: 500, color: "#c8c7c3" }}>{sc.name}</p>
              <p style={{ fontSize: 10, color: "#3e3f4a", marginTop: 1 }}>{sc.tables.length} tables</p>
            </div>
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ color: "#2e2f37" }}>
              <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
        ))}
      </div>

      {entry.conn_id !== "samples" && (
        <div style={{ padding: "10px 16px", borderTop: "0.5px solid #1e1f24", flexShrink: 0 }}>
          <ExplorationBadge connectionId={entry.conn_id} />
        </div>
      )}
    </div>
  );
}

// ── Right: Empty state ────────────────────────────────────────────────────────

function EmptyDetail() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, padding: 32 }}>
      <IcoCatalog color="#2e2f37" />
      <p style={{ fontSize: 12, color: "#3e3f4a", textAlign: "center", lineHeight: 1.6 }}>
        Select a catalog, schema, or table<br />to see details
      </p>
    </div>
  );
}

// ── Tree node ─────────────────────────────────────────────────────────────────

function TreeRow({
  depth, icon, label, badge, count, isOpen, isSelected, hasChildren, onClick, onToggle, dimmed,
}: {
  depth: number;
  icon: React.ReactNode;
  label: string;
  badge?: React.ReactNode;
  count?: number;
  isOpen?: boolean;
  isSelected?: boolean;
  hasChildren?: boolean;
  onClick?: () => void;
  onToggle?: () => void;
  dimmed?: boolean;
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
        transition: "background .08s",
        minWidth: 0,
      }}
      onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "#0f1014"; }}
      onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      {/* Toggle chevron */}
      {hasChildren ? (
        <span
          onClick={e => { e.stopPropagation(); onToggle?.(); }}
          style={{ display: "flex", alignItems: "center", flexShrink: 0 }}
        >
          <Chevron open={!!isOpen} />
        </span>
      ) : (
        <span style={{ width: 10, flexShrink: 0 }} />
      )}

      {/* Icon */}
      <span style={{ color: dimmed ? "#2e2f37" : isSelected ? "#5a9af7" : "#6a6b75", display: "flex", alignItems: "center" }}>
        {icon}
      </span>

      {/* Label */}
      <span style={{
        fontSize: 12, fontFamily: "var(--font-mono)", flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        color: dimmed ? "#3e3f4a" : isSelected ? "#e8e6e1" : "#c8c7c3",
        fontWeight: isSelected ? 500 : 400,
      }}>
        {label}
      </span>

      {/* Badge */}
      {badge}

      {/* Count chip */}
      {count != null && (
        <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "#3e3f4a", flexShrink: 0 }}>
          {count}
        </span>
      )}
    </div>
  );
}

// ── Tree search ───────────────────────────────────────────────────────────────

function TreeSearch({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ padding: "8px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, position: "relative" }}>
      <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
        style={{ position: "absolute", left: 18, top: "50%", transform: "translateY(-50%)", color: "#3e3f4a", pointerEvents: "none" }}>
        <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
      </svg>
      <input
        value={value} onChange={e => onChange(e.target.value)}
        placeholder="Search catalog…"
        style={{ width: "100%", fontSize: 11, padding: "4px 8px 4px 24px", borderRadius: 4, background: "#111115", border: "0.5px solid #1e1f24", color: "#6e6f78", outline: "none" }}
      />
    </div>
  );
}

// ── Main CatalogScreen ────────────────────────────────────────────────────────

interface Props {
  connections:       Connection[];
  selectedConn:      string;
  onSelect:          (id: string) => void;
  onDeleteConn:      (conn: Connection) => void;
  onChatWithTable?:  (table: string, connId: string) => void;
}

export function CatalogScreen({ connections, selectedConn, onSelect, onDeleteConn, onChatWithTable }: Props) {
  // ── Tree data ─────────────────────────────────────────────────────────────
  const [tree, setTree]           = useState<CatalogTree | null>(null);
  const [treeLoading, setTreeLoad] = useState(true);

  // ── Expand state: Set of "section:{id}" | "catalog:{connId}" | "schema:{connId}:{name}" ──
  const [expanded, setExpanded]   = useState<Set<string>>(new Set(["section:samples", "catalog:samples"]));

  // ── Selection ─────────────────────────────────────────────────────────────
  const [sel, setSel]             = useState<Sel>(null);

  // ── Add connection form ───────────────────────────────────────────────────
  const [adding, setAdding]       = useState(false);

  // ── Search ────────────────────────────────────────────────────────────────
  const [search, setSearch]       = useState("");
  const q = search.toLowerCase();

  // ── Hover / pending delete ────────────────────────────────────────────────
  const [hovConn, setHovConn]     = useState<string | null>(null);
  const [pendingDel, setPending]  = useState<string | null>(null);
  const [testing, setTesting]     = useState<string | null>(null);
  const [testRes, setTestRes]     = useState<Record<string, boolean>>({});

  // ── Load tree ─────────────────────────────────────────────────────────────
  const loadTree = () => {
    setTreeLoad(true);
    getCatalogTree()
      .then(t => {
        setTree(t);
        // Auto-expand the first user connection's schema if any
        const userSection = t.sections.find(s => s.id === "connections");
        if (userSection && userSection.entries.length > 0) {
          const first = userSection.entries[0];
          setExpanded(prev => {
            const next = new Set(prev);
            next.add(`catalog:${first.conn_id}`);
            if (first.schemas.length === 1) next.add(`schema:${first.conn_id}:${first.schemas[0].name}`);
            return next;
          });
        }
      })
      .catch(err => console.error("[CatalogScreen] failed to load tree:", err))
      .finally(() => setTreeLoad(false));
  };

  useEffect(() => { loadTree(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Toggle helpers ────────────────────────────────────────────────────────
  const toggle = (key: string) =>
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  const isOpen = (key: string) => expanded.has(key);

  // ── Delete connection ──────────────────────────────────────────────────────
  const handleDelete = (id: string) => {
    if (pendingDel !== id) {
      setPending(id);
      setTimeout(() => setPending(prev => (prev === id ? null : prev)), 3000);
      return;
    }
    setPending(null);
    const conn = connections.find(c => c.id === id);
    if (conn) onDeleteConn(conn);
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const r = await testConnection(id);
      setTestRes(prev => ({ ...prev, [id]: r.ok }));
    } catch { setTestRes(prev => ({ ...prev, [id]: false })); }
    finally { setTesting(null); }
  };

  // ── Table selection from schema detail panel ───────────────────────────────
  const handleSelectTableFromSchema = (table: CatalogTableInfo) => {
    if (sel?.level !== "schema") return;
    setSel({ level: "table", connId: sel.connId, schemaName: sel.schemaName, table });
  };

  // ── Schema selection from catalog detail panel ─────────────────────────────
  const handleSelectSchemaFromCatalog = (schemaInfo: CatalogSchemaInfo) => {
    if (sel?.level !== "catalog") return;
    setSel({ level: "schema", connId: sel.connId, schemaName: schemaInfo.name, entry: schemaInfo });
    setExpanded(prev => { const n = new Set(prev); n.add(`schema:${sel.connId}:${schemaInfo.name}`); return n; });
  };

  // ── Filter tree by search ──────────────────────────────────────────────────
  const matches = (s: string) => !q || s.toLowerCase().includes(q);

  // ── Render tree ───────────────────────────────────────────────────────────
  const renderTree = () => {
    if (!tree) return null;

    const nodes: React.ReactNode[] = [];

    tree.sections.forEach(section => {
      // ── Section header ────────────────────────────────────────────────────
      nodes.push(
        <div key={`sec-${section.id}`} style={{ padding: "10px 10px 4px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <IcoSection />
            <span style={{ fontSize: 10, fontWeight: 600, color: "#4a4b57", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              {section.label}
            </span>
          </div>
          {section.id === "connections" && (
            <button
              onClick={() => setAdding(v => !v)}
              style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "#4a4b57", border: "0.5px solid #1e1f24" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#9a9ba4"; (e.currentTarget as HTMLElement).style.borderColor = "#2e2f37"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#4a4b57"; (e.currentTarget as HTMLElement).style.borderColor = "#1e1f24"; }}
            >
              <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 1v10M1 6h10" /></svg>
              Add
            </button>
          )}
        </div>
      );

      if (section.id === "connections" && adding) {
        nodes.push(
          <AddConnForm key="add-form" onSave={() => { setAdding(false); loadTree(); }} onCancel={() => setAdding(false)} />
        );
      }

      if (section.entries.length === 0 && section.id === "connections") {
        nodes.push(
          <p key="empty-conns" style={{ fontSize: 10, color: "#2e2f37", padding: "6px 12px 10px" }}>No connections yet. Add one above.</p>
        );
      }

      section.entries.forEach(entry => {
        const catalogKey = `catalog:${entry.conn_id}`;
        const catOpen    = isOpen(catalogKey);
        const cm         = connMeta(entry.conn_type);
        const isSamples  = entry.conn_id === "samples";
        const catVisible = matches(entry.name) || entry.schemas.some(sc => matches(sc.name) || sc.tables.some(t => matches(t.name)));

        if (!catVisible) return;

        // ── Catalog row ──────────────────────────────────────────────────────
        nodes.push(
          <div key={catalogKey} style={{ position: "relative" }}
            onMouseEnter={() => setHovConn(entry.conn_id)}
            onMouseLeave={() => setHovConn(null)}
          >
            <TreeRow
              depth={0}
              icon={<IcoCatalog color={cm.color} />}
              label={entry.name}
              badge={
                <span style={{ fontSize: 8, padding: "1px 4px", borderRadius: 2, background: cm.bg, color: cm.color, border: `0.5px solid ${cm.border}`, flexShrink: 0 }}>
                  {cm.label}
                </span>
              }
              count={entry.schemas.reduce((s, sc) => s + sc.tables.length, 0) || undefined}
              isOpen={catOpen}
              isSelected={sel?.level === "catalog" && sel.connId === entry.conn_id}
              hasChildren={entry.schemas.length > 0}
              onClick={() => {
                setSel({ level: "catalog", connId: entry.conn_id, entry });
                onSelect(entry.conn_id);
              }}
              onToggle={() => toggle(catalogKey)}
            />

            {/* Hover actions (user connections only) */}
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
          const schemaKey  = `schema:${entry.conn_id}:${schema.name}`;
          const schOpen    = isOpen(schemaKey);
          const schVisible = matches(entry.name) || matches(schema.name) || schema.tables.some(t => matches(t.name));
          if (!schVisible) return;

          // ── Schema row ─────────────────────────────────────────────────────
          nodes.push(
            <TreeRow
              key={schemaKey}
              depth={1}
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
            if (!matches(table.name) && !matches(entry.name) && !matches(schema.name)) return;
            const tableKey = `table:${entry.conn_id}:${schema.name}:${table.name}`;
            const isSel    = sel?.level === "table" && sel.connId === entry.conn_id && sel.schemaName === schema.name && sel.table.name === table.name;

            // ── Table row ──────────────────────────────────────────────────────
            nodes.push(
              <TreeRow
                key={tableKey}
                depth={2}
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

  // ── Right panel ───────────────────────────────────────────────────────────
  const renderDetail = () => {
    if (!sel) return <EmptyDetail />;
    if (sel.level === "table") return (
      <TableDetailPanel sel={sel} onAsk={onChatWithTable} />
    );
    if (sel.level === "schema") return (
      <SchemaDetailPanel sel={sel} onSelectTable={handleSelectTableFromSchema} onAsk={onChatWithTable} />
    );
    if (sel.level === "catalog") return (
      <CatalogDetailPanel sel={sel} onSelectSchema={handleSelectSchemaFromCatalog} />
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
          <button
            onClick={loadTree}
            title="Refresh"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "transparent", color: "#3e3f4a", border: "0.5px solid #1e1f24", padding: 0 }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#9a9ba4"; (e.currentTarget as HTMLElement).style.borderColor = "#2e2f37"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#3e3f4a"; (e.currentTarget as HTMLElement).style.borderColor = "#1e1f24"; }}
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 4.5A7 7 0 0 1 14 8" /><path d="M15 11.5A7 7 0 0 1 2 8" />
              <polyline points="1 1 1 5 5 5" /><polyline points="15 15 15 11 11 11" />
            </svg>
          </button>
        </div>

        {/* Search */}
        <TreeSearch value={search} onChange={setSearch} />

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
