/**
 * StatusChip — the ONE semantic chip vocabulary (REC-U3).
 *
 * Folds the copy-pasted verdict / statistical-signal / recommendation-status style maps
 * into a single hue × strength scale, so a "confirmed / accepted / positive" chip is the
 * SAME green everywhere and a new status is a one-line META entry, not another hardcoded
 * class bundle. Callers keep a thin semantic map (their status → a hue + a label); the
 * classes live only here.
 *
 * Drawn as the Instrument badge (INSTRUMENT.md §5): an 11px mono rectangle at 3px —
 * tint 1, border 2, text 4 of its hue. `soft` is the callout form of the same hue: tint and
 * border, with the text in --t1.
 */
import type React from "react";

export type ChipHue = "positive" | "negative" | "caution" | "info" | "accent" | "muted";
export type ChipStrength = "strong" | "soft";

export interface ChipTone {
  chip: string; // border + bg + text utility bundle
  bar: string;  // solid fill (progress/confidence bars)
}

// strong: verdict + recommendation-status chips — tint 1 · border 2 · text 4
const STRONG: Record<ChipHue, ChipTone> = {
  positive: { chip: "border-[var(--grn2)] bg-[var(--grn1)] text-[var(--grn4)]",   bar: "bg-[var(--grn3)]"  },
  negative: { chip: "border-[var(--red2)] bg-[var(--red1)] text-[var(--red4)]",   bar: "bg-[var(--red3)]"  },
  caution:  { chip: "border-[var(--amb2)] bg-[var(--amb1)] text-[var(--amb4)]",   bar: "bg-[var(--amb3)]"  },
  info:     { chip: "border-[var(--blue2)] bg-[var(--blue1)] text-[var(--blue4)]", bar: "bg-[var(--blue3)]" },
  accent:   { chip: "border-[var(--vio2)] bg-[var(--vio1)] text-[var(--vio4)]",   bar: "bg-[var(--vio3)]"  },
  muted:    { chip: "border-[var(--b2)] bg-[var(--bg-3)] text-[var(--t2)]",       bar: "bg-[var(--bg-4)]"  },
};

// soft: the callout form (statistical-signal blocks, ReportView) — tint 1 · border 2,
// with the body in --t1: the hue carries the state, the text stays readable prose.
const SOFT: Record<ChipHue, ChipTone> = {
  positive: { chip: "border-[var(--grn2)] bg-[var(--grn1)] text-[var(--t1)]",   bar: "bg-[var(--grn3)]"  },
  negative: { chip: "border-[var(--red2)] bg-[var(--red1)] text-[var(--t1)]",   bar: "bg-[var(--red3)]"  },
  caution:  { chip: "border-[var(--amb2)] bg-[var(--amb1)] text-[var(--t1)]",   bar: "bg-[var(--amb3)]"  },
  info:     { chip: "border-[var(--blue2)] bg-[var(--blue1)] text-[var(--t1)]", bar: "bg-[var(--blue3)]" },
  accent:   { chip: "border-[var(--vio2)] bg-[var(--vio1)] text-[var(--t1)]",   bar: "bg-[var(--vio3)]"  },
  muted:    { chip: "border-[var(--b2)] bg-[var(--bg-3)] text-[var(--t1)]",     bar: "bg-[var(--bg-4)]"  },
};

/** The border/bg/text (and bar) classes for a hue at a strength — for callers that need
 *  the raw classes (a callout container, a progress bar), not the chip component. */
export function chipTone(hue: ChipHue, strength: ChipStrength = "strong"): ChipTone {
  return (strength === "soft" ? SOFT : STRONG)[hue];
}

/** A small chip: an optional leading mark + a label, in one semantic hue. */
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
      className={`inline-flex items-center gap-[5px] aug-fs-xs font-mono font-normal leading-[1.45] px-[7px] py-[2px] rounded-[var(--r1)] border ${chipTone(hue, strength).chip} ${className}`}
    >
      {icon != null && <span className="font-mono">{icon}</span>}
      {children}
    </span>
  );
}
