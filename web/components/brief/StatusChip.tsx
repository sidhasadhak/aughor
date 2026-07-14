/**
 * StatusChip — the ONE semantic chip vocabulary (REC-U3).
 *
 * Folds the copy-pasted verdict / statistical-signal / recommendation-status style maps
 * (ReportView's VERDICT_STYLE, STAT_STYLE, STATUS_STYLE) into a single hue × strength
 * scale, so a "confirmed / accepted / positive" chip is the SAME green everywhere and a
 * new status is a one-line META entry, not another hardcoded class bundle. Callers keep
 * a thin semantic map (their status → a hue + a label); the classes live only here.
 */
import type React from "react";

export type ChipHue = "positive" | "negative" | "caution" | "info" | "accent" | "muted";
export type ChipStrength = "strong" | "soft";

export interface ChipTone {
  chip: string; // border + bg + text utility bundle
  bar: string;  // solid fill (progress/confidence bars)
}

// strong: verdict + recommendation-status chips (/30 border · /10 bg · -400 text)
const STRONG: Record<ChipHue, ChipTone> = {
  positive: { chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400", bar: "bg-emerald-500" },
  negative: { chip: "border-red-500/30 bg-red-500/10 text-red-400",             bar: "bg-red-500"     },
  caution:  { chip: "border-amber-500/30 bg-amber-500/10 text-amber-400",       bar: "bg-amber-500"   },
  info:     { chip: "border-blue-500/30 bg-blue-500/10 text-blue-400",          bar: "bg-blue-500"    },
  accent:   { chip: "border-violet-500/30 bg-violet-500/10 text-violet-400",    bar: "bg-violet-500"  },
  muted:    { chip: "border-zinc-600 bg-zinc-800/50 text-zinc-500",             bar: "bg-zinc-700"    },
};

// soft: statistical-signal callouts (/20 border · /5 bg · -300 text)
const SOFT: Record<ChipHue, ChipTone> = {
  positive: { chip: "border-emerald-500/20 bg-emerald-500/5 text-emerald-300", bar: "bg-emerald-500" },
  negative: { chip: "border-red-500/20 bg-red-500/5 text-red-300",             bar: "bg-red-500"     },
  caution:  { chip: "border-amber-500/20 bg-amber-500/5 text-amber-300",       bar: "bg-amber-500"   },
  info:     { chip: "border-blue-500/20 bg-blue-500/5 text-blue-300",          bar: "bg-blue-500"    },
  accent:   { chip: "border-violet-500/20 bg-violet-500/5 text-violet-300",    bar: "bg-violet-500"  },
  muted:    { chip: "border-zinc-600 bg-zinc-800/50 text-zinc-400",            bar: "bg-zinc-700"    },
};

/** The border/bg/text (and bar) classes for a hue at a strength — for callers that need
 *  the raw classes (a callout container, a progress bar), not the pill component. */
export function chipTone(hue: ChipHue, strength: ChipStrength = "strong"): ChipTone {
  return (strength === "soft" ? SOFT : STRONG)[hue];
}

/** A small pill: an optional leading icon + a label, in one semantic hue. */
export function StatusChip({
  hue,
  strength = "strong",
  icon,
  children,
  className = "",
  title,
}: {
  hue: ChipHue;
  strength?: ChipStrength;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Native tooltip — provenance detail on hover (TrustReceipt badges etc.). */
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 aug-fs-xs font-medium px-1.5 py-0.5 rounded border ${chipTone(hue, strength).chip} ${className}`}
    >
      {icon != null && <span className="font-mono">{icon}</span>}
      {children}
    </span>
  );
}
