"use client";

/**
 * Chart — the reusable chart component, and the ONE seam every surface goes through.
 * Given SQL-shaped { columns, rows } (+ the backend's chart hint, config and exhibit) it
 * resolves a Vega-Lite spec — or a hand-authored Vega one for the four forms Vega-Lite
 * cannot express — and renders it with download-PNG, drag-to-resize and label chrome.
 *
 * The engine history is Observable Plot → Vega-Lite → ECharts → Vega-Lite (2026-08).
 * The PUBLIC PROPS have not changed across any of it, which is why every surface (chat,
 * report, exploration, query builder, canvas, briefing) kept working through each move.
 * Column roles come from ./charts/columnRoles and type inference from
 * ./charts/chartTypeInference — both engine-neutral, and both older than either engine.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { resolveTier3Spec } from "@/components/charts/vega/tier3";
import { downloadChartPng, type ChartInstance } from "@/lib/chartExport";
import type { ChartCustom } from "@/components/charts/chartCustom";
import type { ExhibitSpec } from "@/components/charts/exhibit";
import { Icon } from "@/components/ui/icon";

/** User chart styling applied as a generic post-pass over the built ECharts option —
 *  lets the Query Builder Customize tab override colours / number format / legend /
 *  axis titles. All fields optional; a null/empty custom is a no-op, so non-customizing
 *  callers (chat, reports, explorer) are unaffected. */
// Re-exported for the five components that import it through this module.
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
  type Built = { spec: Record<string, unknown>; defaultH: number; xCategories: number; tier: 1 | 3 };

  const built = useMemo<Built | null>(() => {
    // Tier 3 first — the four forms Vega-Lite cannot express are hand-authored Vega.
    const t3 = resolveTier3Spec({ columns, rows, chartType: String(chartType ?? "") });
    if (t3) return { spec: t3.spec, defaultH: t3.defaultH, xCategories: 0, tier: 3 };

    const v = resolveVegaSpec({
      columns, rows, chartType, showLabels, exhibit,
      format: custom?.format ?? null,
      xTitle: custom?.xTitle ?? null,
      yTitle: custom?.yTitle ?? null,
      orient: custom?.orient ?? null,
      transform: custom?.transform ?? null,
    });
    // null is the honest-refusal verdict: data with no chart in it renders none, and the
    // surface's table view carries it. There is no second engine to fall back to.
    return v ? { spec: v.spec, defaultH: v.defaultH, xCategories: v.xCategories, tier: 1 } : null;
    // orgV: currency / palette / relabel settings feed the resolver via module reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, rows, chartType, chartConfig, showLabels, custom, orgV, columnUnits, exhibit]);

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
        // In fill mode the chart takes the whole box (no few-category width cap).
        const _maxW = fill ? undefined : (_catN > 0 && _catN <= 6 ? Math.max(340, _catN * 130 + 150) : undefined);
        const ready = (inst: ChartInstance) => { instRef.current = inst; onInstanceReady?.(inst); };
        /* A chart is a picture, not a viewport. It used to cap at 350px and scroll inside
           that box, so a ranking with many categories became a thing you scrolled through
           instead of a shape you read — and the axis scrolled out of sight with it. The
           chart now renders at its natural height and the card grows; orientation flips to
           upright before the category count gets that far (HORIZONTAL_MAX_CATS). */
        return (
      <div ref={outerRef} style={{ height: fill ? chartH : undefined, overflow: "hidden", width: "100%", maxWidth: _maxW }}>
        <VegaChart spec={built.spec} tier={built.tier} height={chartH} onSelect={onSelect} onReady={ready} />
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
