/**
 * theme.ts — the Aughor ECharts theme, built LIVE from CSS design tokens.
 *
 * This replaces the Vega-Lite `vegaV2Config()` + the fragile `remapLegacyColors`
 * hex-walk in VegaChart.tsx with one registered ECharts theme object. The token
 * values (--chart-1..6, --chart-axis/grid/tick, --t1/--t3, --bg-*) are read from
 * the document at registration time so the theme flips automatically with
 * dark/light — exactly like the old Vega config, but applied at `echarts.init`
 * instead of deep-merged into every spec.
 *
 * IMPORTANT — fonts: ECharts' default canvas renderer writes the fontFamily
 * string straight into the canvas 2D context, which does NOT resolve CSS
 * `var(--font-ui)`. Vega could use a CSS var because it renders SVG; here we must
 * bake a concrete font stack. Keep it in sync with --font-ui.
 */

const FONT_STACK = "'DM Sans', system-ui, -apple-system, sans-serif";

/** Read a CSS custom property off <html>, with a dark-mode fallback for SSR. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export interface ChartTokens {
  palette: string[];
  axis: string;
  grid: string;
  tick: string;
  t1: string;
  t3: string;
  tooltipBg: string;
  tooltipBorder: string;
  surface: string;
}

/** Resolve every token the chart theme needs from the current CSS context. */
export function readChartTokens(): ChartTokens {
  const palette = [
    cssVar("--chart-1", "#4C8EEE"),
    cssVar("--chart-2", "#2EC87B"),
    cssVar("--chart-3", "#E0AD00"),
    cssVar("--chart-4", "#8B68D8"),
    cssVar("--chart-5", "#E64848"),
    cssVar("--chart-6", "#30B8E0"),
    // Extended hues for high-cardinality categorical encodings — the overflow ramp
    // past the six brand tokens. This is their single home (REC-U4).
    "#F97316", "#EC4899", "#10B981", "#6366F1", "#F59E0B", "#14B8A6",
    "#A855F7", "#22D3EE", "#84CC16", "#E879F9", "#34D399", "#FB923C",
  ];
  return {
    palette,
    axis: cssVar("--chart-axis", "#2A2C2F"),
    grid: cssVar("--chart-grid", "#212325"),
    tick: cssVar("--chart-tick", "#9DA1A8"),
    t1: cssVar("--t1", "#EAEDF3"),
    t3: cssVar("--t3", "#6B7689"),
    tooltipBg: cssVar("--bg-2", "#161A20"),
    tooltipBorder: cssVar("--chart-axis", "#2A2C2F"),
    surface: cssVar("--bg-1", "#111418"),
  };
}

/**
 * Build the ECharts theme object from resolved tokens. Mirrors `vegaV2Config()`:
 * hidden Y axis line + horizontal split lines only, no X grid, rounded bar tops,
 * round line caps, circle legend symbols, transparent background.
 */
export function buildAughorTheme(t: ChartTokens): Record<string, unknown> {
  const axisLabel = { color: t.tick, fontSize: 11, fontFamily: FONT_STACK };
  const categoryAxis = {
    axisLine: { show: true, lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel,
    splitLine: { show: false, lineStyle: { color: t.grid } },
    splitArea: { show: false },
  };
  const valueAxis = {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel,
    splitLine: { show: true, lineStyle: { color: t.grid, width: 1 } },
    splitArea: { show: false },
  };
  // Data-value labels (bar ends, line points): bright text with a thin background-coloured halo so
  // they stay legible whether they sit over a coloured bar or the dark canvas — the default ECharts
  // label had no contrast guard, which made "0.4" hard to read against the bar tip.
  const dataLabel = {
    color: t.t1, fontSize: 11, fontWeight: 500, fontFamily: FONT_STACK,
    textBorderColor: t.surface, textBorderWidth: 2.5,
  };
  return {
    color: t.palette,
    backgroundColor: "transparent",
    textStyle: { fontFamily: FONT_STACK, color: t.t1 },
    title: {
      textStyle: { color: t.t1, fontSize: 13, fontWeight: 600, fontFamily: FONT_STACK },
      left: "left",
      top: 0,
    },
    categoryAxis,
    valueAxis,
    logAxis: valueAxis,
    timeAxis: categoryAxis,
    line: {
      lineStyle: { width: 2, cap: "round", join: "round" },
      symbol: "circle",
      symbolSize: 6,
      smooth: false,
      label: dataLabel,
    },
    bar: { itemStyle: { borderRadius: [3, 3, 0, 0] }, label: dataLabel },
    pie: { itemStyle: { borderWidth: 1, borderColor: t.surface }, label: { ...dataLabel, textBorderWidth: 2 } },
    scatter: { symbolSize: 9 },
    legend: {
      textStyle: { color: t.t1, fontSize: 11, fontFamily: FONT_STACK },
      icon: "circle",
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 14,
    },
    tooltip: {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderWidth: 1,
      padding: [6, 10],
      textStyle: { color: t.t1, fontSize: 11, fontFamily: FONT_STACK },
      extraCssText: "border-radius:4px;box-shadow:0 4px 16px rgba(0,0,0,.4);",
    },
    grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
  };
}

export const AUGHOR_THEME_NAME = "aughor";

/**
 * Register (or re-register) the Aughor theme on an echarts module with the
 * CURRENT token values. Call before each `init` and again whenever data-theme
 * flips so the chart picks up fresh dark/light colours. Returns the theme name.
 */
export function registerAughorTheme(echarts: {
  registerTheme: (name: string, theme: object) => void;
}): string {
  echarts.registerTheme(AUGHOR_THEME_NAME, buildAughorTheme(readChartTokens()));
  return AUGHOR_THEME_NAME;
}
