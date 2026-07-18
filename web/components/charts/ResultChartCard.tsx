"use client";

/**
 * ResultChartCard — the answer-result chart surface for Insight (chat), Deep Analysis
 * (report), and the briefing cockpit. Wraps the canonical <Chart> (ECharts) engine and
 * renders CLEAN: no controls sit on the chart. A single hover pencil ("Edit
 * visualization") opens the Databricks-style right-docked side panel (VizEditorPanel),
 * where every control lives, grouped into layered sections — Visualization, X axis,
 * Y axis, Transform, Labels. Edits apply live to the chart behind the drawer.
 *
 * The controls themselves are unchanged and GRAIN-AWARE:
 *   • Display  — chart type (line/bar/pie/…), from availableChartTypes; + chart⇄table⇄pivot.
 *   • Metric   — which numeric measure to plot.
 *   • Dimension— which category/date column for the x-axis.
 *   • Aggregation — SUM/AVG/COUNT/MIN/MAX, offered ONLY when the dimension repeats;
 *                   defaults to AVG for rate/share metrics (never SUM-of-an-average).
 *   • Transform— period-over-period / share / rolling / cumulative (appends a column).
 *   • Table / Pivot — the raw result, or a cross-tab.
 *
 * Untouched defaults reproduce today's chart exactly (original rows → <Chart>'s own
 * inference), so this is additive — no regression for existing results.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Chart, type ChartCustom } from "@/components/Chart";
import { SqlResultTable } from "@/components/AugTable";
import { PivotTable } from "@/components/PivotTable";
import { classifyColumns, availableChartTypes, type ChartType } from "@/components/charts/chartTypeInference";
import { isUngraphableGrid } from "@/components/charts/columnRoles";
import type { ExhibitSpec } from "@/components/charts/exhibit";
import { cleanLabel } from "@/lib/format";
import { applyPostproc, type PostprocOp } from "@/lib/api";
import { VizEditorPanel, type VizEditorModel } from "@/components/charts/VizEditorPanel";
import { useVizEditorOpen, openVizEditor, closeVizEditor } from "@/components/charts/vizEditorStore";

const TRANSFORM_OPTS: { v: PostprocOp | "none"; t: string }[] = [
  { v: "none", t: "None" },
  { v: "pop", t: "Period-over-period" },
  { v: "contribution", t: "Share of total" },
  { v: "rolling", t: "Rolling avg (3)" },
  { v: "cumulative", t: "Cumulative" },
];

type Agg = "sum" | "avg" | "count" | "min" | "max";

// "Auto" (untouched) option for the Metric/Dimension/Aggregation pickers. Selecting
// it clears that override so the card returns to the original auto-derived chart —
// without it there's no way back to a multi-series default once a control is touched.
const AUTO_OPT = "__auto__";

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
  /** Backend exhibit spec (semantic colour / ref-lines) — takes precedence over the
   *  one riding inside chartConfig; lets the deep-report path pass it explicitly. */
  exhibit?: ExhibitSpec | null;
  /** Authoritative per-column display unit from the backend finding (e.g. percent). */
  columnUnits?: Record<string, string> | null;
  /** Initial data-label visibility (the deep report ships labels on). */
  defaultShowLabels?: boolean;
  heightScale?: number;
  onSelect?: (datum: Record<string, unknown>) => void;
}

