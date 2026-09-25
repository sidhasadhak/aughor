/**
 * palette.ts — the chart palette's single TypeScript source (CA-4).
 *
 * These literals are the SAME values the CSS tokens in web/aughor-v2/theme/tokens-v2.css
 * resolve to (--chart-1..6, --chart-7, --chart-deemph, --bg-2); the `lint:palette` CI gate
 * resolves the CSS aliases, compares both files and fails on any drift, then runs the
 * six-check palette validator (lightness band, chroma floor, CVD separation, normal-vision
 * floor, contrast vs surface) on each mode. Change a colour HERE and in the CSS together,
 * and let the gate arbitrate — never eyeball a palette.
 *
 * Instrument (2026-09-13): the six series ARE the six intent hues — blue interactive,
 * green passed, violet analysis, amber waiting, cyan no-state, red adverse — so a red line
 * and an adverse figure are the same red. Re-skinned 2026-09-25 (dark after Databricks,
 * light after Excel; tokens-v2.css header): the hues moved with the intent tokens, the
 * ORDER did not, and dark amber moved once more for the band (#DE7921 → #D57420).
 *
 * CHART_KIND_ACCENT (--chart-7) is deliberately NOT part of CHART_SERIES: adding it there
 * would raise every chart's series count and stop the "Other" fold at seven instead of six.
 * It exists for surfaces that colour by KIND.
 *
 * Both modes carry the same hue ORDER (blue, green, violet, amber, cyan, red) so a series
 * keeps its hue family when the theme flips. The order is the CVD-safety mechanism: its
 * worst adjacent pair measures ΔE 14.7 light / 10.5 dark under deuteranopia. Six slots is
 * the ceiling: there is no overflow ramp — past six series the data folds into "Other"
 * (the de-emphasis gray), never a generated seventh hue.
 */

export type ChartMode = "light" | "dark";

/** The six categorical series slots, per mode — mirrors --chart-1..6. */
export const CHART_SERIES: Record<ChartMode, string[]> = {
  light: ["#0F6CBD", "#1E7B45", "#6B3FA0", "#B25E00", "#00819C", "#C50F1F"],
  dark: ["#4299E0", "#3CAA60", "#9C7BDD", "#D57420", "#32A6B2", "#E65B77"],
};

/**
 * The kind accent — NOT a seventh series. Mirrors --chart-7.
 *
 * The automation canvas colours a step by its KIND, and a seventh effect kind shipped
 * (VA-11's `connection_call`) with the series exhausted. Folding it into the de-emphasis
 * gray was the chart rule's answer and the wrong one here: on a canvas every kind is
 * visible at once, and grey reads as disabled, not as "seventh". So this is one more
 * validated hue, held to a stricter separation bar than the six carry among themselves —
 * see the note in tokens-v2.css and the gate that enforces it.
 */
export const CHART_KIND_ACCENT: Record<ChartMode, string> = {
  light: "#DC1E98",
  dark: "#9B2378",
};

/** The de-emphasis gray — the "Other" fold and the emphasis form's context series.
 *  Deliberately below the chroma floor so it can never read as a seventh series.
 *  Mirrors --chart-deemph. */
export const CHART_DEEMPH: Record<ChartMode, string> = {
  light: "#AEB5BA",
  dark: "#4E5A6A",
};

/** The surface charts render on — the validator's contrast reference. Mirrors --bg-2:
 *  in dark a card one step above the page (--bg-1), in light the page itself (--bg-0). */
export const CHART_SURFACE: Record<ChartMode, string> = {
  light: "#FFFFFF",
  dark: "#1F272D",
};

/** Sign-diverging pair (change metrics: positive/negative). Sign is a good/bad meaning,
 *  not a series identity, so it wears the intent hues that carry those meanings: green
 *  for passed, red for adverse. Mirrors --grn3 / --chart-threshold-crit (= --red3). */
export const CHART_SIGN: Record<ChartMode, { pos: string; neg: string }> = {
  light: { pos: "#1E7B45", neg: "#C50F1F" },
  dark: { pos: "#3CAA60", neg: "#E65B77" },
};

const cssVar = (name: string): string =>
  typeof window === "undefined"
    ? ""
    : getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const isLightTheme = (): boolean =>
  typeof document !== "undefined" &&
  document.documentElement.getAttribute("data-theme") === "light";

// Headless renderers (the print SSR) have no document to read the theme from —
// they declare the mode once instead of every call site threading it.
let _forcedMode: ChartMode | null = null;
export function setChartMode(mode: ChartMode | null): void { _forcedMode = mode; }
const activeMode = (): ChartMode => _forcedMode ?? (isLightTheme() ? "light" : "dark");

/** The active mode's de-emphasis gray, live from CSS when a document exists
 *  (so org token overrides win), else the literal for the given mode. */
export function resolveDeemph(mode?: ChartMode): string {
  return cssVar("--chart-deemph") || CHART_DEEMPH[mode ?? activeMode()];
}

/** The active sign-diverging pair, live from the intent tokens when a document exists,
 *  else the literals for the given mode. */
export function resolveSign(mode?: ChartMode): { pos: string; neg: string } {
  const m = mode ?? activeMode();
  return {
    pos: cssVar("--grn3") || CHART_SIGN[m].pos,
    neg: cssVar("--chart-threshold-crit") || CHART_SIGN[m].neg,
  };
}

/** The six active series slots, live from CSS when a document exists, else the
 *  literals — for builders that must color data items directly (gantt spans,
 *  forced slot-1 marks) where the registered theme can't reach. */
export function resolveSeries(mode?: ChartMode): string[] {
  const m = mode ?? activeMode();
  return CHART_SERIES[m].map((hex, k) => cssVar(`--chart-${k + 1}`) || hex);
}
