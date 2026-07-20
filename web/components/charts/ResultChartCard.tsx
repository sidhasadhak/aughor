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
import { classifyColumns, availableChartTypes, CHART_TYPE_LABEL, TYPE_TO_HINT, type ChartType } from "@/components/charts/chartTypeInference";
import { isUngraphableGrid } from "@/components/charts/columnRoles";
import type { ExhibitSpec, ExhibitRefLine, ExhibitColor } from "@/components/charts/exhibit";
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

// TYPE_TO_HINT (ChartType → engine hint) and CHART_TYPE_LABEL (display text) are the
// SINGLE-source maps in chartTypeInference — imported, not re-declared here (the old local
// copies were the exact drift that module exists to prevent).

// Databricks-style Customize vocabularies — kept in sync with the Query Builder Customize tab so a
// card and a query offer the same knobs. Chart.applyCustom honors each (unknown schemes no-op).
const COLOR_SCHEMES: { v: string; t: string }[] = [
  { v: "", t: "Default" }, { v: "tableau10", t: "Tableau 10" }, { v: "category10", t: "Category 10" },
  { v: "set2", t: "Set 2" }, { v: "dark2", t: "Dark 2" }, { v: "pastel1", t: "Pastel" }, { v: "tableau20", t: "Tableau 20" },
];
const NUMBER_FORMATS: { v: string; t: string }[] = [
  { v: "", t: "Auto" }, { v: ",.0f", t: "1,234" }, { v: ",.2f", t: "1,234.56" }, { v: "$,.0f", t: "$1,234" },
  { v: "$,.2f", t: "$1,234.56" }, { v: "~s", t: "1.2K (compact)" }, { v: ".0%", t: "12%" }, { v: ".1%", t: "12.3%" },
];
const LEGEND_POS: { v: string; t: string }[] = [
  { v: "", t: "Default" }, { v: "right", t: "Right" }, { v: "bottom", t: "Bottom" }, { v: "top", t: "Top" }, { v: "none", t: "Hidden" },
];

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
  /** Fill an exact pixel height — for a resizeable card/canvas node (chart + table grow to fill). */
  fillHeight?: number | null;
  onSelect?: (datum: Record<string, unknown>) => void;
}

