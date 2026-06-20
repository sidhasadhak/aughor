/**
 * Named categorical chart palettes — shared by the Query Builder "Customize" colour
 * dropdown (per-chart override), the org-level Appearance setting (chart_palette), and
 * the Chart engine that applies them. Fixed hex (these are deliberate brand/accessible
 * palettes); the empty selection falls back to the theme palette (--chart-1..6), which
 * flips with light/dark mode.
 */
export const SCHEME_PALETTES: Record<string, string[]> = {
  tableau10: ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"],
  category10: ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"],
  set2: ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494", "#b3b3b3"],
  dark2: ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666"],
  paired: ["#a6cee3", "#1f78b4", "#b2df8a", "#33a02c", "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00"],
  accent: ["#7fc97f", "#beaed4", "#fdc086", "#ffff99", "#386cb0", "#f0027f", "#bf5b17", "#666666"],
};

/** Palette keys, for a settings/customize dropdown. */
export const CHART_PALETTE_NAMES = Object.keys(SCHEME_PALETTES);

/** Human label for a palette key: "tableau10" → "Tableau 10", "set2" → "Set 2". */
export function chartPaletteLabel(key: string): string {
  if (!key) return "Default (theme)";
  const m = key.match(/^([a-z]+)(\d+)?$/i);
  const word = (m?.[1] ?? key).replace(/^\w/, (c) => c.toUpperCase());
  return m?.[2] ? `${word} ${m[2]}` : word;
}
