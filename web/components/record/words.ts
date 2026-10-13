/**
 * The Record's words for a row (CLARITY: a short label for a long question, the full text on hover; humanised days;
 * a thing said once). Pure — nothing here fetches, and each function says what it does when the data is not the
 * shape it expects: it falls back to the text it was given, never to a blank.
 */
import { compactNumber, formatMetricValue, MONTHS_SHORT, pct } from "@/lib/format";
import { dayMonth, dayWords, SCHEDULED_HEADER } from "@/lib/home";
import type { Claim, Decision, Inquiry } from "@/lib/record";
import { runDisplayTitle } from "@/lib/runTitle";

const ymd = (iso: string | null | undefined) => String(iso ?? "").slice(0, 10);

/** "Tue 10 Nov" — a ledger day as the reader says it; "" when there is none. */
export function dateWords(iso: string | null | undefined): string {
  const d = ymd(iso);
  return d ? dayWords(d) : "";
}

/** Whole days from today to a ledger day; negative once it has passed; null when there is none. */
export function daysFrom(iso: string | null | undefined, now: Date = new Date()): number | null {
  const then = Date.parse(`${ymd(iso)}T00:00:00Z`);
  if (Number.isNaN(then)) return null;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((then - today) / 86_400_000);
}

/** "today" · "tomorrow" · "in 28 days" · "yesterday" · "9 days ago". */
export function distanceWords(iso: string | null | undefined, now: Date = new Date()): string {
  const n = daysFrom(iso, now);
  if (n === null) return "";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

/** "Tue 10 Nov · in 28 days" — the day, then how far off it is. */
export function whenWords(iso: string | null | undefined, now: Date = new Date()): string {
  const d = dateWords(iso);
  if (!d) return "";
  const far = distanceWords(iso, now);
  return far ? `${d} · ${far}` : d;
}

/** "7–13 Sep" · "Oct 2026" (a whole month) · "28 Sep – 4 Oct" — a range of days, both ends included. */
export function periodWords(from: string, to: string): string {
  const a = new Date(`${ymd(from)}T00:00:00Z`), b = new Date(`${ymd(to)}T00:00:00Z`);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return `${from} to ${to}`;
  if (ymd(from) === ymd(to)) return dayMonth(from);
  if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
    const last = new Date(Date.UTC(b.getUTCFullYear(), b.getUTCMonth() + 1, 0)).getUTCDate();
    if (a.getUTCDate() === 1 && b.getUTCDate() === last) return `${MONTHS_SHORT[a.getUTCMonth()]} ${a.getUTCFullYear()}`;
    return `${a.getUTCDate()}–${b.getUTCDate()} ${MONTHS_SHORT[a.getUTCMonth()]}`;
  }
  return `${dayMonth(from)} – ${dayMonth(to)}`;
}

/** snake_case read as words — `order_fulfilment` → "order fulfilment". Ids with digits or colons stay as they are. */
export function readable(text: string): string {
  return text.replace(/([A-Za-z])_(?=[A-Za-z])/g, "$1 ");
}

