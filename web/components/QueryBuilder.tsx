"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { compactNumber } from "@/lib/format";
import {
  getConnections, getSchemaRich, getTableColumns, getMetrics, runDirectQuery, getCatalogTree,
  createCanvas, suggestCanvasName, getMeasureGrains, getColumnDistinct,
  listSavedQueries, createSavedQuery, updateSavedQuery, deleteSavedQuery,
  type Connection, type SchemaColumn, type SchemaJoin, type Metric, type DirectQueryResult,
  type CatalogEntry, type SavedQuery,
} from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import { type ChartCustom } from "@/components/Chart";
import { ResizableSplit } from "@/components/ResizableSplit";
import { SqlResultTable } from "@/components/AugTable";
import { ChartWrapper }       from "@/components/charts/ChartWrapper";
import { inferChartType, availableTypesFor, type ChartType } from "@/components/charts/chartTypeInference";

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

interface DimItem     { id: string; col: string; table: string; transform?: "date" | "month" | "year" | "quarter" | "hour" | "minute" }
interface MeasureItem { id: string; col: string; table: string; agg: AggFn; customExpr: string; alias: string; fromMetric?: string }
interface FilterItem  { id: string; col: string; table: string; op: FilterOp; val: string }
// HAVING — a filter on an aggregate (references a measure, compiles to its aggregate expression).
interface HavingItem  { id: string; measureId: string; op: string; val: string }
const HAVING_OPS = [">", ">=", "<", "<=", "=", "!="];

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

// Quote a (possibly already schema-qualified) table identifier. A table name can arrive
// dotted ("analytics.order_items") straight from the rich schema, or bare ("order_items")
// with the schema known separately. Quote EACH dotted segment — wrapping the whole dotted
// string in one pair of quotes ("analytics.order_items") makes the engine read it as a single
// identifier and fail with "table does not exist" (the beautycommerce builder bug).
function quoteTable(name: string, schema?: string): string {
  if (name.includes(".")) return name.split(".").map(p => `"${p}"`).join(".");
  return schema && schema !== "main" && schema !== "public" ? `"${schema}"."${name}"` : `"${name}"`;
}

// The rich schema returns schema-qualified table names ("analytics.order_items") while the
// catalog tree uses bare names ("order_items") + a separate schema, so the two never key-match
// and the bare catalog rows can't find their columns/joins. Strip the prefix to one canonical
// bare key (quote-time qualification is restored via quoteTable + the tableSchemas map).
function bareTable(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1) : name;
}
function tableSchemaOf(name: string): string | undefined {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(0, i) : undefined;
}

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
  return compactNumber(n, 1);
};

function measureExpr(m: MeasureItem, multi: boolean) {
  const qc = qualify(m.col, m.table, multi);
  if (m.agg === "CUSTOM")          return m.customExpr || qc || "*";
  if (m.agg === "COUNT" && !m.col) return "COUNT(*)";
  if (m.agg === "COUNT DISTINCT")  return `COUNT(DISTINCT ${qc})`;
  return `${m.agg}(${qc || "*"})`;
}

