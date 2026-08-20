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
import { useOrgSettings } from "@/lib/useOrgSettings";
import { EChart } from "@/components/charts/echarts/EChart";
import { resolveChartOption, type ChartCustom } from "@/components/charts/resolveOption";
import type { ExhibitSpec } from "@/components/charts/exhibit";

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
  /** Hand the live ECharts instance up to a chromeless caller (e.g. so a side-panel
   *  "Download PNG" can export a chart rendered with chrome={false}). */
  onInstanceReady?: (inst: { getDataURL: (o?: { type?: string; pixelRatio?: number; backgroundColor?: string }) => string }) => void;
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
  const built = useMemo<{ option: EChartsOption; defaultH: number } | null>(
    () => resolveChartOption({ columns, rows, chartType, chartConfig, custom, columnUnits, exhibit, showLabels }),
    // orgV: currency / palette / relabel settings feed the resolver via module reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns, rows, chartType, chartConfig, showLabels, custom, orgV, columnUnits, exhibit]);

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

      {/* Chart viewport — caps at 350px with internal scroll; the chart renders at its natural height.
          A vertical bar chart with only a few categories no longer stretches across the full panel
          (3 skinny bars adrift in empty space) — width scales with the category count instead. */}
      {(() => {
        const _xd = (built.option as { xAxis?: { data?: unknown[] } })?.xAxis?.data;
        const _catN = Array.isArray(_xd) ? _xd.length : 0;
        // In fill mode the chart takes the whole box (no 350px cap, no few-category width cap).
        const _maxW = fill ? undefined : (_catN > 0 && _catN <= 6 ? Math.max(340, _catN * 130 + 150) : undefined);
        return (
      <div ref={outerRef} style={{ maxHeight: fill ? undefined : 350, height: fill ? chartH : undefined, overflowY: "auto", overflowX: "hidden", width: "100%", maxWidth: _maxW }}>
        <EChart option={built.option} height={chartH} onSelect={onSelect} onReady={(inst) => { instRef.current = inst; onInstanceReady?.(inst); }} />
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