/** The text up to its first full stop — a decimal ("4.62%") is not one. The whole text when it is one sentence. */
export function firstSentence(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  const m = /^(.+?[.!?])(?=\s+["“(]?[A-Z]|$)/.exec(t);
  return m ? m[1] : t;
}

const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/**
 * A short label for a long statement: a leading `kind:` the ledger wrote (`open_case:`, `cockpit:`) becomes words, and
 * the first clause stands for the rest — "Open case: order:2 is in overdue dispatch", "Cockpit: Marketing Dashboard".
 */
export function shortLabel(text: string): string {
  let t = text.replace(/\s+/g, " ").trim();
  let lead = "";
  const m = /^([a-z][a-z0-9_]*):\s*(.+)$/.exec(t);
  if (m) {
    lead = sentenceCase(m[1].replace(/_/g, " "));
    t = m[2];
    const colon = t.indexOf(": ");
    if (colon > 2 && colon < 80) t = t.slice(0, colon);
  }
  const semi = t.indexOf("; ");
  if (semi > 2) t = t.slice(0, semi);
  t = readable(firstSentence(t));
  return lead ? `${lead}: ${t}` : t;
}

export interface RowLabel {
  /** What the row reads as. */
  text: string;
  /** Everything the record holds — for the hover, the copy and the CSV. */
  full: string;
  /** The question was a scheduled run's: its code-written grounding is not the person's question. */
  scheduled: boolean;
}

/**
 * An inquiry's question as a row label. A scheduled run's question opens with the grounding code wrote for the model
 * (`aughor/automations/temporal.py`); the person's own question follows it. The Record keeps the first 500 characters
 * of a question, which a grounding block alone outruns — so the person's words are not in an inquiry opened before
 * 2026-10-13, and its row says what it is ("Scheduled daily run") rather than print the plumbing. Since then the Record
 * stores what was asked and marks the inquiry `scheduled` (`aughor/record/inquiry.py`): pass that flag.
 */
export function inquiryLabel(question: string, scheduled = false): RowLabel {
  const full = (question ?? "").trim();
  if (full.startsWith(SCHEDULED_HEADER) || full.startsWith("[Previous scheduled report")) {
    const t = runDisplayTitle(full);
    if (t.title && t.title !== "Scheduled run" && t.title !== full) {
      return { text: readable(firstSentence(t.title)), full, scheduled: true };
    }
    const cadence = /This is a scheduled (\w+) run/.exec(full)?.[1];
    return { text: cadence ? `Scheduled ${cadence} run` : "Scheduled run", full, scheduled: true };
  }
  return { text: readable(firstSentence(full)), full, scheduled };
}

/** "data that would settle the open items" → "data"; a reason short enough to read stays whole. */
export function waitingShort(waitingFor: string): string {
  const t = (waitingFor ?? "").trim();
  if (t.length <= 24) return t;
  const cut = t.search(/\s(that|which|until|so|to|for|before)\s/);
  if (cut >= 3) return t.slice(0, cut);
  return `${t.split(/\s+/).slice(0, 3).join(" ")}…`;
}

/** open · waiting for data · closed as answered — the state in a few words; the full reason goes on the hover. */
export function inquiryStateShort(q: Pick<Inquiry, "state" | "waiting_for" | "closed_as">): string {
  if (q.state === "waiting") return q.waiting_for ? `waiting for ${waitingShort(q.waiting_for)}` : "waiting";
  if (q.state === "closed") return q.closed_as ? `closed as ${q.closed_as}` : "closed";
  return "open";
}

/** What was chosen, in a word when the options are the approval's two ("approved", "declined"). */
export function chosenWords(d: Pick<Decision, "chosen" | "options">): string {
  if (d.chosen === "approve") return "approved";
  if (d.chosen === "decline") return "declined";
  const opt = d.options.find(o => o.id === d.chosen);
  return shortLabel(opt?.description || d.chosen || "");
}

const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};

/** A figure for a row: "100.8K" from ten thousand up, "1,985" and "551.12" below it. */
export function figure(n: number | null | undefined, symbol = ""): string {
  if (n == null || !Number.isFinite(n)) return "";
  return `${n < 0 ? "-" : ""}${symbol}${Math.abs(n) >= 1e4 ? compactNumber(Math.abs(n)) : formatMetricValue(Math.abs(n))}`;
}

export type PredictionVerdict = "open" | "inside" | "above" | "below" | "cannot_tell";

export interface PredictionView {
  /** The metric, as the statement names it: "Revenue", "Average Order Value (AOV)". */
  metric: string;
  /** The range it is for: "7–13 Sep". */
  period: string;
  /** The band as a range: "$79,438–$98,018"; the statement's own words on hover. */
  band: string;
  bandFull: string;
  verdict: PredictionVerdict;
  /** The measured value once scored: "$100.8K". */
  actual: string;
  /** The day it settles on, and the day it was scored. */
  settles: string;
  scored: string;
}

/** A prediction claim read off the fields the ledger books with it (`extra.low`, `high`, `band_text`, `scored_against`…).
 *  Null for any other kind of claim. */
export function predictionView(c: {
  kind: string; state: string; statement: Pick<Claim["statement"], "text">; extra: Record<string, unknown>;
}): PredictionView | null {
  if (c.kind !== "prediction") return null;
  const x = c.extra ?? {};
  const body = c.statement.text.replace(/^expected:\s*/i, "");
  // The band as the statement wrote it — from the field when it was booked with one, else read off the sentence
  // ("Revenue $79,438 to $98,018 for 2026-09-07 to …").
  const bandFull = typeof x.band_text === "string" ? x.band_text
    : /\s([$€£¥]?-?[\d,.]+%?\s+to\s+[$€£¥]?-?[\d,.]+%?)\s+for\s+\d/.exec(body)?.[1] ?? "";
  const at = bandFull ? body.indexOf(bandFull) : -1;
  const metric = (at > 0 ? body.slice(0, at) : body.split(/ for \d/)[0]).trim();
  const range = /for (\d{4}-\d{2}-\d{2})(?: to (\d{4}-\d{2}-\d{2}))?/.exec(body);
  const symbol = /^[$€£¥]/.exec(bandFull)?.[0] ?? "";
  // A band written in percent is booked as ratios (0.52 for "52%"), and so is its actual.
  const show = (n: number) => (bandFull.includes("%") ? pct(n, 1) : figure(n, symbol));
  const lo = num(x.low), hi = num(x.high), actual = num(x.actual);
  const against = String(x.scored_against ?? "");
  const verdict: PredictionVerdict = c.state === "scored"
    ? (against === "inside" || against === "above" || against === "below" ? against : "cannot_tell")
    : "open";
  return {
    metric: metric || body,
    period: range ? periodWords(range[1], range[2] ?? range[1]) : "",
    // The band as the ledger wrote it ("$79,438 to $98,018", already rounded for a reader), as a range.
    band: bandFull ? bandFull.replace(/\s+to\s+/, "–") : lo != null && hi != null ? `${show(lo)}–${show(hi)}` : "",
    bandFull,
    verdict,
    actual: actual != null ? show(actual) : "",
    settles: typeof x.settles_on === "string" ? x.settles_on : "",
    scored: typeof x.scored_on === "string" ? x.scored_on : "",
  };
}

export const VERDICT_SHORT: Record<PredictionVerdict, string> = {
  open: "open", inside: "held", above: "above its band", below: "below its band", cannot_tell: "cannot tell",
};

/** How many of each, most first: [["finding", 212], ["prediction", 119], …]. */
export function countBy<T>(rows: readonly T[], key: (row: T) => string): [string, number][] {
  const m = new Map<string, number>();
  for (const r of rows) m.set(key(r), (m.get(key(r)) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** The value most rows share — what a row need not repeat. "" for no rows. */
export function modeOf<T>(rows: readonly T[], key: (row: T) => string): string {
  return countBy(rows, key)[0]?.[0] ?? "";
}

/** "212 findings · 119 predictions · 17 more" — the biggest two by name, the rest as a count. */
export function breakdown(pairs: [string, number][], noun: (k: string, n: number) => string, named = 2): string {
  const head = pairs.slice(0, named).map(([k, n]) => `${n} ${noun(k, n)}`);
  const rest = pairs.slice(named).reduce((s, [, n]) => s + n, 0);
  return [...head, ...(rest ? [`${rest} more`] : [])].join(" · ");
}