export function ResultChartCard({
  columns, rows, title, chartType, chartConfig, custom, exhibit: exhibitProp,
  columnUnits, defaultShowLabels, heightScale, fillHeight, onSelect,
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
  // Any column can drive the Color binding (a dimension → discrete legend, a measure → gradient).
  const colorFieldOptions = useMemo(
    () => [{ v: "", t: "None" }, ...columns.map((c) => ({ v: c, t: cleanLabel(c) }))],
    [columns],
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
  // Customize overrides (Color / Format / Legend / Tooltip / Annotation) layered OVER the passed
  // `custom`/`exhibit`, so an untouched card renders byte-identically to before.
  const [colorScheme, setColorScheme] = useState("");
  // Color binding (the Databricks "Color" field): colour marks by a CHOSEN column instead
  // of the plotted measure. "" field = off (default coloring). Scale "" = auto by role
  // (a measure → continuous gradient; a dimension → categorical legend); name = legend title.
  const [colorField, setColorField] = useState("");
  const [colorScaleSel, setColorScaleSel] = useState<"" | "continuous" | "categorical">("");
  const [colorName, setColorName] = useState("");
  const [numberFormat, setNumberFormat] = useState("");
  const [legendPos, setLegendPos] = useState("");
  const [xTitle, setXTitle] = useState("");
  const [yTitle, setYTitle] = useState("");
  const [tooltipOff, setTooltipOff] = useState(false);
  const [userRefLines, setUserRefLines] = useState<ExhibitRefLine[]>([]);

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

  // Customize overrides merged over the passed props (empty string = "unset" → keep the prop).
  const effCustom: ChartCustom = useMemo(() => ({
    ...(custom || {}),
    ...(colorScheme ? { colorScheme } : {}),
    ...(numberFormat ? { format: numberFormat } : {}),
    ...(legendPos ? { legend: legendPos as ChartCustom["legend"] } : {}),
    ...(xTitle ? { xTitle } : {}),
    ...(yTitle ? { yTitle } : {}),
    ...(tooltipOff ? { tooltip: "off" as const } : {}),
  }), [custom, colorScheme, numberFormat, legendPos, xTitle, yTitle, tooltipOff]);

  // The color binding the user built (or null): a chosen field, its scale (explicit, else
  // auto by role — a measure ramps continuous, a dimension is categorical), and legend title.
  const colorBinding: ExhibitColor | null = useMemo(() => {
    if (!colorField) return null;
    const scale = colorScaleSel || (metricCols.includes(colorField) ? "continuous" : "categorical");
    return { mode: scale, field: colorField, name: colorName || null };
  }, [colorField, colorScaleSel, colorName, metricCols]);

  // User annotation lines ride on top of any backend exhibit ref-lines; a color binding, when
  // set, overrides the backend's own color mode (the user asked to colour by that column).
  const effExhibit: ExhibitSpec | null = useMemo(() => {
    if (!userRefLines.length && !colorBinding) return exhibit;
    const spec: ExhibitSpec = { ...(exhibit || {}) };
    if (userRefLines.length) spec.ref_lines = [...(exhibit?.ref_lines || []), ...userRefLines];
    if (colorBinding) spec.color = colorBinding;
    return spec;
  }, [exhibit, userRefLines, colorBinding]);

  const addRefLine = (value: number, label: string) => {
    if (!isFinite(value)) return;
    setUserRefLines(ls => [...ls, { value, label: label || `y = ${value}`, kind: "target" }]);
  };
  const removeRefLine = (idx: number) => setUserRefLines(ls => ls.filter((_, i) => i !== idx));
  const addAverageLine = () => {
    const mi = effData.columns.indexOf(metric);
    const col = mi >= 0 ? mi : effData.columns.length - 1;
    const nums = effData.rows.map(r => Number((r as unknown[])[col])).filter(v => !isNaN(v));
    if (!nums.length) return;
    const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
    setUserRefLines(ls => [...ls, { value: Number(mean.toFixed(4)), label: "Average", kind: "global_avg" }]);
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
    chartTypeOptions: chartTypes.length ? [{ v: "auto", t: "Auto" }, ...chartTypes.map((t) => ({ v: t, t: CHART_TYPE_LABEL[t] }))] : [],
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
    // Color
    colorSchemeValue: colorScheme, colorSchemeOptions: COLOR_SCHEMES, setColorScheme,
    legendValue: legendPos, legendOptions: LEGEND_POS, setLegend: setLegendPos,
    // Color binding (the Databricks "Color" field) — colour by a chosen column.
    colorFieldValue: colorField,
    colorFieldOptions,
    setColorField: (v: string) => { setColorField(v); if (!v) { setColorScaleSel(""); setColorName(""); } },
    colorScaleValue: colorBinding ? (colorBinding.mode as "continuous" | "categorical") : "",
    setColorScale: (v: "continuous" | "categorical") => setColorScaleSel(v),
    colorNameValue: colorName, setColorName,
    // Format & axis titles
    numberFormatValue: numberFormat, numberFormatOptions: NUMBER_FORMATS, setNumberFormat,
    xTitleValue: xTitle, setXTitle,
    yTitleValue: yTitle, setYTitle,
    // Tooltip
    tooltipOn: !tooltipOff, setTooltipOn: (b: boolean) => setTooltipOff(!b),
    // Annotation (reference lines)
    refLines: userRefLines.map(l => ({ label: l.label, value: l.value })),
    addRefLine, addAverageLine, removeRefLine, measureLabel: cleanLabel(metric),
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
        <SqlResultTable columns={effData.columns} rows={effData.rows} maxHeight={fillHeight && fillHeight > 0 ? fillHeight : 340} />
      ) : (
        <Chart
          columns={effData.columns}
          rows={effData.rows}
          chartType={hint}
          chartConfig={userChoseChart ? null : chartConfig}
          exhibit={effExhibit}
          columnUnits={columnUnits}
          custom={effCustom}
          title={title}
          chrome={false}
          showLabels={showLabels}
          heightScale={heightScale}
          fitHeight={fillHeight}
          onSelect={onSelect}
          onInstanceReady={(inst) => { instRef.current = inst; }}
        />
      )}

      {editorOpen && typeof document !== "undefined" &&
        createPortal(<VizEditorPanel model={model} onClose={() => closeVizEditor(cardId)} />, document.body)}
    </div>
  );
}
