/**
 * Band fit — a bar chart fills its row, and its bars stay a readable thickness.
 *
 * Until 2026-11-06 `Chart.tsx` capped the WIDTH of a vertical bar chart with six or fewer
 * categories at `max(340, n × 130 + 150)` px, so three bars would not stretch across a whole
 * panel. It counted categories, not bars: four platforms × two measures drew at 670px, and the
 * rest of the row sat empty — the user's screenshot of a Data Canvas exhibit, and the
 * full-width rule they have stated more than once.
 *
 * The chart now takes the whole row, and what the cap was protecting against — a few bars
 * swelling into slabs, because Vega-Lite fits each bar to its band — is handled where the
 * thickness is decided: the gap BETWEEN categories widens until each bar is at most
 * {@link MAX_BAR_PX}, and never past {@link MAX_BAND_PADDING} of the band, so gaps never
 * dominate. The gap between the bars WITHIN a group (`xOffset`) is a separate Vega-Lite
 * setting and is untouched.
 */

/** The thickest a single bar is drawn, in px. */
export const MAX_BAR_PX = 96;
/** Vega-Lite's own default inner padding for a bar's band scale; below it nothing changes. */
export const BASE_BAND_PADDING = 0.1;
/** The most of a band the gap between categories may take. */
export const MAX_BAND_PADDING = 0.6;
/** What a chart's frame takes from its width before the bands: the value axis and a legend. */
export const PLOT_CHROME_PX = 140;

/**
 * The inner band padding that keeps each bar at most {@link MAX_BAR_PX} wide, or `null` when
 * Vega-Lite's default already does (or there is nothing to fit). `width` is the whole chart's.
 */
export function bandPaddingFor(width: number, bands: number, barsPerBand: number): number | null {
  if (!(bands > 0) || !(width > 0)) return null;
  const step = Math.max(1, width - PLOT_CHROME_PX) / bands;
  const group = Math.max(1, barsPerBand) * MAX_BAR_PX;
  const padding = 1 - group / step;
  if (padding <= BASE_BAND_PADDING) return null;
  return Math.round(Math.min(MAX_BAND_PADDING, padding) * 100) / 100;
}

/**
 * How many bars share one band: the distinct values of the `xOffset` field on a grouped bar
 * (the folded measures when the measures are the series), else one.
 */
export function barsPerBand(spec: Record<string, unknown>, columns: string[], rows: unknown[][]): number {
  const enc = spec.encoding as Record<string, { field?: string }> | undefined;
  const field = enc?.xOffset?.field;
  if (!field) return 1;
  if (field === "__measure") {
    const fold = (spec.transform as { fold?: unknown[] }[] | undefined)?.find((t) => Array.isArray(t.fold))?.fold;
    return Math.max(1, fold?.length ?? 1);
  }
  const i = columns.indexOf(field);
  return i < 0 ? 1 : Math.max(1, new Set(rows.map((r) => r[i])).size);
}

/** `spec` with the padding written into its own config (a spec's config wins over the theme's). */
export function withBandPadding(spec: Record<string, unknown>, padding: number | null): Record<string, unknown> {
  if (padding == null) return spec;
  const config = (spec.config as Record<string, unknown> | undefined) ?? {};
  const scale = (config.scale as Record<string, unknown> | undefined) ?? {};
  // Three names for one gap: a bar's band, any other band, and a band that holds a group (`xOffset`) —
  // Vega-Lite reads the last for a grouped bar and ignores the first two there (its default is 0.2).
  return { ...spec, config: { ...config, scale: { ...scale, barBandPaddingInner: padding, bandPaddingInner: padding,
                                                  bandWithNestedOffsetPaddingInner: padding } } };
}