// ── Measure-grain (additivity) warnings ───────────────────────────────────────
// Driven by the connection's detected per-unit/per-line grains — mirrors the backend
// measure_grain_misuse at the chip level. Catches the $252M-class under-count (SUM a
// per-unit price without ×quantity) and the per-line × quantity double-count.
const _esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function grainWarning(m: MeasureItem, grains: Record<string, string>, qtyCols: string[]): string | null {
  // Structured SUM of a per-unit measure without ×quantity → under-counts.
  if (m.agg === "SUM" && m.col && grains[m.col.toLowerCase()] === "per_unit") {
    return `"${m.col}" is a per-unit value — SUM(${m.col}) under-counts by the units per line. Multiply by quantity.`;
  }
  // CUSTOM expression: per-line × quantity (double-count) or a bare SUM of a per-unit measure.
  if (m.agg === "CUSTOM" && m.customExpr) {
    const e = m.customExpr.toLowerCase();
    for (const [col, g] of Object.entries(grains)) {
      const c = _esc(col);
      if (g === "per_line") {
        const mulQty = qtyCols.some(q => {
          const qq = _esc(q.toLowerCase());
          return new RegExp(`\\b${c}\\b\\s*\\*\\s*\\b${qq}\\b|\\b${qq}\\b\\s*\\*\\s*\\b${c}\\b`).test(e);
        });
        if (mulQty && /\bsum\s*\(/.test(e)) return `"${col}" is a per-line total — multiplying by quantity double-counts. Use SUM(${col}) alone.`;
      }
      if (g === "per_unit" && new RegExp(`sum\\s*\\(\\s*${c}\\s*\\)`).test(e)) {
        return `"${col}" is a per-unit value — SUM(${col}) under-counts. Multiply by quantity.`;
      }
    }
  }
  return null;
}

// ── Join inference ────────────────────────────────────────────────────────────

function findJoin(from: string, to: string, joins: SchemaJoin[]): SchemaJoin | null {
  const exact = joins.find(j => j.match === "exact" && ((j.t1===from&&j.t2===to)||(j.t2===from&&j.t1===to)));
  if (exact) return exact;
  return joins.find(j => (j.t1===from&&j.t2===to)||(j.t2===from&&j.t1===to)) ?? null;
}

function joinClause(join: SchemaJoin, pivot: string, tableSchemas?: Record<string, string>) {
  const fwd = join.t1 === pivot;
  const [lt,lc,rt,rc] = fwd ? [join.t1,join.c1,join.t2,join.c2] : [join.t2,join.c2,join.t1,join.c1];
  const qTable = (t: string) => quoteTable(t, tableSchemas?.[t]);
  return `LEFT JOIN ${qTable(rt)} ON ${qTable(lt)}.${lc} = ${qTable(rt)}.${rc}`;
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

// ── Time controls ─────────────────────────────────────────────────────────────
// A first-class time range (relative presets + custom) and time grain — the two most-used
// controls in real BI, previously buried in a per-dimension transform dropdown.

type TimePreset = "all"|"7d"|"30d"|"90d"|"this_month"|"last_month"|"this_quarter"|"this_year"|"ytd"|"custom";
type TimeGrain  = "none"|"hour"|"day"|"week"|"month"|"quarter"|"year";

interface TimeSpec { col: string; table: string; preset: TimePreset; from: string; to: string; grain: TimeGrain }

const TIME_PRESETS: { id: TimePreset; label: string }[] = [
  { id: "all",          label: "All time" },
  { id: "7d",           label: "Last 7 days" },
  { id: "30d",          label: "Last 30 days" },
  { id: "90d",          label: "Last 90 days" },
  { id: "this_month",   label: "This month" },
  { id: "last_month",   label: "Last month" },
  { id: "this_quarter", label: "This quarter" },
  { id: "this_year",    label: "This year" },
  { id: "ytd",          label: "Year to date" },
  { id: "custom",       label: "Custom range" },
];
const TIME_GRAINS: TimeGrain[] = ["none", "hour", "day", "week", "month", "quarter", "year"];

// Build a WHERE predicate for a relative/custom range on `col` (DuckDB/ANSI INTERVAL syntax).
// Returns "" for "all" or an incomplete custom range. Pure + testable (no DB, no React).
function timePredicate(preset: TimePreset, col: string, from: string, to: string): string {
  switch (preset) {
    case "7d":           return `${col} >= CURRENT_DATE - INTERVAL '7 days'`;
    case "30d":          return `${col} >= CURRENT_DATE - INTERVAL '30 days'`;
    case "90d":          return `${col} >= CURRENT_DATE - INTERVAL '90 days'`;
    case "this_month":   return `${col} >= DATE_TRUNC('month', CURRENT_DATE)`;
    case "last_month":   return `${col} >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AND ${col} < DATE_TRUNC('month', CURRENT_DATE)`;
    case "this_quarter": return `${col} >= DATE_TRUNC('quarter', CURRENT_DATE)`;
    case "this_year":
    case "ytd":          return `${col} >= DATE_TRUNC('year', CURRENT_DATE)`;
    case "custom": {
      const parts: string[] = [];
      if (from.trim()) parts.push(`${col} >= '${from.trim()}'`);
      if (to.trim())   parts.push(`${col} < '${to.trim()}'`);
      return parts.join(" AND ");
    }
    default: return "";
  }
}

// ── SQL builder ───────────────────────────────────────────────────────────────

function buildSql(
  primary: string, joined: string[], schemaJoins: SchemaJoin[],
  dims: DimItem[], measures: MeasureItem[], filters: FilterItem[],
  orderBy: string, limit: number,
  tableSchemas?: Record<string, string>,
  time?: TimeSpec,
  having: HavingItem[] = [],
) {
  const qTable = (t: string) => quoteTable(t, tableSchemas?.[t]);
  const multi = joined.length > 0;
  const dimExpr = (d: DimItem) => {
    const base = qualify(d.col, d.table, multi);
    switch (d.transform) {
      case "date":     return `DATE_TRUNC('day', ${base})`;
      case "month":    return `DATE_TRUNC('month', ${base})`;
      case "year":     return `DATE_TRUNC('year', ${base})`;
      case "quarter":  return `DATE_TRUNC('quarter', ${base})`;
      case "hour":     return `DATE_TRUNC('hour', ${base})`;
      case "minute":   return `DATE_TRUNC('minute', ${base})`;
      default:         return base;
    }
  };
  // Time grain — a DATE_TRUNC over the chosen time column, rendered as the leading dimension.
  const timeBase = time?.col ? qualify(time.col, time.table, multi) : "";
  const timeGrainExpr = (time && time.grain !== "none" && timeBase) ? `DATE_TRUNC('${time.grain}', ${timeBase})` : "";
  const selParts = [
    ...(timeGrainExpr ? [`${timeGrainExpr} AS ${time!.col}_${time!.grain}`] : []),
    ...dims.map(d => `${dimExpr(d)} AS ${d.col}_grouped`),
    ...measures.map(m => `${measureExpr(m,multi)} AS ${m.alias || autoAlias(m.agg,m.col,m.customExpr)}`),
  ];
  const joinLines = resolveJoins(primary, joined, schemaJoins).map(
    ({ table, join, pivot }) => join ? joinClause(join, pivot, tableSchemas) : `-- TODO: no join found for "${table}"`,
  );
  const hasAgg = measures.some(m => m.agg !== "CUSTOM" || /\b(SUM|COUNT|AVG|MIN|MAX|STDDEV|VARIANCE|MEDIAN)\s*\(/i.test(m.customExpr));
  const groupCols = [
    ...(timeGrainExpr ? [timeGrainExpr] : []),
    ...dims.map(d => dimExpr(d)),
  ];
  const groupBy   = groupCols.length && hasAgg ? `GROUP BY ${groupCols.join(", ")}` : "";
  const whereItems = filters.flatMap(f => {
    const qc = qualify(f.col,f.table,multi);
    if (NO_VAL_OPS.includes(f.op as FilterOp)) return [`${qc} ${f.op}`];
    return f.val.trim() ? [`${qc} ${f.op} ${f.val}`] : [];
  });
  const timeWhere = time && timeBase ? timePredicate(time.preset, timeBase, time.from, time.to) : "";
  const allWhere = timeWhere ? [...whereItems, timeWhere] : whereItems;
  // HAVING — filters on aggregates, compiled from each having item's referenced measure expression.
  const havingItems = (having || []).flatMap(h => {
    const m = measures.find(x => x.id === h.measureId);
    return (m && h.val.trim()) ? [`${measureExpr(m, multi)} ${h.op} ${h.val}`] : [];
  });
  const havingClause = havingItems.length && hasAgg ? `HAVING ${havingItems.join("\n  AND ")}` : "";
  return [
    "SELECT", `  ${selParts.length ? selParts.join(",\n  ") : "*"}`,
    `FROM ${qTable(primary)}`, ...joinLines,
    ...(allWhere.length ? [`WHERE ${allWhere.join("\n  AND ")}`] : []),
    ...(groupBy ? [groupBy] : []),
    ...(havingClause ? [havingClause] : []),
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

// ── SQL syntax highlighting + formatting ──────────────────────────────────────
// A tiny SQL tokenizer shared by the highlighter and the formatter. Strings and quoted
// identifiers are tokenized FIRST so the formatter never uppercases a keyword inside a
// literal (which would change the query) — casing/whitespace stay semantically inert.

const _SQL_KW = new Set([
  "SELECT","FROM","WHERE","GROUP","BY","ORDER","HAVING","LIMIT","OFFSET","DISTINCT","AS","JOIN",
  "LEFT","RIGHT","INNER","FULL","OUTER","CROSS","ON","AND","OR","NOT","IN","LIKE","ILIKE","BETWEEN",
  "EXISTS","IS","NULL","UNION","ALL","CASE","WHEN","THEN","ELSE","END","ASC","DESC","WITH","OVER",
  "PARTITION","USING","INTERVAL","CURRENT_DATE","CURRENT_TIMESTAMP","DAY","MONTH","YEAR","QUARTER","HOUR","WEEK","MINUTE",
]);
const _SQL_FN = new Set([
  "SUM","AVG","COUNT","MIN","MAX","MEDIAN","STDDEV","VARIANCE","DATE_TRUNC","DATE_DIFF","DATE_PART",
  "EXTRACT","COALESCE","NULLIF","CAST","ROUND","FLOOR","CEIL","ABS","GREATEST","LEAST","LENGTH","TRIM",
  "LOWER","UPPER","CONCAT","REPLACE","SUBSTRING","ROW_NUMBER","RANK","DENSE_RANK","LAG","LEAD","PERCENTILE_CONT","NOW",
]);

interface SqlTok { t: "kw" | "fn" | "string" | "ident" | "num" | "comment" | "punct" | "word" | "ws"; v: string }

function tokenizeSql(sql: string): SqlTok[] {
  const toks: SqlTok[] = [];
  const n = sql.length;
  let i = 0;
  while (i < n) {
    const c = sql[i];
    if (c === "-" && sql[i + 1] === "-") { let j = i + 2; while (j < n && sql[j] !== "\n") j++; toks.push({ t: "comment", v: sql.slice(i, j) }); i = j; continue; }
    if (c === "/" && sql[i + 1] === "*") { let j = i + 2; while (j < n && !(sql[j] === "*" && sql[j + 1] === "/")) j++; j = Math.min(n, j + 2); toks.push({ t: "comment", v: sql.slice(i, j) }); i = j; continue; }
    if (c === "'") { let j = i + 1; while (j < n) { if (sql[j] === "'") { if (sql[j + 1] === "'") { j += 2; continue; } j++; break; } j++; } toks.push({ t: "string", v: sql.slice(i, j) }); i = j; continue; }
    if (c === '"') { let j = i + 1; while (j < n) { if (sql[j] === '"') { if (sql[j + 1] === '"') { j += 2; continue; } j++; break; } j++; } toks.push({ t: "ident", v: sql.slice(i, j) }); i = j; continue; }
    if (/\s/.test(c)) { let j = i + 1; while (j < n && /\s/.test(sql[j])) j++; toks.push({ t: "ws", v: sql.slice(i, j) }); i = j; continue; }
    if (/[A-Za-z_]/.test(c)) { let j = i + 1; while (j < n && /[A-Za-z0-9_]/.test(sql[j])) j++; const w = sql.slice(i, j); const up = w.toUpperCase(); toks.push({ t: _SQL_KW.has(up) ? "kw" : _SQL_FN.has(up) ? "fn" : "word", v: w }); i = j; continue; }
    if (/[0-9]/.test(c)) { let j = i + 1; while (j < n && /[0-9.]/.test(sql[j])) j++; toks.push({ t: "num", v: sql.slice(i, j) }); i = j; continue; }
    let j = i + 1; while (j < n && /[^\w\s'"]/.test(sql[j]) && !(sql[j] === "-" && sql[j + 1] === "-") && !(sql[j] === "/" && sql[j + 1] === "*")) j++;
    toks.push({ t: "punct", v: sql.slice(i, j) }); i = j;
  }
  return toks;
}

const _escHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const _SQL_COLOR: Record<SqlTok["t"], string> = {
  kw: "#7dd3fc", fn: "#c4b5fd", string: "#86efac", num: "#fbbf24",
  comment: "#71717a", ident: "#fdba74", punct: "#a1a1aa", word: "#e4e4e7", ws: "",
};
function highlightSql(sql: string): string {
  return tokenizeSql(sql).map(tok => {
    const v = _escHtml(tok.v);
    const col = _SQL_COLOR[tok.t];
    return col ? `<span style="color:${col}">${v}</span>` : v;
  }).join("");
}

// Major clauses start a new line; AND/OR get an indented continuation line. Only whitespace
// and keyword CASE change — the SQL stays semantically identical.
const _SQL_NEWLINE = new Set(["SELECT","FROM","WHERE","GROUP","ORDER","HAVING","LIMIT","UNION","LEFT","RIGHT","INNER","FULL","CROSS","JOIN","ON"]);
const _SQL_INDENT  = new Set(["AND","OR"]);
function formatSql(sql: string): string {
  const toks = tokenizeSql(sql.trim());
  let out = "";
  for (let k = 0; k < toks.length; k++) {
    const tok = toks[k];
    if (tok.t === "ws") {
      const next = toks[k + 1];
      const up = next && next.t === "kw" ? next.v.toUpperCase() : "";
      out += up && _SQL_NEWLINE.has(up) && out ? "\n" : (up && _SQL_INDENT.has(up) && out ? "\n  " : " ");
    } else {
      out += (tok.t === "kw" || tok.t === "fn") ? tok.v.toUpperCase() : tok.v;
    }
  }
  return out;
}

// Transparent-textarea-over-highlighted-pre editor: the user types in the textarea (transparent
// text, visible caret); the <pre> behind it shows the colors. Both share identical metrics so the
// caret aligns. Scroll is synced from the textarea. No external editor dependency.
function SqlEditor({ value, rows, taRef, onChange, onKeyDown, onClick, placeholder }: {
  value: string; rows: number; taRef: React.RefObject<HTMLTextAreaElement | null>;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onClick: () => void; placeholder?: string;
}) {
  const preRef = useRef<HTMLPreElement>(null);
  // The theme has unlayered global textarea rules (font-size/color/line-height) that beat
  // Tailwind utility classes on the <textarea> — so drive every metric inline (inline wins),
  // identically on both elements, or the caret drifts out of sync with the highlighted text.
  const metrics: React.CSSProperties = {
    fontFamily: "var(--font-code)", fontSize: "12px", lineHeight: "1.625",
    padding: "16px", tabSize: 2, whiteSpace: "pre-wrap", overflowWrap: "break-word",
    margin: 0, border: "1px solid transparent", borderRadius: "0.375rem",
  };
  return (
    <div className="relative">
      <pre ref={preRef} aria-hidden
        className="absolute inset-0 overflow-auto pointer-events-none"
        style={{ ...metrics, background: "rgba(24,24,27,0.8)" }}
        dangerouslySetInnerHTML={{ __html: highlightSql(value) + "\n" }} />
      <textarea
        ref={taRef} value={value} onChange={onChange} onKeyDown={onKeyDown} onClick={onClick}
        onScroll={e => { if (preRef.current) { preRef.current.scrollTop = e.currentTarget.scrollTop; preRef.current.scrollLeft = e.currentTarget.scrollLeft; } }}
        spellCheck={false} rows={rows} placeholder={placeholder}
        className="relative w-full outline-none resize-none focus:border-zinc-500"
        style={{ ...metrics, background: "transparent", color: "transparent", caretColor: "#f4f4f5", borderColor: "#3f3f46" }} />
    </div>
  );
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

function ResultsPane({
  result,
  connId,
  sql,
  primaryTable,
  joinedTables,
  onStartCanvas,
  tableSchemas,
  vizType,
  showDataLabels,
  chartTitle,
  custom,
}: {
  result: DirectQueryResult;
  connId: string;
  sql: string;
  primaryTable: string | null;
  joinedTables: string[];
  onStartCanvas?: (canvasId: string) => void;
  tableSchemas?: Record<string, string>;
  vizType?: ChartType | "auto";
  showDataLabels?: boolean;
  chartTitle?: string;
  custom?: ChartCustom | null;
}) {
  const [view, setView] = useState<"chart" | "matrix" | "table">("chart");
  const [creatingCanvas, setCreatingCanvas] = useState(false);

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
  const hasTwoCats =
    chartable &&
    chartable.colorCol !== undefined &&
    result.columns.filter((_, i) => {
      const firstVal = rows.find(r => r[i] != null)?.[i];
      return firstVal != null && isNaN(Number(firstVal));
    }).length >= 2;

  const meta = [
    `${result.row_count ?? result.rows.length} rows`,
    result.duration_ms != null ? `${result.duration_ms}ms` : null,
    result.cached ? "cached" : null,
  ].filter(Boolean).join(" · ");

  const exportCsv = () => {
    const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [result.columns.map(esc).join(","), ...rows.map(r => r.map(esc).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "query-results.csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  const handleCreateCanvas = async () => {
    if (!connId || !primaryTable) return;
    setCreatingCanvas(true);
    try {
      const tables = [primaryTable, ...joinedTables];
      // Use the primary table's schema as the canvas scope schema so multi-schema
      // DuckDB connections resolve bare table names correctly.
      const scopeSchema = tableSchemas?.[primaryTable] || null;
      let name = "Query Canvas";
      let description = `Canvas from Query Builder: ${tables.join(", ")}`;
      try {
        const suggested = await suggestCanvasName(connId, tables);
        name = suggested.name;
        description = suggested.description;
      } catch {}
      const canvas = await createCanvas(name, description, [
        { connection_id: connId, schema_name: scopeSchema, tables },
      ]);
      onStartCanvas?.(canvas.id);
    } catch (e) {
      alert((e as Error).message || "Failed to create canvas");
    } finally {
      setCreatingCanvas(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* View toggle + actions */}
      <div className="flex items-center gap-2">
        {chartable && (
          <>
            <button
              onClick={() => setView("chart")}
              className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${view === "chart" ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
            >
              ◈ Chart
            </button>
            {hasTwoCats && (
              <button
                onClick={() => setView("matrix")}
                className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${view === "matrix" ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
              >
                ⊞ Matrix
              </button>
            )}
          </>
        )}
        <button
          onClick={() => setView("table")}
          className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${view === "table" ? "border-blue-500/40 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}
        >
          ≡ Table
        </button>
        <div className="ml-auto flex items-center gap-2.5">
          <span className="text-[11px]" style={{ color: "var(--t3)" }}>{meta}</span>
          <button onClick={exportCsv} title="Download results as CSV"
            className="text-[11px] px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition flex items-center gap-1">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            CSV
          </button>
        </div>
      </div>

      {/* Chart — controlled by the Explore rail (type / labels / title) */}
      {view === "chart" && chartable && (
        <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 560 }}>
          <InvestigationChart columns={result.columns} rows={rows}
            controlled typeOverride={vizType} showLabels={showDataLabels} title={chartTitle} custom={custom} />
        </div>
      )}

      {/* Matrix */}
      {view === "matrix" && chartable && (
        <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 520 }}>
          <InvestigationChart columns={result.columns} rows={rows} title="Matrix" />
        </div>
      )}

      {/* Table */}
      {(view === "table" || !chartable) && (
        <>
          {!chartable && (
            <span className="text-[11px] text-right" style={{ color: "var(--t3)" }}>{meta}</span>
          )}
          <SqlResultTable columns={result.columns} rows={rows} maxHeight={420} />
        </>
      )}

      {/* Start Canvas */}
      {primaryTable && (
        <div className="flex justify-end pt-2">
          <button
            onClick={handleCreateCanvas}
            disabled={creatingCanvas}
            className="text-[11px] px-3 py-1.5 rounded border border-violet-500/40 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 transition disabled:opacity-50 flex items-center gap-1.5"
          >
            {creatingCanvas ? (
              <>
                <span className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin" />
                Creating…
              </>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="7" height="7" rx="1"/>
                  <rect x="14" y="3" width="7" height="7" rx="1"/>
                  <rect x="14" y="14" width="7" height="7" rx="1"/>
                  <rect x="3" y="14" width="7" height="7" rx="1"/>
                </svg>
                Start Canvas
              </>
            )}
          </button>
        </div>
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
  const [loadingTableCols, setLoadingTableCols] = useState<Set<string>>(new Set());
  const [joinHint,      setJoinHint]      = useState<string|null>(null);

  const [primaryTable, setPrimaryTable] = useState<string|null>(null);
  const [joinedTables, setJoinedTables] = useState<string[]>([]);
  const [showAddJoin,  setShowAddJoin]  = useState(false);
  const [expandedTables, setExpandedTables] = useState<Record<string,boolean>>({});
  const [expandedSchemas, setExpandedSchemas] = useState<Record<string,boolean>>({});
  const [catEntry, setCatEntry] = useState<CatalogEntry|null>(null);
  const [tableSchemas, setTableSchemas] = useState<Record<string, string>>({});
  const [allEntries, setAllEntries] = useState<CatalogEntry[]>([]);
  const [expandedConns, setExpandedConns] = useState<Record<string,boolean>>({});
  const [colSearch, setColSearch] = useState("");

  const [metrics,         setMetrics]         = useState<Metric[]>([]);
  // Measure grains (additivity) for this connection — drives the metric-chip warnings.
  const [measureGrains, setMeasureGrains] = useState<Record<string, "per_unit"|"per_line">>({});
  const [grainQtyCols,  setGrainQtyCols]  = useState<string[]>([]);

  // Fetch columns for a single table on-demand (fallback when rich schema is empty)
  const fetchTableColumns = useCallback(async (table: string, schemaName?: string) => {
    if (!connId || loadingTableCols.has(table)) return;
    setLoadingTableCols(p => { const n = new Set(p); n.add(table); return n; });
    try {
      const cols = await getTableColumns(connId, table, schemaName);
      if (cols.length > 0) {
        setTableCols(prev => ({ ...prev, [table]: cols.map(c => ({ ...c, is_fk: false } as SchemaColumn)) }));
      }
    } catch (e) {
      console.error(`[QueryBuilder] failed to load columns for ${table}:`, e);
    } finally {
      setLoadingTableCols(p => { const n = new Set(p); n.delete(table); return n; });
    }
  }, [connId, loadingTableCols]);
  const [showMetricsCatalog, setShowMetricsCatalog] = useState(false);

  const [dims,     setDims]     = useState<DimItem[]>([]);
  const [measures, setMeasures] = useState<MeasureItem[]>([]);
  const [filters,  setFilters]  = useState<FilterItem[]>([]);
  const [having,   setHaving]   = useState<HavingItem[]>([]);   // filters on aggregates → HAVING
  const [orderBy,  setOrderBy]  = useState("");
  // Default to a bounded preview LIMIT — a fresh SELECT * on a large table with no cap is a
  // footgun. 0 (or a cleared field) is an explicit "no limit" opt-out the user can still choose.
  const [limit,    setLimit]    = useState(1000);

  // Time controls — opt-in: a chosen time column enables the range preset + grain.
  const [timeCol,    setTimeCol]    = useState("");
  const [timeColTable, setTimeColTable] = useState("");
  const [timePreset, setTimePreset] = useState<TimePreset>("all");
  const [timeFrom,   setTimeFrom]   = useState("");
  const [timeTo,     setTimeTo]     = useState("");
  const [timeGrain,  setTimeGrain]  = useState<TimeGrain>("none");

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
  const [nfDistinct, setNfDistinct] = useState<string[]>([]);  // distinct-value suggestions for the picker

  // Saved queries (persistence) — savedId/savedName track the currently loaded saved query so
  // "Save" updates in place; the dropdown lists this connection's saved queries to load/delete.
  const [savedList,   setSavedList]   = useState<SavedQuery[]>([]);
  const [savedId,     setSavedId]     = useState<string|null>(null);
  const [savedName,   setSavedName]   = useState("");
  const [showSaved,   setShowSaved]   = useState(false);
  const [railTab,     setRailTab]     = useState<"data"|"customize">("data");  // Superset-style control rail
  const [vizType,        setVizType]        = useState<ChartType | "auto">("auto");  // chart-type override
  const [showDataLabels, setShowDataLabels] = useState(false);
  const [chartTitle,     setChartTitle]     = useState("");
  const [colorScheme,    setColorScheme]    = useState("");   // "" = engine default
  const [numberFormat,   setNumberFormat]   = useState("");   // "" = auto
  const [legendPos,      setLegendPos]      = useState("");   // "" = default (right)
  const [xTitle,         setXTitle]         = useState("");
  const [yTitle,         setYTitle]         = useState("");
  const [showSaveName, setShowSaveName] = useState(false);
  const [saveName,    setSaveName]    = useState("");
  const [savingState, setSavingState] = useState<"idle"|"saving"|"saved">("idle");

  useEffect(() => {
    getConnections().then(cs => { setConnections(cs); if (!connId && cs.length) setConnId(cs[0].id); }).catch(()=>{});
    getMetrics().then(setMetrics).catch(()=>{});
  }, []);

  useEffect(() => {
    if (!connId) return;
    setLoadingTree(true);
    setLoadingCols(true);
    setPrimaryTable(null); setJoinedTables([]); setTableNames([]); setTableCols({});
    setSchemaJoins([]); setDims([]); setMeasures([]); setFilters([]); setHaving([]);
    setTimeCol(""); setTimeColTable(""); setTimePreset("all"); setTimeFrom(""); setTimeTo(""); setTimeGrain("none");
    setVizType("auto"); setShowDataLabels(false); setChartTitle("");
    setColorScheme(""); setNumberFormat(""); setLegendPos(""); setXTitle(""); setYTitle("");
    setSql(""); setResult(null); setCatEntry(null); setExpandedSchemas({});

    // Phase 1 — fast: catalog tree gives us schema/table hierarchy immediately
    getCatalogTree()
      .then(tree => {
        const entries = tree.sections.flatMap(s => s.entries);
        setAllEntries(entries);
        const entry = entries.find(e => e.conn_id === connId) ?? null;
        setCatEntry(entry);
      const ts: Record<string, string> = {};
      entry?.schemas.forEach(s => s.tables.forEach(t => { ts[t.name] = s.name; }));
      setTableSchemas(ts);
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

    // Phase 2 — slower: rich schema adds columns, joins, row counts.
    // Canonicalize the rich schema's qualified names ("analytics.order_items") to the bare key
    // the catalog tree uses ("order_items"), so the catalog rows find their columns/joins.
    // Collision guard: if two schemas expose the same bare name, keep BOTH dotted to stay
    // unambiguous. Schema is recorded in tableSchemas so quoteTable re-qualifies at SQL time.
    getSchemaRich(connId).then(rich => {
      const bareCount: Record<string, number> = {};
      rich.tables.forEach(t => { const b = bareTable(t.name); bareCount[b] = (bareCount[b] || 0) + 1; });
      const keyOf = (full: string) => (bareCount[bareTable(full)] > 1 ? full : bareTable(full));

      const names: string[] = [];
      const cols: Record<string,SchemaColumn[]> = {};
      const rc: Record<string,string|null> = {};
      const schemaAdds: Record<string,string> = {};
      rich.tables.forEach(t => {
        const k = keyOf(t.name);
        names.push(k); cols[k] = t.columns; rc[k] = t.row_count;
        const s = tableSchemaOf(t.name); if (s) schemaAdds[k] = s;
      });
      const joins = rich.joins.map(j => ({ ...j, t1: keyOf(j.t1), t2: keyOf(j.t2) }));
      const iso = (rich.isolated ?? []).map(keyOf);
      setTableNames(names); setTableCols(cols); setRowCounts(rc);
      setTableSchemas(prev => ({ ...prev, ...schemaAdds }));
      setSchemaJoins(joins); setIsolated(iso);
    }).catch(err => { console.error("[QueryBuilder] getSchemaRich failed:", err); }).finally(()=>setLoadingCols(false));
  }, [connId]);

  useEffect(() => {
    if (!autoSql || !primaryTable) return;
    const t: TimeSpec | undefined = timeCol
      ? { col: timeCol, table: timeColTable || primaryTable, preset: timePreset, from: timeFrom, to: timeTo, grain: timeGrain }
      : undefined;
    setSql(buildSql(primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit, tableSchemas, t, having));
  }, [autoSql, primaryTable, joinedTables, schemaJoins, dims, measures, filters, orderBy, limit, tableSchemas,
      timeCol, timeColTable, timePreset, timeFrom, timeTo, timeGrain, having]);

  // Load this connection's saved queries; reset the active saved-query pointer on switch.
  useEffect(() => {
    setSavedId(null); setSavedName("");
    if (!connId) { setSavedList([]); return; }
    listSavedQueries(connId).then(setSavedList).catch(() => setSavedList([]));
  }, [connId]);

  // Fetch measure grains (additivity) for the connection — async/non-blocking; warnings appear
  // on metric chips once resolved (the first probe is slow on a wide warehouse, then cached).
  useEffect(() => {
    if (!connId) { setMeasureGrains({}); setGrainQtyCols([]); return; }
    getMeasureGrains(connId)
      .then(r => { setMeasureGrains(r.grains || {}); setGrainQtyCols(r.quantity_cols || []); })
      .catch(() => { setMeasureGrains({}); setGrainQtyCols([]); });
  }, [connId]);

  const allTables = primaryTable ? [primaryTable, ...joinedTables] : [];
  const isMulti   = allTables.length > 1;
  // A chosen time column enables the range/grain; otherwise time controls are a no-op in SQL.
  const timeSpec: TimeSpec | undefined = timeCol
    ? { col: timeCol, table: timeColTable || primaryTable || "", preset: timePreset, from: timeFrom, to: timeTo, grain: timeGrain }
    : undefined;
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

  const selectPrimary = useCallback((name: string, schema?: string) => {
    if (!name) return;
    if (schema) setTableSchemas(prev => ({ ...prev, [name]: schema }));
    setPrimaryTable(name); setJoinedTables([]); setExpandedTables({[name]: true});
    setDims([]); setMeasures([]); setFilters([]); setHaving([]); setOrderBy("");
    setTimeCol(""); setTimeColTable(""); setTimePreset("all"); setTimeFrom(""); setTimeTo(""); setTimeGrain("none");
    setVizType("auto"); setShowDataLabels(false); setChartTitle("");
    setColorScheme(""); setNumberFormat(""); setLegendPos(""); setXTitle(""); setYTitle("");
    setResult(null); setRunError(null); setAutoSql(true); setColSearch("");
    const qTable = quoteTable(name, schema);
    setSql(limit > 0 ? `SELECT *\nFROM ${qTable}\nLIMIT ${limit}` : `SELECT *\nFROM ${qTable}`);
  }, [limit]);

  // Make `table` part of the query, auto-resolving a multi-hop join path through
  // the studied join graph. Returns true if the table is now reachable.
  const ensureTable = useCallback((table: string, schema?: string): boolean => {
    if (!table) return false;
    // Auto-lookup schema from catalog tree if not explicitly passed
    const resolvedSchema = schema ?? catEntry?.schemas.find(s => s.tables.some(t => t.name === table))?.name;
    if (resolvedSchema) setTableSchemas(prev => ({ ...prev, [table]: resolvedSchema }));
    if (!primaryTable) { selectPrimary(table, resolvedSchema); return true; }
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

  // ── Saved-query persistence ────────────────────────────────────────────────
  // The visual builder state we persist so loading restores the builder, not just the SQL.
  const buildSpec = useCallback(() => ({
    primaryTable, joinedTables, dims, measures, filters, having, orderBy, limit,
    timeCol, timeColTable, timePreset, timeFrom, timeTo, timeGrain,
    vizType, showDataLabels, chartTitle, colorScheme, numberFormat, legendPos, xTitle, yTitle,
  }), [primaryTable, joinedTables, dims, measures, filters, having, orderBy, limit,
       timeCol, timeColTable, timePreset, timeFrom, timeTo, timeGrain,
       vizType, showDataLabels, chartTitle, colorScheme, numberFormat, legendPos, xTitle, yTitle]);

  const suggestedName = () => {
    if (!primaryTable) return "Untitled query";
    const ms = measures.map(m => m.alias || m.col || m.agg).filter(Boolean).slice(0, 2).join(", ");
    return ms ? `${primaryTable} · ${ms}` : `${primaryTable} query`;
  };

  const refreshSavedList = useCallback(() => {
    if (connId) listSavedQueries(connId).then(setSavedList).catch(() => {});
  }, [connId]);

  const doCreateSaved = async (name: string) => {
    if (!connId || !name.trim()) return;
    setSavingState("saving");
    try {
      const q = await createSavedQuery(connId, name.trim(), sql, buildSpec());
      setSavedId(q.id); setSavedName(q.name);
      setShowSaveName(false); setSaveName("");
      setSavingState("saved"); setTimeout(() => setSavingState("idle"), 1500);
      refreshSavedList();
    } catch (e) { alert((e as Error).message || "Failed to save query"); setSavingState("idle"); }
  };

  const doUpdateSaved = async () => {
    if (!savedId) return;
    setSavingState("saving");
    try {
      const q = await updateSavedQuery(savedId, { name: savedName, sql, spec: buildSpec() });
      setSavedName(q.name);
      setSavingState("saved"); setTimeout(() => setSavingState("idle"), 1500);
      refreshSavedList();
    } catch (e) { alert((e as Error).message || "Failed to update query"); setSavingState("idle"); }
  };

  const onSaveClick = () => {
    if (!sql.trim()) return;
    if (savedId) doUpdateSaved();
    else { setSaveName(suggestedName()); setShowSaveName(true); }
  };

  const loadSaved = (q: SavedQuery) => {
    const s = (q.spec || {}) as Record<string, unknown>;
    setPrimaryTable((s.primaryTable as string) ?? null);
    setJoinedTables(Array.isArray(s.joinedTables) ? s.joinedTables as string[] : []);
    setDims(Array.isArray(s.dims) ? s.dims as DimItem[] : []);
    setMeasures(Array.isArray(s.measures) ? s.measures as MeasureItem[] : []);
    setFilters(Array.isArray(s.filters) ? s.filters as FilterItem[] : []);
    setHaving(Array.isArray(s.having) ? s.having as HavingItem[] : []);
    setOrderBy(typeof s.orderBy === "string" ? s.orderBy : "");
    setLimit(typeof s.limit === "number" ? s.limit : 1000);
    setTimeCol(typeof s.timeCol === "string" ? s.timeCol : "");
    setTimeColTable(typeof s.timeColTable === "string" ? s.timeColTable : "");
    setTimePreset((s.timePreset as TimePreset) ?? "all");
    setTimeFrom(typeof s.timeFrom === "string" ? s.timeFrom : "");
    setTimeTo(typeof s.timeTo === "string" ? s.timeTo : "");
    setTimeGrain((s.timeGrain as TimeGrain) ?? "none");
    setVizType((s.vizType as ChartType | "auto") ?? "auto");
    setShowDataLabels(typeof s.showDataLabels === "boolean" ? s.showDataLabels : false);
    setChartTitle(typeof s.chartTitle === "string" ? s.chartTitle : "");
    setColorScheme(typeof s.colorScheme === "string" ? s.colorScheme : "");
    setNumberFormat(typeof s.numberFormat === "string" ? s.numberFormat : "");
    setLegendPos(typeof s.legendPos === "string" ? s.legendPos : "");
    setXTitle(typeof s.xTitle === "string" ? s.xTitle : "");
    setYTitle(typeof s.yTitle === "string" ? s.yTitle : "");
    setAutoSql(false);            // preserve the saved SQL exactly
    setSql(q.sql);
    setSavedId(q.id); setSavedName(q.name);
    setResult(null); setRunError(null); setShowSaved(false);
  };

  const removeSaved = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteSavedQuery(id);
      if (savedId === id) { setSavedId(null); setSavedName(""); }
      refreshSavedList();
    } catch { /* best-effort */ }
  };

  const commitFilter = () => {
    if (!nfCol) return;
    setFilters(p => [...p, {id:uid(),col:nfCol,table:nfTable||primaryTable||"",op:nfOp,val:nfVal}]);
    setNfTable(""); setNfCol(""); setNfOp("="); setNfVal(""); setNfDistinct([]); setShowAddFilter(false);
  };

  // Fetch distinct values for the chosen filter column and format them as SQL literals
  // (quoted for text columns) so the picker inserts a valid predicate value.
  const loadDistinct = useCallback(async (table: string, col: string) => {
    setNfDistinct([]);
    if (!connId || !table || !col) return;
    try {
      const { values } = await getColumnDistinct(connId, table, col, tableSchemas[table], 200);
      const numeric = isNum((tableCols[table] ?? []).find(c => c.name === col)?.type ?? "");
      setNfDistinct(values.filter((v): v is string => v != null)
        .map(v => numeric ? v : `'${v.replace(/'/g, "''")}'`));
    } catch { setNfDistinct([]); }
  }, [connId, tableSchemas, tableCols]);

  // ── Suggestion intelligence (over the resolved tables) ────────────────────
  const usedDimKeys = new Set(dims.map(d => `${d.table}.${d.col}`));
  const usedMeaCols = new Set(measures.map(m => `${m.table}.${m.col}`));
  const resolvedCols = allTables.flatMap(t => (tableCols[t] ?? []).map(c => ({ ...c, table: t })));
  const timeColumns = resolvedCols.filter(c => isDate(c.type));

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

  // One-click fix for a per-unit SUM under-count: rewrite the measure to SUM(col × quantity).
  const fixGrainMeasure = (m: MeasureItem) => {
    const qty = grainQtyCols.find(q => (tableCols[m.table] ?? []).some(c => c.name.toLowerCase() === q.toLowerCase()))
      || grainQtyCols[0] || "quantity";
    const base = qualify(m.col, m.table, isMulti);
    const qtyQ = qualify(qty, m.table, isMulti);
    setMeasures(p => p.map(x => x.id === m.id
      ? { ...x, agg: "CUSTOM" as AggFn, customExpr: `SUM(${base} * ${qtyQ})`, alias: x.alias || `sum_${m.col}_x_${qty}` }
      : x));
  };

  // Chart customization — the available viz types depend on the current result's shape.
  const chartInfo = result && !result.error && result.columns.length
    ? inferChartType(result.columns, result.rows as unknown[][]) : null;
  const availTypes = chartInfo ? availableTypesFor(chartInfo.type) : [];
  const CHART_TYPE_LABEL: Record<string, string> = {
    auto: "Auto", bar: "Bar", line: "Line", "multi-line": "Multi-line", area: "Area",
    "stacked-bar": "Stacked", "grouped-bar": "Grouped", combo: "Combo", scatter: "Scatter",
    heatmap: "Heatmap", pie: "Pie", treemap: "Treemap",
  };
  const chartCustom: ChartCustom = {
    format: numberFormat || undefined,
    colorScheme: colorScheme || undefined,
    legend: (legendPos || undefined) as ChartCustom["legend"],
    xTitle: xTitle || undefined,
    yTitle: yTitle || undefined,
  };
  // Customize-tab option lists
  const COLOR_SCHEMES = [["", "Default"], ["tableau10", "Tableau 10"], ["category10", "Category 10"], ["set2", "Set 2"], ["dark2", "Dark 2"], ["pastel1", "Pastel"], ["tableau20", "Tableau 20"]];
  const NUMBER_FORMATS = [["", "Auto"], [",.0f", "1,234"], [",.2f", "1,234.56"], ["$,.0f", "$1,234"], ["$,.2f", "$1,234.56"], ["~s", "1.2K (compact)"], [".0%", "12%"], [".1%", "12.3%"]];
  const LEGEND_POS = [["", "Default"], ["right", "Right"], ["bottom", "Bottom"], ["top", "Top"], ["none", "Hidden"]];

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

          {/* Saved queries — persistence */}
          <div className="relative flex items-center gap-1.5">
            <button onClick={() => { setShowSaved(v => !v); refreshSavedList(); }}
              title="Open saved queries"
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 border border-zinc-700 rounded-lg px-2.5 py-1 transition">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="shrink-0">
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
              </svg>
              {savedName ? <span className="max-w-[110px] truncate">{savedName}</span> : "Saved"}
              {savedList.length > 0 && <span className="text-zinc-500">{savedList.length}</span>}
              <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="shrink-0"><polyline points="1,2 4,6 7,2"/></svg>
            </button>
            <button onClick={onSaveClick} disabled={!sql.trim()}
              title={savedId ? "Update this saved query" : "Save the current query"}
              className={`text-[11px] rounded-lg px-2.5 py-1 transition border disabled:opacity-40 ${
                savingState === "saved" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                  : "border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
              }`}>
              {savingState === "saving" ? "Saving…" : savingState === "saved" ? "Saved ✓" : savedId ? "Save" : "Save"}
            </button>

            {/* Saved-query list */}
            {showSaved && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowSaved(false)} />
                <div className="absolute right-0 top-full mt-2 z-40 w-72 rounded-md border border-zinc-700 bg-zinc-900 shadow-2xl overflow-hidden">
                  <div className="px-3 py-2 border-b border-zinc-700/50 flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-zinc-400">Saved queries</span>
                    <button onClick={() => { setSavedId(null); setSaveName(suggestedName()); setShowSaved(false); setShowSaveName(true); }}
                      disabled={!sql.trim()}
                      className="text-[11px] text-blue-400 hover:text-blue-300 disabled:opacity-40">+ Save current as…</button>
                  </div>
                  <div className="max-h-[320px] overflow-y-auto">
                    {savedList.length === 0 ? (
                      <p className="px-3 py-3 text-[11px] text-zinc-500">No saved queries for this connection yet.</p>
                    ) : savedList.map(q => (
                      <div key={q.id} onClick={() => loadSaved(q)}
                        className={`group/sq flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-zinc-800/70 border-b border-zinc-700/30 last:border-0 ${q.id === savedId ? "bg-zinc-800/40" : ""}`}>
                        <div className="min-w-0 flex-1">
                          <p className="text-[12px] text-zinc-200 truncate">{q.name}</p>
                          <p className="text-[10px] text-zinc-500 truncate font-mono">{(q.sql || "").replace(/\s+/g, " ").slice(0, 52)}</p>
                        </div>
                        {q.id === savedId && <span className="text-[9px] text-blue-400 shrink-0">active</span>}
                        <button onClick={(e) => removeSaved(q.id, e)} title="Delete saved query"
                          className="opacity-0 group-hover/sq:opacity-100 text-zinc-500 hover:text-red-400 shrink-0 leading-none">✕</button>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Name prompt for create */}
            {showSaveName && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowSaveName(false)} />
                <div className="absolute right-0 top-full mt-2 z-50 w-72 rounded-md border border-zinc-700 bg-zinc-900 shadow-2xl p-3">
                  <p className="text-[11px] font-semibold text-zinc-400 mb-2">Save query as</p>
                  <input autoFocus value={saveName} onChange={e => setSaveName(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") doCreateSaved(saveName); if (e.key === "Escape") setShowSaveName(false); }}
                    placeholder="Query name"
                    className="w-full text-[12px] bg-zinc-800 border border-zinc-600 rounded-md px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-400" />
                  <div className="flex justify-end gap-2 mt-2.5">
                    <button onClick={() => setShowSaveName(false)} className="text-[11px] text-zinc-400 hover:text-zinc-200 px-2 py-1">Cancel</button>
                    <button onClick={() => doCreateSaved(saveName)} disabled={!saveName.trim()}
                      className="text-[11px] bg-blue-600 hover:bg-blue-500 text-white rounded-md px-3 py-1 font-medium disabled:opacity-40">Save</button>
                  </div>
                </div>
              </>
            )}
          </div>

          {!autoSql && (
            <button
              onClick={() => { setAutoSql(true); if (primaryTable) setSql(buildSql(primaryTable,joinedTables,schemaJoins,dims,measures,filters,orderBy,limit,tableSchemas,timeSpec,having)); }}
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
                                <button onClick={()=> {
                                    const willOpen = !(expandedTables[tbl] ?? isResolved);
                                    setExpandedTables(p=>({...p,[tbl]: willOpen}));
                                    if (willOpen && !(tableCols[tbl]?.length > 0) && !loadingTableCols.has(tbl)) {
                                      // Try to infer schema name from catalog tree
                                      const schemaName = catEntry?.schemas.find(s => s.tables.some(t => t.name === tbl))?.name;
                                      fetchTableColumns(tbl, schemaName);
                                    }
                                  }}
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
                                  <button onClick={()=>ensureTable(tbl, schema.name)} title="Add to query (auto-join)"
                                    className="opacity-0 group-hover/tbl:opacity-100 text-[11px] text-zinc-500 hover:text-blue-400 border border-zinc-700 hover:border-blue-500/50 rounded px-1.5 leading-tight transition shrink-0">
                                    + add
                                  </button>
                                )}
                              </div>
                              {open && (
                                loadingCols && cols.length === 0
                                  ? <div className="pl-11 py-1.5"><span className="text-[11px] text-zinc-500 animate-pulse">Loading columns…</span></div>
                                  : cols.length > 0
                                    ? cols.map(col => (
                                      <div key={col.name} className="pl-4">
                                        <ColRow col={col} tableName={tbl}
                                          onAddDim={()=>addDim(col.name, tbl)}
                                          onAddMeasure={()=>openMeasure(col, tbl)}
                                        />
                                      </div>
                                    ))
                                    : <div className="pl-11 py-1.5">
                                      <span className="text-[11px] text-zinc-500">
                                        {loadingTableCols.has(tbl) ? "Loading columns…" : "No columns available — schema may need refresh"}
                                      </span>
                                    </div>
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
        <div className="flex-1 flex overflow-hidden h-full">

          {/* ── CONTROL RAIL: DATA / CUSTOMIZE tabs (Superset Explore structure) ── */}
          <div className="w-[380px] shrink-0 flex flex-col border-r border-zinc-700/40 bg-zinc-900/20 h-full">
            <div className="flex items-center gap-1 px-4 pt-3 border-b border-zinc-700/40 shrink-0">
              {(["data","customize"] as const).map(tab => (
                <button key={tab} onClick={()=>setRailTab(tab)}
                  className={`text-[12px] font-semibold uppercase tracking-wide px-3 py-2 -mb-px border-b-2 transition ${railTab===tab ? "border-blue-500 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}>
                  {tab}
                </button>
              ))}
            </div>
            <div className={`flex-1 overflow-y-auto px-5 py-4 space-y-5 ${railTab==="data"?"":"hidden"}`}>

              {/* CHART TYPE — viz gallery (Superset's first DATA section); appears once chartable */}
              {availTypes.length > 0 && (
                <div className="pb-1">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Chart Type</p>
                  <div className="flex flex-wrap gap-1.5">
                    {(["auto", ...availTypes] as (ChartType|"auto")[]).map(t => (
                      <button key={t} onClick={()=>setVizType(t)}
                        className={`text-[11px] px-2.5 py-1 rounded-lg border transition ${vizType===t ? "border-blue-500/50 bg-blue-500/10 text-blue-300" : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"}`}>
                        {CHART_TYPE_LABEL[t] ?? t}
                      </button>
                    ))}
                  </div>
                </div>
              )}

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

              {/* Time controls — range + grain over a date column */}
              {primaryTable && timeColumns.length > 0 && (
                <div className="rounded-md border border-zinc-700/40 bg-zinc-800/20 px-4 py-3">
                  <div className="flex items-center gap-2 mb-2.5">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.8" strokeLinecap="round" className="shrink-0">
                      <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>
                    </svg>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Time</p>
                    <span className="text-[11px] text-zinc-500">range &amp; grain over a date column</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <select value={timeCol}
                      onChange={e => { const v = e.target.value; setTimeCol(v); const tc = timeColumns.find(c => c.name === v); setTimeColTable(tc ? tc.table : ""); }}
                      className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                      <option value="">No time column</option>
                      {timeColumns.map(c => <option key={`${c.table}.${c.name}`} value={c.name}>{isMulti ? `${c.table}.` : ""}{c.name}</option>)}
                    </select>
                    <select value={timePreset} onChange={e => setTimePreset(e.target.value as TimePreset)} disabled={!timeCol}
                      className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition disabled:opacity-40">
                      {TIME_PRESETS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                    </select>
                    {timeCol && timePreset === "custom" && (
                      <div className="flex items-center gap-1.5">
                        <input type="date" value={timeFrom} onChange={e => setTimeFrom(e.target.value)}
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-zinc-200 outline-none focus:border-zinc-500" />
                        <span className="text-zinc-500 text-[11px]">→</span>
                        <input type="date" value={timeTo} onChange={e => setTimeTo(e.target.value)}
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-zinc-200 outline-none focus:border-zinc-500" />
                      </div>
                    )}
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] text-zinc-500">grain</span>
                      <select value={timeGrain} onChange={e => setTimeGrain(e.target.value as TimeGrain)} disabled={!timeCol}
                        className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition disabled:opacity-40">
                        {TIME_GRAINS.map(g => <option key={g} value={g}>{g}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Dimensions + Metrics */}
              <div className="grid grid-cols-1 gap-4">

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
                      <span key={d.id} className="inline-flex items-center gap-1 text-[12px] font-mono px-2 py-1 rounded-lg border bg-blue-500/10 border-blue-500/30 text-blue-300">
                        {isMulti ? `${d.table}.${d.col}` : d.col}
                        {/* Date transform dropdown */}
                        {(tableCols[d.table]?.find(c=>c.name===d.col)?.type?.toLowerCase().includes("date") ||
                          tableCols[d.table]?.find(c=>c.name===d.col)?.type?.toLowerCase().includes("time")) && (
                          <select
                            value={d.transform || ""}
                            onChange={e=> {
                              const t = e.target.value as DimItem["transform"];
                              setDims(p => p.map(x => x.id === d.id ? { ...x, transform: t || undefined } : x));
                            }}
                            className="text-[10px] bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-zinc-300 outline-none ml-1"
                            onClick={e=> e.stopPropagation()}
                          >
                            <option value="">raw</option>
                            <option value="date">DATE</option>
                            <option value="month">MONTH</option>
                            <option value="quarter">QUARTER</option>
                            <option value="year">YEAR</option>
                            <option value="hour">HOUR</option>
                            <option value="minute">MIN</option>
                          </select>
                        )}
                        <button onClick={()=>setDims(p=>p.filter(x=>x.id!==d.id))} className="opacity-50 hover:opacity-100 text-sm leading-none ml-0.5">×</button>
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
                      const warn = grainWarning(m, measureGrains, grainQtyCols);
                      return (
                        <span key={m.id} title={warn || `${measureExpr(m,isMulti)} AS ${m.alias}`}
                          className={`inline-flex items-center gap-1.5 text-[12px] font-mono px-2.5 py-1 rounded-lg border ${
                            warn ? "text-amber-200 border-amber-500/50 bg-amber-500/10"
                                 : (ao?.cls ?? "text-violet-300 border-violet-500/30 bg-violet-500/10")}`}>
                          <span className="text-[11px] font-sans opacity-70">{m.fromMetric?"📊":m.agg==="CUSTOM"?"fx":m.agg}</span>
                          <span className="max-w-[120px] truncate">{m.alias||measureExpr(m,isMulti)}</span>
                          {warn && (
                            <>
                              <span title={warn} className="text-amber-400 cursor-help">⚠</span>
                              {m.agg === "SUM" && (
                                <button onClick={()=>fixGrainMeasure(m)} title={`Rewrite as SUM(${m.col} × quantity)`}
                                  className="text-[10px] text-amber-300 hover:text-amber-100 underline decoration-dotted">fix</button>
                              )}
                            </>
                          )}
                          <button onClick={()=>{ setMeasures(p=>p.filter(x=>x.id!==m.id)); setHaving(h=>h.filter(x=>x.measureId!==m.id)); }} className="opacity-50 hover:opacity-100 text-sm leading-none">×</button>
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
                        <select value={nfTable} onChange={e=>{ setNfTable(e.target.value); setNfCol(""); setNfDistinct([]); }}
                          className="text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                          <option value="">table</option>
                          {allTables.map(t=><option key={t} value={t}>{t}</option>)}
                        </select>
                      )}
                      <select value={nfCol} onChange={e=>{ const c=e.target.value; setNfCol(c); loadDistinct(nfTable||primaryTable||"", c); }}
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
                        <>
                          <input value={nfVal} onChange={e=>setNfVal(e.target.value)} list="qb-nf-distinct"
                            onKeyDown={e=>{if(e.key==="Enter")commitFilter();}} placeholder="value" autoFocus
                            className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 w-40 transition" />
                          {nfDistinct.length > 0 && (
                            <datalist id="qb-nf-distinct">
                              {nfDistinct.map(v => <option key={v} value={v} />)}
                            </datalist>
                          )}
                        </>
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

              {/* HAVING — filter on aggregated metrics */}
              {measures.length > 0 && (
                <div className="border-t border-zinc-700/30 pt-5">
                  <p className="text-[13px] font-semibold text-zinc-300 mb-1">Having</p>
                  <p className="text-[11px] text-zinc-500 mb-3">HAVING — filter on aggregated metrics (e.g. total &gt; 1000)</p>
                  <div className="flex flex-col gap-2 items-start">
                    {having.map(h => (
                      <div key={h.id} className="flex items-center gap-2 flex-wrap">
                        <select value={h.measureId} onChange={e=>setHaving(p=>p.map(x=>x.id===h.id?{...x,measureId:e.target.value}:x))}
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition max-w-[200px]">
                          {measures.map(mm=><option key={mm.id} value={mm.id}>{mm.alias||measureExpr(mm,isMulti)}</option>)}
                        </select>
                        <select value={h.op} onChange={e=>setHaving(p=>p.map(x=>x.id===h.id?{...x,op:e.target.value}:x))}
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                          {HAVING_OPS.map(op=><option key={op} value={op}>{op}</option>)}
                        </select>
                        <input value={h.val} onChange={e=>setHaving(p=>p.map(x=>x.id===h.id?{...x,val:e.target.value}:x))} placeholder="value"
                          className="text-[12px] font-mono bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 w-28 transition" />
                        <button onClick={()=>setHaving(p=>p.filter(x=>x.id!==h.id))} className="text-zinc-500 hover:text-red-400 text-sm leading-none px-1">×</button>
                      </div>
                    ))}
                    <button onClick={()=>setHaving(p=>[...p,{id:uid(),measureId:measures[0].id,op:">",val:""}])}
                      className="flex items-center gap-1.5 text-[12px] border border-dashed border-zinc-700 rounded-lg px-3 py-1.5 text-zinc-500 hover:border-zinc-500 hover:text-zinc-300 transition">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                      </svg>
                      Add having
                    </button>
                  </div>
                </div>
              )}

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
                  <input type="number" min={0} max={50000} value={limit || ""} onChange={e=>{
                      const v = e.target.value;
                      setLimit(v === "" ? 0 : Math.max(0, parseInt(v) || 0));
                    }}
                    placeholder="∞"
                    title="Rows to preview. Blank or 0 = no limit (unbounded — use with care on large tables)."
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
                    <button onClick={()=>{ if (sql.trim()) { setSql(formatSql(sql)); setAutoSql(false); } }}
                      className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded-lg px-2.5 py-1 transition">
                      Format
                    </button>
                    <button onClick={()=>navigator.clipboard.writeText(sql).catch(()=>{})}
                      className="text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded-lg px-2.5 py-1 transition">
                      Copy
                    </button>
                  </div>
                </div>
                <SqlEditor
                  taRef={sqlRef}
                  value={sql}
                  rows={Math.max(6, Math.min(16, sql.split("\n").length + 2))}
                  onChange={handleSqlChange}
                  onKeyDown={handleSqlKeyDown}
                  onClick={()=>setAcItems([])}
                  placeholder={"SELECT *\nFROM table\nLIMIT 1000"}
                />
              </div>

              {/* close the primaryTable fragment — Filters/Having/Sort/SQL live in the rail */}
              </>)}
            </div>{/* end DATA tab */}

            {/* CUSTOMIZE tab — chart styling */}
            <div className={`flex-1 overflow-y-auto px-5 py-4 space-y-5 ${railTab==="customize"?"":"hidden"}`}>
              {availTypes.length === 0 ? (
                <p className="text-[12px] text-zinc-500">Run a chartable query, then customize its chart here.</p>
              ) : (
                <>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Chart title</p>
                    <input value={chartTitle} onChange={e=>setChartTitle(e.target.value)} placeholder="(auto)"
                      className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 transition" />
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Labels</p>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={showDataLabels} onChange={e=>setShowDataLabels(e.target.checked)} className="w-3.5 h-3.5 accent-blue-500" />
                      <span className="text-[12px] text-zinc-300">Show data labels on the chart</span>
                    </label>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Color scheme</p>
                    <select value={colorScheme} onChange={e=>setColorScheme(e.target.value)}
                      className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                      {COLOR_SCHEMES.map(([v,l])=><option key={v} value={v}>{l}</option>)}
                    </select>
                    <p className="text-[10px] text-zinc-600 mt-1">Applies to multi-series charts.</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Number format</p>
                    <select value={numberFormat} onChange={e=>setNumberFormat(e.target.value)}
                      className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                      {NUMBER_FORMATS.map(([v,l])=><option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Legend</p>
                    <select value={legendPos} onChange={e=>setLegendPos(e.target.value)}
                      className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none hover:border-zinc-500 transition">
                      {LEGEND_POS.map(([v,l])=><option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">X axis title</p>
                      <input value={xTitle} onChange={e=>setXTitle(e.target.value)} placeholder="(auto)"
                        className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 transition" />
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">Y axis title</p>
                      <input value={yTitle} onChange={e=>setYTitle(e.target.value)} placeholder="(auto)"
                        className="w-full text-[12px] bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 outline-none focus:border-zinc-500 transition" />
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>{/* end control rail */}

          {/* ── CHART AREA — the chart is the hero; the data table sits below ── */}
          <main className="flex-1 overflow-y-auto h-full px-6 py-5">
            {(running || runError || result) ? (
              <div className="pb-6">
                <div className="flex items-center gap-3 mb-4">
                  <p className="text-[15px] font-semibold text-zinc-100">{savedName || (primaryTable ?? "Results")}</p>
                  {result && !result.error && (
                    <span className="text-[12px] text-zinc-400">
                      {fmtN(result.row_count)} rows · {fmtMs(result.duration_ms)}
                      {result.cached && <span className="ml-2 text-[11px] text-violet-400 border border-violet-500/30 rounded-md px-1.5 py-0.5">cached</span>}
                    </span>
                  )}
                </div>
                {running && (
                  <div className="flex items-center gap-2 py-16 justify-center text-zinc-500">
                    <span className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-400 rounded-full animate-spin"/>
                    <span className="text-[12px]">Running query…</span>
                  </div>
                )}
                {runError && !running && (
                  <div className="p-4 rounded-md border border-red-500/20 bg-red-500/5">
                    <p className="text-[12px] font-mono text-red-400">{runError}</p>
                  </div>
                )}
                {result && !running && (
                  <ResultsPane
                    result={result}
                    connId={connId}
                    sql={sql}
                    primaryTable={primaryTable}
                    joinedTables={joinedTables}
                    tableSchemas={tableSchemas}
                    vizType={vizType}
                    showDataLabels={showDataLabels}
                    chartTitle={chartTitle || undefined}
                    custom={chartCustom}
                    onStartCanvas={(id) => { window.location.href = `/?canvas=${id}`; }}
                  />
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center gap-2 text-zinc-500">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" className="opacity-50">
                  <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
                </svg>
                <p className="text-[12px] italic">Configure your query in the panel, then <strong className="text-zinc-400 font-normal not-italic">Run</strong> or press <kbd className="text-zinc-400 bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[11px]">⌘↵</kbd></p>
              </div>
            )}
          </main>
        </div>
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
