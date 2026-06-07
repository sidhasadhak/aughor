/**
 * palette.ts — the SINGLE home for colour palettes used across the web app.
 *
 * Three independent palettes had been copy-pasted into the components that use
 * them (chart series in VegaChart, per-table cards in SchemaCards, hypothesis
 * cards in ReportView). Centralising them means the brand colours change once.
 *
 *   AUG_PALETTE    — ordered chart-series colours (hex), fed to Vega `range.category`.
 *   TABLE_PALETTES — per-table card chrome (Tailwind class bundles), cycled by index.
 *   H_PALETTES     — hypothesis card chrome (Tailwind class bundles), cycled by index.
 */

// ── Chart series palette (Vega-Lite range.category) ──────────────────────────
// First six are the Aughor brand ramp; the rest extend it for high-cardinality
// categorical encodings. Order is intentional — do not sort.
const C1 = "#4C8EEE";
const C2 = "#2EC87B";
const C3 = "#E0AD00";
const C4 = "#8B68D8";
const C5 = "#E64848";
const C6 = "#30B8E0";

export const AUG_PALETTE = [
  C1, C2, C3, C4, C5, C6,
  "#F97316", "#EC4899", "#10B981", "#6366F1", "#F59E0B", "#14B8A6",
  "#A855F7", "#22D3EE", "#84CC16", "#E879F9", "#34D399", "#FB923C",
  "#818CF8", "#4ADE80",
];

// ── Per-table card palette (Tailwind class bundles), cycled by table index ────
export interface TablePalette {
  border: string;
  header: string;
  badge: string;
  dot: string;
}

export const TABLE_PALETTES: TablePalette[] = [
  { border: "border-violet-500/30",  header: "bg-violet-500/10",  badge: "bg-violet-500/20 text-violet-300",   dot: "bg-violet-400"  },
  { border: "border-blue-500/30",    header: "bg-blue-500/10",    badge: "bg-blue-500/20 text-blue-300",       dot: "bg-blue-400"    },
  { border: "border-emerald-500/30", header: "bg-emerald-500/10", badge: "bg-emerald-500/20 text-emerald-300", dot: "bg-emerald-400" },
  { border: "border-amber-500/30",   header: "bg-amber-500/10",   badge: "bg-amber-500/20 text-amber-300",     dot: "bg-amber-400"   },
  { border: "border-rose-500/30",    header: "bg-rose-500/10",    badge: "bg-rose-500/20 text-rose-300",       dot: "bg-rose-400"    },
  { border: "border-cyan-500/30",    header: "bg-cyan-500/10",    badge: "bg-cyan-500/20 text-cyan-300",       dot: "bg-cyan-400"    },
  { border: "border-indigo-500/30",  header: "bg-indigo-500/10",  badge: "bg-indigo-500/20 text-indigo-300",   dot: "bg-indigo-400"  },
  { border: "border-teal-500/30",    header: "bg-teal-500/10",    badge: "bg-teal-500/20 text-teal-300",       dot: "bg-teal-400"    },
];

// ── Hypothesis card palette (Tailwind class bundles), cycled by index ─────────
export interface HypothesisPalette {
  ring: string;
  dimBg: string;
  badge: string;
  divider: string;
}

export const H_PALETTES: HypothesisPalette[] = [
  { ring: "border-violet-500/40",  dimBg: "bg-violet-500/5",  badge: "bg-violet-500/20 text-violet-300 border-violet-500/30",   divider: "divide-violet-500/10"  },
  { ring: "border-blue-500/40",    dimBg: "bg-blue-500/5",    badge: "bg-blue-500/20 text-blue-300 border-blue-500/30",         divider: "divide-blue-500/10"    },
  { ring: "border-emerald-500/40", dimBg: "bg-emerald-500/5", badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30", divider: "divide-emerald-500/10" },
  { ring: "border-amber-500/40",   dimBg: "bg-amber-500/5",   badge: "bg-amber-500/20 text-amber-300 border-amber-500/30",       divider: "divide-amber-500/10"   },
  { ring: "border-rose-500/40",    dimBg: "bg-rose-500/5",    badge: "bg-rose-500/20 text-rose-300 border-rose-500/30",          divider: "divide-rose-500/10"    },
];
