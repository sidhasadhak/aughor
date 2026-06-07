"use client";

/**
 * BriefProse — the single inline-emphasis renderer for every answer surface.
 *
 * Replaces the two drifting number-coloring impls (RichText in
 * InvestigationReport, the ad-hoc `fmt` brightening in ChatMessage). One rule,
 * tuned for a published-brief read:
 *   - **bold**            → real bold, brightened (the primary emphasis)
 *   - +1.2K / -$2.1M      → the ONLY semantic color (emerald / red), monospace
 *   - $1,234 · 12% · 9999 → monospace, brightened, NO hue (figures, not signals)
 *   - everything else     → inherits the surrounding body color
 *
 * Bold wins over number rules (the alternation lists `**…**` first), so a bolded
 * delta like **-$2.1M** renders bold, not red — exactly the Databricks treatment.
 */

import React from "react";

const EMPHASIS_RE =
  /(\*\*[^*]+\*\*|\*[^*\n]+\*|[+]\$?[\d,]+(?:\.\d+)?[KMBk]?%?|-\$?[\d,]+(?:\.\d+)?[KMBk]?%?|\$[\d,]+(?:\.\d+)?[KMBk]?|\d+(?:\.\d+)?%|\b\d{4,}(?:,\d{3})*\b)/g;

/** Parse a narrative string into emphasized inline nodes. Reused by bullets. */
export function renderEmphasis(text: string): React.ReactNode[] {
  if (!text) return [];
  return text.split(EMPHASIS_RE).map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**"))
      return (
        <strong key={i} className="font-semibold text-zinc-100">
          {part.slice(2, -2)}
        </strong>
      );
    // Single-asterisk italic (LLMs emit these too) — subtle, inherits color.
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*"))
      return <em key={i} className="italic">{part.slice(1, -1)}</em>;
    if (/^\+/.test(part))
      return <span key={i} className="font-mono text-emerald-400">{part}</span>;
    if (/^-/.test(part) && /\d/.test(part))
      return <span key={i} className="font-mono text-red-400">{part}</span>;
    if (/\$[\d,]+|\d+%|\b\d{4,}/.test(part))
      return <span key={i} className="font-mono text-zinc-200">{part}</span>;
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

/**
 * A paragraph of brief narrative. 13px reading body by default; pass `muted` for
 * supporting/secondary text. No box, no border — prose sits directly on the page.
 */
export function BriefProse({
  text,
  muted = false,
  className = "",
}: {
  text: string;
  muted?: boolean;
  className?: string;
}) {
  if (!text) return null;
  return (
    <p
      className={`aug-text-ui leading-relaxed ${muted ? "text-zinc-500" : "text-zinc-300"} ${className}`}
    >
      {renderEmphasis(text)}
    </p>
  );
}
