/**
 * chartEngine.ts — which engine draws a chart (Phase 2 of the Vega migration).
 *
 * Precedence deliberately mirrors lib/config.ts, because the problem is the same one:
 *   1. the user's own setting (localStorage) — flip engines live, no rebuild
 *   2. NEXT_PUBLIC_CHART_ENGINE at build time — for a deployment that has decided
 *   3. "echarts" — the engine that ships today
 *
 * A rollout switch, not a feature flag: it is read on the client at render time, and both
 * engines render from the SAME intent (columns, rows, chartType, chartConfig, exhibit,
 * VizConfig), so flipping it changes the renderer and nothing else. That is the property
 * Phase 2 has to hold — the moment the two engines need different inputs, the comparison
 * stops meaning anything and the migration is no longer reversible.
 */

export type ChartEngine = "echarts" | "vega";

const STORAGE_KEY = "aughor.chartEngine";

function isEngine(v: string | null | undefined): v is ChartEngine {
  return v === "echarts" || v === "vega";
}

/** The build-time answer: what the engine resolves to with no local override stored. */
export const CHART_ENGINE_DEFAULT: ChartEngine =
  (typeof process !== "undefined" && isEngine(process.env.NEXT_PUBLIC_CHART_ENGINE)
    ? process.env.NEXT_PUBLIC_CHART_ENGINE
    : "echarts");

/** The engine in force right now. SSR-safe: falls back to the build-time answer. */
export function chartEngine(): ChartEngine {
  if (typeof window === "undefined") return CHART_ENGINE_DEFAULT;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isEngine(stored)) return stored;
  } catch {
    // Private mode / storage disabled — the build-time answer still applies.
  }
  return CHART_ENGINE_DEFAULT;
}

/** Store an override (or clear it with null) and tell the page to re-render. */
export function setChartEngine(engine: ChartEngine | null): void {
  if (typeof window === "undefined") return;
  try {
    if (engine) window.localStorage.setItem(STORAGE_KEY, engine);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    return;
  }
  window.dispatchEvent(new CustomEvent(CHART_ENGINE_EVENT));
}

/** Fired when the override changes, so mounted charts re-render without a reload. */
export const CHART_ENGINE_EVENT = "aughor:chart-engine";
