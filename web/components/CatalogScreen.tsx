"use client";

import { useEffect, useRef, useState } from "react";
import {
  getConnections, getSchemaRich, addConnection, deleteConnection, testConnection, sampleTable,
  type Connection, type RichSchema, type SchemaTable, type TableSample,
} from "@/lib/api";
import { ExplorationBadge } from "@/components/ExplorationBadge";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRows(n: string | number | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000)     return (num / 1_000).toFixed(0) + "K";
  return String(num);
}

function typeColor(t: string): string {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT"))                return "#7ba8f7";
  if (u.includes("BIGINT") || u.includes("INT"))                  return "#c084fc";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "#4ade80";
  if (u.includes("DATE") || u.includes("TIME"))                   return "#f97316";
  if (u.includes("BOOL"))                                         return "#4ade80";
  return "#9a9ba4";
}

const TYPE_TAG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  duckdb:   { label: "DuckDB",   color: "#fbbf24", bg: "#1e1a0e", border: "#3a2e0a" },
  postgres: { label: "Postgres", color: "#7ba8f7", bg: "#1a1e2e", border: "#2a3050" },
};
function connTypeMeta(t: string) {
  return TYPE_TAG[t] ?? { label: t, color: "#9a9ba4", bg: "#1a1a22", border: "#2a2a35" };
}

// ── Add connection form ───────────────────────────────────────────────────────

