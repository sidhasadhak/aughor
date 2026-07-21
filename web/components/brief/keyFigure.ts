/**
 * keyFigure — pull the one salient figure out of a finding's OWN statement.
 *
 * The Briefing's digest tiles, the ledger's key-figure column, and the cockpit's
 * suggested pins all want "the number this finding is about." We never invent a number:
 * we quote the finding's grounded prose, extracting the most headline-worthy token by a
 * fixed priority (% › ratio › currency › largest grouped integer). When nothing scans as
 * a figure we return null and the caller shows no key figure — honest over guessed.
 *
 * Pure/string-only so it has no React or data-layer coupling and is trivially testable.
 */

import { normalizeNumberPrecision } from "@/lib/format";

export interface KeyFigure {
  /** The headline figure, formatted as it appears ("33.88%", "3,704", "$2.8B"). */
  value:      string;
  /** A paired secondary part, rendered smaller (e.g. the denominator of a "N vs M"). */
  secondary?: string;
  /** A short best-effort descriptor drawn from the words around the figure; omitted
   *  when it can't be pulled cleanly (never a junk fragment). */
  sublabel?:  string;
}

// A grouped magnitude: leading digit, optional thousands groups, optional decimals.
const NUM = String.raw`\d[\d,]*(?:\.\d+)?`;
const toNum = (s: string) => parseFloat(s.replace(/,/g, ""));
const trimNum = (n: number) => String(Math.round(n * 100) / 100);
// Figures are LIFTED from grounded prose, so whatever precision the finding carries lands in
// the tile verbatim — that is how `43.959061407888164%` reached the verdict. Every branch below
// routes its value through the platform precision policy (see web/lib/format.ts). Comma
// grouping survives: the pattern only matches a long FRACTIONAL run.
const fig = (raw: string) => normalizeNumberPrecision(raw);

// Words that shouldn't start/end a sublabel (prepositions, articles, hedges).
const FILLER = new Set([
  "at", "of", "to", "is", "was", "the", "a", "an", "about", "only", "and", "with",
  "in", "by", "for", "are", "all", "its", "their", "than", "that", "as", "or", "on",
]);

/** Up to three content words immediately before the figure, trimmed of filler. Returns
 *  undefined when the result would be too short to be meaningful. */
function sublabelBefore(text: string, index: number): string | undefined {
  const words = text.slice(0, index).trim().split(/\s+/).filter(w => /[a-z]/i.test(w));
  const out: string[] = [];
  for (let i = words.length - 1; i >= 0 && out.length < 3; i--) {
    const w = words[i].replace(/[^a-z0-9%$/-]/gi, "").toLowerCase();
    if (!w) continue;
    if (out.length === 0 && FILLER.has(w)) continue;   // drop trailing filler
    out.unshift(w);
  }
  while (out.length && FILLER.has(out[0])) out.shift(); // drop leading filler
  const label = out.join(" ").trim();
  if (label.length < 3) return undefined;
  return label.length > 30 ? label.slice(0, 30) : label;
}

export function extractKeyFigure(finding: string): KeyFigure | null {
  const text = (finding || "").trim();
  if (!text) return null;

  // 1) Percentages — the most common headline number. An explicit range takes its peak
  //    (the notable endpoint); a single/first percentage otherwise.
  const range = text.match(new RegExp(`(${NUM})\\s*%\\s*(?:[–—-]|to)\\s*(${NUM})\\s*%`));
  if (range && range.index != null) {
    return { value: `${trimNum(Math.max(toNum(range[1]), toNum(range[2])))}%`, sublabel: sublabelBefore(text, range.index) };
  }
  const pct = text.match(new RegExp(`(${NUM})\\s*%`));
  if (pct && pct.index != null) {
    return { value: `${fig(pct[1])}%`, sublabel: sublabelBefore(text, pct.index) };
  }

  // 2) Ratio — "N vs M" / "N versus M": the finding contrasts two magnitudes.
  const ratio = text.match(new RegExp(`(${NUM})[^\\d]{0,40}?\\b(?:vs\\.?|versus)\\b[^\\d]{0,40}?(${NUM})`, "i"));
  if (ratio && ratio.index != null) {
    return { value: fig(ratio[1]), secondary: `/${fig(ratio[2])}`, sublabel: sublabelBefore(text, ratio.index) };
  }

  // 3) Currency.
  const cur = text.match(new RegExp(`[$€£¥₹]\\s?${NUM}\\s?[BMK]?`));
  if (cur && cur.index != null) {
    return { value: fig(cur[0].replace(/\s+/g, "")), sublabel: sublabelBefore(text, cur.index) };
  }

  // 4) Largest grouped integer (thousands or more) — a raw count worth surfacing.
  const ints = [...text.matchAll(new RegExp(`\\b(${NUM})\\b`, "g"))]
    .map(m => ({ raw: m[1], n: toNum(m[1]), i: m.index ?? 0 }))
    .filter(x => !isNaN(x.n));
  if (ints.length) {
    const big = ints.reduce((a, b) => (b.n > a.n ? b : a));
    if (big.n >= 1000) return { value: fig(big.raw), sublabel: sublabelBefore(text, big.i) };
  }
  return null;
}
