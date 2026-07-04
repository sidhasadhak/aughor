"use client";

/**
 * ResultChartCard — the answer-result chart surface for Insight (chat) and Deep
 * Analysis (report) modes. Wraps the canonical <Chart> (ECharts) engine with an
 * inline, re-pivot-in-place control strip + a chart⇄table toggle, in the spirit
 * of a ThoughtSpot-style answer card — but GRAIN-AWARE:
 *
 *   • Display  — swap chart type (line/bar/pie/…), driven by availableChartTypes.
 *   • Metric   — which numeric measure to plot (shown only when ≥2 exist).
 *   • Dimension— which category/date column for the x-axis (shown only when ≥2).
 *   • Aggregation — SUM/AVG/COUNT/MIN/MAX, shown ONLY when the chosen dimension
 *                   has repeated values (i.e. re-aggregation is actually meaningful);
 *                   defaults to AVG for rate/share metrics so we never offer the
 *                   nonsensical SUM-of-an-average that naive tools expose.
 *   • ⊞ table  — one-click toggle to the raw result table.
 *   • ⊞ pivot  — cross-tab (rows × columns → aggregated values) via PivotTable,
 *                fed the FULL result (not the projected [dim, metric]); its own
 *                Rows/Columns/Values/Agg pickers own the re-shape there.
 *
 * Untouched defaults reproduce today's chart exactly (original rows → <Chart>'s
 * own inference), so this is additive — no regression for existing results.
 */

import { useEffect, useMemo, useState } from "react";
import { BarChart3, Table2, Grid3x3 } from "lucide-react";
import { Chart, type ChartCustom } from "@/components/Chart";
import { SqlResultTable } from "@/components/AugTable";
import { PivotTable } from "@/components/PivotTable";
import { classifyColumns, availableChartTypes, type ChartType } from "@/components/charts/chartTypeInference";
import { cleanLabel } from "@/lib/format";
import { applyPostproc, type PostprocOp } from "@/lib/api";

const TRANSFORM_OPTS: { v: PostprocOp | "none"; t: string }[] = [
  { v: "none", t: "None" },
  { v: "pop", t: "Period-over-period" },
  { v: "contribution", t: "Share of total" },
  { v: "rolling", t: "Rolling avg (3)" },
  { v: "cumulative", t: "Cumulative" },
];

type Agg = "sum" | "avg" | "count" | "min" | "max";

// ChartType (hyphenated) → the underscore "hint" the <Chart> engine speaks.
const TYPE_TO_HINT: Record<ChartType, string> = {
  "line": "line", "area": "area", "multi-line": "multi_line", "small-multiples": "small_multiples", "bar": "bar",
  "grouped-bar": "combo", "combo": "combo", "stacked-bar": "stacked_bar",
  "scatter": "scatter", "heatmap": "heatmap", "matrix": "heatmap",
  "pie": "pie", "treemap": "treemap", "table": "auto",
};
const TYPE_LABEL: Record<ChartType, string> = {
  "line": "Line", "area": "Area", "multi-line": "Multi-line", "small-multiples": "Small multiples", "bar": "Bar",
  "grouped-bar": "Grouped", "combo": "Combo", "stacked-bar": "Stacked",
  "scatter": "Scatter", "heatmap": "Heatmap", "matrix": "Matrix",
  "pie": "Pie", "treemap": "Treemap", "table": "Table",
};

const RATE_RE = /avg|average|mean|rate|ratio|share|pct|percent|proportion|margin|per_/i;
/** Grain-aware default aggregation: rate/share metrics average, additive metrics sum. */
function defaultAgg(metric: string): Agg {
  return RATE_RE.test(metric) ? "avg" : "sum";
}

function aggregate(xs: number[], agg: Agg): number | null {
  if (agg === "count") return xs.length;
  if (!xs.length) return null;
  switch (agg) {
    case "sum": return xs.reduce((a, b) => a + b, 0);
    case "avg": return xs.reduce((a, b) => a + b, 0) / xs.length;
    case "min": return Math.min(...xs);
    case "max": return Math.max(...xs);
  }
}

