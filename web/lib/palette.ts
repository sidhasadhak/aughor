/**
 * palette.ts — brand-ramp chrome for index-cycled cards, derived from ONE source.
 *
 * There is a single brand palette: the `--chart-1..6` CSS tokens (defined in the
 * active theme, `aughor-v2/theme/tokens-v2.css`). The ECharts theme reads them live
 * (`components/charts/echarts/theme.ts`), and the card palettes below derive from the
 * SAME tokens via `color-mix` — so changing `--chart-1` moves both the chart series
 * and the card chrome, and everything flips together in dark/light (REC-U4).
 *
 * The old hard-coded `AUG_PALETTE` hex ramp was a stale duplicate of `--chart-*`
 * (unused since the ECharts migration) and is gone; the card palettes were unrelated
 * Tailwind color classes (violet/blue/emerald/…) and are now the brand ramp.
 *
 *   TABLE_PALETTES — per-table card chrome (SchemaCards), cycled by table index.
 *   H_PALETTES     — hypothesis card chrome (ReportView), cycled by index.
 */
import type { CSSProperties } from "react";

/** The i-th brand ramp colour as a live CSS-token reference (cycles 1..6). */
function ramp(i: number): string {
  return `var(--chart-${(i % 6) + 1})`;
}

/** A brand colour at `pct`% opacity — the token-era replacement for Tailwind's `/NN`. */
function alpha(c: string, pct: number): string {
  return `color-mix(in srgb, ${c} ${pct}%, transparent)`;
}

// ── Per-table card palette (SchemaCards), cycled by table index ───────────────
export interface TablePalette {
  border: CSSProperties; // card outline
  header: CSSProperties; // header strip background
  badge: CSSProperties;  // row-count pill
  dot: CSSProperties;    // status dot
}

export const TABLE_PALETTES: TablePalette[] = Array.from({ length: 6 }, (_, i) => {
  const c = ramp(i);
  return {
    border: { borderColor: alpha(c, 30) },
    header: { background: alpha(c, 10) },
    badge: { background: alpha(c, 20), color: c },
    dot: { background: c },
  };
});

// ── Hypothesis card palette (ReportView), cycled by index ─────────────────────
export interface HypothesisPalette {
  ring: CSSProperties;  // border
  dimBg: CSSProperties; // expanded-section background
  badge: CSSProperties; // index badge
}

export const H_PALETTES: HypothesisPalette[] = Array.from({ length: 6 }, (_, i) => {
  const c = ramp(i);
  return {
    ring: { borderColor: alpha(c, 40) },
    dimBg: { background: alpha(c, 5) },
    badge: { background: alpha(c, 20), color: c, borderColor: alpha(c, 30) },
  };
});
