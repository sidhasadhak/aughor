"use client";

/**
 * Chart — the reusable chart component. Given SQL-shaped { columns, rows }
 * (+ optional backend chartConfig), it resolves the column roles, picks the
 * right chart type (the same data-shape rules as before), builds an Apache
 * ECharts `option` via the pure builders in ./charts/echarts, and renders it
 * through <EChart> with download-PNG + drag-to-resize + labels chrome.
 *
 * This is the ECharts replacement for the former Vega-Lite engine. The PUBLIC
 * PROPS are unchanged, so every surface (chat, report, exploration, query
 * builder, canvas, briefing) keeps working without edits. Chart-type selection
 * reuses scoreDualAxis (combo vs grouped vs bar); column roles via
 * ./charts/columnRoles; formatting/date logic lives inside the builders
 * (@/lib/format). The measure-additivity / percent-leak fixes are preserved by
 * the builders' per-field `valueFormatter`.
 */

import React, { useMemo, useRef, useState } from "react";
import DownloadIcon from "@atlaskit/icon/core/download";
import type { EChartsOption } from "echarts";
import { format as d3format } from "d3-format";
import { SCHEME_PALETTES } from "@/lib/chartPalettes";
import { effectiveChartPalette } from "@/lib/orgSettings";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { EChart } from "@/components/charts/echarts/EChart";
import {
  lineOption, multiLineOption, smallMultiplesOption, barOption, groupedBarOption, stackedBarOption,
  pieOption, scatterOption, comboOption, heatmapOption, treemapOption, paretoOption,
} from "@/components/charts/echarts/builders";
import {
  SHARE_COL, CHANGE_METRIC_COL, TIME_LABEL_COL, INSTRUMENTATION_COL, PREFER_COL, classifyColumns,
} from "@/components/charts/columnRoles";
import { scoreDualAxis } from "@/components/charts/chartTypeInference";

/** User chart styling applied as a generic post-pass over the built ECharts option —
 *  lets the Query Builder Customize tab override colours / number format / legend /
 *  axis titles. All fields optional; a null/empty custom is a no-op, so non-customizing
 *  callers (chat, reports, explorer) are unaffected. */
export interface ChartCustom {
  format?: string;        // d3 number format for the quantitative axis (e.g. ",.0f", "$,.2f", "~s")
  colorScheme?: string;   // categorical palette name (e.g. "tableau10", "set2")
  xTitle?: string;
  yTitle?: string;
  legend?: "right" | "bottom" | "top" | "left" | "none";
}

// ── Customize post-pass (ECharts) ────────────────────────────────────────────

// SCHEME_PALETTES (named categorical palettes) now live in @/lib/chartPalettes.

type AxisLike = Record<string, unknown>;
function mapAxes(ax: unknown, fn: (a: AxisLike) => AxisLike): unknown {
  if (Array.isArray(ax)) return ax.map((a) => fn(a as AxisLike));
  if (ax && typeof ax === "object") return fn(ax as AxisLike);
  return ax;
}