/** Project (and optionally re-aggregate) to a [dimension, metric] table. */
function derive(
  columns: string[], rows: unknown[][], dim: string, metric: string, agg: Agg,
): { columns: string[]; rows: unknown[][] } {
  const di = columns.indexOf(dim);
  const mi = columns.indexOf(metric);
  if (di < 0 || mi < 0) return { columns, rows };
  const distinct = new Set(rows.map((r) => String((r as unknown[])[di])));
  const hasDups = distinct.size < rows.length;
  if (!hasDups && agg !== "count") {
    // Already one row per dimension value → just project the two chosen columns.
    return { columns: [dim, metric], rows: rows.map((r) => [(r as unknown[])[di], (r as unknown[])[mi]]) };
  }
  const groups = new Map<string, number[]>();
  const order: string[] = [];
  for (const r of rows) {
    const k = String((r as unknown[])[di]);
    if (!groups.has(k)) { groups.set(k, []); order.push(k); }
    const v = Number((r as unknown[])[mi]);
    if (!isNaN(v)) groups.get(k)!.push(v);
  }
  const outCol = agg === "count" ? "count" : metric;
  return { columns: [dim, outCol], rows: order.map((k) => [k, aggregate(groups.get(k)!, agg)]) };
}

interface Props {
  columns: string[];
  rows: unknown[][];
  title?: string;
  /** Backend-suggested chart hint, respected until the user changes Display. */
  chartType?: string | null;
  chartConfig?: Record<string, unknown> | null;
  custom?: ChartCustom | null;
  heightScale?: number;
  onSelect?: (datum: Record<string, unknown>) => void;
}

const SELECT_CLS =
  "aug-fs-xs rounded border bg-transparent px-1.5 py-0.5 outline-none cursor-pointer";
const selectStyle = { borderColor: "var(--chart-grid)", color: "var(--t2)" } as const;

