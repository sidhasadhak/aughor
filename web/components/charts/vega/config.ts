/**
 * config.ts — the Aughor Vega-Lite config, built LIVE from the same design tokens
 * the ECharts theme reads (Phase 1 spike, docs/CHART_ENGINE_VEGA_DESIGN_2026-08-21).
 *
 * This is the file that has to be right, because it is the file that failed last time:
 * the 2026-06 exit from Vega-Lite was driven by "the fragile remapLegacyColors hex-walk"
 * — colours retrofitted by walking a produced spec. Nothing here walks a spec. Tokens
 * resolve to ONE `config` object that is injected at compile time, which is also the
 * property that lets a stored tier-2/tier-3 spec keep following the token layer: the
 * theme is never baked into the spec.
 *
 * Palette values come from components/charts/palette.ts, the CVD-validated source the
 * `lint:palette` gate parses by path. It moved out of the ECharts tree when that tree was
 * deleted; the gate moved with it.
 */

import { CHART_SERIES, CHART_DEEMPH, CHART_SIGN, CHART_SURFACE, type ChartMode } from "@/components/charts/palette";

export interface VegaTokens {
  palette: string[];
  deemph: string;
  /** Sign pair — a good/bad meaning, never a series identity. */
  sign: { pos: string; neg: string };
  axis: string;
  grid: string;
  tick: string;
  t1: string;
  t3: string;
  surface: string;
  /** The font stack the surrounding UI actually renders, resolved from the DOM. */
  font: string;
}

/** Read a CSS custom property off <html>, with a dark-mode literal fallback for SSR. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * Resolve every token the chart config needs from the current CSS context.
 *
 * `font` is read as the COMPUTED font-family of the chart's own container rather than
 * baked as a literal. ECharts cannot do this — its canvas renderer writes the font string
 * into the 2D context, which does not resolve `var(--font-ui)` — the retired ECharts theme
 * had to keep a hardcoded stack in sync by hand. Vega renders SVG, so the chart simply
 * wears whatever the UI around it wears.
 */
export function readVegaTokens(el?: Element | null): VegaTokens {
  const mode: ChartMode = "dark";
  const font =
    typeof window === "undefined"
      ? "system-ui, sans-serif"
      : getComputedStyle(el ?? document.body).fontFamily || "system-ui, sans-serif";
  return {
    palette: CHART_SERIES[mode].map((hex, k) => cssVar(`--chart-${k + 1}`, hex)),
    deemph: cssVar("--chart-deemph", CHART_DEEMPH[mode]),
    sign: {
      pos: cssVar("--chart-threshold-target", CHART_SIGN[mode].pos),
      neg: cssVar("--chart-threshold-crit", CHART_SIGN[mode].neg),
    },
    axis: cssVar("--chart-axis", "#2F3D48"),
    grid: cssVar("--chart-grid", "#232F39"),
    tick: cssVar("--chart-tick", "#93A7B6"),
    t1: cssVar("--t1", "#EAEDF3"),
    t3: cssVar("--t3", "#6B7689"),
    surface: cssVar("--bg-2", CHART_SURFACE[mode]),
    font,
  };
}

/**
 * The LIGHT token set for headless print rendering — no document to read from, so the
 * values are the light literals — the print path has no document to read them from.
 */
export function printVegaTokens(): VegaTokens {
  return {
    palette: [...CHART_SERIES.light],
    deemph: CHART_DEEMPH.light,
    sign: { ...CHART_SIGN.light },
    axis: "#D3DAE0",
    grid: "#E6EBEF",
    tick: "#5F7281",
    t1: "#11171C",
    t3: "#6C7E8C",
    surface: "#FFFFFF",
    font: "sans-serif",
  };
}

