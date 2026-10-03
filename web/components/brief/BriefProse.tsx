"use client";

/**
 * BriefProse — the single inline-emphasis renderer for every answer surface.
 *
 * One rule, at the user's word (2026-09-30): "no colouring of the output text at all —
 * only bold or normal text". `**bold**` renders bold in the body colour; everything else —
 * figures, signed changes, `*italics*` — renders as normal text.
 *
 * Signed changes used to be the one hue (emerald / red), and the pass that found them split
 * the text around every figure: the leftover piece after the year in "2026-03-02" starts
 * with a minus sign, so a whole paragraph of an Agent answer turned red from there to its
 * end. With no colour there is nothing for a figure pattern to decide, so there is none.
 */

import React from "react";
import { localizeCurrency } from "@/lib/orgSettings";
import { monthsInTables } from "@/lib/format";
import { ProseTable } from "@/components/TableActions";

const EMPHASIS_RE = /(\*\*[^*]+\*\*|\*[^*\n]+\*)/g;

/** Parse a narrative string into inline nodes: bold, or normal text. Reused by bullets. */
export function renderEmphasis(text: string): React.ReactNode[] {
  if (!text) return [];
  // Honour the configured reporting currency, so "$69.81" → "€69.81" everywhere prose,
  // headlines and bullets render (no-op for USD / unset).
  text = localizeCurrency(text);
  return text.split(EMPHASIS_RE).map((part, i) => {
    if (!part) return null;
    if (part.length > 4 && part.startsWith("**") && part.endsWith("**"))
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    // Single-asterisk italic (models emit these) reads as normal text, markers dropped.
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*"))
      return <React.Fragment key={i}>{part.slice(1, -1)}</React.Fragment>;
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
  const lines = monthsInTables(text || "").split("\n");
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
          <ProseTable key={`t${out.length}`}>
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
          </ProseTable>,
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
