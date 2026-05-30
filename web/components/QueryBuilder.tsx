"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  getConnections, getSchemaRich, getMetrics, runDirectQuery,
  type Connection, type SchemaColumn, type SchemaJoin, type Metric, type DirectQueryResult,
} from "@/lib/api";

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
  const resolved = new Set([primary]);
  const joinLines: string[] = [];
  for (const t of joined) {
    let found: SchemaJoin | null = null, pivot = primary;
    for (const p of resolved) { const j = findJoin(p,t,schemaJoins); if (j){found=j;pivot=p;break;} }
    joinLines.push(found ? joinClause(found,pivot) : `-- TODO: no join found for "${t}"`);
    resolved.add(t);
  }
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
        JSON.stringify({ name: col.name, type: col.type, table: tableName }))}
      className="group flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/60 cursor-grab active:cursor-grabbing select-none transition-colors"
    >
      <svg width="8" height="11" viewBox="0 0 8 14" className="text-zinc-700 group-hover:text-zinc-500 shrink-0 transition-colors">
        {[1,5,9,13].map(y=>[1,5].map(x=><circle key={`${x}${y}`} cx={x} cy={y} r="1.2" fill="currentColor"/>)).flat()}
      </svg>
      <span className={`w-2 h-2 rounded-full shrink-0 ${dot(col.type)}`} />
      <span className="text-[12px] font-mono text-zinc-300 truncate flex-1" title={`${col.name} (${col.type})`}>
        {col.name}
      </span>
      <span className="hidden group-hover:inline text-[11px] text-zinc-600 font-mono shrink-0 uppercase">
        {col.type.split(" ")[0].slice(0,6)}
      </span>
      {col.is_fk && <span className="text-[11px] text-zinc-600">FK</span>}
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
          <span className="text-[11px] text-zinc-700">↑↓  ↵ insert  Esc</span>
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

