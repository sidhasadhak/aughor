/**
 * Arc BG (ROADMAP §3.66) — the words an edition's page puts around what the server measured and wrote.
 *
 * Pure: no fetch, no DOM. The page reads these so a story's kicker, a figure's tone and the readers on
 * offer are decided once, in one place a test can hold.
 */
import type { AccessGroup, EditionBlock, EditionFigure, EditionSource } from "@/lib/api";
import { compactNumber, formatCount, pct } from "@/lib/format";

/** The Segmented control needs a non-empty value; the organisation is "" to the server. */
export const ORGANISATION = "_organisation";

export const toServerReader = (v: string): string => (v === ORGANISATION ? "" : v);
export const fromServerReader = (v: string | undefined | null): string => (v ? v : ORGANISATION);

/** The readers on offer: the organisation, then every function group, by name. */
export function readerOptions(groups: Pick<AccessGroup, "id" | "name" | "kind">[]): { value: string; label: string }[] {
  const fns = groups.filter(g => g.kind === "function").sort((a, b) => a.name.localeCompare(b.name));
  return [{ value: ORGANISATION, label: "The organisation" }, ...fns.map(g => ({ value: g.id, label: g.name }))];
}

const UNIT_WORDS: Record<string, [string, string]> = {
  day: ["day", "days"], week: ["week", "weeks"], month: ["month", "months"], year: ["year", "years"],
};

export function rangeWord(period: string, n = 1): string {
  const [one, many] = UNIT_WORDS[period] ?? ["range", "ranges"];
  return n === 1 ? one : many;
}

/** Good, bad or neither: a figure's distance from its usual range, read in the direction the guide
 *  calls good. A figure whose good direction is not declared is neither — colour would be a judgement
 *  the data does not carry. */
export function toneOf(fig: Pick<EditionFigure, "better" | "current" | "usual">): "good" | "bad" | "neutral" {
  if (fig.better === "none" || fig.current === null || !fig.usual) return "neutral";
  const up = fig.current > fig.usual.mean;
  return (up === (fig.better === "up")) ? "good" : "bad";
}

export function writeLabel(period: string, custom: boolean): string {
  if (custom) return "Write this range's edition";
  return `Write this ${rangeWord(period)}'s edition`;
}

/** A function group's id from a name a person types: a lowercase slug of at most 64 characters. */
export function groupIdOf(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

// ── Arc BC · an edition composed from blocks ─────────────────────────────────────────────────

const SYMBOL: Record<string, string> = { EUR: "€", USD: "$", GBP: "£", BRL: "R$", JPY: "¥", CHF: "CHF " };

/** A source's value worded by its unit: a share as a percentage (two places under 10%), money with its symbol. */
export function fmtValue(v: unknown, unit = ""): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return v === null || v === undefined ? "—" : String(v);
  const u = unit.trim();
  if (/^ratio/i.test(u) && Math.abs(v) <= 1) return pct(v, Math.abs(v) < 0.1 ? 2 : 1);
  if (u === "%" || /^percent/i.test(u)) return `${v.toFixed(1)}%`;
  const sym = SYMBOL[u.toUpperCase()] ?? "";
  if (sym) return `${sym}${compactNumber(v, 1)}`;
  if (Number.isInteger(v)) return Math.abs(v) < 10000 ? formatCount(v) : compactNumber(v, 1);
  return Math.abs(v) >= 1000 ? compactNumber(v, 1) : v.toFixed(Math.abs(v) < 1 ? 3 : 2).replace(/\.?0+$/, "");
}

