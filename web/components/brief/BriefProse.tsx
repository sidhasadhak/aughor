"use client";

/**
 * BriefProse — the single inline-emphasis renderer for every answer surface.
 *
 * Replaces the two drifting number-coloring impls (RichText in
 * InvestigationReport, the ad-hoc `fmt` brightening in ChatMessage). One rule,
 * tuned for a published-brief read:
 *   - **bold**            → real bold, brightened (the primary emphasis)
 *   - +1.2K / -$2.1M      → the ONLY semantic color (emerald / red), medium weight
 *   - $1,234 · 12% · 9999 → inherit the body color (figures read as text, not signals)
 *   - everything else     → inherits the surrounding body color
 *
 * ONE font: figures render in the body font (weight + color carry the emphasis),
 * never a second monospace face mid-sentence — the Databricks report treatment,
 * where "$1.2M" reads in the same type as the words around it. Bold wins over
 * number rules (the alternation lists `**…**` first), so a bolded delta like
 * **-$2.1M** renders bold, not red.
 */

import React from "react";
import { localizeCurrency } from "@/lib/orgSettings";

const EMPHASIS_RE =
  /(\*\*[^*]+\*\*|\*[^*\n]+\*|[+]\$?[\d,]+(?:\.\d+)?[KMBk]?%?|-\$?[\d,]+(?:\.\d+)?[KMBk]?%?|\$[\d,]+(?:\.\d+)?[KMBk]?|\d+(?:\.\d+)?%|\b\d{4,}(?:,\d{3})*\b)/g;

/** Parse a narrative string into emphasized inline nodes. Reused by bullets. */
export function renderEmphasis(text: string): React.ReactNode[] {
  if (!text) return [];
  // Honour the configured reporting currency before emphasis is applied, so "$69.81" → "€69.81"
  // everywhere prose, headlines and bullets render (no-op for USD / unset).
  text = localizeCurrency(text);
  return text.split(EMPHASIS_RE).map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**"))
      return (
        // Weight-only emphasis — bold stays the SAME color as the surrounding body, so a
        // sentence reads in one colour (the user's "different colours" note). Reserve hue
        // for the one real signal: a signed +/- delta (below).
        <strong key={i} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    // Single-asterisk italic (LLMs emit these too) — subtle, inherits color.
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*"))
      return <em key={i} className="italic">{part.slice(1, -1)}</em>;
    if (/^\+/.test(part))
      return <span key={i} className="font-medium tabular-nums text-emerald-400">{part}</span>;
    if (/^-/.test(part) && /\d/.test(part))
      return <span key={i} className="font-medium tabular-nums text-red-400">{part}</span>;
    // Plain figures ($1,234 · 12% · 9999) inherit the surrounding body color — no
    // brightening. One color for the reading text; only **bold** (below) and a signed
    // +/- delta (a real favourability signal) stand out. tabular-nums keeps digits aligned.
    if (/\$[\d,]+|\d+%|\b\d{4,}/.test(part))
      return <span key={i} className="tabular-nums">{part}</span>;
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
  caret = false,
}: {
  text: string;
  muted?: boolean;
  className?: string;
  /** Trail a pulsing streaming caret after the text (CK-0.2 token stream). */
  caret?: boolean;
}) {
  if (!text) return null;
  return (
    <p
      className={`aug-text-ui leading-relaxed ${muted ? "text-zinc-500" : "text-zinc-300"} ${className}`}
    >
      {renderEmphasis(text)}
      {caret && <span className="aug-caret" aria-hidden="true" />}
    </p>
  );
}

/* ── block structure ──────────────────────────────────────────────────────────
 * The renderer above is INLINE-only, and an answer is not always one sentence. A
 * conversational turn that tabulates its result wrote a markdown table into the answer
 * text, and every pipe and dash of it rendered literally:
 *
 *   The number of flights per route is as follows: | Route ID | Number of Flights | |
 *   :--- | :--- | | ZRH-LHR | 108 | | GVA-LHR | 96 | …
 *
 * Parsed here rather than pulled in as a markdown dependency: the surface needs tables
 * and paragraphs, the repo's other gates are dependency-free for the same reason, and a
 * full CommonMark renderer would also bring headings, images and raw HTML into a
 * surface that has no design for them.
 */

/** A `| a | b |` row split into its cells, or null when the line is not one. */
function tableCells(line: string): string[] | null {
  const t = line.trim();
  if (!t.startsWith("|") || !t.endsWith("|") || t.length < 3) return null;
  return t.slice(1, -1).split("|").map((c) => c.trim());
}

/** The `|:---|---:|` line under a header row — separator, never data. */
function isTableRule(line: string): boolean {
  const cells = tableCells(line);
  return !!cells && cells.length > 0 && cells.every((c) => /^:?-{1,}:?$/.test(c));
}

/**
 * Answer text as blocks: markdown tables become real tables, everything else stays a
 * paragraph with the inline emphasis above.
 *
 * A table needs a header row, its rule, and at least one body row — anything less is
 * prose that happens to contain a pipe, and rewriting it as a table would be a worse
 * misreading than leaving it alone.
 */
export function renderProseBlocks(text: string): React.ReactNode[] {
  const lines = (text || "").split("\n");
  const out: React.ReactNode[] = [];
  let para: string[] = [];

  const flush = () => {
    const joined = para.join("\n").trim();
    para = [];
    if (joined) out.push(<BriefProse key={`p${out.length}`} text={joined} />);
  };

  for (let i = 0; i < lines.length; i++) {
    const header = tableCells(lines[i]);
    if (header && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      const body: string[][] = [];
      let j = i + 2;
      for (; j < lines.length; j++) {
        const row = tableCells(lines[j]);
        if (!row) break;
        body.push(row);
      }
      if (body.length) {
        flush();
        out.push(
          <div key={`t${out.length}`} className="overflow-x-auto my-2">
            <table className="aug-text-ui border-collapse">
              <thead>
                <tr>
                  {header.map((h, hi) => (
                    <th key={hi} className="text-left font-medium text-zinc-400 px-2 py-1 border-b border-zinc-700">
                      {renderEmphasis(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((c, ci) => (
                      <td key={ci} className="text-zinc-300 px-2 py-1 border-b border-zinc-800 whitespace-nowrap">
                        {renderEmphasis(c)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>,
        );
        i = j - 1;
        continue;
      }
    }
    if (!lines[i].trim()) flush();
    else para.push(lines[i]);
  }
  flush();
  return out;
}

/** True when `text` carries block structure the inline renderer would mangle. */
export function hasProseBlocks(text: string): boolean {
  const lines = (text || "").split("\n");
  return lines.some((l, i) => !!tableCells(l) && i + 1 < lines.length && isTableRule(lines[i + 1]));
}