function AddConnForm({ onSave, onCancel }: { onSave: () => void; onCancel: () => void }) {
  const [name, setName]         = useState("");
  const [type, setType]         = useState("postgres");
  const [dsn, setDsn]           = useState("");
  const [schema, setSchema]     = useState("");
  const [err, setErr]           = useState("");
  const [loading, setLoading]   = useState(false);

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoading(true);
    try {
      await addConnection(name, type, dsn, schema || undefined);
      onSave();
    } catch (ex: unknown) {
      setErr((ex as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const INPUT: React.CSSProperties = {
    width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4,
    background: "#111115", border: "0.5px solid #2a2b35",
    color: "#c8c7c3", outline: "none", fontFamily: "inherit",
  };
  const LABEL: React.CSSProperties = { fontSize: 10, color: "#4a4b57", marginBottom: 3, display: "block" };

  return (
    <form onSubmit={handle} style={{ padding: "12px 14px", borderBottom: "0.5px solid #1e1f24", background: "#0d0e11", display: "flex", flexDirection: "column", gap: 10 }}>
      <p style={{ fontSize: 11, fontWeight: 500, color: "#9a9ba4", marginBottom: 2 }}>New connection</p>
      <div><label style={LABEL}>Name</label><input style={INPUT} placeholder="My database" value={name} onChange={e => setName(e.target.value)} required /></div>
      <div>
        <label style={LABEL}>Type</label>
        <select style={{ ...INPUT, cursor: "pointer" }} value={type} onChange={e => setType(e.target.value)}>
          <option value="postgres">PostgreSQL</option>
          <option value="duckdb">DuckDB file</option>
        </select>
      </div>
      <div>
        <label style={LABEL}>{type === "postgres" ? "Connection string" : "File path"}</label>
        <input style={{ ...INPUT, fontFamily: "var(--font-mono)" }}
          placeholder={type === "postgres" ? "postgresql://user:pass@host/db" : "/path/to/file.duckdb"}
          value={dsn} onChange={e => setDsn(e.target.value)} required />
      </div>
      <div>
        <label style={LABEL}>Schema <span style={{ color: "#2e2f37" }}>(optional)</span></label>
        <input style={{ ...INPUT, fontFamily: "var(--font-mono)" }}
          placeholder={type === "postgres" ? "public" : "main"}
          value={schema} onChange={e => setSchema(e.target.value)} />
      </div>
      {err && <p style={{ fontSize: 10, color: "#f87171" }}>{err}</p>}
      <div style={{ display: "flex", gap: 6 }}>
        <button type="submit" disabled={loading} style={{
          flex: 1, fontSize: 11, padding: "5px 0", borderRadius: 4, cursor: "pointer",
          background: "#1a2030", color: "#7ba8f7", border: "0.5px solid #2a3050",
          opacity: loading ? 0.5 : 1,
        }}>
          {loading ? "Saving…" : "Save connection"}
        </button>
        <button type="button" onClick={onCancel} style={{
          fontSize: 11, padding: "5px 10px", borderRadius: 4, cursor: "pointer",
          background: "transparent", color: "#4a4b57", border: "0.5px solid #1e1f24",
        }}>Cancel</button>
      </div>
    </form>
  );
}

// ── Table detail panel ────────────────────────────────────────────────────────

type DetailTab = "columns" | "sample";

function SampleGrid({ connId, tableName }: { connId: string; tableName: string }) {
  const [data, setData]     = useState<TableSample | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const fetched = useRef(false);

  useEffect(() => {
    // reset when table changes
    setData(null); setError(null); fetched.current = false;
  }, [connId, tableName]);

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    setLoading(true);
    sampleTable(connId, tableName, 200)
      .then(d => setData(d))
      .catch(e => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [connId, tableName]);

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 8 }}>
      <div style={{ width: 18, height: 18, border: "2px solid #2a2b35", borderTopColor: "#4a6aaa", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
      <span style={{ fontSize: 10, color: "#3e3f4a" }}>Loading sample…</span>
    </div>
  );

  if (error) return (
    <div style={{ padding: "16px", fontSize: 11, color: "#f87171", textAlign: "center" }}>{error}</div>
  );

  if (!data || data.rows.length === 0) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%"}}>
      <span style={{ fontSize: 11, color: "#3e3f4a" }}>No rows returned.</span>
    </div>
  );

  // Clamp cell values for display
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
              <th key={col} style={{
                padding: "5px 10px", textAlign: "left", whiteSpace: "nowrap",
                borderBottom: "0.5px solid #1e1f24", borderRight: "0.5px solid #111115",
                fontSize: 9, color: "#4a4b57", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600,
              }}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, ri) => (
            <tr key={ri}
              style={{ borderBottom: "0.5px solid #111115" }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
            >
              {row.map((cell, ci) => (
                <td key={ci} style={{
                  padding: "4px 10px", color: cell === null ? "#2e2f37" : "#9a9ba4",
                  whiteSpace: "nowrap", borderRight: "0.5px solid #111115",
                }}>
                  {clamp(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: "6px 10px", borderTop: "0.5px solid #1e1f24", fontSize: 9, color: "#3e3f4a" }}>
        {data.rows.length} row{data.rows.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

function TableDetail({ table, connId, connName, onAsk }: {
  table:    SchemaTable;
  connId:   string;
  connName: string;
  onAsk?:   (t: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<DetailTab>("columns");

  // Reset tab when table changes
  useEffect(() => { setActiveTab("columns"); }, [table.name]);

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    fontSize: 11, padding: "5px 12px", cursor: "pointer", border: "none",
    background: "transparent", fontFamily: "inherit",
    color: active ? "#e8e6e1" : "#4a4b57",
    borderBottom: `1.5px solid ${active ? "#3d6bff" : "transparent"}`,
    transition: "color .1s",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "14px 16px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ color: "#5a5b62", flexShrink: 0 }}>
            <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".5" />
            <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".35" />
            <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".2" />
          </svg>
          <span style={{ fontSize: 13, fontWeight: 500, color: "#e8e6e1", fontFamily: "var(--font-mono)" }}>{table.name}</span>
        </div>
        <p style={{ fontSize: 10, color: "#3e3f4a", fontFamily: "var(--font-mono)" }}>{connName}</p>
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, padding: "10px 16px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0 }}>
        {[["Columns", String(table.columns.length)], ["Rows", fmtRows(table.row_count)]].map(([k, v]) => (
          <div key={k} style={{ padding: "7px 10px", background: "#111115", border: "0.5px solid #1e1f24", borderRadius: 6 }}>
            <div style={{ fontSize: 9, color: "#3e3f4a", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 3 }}>{k}</div>
            <div style={{ fontSize: 14, fontWeight: 500, color: "#c8c7c3", fontFamily: "var(--font-mono)" }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, paddingLeft: 4 }}>
        <button style={TAB_STYLE(activeTab === "columns")} onClick={() => setActiveTab("columns")}>Columns</button>
        <button style={TAB_STYLE(activeTab === "sample")}  onClick={() => setActiveTab("sample")}>Sample</button>
      </div>

      {/* Tab body */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "columns" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            {/* Column header */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 28px", padding: "5px 16px", borderBottom: "0.5px solid #1e1f24", background: "#0a0b0d", position: "sticky", top: 0, zIndex: 1 }}>
              {["Column", "Type", ""].map(h => (
                <span key={h} style={{ fontSize: 9, color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em" }}>{h}</span>
              ))}
            </div>
            {table.columns.map(col => (
              <div key={col.name}
                style={{ display: "grid", gridTemplateColumns: "1fr 90px 28px", padding: "5px 16px", borderBottom: "0.5px solid #111115", alignItems: "center" }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#0f1014"}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
              >
                <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#9a9ba4", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{col.name}</span>
                <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: typeColor(col.type) }}>{col.type}</span>
                <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: col.is_fk ? "#3d6bff" : "#2e2f37" }}>{col.is_fk ? "FK" : "—"}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === "sample" && (
          <SampleGrid connId={connId} tableName={table.name} />
        )}
      </div>

      {/* Ask button */}
      {onAsk && (
        <div style={{ padding: "10px 16px", borderTop: "0.5px solid #1e1f24", flexShrink: 0 }}>
          <button onClick={() => onAsk(table.name)} style={{
            width: "100%", fontSize: 11, padding: "6px 0", borderRadius: 5, cursor: "pointer",
            background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050",
            fontWeight: 500, transition: "all .1s",
          }}
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

// ── Table list (center panel) ─────────────────────────────────────────────────

function TableList({ schema, loading, onSelectTable, selectedTable, onAsk }: {
  schema: RichSchema | null;
  loading: boolean;
  onSelectTable: (t: SchemaTable) => void;
  selectedTable: SchemaTable | null;
  onAsk?: (t: string) => void;
}) {
  const [search, setSearch] = useState("");
  const tables = schema?.tables ?? [];
  const q = search.toLowerCase();
  const filtered = q ? tables.filter(t => t.name.toLowerCase().includes(q)) : tables;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Center header */}
      <div style={{ padding: "10px 14px 10px", borderBottom: "0.5px solid #1e1f24", flexShrink: 0, display: "flex", alignItems: "center", gap: 10 }}>
        {schema && (
          <span style={{ fontSize: 10, color: "#4a4b57" }}>
            <span style={{ color: "#9a9ba4", fontWeight: 500 }}>{tables.length}</span> tables
          </span>
        )}
        <div style={{ flex: 1 }} />
        <div style={{ position: "relative" }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
            style={{ position: "absolute", left: 7, top: "50%", transform: "translateY(-50%)", color: "#3e3f4a", pointerEvents: "none" }}>
            <circle cx="6" cy="6" r="4" /><path d="m10 10 3 3" strokeLinecap="round" />
          </svg>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter tables…"
            style={{ fontSize: 11, padding: "4px 8px 4px 24px", borderRadius: 4, background: "#111115", border: "0.5px solid #1e1f24", color: "#6e6f78", outline: "none", width: 150 }}
          />
        </div>
      </div>

      {/* Table rows */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: 12 }}>
            {[1,2,3,4,5].map(i => (
              <div key={i} style={{ height: 40, borderRadius: 6, background: "#111115", animation: "pulse 1.5s ease-in-out infinite" }} />
            ))}
          </div>
        )}

        {!loading && !schema && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 200 }}>
            <p style={{ fontSize: 11, color: "#3e3f4a" }}>Select a connection to browse tables.</p>
          </div>
        )}

        {!loading && schema && filtered.length === 0 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 120 }}>
            <p style={{ fontSize: 11, color: "#3e3f4a" }}>No tables match.</p>
          </div>
        )}

        {!loading && filtered.map(table => {
          const isSelected = selectedTable?.name === table.name;
          const fkCount = table.columns.filter(c => c.is_fk).length;
          return (
            <div
              key={table.name}
              onClick={() => onSelectTable(table)}
              style={{
                display: "flex", alignItems: "center", gap: 10, padding: "9px 14px",
                borderBottom: "0.5px solid #111115", cursor: "pointer",
                background: isSelected ? "#111820" : "transparent",
                borderLeft: `2px solid ${isSelected ? "#2D72D2" : "transparent"}`,
                transition: "background .08s",
              }}
              onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "#0f1014"; }}
              onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              {/* Table icon */}
              <div style={{ width: 26, height: 26, borderRadius: 5, background: "#161720", border: "0.5px solid #2a2b30", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ color: isSelected ? "#5a9af7" : "#4a4b57" }}>
                  <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".8" />
                  <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".5" />
                  <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".3" />
                </svg>
              </div>

              {/* Name + meta */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: 12, fontFamily: "var(--font-mono)", fontWeight: 500, color: isSelected ? "#e8e6e1" : "#c8c7c3", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {table.name}
                </p>
                <p style={{ fontSize: 10, color: "#3e3f4a", marginTop: 1 }}>
                  {table.columns.length} cols · {fmtRows(table.row_count)} rows
                  {fkCount > 0 && <span style={{ marginLeft: 6, color: "#3d6bff" }}>{fkCount} FK</span>}
                </p>
              </div>

              {/* Ask button */}
              {onAsk && (
                <button
                  onClick={e => { e.stopPropagation(); onAsk(table.name); }}
                  style={{ fontSize: 10, padding: "3px 8px", borderRadius: 3, cursor: "pointer", flexShrink: 0, background: "transparent", color: "#3e3f4a", border: "0.5px solid #1e1f24", transition: "all .1s" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#7ba8f7"; (e.currentTarget as HTMLElement).style.borderColor = "#2a3050"; (e.currentTarget as HTMLElement).style.background = "#1a1e2e"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#3e3f4a"; (e.currentTarget as HTMLElement).style.borderColor = "#1e1f24"; (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  Ask →
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main CatalogScreen ────────────────────────────────────────────────────────

interface Props {
  connections:   Connection[];
  selectedConn:  string;
  onSelect:      (id: string) => void;
  onAddConn:     () => void;
  onDeleteConn:  (conn: Connection) => void;
  onChatWithTable?: (table: string, connId: string) => void;
}

export function CatalogScreen({ connections, selectedConn, onSelect, onAddConn, onDeleteConn, onChatWithTable }: Props) {
  const [schema, setSchema]         = useState<RichSchema | null>(null);
  const [loadingSchema, setLoading] = useState(false);
  const [selectedTable, setSelectedTable] = useState<SchemaTable | null>(null);
  const [adding, setAdding]         = useState(false);
  const [hovConn, setHovConn]       = useState<string | null>(null);
  const [pendingDel, setPendingDel] = useState<string | null>(null);
  const [testing, setTesting]       = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean }>>({});

  // Own the connection list — fetch directly so we never depend on parent timing.
  // Also sync when parent passes a fresh list (e.g. after add/delete in Settings).
  const [localConns, setLocalConns] = useState<Connection[]>(connections);

  const refreshConns = () =>
    getConnections()
      .then(conns => {
        setLocalConns(conns);
        // If nothing is selected yet, auto-select the first connection
        if (!selectedConn && conns.length > 0) onSelect(conns[0].id);
      })
      .catch(err => console.error("[CatalogScreen] failed to load connections:", err));

  useEffect(() => { refreshConns(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (connections.length > 0) setLocalConns(connections); }, [connections]);

  // Load schema when selected connection changes
  useEffect(() => {
    if (!selectedConn) return;
    setLoading(true);
    setSchema(null);
    setSelectedTable(null);
    getSchemaRich(selectedConn)
      .then(s => { setSchema(s); })
      .catch(() => setSchema(null))
      .finally(() => setLoading(false));
  }, [selectedConn]);

  const handleSaveConn = async () => {
    await refreshConns();
    setAdding(false);
  };

  const handleDelete = (id: string) => {
    if (pendingDel !== id) {
      setPendingDel(id);
      setTimeout(() => setPendingDel(prev => (prev === id ? null : prev)), 3000);
      return;
    }
    setPendingDel(null);
    const conn = localConns.find(c => c.id === id);
    if (conn) onDeleteConn(conn);
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const r = await testConnection(id);
      setTestResults(prev => ({ ...prev, [id]: { ok: r.ok } }));
    } catch {
      setTestResults(prev => ({ ...prev, [id]: { ok: false } }));
    } finally {
      setTesting(null);
    }
  };

  const selectedConnObj = localConns.find(c => c.id === selectedConn);

  return (
    <div style={{ display: "flex", flexDirection: "row", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>

      {/* ── Left: Connection list ── */}
      <div style={{ width: 220, borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", flexShrink: 0, background: "var(--bg-1)" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Catalog</span>
          <button
            onClick={() => setAdding(v => !v)}
            style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, padding: "3px 8px", borderRadius: 4, cursor: "pointer", background: "var(--bg-3)", color: "var(--t2)", border: "0.5px solid var(--b2)" }}
          >
            <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 1v10M1 6h10" /></svg>
            Add
          </button>
        </div>

        {/* Add form (inline) */}
        {adding && <AddConnForm onSave={handleSaveConn} onCancel={() => setAdding(false)} />}

        {/* Connection list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "6px 6px" }}>
          {localConns.map(conn => {
            const isActive  = conn.id === selectedConn;
            const tm        = connTypeMeta(conn.conn_type);
            const testR     = testResults[conn.id];
            const dotColor  = testR ? (testR.ok ? "#34d399" : "#f87171") : isActive ? "#34d399" : "#3e3f4a";

            return (
              <div
                key={conn.id}
                style={{ position: "relative", marginBottom: 2 }}
                onMouseEnter={() => setHovConn(conn.id)}
                onMouseLeave={() => setHovConn(null)}
              >
                <button
                  onClick={() => onSelect(conn.id)}
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 8, width: "100%", padding: "8px 10px",
                    borderRadius: 6, textAlign: "left", cursor: "pointer", transition: "all .1s",
                    background: isActive ? "var(--bg-sel)" : "transparent",
                    border: `1px solid ${isActive ? "var(--blue2)" : "transparent"}`,
                  }}
                  onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)"; }}
                  onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0, marginTop: 4 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 500, color: isActive ? "var(--t1)" : "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {conn.name}
                    </div>
                    <div style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
                      {conn.dsn_preview}
                    </div>
                    <div style={{ display: "flex", gap: 5, marginTop: 4, alignItems: "center" }}>
                      <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: tm.bg, color: tm.color, border: `0.5px solid ${tm.border}` }}>
                        {tm.label}
                      </span>
                      <ExplorationBadge connectionId={conn.id} />
                    </div>
                  </div>
                </button>

                {/* Hover actions: Test + Delete */}
                {hovConn === conn.id && (
                  <div style={{ position: "absolute", bottom: 4, right: 6, display: "flex", gap: 4, alignItems: "center" }}>
                    <button
                      onClick={e => { e.stopPropagation(); handleTest(conn.id); }}
                      disabled={testing === conn.id}
                      style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "var(--bg-3)", color: "var(--t3)", border: "0.5px solid var(--b2)" }}
                    >
                      {testing === conn.id ? "…" : "Test"}
                    </button>
                    {!conn.builtin && (
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(conn.id); }}
                        style={{
                          fontSize: 9, padding: "2px 6px", borderRadius: 3, cursor: "pointer",
                          background: pendingDel === conn.id ? "#2a1414" : "var(--bg-3)",
                          color: pendingDel === conn.id ? "#f87171" : "var(--t4)",
                          border: `0.5px solid ${pendingDel === conn.id ? "#3e2020" : "var(--b2)"}`,
                        }}
                      >
                        {pendingDel === conn.id ? "Confirm" : "×"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Center: Table list ── */}
      <div style={{ flex: 1, borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {/* Center sub-header: connection name */}
        {selectedConnObj && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#34d399", flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)", fontFamily: "var(--font-mono)" }}>{selectedConnObj.name}</span>
            <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, ...connTypeMeta(selectedConnObj.conn_type) }}>
              {connTypeMeta(selectedConnObj.conn_type).label}
            </span>
            {selectedConnObj.schema_name && (
              <span style={{ fontSize: 10, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>· {selectedConnObj.schema_name}</span>
            )}
          </div>
        )}

        <TableList
          schema={schema}
          loading={loadingSchema}
          selectedTable={selectedTable}
          onSelectTable={setSelectedTable}
          onAsk={onChatWithTable ? (t) => onChatWithTable(t, selectedConn) : undefined}
        />
      </div>

      {/* ── Right: Table detail ── */}
      <div style={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {selectedTable ? (
          <TableDetail
            table={selectedTable}
            connId={selectedConn}
            connName={selectedConnObj?.name ?? selectedConn}
            onAsk={onChatWithTable ? (t) => onChatWithTable(t, selectedConn) : undefined}
          />
        ) : (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, padding: 24 }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" style={{ color: "#2e2f37" }}>
              <rect x="3" y="3" width="18" height="4" rx="1" />
              <rect x="3" y="9" width="18" height="4" rx="1" opacity=".6" />
              <rect x="3" y="15" width="18" height="4" rx="1" opacity=".3" />
            </svg>
            <p style={{ fontSize: 11, color: "#3e3f4a", textAlign: "center", lineHeight: 1.5 }}>
              Select a table to see its columns and details
            </p>
          </div>
        )}
      </div>

    </div>
  );
}