function ResultsTable({ result }: { result: DirectQueryResult }) {
  if (result.error) return (
    <div className="p-4 rounded-md border border-red-500/20 bg-red-500/5">
      <p className="text-[12px] font-mono text-red-400 whitespace-pre-wrap">{result.error}</p>
    </div>
  );
  if (!result.columns.length) return <p className="text-sm text-zinc-500 italic py-4">Query returned no rows.</p>;
  return (
    <div className="overflow-auto rounded-md border border-zinc-700/60">
      <table className="min-w-full text-[12px] font-mono">
        <thead>
          <tr className="bg-zinc-800/70">
            {result.columns.map((c,i) => (
              <th key={i} className="text-left px-4 py-2.5 text-zinc-400 font-semibold border-b border-zinc-700/50 whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row,ri) => (
            <tr key={ri} className={ri%2 ? "bg-zinc-800/20" : ""}>
              {row.map((cell,ci) => (
                <td key={ci} title={cell} className="px-4 py-2 text-zinc-300 border-b border-zinc-700/20 whitespace-nowrap max-w-[240px] truncate">
                  {cell === "NULL" ? <span className="text-zinc-600">null</span> : cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function QueryBuilder({ initialConnId }: { initialConnId?: string }) {
  const [connections,   setConnections]   = useState<Connection[]>([]);
  const [connId,        setConnId]        = useState(initialConnId ?? "");
  const [tableNames,    setTableNames]    = useState<string[]>([]);
  const [tableCols,     setTableCols]     = useState<Record<string,SchemaColumn[]>>({});
  const [schemaJoins,   setSchemaJoins]   = useState<SchemaJoin[]>([]);
  const [loadingSchema, setLoadingSchema] = useState(false);

  const [primaryTable, setPrimaryTable] = useState<string|null>(null);
  const [joinedTables, setJoinedTables] = useState<string[]>([]);
  const [showAddJoin,  setShowAddJoin]  = useState(false);
  const [expandedTables, setExpandedTables] = useState<Record<string,boolean>>({});
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
    setLoadingSchema(true);
    setPrimaryTable(null); setJoinedTables([]); setTableNames([]); setTableCols({});
    setSchemaJoins([]); setDims([]); setMeasures([]); setFilters([]);
    setSql(""); setResult(null);
    getSchemaRich(connId).then(rich => {
      const names = rich.tables.map(t => t.name);
      const cols: Record<string,SchemaColumn[]> = {};
      rich.tables.forEach(t => { cols[t.name] = t.columns; });
      setTableNames(names); setTableCols(cols); setSchemaJoins(rich.joins);
    }).catch(()=>{}).finally(()=>setLoadingSchema(false));
  }, [connId]);

  useEffect(() => {
    if (!autoSql || !primaryTable) return;
    setSql(buildSql(primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit));
  }, [autoSql, primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit]);

  const allTables = primaryTable ? [primaryTable, ...joinedTables] : [];
  const isMulti   = allTables.length > 1;
  const allCols   = allTables.flatMap(t => (tableCols[t]??[]).map(c => c.name));
  const qualCols  = isMulti ? allTables.flatMap(t => (tableCols[t]??[]).map(c => `${t}.${c.name}`)) : [];
  const joinStatuses = joinedTables.map(t => ({ table: t, join: findJoin(primaryTable ?? "", t, schemaJoins) }));
  const joinableOptions = tableNames.filter(t => t !== primaryTable && !joinedTables.includes(t));

  const selectPrimary = useCallback((name: string) => {
    if (!name) return;
    setPrimaryTable(name); setJoinedTables([]); setExpandedTables({[name]: true});
    setDims([]); setMeasures([]); setFilters([]); setOrderBy("");
    setResult(null); setRunError(null); setAutoSql(true); setColSearch("");
    setSql(`SELECT *\nFROM ${name}\nLIMIT ${limit}`);
  }, [limit]);

  const addJoin = useCallback((t: string) => {
    setJoinedTables(p => [...p, t]);
    setExpandedTables(p => ({...p, [t]: true}));
    setShowAddJoin(false);
  }, []);

  const removeJoin = useCallback((t: string) => {
    setJoinedTables(p => p.filter(x=>x!==t));
    setDims(p     => p.filter(d=>d.table!==t));
    setMeasures(p => p.filter(m=>m.table!==t));
    setFilters(p  => p.filter(f=>f.table!==t));
  }, []);

  const parseDrop = (e: React.DragEvent) => {
    try {
      const d = JSON.parse(e.dataTransfer.getData("application/x-col"));
      return { col: { name:d.name, type:d.type, is_fk:false } as SchemaColumn, table: d.table||primaryTable||"" };
    } catch { return null; }
  };

  const onDropDims = (e: React.DragEvent) => {
    e.preventDefault(); setOverDims(false);
    const d = parseDrop(e);
    if (d) setDims(p => p.some(x=>x.col===d.col.name&&x.table===d.table) ? p : [...p, {id:uid(),col:d.col.name,table:d.table}]);
  };

  const onDropMeasures = (e: React.DragEvent) => {
    e.preventDefault(); setOverMeasures(false);
    const d = parseDrop(e);
    if (d) setAggInfo(d);
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

        {/* Table */}
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-zinc-500">Table</span>
          <select value={primaryTable??""} onChange={e=>selectPrimary(e.target.value)}
            className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1 text-zinc-200 outline-none hover:border-zinc-500 transition cursor-pointer">
            <option value="">— select —</option>
            {tableNames.map(t=><option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        {/* Joined table badges + add join */}
        {primaryTable && (
          <div className="flex items-center gap-2 ml-1">
            {joinedTables.map(t => {
              const js = joinStatuses.find(s=>s.table===t);
              const found = !!js?.join;
              return (
                <span key={t} className={`flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-0.5 rounded-full border ${
                  found ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                        : "bg-amber-500/10  border-amber-500/30  text-amber-300"
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${found ? "bg-emerald-400" : "bg-amber-400"}`} />
                  {t}
                  <button onClick={()=>removeJoin(t)} className="opacity-50 hover:opacity-100 ml-0.5 leading-none">×</button>
                </span>
              );
            })}
            {joinableOptions.length > 0 && (
              <div className="relative">
                <button onClick={()=>setShowAddJoin(v=>!v)}
                  className="flex items-center gap-1.5 text-[11px] text-zinc-400 hover:text-zinc-200 border border-dashed border-zinc-600 rounded-full px-2.5 py-0.5 transition hover:border-zinc-400">
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                  </svg>
                  Join table
                </button>
                {showAddJoin && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={()=>setShowAddJoin(false)} />
                    <div className="absolute top-full left-0 mt-2 z-40 w-56 rounded-md border border-zinc-700 bg-zinc-900 shadow-2xl overflow-hidden">
                      <div className="px-4 py-2.5 border-b border-zinc-700/40">
                        <p className="text-[11px] font-semibold text-zinc-400">Add table to query</p>
                      </div>
                      {joinableOptions.map(t => {
                        const j = findJoin(primaryTable, t, schemaJoins);
                        return (
                          <button key={t} onClick={()=>addJoin(t)}
                            className="w-full text-left px-4 py-2.5 hover:bg-zinc-800 transition border-b border-zinc-700/30 last:border-0">
                            <div className="flex items-center gap-2">
                              <span className={`w-2 h-2 rounded-full shrink-0 ${j?"bg-emerald-400":"bg-amber-400"}`}/>
                              <span className="text-[12px] text-zinc-200 font-mono">{t}</span>
                            </div>
                            <p className="text-[11px] text-zinc-500 mt-0.5 ml-4">
                              {j ? `${j.t1}.${j.c1} = ${j.t2}.${j.c2}` : "no join detected"}
                            </p>
                          </button>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
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
      <div className="flex flex-1 overflow-hidden">

        {/* ── Left: Column browser ── */}
        <aside className="w-72 shrink-0 border-r border-zinc-700/40 flex flex-col bg-zinc-900/30">
          {/* Header */}
          <div className="px-4 pt-4 pb-3 border-b border-zinc-700/30">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2.5">Schema columns</p>
            <div className="flex items-center gap-2 bg-zinc-800/70 border border-zinc-700 rounded-md px-3 py-2">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input placeholder="Search columns…" value={colSearch} onChange={e=>setColSearch(e.target.value)}
                className="bg-transparent text-[12px] text-zinc-300 outline-none placeholder-zinc-600 w-full" />
              {colSearch && <button onClick={()=>setColSearch("")} className="text-zinc-600 hover:text-zinc-400 leading-none">✕</button>}
            </div>
            {/* type legend */}
            <div className="flex items-center gap-3 mt-2.5">
              {[["bg-emerald-500","num"],["bg-blue-400","date"],["bg-zinc-500","text"]].map(([d,l])=>(
                <span key={l} className="flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <span className={`w-2 h-2 rounded-full ${d}`}/>{l}
                </span>
              ))}
              <span className="ml-auto text-[11px] text-zinc-700">drag or D / M</span>
            </div>
          </div>

          {/* Column list */}
          <div className="flex-1 overflow-y-auto py-1">
            {loadingSchema ? (
              <p className="text-[12px] text-zinc-600 px-4 py-4 animate-pulse">Loading schema…</p>
            ) : !primaryTable ? (
              <p className="text-[12px] text-zinc-600 px-4 py-4">Select a table in the header to browse columns</p>
            ) : (
              allTables.map(tbl => {
                const cols = (tableCols[tbl]??[]).filter(c=>c.name.toLowerCase().includes(colSearch.toLowerCase()));
                const open = expandedTables[tbl] !== false;
                const js   = joinStatuses.find(s=>s.table===tbl);
                return (
                  <div key={tbl} className="border-b border-zinc-700/20 last:border-0">
                    <button
                      onClick={()=>setExpandedTables(p=>({...p,[tbl]:!p[tbl]}))}
                      className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-zinc-800/30 transition">
                      <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t4)" strokeWidth="1.5" strokeLinecap="round"
                        className={`shrink-0 transition-transform duration-150 ${open?"rotate-90":""}`}>
                        <polyline points="2,1 6,4 2,7"/>
                      </svg>
                      <span className="text-[12px] font-semibold text-zinc-300 font-mono truncate">{tbl}</span>
                      {tbl === primaryTable && <span className="ml-auto text-[11px] text-zinc-600 shrink-0">primary</span>}
                      {tbl !== primaryTable && (
                        js?.join
                          ? <span className="ml-auto text-[11px] text-emerald-600 shrink-0">✓</span>
                          : <span className="ml-auto text-[11px] text-amber-600 shrink-0">⚠</span>
                      )}
                    </button>
                    {open && cols.map(col => (
                      <ColRow key={col.name} col={col} tableName={tbl}
                        onAddDim={()=>setDims(p=>p.some(d=>d.col===col.name&&d.table===tbl)?p:[...p,{id:uid(),col:col.name,table:tbl}])}
                        onAddMeasure={()=>setAggInfo({col,table:tbl})}
                      />
                    ))}
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* ── Right: Builder + SQL + Results ── */}
        <main className="flex-1 overflow-y-auto">

          {/* ── EMPTY STATE ── */}
          {!primaryTable && (
            <div className="flex flex-col items-center justify-center h-full gap-6 text-center px-8">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="1" strokeLinecap="round">
                <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
                <rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>
              </svg>
              <div>
                <p className="text-lg font-medium text-zinc-300 mb-2">Select a table to start building</p>
                <p className="text-sm text-zinc-500 max-w-sm">Use the Table dropdown above, then drag columns from the left panel into Dimensions or Metrics zones</p>
              </div>
              <div className="flex items-center gap-4 text-[12px] text-zinc-600">
                <div className="flex flex-col items-center gap-1.5">
                  <span className="w-8 h-8 rounded-lg bg-zinc-800 border border-zinc-700 flex items-center justify-center text-zinc-400 font-semibold">1</span>
                  Select table
                </div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="1.5" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12,5 19,12 12,19"/></svg>
                <div className="flex flex-col items-center gap-1.5">
                  <span className="w-8 h-8 rounded-lg bg-zinc-800 border border-zinc-700 flex items-center justify-center text-zinc-400 font-semibold">2</span>
                  Drag columns
                </div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="1.5" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12,5 19,12 12,19"/></svg>
                <div className="flex flex-col items-center gap-1.5">
                  <span className="w-8 h-8 rounded-lg bg-zinc-800 border border-zinc-700 flex items-center justify-center text-zinc-400 font-semibold">3</span>
                  Run query
                </div>
              </div>
            </div>
          )}

          {/* ── BUILDER ── */}
          {primaryTable && (
            <div className="px-6 py-5 space-y-6">

              {/* Join status */}
              {joinStatuses.length > 0 && (
                <div className="rounded-md border border-zinc-700/50 bg-zinc-800/30 px-4 py-3 space-y-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600">Detected joins</p>
                  {joinStatuses.map(({table, join}) => (
                    <div key={table} className="flex items-center gap-2 text-[11px] font-mono">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${join?"bg-emerald-400":"bg-red-400"}`}/>
                      <span className="text-zinc-400">{primaryTable}</span>
                      <span className="text-zinc-600">→</span>
                      <span className="text-zinc-400">{table}</span>
                      {join ? (
                        <>
                          <span className="text-zinc-600 mx-1">ON</span>
                          <span className="text-emerald-400">{join.t1}.{join.c1} = {join.t2}.{join.c2}</span>
                          <span className={`ml-auto text-[11px] px-1.5 py-0.5 rounded border ${
                            join.match==="exact" ? "text-emerald-600 border-emerald-700/50 bg-emerald-500/5"
                                                 : "text-amber-600  border-amber-700/50  bg-amber-500/5"
                          }`}>{join.match}</span>
                        </>
                      ) : <span className="text-red-400 ml-2 italic">no join found — add manually in SQL</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Dimensions + Metrics */}
              <div className="grid grid-cols-2 gap-5">

                {/* DIMENSIONS */}
                <div>
                  <div className="mb-3">
                    <p className="text-[13px] font-semibold text-zinc-300">Dimensions</p>
                    <p className="text-[11px] text-zinc-600 mt-0.5">GROUP BY — drag from left or click D</p>
                  </div>
                  <div
                    onDragOver={e=>{e.preventDefault();setOverDims(true);}}
                    onDragLeave={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setOverDims(false);}}
                    onDrop={onDropDims}
                    className={`min-h-[120px] rounded-md border-2 border-dashed p-4 flex flex-wrap gap-2 items-start content-start transition-all ${
                      overDims ? "border-blue-500 bg-blue-500/5 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]"
                               : "border-zinc-700/70 bg-zinc-800/10 hover:border-zinc-600"
                    }`}
                  >
                    {dims.length === 0 && (
                      <div className={`w-full flex flex-col items-center justify-center py-4 gap-2 ${overDims?"text-blue-400":"text-zinc-600"}`}>
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
                      <p className="text-[11px] text-zinc-600 mt-0.5">Aggregations — drag from left or click M</p>
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
                                  onClick={()=>{setMeasures(p=>[...p,{id:uid(),col:"",table:primaryTable,agg:"CUSTOM",customExpr:m.sql,alias:m.name,fromMetric:m.name}]);setShowMetricsCatalog(false);}}
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
                                   : "border-zinc-700/70 bg-zinc-800/10 hover:border-zinc-600"
                    }`}
                  >
                    {measures.length === 0 && (
                      <div className={`w-full flex flex-col items-center justify-center py-4 gap-2 ${overMeasures?"text-violet-400":"text-zinc-600"}`}>
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

              {/* FILTERS */}
              <div className="border-t border-zinc-700/30 pt-5">
                <p className="text-[13px] font-semibold text-zinc-300 mb-1">Filters</p>
                <p className="text-[11px] text-zinc-600 mb-3">WHERE — narrow down your results</p>
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
                    <span className="text-[11px] text-zinc-600">⌘↵ to run</span>
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
                  {result && !running && <ResultsTable result={result} />}
                </div>
              )}
              {!result && !running && !runError && (
                <p className="text-[12px] text-zinc-600 italic pb-4">Configure your query above, then click <strong className="text-zinc-500 font-normal">Run</strong> or press <kbd className="text-zinc-500 bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[11px]">⌘↵</kbd></p>
              )}

            </div>
          )}
        </main>
      </div>

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