/** A change worded with its sign: a share in points, anything else as a percentage of where it was. */
export function fmtChange(now: number | null, base: number | null, unit = ""): string {
  if (now === null || base === null || !Number.isFinite(now) || !Number.isFinite(base)) return "";
  if (/^ratio/i.test(unit) && Math.abs(now) <= 1 && Math.abs(base) <= 1) {
    const pts = (now - base) * 100;
    return `${pts >= 0 ? "+" : "−"}${Math.abs(pts).toFixed(2)} pt`;
  }
  if (unit === "%") return `${now - base >= 0 ? "+" : "−"}${Math.abs(now - base).toFixed(1)} pt`;
  if (!base) return "";
  const r = now / base - 1;
  return `${r >= 0 ? "+" : "−"}${Math.abs(r * 100).toFixed(0)}%`;
}

/** Words with citations ({words|source_id}) as runs a renderer draws — plain text, or a cited number. */
export function parseCited(text: string | undefined): { text: string; source?: string }[] {
  const out: { text: string; source?: string }[] = [];
  const re = /\{([^{}|]+)\|([A-Za-z0-9_-]+)\}/g;
  const s = text ?? "";
  let at = 0;
  for (let m = re.exec(s); m; m = re.exec(s)) {
    if (m.index > at) out.push({ text: s.slice(at, m.index) });
    out.push({ text: m[1], source: m[2] });
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push({ text: s.slice(at) });
  return out;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** A bridge's steps: a breakdown from its usual total through each segment's change to this range's total, or a
 *  chain of checks — a total, then each next total, the steps between them their differences. */
export function bridgeSteps(block: EditionBlock, sources: Record<string, EditionSource>):
    { label: string; value: number; kind: "base" | "delta" | "total" }[] {
  if (block.chain && block.chain.length >= 2) {
    const totals = block.chain.map(id => ({ label: sources[id]?.label ?? id, v: num(sources[id]?.facts?.current) }));
    if (totals.some(t => t.v === null)) return [];
    const out: { label: string; value: number; kind: "base" | "delta" | "total" }[] = [];
    totals.forEach((t, i) => {
      if (i > 0) out.push({ label: `to ${t.label}`, value: (t.v as number) - (totals[i - 1].v as number), kind: "delta" });
      out.push({ label: t.label, value: t.v as number, kind: i === 0 ? "base" : "total" });
    });
    return out;
  }
  const src = block.source ? sources[block.source] : undefined;
  if (!src) return [];
  const col = (n: string) => src.columns.indexOf(n);
  const [seg, now, usual, change] = [col("segment"), col("this_range"), col("usual"), col("change")];
  if ([seg, now, usual, change].some(i => i < 0)) return [];
  const rows = src.rows.filter(r => num(r[usual]) !== null && num(r[now]) !== null);
  const start = rows.reduce((a, r) => a + (num(r[usual]) as number), 0);
  const end = rows.reduce((a, r) => a + (num(r[now]) as number), 0);
  const word = (v: unknown) => (v === true ? "Yes" : v === false ? "No" : String(v));
  return [{ label: "A usual range", value: start, kind: "base" },
          ...rows.map(r => ({ label: word(r[seg]), value: num(r[change]) ?? 0, kind: "delta" as const })),
          { label: "This range", value: end, kind: "total" }];
}

/** The drills a block offers: one per column its check can be drilled by, less the ones it already reads. */
export function drillOptions(block: EditionBlock, sources: Record<string, EditionSource>,
                             drillColumns: Record<string, string[]> | undefined): { column: string; segment?: unknown }[] {
  const src = block.source ? sources[block.source] : undefined;
  if (!src || !drillColumns) return [];
  if (src.kind === "check") return (drillColumns[src.id] ?? []).slice(0, 3).map(column => ({ column }));
  if (src.kind !== "breakdown" && src.kind !== "drill") return [];
  const check = String(src.facts?.check ?? "");
  const used = new Set<string>([String(src.facts?.by ?? ""), ...Object.keys((src.facts?.within as object) ?? {})]);
  const top = src.rows[0]?.[0];
  return (drillColumns[check] ?? []).filter(c => !used.has(c)).slice(0, 2).map(column => ({ column, segment: top }));
}
