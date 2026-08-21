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

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { EChart } from "@/components/charts/echarts/EChart";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { chartEngine, CHART_ENGINE_DEFAULT, CHART_ENGINE_EVENT, type ChartEngine } from "@/lib/chartEngine";
import { downloadChartPng, type ChartInstance } from "@/lib/chartExport";
import { resolveChartOption, type ChartCustom } from "@/components/charts/resolveOption";
import type { ExhibitSpec } from "@/components/charts/exhibit";
import { Icon } from "@/components/ui/icon";

/** User chart styling applied as a generic post-pass over the built ECharts option —
 *  lets the Query Builder Customize tab override colours / number format / legend /
 *  axis titles. All fields optional; a null/empty custom is a no-op, so non-customizing
 *  callers (chat, reports, explorer) are unaffected. */
// ChartCustom moved to resolveOption.ts with the resolver; re-exported for existing importers.
export type { ChartCustom };

// ── Customize post-pass (ECharts) ────────────────────────────────────────────

// SCHEME_PALETTES (named categorical palettes) now live in @/lib/chartPalettes.


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
  fitHeight = null,
  columnUnits,
  exhibit = null,
  onSelect,
  onInstanceReady,
}: {
  columns: string[];
  rows: unknown[][];
  chartType?: string | null;
  chartConfig?: Record<string, unknown> | null;
  title?: string;
  /** Scale the computed chart height (e.g. 0.75 for a compact briefing card). */
  heightScale?: number;
  /** Fill an exact pixel height instead of the data-derived default — for a resizeable
   *  card/canvas node where the chart should grow to fill the box (drops the 350px + few-cat
   *  width caps). */
  fitHeight?: number | null;
  /** Click a mark to drill in — receives the datum behind the clicked bar/point. */
  onSelect?: (datum: Record<string, unknown>) => void;
  /** Hand the live chart instance up to a chromeless caller (e.g. so a side-panel
   *  "Download PNG" can export a chart rendered with chrome={false}). Engine-neutral:
   *  Vega produces its image asynchronously, so getDataURL may return a promise. */
  onInstanceReady?: (inst: ChartInstance) => void;
  /** Render the hover toolbar (labels + download) and drag-to-resize handle. */
  chrome?: boolean;
  /** Externally control data-label visibility (chromeless mode). */
  showLabels?: boolean;
  /** User styling overrides applied as a post-pass over the option. */
  custom?: ChartCustom | null;
  /** Authoritative per-column display unit from the backend finding ({"metric_total":"percent"}),
   *  so a rate renders "41.0%" on the axis + labels instead of the raw "0.4". */
  columnUnits?: Record<string, string> | null;
  /** Optional backend exhibit spec (semantic color mode, reference lines, point labels,
   *  quadrant dividers). Absent → rendering is byte-identical to before. */
  exhibit?: ExhibitSpec | null;
}) {
  const outerRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<ChartInstance | null>(null);

  // Which engine draws this chart. Read on every render and re-read when the override
  // changes, so flipping engines re-renders every mounted chart without a reload — the
  // only way to compare them on the SAME screen with the SAME data.
  // Seeded with the BUILD-TIME answer, not the stored one. The server has no localStorage,
  // so reading the override during the first client render makes the two trees disagree —
  // and because the engines compute different heights, React reports a hydration failure and
  // throws the server tree away. The effect below applies any override after mount.
  const [engine, setEngine] = useState<ChartEngine>(CHART_ENGINE_DEFAULT);
  useEffect(() => {
    const sync = () => setEngine(chartEngine());
    sync();
    window.addEventListener(CHART_ENGINE_EVENT, sync);
    return () => window.removeEventListener(CHART_ENGINE_EVENT, sync);
  }, []);
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
    void downloadChartPng(instRef.current, title);
  }

  // Re-render + rebuild the option when org settings change, so the currency symbol /
  // chart palette / relabelled fields apply even if the cache populates after first render.
  const orgV = useOrgSettings();

  // Build the option + default height. Memoized so its identity is stable across
  // renders (EChart re-inits when the option object changes) — only rebuilds when
  // data / type / labels / custom / org settings change. userH & heightScale affect height only.
  type Built =
    | { engine: "echarts"; option: EChartsOption; defaultH: number; xCategories: number }
    | { engine: "vega"; spec: Record<string, unknown>; defaultH: number; xCategories: number };

  const built = useMemo<Built | null>(() => {
    if (engine === "vega") {
      // Same intent, different target language.
      const v = resolveVegaSpec({ columns, rows, chartType, showLabels, format: custom?.format ?? null,
                                  xTitle: custom?.xTitle ?? null, yTitle: custom?.yTitle ?? null,
                                  orient: custom?.orient ?? null,
                                  transform: custom?.transform ?? null });
      // null here means "tier 1 does not draw this type" — fall through to ECharts, which
      // still draws every type. parity.test.ts pins that both engines agree about refusal.
      if (v) return { engine: "vega", spec: v.spec, defaultH: v.defaultH, xCategories: v.xCategories };
    }
    const e = resolveChartOption({ columns, rows, chartType, chartConfig, custom, columnUnits, exhibit, showLabels });
    if (!e) return null;
    const xd = (e.option as { xAxis?: { data?: unknown[] } })?.xAxis?.data;
    return { engine: "echarts", option: e.option, defaultH: e.defaultH,
             xCategories: Array.isArray(xd) ? xd.length : 0 };
    // orgV: currency / palette / relabel settings feed the resolver via module reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, rows, chartType, chartConfig, showLabels, custom, orgV, columnUnits, exhibit, engine]);

  if (!built) return null;
  const fill = !!(fitHeight && fitHeight > 0);
  const chartH = fill ? Math.round(fitHeight!) : Math.round((userH ?? built.defaultH) * heightScale);

  return (
    <div className="mt-2 w-full group/chart">
      {chrome && (
        <div className="flex justify-end h-6 mb-0.5 opacity-0 group-hover/chart:opacity-100 transition-opacity gap-1">
          <button
            onClick={() => setShowLabels((s) => !s)}
            title={showLabels ? "Hide data labels" : "Show data labels"}
            className={`w-6 h-6 flex items-center justify-center rounded transition-colors ${showLabels ? "bg-blue-500/20 text-blue-300" : "bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200"}`}
          >
            <Icon name="expand" size={14} />
          </button>
          <button
            onClick={handleDownloadPng}
            title="Download chart as PNG"
            className="w-6 h-6 flex items-center justify-center rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-500 hover:text-zinc-200 transition-colors"
          >
            <Icon name="download" size={16} label="Download chart as PNG" />
          </button>
        </div>
      )}

      {/* Chart viewport — caps at 350px with internal scroll; the chart renders at its natural height.
          A vertical bar chart with only a few categories no longer stretches across the full panel
          (3 skinny bars adrift in empty space) — width scales with the category count instead. */}
      {(() => {
        const _catN = built.xCategories;
        // In fill mode the chart takes the whole box (no 350px cap, no few-category width cap).
        const _maxW = fill ? undefined : (_catN > 0 && _catN <= 6 ? Math.max(340, _catN * 130 + 150) : undefined);
        const ready = (inst: ChartInstance) => { instRef.current = inst; onInstanceReady?.(inst); };
        return (
      <div ref={outerRef} style={{ maxHeight: fill ? undefined : 350, height: fill ? chartH : undefined, overflowY: "auto", overflowX: "hidden", width: "100%", maxWidth: _maxW }}>
        {built.engine === "vega"
          ? <VegaChart spec={built.spec} height={chartH} onSelect={onSelect} onReady={ready} />
          : <EChart option={built.option} height={chartH} onSelect={onSelect} onReady={ready} />}
      </div>
        );
      })()}

      {chrome && (
        <div onMouseDown={startDrag} className="flex items-center justify-center h-3 cursor-ns-resize group/drag">
          <div className="w-10 h-0.5 rounded-[var(--r-pill)] bg-zinc-800 group-hover/drag:bg-zinc-600 transition-colors" />
        </div>
      )}
    </div>
  );
}