/**
 * Build the Vega-Lite config from resolved tokens. Mark specs mirror the ECharts theme
 * one-for-one so the Phase 1 comparison is about the ENGINE, not about two different
 * designers: 2px round-capped lines, ≥8px points with a 2px surface ring, SQUARE bar ends,
 * a 1px surface seam between touching marks, horizontal grid only, circle legend symbols on
 * top, transparent background.
 */
export function buildVegaConfig(t: VegaTokens): Record<string, unknown> {
  const label = { font: t.font, fontSize: 11, color: t.tick };
  return {
    background: "transparent",
    view: { stroke: null },
    padding: 0,
    autosize: { type: "fit", contains: "padding" },

    range: {
      category: t.palette,
      ordinal: t.palette,
      // `diverging` carries the SIGN pair (good/bad), a different job from series identity:
      // a delta bar and a waterfall step read their colour here, so a spec can say "colour
      // by sign" without naming a colour. `heatmap` is the single-hue ramp a magnitude gets.
      diverging: [t.sign.neg, t.sign.pos],
      heatmap: [t.surface, t.palette[0]],
    },

    /**
     * The DEFAULT mark colour, which is a different setting from the categorical range and
     * the reason to check a fill rather than trust a screenshot: a mark with no `color`
     * encoding — every single-series bar, line and area, which is most of what this product
     * draws — ignores `range.category` entirely and takes `config.mark.color`. Left unset,
     * Vega-Lite's own #4c78a8 renders instead of --chart-1. It is a plausible blue, so it
     * reads as "the palette worked" until you read the fill attribute.
     */
    mark: { color: t.palette[0] },

    axis: {
      ...label,
      labelFont: t.font, labelFontSize: 11, labelColor: t.tick, labelPadding: 6,
      titleFont: t.font, titleFontSize: 11, titleFontWeight: 500, titleColor: t.t3, titlePadding: 8,
      domainColor: t.axis, domainWidth: 1,
      ticks: false, grid: false, labelOverlap: "greedy",
    },
    // Category axis keeps its domain line and no grid; value axis drops the domain line and
    // carries the horizontal split lines. A horizontal bar mirrors this per-spec.
    // GRID ON BOTH AXES, forming a faint lattice rather than horizontal rules alone.
    // From the reference chart (Chrome traffic / bounce rate, 2026-08-21): with a dense
    // time axis, verticals are what let you carry a value back to its date across a wide
    // plot. Kept recessive enough that the marks still dominate.
    axisX: { domain: true, grid: true, gridColor: t.grid, gridWidth: 1, labelAngle: 0 },
    axisY: { domain: false, grid: true, gridColor: t.grid, gridWidth: 1 },
    // Grid lines live behind the data. Vega-Lite's default puts a gridded axis in front.
    axisBand: { zindex: 0 },
    axisQuantitative: { gridColor: t.grid, gridWidth: 1, zindex: 0 },

    // Right, stacked, one row per series — each entry on its own line BESIDE the plot.
    // ⚠ Not "top-right": Vega-Lite's corner orients draw INSIDE the data rectangle,
    // so the old top-right default overlaid the legend on full-width bars (measured on
    // theLook's margin ranking — the gradient sat on the longest bar). "right" reserves
    // space outside the plot, which is also Vega-Lite's own non-overlapping default.
    // Vega-Lite draws the swatch in the shape of the mark it stands for, so a bar
    // series gets a square and a line series a stroke — kept from the reference.
    legend: {
      orient: "right", direction: "vertical", title: null,
      labelFont: t.font, labelFontSize: 11, labelColor: t.t1,
      symbolSize: 64, symbolStrokeWidth: 0,
      offset: 4, padding: 0, rowPadding: 4, columnPadding: 14,
      // A top/bottom legend centres under the plot instead of hugging the left —
      // Vega's legend layout anchor, passed through the Vega-Lite config.
      layout: { top: { anchor: "middle" }, bottom: { anchor: "middle" } },
    },

    title: {
      font: t.font, fontSize: 13, fontWeight: 600, color: t.t1,
      anchor: "start", offset: 8, subtitleFont: t.font, subtitleColor: t.t3, subtitleFontSize: 11,
    },

    bar: { stroke: t.surface, strokeWidth: 1 },
    line: { strokeWidth: 2, strokeCap: "round", strokeJoin: "round" },
    point: { size: 70, filled: true, stroke: t.surface, strokeWidth: 2 },
    arc: { stroke: t.surface, strokeWidth: 1 },
    // The base map is chrome, not data: it wears the grid colour so the answer painted on
    // top of it is the only thing carrying a hue — and so no spec has to name one.
    geoshape: { fill: t.grid, stroke: t.axis, strokeWidth: 0.5 },
    rule: { stroke: t.t3, strokeDash: [4, 4] },
    text: { font: t.font, fontSize: 11, fontWeight: 500, fill: t.t1 },
  };
}