export function ResultChartCard({ columns, rows, title, chartType, chartConfig, custom, heightScale, onSelect }: Props) {
  const { numericIdxs, catIdxs, dateIdxs } = useMemo(() => classifyColumns(columns, rows), [columns, rows]);
  const chartTypes = useMemo(() => availableChartTypes(columns, rows), [columns, rows]);

  const metricCols = useMemo(() => numericIdxs.map((i) => columns[i]), [numericIdxs, columns]);
  const dimCols = useMemo(
    () => [...dateIdxs, ...catIdxs].map((i) => columns[i]),
    [dateIdxs, catIdxs, columns],
  );

  const [view, setView] = useState<"chart" | "table" | "pivot">(chartTypes.length ? "chart" : "table");
  const [typeSel, setTypeSel] = useState<ChartType | "auto">("auto");
  const [metricSel, setMetricSel] = useState<string | null>(null);
  const [dimSel, setDimSel] = useState<string | null>(null);
  const [aggSel, setAggSel] = useState<Agg | null>(null);

  // Default metric MUST match what <Chart> resolves when untouched, or the strip
  // label contradicts the plot. <Chart> prefers a rate/share column as its primary
  // measure (PREFER_COL), so mirror that here.
  const defaultMetric = useMemo(
    () => metricCols.find((c) => /pct|percent|share|rate|ratio|proportion/i.test(c)) ?? metricCols[0] ?? "",
    [metricCols],
  );
  const metric = metricSel ?? defaultMetric;
  const dim = dimSel ?? dimCols[0] ?? "";
  const touched = metricSel !== null || dimSel !== null || aggSel !== null;

  // Aggregation is only meaningful when the chosen dimension repeats in the raw rows.
  const dimHasDups = useMemo(() => {
    const di = columns.indexOf(dim);
    if (di < 0) return false;
    return new Set(rows.map((r) => String((r as unknown[])[di]))).size < rows.length;
  }, [columns, rows, dim]);

  const agg: Agg = aggSel ?? defaultAgg(metric);
  const rateSummed = dimHasDups && agg === "sum" && RATE_RE.test(metric);

  // Pivot (cross-tab) earns its place when there's a dimension to group on and a
  // measure to aggregate; PivotTable picks sensible Rows/Columns/Values defaults.
  const canPivot = metricCols.length >= 1 && dimCols.length >= 1;

  // Derived data: untouched → original (today's behaviour); a control change → re-pivot.
  const data = useMemo(() => {
    if (!touched || !metric || !dim) return { columns, rows };
    return derive(columns, rows, dim, metric, agg);
  }, [touched, columns, rows, dim, metric, agg]);

  // On-demand post-processing transform (PoP / share / rolling / cumulative) — appends a
  // derived column on the chosen measure via /query/postproc. Off by default (today's view).
  const [transformOp, setTransformOp] = useState<PostprocOp | "none">("none");
  const [transformed, setTransformed] = useState<{ columns: string[]; rows: unknown[][] } | null>(null);
  const [tErr, setTErr] = useState("");
  useEffect(() => {
    if (transformOp === "none" || !metric) { setTransformed(null); setTErr(""); return; }
    let alive = true;
    applyPostproc(data.columns, data.rows, transformOp, metric)
      .then(r => { if (alive) { setTransformed(r); setTErr(""); } })
      .catch(e => { if (alive) { setTransformed(null); setTErr(String((e as Error).message)); } });
    return () => { alive = false; };
  }, [transformOp, data, metric]);
  const effData = transformed ?? data;

  // Respect the backend hint until the user picks a type from Display.
  const hint = typeSel === "auto" ? (chartType ?? "auto") : (TYPE_TO_HINT[typeSel] ?? "auto");
  const Dropdown = (label: string, value: string, opts: { v: string; t: string }[], on: (v: string) => void) => (
    <label className="flex items-center gap-1" style={{ color: "var(--t3)" }}>
      <span className="aug-fs-xs uppercase tracking-wide">{label}</span>
      <select className={SELECT_CLS} style={selectStyle} value={value} onChange={(e) => on(e.target.value)}>
        {opts.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
      </select>
    </label>
  );

  return (
    <div className="flex flex-col gap-1.5">
      {/* Control strip */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {/* The grain-aware strip drives chart/table; pivot owns its own field pickers. */}
          {view !== "pivot" && (
            <>
              {metricCols.length >= 2 &&
                Dropdown("Metric", metric, metricCols.map((c) => ({ v: c, t: cleanLabel(c) })), setMetricSel)}
              {dimCols.length >= 2 &&
                Dropdown("Dimension", dim, dimCols.map((c) => ({ v: c, t: cleanLabel(c) })), setDimSel)}
              {dimHasDups &&
                Dropdown("Aggregation", agg,
                  (["sum", "avg", "count", "min", "max"] as Agg[]).map((a) => ({ v: a, t: a.toUpperCase() })),
                  (v) => setAggSel(v as Agg))}
              {rateSummed && (
                <span className="aug-fs-xs" style={{ color: "var(--amber4, #B25D00)" }} title="Summing a rate/ratio is usually not meaningful — AVG is the grain-correct aggregate.">
                  ⚠ summing a rate
                </span>
              )}
              {metricCols.length >= 1 &&
                Dropdown("Transform", transformOp, TRANSFORM_OPTS, (v) => setTransformOp(v as PostprocOp | "none"))}
              {tErr && <span className="aug-fs-xs" style={{ color: "var(--amber4, #B25D00)" }} title={tErr}>⚠ transform n/a</span>}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {view === "chart" && chartTypes.length > 0 &&
            Dropdown("Display", typeSel,
              [{ v: "auto", t: "Auto" }, ...chartTypes.map((t) => ({ v: t, t: TYPE_LABEL[t] }))],
              (v) => setTypeSel(v as ChartType | "auto"))}
          {/* chart ⇄ table toggle */}
          <div className="flex items-center gap-0.5 rounded border p-0.5" style={{ borderColor: "var(--chart-grid)" }}>
            <button
              onClick={() => setView("chart")}
              title="Chart"
              disabled={!chartTypes.length}
              className="w-6 h-6 flex items-center justify-center rounded transition-colors disabled:opacity-30"
              style={view === "chart" ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}
            >
              <BarChart3 size={14} />
            </button>
            <button
              onClick={() => setView("table")}
              title="Table"
              className="w-6 h-6 flex items-center justify-center rounded transition-colors"
              style={view === "table" ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}
            >
              <Table2 size={14} />
            </button>
            <button
              onClick={() => setView("pivot")}
              title="Pivot (cross-tab)"
              disabled={!canPivot}
              className="w-6 h-6 flex items-center justify-center rounded transition-colors disabled:opacity-30"
              style={view === "pivot" ? { background: "var(--bg-sel)", color: "var(--accent)" } : { color: "var(--t3)" }}
            >
              <Grid3x3 size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Body */}
      {view === "pivot" ? (
        <PivotTable columns={columns} rows={rows} />
      ) : view === "table" ? (
        <SqlResultTable columns={effData.columns} rows={effData.rows} maxHeight={340} />
      ) : (
        <Chart
          columns={effData.columns}
          rows={effData.rows}
          chartType={hint}
          chartConfig={touched ? null : chartConfig}
          custom={custom}
          title={title}
          chrome={false}
          heightScale={heightScale}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}
