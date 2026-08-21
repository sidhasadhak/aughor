/**
 * resolveOption.ts — the ONE chart resolver: (finding data + hint + exhibit +
 * customization) → an ECharts option. Extracted from Chart.tsx (CA-4) so the
 * same cascade serves the browser AND the headless print renderer — the PDF
 * draws exactly the chart the user was just looking at, because it runs the
 * same function. Pure: no React, no DOM.
 */

import type { EChartsOption } from "echarts";
import { format as d3format } from "d3-format";
import { SCHEME_PALETTES } from "@/lib/chartPalettes";
import { effectiveChartPalette } from "@/lib/orgSettings";
import {
  lineOption, multiLineOption, smallMultiplesOption, barOption, groupedBarOption, stackedBarOption,
  pieOption, scatterOption, deltaBarOption, heatmapOption, treemapOption, paretoOption,
  counterOption, funnelOption, histogramOption, boxplotOption, sankeyOption, waterfallOption,
  lineForecastOption, ganttOption, choroplethOption, pointMapOption,
} from "@/components/charts/echarts/builders";
import {
  SHARE_COL, CHANGE_METRIC_COL, TIME_LABEL_COL, INSTRUMENTATION_COL, PREFER_COL, classifyColumns,
  isIdLike, isUngraphableGrid, GEO_NAME_COL, LAT_COL, LON_COL, HORIZONTAL_MAX_CATS,
} from "@/components/charts/columnRoles";
import { chooseMultiMeasure, JOB_TO_ENGINE_HINT } from "@/components/charts/chartTypeInference";
import { sanitizeExhibit, type ExhibitSpec } from "@/components/charts/exhibit";

export interface ChartCustom {
  format?: string;        // d3 number format for the quantitative axis (e.g. ",.0f", "$,.2f", "~s")
  colorScheme?: string;   // categorical palette name (e.g. "tableau10", "set2")
  xTitle?: string;
  yTitle?: string;
  legend?: "right" | "bottom" | "top" | "left" | "none";
  tooltip?: "on" | "off"; // hover tooltip visibility (default on); "off" for a clean tile
  /** Swap the axes of a bar form. Absent → the shared rule decides (category reads
   *  horizontally, time reads vertically). */
  orient?: "vertical" | "horizontal";
  /** Post-processing to apply IN the chart rather than to the data beforehand. Only the
   *  Vega path reads this: the ECharts builders take already-transformed rows, which is why
   *  that path still round-trips through /query/postproc. */
  transform?: { op: "pop" | "contribution" | "rolling" | "cumulative"; valueCol: string;
                window?: number; agg?: "mean" | "sum" | "min" | "max" } | null;
}

type AxisLike = Record<string, unknown>;
function mapAxes(ax: unknown, fn: (a: AxisLike) => AxisLike): unknown {
  if (Array.isArray(ax)) return ax.map((a) => fn(a as AxisLike));
  if (ax && typeof ax === "object") return fn(ax as AxisLike);
  return ax;
}

function applyCustom(option: EChartsOption, custom?: ChartCustom | null): EChartsOption {
  if (!custom || !(custom.format || custom.colorScheme || custom.xTitle || custom.yTitle || custom.legend || custom.tooltip)) return option;
  const o: EChartsOption = { ...option };

  // Hover tooltip visibility — "off" makes a clean, static tile (Databricks "Tooltip" section).
  if (custom.tooltip === "off") {
    o.tooltip = { ...(o.tooltip as object || {}), show: false } as EChartsOption["tooltip"];
  }

  if (custom.format) {
    let f: ((n: number) => string) | null = null;
    try { f = d3format(custom.format); } catch { f = null; }
    if (f) {
      const fmt = f;
      // Apply to whichever axis carries the quantitative measure (type:"value").
      const setFmt = (a: AxisLike) => a.type === "value"
        ? { ...a, axisLabel: { ...(a.axisLabel as object || {}), formatter: (v: number) => fmt(v) } }
        : a;
      o.xAxis = mapAxes(o.xAxis, setFmt) as EChartsOption["xAxis"];
      o.yAxis = mapAxes(o.yAxis, setFmt) as EChartsOption["yAxis"];
    }
  }
  if (custom.xTitle) o.xAxis = mapAxes(o.xAxis, (a) => ({ ...a, name: custom.xTitle })) as EChartsOption["xAxis"];
  if (custom.yTitle) o.yAxis = mapAxes(o.yAxis, (a) => ({ ...a, name: custom.yTitle })) as EChartsOption["yAxis"];
  if (custom.colorScheme && SCHEME_PALETTES[custom.colorScheme]) o.color = SCHEME_PALETTES[custom.colorScheme];
  if (custom.legend) {
    if (custom.legend === "none") {
      o.legend = { show: false };
    } else {
      const vert = custom.legend === "left" || custom.legend === "right";
      o.legend = {
        ...(o.legend as object || {}), show: true, orient: vert ? "vertical" : "horizontal",
        top: custom.legend === "top" ? 0 : vert ? "middle" : undefined,
        bottom: custom.legend === "bottom" ? 0 : undefined,
        left: custom.legend === "left" ? 0 : undefined,
        right: custom.legend === "right" ? 0 : undefined,
      } as EChartsOption["legend"];
    }
  }
  return o;
}