/**
 * The same tokens, in RAW VEGA's config shape.
 *
 * Tier 3 hands Vega a spec directly, skipping the Vega-Lite compiler — which is also the
 * thing that was applying `buildVegaConfig`. Without this, an ejected chart would silently
 * fall back to Vega's own blue-and-grey defaults and stop following the token layer, which
 * is exactly the failure the June hex-walk represented. The two configs are NOT the same
 * object: Vega-Lite names its mark families after encodings (`bar`, `point`), Vega names
 * them after primitives (`rect`, `symbol`), so the mapping is written out rather than
 * spread across.
 */
export function buildVegaRuntimeConfig(t: VegaTokens): Record<string, unknown> {
  const label = { font: t.font, fontSize: 11, fill: t.tick };
  return {
    background: "transparent",
    range: {
      category: t.palette,
      ordinal: t.palette,
      // `diverging` carries the SIGN pair (good/bad), a different job from series identity:
      // a delta bar and a waterfall step read their colour here, so a spec can say "colour
      // by sign" without naming a colour. `heatmap` is the single-hue ramp a magnitude gets.
      diverging: [t.sign.neg, t.sign.pos],
      heatmap: [t.surface, t.palette[0]],
    },
    axis: {
      labelFont: t.font, labelFontSize: 11, labelColor: t.tick, labelPadding: 6,
      titleFont: t.font, titleFontSize: 11, titleFontWeight: 500, titleColor: t.t3,
      domainColor: t.axis, domainWidth: 1, tickColor: t.axis, ticks: false,
      grid: true, gridColor: t.grid, gridWidth: 1,
    },
    legend: {
      labelFont: t.font, labelFontSize: 11, labelColor: t.t1,
      titleFont: t.font, titleFontSize: 11, titleColor: t.t3,
      // "right", not "top-right" — corner orients draw inside the plot (see tier 1).
      symbolStrokeWidth: 0, orient: "right", direction: "vertical",
    },
    title: { font: t.font, fontSize: 13, fontWeight: 600, color: t.t1, anchor: "start" },
    // Primitive marks, not encoding names — this is where the two config shapes diverge.
    // `fill` is NOT optional here. A mark with no colour encoding — every bar in a funnel,
    // every span in a gantt — falls back to Vega's own #4c78a8, which is a perfectly
    // plausible blue and therefore invisible as a bug until you read the fill attribute.
    // Same failure as tier 1's config.mark.color, one config shape over.
    rect: { fill: t.palette[0], stroke: t.surface, strokeWidth: 1 },
    symbol: { size: 70, fill: t.palette[0], stroke: t.surface, strokeWidth: 2 },
    line: { stroke: t.palette[0], strokeWidth: 2, strokeCap: "round", strokeJoin: "round" },
    arc: { fill: t.palette[0], stroke: t.surface, strokeWidth: 1 },
    path: { fill: t.palette[0] },
    rule: { stroke: t.t3 },
    text: { ...label, fill: t.t1, fontWeight: 500 },
  };
}