function applyCustom(option: EChartsOption, custom?: ChartCustom | null): EChartsOption {
  if (!custom || !(custom.format || custom.colorScheme || custom.xTitle || custom.yTitle || custom.legend)) return option;
  const o: EChartsOption = { ...option };

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

export function Chart({
  columns,
  rows,
  chartType = "auto",
  chartConfig = null,
  title = "chart",
  chrome = true,
  showLabels: showLabelsProp,
  custom = null,
  heightScale = 1,
  columnUnits,
  onSelect,
}: {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
  chartConfig?: Record<string, unknown> | null;
  title?: string;
  /** Scale the computed chart height (e.g. 0.75 for a compact briefing card). */
  heightScale?: number;
  /** Click a mark to drill in — receives the datum behind the clicked bar/point. */
  onSelect?: (datum: Record<string, unknown>) => void;
  /** Render the hover toolbar (labels + download) and drag-to-resize handle. */
  chrome?: boolean;
  /** Externally control data-label visibility (chromeless mode). */
  showLabels?: boolean;
  /** User styling overrides applied as a post-pass over the option. */
  custom?: ChartCustom | null;
  /** Authoritative per-column display unit from the backend finding ({"metric_total":"percent"}),
   *  so a rate renders "41.0%" on the axis + labels instead of the raw "0.4". */
  columnUnits?: Record<string, string> | null;
}) {
  const outerRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<{ getDataURL: (o?: { type?: string; pixelRatio?: number; backgroundColor?: string }) => string } | null>(null);
  // userH = null means "use computed default height". Set by drag handle.
  const [userH, setUserH] = useState<number | null>(null);
  const [showLabelsState, setShowLabels] = useState(false);
  const showLabels = showLabelsProp ?? showLabelsState;

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = outerRef.current?.clientHeight ?? 300;
    function onMove(ev: MouseEvent) {
      const newH = Math.max(80, startH + (ev.clientY - startY));
      if (outerRef.current) outerRef.current.style.minHeight = `${newH}px`;
    }
    function onUp(ev: MouseEvent) {
      if (outerRef.current) outerRef.current.style.minHeight = "";
      setUserH(Math.max(80, startH + (ev.clientY - startY)));
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function handleDownloadPng() {
    const inst = instRef.current;
    if (!inst) return;
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg-2").trim() || "#131c27";
    const url = inst.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: bg });
    const fname = title.replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
    const a = Object.assign(document.createElement("a"), { href: url, download: fname });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }

  // Re-render + rebuild the option when org settings change, so the currency symbol /
  // chart palette / relabelled fields apply even if the cache populates after first render.
  const orgV = useOrgSettings();

  // Build the option + default height. Memoized so its identity is stable across
  // renders (EChart re-inits when the option object changes) — only rebuilds when
  // data / type / labels / custom / org settings change. userH & heightScale affect height only.
  const built = useMemo<{ option: EChartsOption; defaultH: number } | null>(() => {
    if (!rows.length || !columns.length) return null;

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
    const ID_COL = /(^|_)(id|key|sk|pk|code|uuid|guid|hash)$/i;
    const NAME_COL = /(name|title|label|desc|description|channel|category|region|country|city|state|store|product|customer|item|page|segment|brand|merchant|franchise|email|url)/i;
    const catCol = catCols.find((c) => NAME_COL.test(c) && !ID_COL.test(c)) ?? catCols.find((c) => !ID_COL.test(c)) ?? catCols[0];
    const catCol2 = catCols.find((c) => c !== catCol) ?? catCols[1];
    const CHANGE_PREFER_COL = /(change|delta|growth|pct_change|percent_change|_chg$|_diff$)/i;
    const baseNumCol = chartNumericCols.find((c) => PREFER_COL.test(c)) ?? chartNumericCols.find((c) => !CHANGE_METRIC_COL.test(c)) ?? chartNumericCols[0];
    const changeNumCol = chartNumericCols.find((c) => CHANGE_PREFER_COL.test(c)) ?? chartNumericCols.find((c) => PREFER_COL.test(c)) ?? chartNumericCols[0];
    const numCol = (_isChangeMetric && catCol) ? changeNumCol : baseNumCol;
    const hint = (chartType ?? "auto").toLowerCase();
    if (!numCol) return null;

    const isTimeLabel = catCol ? TIME_LABEL_COL.test(catCol) : false;
    const _stackUnique = catCol ? new Set(data.map((d) => d[catCol])).size : 0;
    const nCats = catCol ? new Set(data.map((d) => d[catCol])).size : 0;

    // Pareto detection (concentration columns) — same logic as before.
    const PARETO_SHARE = /(share|cumulative|cum_pct|pct_of_total|of_total|contribution)/i;
    const paretoShareCol = columns.find((c) => PARETO_SHARE.test(c));
    const paretoCat: string | null = catCol ?? columns.find((c) => c !== paretoShareCol && ID_COL.test(c)) ?? null;
    const paretoMeasure: string | null =
      numericCols.find((c) => c !== paretoShareCol && !PARETO_SHARE.test(c) && !SHARE_COL.test(c) && !ID_COL.test(c))
      ?? (hint === "pareto" ? numCol : null);
    const PARETO_UPGRADE = new Set(["auto", "bar", "bar_horizontal", "bar_vertical", "treemap", "pie"]);
    const wantPareto =
      (hint === "pareto" || (PARETO_UPGRADE.has(hint) && !!paretoShareCol && rows.length >= 4))
      && !!paretoCat && !!paretoMeasure && paretoCat !== paretoMeasure;

    // Backend-provided chart config (LLM-generated alongside SQL). TRUST IT ONLY WHEN ITS
    // FIELD ROLES ARE COHERENT WITH THE DATA — the LLM sometimes mis-maps the axes (e.g.
    // puts the MEASURE on x_field), which renders a broken chart (values on the category
    // axis, blank bars). When the config is incoherent we fall through to the data-shape
    // inference below, which is robust. (The config is dropped on history restore, so a
    // validated-or-inferred chart also makes a live answer match what History shows.)
    const cc = chartConfig;
    const ccType = cc?.type as string | undefined;
    const ccX = cc?.x_field as string | undefined;
    const ccY = cc?.y_field as string | undefined;
    const ccY2 = cc?.y_field_2 as string | undefined;
    const ccColor = cc?.color_field as string | undefined;
    const _colSet = new Set(columns);
    const _xReal = !!ccX && _colSet.has(ccX);
    const _xNum = !!ccX && numericCols.includes(ccX);
    const _yNum = !!ccY && numericCols.includes(ccY);  // the measure MUST be numeric
    const _ccType = (ccType ?? "").toLowerCase();
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
      if (backendHint === "combo" && ccY2) { option = comboOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF, ccY2] }); defaultH = 350; }
      else if (backendHint === "line" || backendHint === "multi_line") {
        option = ccColor
          ? multiLineOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], color: ccColor, xKind: "time" })
          : lineOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], xKind: "time" });
        defaultH = 350;
      }
      else if (backendHint === "bar" || backendHint === "bar_horizontal") { option = barOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF], labels: lbls }); defaultH = 350; }
      else if (backendHint === "scatter") { option = scatterOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF] }); defaultH = 350; }
      else if (backendHint === "pie") { option = pieOption({ rows: data, units: columnUnits ?? undefined, x: xF, ys: [yF] }); defaultH = 350; }
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
    if (!option && (hint === "stacked_bar" || (hint === "auto" && catCol && (catCol2 || dateCol) && !_isChangeMetric && _stackUnique <= 6))) {
      const x = dateCol ?? catCol;
      const color = dateCol ? catCol : catCol2;
      if (x && color) { option = stackedBarOption({ rows: data, units: columnUnits ?? undefined, x, ys: [numCol], color, xKind: dateCol ? "time" : "category" }, SHARE_COL.test(numCol)); defaultH = 280; }
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
    if (!option && dateCol && !catCol && (hint === "bar" || hint === "bar_horizontal")) { option = barOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: true }, { order: "time" }); defaultH = 220; }
    // 11. Line / area (timeseries)
    if (!option && dateCol && !catCol && (hint === "line" || hint === "area" || hint === "auto")) { option = lineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: lbls }, hint === "area"); defaultH = 220; }
    // 12. Vertical bar (explicit)
    if (!option && catCol && hint === "bar_vertical") { option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls }, { order: isTimeLabel ? "keep" : "value" }); defaultH = 260; }
    // 13. Scatter (explicit)
    if (!option && hint === "scatter" && numericCols.length >= 2) { option = scatterOption({ rows: data, units: columnUnits ?? undefined, x: numericCols[0], ys: [numericCols[1]] }); defaultH = 300; }
    // 14. Categorical default → combo / grouped / change-bar / horizontal bar
    if (!option && catCol) {
      if (chartNumericCols.length >= 2 && catCols.length === 1) {
        const numericIdxs = chartNumericCols.map((n) => columns.indexOf(n)).filter((i) => i >= 0);
        const d = scoreDualAxis(columns, rows, numericIdxs);
        const primary = columns[d.barIdx] ?? chartNumericCols[0];
        if (d.combo && d.lineIdx != null) { option = comboOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [primary, columns[d.lineIdx]] }); defaultH = 350; }
        else if (d.groupIdxs.length >= 2) { option = groupedBarOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: d.groupIdxs.map((i) => columns[i]) }); defaultH = 300; }
        else { option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [primary], labels: lbls }, { horizontal: true }); defaultH = Math.max(110, nCats * 46 + 44); }
      } else if (_isChangeMetric) {
        option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls }, { horizontal: true, diverging: true });
        defaultH = Math.max(110, nCats * 46 + 44);
      } else {
        option = barOption({ rows: data, units: columnUnits ?? undefined, x: catCol, ys: [numCol], labels: lbls }, { horizontal: true });
        defaultH = Math.max(110, nCats * 46 + 44);
      }
    }
    // 15. Final fallback — line on date + measure
    if (!option && dateCol && numCol) { option = lineOption({ rows: data, units: columnUnits ?? undefined, x: dateCol, ys: [numCol], xKind: "time", labels: lbls }); defaultH = 350; }

    if (!option) return null;
    // Org-level chart palette (Settings ▸ Appearance) applies when the chart hasn't set
    // its own colorScheme; a per-chart Customize colour still wins.
    const built = applyCustom(option, custom);
    if (!custom?.colorScheme) {
      const pal = effectiveChartPalette();
      if (pal && SCHEME_PALETTES[pal]) built.color = SCHEME_PALETTES[pal];
    }
    return { option: built, defaultH };
  }, [columns, rows, chartType, chartConfig, showLabels, custom, orgV, columnUnits]);

  if (!built) return null;
  const chartH = Math.round((userH ?? built.defaultH) * heightScale);

  return (
    <div className="mt-2 w-full group/chart">
      {chrome && (
        <div className="flex justify-end h-6 mb-0.5 opacity-0 group-hover/chart:opacity-100 transition-opacity gap-1">
          <button
            onClick={() => setShowLabels((s) => !s)}
            title={showLabels ? "Hide data labels" : "Show data labels"}
            className={`w-6 h-6 flex items-center justify-center rounded transition-colors ${showLabels ? "bg-blue-500/20 text-blue-300" : "bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200"}`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 7V4h3" /><path d="M4 17v3h3" /><path d="M20 7V4h-3" /><path d="M20 17v3h-3" /><path d="M9 9h6v6H9z" />
            </svg>
          </button>
          <button
            onClick={handleDownloadPng}
            title="Download chart as PNG"
            className="w-6 h-6 flex items-center justify-center rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200 transition-colors"
          >
            <DownloadIcon label="Download chart as PNG" size="small" />
          </button>
        </div>
      )}

      {/* Chart viewport — caps at 350px with internal scroll; the chart renders at its natural height. */}
      <div ref={outerRef} style={{ maxHeight: 350, overflowY: "auto", overflowX: "hidden", width: "100%" }}>
        <EChart option={built.option} height={chartH} onSelect={onSelect} onReady={(inst) => { instRef.current = inst; }} />
      </div>

      {chrome && (
        <div onMouseDown={startDrag} className="flex items-center justify-center h-3 cursor-ns-resize group/drag">
          <div className="w-10 h-0.5 rounded-full bg-zinc-800 group-hover/drag:bg-zinc-600 transition-colors" />
        </div>
      )}
    </div>
  );
}