export interface ResolveChartArgs {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
  chartConfig?: Record<string, unknown> | null;
  custom?: ChartCustom | null;
  columnUnits?: Record<string, string> | null;
  exhibit?: ExhibitSpec | null;
  showLabels?: boolean;
}

/** Resolve the chart for a result grid — identical in the browser and in print. */
export function resolveChartOption(
  { columns, rows, chartType, chartConfig, custom, columnUnits, exhibit: exhibitRaw, showLabels = false }: ResolveChartArgs,
): { option: EChartsOption; defaultH: number } | null {
  // "none" is the backend's explicit no-chart verdict; honour it everywhere.
  if (String(chartType ?? "").toLowerCase() === "none") return null;

  /**
   * The user's orientation override, applied at every point where a bar form picks a side.
   * Absent (the normal case) → `orientH` returns the rule's own answer unchanged, so nothing
   * about the default rendering moves. Threaded through the DECISIONS rather than swapped
   * onto a finished option: flipping a built ECharts option means transposing axis objects,
   * label positions and the category `inverse` flag, and getting any one of them wrong
   * produces a chart that looks deliberate and reads backwards.
   */
  const _forceH: boolean | null = custom?.orient ? custom.orient === "horizontal" : null;
  const orientH = (dflt: boolean): boolean => (_forceH === null ? dflt : _forceH);
  // Fail-open on a malformed backend spec: a bad exhibit costs its semantics,
  // never the chart.
  const exhibit = sanitizeExhibit(exhibitRaw);
    if (!rows.length || !columns.length) return null;
    // Chart-grammar gate: a stats/entity-profile grid has no honest chart — render
    // nothing and let the surface's table view carry it (mirrors the export).
    if (isUngraphableGrid(columns, rows)) return null;

    const data: Record<string, unknown>[] = rows.map((r) =>
      Object.fromEntries(columns.map((c, i) => [c, (r as unknown[])[i]])),
    );

    // Column roles from the ONE shared classifier (columnRoles.classifyColumns) — date / numeric /
    // category — so this renderer and chartTypeInference can never disagree on what a column is.
    const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);
    const dateCol = dateIdxs.length ? columns[dateIdxs[0]] : undefined;
    const catCols = catIdxs.map((i) => columns[i]);
    const numericCols = numericIdxs.map((i) => columns[i]);
    // Instrumentation columns exist only to make a metric auditable — the numerator/denominator a
    // ratio is built from, or a bare row-count `n`/`event_count`. They are never the answer, so they
    // must not be picked as a chart measure (charting `numerator_total` is what made an AOV finding
    // render as a giant SUM bar with the actual ratio hidden). `INSTRUMENTATION_COL` is the shared
    // pattern from columnRoles. Exclude them; fall back to the full set only if that leaves nothing.
    const _filteredNum = numericCols.filter((c) => !INSTRUMENTATION_COL.test(c));
    const chartNumericCols = _filteredNum.length ? _filteredNum : numericCols;
    const _isChangeMetric = numericCols.some((c) => CHANGE_METRIC_COL.test(c));
    const ID_COL = { test: (c: string) => /(^|_)(id|key|sk|pk|code|uuid|guid|hash)$/i.test(c) || isIdLike(c) };
    const NAME_COL = /(name|title|label|desc|description|channel|category|region|country|city|state|store|product|customer|item|page|segment|brand|merchant|franchise|email|url)/i;
    const catCol = catCols.find((c) => NAME_COL.test(c) && !ID_COL.test(c)) ?? catCols.find((c) => !ID_COL.test(c)) ?? catCols[0];
    const catCol2 = catCols.find((c) => c !== catCol) ?? catCols[1];
    const CHANGE_PREFER_COL = /(change|delta|growth|pct_change|percent_change|_chg$|_diff$)/i;
    const baseNumCol = chartNumericCols.find((c) => PREFER_COL.test(c)) ?? chartNumericCols.find((c) => !CHANGE_METRIC_COL.test(c)) ?? chartNumericCols[0];
    const changeNumCol = chartNumericCols.find((c) => CHANGE_PREFER_COL.test(c)) ?? chartNumericCols.find((c) => PREFER_COL.test(c)) ?? chartNumericCols[0];
    const numCol = (_isChangeMetric && catCol) ? changeNumCol : baseNumCol;
    // CA-4 form-by-job: a job token ("magnitude", "trend", …) renders as its form.
    const _rawHint = (chartType ?? "auto").toLowerCase();
    const hint = JOB_TO_ENGINE_HINT[_rawHint] ?? _rawHint;

    // Measure-less Tier-2 types render BEFORE the numeric-measure guard below, since they key
    // off dates (gantt) / coordinates (point map), not a measure.
    if (hint === "gantt" && dateIdxs.length >= 2) {
      const dcols = dateIdxs.map((k) => columns[k]);
      const START = /(start|begin|from|open)/i, END = /(end|finish|due|close|^to$|_to$)/i;
      const startF = dcols.find((c) => START.test(c)) ?? dcols[0];
      const endF = dcols.find((c) => END.test(c) && c !== startF) ?? dcols.find((c) => c !== startF) ?? dcols[1];
      const labelCol = catCol ?? columns.find((c) => c !== startF && c !== endF) ?? columns[0];
      const gopt = ganttOption({ rows: data, units: columnUnits ?? undefined, x: labelCol, ys: [], gantt: { start: startF, end: endF }, color: catCol2 });
      return { option: applyCustom(gopt, custom), defaultH: Math.max(200, new Set(data.map((d) => d[labelCol])).size * 32 + 60) };
    }
    if (hint === "point_map") {
      const latF = columns.find((c) => LAT_COL.test(c));
      const lonF = columns.find((c) => LON_COL.test(c));
      if (latF && lonF) {
        const sizeMeasure = numericCols.find((c) => !LAT_COL.test(c) && !LON_COL.test(c) && !isIdLike(c));
        const label = catCol ?? columns.find((c) => c !== latF && c !== lonF && !numericCols.includes(c));
        const popt = pointMapOption({ rows: data, units: columnUnits ?? undefined, x: latF, ys: sizeMeasure ? [sizeMeasure] : [], pointLabel: label }, latF, lonF);
        return { option: applyCustom(popt, custom), defaultH: 380 };
      }
    }

    if (!numCol) return null;

    const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;
    const _stackUnique = catCol ? new Set(data.map((d) => d[catCol])).size : 0;
    const nCats = catCol ? new Set(data.map((d) => d[catCol])).size : 0;

    // Pareto renders ONLY on an explicit backend hint. The old silent "upgrade" promoted any
    // plain bar carrying a share-like column into a dual-axis bars+cumulative combo — and its
    // measure picker EXCLUDED the share column, so a finding titled "share of refunds by
    // channel" charted raw COUNTS under a share title (the flags-on soak, inv 721d68aa). Both
    // defects die together: no upgrade, and a share ranking stays a ranked bar of the share.
    const PARETO_SHARE = /(share|cumulative|cum_pct|pct_of_total|of_total|contribution)/i;
    const paretoShareCol = columns.find((c) => PARETO_SHARE.test(c));
    const paretoCat: string | null = catCol ?? columns.find((c) => c !== paretoShareCol && ID_COL.test(c)) ?? null;
    const paretoMeasure: string | null =
      numericCols.find((c) => c !== paretoShareCol && !PARETO_SHARE.test(c) && !SHARE_COL.test(c) && !ID_COL.test(c))
      ?? (hint === "pareto" ? numCol : null);
    const wantPareto =
      hint === "pareto" && !!paretoCat && !!paretoMeasure && paretoCat !== paretoMeasure;

    // Backend-provided chart config (LLM-generated alongside SQL). TRUST IT ONLY WHEN ITS
    // FIELD ROLES ARE COHERENT WITH THE DATA — the LLM sometimes mis-maps the axes (e.g.
    // puts the MEASURE on x_field), which renders a broken chart (values on the category
    // axis, blank bars). When the config is incoherent we fall through to the data-shape
    // inference below, which is robust. (The config is dropped on history restore, so a
    // validated-or-inferred chart also makes a live answer match what History shows.)
    const cc = chartConfig;
    // The quick path's exhibit spec rides INSIDE chart_config (no separate event); an explicit
    // `exhibit` prop (deep report) wins over it.
    const exhibitEff = exhibit ?? ((cc?.exhibit as ExhibitSpec | undefined) || null);
    const ccType = cc?.type as string | undefined;
    const ccX = cc?.x_field as string | undefined;
    const ccY = cc?.y_field as string | undefined;
    const ccY2 = cc?.y_field_2 as string | undefined;
    const ccColor = cc?.color_field as string | undefined;
    const _colSet = new Set(columns);
    const _xReal = !!ccX && _colSet.has(ccX);
    const _xNum = !!ccX && numericCols.includes(ccX);
    const _yNum = !!ccY && numericCols.includes(ccY);  // the measure MUST be numeric
    const _ccType = (JOB_TO_ENGINE_HINT[(ccType ?? "").toLowerCase()] ?? (ccType ?? "")).toLowerCase();
    const _rolesOk =
      !!ccType && _xReal && _yNum && ccX !== ccY
      && (!ccColor || _colSet.has(ccColor))
      && (!ccY2 || numericCols.includes(ccY2))
      // scatter plots a measure on BOTH axes; every other type needs a dimension/date on x.
      && (_ccType === "scatter" ? _xNum : !_xNum);
    const hasBackendConfig = _rolesOk;
    const backendHint = hasBackendConfig ? ccType!.toLowerCase() : null;

    const lbls = showLabels;
    let option: EChartsOption | null = null;
    let defaultH = 300;

    // 1. Backend chart config
    if (hasBackendConfig && backendHint) {
      const xF = ccX!, yF = ccY!;
      // Dual axes are banned (§6): a config asking for "combo" falls through to the
      // shape inference below; a delta pair renders the signed change directly.
      if (backendHint === "delta_bar" && ccY2) { option = deltaBarOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [ccY2, yF], labels: lbls }); defaultH = 320; }
      else if (backendHint === "line" || backendHint === "multi_line") {
        option = ccColor
          ? multiLineOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], color: ccColor, xKind: "time" })
          : lineOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], xKind: "time" });
        defaultH = 350;
      }
      else if (backendHint === "bar" || backendHint === "bar_horizontal") { option = barOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], labels: lbls, exhibit: exhibitEff }); defaultH = 350; }
      else if (backendHint === "scatter") {
        option = scatterOption({
          rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], exhibit: exhibitEff,
          color: ccColor, pointLabel: catCols.find((c) => c !== ccColor) ?? catCol,
        });
        defaultH = 350;
      }
      else if (backendHint === "pie") { option = pieOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF] }); defaultH = 350; }
    }

    // 1b. Native-fit explicit types (2026-07 viz wave) — user-selected from the viz editor.
    //     Each renders only when the shape provides the fields it needs; otherwise it falls
    //     through to the inference cascade below, so a bad pick degrades, never blanks.
    if (!option && hint === "counter" && numCol) { option = counterOption({ rows: data, units: columnUnits ?? undefined, x: catCol ?? dateCol ?? numCol, ys: [numCol] }); defaultH = 200; }
    if (!option && hint === "funnel" && catCol && numCol) { option = funnelOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls }); defaultH = 320; }
    if (!option && hint === "histogram" && numCol) { option = histogramOption({ rows: data, units: columnUnits ?? undefined, x: catCol ?? numCol, ys: [numCol], labels: lbls }); defaultH = 300; }
    if (!option && hint === "boxplot" && numCol) { option = boxplotOption({ rows: data, units: columnUnits ?? undefined, x: catCol ?? numCol, ys: [numCol] }); defaultH = 320; }
    if (!option && hint === "sankey" && catCol && catCol2 && numCol) { option = sankeyOption({ rows: data, units: columnUnits ?? undefined, x: catCol, color: catCol2, ys: [numCol] }); defaultH = 360; }
    if (!option && hint === "waterfall" && (catCol || dateCol) && numCol) { option = waterfallOption({ rows: data, units: columnUnits ?? undefined, x: (catCol ?? dateCol)!, ys: [numCol], xKind: dateCol && !catCol ? "time" : "category" }); defaultH = 320; }
    if (!option && hint === "line_forecast" && dateCol && numCol) { option = lineForecastOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time" }); defaultH = 320; }
    if (!option && hint === "choropleth" && numCol) {
      const geoCol = catCols.find((c) => GEO_NAME_COL.test(c)) ?? catCol;
      if (geoCol) { option = choroplethOption({ rows: data, units: columnUnits ?? undefined, x: geoCol, ys: [numCol] }); defaultH = 380; }
    }

    // 1c. Colour binding on a LINE → one line per value of the chosen DIMENSION (multi-line).
    //     A continuous colour on a trend line isn't a standard encoding, so only the categorical
    //     case routes here (the picked dimension overrides the auto series column); otherwise the
    //     line renders plain. Bar/scatter honour the binding inside their own builders.
    const _cb = exhibitEff?.color;
    const _cbField = _cb?.field && _colSet.has(_cb.field) ? _cb.field : null;
    const _cbCategorical = !!_cbField && (_cb?.mode === "categorical" || !numericCols.includes(_cbField));
    if (!option && _cbCategorical && dateCol && _cbField !== dateCol
        && (hint === "line" || hint === "area" || hint === "multi_line" || hint === "auto")) {
      option = multiLineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], color: _cbField!, xKind: "time" });
      defaultH = 320;
    }
    // 1d. Colour binding on a CATEGORICAL result → a single-measure BAR carrying the binding
    //     (dimension → stacked split; measure → per-bar gradient), overriding the default bar
    //     variant (combo / grouped / auto). This makes "Color by" always visibly split or shade
    //     the bars — the fix for a colour picked on a multi-measure card (else combo ignored it).
    if (!option && _cbField && catCol && !dateCol
        && (hint === "bar" || hint === "bar_horizontal" || hint === "bar_vertical" || hint === "combo" || hint === "grouped_bar" || hint === "auto")) {
      option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff },
                         { horizontal: orientH(hint !== "bar_vertical" && nCats <= HORIZONTAL_MAX_CATS) });
      defaultH = Math.max(180, new Set(data.map((d) => d[catCol])).size * 42 + 60);
    }

    // 2. Pie (explicit)
    if (!option && hint === "pie" && catCol) { option = pieOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls }); defaultH = 240; }
    // 3. Pareto (explicit or concentration-upgrade)
    if (!option && wantPareto && paretoCat && paretoMeasure) { option = paretoOption({ rows: data, units: columnUnits ?? undefined, x: paretoCat, ys: [paretoMeasure] }); defaultH = 320; }
    // 4. Heatmap (explicit hint only; never for change metrics)
    if (!option && hint === "heatmap" && !_isChangeMetric && catCol) {
      const xSrc = dateCol ?? catCol2;
      if (xSrc) { option = heatmapOption({ rows: data, units: columnUnits ?? undefined, x: xSrc, color: catCol, ys: [numCol], xKind: dateCol ? "time" : "category" }); defaultH = Math.max(220, Math.min(_stackUnique * 18 + 80, 600)); }
    }
    // 5. Multi-line (explicit)
    if (!option && hint === "multi_line" && catCol && dateCol) { option = multiLineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], color: catCol, xKind: "time" }); defaultH = 320; }
    // 6. Treemap (explicit)
    if (!option && hint === "treemap" && catCol) { option = treemapOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol] }); defaultH = 340; }
    // 7. Change metric over time (auto) → multi-line of the delta
    if (!option && hint === "auto" && _isChangeMetric && catCol && dateCol) { option = multiLineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], color: catCol, xKind: "time" }); defaultH = 320; }
    // 8. Stacked bar (explicit, or auto date/cat with ≤6 series). A SHARE measure → 100%-stacked
    //    (composition shift over time); an absolute measure stacks by volume.
    //    A stack needs ≥2 x positions: one stacked column is a single lying bar (the
    //    "loyalty_members at 100%" exhibit), so a degenerate x falls through to the
    //    categorical branch below. 100%-stacked additionally demands share-like VALUES —
    //    the name test alone let `award_miles_fraction` (values to 309) normalise
    //    incomparable measures into a fake composition.
    if (!option && (hint === "stacked_bar" || (hint === "auto" && catCol && (catCol2 || dateCol) && !_isChangeMetric && _stackUnique <= 6))) {
      const x = dateCol ?? catCol;
      const color = dateCol ? catCol : catCol2;
      const xUnique = x ? new Set(data.map((d) => d[x])).size : 0;
      if (x && color && xUnique >= 2) {
        const shareVals = data.map((d) => Number(d[numCol])).filter((v) => !isNaN(v));
        const asPercent = SHARE_COL.test(numCol) && shareVals.length > 0 && shareVals.every((v) => Math.abs(v) <= 1.0001);
        option = stackedBarOption({ rows: data, units: columnUnits ?? undefined, x, ys: [numCol], color, xKind: dateCol ? "time" : "category" }, asPercent);
        defaultH = 280;
      }
    }
    // 8b. Small multiples — a many-group trend (auto date/cat with >6 series, or explicit): a grid of
    //     mini lines beats a spaghetti multi-line. Explicit hint always; auto only past the stack cap.
    if (!option && (hint === "small_multiples" || (hint === "auto" && dateCol && catCol && !_isChangeMetric && _stackUnique > 6))
        && dateCol && catCol) {
      option = smallMultiplesOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], color: catCol, xKind: "time" });
      defaultH = Math.max(260, Math.min(Math.ceil(Math.min(_stackUnique, 9) / (_stackUnique <= 4 ? 2 : 3)) * 140 + 20, 560));
    }
    // 9. Temporal multi-line (auto, ≤6 series)
    if (!option && hint === "auto" && dateCol && catCol && !_isChangeMetric) { option = multiLineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], color: catCol, xKind: "time" }); defaultH = 320; }
    // 10. Date bar (date + measure, no category)
    if (!option && dateCol && !catCol && (hint === "bar" || hint === "bar_horizontal")) { option = barOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: true, exhibit: exhibitEff }, { order: "time", horizontal: orientH(false) }); defaultH = 220; }
    // 11. Line / area (timeseries)
    if (!option && dateCol && !catCol && (hint === "line" || hint === "area" || hint === "auto")) { option = lineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: lbls, exhibit: exhibitEff }, hint === "area"); defaultH = 220; }
    // 12. Vertical bar (explicit)
    if (!option && catCol && hint === "bar_vertical") { option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff }, { order: isTimeLabel ? "keep" : "value" }); defaultH = 260; }
    // 13. Scatter (explicit) — an ENTITY scatter names each point with the id-like column and, when a
    //     second low-cardinality category exists, colors the points by it (hue = third dimension).
    if (!option && hint === "scatter" && numericCols.length >= 2) {
      const scatterLabel = catCols.find((c) => ID_COL.test(c)) ?? catCol;
      const scatterColor = catCols.find((c) =>
        c !== scatterLabel && !ID_COL.test(c) && new Set(data.map((d) => d[c])).size <= 12);
      option = scatterOption({
        rows: data, units: columnUnits ?? undefined, x: numericCols[0], ys: [numericCols[1]],
        exhibit: exhibitEff, pointLabel: scatterLabel, color: scatterColor,
      });
      defaultH = 300;
    }
    // 14a. Explicit RANKING hint (bar / bar_horizontal) on a categorical result — the backend's
    //      intent-driven chart_type is authoritative: plot the PRIMARY measure as one sorted
    //      horizontal bar. Without this branch the hint fell through to the data-shape gate
    //      below, which turned a [dim, metric, n, avg] ranking finding into a dual-axis COMBO
    //      of metric vs row-count — second-guessing the backend and discarding exhibit.order.
    if (!option && catCol && (hint === "bar" || hint === "bar_horizontal")) {
      option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff },
                         { horizontal: orientH(nCats <= HORIZONTAL_MAX_CATS), diverging: _isChangeMetric });
      defaultH = Math.max(110, nCats * 46 + 44);
    }
    // 13b. Explicit CA-4 forms — the delta pair ("change" job) and grouped bars.
    if (!option && hint === "delta_bar" && catCol) {
      const numericIdxs = chartNumericCols.map((n) => columns.indexOf(n)).filter((i) => i >= 0);
      const d = numericIdxs.length >= 2 ? chooseMultiMeasure(columns, rows, numericIdxs) : null;
      if (d?.mode === "delta" && d.pair) {
        option = deltaBarOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [columns[d.pair[0]], columns[d.pair[1]]], labels: lbls });
        defaultH = Math.max(110, nCats * 46 + 44);
      } else {
        // No detectable pair → the change is already a single signed measure.
        option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff }, { horizontal: orientH(nCats <= HORIZONTAL_MAX_CATS), diverging: true });
        defaultH = Math.max(110, nCats * 46 + 44);
      }
    }
    if (!option && hint === "grouped_bar" && catCol && chartNumericCols.length >= 2) {
      option = groupedBarOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: chartNumericCols.slice(0, 4) });
      defaultH = 300;
    }

    // 14. Categorical default → delta / grouped / change-bar / horizontal bar (never a dual axis)
    if (!option && catCol) {
      if (chartNumericCols.length >= 2 && catCols.length === 1) {
        const numericIdxs = chartNumericCols.map((n) => columns.indexOf(n)).filter((i) => i >= 0);
        const d = chooseMultiMeasure(columns, rows, numericIdxs);
        const primary = columns[d.barIdx] ?? chartNumericCols[0];
        if (d.mode === "delta" && d.pair) { option = deltaBarOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [columns[d.pair[0]], columns[d.pair[1]]], labels: lbls }); defaultH = Math.max(110, nCats * 46 + 44); }
        else if (d.mode === "grouped" && d.groupIdxs.length >= 2) { option = groupedBarOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: d.groupIdxs.map((i) => columns[i]) }); defaultH = 300; }
        else { option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [primary], labels: lbls, exhibit: exhibitEff }, { horizontal: orientH(nCats <= HORIZONTAL_MAX_CATS) }); defaultH = Math.max(110, nCats * 46 + 44); }
      } else if (_isChangeMetric) {
        option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff }, { horizontal: orientH(nCats <= HORIZONTAL_MAX_CATS), diverging: true });
        defaultH = Math.max(110, nCats * 46 + 44);
      } else {
        option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls, exhibit: exhibitEff }, { horizontal: orientH(nCats <= HORIZONTAL_MAX_CATS) });
        defaultH = Math.max(110, nCats * 46 + 44);
      }
    }
    // 15. Final fallback — line on date + measure
    if (!option && dateCol && numCol) { option = lineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: lbls, exhibit: exhibitEff }); defaultH = 350; }

    if (!option) return null;
    // Org-level chart palette (Settings ▸ Appearance) applies when the chart hasn't set
    // its own colorScheme; a per-chart Customize colour still wins.
    const built = applyCustom(option, custom);
    if (!custom?.colorScheme) {
      const pal = effectiveChartPalette();
      if (pal && SCHEME_PALETTES[pal]) built.color = SCHEME_PALETTES[pal];
    }
    return { option: built, defaultH };
}
