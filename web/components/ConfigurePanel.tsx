"use client";

import { useEffect, useRef, useState } from "react";
import CloseIcon         from "@atlaskit/icon/core/close";
import ChevronRightIcon  from "@atlaskit/icon/core/chevron-right";
import TableIcon         from "@atlaskit/icon/core/table";
import InformationIcon   from "@atlaskit/icon/core/information";
import { MetricsPanel } from "./MetricsPanel";
import { useSchema } from "@/lib/schema-context";
import type { Connection } from "@/lib/api";

const BASE = "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SchemaColumn {
  name: string;
  type: string;
  is_fk: boolean;
}
interface SchemaTable {
  name: string;
  row_count: string;
  columns: SchemaColumn[];
}

// ── Shared tab bar ────────────────────────────────────────────────────────────

function TabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="flex border-b border-zinc-700/60 shrink-0">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-2.5 text-[12px] font-medium transition-colors border-b-2 -mb-px ${
            active === t.id
              ? "border-blue-500 text-zinc-100"
              : "border-transparent text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── About tab ─────────────────────────────────────────────────────────────────

function AboutTab({
  connection,
  connections,
  onSelectConn,
}: {
  connection: Connection | undefined;
  connections: Connection[];
  onSelectConn: (id: string) => void;
}) {
  if (!connection) return <p className="text-[12px] text-zinc-500 p-4">No connection selected.</p>;

  const rows: { label: string; value: string }[] = [
    { label: "Name",    value: connection.name },
    { label: "Type",    value: connection.conn_type },
    { label: "Schema",  value: connection.schema_name ?? "—" },
    { label: "ID",      value: connection.id },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-5">
      <div>
        <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-semibold mb-3">About this space</p>
        <div className="rounded-lg border border-zinc-700/50 overflow-hidden" style={{ background: "#131c27" }}>
          {rows.map((r, i) => (
            <div key={r.label} className={`flex items-start px-3 py-2.5 gap-4 text-[12px] ${i > 0 ? "border-t border-zinc-700/40" : ""}`}>
              <span className="w-16 shrink-0 text-zinc-500">{r.label}</span>
              <span className="text-zinc-200 font-mono break-all">{r.value}</span>
            </div>
          ))}
        </div>
      </div>

      {connections.length > 1 && (
        <div>
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-semibold mb-3">Switch connection</p>
          <div className="space-y-1">
            {connections.map((c) => (
              <button
                key={c.id}
                onClick={() => onSelectConn(c.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] transition ${
                  c.id === connection.id
                    ? "bg-zinc-700/60 text-zinc-100"
                    : "text-zinc-400 hover:bg-zinc-700/30 hover:text-zinc-200"
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${c.id === connection.id ? "bg-emerald-400" : "bg-zinc-600"}`} />
                <span className="font-mono truncate flex-1 text-left">{c.name}</span>
                {c.id === connection.id && (
                  <span className="text-[10px] text-emerald-400 font-medium">active</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Table detail (Overview + Sample Data) ──────────────────────────────────────

function TableDetail({
  connId,
  table,
  onClose,
}: {
  connId: string;
  table: SchemaTable;
  onClose: () => void;
}) {
  const [subtab, setSubtab] = useState<"overview" | "sample">("overview");
  const [sampleCols, setSampleCols] = useState<string[]>([]);
  const [sampleRows, setSampleRows] = useState<(string | null)[][]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (subtab !== "sample" || loaded) return;
    setLoading(true);
    fetch(`${BASE}/connections/${connId}/tables/${encodeURIComponent(table.name)}/sample?limit=100`)
      .then((r) => r.json())
      .then((d) => { setSampleCols(d.columns ?? []); setSampleRows(d.rows ?? []); setLoaded(true); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [subtab, connId, table.name, loaded]);

  const TYPE_COLOR: Record<string, string> = {
    VARCHAR: "text-sky-400", BIGINT: "text-amber-400", INTEGER: "text-amber-400",
    DOUBLE: "text-violet-400", FLOAT: "text-violet-400", DATE: "text-emerald-400",
    TIMESTAMP: "text-emerald-400", BOOLEAN: "text-rose-400",
  };

  function typeColor(t: string) {
    const key = Object.keys(TYPE_COLOR).find((k) => t.toUpperCase().startsWith(k));
    return key ? TYPE_COLOR[key] : "text-zinc-400";
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-700/60 shrink-0">
        <div className="flex items-center gap-2">
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 transition">
            <span className="rotate-180 inline-block"><ChevronRightIcon label="Back" size="small" /></span>
          </button>
          <span className="text-[12px] font-semibold text-zinc-200 font-mono">{table.name}</span>
          <span className="text-[10px] text-zinc-500">
            {table.columns.length} cols · {Number(table.row_count).toLocaleString()} rows
          </span>
        </div>
      </div>

      <TabBar
        tabs={[{ id: "overview", label: "Overview" }, { id: "sample", label: "Sample Data" }]}
        active={subtab}
        onChange={(id) => setSubtab(id as "overview" | "sample")}
      />

      {subtab === "overview" && (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 z-10">
              <tr style={{ background: "#1a2535" }}>
                <th className="px-3 py-2 text-left text-zinc-400 font-semibold">Column</th>
                <th className="px-3 py-2 text-left text-zinc-400 font-semibold">Type</th>
                <th className="px-3 py-2 text-left text-zinc-400 font-semibold">FK</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((col, i) => (
                <tr key={col.name} className={`border-t border-zinc-700/30 ${i % 2 === 0 ? "" : "bg-white/[0.01]"}`}>
                  <td className="px-3 py-2 font-mono text-zinc-200">{col.name}</td>
                  <td className={`px-3 py-2 font-mono ${typeColor(col.type)}`}>{col.type}</td>
                  <td className="px-3 py-2 text-zinc-500">{col.is_fk ? "✓" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {subtab === "sample" && (
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="flex items-center justify-center h-24 text-[12px] text-zinc-500">Loading…</div>
          )}
          {!loading && sampleCols.length > 0 && (
            <table className="text-[12px] whitespace-nowrap">
              <thead className="sticky top-0 z-10">
                <tr style={{ background: "#1a2535" }}>
                  {sampleCols.map((c) => (
                    <th key={c} className="px-3 py-2 text-left text-zinc-400 font-semibold border-r border-zinc-700/40 last:border-0">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleRows.map((row, ri) => (
                  <tr key={ri} className="border-t border-zinc-700/30 hover:bg-white/[0.02]">
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-3 py-1.5 text-zinc-300 font-mono border-r border-zinc-700/20 last:border-0 max-w-[180px] truncate">
                        {cell ?? <span className="text-zinc-600 italic">null</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!loading && sampleCols.length === 0 && loaded && (
            <p className="text-[12px] text-zinc-500 p-4">No data available.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Data tab ──────────────────────────────────────────────────────────────────

function DataTab({ connId }: { connId: string }) {
  const { schema } = useSchema();
  const tables: SchemaTable[] = (schema?.tables ?? []) as SchemaTable[];
  const [selected, setSelected] = useState<SchemaTable | null>(null);
  const [filter, setFilter] = useState("");

  if (selected) {
    return <TableDetail connId={connId} table={selected} onClose={() => setSelected(null)} />;
  }

  const filtered = tables.filter((t) =>
    !filter || t.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Filter */}
      <div className="px-3 py-2 border-b border-zinc-700/40 shrink-0">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter tables…"
          className="w-full bg-zinc-800/60 border border-zinc-700/50 rounded-lg px-3 py-1.5 text-[12px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600"
        />
      </div>

      {/* Table list */}
      <div className="flex-1 overflow-y-auto">
        {tables.length > 0 && (
          <div className="flex items-center px-3 py-2 text-[11px] text-zinc-600 font-semibold uppercase tracking-wider border-b border-zinc-700/40 sticky top-0 bg-zinc-900">
            <span className="flex-1">Name</span>
            <span className="w-12 text-right">Cols</span>
            <span className="w-20 text-right">Rows</span>
            <span className="w-4" />
          </div>
        )}
        {filtered.map((t) => (
          <button
            key={t.name}
            onClick={() => setSelected(t)}
            className="w-full flex items-center px-3 py-2.5 text-[12px] border-b border-zinc-700/30 hover:bg-zinc-700/20 transition group text-left"
          >
            <span className="text-zinc-500 shrink-0 mr-2"><TableIcon label="Table" size="small" /></span>
            <span className="flex-1 font-mono text-zinc-200 truncate">{t.name}</span>
            <span className="w-12 text-right text-zinc-500 shrink-0">{t.columns.length}</span>
            <span className="w-20 text-right text-zinc-500 shrink-0 font-mono">
              {Number(t.row_count) >= 1_000_000
                ? `${(Number(t.row_count) / 1_000_000).toFixed(1)}M`
                : Number(t.row_count) >= 1_000
                ? `${(Number(t.row_count) / 1_000).toFixed(0)}k`
                : t.row_count}
            </span>
            <span className="text-zinc-600 group-hover:text-zinc-400 transition ml-1 shrink-0"><ChevronRightIcon label="" size="small" /></span>
          </button>
        ))}
        {filter && filtered.length === 0 && (
          <p className="text-[12px] text-zinc-500 p-4">No tables match &ldquo;{filter}&rdquo;.</p>
        )}
      </div>
    </div>
  );
}

// ── Instructions tab ──────────────────────────────────────────────────────────

function InstructionsTab({ connId }: { connId: string }) {
  const [subtab, setSubtab] = useState<"text" | "metrics">("text");
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    fetch(`${BASE}/connections/${connId}/instructions`)
      .then((r) => r.json())
      .then((d) => { setText(d.text ?? ""); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [connId]);

  async function handleSave() {
    setSaving(true);
    try {
      await fetch(`${BASE}/connections/${connId}/instructions`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <TabBar
        tabs={[{ id: "text", label: "Text" }, { id: "metrics", label: "Metrics" }]}
        active={subtab}
        onChange={(id) => setSubtab(id as "text" | "metrics")}
      />

      {subtab === "text" && (
        <div className="flex-1 flex flex-col overflow-hidden p-3 gap-2">
          <p className="text-[11px] text-zinc-500 leading-relaxed">
            Plain-English instructions the AI follows for every query on this connection. Describe business rules, metric definitions, fiscal calendar, naming conventions, etc.
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!loaded}
            placeholder={loaded ? "* Revenue uses the net_revenue column, not gross_revenue\n* Fiscal year starts in February\n* Always include region when comparing performance" : "Loading…"}
            className="flex-1 resize-none bg-zinc-900/80 border border-zinc-700/50 rounded-lg px-3 py-2.5 text-[12px] font-mono text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600"
          />
          <div className="flex justify-end shrink-0">
            <button
              onClick={handleSave}
              disabled={saving || !loaded}
              className="px-4 py-1.5 rounded-lg bg-blue-600 text-white text-[12px] font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {saving ? "Saving…" : saved ? "Saved ✓" : "Save"}
            </button>
          </div>
        </div>
      )}

      {subtab === "metrics" && (
        <div className="flex-1 overflow-auto p-2">
          <MetricsPanel />
        </div>
      )}
    </div>
  );
}

// ── Main ConfigurePanel ───────────────────────────────────────────────────────

interface ConfigurePanelProps {
  connectionId: string;
  connections: Connection[];
  onSelectConn: (id: string) => void;
  onClose: () => void;
}

export function ConfigurePanel({ connectionId, connections, onSelectConn, onClose }: ConfigurePanelProps) {
  const [tab, setTab] = useState<"about" | "data" | "instructions">("about");
  const connection = connections.find((c) => c.id === connectionId);

  const TABS = [
    { id: "about",        label: "About" },
    { id: "data",         label: "Data" },
    { id: "instructions", label: "Instructions" },
  ];

  return (
    <>
      {/* Backdrop — only covers area below both topbars (global h-12=48px + section h=52px) */}
      <div
        className="fixed left-0 right-0 bottom-0 z-40"
        style={{ top: "100px" }}
        onClick={onClose}
      />

      {/* Panel — anchored below topbars, not covering the header */}
      <div
        className="fixed right-0 bottom-0 z-50 flex flex-col border-l border-zinc-700/80 shadow-2xl"
        style={{ top: "100px", width: "400px", background: "#11171d" }}
      >
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/60 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-zinc-400"><InformationIcon label="Configure" size="small" /></span>
            <span className="text-[12px] font-semibold text-zinc-200">Configure</span>
            {connection && (
              <span className="text-[11px] text-zinc-500 font-mono truncate max-w-[140px]">{connection.name}</span>
            )}
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 transition">
            <CloseIcon label="Close" size="small" />
          </button>
        </div>

        {/* Top-level tabs */}
        <TabBar tabs={TABS} active={tab} onChange={(id) => setTab(id as typeof tab)} />

        {/* Tab content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {tab === "about" && (
            <AboutTab connection={connection} connections={connections} onSelectConn={(id) => { onSelectConn(id); }} />
          )}
          {tab === "data" && (
            <DataTab connId={connectionId} />
          )}
          {tab === "instructions" && (
            <InstructionsTab connId={connectionId} />
          )}
        </div>
      </div>
    </>
  );
}
