"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  getConnections, getSchemaRich, getMetrics, runDirectQuery, getCatalogTree,
  type Connection, type SchemaColumn, type SchemaJoin, type Metric, type DirectQueryResult,
  type CatalogEntry,
} from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import { ResizableSplit } from "@/components/ResizableSplit";
import { SqlResultTable } from "@/components/AugTable";
import { ChartWrapper }       from "@/components/charts/ChartWrapper";
import { inferChartType, type ChartType } from "@/components/charts/chartTypeInference";

// ── Aggregation catalogue ─────────────────────────────────────────────────────

const AGG_OPTIONS = [
  { fn: "SUM",            label: "SUM",    hint: "Sum of values",            cls: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10" },
  { fn: "AVG",            label: "AVG",    hint: "Average value",            cls: "text-blue-400   border-blue-500/30   bg-blue-500/10"    },
  { fn: "COUNT",          label: "COUNT",  hint: "Row count",                cls: "text-violet-400 border-violet-500/30 bg-violet-500/10"  },
  { fn: "COUNT DISTINCT", label: "C.DIST", hint: "Count unique values",      cls: "text-purple-400 border-purple-500/30 bg-purple-500/10"  },
  { fn: "MIN",            label: "MIN",    hint: "Minimum value",            cls: "text-amber-400  border-amber-500/30  bg-amber-500/10"   },
  { fn: "MAX",            label: "MAX",    hint: "Maximum value",            cls: "text-orange-400 border-orange-500/30 bg-orange-500/10"  },
  { fn: "MEDIAN",         label: "MEDIAN", hint: "50th percentile",          cls: "text-cyan-400   border-cyan-500/30   bg-cyan-500/10"    },
  { fn: "STDDEV",         label: "STDDEV", hint: "Standard deviation",       cls: "text-rose-400   border-rose-500/30   bg-rose-500/10"    },
  { fn: "VARIANCE",       label: "VAR",    hint: "Statistical variance",     cls: "text-pink-400   border-pink-500/30   bg-pink-500/10"    },
  { fn: "CUSTOM",         label: "Custom", hint: "Write your own expression",cls: "text-zinc-400   border-zinc-600      bg-zinc-700/30"    },
] as const;
type AggFn = typeof AGG_OPTIONS[number]["fn"];

const SQL_WORDS = [
  "SELECT","FROM","WHERE","GROUP BY","ORDER BY","HAVING","LIMIT","OFFSET","DISTINCT",
  "AS","JOIN","LEFT JOIN","INNER JOIN","FULL JOIN","ON","AND","OR","NOT",
  "IN","LIKE","ILIKE","BETWEEN","EXISTS","IS NULL","IS NOT NULL","UNION",
  "CASE WHEN","THEN","ELSE","END",
  "SUM","AVG","COUNT","COUNT DISTINCT","MIN","MAX","MEDIAN","STDDEV","VARIANCE",
  "PERCENTILE_CONT","COALESCE","NULLIF","CAST","IIF","ROUND","FLOOR","CEIL",
  "ABS","GREATEST","LEAST","LENGTH","TRIM","LOWER","UPPER","CONCAT","REPLACE",
  "SUBSTRING","DATE_TRUNC","DATE_DIFF","DATE_PART","EXTRACT","CURRENT_DATE",
  "CURRENT_TIMESTAMP","NOW","ROW_NUMBER","RANK","DENSE_RANK","LAG","LEAD",
  "OVER","PARTITION BY",
];

type FilterOp = "=" | "!=" | ">" | ">=" | "<" | "<=" | "LIKE" | "ILIKE" | "IN" | "IS NULL" | "IS NOT NULL";
const FILTER_OPS: FilterOp[] = ["=","!=",">",">=","<","<=","LIKE","ILIKE","IN","IS NULL","IS NOT NULL"];
const NO_VAL_OPS: FilterOp[] = ["IS NULL","IS NOT NULL"];

interface DimItem     { id: string; col: string; table: string }
interface MeasureItem { id: string; col: string; table: string; agg: AggFn; customExpr: string; alias: string; fromMetric?: string }
interface FilterItem  { id: string; col: string; table: string; op: FilterOp; val: string }

// ── Pure helpers ──────────────────────────────────────────────────────────────

let _s = 0;
const uid = () => `qb${++_s}`;

const NUM_T  = ["int","float","double","decimal","numeric","real","number","bigint","smallint","money","hugeint"];
const DATE_T = ["date","time","timestamp","datetime","interval"];
const isNum  = (t: string) => NUM_T.some(k  => t.toLowerCase().includes(k));
const isDate = (t: string) => DATE_T.some(k => t.toLowerCase().includes(k));
const dot    = (t: string) => isNum(t) ? "bg-emerald-500" : isDate(t) ? "bg-blue-400" : "bg-zinc-500";
const fmtMs  = (ms: number) => ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms/1000).toFixed(2)}s`;
const fmtN   = (n: number) => n.toLocaleString();

function autoAlias(agg: AggFn, col: string, expr: string) {
  return agg === "CUSTOM"
    ? (expr || col || "expr").replace(/[^a-zA-Z0-9_]/g,"_").toLowerCase().slice(0,32)
    : `${agg.toLowerCase().replace(/ /g,"_")}_${col||"all"}`;
}
function qualify(col: string, table: string, multi: boolean) { return multi ? `${table}.${col}` : col; }

// ── Suggestion intelligence (type + name heuristics) ──────────────────────────
// Columns that make natural GROUP BY dimensions.
const CATEGORICAL_HINT = /(channel|region|type|status|category|segment|name|country|state|city|gender|tier|group|method|source|stage|priority|currency|brand|department|role|plan|product|customer|account|industry|cohort|level|class|kind|label)/i;
// Numeric columns that are typically summed vs. averaged.
const AVG_HINT = /(rate|ratio|score|pct|percent|avg|average|margin|age|duration|days|temperature|index|weight|height|balance_pct)/i;
const SUM_HINT = /(revenue|amount|total|value|price|spend|cost|sales|qty|quantity|budget|profit|gmv|fee|sum|payment|charge|discount|tax|units)/i;
const suggestAgg = (name: string): AggFn => AVG_HINT.test(name) ? "AVG" : "SUM";
// Identifier-ish columns that rarely make good aggregates or dimensions on their own.
const isIdLike = (name: string) => /(^id$|_id$|_key$|uuid|guid|^pk_|hash)/i.test(name);
const fmtRows = (rc: string | number | null | undefined) => {
  if (rc == null || rc === "") return null;
  const n = typeof rc === "string" ? parseInt(rc.replace(/[^0-9]/g, ""), 10) : rc;
  if (!Number.isFinite(n)) return null;
  if (n >= 1e9) return `${(n/1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n/1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n/1e3).toFixed(1)}K`;
  return String(n);
};

function measureExpr(m: MeasureItem, multi: boolean) {
  const qc = qualify(m.col, m.table, multi);
  if (m.agg === "CUSTOM")          return m.customExpr || qc || "*";
  if (m.agg === "COUNT" && !m.col) return "COUNT(*)";
  if (m.agg === "COUNT DISTINCT")  return `COUNT(DISTINCT ${qc})`;
  return `${m.agg}(${qc || "*"})`;
}

// ── Join inference ────────────────────────────────────────────────────────────

function findJoin(from: string, to: string, joins: SchemaJoin[]): SchemaJoin | null {
  const exact = joins.find(j => j.match === "exact" && ((j.t1===from&&j.t2===to)||(j.t2===from&&j.t1===to)));
  if (exact) return exact;
  return joins.find(j => (j.t1===from&&j.t2===to)||(j.t2===from&&j.t1===to)) ?? null;
}

function joinClause(join: SchemaJoin, pivot: string) {
  const fwd = join.t1 === pivot;
  const [lt,lc,rt,rc] = fwd ? [join.t1,join.c1,join.t2,join.c2] : [join.t2,join.c2,join.t1,join.c1];
  return `LEFT JOIN ${rt} ON ${lt}.${lc} = ${rt}.${rc}`;
}

// Adjacency list over the studied join graph (undirected).
function buildAdjacency(joins: SchemaJoin[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => { if (!adj.has(a)) adj.set(a, new Set()); adj.get(a)!.add(b); };
  joins.forEach(j => { link(j.t1, j.t2); link(j.t2, j.t1); });
  return adj;
}

// How many distinct tables a given table can join to (relationship degree).
function joinDegree(table: string, joins: SchemaJoin[]): number {
  const s = new Set<string>();
  joins.forEach(j => { if (j.t1 === table) s.add(j.t2); if (j.t2 === table) s.add(j.t1); });
  return s.size;
}

// BFS the shortest path from any already-resolved table to `target`.
// Returns the ordered list of tables to ADD (intermediate hops + target), or null
// if `target` is unreachable from the resolved set.
function findJoinPath(resolved: Set<string>, target: string, joins: SchemaJoin[]): string[] | null {
  if (resolved.has(target)) return [];
  const adj = buildAdjacency(joins);
  const prev = new Map<string, string>();
  const seen = new Set<string>([target]);
  const queue: string[] = [target];
  let hit: string | null = null;
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nb of adj.get(cur) ?? []) {
      if (seen.has(nb)) continue;
      seen.add(nb); prev.set(nb, cur);
      if (resolved.has(nb)) { hit = nb; queue.length = 0; break; }
      queue.push(nb);
    }
  }
  if (!hit) return null;
  // Walk hit(resolved) → … → target via prev, then drop the resolved boundary node.
  const chain: string[] = [];
  let c: string | undefined = hit;
  while (c !== undefined) { chain.push(c); if (c === target) break; c = prev.get(c); }
  return chain.slice(1); // tables to add, ordered from the resolved boundary toward target
}

// Resolve the concrete join used for each joined table against the growing
// resolved set — shared by buildSql and the UI so both agree on multi-hop paths.
function resolveJoins(primary: string, joined: string[], joins: SchemaJoin[]) {
  const resolved = new Set([primary]);
  return joined.map(t => {
    let found: SchemaJoin | null = null, pivot = primary;
    for (const p of resolved) { const j = findJoin(p, t, joins); if (j) { found = j; pivot = p; break; } }
    resolved.add(t);
    return { table: t, join: found, pivot };
  });
}

// ── SQL builder ───────────────────────────────────────────────────────────────

function buildSql(
  primary: string, joined: string[], schemaJoins: SchemaJoin[],
  dims: DimItem[], measures: MeasureItem[], filters: FilterItem[],
  orderBy: string, limit: number,
) {
  const multi = joined.length > 0;
  const selParts = [
    ...dims.map(d => qualify(d.col, d.table, multi)),
    ...measures.map(m => `${measureExpr(m,multi)} AS ${m.alias || autoAlias(m.agg,m.col,m.customExpr)}`),
  ];
  const joinLines = resolveJoins(primary, joined, schemaJoins).map(
    ({ table, join, pivot }) => join ? joinClause(join, pivot) : `-- TODO: no join found for "${table}"`,
  );
  const hasAgg = measures.some(m => m.agg !== "CUSTOM" || /\b(SUM|COUNT|AVG|MIN|MAX|STDDEV|VARIANCE|MEDIAN)\s*\(/i.test(m.customExpr));
  const groupCols = dims.map(d => qualify(d.col,d.table,multi));
  const groupBy   = groupCols.length && hasAgg ? `GROUP BY ${groupCols.join(", ")}` : "";
  const whereItems = filters.flatMap(f => {
    const qc = qualify(f.col,f.table,multi);
    if (NO_VAL_OPS.includes(f.op as FilterOp)) return [`${qc} ${f.op}`];
    return f.val.trim() ? [`${qc} ${f.op} ${f.val}`] : [];
  });
  return [
    "SELECT", `  ${selParts.length ? selParts.join(",\n  ") : "*"}`,
    `FROM ${primary}`, ...joinLines,
    ...(whereItems.length ? [`WHERE ${whereItems.join("\n  AND ")}`] : []),
    ...(groupBy ? [groupBy] : []),
    ...(orderBy.trim() ? [`ORDER BY ${orderBy}`] : []),
    ...(limit > 0 ? [`LIMIT ${limit}`] : []),
  ].join("\n");
}

// ── Autocomplete ──────────────────────────────────────────────────────────────

function wordAtCursor(text: string, cursor: number) {
  let start = cursor;
  while (start > 0 && /[\w.]/.test(text[start-1])) start--;
  return { word: text.slice(start, cursor), start };
}

function getSuggestions(text: string, cursor: number, cols: string[], qcols: string[], tables: string[]) {
  const { word } = wordAtCursor(text, cursor);
  if (word.length < 2) return [];
  const lo = word.toLowerCase();
  const seen = new Set<string>();
  return [...SQL_WORDS, ...cols, ...qcols, ...tables]
    .filter(s => { const sl = s.toLowerCase(); if (!sl.startsWith(lo)||sl===lo||seen.has(s)) return false; seen.add(s); return true; })
    .slice(0, 9);
}

function caretPos(el: HTMLTextAreaElement): { top: number; left: number } {
  const cs  = window.getComputedStyle(el);
  const lh  = parseFloat(cs.lineHeight) || 18;
  const pt  = parseFloat(cs.paddingTop) || 0;
  const pl  = parseFloat(cs.paddingLeft) || 0;
  const cw  = (parseFloat(cs.fontSize) || 12) * 0.601;
  const rect = el.getBoundingClientRect();
  const cursor = el.selectionStart ?? el.value.length;
  const lines  = el.value.substring(0, cursor).split("\n");
  const row = lines.length - 1, col = lines[row].length;
  const logTop = pt + row * lh, logLeft = pl + Math.min(col * cw, el.clientWidth - 28);
  return {
    top:  rect.top  + logTop - el.scrollTop + lh + 5,
    left: Math.min(rect.left + logLeft, rect.right - 220),
  };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ColRow({ col, tableName, onAddDim, onAddMeasure }: {
  col: SchemaColumn; tableName: string; onAddDim: () => void; onAddMeasure: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={e => e.dataTransfer.setData("application/x-col",
        JSON.stringify({ name: col.name, type: col.type, table: tableName, is_fk: col.is_fk }))}
      className="group flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/60 cursor-grab active:cursor-grabbing select-none transition-colors"
    >
      <svg width="8" height="11" viewBox="0 0 8 14" className="text-zinc-500 group-hover:text-zinc-300 shrink-0 transition-colors">
        {[1,5,9,13].map(y=>[1,5].map(x=><circle key={`${x}${y}`} cx={x} cy={y} r="1.2" fill="currentColor"/>)).flat()}
      </svg>
      <span className={`w-2 h-2 rounded-full shrink-0 ${dot(col.type)}`} />
      <span className="text-[12px] font-mono text-zinc-200 truncate flex-1" title={`${col.name} (${col.type})`}>
        {col.name}
      </span>
      <span className="hidden group-hover:inline text-[11px] text-zinc-500 font-mono shrink-0 uppercase">
        {col.type.split(" ")[0].slice(0,6)}
      </span>
      {col.is_fk && <span className="text-[11px] text-zinc-500">FK</span>}
      <div className="hidden group-hover:flex gap-0.5 shrink-0">
        <button onMouseDown={e=>{e.stopPropagation();onAddDim();}} title="Add as dimension"
          className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-blue-500/20 text-blue-400 hover:bg-blue-500/40 transition">D</button>
        <button onMouseDown={e=>{e.stopPropagation();onAddMeasure();}} title="Add as metric"
          className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-violet-500/20 text-violet-400 hover:bg-violet-500/40 transition">M</button>
      </div>
    </div>
  );
}

function AggPicker({ col, table, onAdd, onCancel }: {
  col: SchemaColumn; table: string; onAdd: (m: MeasureItem) => void; onCancel: () => void;
}) {
  const defAgg: AggFn = isNum(col.type) ? "SUM" : "COUNT";
  const [agg, setAgg] = useState<AggFn>(defAgg);
  const [expr, setExpr] = useState(col.name);
  const [alias, setAlias] = useState(autoAlias(defAgg, col.name, col.name));
  const aliasEdited = useRef(false);
  const exprRef = useRef<HTMLInputElement>(null);

  const changeAgg = (fn: AggFn) => {
    setAgg(fn);
    if (!aliasEdited.current) setAlias(autoAlias(fn, col.name, expr));
  };
  useEffect(() => { if (agg === "CUSTOM") exprRef.current?.focus(); }, [agg]);

  const preview = measureExpr({ id:"", col: col.name, table, agg, customExpr: expr, alias }, false);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onCancel} />
      <div className="fixed z-50 rounded-md border border-zinc-600 bg-zinc-900 shadow-2xl p-6 w-[360px]"
        style={{ top:"50%", left:"50%", transform:"translate(-50%,-50%)" }}>
        <div className="flex items-start justify-between mb-5">
          <div>
            <p className="text-base font-semibold text-zinc-100">Configure Metric</p>
            <p className="text-[12px] font-mono text-zinc-500 mt-0.5">{table}.{col.name} · {col.type}</p>
          </div>
          <button onClick={onCancel} className="text-zinc-500 hover:text-zinc-300 text-lg p-0.5 leading-none">×</button>
        </div>

        <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2.5">Aggregation function</p>
        <div className="grid grid-cols-5 gap-2 mb-5">
          {AGG_OPTIONS.map(o => (
            <button key={o.fn} onClick={() => changeAgg(o.fn as AggFn)} title={o.hint}
              className={`py-2 text-[11px] font-medium rounded-lg border transition ${
                agg === o.fn ? `${o.cls} ring-2 ring-current/40` : "text-zinc-500 border-zinc-700 bg-zinc-800/50 hover:border-zinc-500 hover:text-zinc-300"
              }`}>
              {o.label}
            </button>
          ))}
        </div>

        {agg === "CUSTOM" && (
          <div className="mb-5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">SQL expression</p>
            <input ref={exprRef} value={expr} onChange={e => setExpr(e.target.value)}
              placeholder="e.g. ROUND(SUM(revenue) / COUNT(*), 2)"
              className="w-full text-[12px] font-mono bg-zinc-800 border border-zinc-600 rounded-md px-3 py-2.5 text-zinc-200 outline-none focus:border-zinc-400 transition" />
          </div>
        )}

        <div className="mb-5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Column alias</p>
          <input value={alias} onChange={e => { aliasEdited.current = true; setAlias(e.target.value); }}
            placeholder="metric_name"
            className="w-full text-[12px] font-mono bg-zinc-800 border border-zinc-600 rounded-md px-3 py-2.5 text-zinc-200 outline-none focus:border-zinc-400 transition" />
        </div>

        <div className="mb-6 px-4 py-3 rounded-md bg-zinc-800/70 border border-zinc-700/60">
          <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-1.5">SQL preview</p>
          <p className="text-[13px] font-mono text-emerald-400 break-all">
            {preview} <span className="text-zinc-500">AS</span> {alias || "alias"}
          </p>
        </div>

        <div className="flex gap-3 justify-end">
          <button onClick={onCancel}
            className="px-4 py-2 text-[13px] text-zinc-400 hover:text-zinc-200 border border-zinc-700 rounded-md transition">
            Cancel
          </button>
          <button
            onClick={() => onAdd({ id:uid(), col:col.name, table, agg, customExpr:expr, alias: alias||autoAlias(agg,col.name,expr) })}
            disabled={agg === "CUSTOM" && !expr.trim()}
            className="px-5 py-2 text-[13px] bg-blue-600 hover:bg-blue-500 text-white rounded-md font-semibold transition disabled:opacity-40">
            Add Metric
          </button>
        </div>
      </div>
    </>
  );
}

function AcDropdown({ items, active, setActive, onSelect, onClose, pos }: {
  items: string[]; active: number; pos: { top: number; left: number };
  setActive: (i: number) => void; onSelect: (s: string) => void; onClose: () => void;
}) {
  if (!items.length) return null;
  const flipUp = pos.top + items.length * 28 + 40 > (typeof window !== "undefined" ? window.innerHeight - 16 : 800);
  return (
    <>
      <div className="fixed inset-0 z-30" onMouseDown={onClose} />
      <div className="fixed z-50 min-w-[220px] max-w-[320px] rounded-md border border-zinc-600/90 bg-zinc-900 shadow-2xl overflow-hidden"
        style={{ top: flipUp ? pos.top - items.length * 28 - 40 : pos.top, left: pos.left }}>
        <div className="px-3 py-1.5 border-b border-zinc-700/50 flex items-center justify-between">
          <span className="text-[11px] text-zinc-500 font-medium">Suggestions</span>
          <span className="text-[11px] text-zinc-500">↑↓  ↵ insert  Esc</span>
        </div>
        {items.map((s, i) => (
          <button key={s}
            onMouseDown={e => { e.preventDefault(); onSelect(s); }}
            onMouseEnter={() => setActive(i)}
            className={`w-full text-left px-3 py-[7px] text-[12px] font-mono transition ${
              i === active ? "bg-blue-600/25 text-blue-200" : "text-zinc-300 hover:bg-zinc-800"
            }`}>{s}</button>
        ))}
      </div>
    </>
  );
}

function ResultsPane({ result }: { result: DirectQueryResult }) {
  const [view, setView] = useState<"chart" | "table">("chart");

  if (result.error) {
    return (
      <ChartWrapper error={result.error} empty={false}>
        <></>
      </ChartWrapper>
    );
  }

  if (!result.columns.length) {
    return (
      <ChartWrapper empty emptyMessage="Query returned no rows.">
        <></>
      </ChartWrapper>
    );
  }

  const rows = result.rows as unknown[][];
  const chartable = inferChartType(result.columns, rows);

  const meta = [
    `${result.row_count ?? result.rows.length} rows`,
    result.duration_ms != null ? `${result.duration_ms}ms` : null,
    result.cached ? "cached" : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-col gap-3">
      {/* View toggle */}
      {chartable && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => setView("chart")}
            className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${view === "chart" ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
          >
            ◈ Chart
          </button>
          <button
            onClick={() => setView("table")}
            className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${view === "table" ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
          >
            ≡ Table
          </button>
          <span className="text-[11px] ml-auto" style={{ color: "var(--t3)" }}>{meta}</span>
        </div>
      )}

      {/* Chart */}
      {view === "chart" && chartable && (
        <InvestigationChart columns={result.columns} rows={rows} />
      )}

      {/* Table — shared AugTable (sortable, themed, Σ Totals toggle) */}
      {(view === "table" || !chartable) && (
        <>
          {!chartable && (
            <span className="text-[11px] text-right" style={{ color: "var(--t3)" }}>{meta}</span>
          )}
          <SqlResultTable columns={result.columns} rows={rows} maxHeight={420} />
        </>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function QueryBuilder({ initialConnId }: { initialConnId?: string }) {
  const [connections,   setConnections]   = useState<Connection[]>([]);
  const [connId,        setConnId]        = useState(initialConnId ?? "");
  const [tableNames,    setTableNames]    = useState<string[]>([]);
  const [tableCols,     setTableCols]     = useState<Record<string,SchemaColumn[]>>({});
  const [rowCounts,     setRowCounts]     = useState<Record<string,string|null>>({});
  const [schemaJoins,   setSchemaJoins]   = useState<SchemaJoin[]>([]);
  const [isolated,      setIsolated]      = useState<string[]>([]);
  const [loadingTree,   setLoadingTree]   = useState(false);  // fast: catalog tree
  const [loadingCols,   setLoadingCols]   = useState(false);  // slow: columns/joins/rowcounts
  const [joinHint,      setJoinHint]      = useState<string|null>(null);

  const [primaryTable, setPrimaryTable] = useState<string|null>(null);
  const [joinedTables, setJoinedTables] = useState<string[]>([]);
  const [showAddJoin,  setShowAddJoin]  = useState(false);
  const [expandedTables, setExpandedTables] = useState<Record<string,boolean>>({});
  const [expandedSchemas, setExpandedSchemas] = useState<Record<string,boolean>>({});
  const [catEntry, setCatEntry] = useState<CatalogEntry|null>(null);
  const [allEntries, setAllEntries] = useState<CatalogEntry[]>([]);
  const [expandedConns, setExpandedConns] = useState<Record<string,boolean>>({});
  const [colSearch, setColSearch] = useState("");

  const [metrics,         setMetrics]         = useState<Metric[]>([]);
  const [showMetricsCatalog, setShowMetricsCatalog] = useState(false);

  const [dims,     setDims]     = useState<DimItem[]>([]);
  const [measures, setMeasures] = useState<MeasureItem[]>([]);
  const [filters,  setFilters]  = useState<FilterItem[]>([]);
  const [orderBy,  setOrderBy]  = useState("");
  const [limit,    setLimit]    = useState(1000);

  const [aggInfo,     setAggInfo]     = useState<{col:SchemaColumn;table:string}|null>(null);
  const [overDims,    setOverDims]    = useState(false);
  const [overMeasures,setOverMeasures]= useState(false);

  const [sql,     setSql]     = useState("");
  const [autoSql, setAutoSql] = useState(true);
  const sqlRef = useRef<HTMLTextAreaElement>(null);

  const [acItems,  setAcItems]  = useState<string[]>([]);
  const [acActive, setAcActive] = useState(0);
  const [acPos,    setAcPos]    = useState({top:0,left:0});

  const [running,  setRunning]  = useState(false);
  const [result,   setResult]   = useState<DirectQueryResult|null>(null);
  const [runError, setRunError] = useState<string|null>(null);
  const [useCache, setUseCache] = useState(false);

  const [showAddFilter, setShowAddFilter] = useState(false);
  const [nfTable, setNfTable] = useState("");
  const [nfCol,   setNfCol]   = useState("");
  const [nfOp,    setNfOp]    = useState<FilterOp>("=");
  const [nfVal,   setNfVal]   = useState("");

  useEffect(() => {
    getConnections().then(cs => { setConnections(cs); if (!connId && cs.length) setConnId(cs[0].id); }).catch(()=>{});
    getMetrics().then(setMetrics).catch(()=>{});
  }, []);

  useEffect(() => {
    if (!connId) return;
    setLoadingTree(true);
    setLoadingCols(true);
    setPrimaryTable(null); setJoinedTables([]); setTableNames([]); setTableCols({});
    setSchemaJoins([]); setDims([]); setMeasures([]); setFilters([]);
    setSql(""); setResult(null); setCatEntry(null); setExpandedSchemas({});

    // Phase 1 — fast: catalog tree gives us schema/table hierarchy immediately
    getCatalogTree()
      .then(tree => {
        const entries = tree.sections.flatMap(s => s.entries);
        setAllEntries(entries);
        const entry = entries.find(e => e.conn_id === connId) ?? null;
        setCatEntry(entry);
        // Active connection expanded by default; others collapsed.
        setExpandedConns(prev => ({ ...Object.fromEntries(entries.map(e => [e.conn_id, false])), ...prev, [connId]: true }));
        if (entry) {
          setExpandedSchemas(Object.fromEntries(entry.schemas.map(s => [s.name, true])));
          // seed table names so the hierarchy renders before getSchemaRich finishes
          setTableNames(entry.schemas.flatMap(s => s.tables.map(t => t.name)));
        }
      })
      .catch(() => setCatEntry(null))
      .finally(() => setLoadingTree(false));

    // Phase 2 — slower: rich schema adds columns, joins, row counts
    getSchemaRich(connId).then(rich => {
      const names = rich.tables.map(t => t.name);
      const cols: Record<string,SchemaColumn[]> = {};
      const rc: Record<string,string|null> = {};
      rich.tables.forEach(t => { cols[t.name] = t.columns; rc[t.name] = t.row_count; });
      setTableNames(names); setTableCols(cols); setRowCounts(rc);
      setSchemaJoins(rich.joins); setIsolated(rich.isolated ?? []);
    }).catch(()=>{}).finally(()=>setLoadingCols(false));
  }, [connId]);

  useEffect(() => {
    if (!autoSql || !primaryTable) return;
    setSql(buildSql(primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit));
  }, [autoSql, primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit]);

  const allTables = primaryTable ? [primaryTable, ...joinedTables] : [];
  const isMulti   = allTables.length > 1;
  const allCols   = allTables.flatMap(t => (tableCols[t]??[]).map(c => c.name));
  const qualCols  = isMulti ? allTables.flatMap(t => (tableCols[t]??[]).map(c => `${t}.${c.name}`)) : [];
  const joinStatuses = primaryTable ? resolveJoins(primaryTable, joinedTables, schemaJoins) : [];
  const joinableOptions = tableNames.filter(t => t !== primaryTable && !joinedTables.includes(t));

  // Catalog → Schema → Table grouping (mirrors the nav Catalog hierarchy).
  // Use the catalog tree's schema grouping when available; fall back to a single
  // synthetic schema built from the rich-schema table names.
  const tableSet = new Set(tableNames);
  const catSchemas: { name: string; tables: string[] }[] = catEntry
    ? catEntry.schemas
        .map(s => ({ name: s.name, tables: s.tables.map(t => t.name).filter(n => tableSet.has(n)) }))
        .filter(s => s.tables.length > 0)
    : [];
  // Any rich-schema tables not represented in the catalog tree fall into "main".
  const grouped = new Set(catSchemas.flatMap(s => s.tables));
  const ungrouped = tableNames.filter(t => !grouped.has(t));
  if (ungrouped.length) catSchemas.push({ name: catSchemas.length ? "other" : "main", tables: ungrouped });

  const flashHint = useCallback((msg: string) => {
    setJoinHint(msg);
    window.setTimeout(() => setJoinHint(h => (h === msg ? null : h)), 4500);
  }, []);

  const selectPrimary = useCallback((name: string) => {
    if (!name) return;
    setPrimaryTable(name); setJoinedTables([]); setExpandedTables({[name]: true});
    setDims([]); setMeasures([]); setFilters([]); setOrderBy("");
    setResult(null); setRunError(null); setAutoSql(true); setColSearch("");
    setSql(`SELECT *\nFROM ${name}\nLIMIT ${limit}`);
  }, [limit]);

  // Make `table` part of the query, auto-resolving a multi-hop join path through
  // the studied join graph. Returns true if the table is now reachable.
  const ensureTable = useCallback((table: string): boolean => {
    if (!table) return false;
    if (!primaryTable) { selectPrimary(table); return true; }
    if (table === primaryTable || joinedTables.includes(table)) return true;
    const resolved = new Set([primaryTable, ...joinedTables]);
    const path = findJoinPath(resolved, table, schemaJoins);
    if (path && path.length) {
      const toAdd = path.filter(t => t !== primaryTable && !joinedTables.includes(t));
      setJoinedTables(p => [...p, ...toAdd.filter(t => !p.includes(t))]);
      setExpandedTables(p => { const n = {...p}; toAdd.forEach(t => n[t] = true); return n; });
      setAutoSql(true);
      const hops = [primaryTable, ...joinedTables].slice(-1)[0];
      flashHint(toAdd.length > 1
        ? `Auto-joined ${table} via ${toAdd.slice(0, -1).join(" → ")} → ${table}`
        : `Auto-joined ${hops} → ${table}`);
      return true;
    }
    // Unreachable — add it anyway so the user can wire the join manually in SQL.
    setJoinedTables(p => p.includes(table) ? p : [...p, table]);
    setExpandedTables(p => ({...p, [table]: true}));
    setAutoSql(true);
    flashHint(`No join path to ${table} — add the ON clause manually in SQL`);
    return false;
  }, [primaryTable, joinedTables, schemaJoins, selectPrimary, flashHint]);

  const addJoin = useCallback((t: string) => { ensureTable(t); setShowAddJoin(false); }, [ensureTable]);

  const removeJoin = useCallback((t: string) => {
    setJoinedTables(p => p.filter(x=>x!==t));
    setDims(p     => p.filter(d=>d.table!==t));
    setMeasures(p => p.filter(m=>m.table!==t));
    setFilters(p  => p.filter(f=>f.table!==t));
  }, []);

  const addDim = useCallback((col: string, table: string) => {
    ensureTable(table);
    setDims(p => p.some(x => x.col===col && x.table===table) ? p : [...p, {id:uid(), col, table}]);
  }, [ensureTable]);

  const openMeasure = useCallback((col: SchemaColumn, table: string) => {
    ensureTable(table);
    setAggInfo({ col, table });
  }, [ensureTable]);

  const parseDrop = (e: React.DragEvent) => {
    try {
      const d = JSON.parse(e.dataTransfer.getData("application/x-col"));
      return { col: { name:d.name, type:d.type, is_fk:!!d.is_fk } as SchemaColumn, table: d.table||primaryTable||"" };
    } catch { return null; }
  };

  const onDropDims = (e: React.DragEvent) => {
    e.preventDefault(); setOverDims(false);
    const d = parseDrop(e);
    if (d) addDim(d.col.name, d.table);
  };

  const onDropMeasures = (e: React.DragEvent) => {
    e.preventDefault(); setOverMeasures(false);
    const d = parseDrop(e);
    if (d) openMeasure(d.col, d.table);
  };

  const handleSqlChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setSql(e.target.value); setAutoSql(false);
    const cursor = e.target.selectionStart ?? e.target.value.length;
    const items = getSuggestions(e.target.value, cursor, allCols, qualCols, tableNames);
    setAcItems(items); setAcActive(0);
    if (items.length) setAcPos(caretPos(e.target));
  };

  const insertSuggestion = useCallback((s: string) => {
    const ta = sqlRef.current; if (!ta) return;
    const cursor = ta.selectionStart ?? sql.length;
    const { word, start } = wordAtCursor(sql, cursor);
    const ns = sql.slice(0, start) + s + " " + sql.slice(cursor);
    setSql(ns); setAutoSql(false); setAcItems([]);
    const nc = start + s.length + 1;
    setTimeout(()=>{ ta.focus(); ta.setSelectionRange(nc,nc); }, 0);
  }, [sql]);

  const handleSqlKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (acItems.length) {
      if (e.key==="ArrowDown")  { e.preventDefault(); setAcActive(a=>Math.min(a+1,acItems.length-1)); return; }
      if (e.key==="ArrowUp")    { e.preventDefault(); setAcActive(a=>Math.max(a-1,0)); return; }
      if (e.key==="Tab"||e.key==="Enter") { e.preventDefault(); insertSuggestion(acItems[acActive]); return; }
      if (e.key==="Escape")     { setAcItems([]); return; }
    }
    if ((e.metaKey||e.ctrlKey)&&e.key==="Enter") { e.preventDefault(); triggerRun(); }
  };

  const runRef = useRef({sql,connId,limit,useCache});
  useEffect(()=>{ runRef.current={sql,connId,limit,useCache}; },[sql,connId,limit,useCache]);

  const triggerRun = async () => {
    const {sql:s,connId:c,limit:l,useCache:uc} = runRef.current;
    if (!s.trim()||!c) return;
    setRunning(true); setRunError(null); setResult(null); setAcItems([]);
    try { setResult(await runDirectQuery(c,s,l,{useCache:uc})); }
    catch(err) { setRunError(err instanceof Error ? err.message : "Query failed"); }
    finally { setRunning(false); }
  };

  const commitFilter = () => {
    if (!nfCol) return;
    setFilters(p => [...p, {id:uid(),col:nfCol,table:nfTable||primaryTable||"",op:nfOp,val:nfVal}]);
    setNfTable(""); setNfCol(""); setNfOp("="); setNfVal(""); setShowAddFilter(false);
  };

  // ── Suggestion intelligence (over the resolved tables) ────────────────────
  const usedDimKeys = new Set(dims.map(d => `${d.table}.${d.col}`));
  const usedMeaCols = new Set(measures.map(m => `${m.table}.${m.col}`));
  const resolvedCols = allTables.flatMap(t => (tableCols[t] ?? []).map(c => ({ ...c, table: t })));

  const suggestedDims = resolvedCols
    .filter(c => !usedDimKeys.has(`${c.table}.${c.name}`) && !c.is_fk && !isIdLike(c.name)
      && (isDate(c.type) || (!isNum(c.type) && CATEGORICAL_HINT.test(c.name))))
    .sort((a, b) => (isDate(b.type)?1:0) - (isDate(a.type)?1:0)) // dates first
    .slice(0, 6);

  const suggestedMetrics = resolvedCols
    .filter(c => isNum(c.type) && !c.is_fk && !isIdLike(c.name) && !usedMeaCols.has(`${c.table}.${c.name}`))
    .slice(0, 6)
    .map(c => ({ table: c.table, col: c.name, agg: suggestAgg(c.name) as AggFn }));

  const hasCount = measures.some(m => m.agg === "COUNT" && !m.col);
  // Joins can fan rows out across one-to-many relationships → aggregates may double-count.
  const fanOutRisk = isMulti && measures.some(m => m.agg !== "CUSTOM");

  const addMeasureDirect = (table: string, col: string, agg: AggFn) => {
    ensureTable(table);
    setMeasures(p => [...p, { id:uid(), col, table, agg, customExpr: col, alias: autoAlias(agg, col, col) }]);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg-0)" }}>

      {/* ══ HEADER ═══════════════════════════════════════════════════════════ */}
      <div className="flex items-center gap-3 px-5 h-14 border-b border-zinc-700/50 shrink-0 bg-zinc-900/50">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.6" strokeLinecap="round" className="shrink-0">
          <rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>
          <rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>
        </svg>
        <span className="text-[14px] font-semibold text-zinc-200">Query Builder</span>

        <div className="h-5 w-px bg-zinc-700/60 mx-1" />

        {/* Connection */}
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-zinc-500">Connection</span>
          <select value={connId} onChange={e=>setConnId(e.target.value)}
            className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1 text-zinc-200 outline-none hover:border-zinc-500 transition cursor-pointer">
            {connections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {/* Active table chips — populated automatically as fields are added */}
        {primaryTable ? (
          <div className="flex items-center gap-2 ml-1 min-w-0 overflow-x-auto">
            {allTables.map(t => {
              const isPrimary = t === primaryTable;
              const js = joinStatuses.find(s=>s.table===t);
              const found = isPrimary || !!js?.join;
              return (
                <span key={t} title={js?.join ? `${js.join.t1}.${js.join.c1} = ${js.join.t2}.${js.join.c2}` : undefined}
                  className={`flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-0.5 rounded-full border shrink-0 ${
                    isPrimary ? "bg-blue-500/10 border-blue-500/30 text-blue-300"
                    : found ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                            : "bg-amber-500/10  border-amber-500/30  text-amber-300"
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${isPrimary ? "bg-blue-400" : found ? "bg-emerald-400" : "bg-amber-400"}`} />
                  {t}
                  {!isPrimary && <button onClick={()=>removeJoin(t)} className="opacity-50 hover:opacity-100 ml-0.5 leading-none">×</button>}
                </span>
              );
            })}
          </div>
        ) : (
          <span className="text-[12px] text-zinc-500 ml-1">Drag a field from the catalog to begin</span>
        )}

        {/* Right controls */}
        <div className="ml-auto flex items-center gap-3">
          {!autoSql && (
            <button
              onClick={() => { setAutoSql(true); if (primaryTable) setSql(buildSql(primaryTable,joinedTables,schemaJoins,dims,measures,filters,orderBy,limit)); }}
              className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded-lg px-2.5 py-1 transition">
              ↺ Regenerate SQL
            </button>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={useCache} onChange={e=>setUseCache(e.target.checked)} className="w-3 h-3 accent-violet-500" />
            <span className="text-[11px] text-zinc-500">Cache</span>
          </label>
          <button onClick={triggerRun} disabled={running||!sql.trim()}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-[13px] font-semibold transition ${
              running ? "bg-zinc-700 text-zinc-400 cursor-not-allowed"
                      : "bg-blue-600 hover:bg-blue-500 text-white shadow-sm"
            }`}>
            {running
              ? <><span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>Running…</>
              : <><svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>Run</>
            }
          </button>
        </div>
      </div>

      {/* ══ BODY ═════════════════════════════════════════════════════════════ */}
      <ResizableSplit storageKey="builder" initial={320} min={220} max={520} className="flex-1 overflow-hidden"
        left={
        /* ── Left: Catalog browser (all tables, auto-join on drag) ── */
        <aside className="border-r border-zinc-700/40 flex flex-col bg-zinc-900/30 h-full w-full">
          {/* Header */}
          <div className="px-4 pt-4 pb-3 border-b border-zinc-700/30">
            <div className="flex items-center justify-between mb-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">Catalog</p>
              <span className="text-[11px] text-zinc-500">{tableNames.length} tables</span>
            </div>
            <div className="flex items-center gap-2 bg-zinc-800/70 border border-zinc-700 rounded-md px-3 py-2">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input placeholder="Search tables &amp; columns…" value={colSearch} onChange={e=>setColSearch(e.target.value)}
                className="bg-transparent text-[12px] text-zinc-300 outline-none placeholder-zinc-500 w-full" />
              {colSearch && <button onClick={()=>setColSearch("")} className="text-zinc-500 hover:text-zinc-400 leading-none">✕</button>}
            </div>
            {/* type legend */}
            <div className="flex items-center gap-3 mt-2.5">
              {[["bg-emerald-500","num"],["bg-blue-400","date"],["bg-zinc-500","text"]].map(([d,l])=>(
                <span key={l} className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                  <span className={`w-2 h-2 rounded-full ${d}`}/>{l}
                </span>
              ))}
              <span className="ml-auto text-[11px] text-zinc-500">drag to auto-join</span>
            </div>
          </div>

          {/* Catalog → Schema → Table → columns hierarchy */}
          <div className="flex-1 overflow-y-auto py-1">
            {loadingTree ? (
              <p className="text-[12px] text-zinc-500 px-4 py-4 animate-pulse">Loading catalog…</p>
            ) : tableNames.length === 0 ? (
              <p className="text-[12px] text-zinc-500 px-4 py-4">No tables in this connection.</p>
            ) : (() => {
              const q = colSearch.toLowerCase().trim();

              // Connection → schema → table → column hierarchy (all connections,
              // mirroring the big Catalog tab).  The active connection expands to
              // the full rich tree; others show a lightweight schema/table preview
              // and switch the builder to that connection on click.
              const dbIcon = (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.6" strokeLinecap="round" className="shrink-0">
                  <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>
                </svg>
              );
              const entries = allEntries.length ? allEntries : (catEntry ? [catEntry] : []);
              return (
                <div>
                  {entries.map(entry => {
                    const isActive = entry.conn_id === connId;
                    const connMatches = !q || entry.name.toLowerCase().includes(q)
                      || entry.schemas.some(s => s.name.toLowerCase().includes(q) || s.tables.some(t => t.name.toLowerCase().includes(q)));
                    if (q && !connMatches && !isActive) return null;
                    const cOpen = q ? connMatches : (expandedConns[entry.conn_id] ?? isActive);
                    return (
                      <div key={entry.conn_id} className="border-b-2 border-zinc-700/40 last:border-b-0">
                        {/* Connection row */}
                        <button
                          onClick={() => {
                            if (!isActive) { setConnId(entry.conn_id); setExpandedConns(p => ({ ...p, [entry.conn_id]: true })); }
                            else setExpandedConns(p => ({ ...p, [entry.conn_id]: !(p[entry.conn_id] ?? true) }));
                          }}
                          className={`w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/40 transition ${isActive ? "bg-zinc-800/30" : ""}`}>
                          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5" strokeLinecap="round"
                            className={`shrink-0 transition-transform duration-150 ${cOpen ? "rotate-90" : ""}`}>
                            <polyline points="2,1 6,4 2,7"/>
                          </svg>
                          {dbIcon}
                          <span className={`text-[12px] font-semibold truncate ${isActive ? "text-zinc-100" : "text-zinc-300"}`}>{entry.name}</span>
                          {isActive && <span className="ml-auto text-[9px] text-blue-400 shrink-0">active</span>}
                        </button>

                        {/* Active connection → full rich tree */}
                        {cOpen && isActive && (
                          <div className="ml-3 border-l-2 border-zinc-700/40">
                  {catSchemas.map(schema => {
                    const schemaMatch = !q || schema.name.toLowerCase().includes(q);
                    const visTables = schema.tables.filter(tbl =>
                      !q || schemaMatch || tbl.toLowerCase().includes(q)
                        || (tableCols[tbl]??[]).some(c => c.name.toLowerCase().includes(q)));
                    if (q && visTables.length === 0) return null;
                    const sOpen = q ? true : (expandedSchemas[schema.name] ?? true);
                    return (
                      <div key={schema.name} className="border-b border-zinc-700/25 last:border-b-0">
                        {/* Schema row */}
                        <button onClick={()=>setExpandedSchemas(p=>({...p,[schema.name]: !(p[schema.name] ?? true)}))}
                          className="w-full flex items-center gap-2 pl-3 pr-2 py-1.5 hover:bg-zinc-800/40 transition">
                          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5" strokeLinecap="round"
                            className={`shrink-0 transition-transform duration-150 ${sOpen?"rotate-90":""}`}>
                            <polyline points="2,1 6,4 2,7"/>
                          </svg>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.7" strokeLinecap="round" className="shrink-0">
                            <path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 12l9 4 9-4M3 17l9 4 9-4"/>
                          </svg>
                          <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-300 truncate">{schema.name}</span>
                        </button>

                        {/* Tables under schema */}
                        {sOpen && visTables.map(tbl => {
                          const tableMatch = !q || schemaMatch || tbl.toLowerCase().includes(q);
                          const cols = (tableCols[tbl]??[]).filter(c => !q || tableMatch || c.name.toLowerCase().includes(q));
                          const isPrimary  = tbl === primaryTable;
                          const isJoined   = joinedTables.includes(tbl);
                          const isResolved = isPrimary || isJoined;
                          const open  = q ? true : (expandedTables[tbl] ?? isResolved);
                          const js    = joinStatuses.find(s => s.table === tbl);
                          const deg   = joinDegree(tbl, schemaJoins);
                          const rc    = fmtRows(rowCounts[tbl]);
                          const iso   = isolated.includes(tbl);
                          return (
                            <div key={tbl} className={isResolved ? "bg-zinc-800/20" : ""}>
                              <div className="group/tbl w-full flex items-center gap-2 pl-7 pr-2 py-1.5 hover:bg-zinc-800/40 transition">
                                <button onClick={()=>setExpandedTables(p=>({...p,[tbl]: !(p[tbl] ?? isResolved)}))}
                                  className="flex items-center gap-2 min-w-0 flex-1">
                                  <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5" strokeLinecap="round"
                                    className={`shrink-0 transition-transform duration-150 ${open?"rotate-90":""}`}>
                                    <polyline points="2,1 6,4 2,7"/>
                                  </svg>
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={isResolved?"var(--t1)":"var(--t2)"} strokeWidth="1.7" strokeLinecap="round" className="shrink-0">
                                    <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="9" x2="9" y2="21"/>
                                  </svg>
                                  <span className={`text-[12px] font-mono truncate ${isResolved ? "text-zinc-100 font-semibold" : "text-zinc-200"}`}>{tbl}</span>
                                  {rc && <span className="text-[10px] text-zinc-500 shrink-0">{rc}</span>}
                                </button>
                                {deg > 0 && (
                                  <span title={`${deg} related table${deg>1?"s":""}`} className="hidden sm:flex items-center gap-0.5 text-[10px] text-zinc-500 shrink-0">
                                    ⋈{deg}
                                  </span>
                                )}
                                {isPrimary ? (
                                  <span className="text-[10px] text-blue-400 shrink-0 font-medium">primary</span>
                                ) : isJoined ? (
                                  <span title={js?.join ? `${js.join.t1}.${js.join.c1} = ${js.join.t2}.${js.join.c2}` : "no join — wire in SQL"}
                                    className={`text-[11px] shrink-0 ${js?.join ? "text-emerald-500" : "text-amber-500"}`}>{js?.join ? "✓" : "⚠"}</span>
                                ) : iso ? (
                                  <span title="No detected joins to other tables" className="text-[10px] text-zinc-500 shrink-0">isolated</span>
                                ) : (
                                  <button onClick={()=>ensureTable(tbl)} title="Add to query (auto-join)"
                                    className="opacity-0 group-hover/tbl:opacity-100 text-[11px] text-zinc-500 hover:text-blue-400 border border-zinc-700 hover:border-blue-500/50 rounded px-1.5 leading-tight transition shrink-0">
                                    + add
                                  </button>
                                )}
                              </div>
                              {open && (
                                loadingCols && cols.length === 0
                                  ? <div className="pl-11 py-1.5"><span className="text-[11px] text-zinc-500 animate-pulse">Loading columns…</span></div>
                                  : cols.map(col => (
                                    <div key={col.name} className="pl-4">
                                      <ColRow col={col} tableName={tbl}
                                        onAddDim={()=>addDim(col.name, tbl)}
                                        onAddMeasure={()=>openMeasure(col, tbl)}
                                      />
                                    </div>
                                  ))
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                          </div>
                        )}

                        {/* Inactive connection → lightweight schema/table preview */}
                        {cOpen && !isActive && entry.schemas.map(schema => {
                          const sMatch = !q || schema.name.toLowerCase().includes(q);
                          const visT = schema.tables.filter(t => !q || sMatch || t.name.toLowerCase().includes(q));
                          if (q && visT.length === 0) return null;
                          const sKey = `${entry.conn_id}:${schema.name}`;
                          const sOpen = q ? true : (expandedSchemas[sKey] ?? false);
                          return (
                            <div key={schema.name}>
                              <button onClick={() => setExpandedSchemas(p => ({ ...p, [sKey]: !(p[sKey] ?? false) }))}
                                className="w-full flex items-center gap-2 pl-3 pr-2 py-1.5 hover:bg-zinc-800/40 transition">
                                <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5" strokeLinecap="round"
                                  className={`shrink-0 transition-transform duration-150 ${sOpen ? "rotate-90" : ""}`}>
                                  <polyline points="2,1 6,4 2,7"/>
                                </svg>
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.7" strokeLinecap="round" className="shrink-0">
                                  <path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 12l9 4 9-4M3 17l9 4 9-4"/>
                                </svg>
                                <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400 truncate">{schema.name}</span>
                                <span className="ml-auto text-[10px] text-zinc-500 shrink-0">{visT.length}</span>
                              </button>
                              {sOpen && visT.map(t => (
                                <button key={t.name} onClick={() => { setConnId(entry.conn_id); setExpandedConns(p => ({ ...p, [entry.conn_id]: true })); }}
                                  title={`Switch to ${entry.name} to query ${t.name}`}
                                  className="group/pt w-full flex items-center gap-2 pl-7 pr-2 py-1.5 hover:bg-zinc-800/40 transition">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--t2)" strokeWidth="1.7" strokeLinecap="round" className="shrink-0">
                                    <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="9" x2="9" y2="21"/>
                                  </svg>
                                  <span className="text-[12px] font-mono text-zinc-300 truncate">{t.name}</span>
                                  {t.row_count != null && <span className="text-[10px] text-zinc-500 shrink-0">{fmtRows(String(t.row_count))}</span>}
                                  <span className="ml-auto opacity-0 group-hover/pt:opacity-100 text-[10px] text-blue-400 shrink-0">open →</span>
                                </button>
                              ))}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              );
            })()}
          </div>
        </aside>
        }
        right={
        <main className="flex-1 overflow-y-auto h-full">

          {/* ── BUILDER (always rendered once a connection is loaded) ── */}
          {(
            <div className="px-6 py-5 space-y-6">

              {/* Onboarding prompt — until the first field is dropped */}
              {!primaryTable && (
                <div className="flex items-center gap-3 rounded-md border border-zinc-700/50 bg-zinc-800/30 px-4 py-3">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.5" strokeLinecap="round" className="shrink-0">
                    <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
                    <rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>
                  </svg>
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-zinc-300">Drag a field from the catalog to begin</p>
                    <p className="text-[11px] text-zinc-500 mt-0.5">Drop columns into Dimensions or Metrics below. Fields from related tables join automatically along the studied schema relationships.</p>
                  </div>
                </div>
              )}

              {/* Auto-join hint */}
              {joinHint && (
                <div className="flex items-center gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-[12px] text-blue-200">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="shrink-0">
                    <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
                  </svg>
                  <span className="font-mono">{joinHint}</span>
                  <button onClick={()=>setJoinHint(null)} className="ml-auto opacity-60 hover:opacity-100 leading-none">×</button>
                </div>
              )}

              {/* Join status */}
              {joinStatuses.length > 0 && (
                <div className="rounded-md border border-zinc-700/50 bg-zinc-800/30 px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Resolved joins · {allTables.length} tables</p>
                    {fanOutRisk && (
                      <span title="One-to-many joins can repeat rows from the parent table, inflating SUM/COUNT. Verify the aggregation grain."
                        className="flex items-center gap-1 text-[11px] text-amber-400/90 border border-amber-500/30 bg-amber-500/5 rounded px-1.5 py-0.5">
                        ⚠ joins may fan out rows
                      </span>
                    )}
                  </div>
                  {joinStatuses.map(({table, join, pivot}) => (
                    <div key={table} className="flex items-center gap-2 text-[11px] font-mono">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${join?"bg-emerald-400":"bg-red-400"}`}/>
                      <span className="text-zinc-500">{join ? pivot : primaryTable}</span>
                      <span className="text-zinc-500">→</span>
                      <span className="text-zinc-300">{table}</span>
                      {join ? (
                        <>
                          <span className="text-zinc-500 mx-1">ON</span>
                          <span className="text-emerald-400">{join.t1}.{join.c1} = {join.t2}.{join.c2}</span>
                          <span className={`ml-auto text-[11px] px-1.5 py-0.5 rounded border ${
                            join.match==="exact" ? "text-emerald-600 border-emerald-700/50 bg-emerald-500/5"
                                                 : "text-amber-600  border-amber-700/50  bg-amber-500/5"
                          }`}>{join.match}</span>
                        </>
                      ) : <span className="text-red-400 ml-2 italic">no join found — add ON clause manually in SQL</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Suggested fields */}
              {primaryTable && (suggestedDims.length > 0 || suggestedMetrics.length > 0 || !hasCount) && (
                <div className="rounded-md border border-zinc-700/40 bg-zinc-800/20 px-4 py-3">
                  <div className="flex items-center gap-2 mb-2.5">
                    <span className="text-violet-400 text-[12px]">✦</span>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Suggested</p>
                    <span className="text-[11px] text-zinc-500">one-click add, based on column types &amp; relationships</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {!hasCount && (
                      <button onClick={()=>setMeasures(p=>[...p,{id:uid(),col:"",table:primaryTable,agg:"COUNT",customExpr:"",alias:"row_count"}])}
                        className="inline-flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded border border-violet-500/30 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 transition">
                        <span className="opacity-70">M</span> COUNT(*)
                      </button>
                    )}
                    {suggestedMetrics.map(s => (
                      <button key={`m-${s.table}.${s.col}`} onClick={()=>addMeasureDirect(s.table, s.col, s.agg)}
                        title={`${s.agg}(${isMulti?`${s.table}.`:""}${s.col})`}
                        className="inline-flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded border border-violet-500/30 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 transition">
                        <span className="opacity-70">{s.agg}</span> {s.col}
                      </button>
                    ))}
                    {suggestedDims.map(s => (
                      <button key={`d-${s.table}.${s.name}`} onClick={()=>addDim(s.name, s.table)}
                        title={`Group by ${isMulti?`${s.table}.`:""}${s.name}`}
                        className="inline-flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition">
                        <span className={`w-1.5 h-1.5 rounded-full ${dot(s.type)}`}/> {s.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Dimensions + Metrics */}
              <div className="grid grid-cols-2 gap-5">

                {/* DIMENSIONS */}
                <div>
                  <div className="mb-3">
                    <p className="text-[13px] font-semibold text-zinc-300">Dimensions</p>
                    <p className="text-[11px] text-zinc-500 mt-0.5">GROUP BY — drag from left or click D</p>
                  </div>
                  <div
                    onDragOver={e=>{e.preventDefault();setOverDims(true);}}
                    onDragLeave={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setOverDims(false);}}
                    onDrop={onDropDims}
                    className={`min-h-[120px] rounded-md border-2 border-dashed p-4 flex flex-wrap gap-2 items-start content-start transition-all ${
                      overDims ? "border-blue-500 bg-blue-500/5 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]"
                               : "border-zinc-600 bg-zinc-800/10 hover:border-zinc-500"
                    }`}
                  >
                    {dims.length === 0 && (
                      <div className={`w-full flex flex-col items-center justify-center py-4 gap-2 ${overDims?"text-blue-400":"text-zinc-500"}`}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M12 5v14M5 12l7 7 7-7"/>
                        </svg>
                        <p className="text-[12px] italic">{overDims ? "Release to add dimension" : "Drop columns here"}</p>
                      </div>
                    )}
                    {dims.map(d => (
                      <span key={d.id} className="inline-flex items-center gap-1.5 text-[12px] font-mono px-2.5 py-1 rounded-lg border bg-blue-500/10 border-blue-500/30 text-blue-300">
                        {isMulti ? `${d.table}.${d.col}` : d.col}
                        <button onClick={()=>setDims(p=>p.filter(x=>x.id!==d.id))} className="opacity-50 hover:opacity-100 text-sm leading-none">×</button>
                      </span>
                    ))}
                  </div>
                </div>

                {/* METRICS */}
                <div>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <p className="text-[13px] font-semibold text-zinc-300">Metrics</p>
                      <p className="text-[11px] text-zinc-500 mt-0.5">Aggregations — drag from left or click M</p>
                    </div>
                    {metrics.length > 0 && (
                      <div className="relative">
                        <button onClick={()=>setShowMetricsCatalog(v=>!v)}
                          className="text-[11px] px-2.5 py-1 rounded-lg border border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300 transition whitespace-nowrap">
                          📊 Catalog
                        </button>
                        {showMetricsCatalog && (
                          <>
                            <div className="fixed inset-0 z-30" onClick={()=>setShowMetricsCatalog(false)}/>
                            <div className="absolute right-0 top-full mt-2 z-40 w-68 rounded-md border border-zinc-700 bg-zinc-900 shadow-2xl overflow-hidden min-w-[260px]">
                              <div className="px-4 py-2.5 border-b border-zinc-700/50">
                                <p className="text-[11px] font-semibold text-zinc-400">Metrics Catalog</p>
                              </div>
                              {metrics.map(m => (
                                <button key={m.name}
                                  onClick={()=>{setMeasures(p=>[...p,{id:uid(),col:"",table:primaryTable??"",agg:"CUSTOM",customExpr:m.sql,alias:m.name,fromMetric:m.name}]);setShowMetricsCatalog(false);}}
                                  className="w-full text-left px-4 py-3 hover:bg-zinc-800/70 transition border-b border-zinc-700/30 last:border-0">
                                  <p className="text-[12px] font-semibold text-zinc-200">{m.label}</p>
                                  <p className="text-[11px] font-mono text-zinc-500 truncate mt-0.5">{m.sql}</p>
                                </button>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div
                    onDragOver={e=>{e.preventDefault();setOverMeasures(true);}}
                    onDragLeave={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setOverMeasures(false);}}
                    onDrop={onDropMeasures}
                    className={`min-h-[120px] rounded-md border-2 border-dashed p-4 flex flex-wrap gap-2 items-start content-start transition-all ${
                      overMeasures ? "border-violet-500 bg-violet-500/5 shadow-[0_0_0_1px_rgba(139,92,246,0.2)]"
                                   : "border-zinc-600 bg-zinc-800/10 hover:border-zinc-500"
                    }`}
                  >
                    {measures.length === 0 && (
                      <div className={`w-full flex flex-col items-center justify-center py-4 gap-2 ${overMeasures?"text-violet-400":"text-zinc-500"}`}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M12 5v14M5 12l7 7 7-7"/>
                        </svg>
                        <p className="text-[12px] italic">{overMeasures ? "Release to configure metric" : "Drop columns here"}</p>
                      </div>
                    )}
                    {measures.map(m => {
                      const ao = AGG_OPTIONS.find(o=>o.fn===m.agg);
                      return (
                        <span key={m.id} title={`${measureExpr(m,isMulti)} AS ${m.alias}`}
                          className={`inline-flex items-center gap-1.5 text-[12px] font-mono px-2.5 py-1 rounded-lg border ${ao?.cls??"text-violet-300 border-violet-500/30 bg-violet-500/10"}`}>
                          <span className="text-[11px] font-sans opacity-70">{m.fromMetric?"📊":m.agg==="CUSTOM"?"fx":m.agg}</span>
                          <span className="max-w-[120px] truncate">{m.alias||measureExpr(m,isMulti)}</span>
                          <button onClick={()=>setMeasures(p=>p.filter(x=>x.id!==m.id))} className="opacity-50 hover:opacity-100 text-sm leading-none">×</button>
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Filters / ordering / SQL / results need a resolved table */}
              {primaryTable && (<>

              {/* FILTERS */}
              <div className="border-t border-zinc-700/30 pt-5">
                <p className="text-[13px] font-semibold text-zinc-300 mb-1">Filters</p>
                <p className="text-[11px] text-zinc-500 mb-3">WHERE — narrow down your results</p>
                <div className="flex flex-wrap gap-2 items-center min-h-[36px]">
                  {filters.map(f => (
                    <span key={f.id} className="inline-flex items-center gap-1.5 text-[12px] font-mono px-3 py-1 rounded-lg border bg-amber-500/10 border-amber-500/30 text-amber-300">
                      {NO_VAL_OPS.includes(f.op) ? `${qualify(f.col,f.table,isMulti)} ${f.op}` : `${qualify(f.col,f.table,isMulti)} ${f.op} ${f.val}`}
                      <button onClick={()=>setFilters(p=>p.filter(x=>x.id!==f.id))} className="opacity-50 hover:opacity-100 text-sm leading-none">×</button>
                    </span>
                  ))}
                  {showAddFilter ? (
                    <div className="flex items-center gap-2 flex-wrap p-3 rounded-md border border-zinc-700/60 bg-zinc-800/30">
                      {isMulti && (
                        <select value={nfTable} onChange={e=>setNfTable(e.target.value)}
                          className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                          <option value="">table</option>
                          {allTables.map(t=><option key={t} value={t}>{t}</option>)}
                        </select>
                      )}
                      <select value={nfCol} onChange={e=>setNfCol(e.target.value)}
                        className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                        <option value="">column</option>
                        {(isMulti&&nfTable ? tableCols[nfTable]??[] : allTables.flatMap(t=>tableCols[t]??[])).map(c=>(
                          <option key={c.name} value={c.name}>{c.name}</option>
                        ))}
                      </select>
                      <select value={nfOp} onChange={e=>setNfOp(e.target.value as FilterOp)}
                        className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                        {FILTER_OPS.map(op=><option key={op} value={op}>{op}</option>)}
                      </select>
                      {!NO_VAL_OPS.includes(nfOp) && (
                        <input value={nfVal} onChange={e=>setNfVal(e.target.value)}
                          onKeyDown={e=>{if(e.key==="Enter")commitFilter();}} placeholder="value" autoFocus
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 w-32 transition" />
                      )}
                      <button onClick={commitFilter} className="px-3 py-1.5 text-[12px] rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 font-medium transition">Add</button>
                      <button onClick={()=>setShowAddFilter(false)} className="text-[12px] text-zinc-500 hover:text-zinc-300 px-1.5 transition">Cancel</button>
                    </div>
                  ) : (
                    <button onClick={()=>setShowAddFilter(true)}
                      className="flex items-center gap-1.5 text-[12px] border border-dashed border-zinc-700 rounded-lg px-3 py-1.5 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300 transition">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                      </svg>
                      Add filter
                    </button>
                  )}
                </div>
              </div>

              {/* ORDER BY + LIMIT */}
              <div className="border-t border-zinc-700/30 pt-5 flex items-end gap-6">
                <div>
                  <p className="text-[12px] text-zinc-500 mb-2">ORDER BY</p>
                  <input value={orderBy} onChange={e=>setOrderBy(e.target.value)}
                    placeholder="e.g. total_revenue DESC"
                    className="text-[12px] font-mono bg-zinc-800/60 border border-zinc-700 rounded-md px-3 py-2 text-zinc-200 outline-none focus:border-zinc-500 w-56 transition" />
                </div>
                <div>
                  <p className="text-[12px] text-zinc-500 mb-2">LIMIT</p>
                  <input type="number" min={1} max={50000} value={limit} onChange={e=>setLimit(parseInt(e.target.value)||1000)}
                    className="text-[12px] font-mono bg-zinc-800/60 border border-zinc-700 rounded-md px-3 py-2 text-zinc-200 outline-none focus:border-zinc-500 w-24 transition" />
                </div>
              </div>

              {/* SQL EDITOR */}
              <div className="border-t border-zinc-700/30 pt-5">
                <div className="flex items-center gap-3 mb-3">
                  <p className="text-[13px] font-semibold text-zinc-300">SQL</p>
                  {!autoSql && (
                    <span className="text-[11px] text-amber-500/80 border border-amber-500/20 bg-amber-500/5 rounded-md px-1.5 py-0.5">
                      manually edited
                    </span>
                  )}
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-[11px] text-zinc-500">⌘↵ to run</span>
                    <button onClick={()=>navigator.clipboard.writeText(sql).catch(()=>{})}
                      className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded-lg px-2.5 py-1 transition">
                      Copy
                    </button>
                  </div>
                </div>
                <div className="relative">
                  <textarea
                    ref={sqlRef}
                    value={sql}
                    onChange={handleSqlChange}
                    onKeyDown={handleSqlKeyDown}
                    onClick={()=>setAcItems([])}
                    spellCheck={false}
                    rows={Math.max(6, Math.min(16, sql.split("\n").length + 2))}
                    placeholder={"SELECT *\nFROM table\nLIMIT 1000"}
                    className="w-full text-[12px] leading-relaxed bg-zinc-900/80 border border-zinc-700 rounded-md p-4 text-zinc-200 outline-none focus:border-zinc-500 resize-none transition"
                    style={{ fontFamily: "var(--font-mono)" }}
                  />
                </div>
              </div>

              {/* RESULTS */}
              {(running || runError || result) && (
                <div className="border-t border-zinc-700/30 pt-5 pb-6">
                  <div className="flex items-center gap-3 mb-3">
                    <p className="text-[13px] font-semibold text-zinc-300">Results</p>
                    {result && !result.error && (
                      <span className="text-[12px] text-zinc-400">
                        {fmtN(result.row_count)} rows · {fmtMs(result.duration_ms)}
                        {result.cached && <span className="ml-2 text-[11px] text-violet-400 border border-violet-500/30 rounded-md px-1.5 py-0.5">cached</span>}
                      </span>
                    )}
                  </div>
                  {running && (
                    <div className="flex items-center gap-2 py-8 justify-center text-zinc-500">
                      <span className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-400 rounded-full animate-spin"/>
                      <span className="text-[12px]">Running query…</span>
                    </div>
                  )}
                  {runError && !running && (
                    <div className="p-4 rounded-md border border-red-500/20 bg-red-500/5">
                      <p className="text-[12px] font-mono text-red-400">{runError}</p>
                    </div>
                  )}
                  {result && !running && <ResultsPane result={result} />}
                </div>
              )}
              {!result && !running && !runError && (
                <p className="text-[12px] text-zinc-500 italic pb-4">Configure your query above, then click <strong className="text-zinc-500 font-normal">Run</strong> or press <kbd className="text-zinc-500 bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[11px]">⌘↵</kbd></p>
              )}

              </>)}
            </div>
          )}
        </main>
        }
      />

      {/* ══ CURSOR-ANCHORED AUTOCOMPLETE ═════════════════════════════════════ */}
      <AcDropdown items={acItems} active={acActive} setActive={setAcActive}
        onSelect={insertSuggestion} onClose={()=>setAcItems([])} pos={acPos} />

      {/* ══ AGGPICKER MODAL ══════════════════════════════════════════════════ */}
      {aggInfo && (
        <AggPicker col={aggInfo.col} table={aggInfo.table}
          onAdd={m=>{setMeasures(p=>[...p,m]);setAggInfo(null);}}
          onCancel={()=>setAggInfo(null)} />
      )}
    </div>
  );
}
