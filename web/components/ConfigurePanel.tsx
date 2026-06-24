"use client";

import { useEffect, useMemo, useState } from "react";
import { SqlResultTable } from "@/components/AugTable";
import { compactNumber } from "@/lib/format";
import CloseIcon         from "@atlaskit/icon/core/close";
import ChevronRightIcon  from "@atlaskit/icon/core/chevron-right";
import TableIcon         from "@atlaskit/icon/core/table";
import InformationIcon   from "@atlaskit/icon/core/information";
import { MetricsPanel } from "./MetricsPanel";
import { DocumentUploader } from "./DocumentUploader";
import { useSchema } from "@/lib/schema-context";
import {
  updateCanvas,
  getCanvasInstructions,
  putCanvasInstructions,
  type Connection,
  type Canvas,
} from "@/lib/api";

import { API_BASE as BASE } from "@/lib/config";

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

const leaf = (s: string) => (s || "").split(".").pop()!.toLowerCase();

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
    <div className="flex border-b border-[--b1] shrink-0">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-2.5 text-[12px] font-medium transition-colors border-b-2 -mb-px ${
            active === t.id
              ? "border-[--blue3] text-[--t1]"
              : "border-transparent text-[--t3] hover:text-[--t1]"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── About tab (Canvas-level) ────────────────────────────────────────────────

function AboutTab({
  canvas,
  connection,
  onCanvasUpdate,
}: {
  canvas: Canvas;
  connection: Connection | undefined;
  onCanvasUpdate?: (c: Canvas) => void;
}) {
  const [name, setName] = useState(canvas.name);
  const [desc, setDesc] = useState(canvas.description);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { setName(canvas.name); setDesc(canvas.description); }, [canvas.id, canvas.name, canvas.description]);

  const scope = canvas.scopes[0];
  const tableCount = scope?.tables.length ?? 0;
  const dirty = name.trim() !== canvas.name || desc !== canvas.description;

  async function handleSave() {
    if (!dirty || !name.trim()) return;
    setSaving(true);
    try {
      const updated = await updateCanvas(canvas.id, { name: name.trim(), description: desc });
      onCanvasUpdate?.(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  const scopeRows: { label: string; value: string }[] = [
    { label: "Connection", value: connection?.name ?? scope?.connection_id ?? "—" },
    { label: "Type",       value: connection?.conn_type ?? "—" },
    { label: "Schema",     value: scope?.schema_name ?? connection?.schema_name ?? "—" },
    { label: "Tables",     value: tableCount === 0 ? "All tables" : `${tableCount} selected` },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-5">
      <div>
        <p className="aug-label mb-2">Data Canvas name</p>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="aug-input"
          placeholder="Data Canvas name"
        />
      </div>

      <div>
        <p className="aug-label mb-2">Description</p>
        <textarea
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          rows={4}
          placeholder="What is this canvas about? Auto-generated from your data — edit anytime."
          className="w-full resize-none border border-[--b2] rounded-md px-3 py-2 text-[12px] text-[--t1] placeholder:text-[--t4] focus:outline-none focus:border-[--bfocus] transition-colors"
          style={{ background: "var(--bg-0)", fontFamily: "var(--font-ui)" }}
        />
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={!dirty || !name.trim() || saving}
          className="aug-btn aug-btn-primary aug-btn-sm disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving…" : saved ? "Saved ✓" : "Save"}
        </button>
      </div>

      <div>
        <p className="aug-label mb-3">Scope</p>
        <div className="rounded-md border border-[--b1] overflow-hidden" style={{ background: "var(--bg-3)" }}>
          {scopeRows.map((r, i) => (
            <div key={r.label} className={`flex items-start px-3 py-2.5 gap-4 text-[12px] ${i > 0 ? "border-t border-[--b0]" : ""}`}>
              <span className="w-20 shrink-0 text-[--t3]">{r.label}</span>
              <span className="text-[--t1] font-mono break-all">{r.value}</span>
            </div>
          ))}
        </div>
      </div>
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
    VARCHAR: "text-cyan-400", BIGINT: "text-amber-400", INTEGER: "text-amber-400",
    DOUBLE: "text-zinc-400", FLOAT: "text-zinc-400", DATE: "text-zinc-400",
    TIMESTAMP: "text-zinc-400", BOOLEAN: "text-zinc-400",
  };

  function typeColor(t: string) {
    const key = Object.keys(TYPE_COLOR).find((k) => t.toUpperCase().startsWith(k));
    return key ? TYPE_COLOR[key] : "text-zinc-400";
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[--b1] shrink-0">
        <div className="flex items-center gap-2">
          <button onClick={onClose} className="text-[--t3] hover:text-[--t1] transition">
            <span className="rotate-180 inline-block"><ChevronRightIcon label="Back" size="small" /></span>
          </button>
          <span className="text-[12px] font-semibold text-[--t1] font-mono">{table.name}</span>
          <span className="text-[11px] text-[--t3]">
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
              <tr style={{ background: "var(--bg-3)" }}>
                <th className="px-3 py-2 text-left text-[--t2] font-semibold">Column</th>
                <th className="px-3 py-2 text-left text-[--t2] font-semibold">Type</th>
                <th className="px-3 py-2 text-left text-[--t2] font-semibold">FK</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((col, i) => (
                <tr key={col.name} className={`border-t border-[--b0] ${i % 2 === 0 ? "" : "bg-white/[0.01]"}`}>
                  <td className="px-3 py-2 font-mono text-[--t1]">{col.name}</td>
                  <td className={`px-3 py-2 font-mono ${typeColor(col.type)}`}>{col.type}</td>
                  <td className="px-3 py-2 text-[--t3]">{col.is_fk ? "✓" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {subtab === "sample" && (
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="flex items-center justify-center h-24 text-[12px] text-[--t2]">Loading…</div>
          )}
          {!loading && sampleCols.length > 0 && (
            <SqlResultTable columns={sampleCols} rows={sampleRows as unknown[][]} maxHeight={420} />
          )}
          {!loading && sampleCols.length === 0 && loaded && (
            <p className="text-[12px] text-[--t2] p-4">No data available.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Data tab (scoped to Canvas tables) ──────────────────────────────────────

function DataTab({
  canvas,
  connId,
  onCanvasUpdate,
}: {
  canvas: Canvas;
  connId: string;
  onCanvasUpdate?: (c: Canvas) => void;
}) {
  const { schema } = useSchema();
  const allTables: SchemaTable[] = (schema?.tables ?? []) as SchemaTable[];
  const [selected, setSelected] = useState<SchemaTable | null>(null);
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);

  const scope = canvas.scopes[0];
  const scopeTables = scope?.tables ?? [];

  // Membership as a set of leaf names. Empty scope = ALL tables included.
  const allLeaves = useMemo(() => allTables.map((t) => leaf(t.name)), [allTables]);
  const [included, setIncluded] = useState<Set<string>>(new Set());
  useEffect(() => {
    setIncluded(
      scopeTables.length === 0
        ? new Set(allLeaves)
        : new Set(scopeTables.map(leaf)),
    );
    // Re-sync when the canvas or the available table set changes.
  }, [canvas.id, scopeTables.length, allLeaves.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const persist = (next: Set<string>) => {
    if (!scope) return;
    const coversAll = allLeaves.length > 0 && allLeaves.every((l) => next.has(l));
    const tables = coversAll
      ? []                                   // all tables → store empty (means "all")
      : allTables.filter((t) => next.has(leaf(t.name))).map((t) => t.name);
    setSaving(true);
    updateCanvas(canvas.id, {
      scopes: [{ connection_id: scope.connection_id, schema_name: scope.schema_name ?? null, tables }],
    })
      .then((updated) => onCanvasUpdate?.(updated))
      .catch(() => {})
      .finally(() => setSaving(false));
  };

  const toggle = (name: string) => {
    const l = leaf(name);
    const next = new Set(included);
    if (next.has(l)) next.delete(l);
    else next.add(l);
    setIncluded(next);
    persist(next);
  };

  const setAll = (on: boolean) => {
    const next = on ? new Set(allLeaves) : new Set<string>();
    setIncluded(next);
    persist(next);
  };

  if (selected) {
    return <TableDetail connId={connId} table={selected} onClose={() => setSelected(null)} />;
  }

  const filtered = allTables.filter((t) =>
    !filter || t.name.toLowerCase().includes(filter.toLowerCase())
  );
  const includedCount = allLeaves.filter((l) => included.has(l)).length;
  const isAll = includedCount === allLeaves.length && allLeaves.length > 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Scope note + filter */}
      <div className="px-3 py-2 border-b border-[--b1] shrink-0 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-[--t3]">
            {isAll
              ? "All tables included in this canvas."
              : `${includedCount} of ${allTables.length} table${allTables.length === 1 ? "" : "s"} included.`}
            {saving && <span className="text-[--t4]"> · saving…</span>}
          </p>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => setAll(true)}
              disabled={isAll || saving}
              className="text-[11px] text-[--t3] hover:text-[--t1] disabled:opacity-40 transition"
            >
              Include all
            </button>
            <span className="text-[--b2]">·</span>
            <button
              onClick={() => setAll(false)}
              disabled={includedCount === 0 || saving}
              className="text-[11px] text-[--t3] hover:text-[--t1] disabled:opacity-40 transition"
            >
              Clear
            </button>
          </div>
        </div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter tables…"
          className="aug-input py-1.5"
        />
      </div>

      {/* Table list — checkbox toggles canvas membership; row opens detail */}
      <div className="flex-1 overflow-y-auto">
        {allTables.length > 0 && (
          <div className="flex items-center px-3 py-2 aug-label border-b border-[--b1] sticky top-0" style={{ background: "var(--bg-1)" }}>
            <span className="w-6" />
            <span className="flex-1">Name</span>
            <span className="w-12 text-right">Cols</span>
            <span className="w-20 text-right">Rows</span>
            <span className="w-4" />
          </div>
        )}
        {filtered.map((t) => {
          const on = included.has(leaf(t.name));
          return (
          <div
            key={t.name}
            className="w-full flex items-center px-3 py-2.5 text-[12px] border-b border-[--b0] hover:bg-[--bg-hover] transition group"
          >
            {/* Membership checkbox */}
            <button
              onClick={() => toggle(t.name)}
              disabled={saving}
              title={on ? "Remove from canvas" : "Add to canvas"}
              className="w-6 shrink-0 flex items-center"
            >
              <span
                className="w-4 h-4 rounded flex items-center justify-center transition"
                style={{
                  border: `1px solid ${on ? "var(--blue4)" : "var(--b2)"}`,
                  background: on ? "var(--blue4)" : "transparent",
                }}
              >
                {on && (
                  <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#0b1220" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 6.5l2.5 2.5 4.5-5" /></svg>
                )}
              </span>
            </button>
            {/* Open detail */}
            <button onClick={() => setSelected(t)} className="flex-1 flex items-center min-w-0 text-left">
              <span className="text-[--t3] shrink-0 mr-2"><TableIcon label="Table" size="small" /></span>
              <span className="flex-1 font-mono text-[--t1] truncate">{t.name}</span>
            </button>
            <span className="w-12 text-right text-[--t3] shrink-0">{t.columns.length}</span>
            <span className="w-20 text-right text-[--t3] shrink-0 font-mono">
              {compactNumber(Number(t.row_count), 1)}
            </span>
            <button onClick={() => setSelected(t)} className="text-[--t4] group-hover:text-[--t2] transition ml-1 shrink-0">
              <ChevronRightIcon label="" size="small" />
            </button>
          </div>
          );
        })}
        {filter && filtered.length === 0 && (
          <p className="text-[12px] text-[--t2] p-4">No tables match &ldquo;{filter}&rdquo;.</p>
        )}
        {!filter && allTables.length === 0 && (
          <p className="text-[12px] text-[--t2] p-4">No tables available in this connection.</p>
        )}
      </div>
    </div>
  );
}

// ── Instructions tab (Canvas-level) ─────────────────────────────────────────

function InstructionsTab({ canvasId }: { canvasId: string }) {
  const [subtab, setSubtab] = useState<"text" | "metrics">("text");
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    getCanvasInstructions(canvasId)
      .then((t) => { setText(t); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [canvasId]);

  async function handleSave() {
    setSaving(true);
    try {
      await putCanvasInstructions(canvasId, text);
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
          <p className="text-[12px] text-[--t2] leading-relaxed">
            Plain-English instructions the AI follows for every query on this canvas. Describe business rules, metric definitions, fiscal calendar, naming conventions, etc.
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!loaded}
            placeholder={loaded ? "* Revenue uses the net_revenue column, not gross_revenue\n* Fiscal year starts in February\n* Always include region when comparing performance" : "Loading…"}
            className="flex-1 resize-none border border-[--b2] rounded-md px-3 py-2.5 text-[12px] font-mono text-[--t1] placeholder:text-[--t4] focus:outline-none focus:border-[--bfocus] transition-colors"
            style={{ background: "var(--bg-0)" }}
          />
          <div className="flex justify-end shrink-0">
            <button
              onClick={handleSave}
              disabled={saving || !loaded}
              className="aug-btn aug-btn-primary aug-btn-sm disabled:opacity-40 disabled:cursor-not-allowed"
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
  canvas: Canvas;
  connections: Connection[];
  onClose: () => void;
  onCanvasUpdate?: (c: Canvas) => void;
}

export function ConfigurePanel({ canvas, connections, onClose, onCanvasUpdate }: ConfigurePanelProps) {
  const [tab, setTab] = useState<"about" | "data" | "instructions" | "docs">("about");
  const connectionId = canvas.scopes[0]?.connection_id ?? "";
  const connection = connections.find((c) => c.id === connectionId);
  const scopeTables = canvas.scopes[0]?.tables ?? [];

  const TABS = [
    { id: "about",        label: "About" },
    { id: "data",         label: "Data" },
    { id: "instructions", label: "Instructions" },
    { id: "docs",         label: "Docs" },
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
        className="fixed right-0 bottom-0 z-50 flex flex-col border-l border-[--b1] shadow-2xl"
        style={{ top: "100px", width: "400px", background: "var(--bg-0)" }}
      >
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[--b1] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[--t3]"><InformationIcon label="Configure" size="small" /></span>
            <span className="text-[12px] font-semibold text-[--t1]">Configure</span>
            <span className="text-[11px] text-[--t3] truncate max-w-[180px]">{canvas.name}</span>
          </div>
          <button onClick={onClose} className="text-[--t3] hover:text-[--t1] transition">
            <CloseIcon label="Close" size="small" />
          </button>
        </div>

        {/* Top-level tabs */}
        <TabBar tabs={TABS} active={tab} onChange={(id) => setTab(id as typeof tab)} />

        {/* Tab content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {tab === "about" && (
            <AboutTab canvas={canvas} connection={connection} onCanvasUpdate={onCanvasUpdate} />
          )}
          {tab === "data" && (
            <DataTab canvas={canvas} connId={connectionId} onCanvasUpdate={onCanvasUpdate} />
          )}
          {tab === "instructions" && (
            <InstructionsTab canvasId={canvas.id} />
          )}
          {tab === "docs" && (
            <div className="flex-1 overflow-auto p-2">
              <DocumentUploader />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
