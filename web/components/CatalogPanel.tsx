"use client";

import { Fragment, useEffect, useState } from "react";
import TableIcon       from "@atlaskit/icon/core/table";
import ChevronDownIcon from "@atlaskit/icon/core/chevron-down";
import { getSchemaRich, RichSchema, getConnections, Connection } from "@/lib/api";

function fmtRows(n: string | number | null | undefined): string {
  if (n == null) return "—";
  const num = Number(n);
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + "M";
  if (num >= 1_000) return (num / 1_000).toFixed(0) + "K";
  return String(num);
}

function typeColor(t: string) {
  const u = t.toUpperCase();
  if (u.includes("VARCHAR") || u.includes("TEXT")) return "text-sky-400";
  if (u.includes("INT") || u.includes("BIGINT") || u.includes("DOUBLE") || u.includes("FLOAT") || u.includes("NUMERIC")) return "text-violet-400";
  if (u.includes("DATE") || u.includes("TIME")) return "text-amber-400";
  if (u.includes("BOOL")) return "text-emerald-400";
  return "text-zinc-400";
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
    <div className="flex-1 flex flex-col overflow-hidden">

      {/* ── Header ── */}
      <div className="px-6 py-4 border-b border-zinc-600 shrink-0 flex items-center gap-4">
        <div className="flex-1">
          <h2 className="text-base font-semibold text-zinc-200">Catalog</h2>
          <p className="text-xs text-zinc-500 mt-0.5">Browse tables and columns in the connected database</p>
        </div>

        {/* Connection picker */}
        <select
          value={selectedConn}
          onChange={e => setSelectedConn(e.target.value)}
          className="text-xs bg-zinc-700/60 border border-zinc-600 rounded-lg text-zinc-300 px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-zinc-500 transition"
        >
          {connections.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        {/* Search */}
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter tables…"
          className="text-xs bg-zinc-700/60 border border-zinc-600 rounded-lg text-zinc-300 placeholder:text-zinc-500 px-3 py-1.5 w-44 focus:outline-none focus:ring-1 focus:ring-zinc-500 transition"
        />
      </div>

      {/* ── Stats bar ── */}
      {schema && (
        <div className="px-6 py-2 border-b border-zinc-600/50 shrink-0 flex items-center gap-6">
          <span className="text-xs text-zinc-500">{tables.length} tables</span>
          <span className="text-xs text-zinc-600">·</span>
          <span className="text-xs text-zinc-500">
            {tables.reduce((s, t) => s + t.columns.length, 0)} columns
          </span>
          <span className="text-xs text-zinc-600">·</span>
          <span className="text-xs text-zinc-500">
            {(() => {
              const total = tables.reduce((s, t) => s + Number(t.row_count ?? 0), 0);
              return fmtRows(total) + " total rows";
            })()}
          </span>
        </div>
      )}

      {/* ── Table list ── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {loading && (
          <div className="p-6 space-y-3">
            {[1,2,3,4,5,6].map(i => (
              <div key={i} className="h-16 rounded-xl bg-zinc-700/20 animate-pulse" />
            ))}
          </div>
        )}
        {error && (
          <div className="p-6">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}
        {!loading && !error && (
          <div className="p-6 grid grid-cols-1 gap-2 max-w-5xl">
            {filtered.length === 0 && (
              <p className="text-sm text-zinc-500 col-span-full py-8 text-center">No tables found.</p>
            )}
            {filtered.map(table => {
              const expanded = expandedTable === table.name;
              return (
                <div
                  key={table.name}
                  className="rounded-xl border border-zinc-700 bg-zinc-800/40 overflow-hidden transition-all hover:border-zinc-600"
                >
                  {/* Table header row — div with role="button" to allow nested interactive elements */}
                  <div
                    role="button"
                    tabIndex={0}
                    className="w-full text-left px-5 py-3.5 flex items-center gap-4 group cursor-pointer"
                    onClick={() => setExpandedTable(expanded ? null : table.name)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") setExpandedTable(expanded ? null : table.name); }}
                  >
                    {/* Table icon */}
                    <div className="w-8 h-8 rounded-lg bg-zinc-700/60 border border-zinc-600 flex items-center justify-center shrink-0 text-zinc-400">
                      <TableIcon label="Table" size="small" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-zinc-200 group-hover:text-white transition font-mono">
                        {table.name}
                      </p>
                      <p className="text-xs text-zinc-500 mt-0.5">
                        {table.columns.length} columns · {fmtRows(table.row_count)} rows
                      </p>
                    </div>

                    {/* Column type pills preview */}
                    <div className="hidden md:flex items-center gap-1.5 shrink-0">
                      {table.columns.slice(0, 4).map(col => (
                        <span
                          key={col.name}
                          className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-700/60 text-zinc-400"
                        >
                          {col.name}
                        </span>
                      ))}
                      {table.columns.length > 4 && (
                        <span className="text-[10px] text-zinc-500">+{table.columns.length - 4}</span>
                      )}
                    </div>

                    {/* Ask button — separate click target, stops propagation */}
                    {onChatWithTable && (
                      <button
                        onClick={e => { e.stopPropagation(); onChatWithTable(table.name, selectedConn); }}
                        className="shrink-0 text-[11px] text-zinc-500 hover:text-zinc-200 border border-zinc-600 hover:border-zinc-500 rounded-lg px-2.5 py-1 transition ml-2"
                      >
                        Ask →
                      </button>
                    )}

                    {/* Chevron */}
                    <span className={`shrink-0 text-zinc-500 transition-transform ml-1 inline-block ${expanded ? "rotate-180" : ""}`}>
                      <ChevronDownIcon label="" size="small" />
                    </span>
                  </div>

                  {/* Expanded columns */}
                  {expanded && (
                    <div className="border-t border-zinc-700/60 px-5 pb-4 pt-3">
                      <div className="grid grid-cols-[1fr_auto_auto] gap-x-6 gap-y-1.5">
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium">Column</span>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium">Type</span>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium">FK</span>
                        {table.columns.map(col => (
                          <Fragment key={col.name}>
                            <span className="text-xs font-mono text-zinc-300">{col.name}</span>
                            <span className={`text-xs font-mono ${typeColor(col.type)}`}>{col.type}</span>
                            <span className="text-xs text-zinc-500">
                              {col.is_fk ? <span className="text-violet-400">FK</span> : "—"}
                            </span>
                          </Fragment>
                        ))}
                      </div>
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
