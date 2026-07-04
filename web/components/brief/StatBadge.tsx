"use client";

/**
 * SignificanceBadge — a quiet "is this real, or within noise?" marker.
 *
 * The backend already computes is_significant (z-score / p-value) for ADA
 * findings but only ever surfaced the raw stat_note string. This badge makes
 * the verdict glanceable WITHOUT a loud colored pill — matching Brief's
 * "dots, not boxes" philosophy (same w-1.5 dot the confidence factors use).
 *
 * Gate on the presence of a stat test (stat_note), not on is_significant —
 * a false is_significant on a finding that ran no test would be misleading.
 */

import React from "react";

export function SignificanceBadge({
  significant,
  note,
  className = "",
}: {
  significant: boolean;
  /** The raw stat note (z=2.4, p<0.05 …) — shown muted as the detail, and as title. */
  note?: string;
  className?: string;
}) {
  const label = significant ? "Significant" : "Within noise";
  const dot   = significant ? "bg-emerald-400" : "bg-zinc-600";
  const txt   = significant ? "text-emerald-400/90" : "text-zinc-500";
  return (
    <span
      className={`inline-flex items-center gap-1.5 aug-text-xs ${className}`}
      title={note || (significant ? "Statistically significant" : "Not distinguishable from random variation")}
    >
      <span className={`w-1.5 h-1.5 rounded-[var(--r-pill)] shrink-0 ${dot}`} />
      <span className={txt}>{label}</span>
      {note && <span className="text-zinc-500 font-mono">· {note}</span>}
    </span>
  );
}
