"use client";

import { Fragment, useEffect, useState } from "react";
import TableIcon       from "@atlaskit/icon/core/table";
import ChevronDownIcon from "@atlaskit/icon/core/chevron-down";
import ChevronUpIcon   from "@atlaskit/icon/core/chevron-up";
import { getSchemaRich, RichSchema, getConnections, Connection } from "@/lib/api";

function fmtRows(n: string | number | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000) return (num / 1_000).toFixed(0) + "K";
  return String(num);
}

function typeColor(t: string): string {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT")) return "#7ba8f7";
  if (u.includes("BIGINT") || u.includes("INT")) return "#c084fc";
  if (u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "#4ade80";
  if (u.includes("DATE") || u.includes("TIME")) return "#f97316";
  if (u.includes("BOOL")) return "#4ade80";
  return "#9a9ba4";
}

function DBSelect({ connections, selectedId, onSelect }: {
  connections: Connection[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = connections.find(c => c.id === selectedId);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] cursor-pointer font-mono"
        style={{ background: "#13141a", border: "0.5px solid #1e1f24", color: "#9a9ba4" }}
      >
        <span className="w-[5px] h-[5px] rounded-full bg-emerald-400 shrink-0" />
        <span className="truncate max-w-[120px]">{current?.name ?? selectedId}</span>
        <span className="text-zinc-600 shrink-0"><ChevronDownIcon label="" size="small" /></span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 z-40 rounded-lg shadow-xl overflow-hidden" style={{ background: "#0d0e11", border: "0.5px solid #2a2b30", minWidth: "160px" }}>
            {connections.map(c => (
              <button
                key={c.id}
                onClick={() => { onSelect(c.id); setOpen(false); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-left transition font-mono"
                style={{ color: c.id === selectedId ? "#e8e6e1" : "#6e6f78" }}
                onMouseEnter={e => (e.currentTarget.style.background = "#13141a")}
                onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              >
                <span className={`w-[5px] h-[5px] rounded-full shrink-0 ${c.id === selectedId ? "bg-emerald-400" : "bg-zinc-600"}`} />
                <span className="truncate">{c.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

interface Props {
  connectionId: string;
  onChatWithTable?: (table: string, connectionId: string) => void;
}

export function CatalogPanel({ connectionId, onChatWithTable }: Props) {
  const [schema, setSchema] = useState<RichSchema | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedConn, setSelectedConn] = useState(connectionId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    getConnections().then(setConnections).catch(() => {});
  }, []);

  useEffect(() => {
    setSelectedConn(connectionId);
  }, [connectionId]);

  useEffect(() => {
    if (!selectedConn) return;
    setLoading(true);
    setError(null);
    setSchema(null);
    getSchemaRich(selectedConn)
      .then(setSchema)
      .catch(() => setError("Failed to load catalog."))
      .finally(() => setLoading(false));
  }, [selectedConn]);

  const tables = schema?.tables ?? [];
  const q = search.toLowerCase().trim();
  const filtered = q ? tables.filter(t => t.name.toLowerCase().includes(q)) : tables;

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "#0d0e11" }}>

      {/* ── Header ── */}
      <div className="px-5 pt-4 pb-3 shrink-0" style={{ borderBottom: "0.5px solid #1e1f24" }}>
        <div className="flex items-center justify-between mb-2">
          <div>
            <h2 className="text-[13.5px] font-medium" style={{ color: "#e8e6e1" }}>Catalog</h2>
            <p className="text-[11px] mt-0.5" style={{ color: "#3e3f47" }}>Browse tables and columns in the connected database</p>
          </div>
          <div className="flex items-center gap-2">
            <DBSelect connections={connections} selectedId={selectedConn} onSelect={setSelectedConn} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter tables…"
              className="text-[11px] rounded-md px-2.5 py-1 focus:outline-none w-36"
              style={{ background: "#13141a", border: "0.5px solid #1e1f24", color: "#6e6f78" }}
            />
          </div>
        </div>
        {schema && (
          <div className="flex items-center gap-4 mt-2">
            <span className="text-[11px] font-mono" style={{ color: "#5a5b62" }}>
              <span style={{ color: "#9a9ba4", fontWeight: 500 }}>{tables.length}</span> tables
            </span>
            <span className="text-[11px] font-mono" style={{ color: "#5a5b62" }}>
              <span style={{ color: "#9a9ba4", fontWeight: 500 }}>{tables.reduce((s, t) => s + t.columns.length, 0)}</span> columns
            </span>
            <span className="text-[11px] font-mono" style={{ color: "#5a5b62" }}>
              <span style={{ color: "#9a9ba4", fontWeight: 500 }}>
                {fmtRows(tables.reduce((s, t) => s + Number(t.row_count ?? 0), 0))}
              </span> total rows
            </span>
          </div>
        )}
      </div>

      {/* ── Table list ── */}
      <div className="flex-1 overflow-y-auto min-h-0 px-5 py-3">
        {loading && (
          <div className="space-y-1.5">
            {[1,2,3,4,5,6].map(i => (
              <div key={i} className="h-12 rounded-lg animate-pulse" style={{ background: "#13141a" }} />
            ))}
          </div>
        )}
        {error && (
          <p className="text-sm text-red-400 py-4">{error}</p>
        )}
        {!loading && !error && (
          <div className="flex flex-col gap-1.5">
            {filtered.length === 0 && (
              <p className="text-sm py-8 text-center" style={{ color: "#5a5b62" }}>No tables found.</p>
            )}
            {filtered.map(table => {
              const expanded = expandedTable === table.name;
              return (
                <div
                  key={table.name}
                  className="rounded-lg overflow-hidden"
                  style={{ background: "#13141a", border: "0.5px solid #1e1f24" }}
                >
                  {/* Table header row */}
                  <div
                    role="button"
                    tabIndex={0}
                    className="w-full text-left px-3.5 py-2.5 flex items-center gap-2.5 cursor-pointer"
                    onClick={() => setExpandedTable(expanded ? null : table.name)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") setExpandedTable(expanded ? null : table.name); }}
                    onMouseEnter={e => (e.currentTarget.querySelector(".table-name-text") as HTMLElement | null)?.style.setProperty("color", "#e8e6e1")}
                    onMouseLeave={e => (e.currentTarget.querySelector(".table-name-text") as HTMLElement | null)?.style.setProperty("color", "#c8c7c3")}
                  >
                    {/* Table icon */}
                    <div className="w-7 h-7 rounded-[5px] flex items-center justify-center shrink-0"
                      style={{ background: "#1a1b22", border: "0.5px solid #2a2b30", color: "#5a5b62" }}>
                      <TableIcon label="Table" size="small" />
                    </div>

                    <div className="min-w-0 shrink-0">
                      <p className="table-name-text text-[13px] font-medium font-mono transition-colors" style={{ color: "#c8c7c3" }}>
                        {table.name}
                      </p>
                      <p className="text-[10.5px] font-mono mt-0.5" style={{ color: "#3e3f47" }}>
                        {table.columns.length} columns · {fmtRows(table.row_count)} rows
                      </p>
                    </div>

                    {/* Column name tags */}
                    <div className="flex items-center gap-1 flex-1 flex-wrap ml-1">
                      {table.columns.slice(0, 4).map(col => (
                        <span
                          key={col.name}
                          className="text-[9.5px] font-mono px-1.5 py-0.5 rounded-[3px]"
                          style={{ background: "#1a1b22", border: "0.5px solid #2a2b30", color: "#5a5b62" }}
                        >
                          {col.name}
                        </span>
                      ))}
                      {table.columns.length > 4 && (
                        <span className="text-[9.5px] font-mono" style={{ color: "#3e3f47" }}>
                          +{table.columns.length - 4}
                        </span>
                      )}
                    </div>

                    {/* Ask button */}
                    {onChatWithTable && (
                      <button
                        onClick={e => { e.stopPropagation(); onChatWithTable(table.name, selectedConn); }}
                        className="shrink-0 flex items-center gap-1 text-[10.5px] px-2.5 py-1 rounded-[4px] transition-all"
                        style={{ border: "0.5px solid #2a3050", background: "#0d1525", color: "#4a6aaa" }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = "#3d6bff"; e.currentTarget.style.color = "#7ba8f7"; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = "#2a3050"; e.currentTarget.style.color = "#4a6aaa"; }}
                      >
                        Ask →
                      </button>
                    )}

                    {/* Chevron */}
                    <span className="shrink-0 ml-1" style={{ color: "#2e2f37" }}>
                      {expanded ? <ChevronUpIcon label="" size="small" /> : <ChevronDownIcon label="" size="small" />}
                    </span>
                  </div>

                  {/* Expanded columns */}
                  {expanded && (
                    <div style={{ borderTop: "0.5px solid #1a1b20" }}>
                      <div className="grid px-3.5 py-1.5 text-[9.5px] uppercase tracking-[0.07em]"
                        style={{ gridTemplateColumns: "1fr 100px 40px", background: "#0f1014", color: "#2e2f37" }}>
                        <span>Column</span>
                        <span>Type</span>
                        <span>FK</span>
                      </div>
                      {table.columns.map(col => (
                        <div
                          key={col.name}
                          className="grid px-3.5 py-1.5 transition-colors"
                          style={{ gridTemplateColumns: "1fr 100px 40px", borderTop: "0.5px solid #1a1b20" }}
                          onMouseEnter={e => (e.currentTarget.style.background = "#161720")}
                          onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                        >
                          <span className="text-[11.5px] font-mono" style={{ color: "#9a9ba4" }}>{col.name}</span>
                          <span className="text-[10.5px] font-mono" style={{ color: typeColor(col.type) }}>{col.type}</span>
                          <span className="text-[10px] font-mono" style={{ color: col.is_fk ? "#3d6bff" : "#3e3f47" }}>
                            {col.is_fk ? "FK" : "—"}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
