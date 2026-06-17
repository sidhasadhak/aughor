/* ════════════════════════════════════════════════════════════════════════════
   AUGHOR v2 — VEGA-LITE THEME
   ────────────────────────────────────────────────────────────────────────────
   Elevates the EXISTING Vega chart engine (components/Chart.tsx → VegaChart) to
   the v2 look without rewriting any spec-building branch. Returns a Vega-Lite
   `config` object + categorical range, read LIVE from CSS custom properties so
   it flips automatically with dark/light.

   ── INTEGRATION (Chart.tsx / VegaChart.tsx) ──────────────────────────────────
   1. Build the spec exactly as today.
   2. Merge this config in before rendering:
          import { vegaV2Config, vegaV2Range } from "@/aughor-v2/charts/vega-theme-v2";
          const themed = { ...spec, config: { ...vegaV2Config(), ...(spec.config ?? {}) } };
   3. Feed `vegaV2Range()` to any categorical color scale
      (replaces the inline AUG_PALETTE range in lib/palette.ts usage).
   4. Replace hardcoded mark colors ("#818cf8" bars, "#10b981" lines, "#f59e0b"
      pareto, PNG bg "#131c27") with the tokens below — see MAPPING.md › Charts.

   Re-read on theme change (the values are resolved at call time, so just
   re-render the chart when `data-theme` flips — VegaChart already re-renders on
   prop change; pass the current theme as a key or dep).
   ════════════════════════════════════════════════════════════════════════════ */

function cssVar(name: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Ordered categorical series palette (chart-1..6 then extended hues). */
export function vegaV2Range(): string[] {
  return [
    cssVar("--chart-1", "#4C8EEE"),
    cssVar("--chart-2", "#2EC87B"),
    cssVar("--chart-3", "#E0AD00"),
    cssVar("--chart-4", "#8B68D8"),
    cssVar("--chart-5", "#E64848"),
    cssVar("--chart-6", "#30B8E0"),
    "#F97316", "#EC4899", "#10B981", "#6366F1", "#F59E0B", "#14B8A6",
    "#A855F7", "#22D3EE", "#84CC16", "#E879F9", "#34D399", "#FB923C",
  ];
}

/** Single-series mark colors — use instead of the old hardcoded hexes. */
export const vegaV2Marks = {
  get bar()        { return cssVar("--chart-1", "#4C8EEE"); },
  get line()       { return cssVar("--chart-2", "#2EC87B"); },
  get paretoLine() { return cssVar("--chart-3", "#E0AD00"); },
  get reference()  { return cssVar("--chart-tick", "#7C8699"); },
  get pngBg()      { return cssVar("--bg-2", "#141925"); },
  /** rounded bar tops — the v2 signature */
  cornerRadiusEnd: 3,
};

/** Vega-Lite top-level `config` — axes, grid, legend, view, fonts, rounded bars. */
export function vegaV2Config() {
  const tick = cssVar("--chart-tick", "#7C8699");
  const axis = cssVar("--chart-axis", "rgba(255,255,255,.10)");
  const grid = cssVar("--chart-grid", "rgba(255,255,255,.05)");
  const t1   = cssVar("--t1", "#EAEDF3");
  const t3   = cssVar("--t3", "#6B7689");
  const font = "DM Sans, system-ui, sans-serif";

  return {
    background: "transparent",
    font,
    view: { stroke: "transparent" },
    axis: {
      labelColor: tick, titleColor: t3, tickColor: axis, domainColor: axis,
      gridColor: grid, gridWidth: 1, labelFontSize: 11, titleFontSize: 11,
      titleFontWeight: 600, titlePadding: 8, labelPadding: 6, tickSize: 0,
    },
    axisX: { domain: true, grid: false, labelAngle: 0 },
    axisY: { domain: false, ticks: false },
    legend: {
      labelColor: t1, titleColor: t3, labelFontSize: 11, titleFontSize: 10,
      titleFontWeight: 700, symbolSize: 90, symbolType: "circle", orient: "bottom",
    },
    bar: { cornerRadiusEnd: 3 },
    line: { strokeWidth: 2, strokeCap: "round", strokeJoin: "round" },
    point: { size: 36, filled: true },
    arc: { innerRadius: 0 },
    range: { category: vegaV2Range() },
    title: { color: t1, fontSize: 13, fontWeight: 600, anchor: "start", dy: -4 },
  };
}