export function ResultChartCard({
  columns, rows, title, chartType, chartConfig, custom, exhibit: exhibitProp,
  columnUnits, defaultShowLabels, heightScale, onSelect,
}: Props) {
  const { numericIdxs, catIdxs, dateIdxs } = useMemo(() => classifyColumns(columns, rows), [columns, rows]);
  const chartTypes = useMemo(() => availableChartTypes(columns, rows), [columns, rows]);
  // The exhibit spec (semantic colour / reference lines) rides inside chart_config on the quick
  // path, but it is NOT field-role config: it must survive the user choosing a chart type, which
  // nulls chartConfig below. Lift it out so a Display switch can't silently drop the grammar.
  // An explicit `exhibit` prop (deep report) wins over the one embedded in chartConfig.
  const exhibit = useMemo(
    () => exhibitProp ?? (chartConfig?.exhibit as ExhibitSpec | undefined) ?? null,
    [exhibitProp, chartConfig],
  );

  const metricCols = useMemo(() => numericIdxs.map((i) => columns[i]), [numericIdxs, columns]);
  const dimCols = useMemo(
    () => [...dateIdxs, ...catIdxs].map((i) => columns[i]),
    [dateIdxs, catIdxs, columns],
  );

  // Chart-grammar gate: a stats/entity-profile grid opens on the TABLE (its honest
  // form — the chart toggle stays available); everything else opens on the chart.
  const [view, setView] = useState<"chart" | "table" | "pivot">(
    chartTypes.length && !isUngraphableGrid(columns, rows) ? "chart" : "table");
  const [typeSel, setTypeSel] = useState<ChartType | "auto">("auto");
  const [metricSel, setMetricSel] = useState<string | null>(null);
  const [dimSel, setDimSel] = useState<string | null>(null);
  const [aggSel, setAggSel] = useState<Agg | null>(null);
  const [showLabels, setShowLabels] = useState<boolean>(defaultShowLabels ?? false);

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
  // A transform APPENDS a derived column (*_cumulative, *_pct_change, *_pct_of_total,
  // *_rolling_*) and keeps the original. Chart that derived column against the dimension —
  // seeing the transform is the whole point; re-plotting the original shows no change.
  const effData = useMemo(() => {
    if (!transformed) return data;
    const derivedCol = transformed.columns.find((c) => !data.columns.includes(c));
    const di = transformed.columns.indexOf(dim);
    if (!derivedCol || di < 0) return transformed;
    const ci = transformed.columns.indexOf(derivedCol);
    return {
      columns: [dim, derivedCol],
      rows: transformed.rows.map((r) => [(r as unknown[])[di], (r as unknown[])[ci]]),
    };
  }, [transformed, data, dim]);

  // Respect the backend hint until the user picks a type from Display.
  const hint = typeSel === "auto" ? (chartType ?? "auto") : (TYPE_TO_HINT[typeSel] ?? "auto");
  // The backend chart config re-plots its OWN field + type, so it must yield the moment the
  // user picks a chart type, applies a transform, or reshapes the data (metric/dim/agg) —
  // otherwise those controls silently do nothing on any answer that shipped a config.
  const userChoseChart = touched || typeSel !== "auto" || transformOp !== "none";

  // Live ECharts instance (for the panel's Download PNG on a chromeless chart).
  const instRef = useRef<{ getDataURL: (o?: { type?: string; pixelRatio?: number; backgroundColor?: string }) => string } | null>(null);
  const handleDownload = () => {
    const inst = instRef.current;
    if (!inst) return;
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg-2").trim() || "#161A20";
    const url = inst.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: bg });
    const fname = (title || "chart").replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
    const a = Object.assign(document.createElement("a"), { href: url, download: fname });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  // Single-instance viz editor (one drawer open app-wide).
  const cardId = useId();
  const editorOpen = useVizEditorOpen(cardId);

  // The control model handed to the side panel. The panel is stateless; this is the
  // single place the AUTO sentinel ↔ null mapping lives.
  const model: VizEditorModel = {
    title,
    view, setView,
    chartAvailable: chartTypes.length > 0,
    canPivot,
    chartTypeValue: typeSel,
    chartTypeOptions: chartTypes.length ? [{ v: "auto", t: "Auto" }, ...chartTypes.map((t) => ({ v: t, t: TYPE_LABEL[t] }))] : [],
    setChartType: (v) => setTypeSel(v as ChartType | "auto"),
    dimValue: dimSel ?? (dimCols.length >= 2 ? AUTO_OPT : (dimCols[0] ?? "")),
    dimOptions: dimCols.length
      ? [...(dimCols.length >= 2 ? [{ v: AUTO_OPT, t: "Auto" }] : []), ...dimCols.map((c) => ({ v: c, t: cleanLabel(c) }))]
      : [],
    setDim: (v) => setDimSel(v === AUTO_OPT ? null : v),
    metricValue: metricSel ?? (metricCols.length >= 2 ? AUTO_OPT : (metricCols[0] ?? "")),
    metricOptions: metricCols.length
      ? [...(metricCols.length >= 2 ? [{ v: AUTO_OPT, t: "Auto" }] : []), ...metricCols.map((c) => ({ v: c, t: cleanLabel(c) }))]
      : [],
    setMetric: (v) => setMetricSel(v === AUTO_OPT ? null : v),
    aggValue: dimHasDups ? (aggSel ?? AUTO_OPT) : null,
    aggOptions: [{ v: AUTO_OPT, t: "Auto" }, ...(["sum", "avg", "count", "min", "max"] as Agg[]).map((a) => ({ v: a, t: a.toUpperCase() }))],
    setAgg: (v) => setAggSel(v === AUTO_OPT ? null : (v as Agg)),
    rateSummed,
    transformValue: transformOp,
    transformOptions: metricCols.length >= 1 ? TRANSFORM_OPTS : [],
    setTransform: (v) => setTransformOp(v as PostprocOp | "none"),
    transformErr: tErr || undefined,
    showLabels, setShowLabels,
    onDownload: view === "chart" ? handleDownload : null,
  };

  return (
    <div className="group/viz relative">
      {/* Edit visualization — the single hover affordance; every control lives in the panel. */}
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => openVizEditor(cardId)}
        title="Edit visualization"
        className="absolute -top-1 right-0 z-10 opacity-0 group-hover/viz:opacity-100 transition-opacity"
        style={editorOpen ? { color: "var(--accent)", opacity: 1 } : { color: "var(--t3)" }}
      >
        <Pencil size={13} />
      </Button>

      {/* Body — clean chart / table / pivot */}
      {view === "pivot" ? (
        <PivotTable columns={columns} rows={rows} />
      ) : view === "table" ? (
        <SqlResultTable columns={effData.columns} rows={effData.rows} maxHeight={340} />
      ) : (
        <Chart
          columns={effData.columns}
          rows={effData.rows}
          chartType={hint}
          chartConfig={userChoseChart ? null : chartConfig}
          exhibit={exhibit}
          columnUnits={columnUnits}
          custom={custom}
          title={title}
          chrome={false}
          showLabels={showLabels}
          heightScale={heightScale}
          onSelect={onSelect}
          onInstanceReady={(inst) => { instRef.current = inst; }}
        />
      )}

      {editorOpen && typeof document !== "undefined" &&
        createPortal(<VizEditorPanel model={model} onClose={() => closeVizEditor(cardId)} />, document.body)}
    </div>
  );
}
