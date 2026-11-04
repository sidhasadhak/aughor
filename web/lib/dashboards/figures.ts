/**
 * A range's figures in the words a dashboard uses for them: each period in a few words, and the rule that every figure is
 * the period's own (the user, 2026-10-23). The Metrics dashboard's rows are `ledger.ts`. Pure: nothing here fetches.
 */
import type { BriefingRangeBlock, BriefingRangeMeasure } from "@/lib/api";

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const at = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);
const dayBefore = (iso: string) => new Date(at(iso).getTime() - 86_400_000);
const dm = (d: Date) => `${d.getUTCDate()} ${MONTH[d.getUTCMonth()]}`;

/** A period in a few words, from its first day and its EXCLUSIVE end: "Aug 2026", "Thu 24 Sep", "14–20 Sep", "2025". */
export function periodShort(start: string, endExclusive: string, period: string): string {
  if (!start || !endExclusive) return "";
  const s = at(start);
  const last = dayBefore(endExclusive);
  const whole = (unit: "month" | "year") => {
    const next = new Date(s);
    if (unit === "month") next.setUTCMonth(next.getUTCMonth() + 1); else next.setUTCFullYear(next.getUTCFullYear() + 1);
    return next.getTime() === at(endExclusive).getTime();
  };
  if (period === "year" && s.getUTCMonth() === 0 && s.getUTCDate() === 1 && whole("year")) return String(s.getUTCFullYear());
  if (period === "month" && s.getUTCDate() === 1 && whole("month")) return `${MONTH[s.getUTCMonth()]} ${s.getUTCFullYear()}`;
  if (s.getTime() === last.getTime()) return `${DAY[s.getUTCDay()]} ${dm(s)}`;
  if (s.getUTCMonth() === last.getUTCMonth() && s.getUTCFullYear() === last.getUTCFullYear()) {
    return `${s.getUTCDate()}–${dm(last)}`;
  }
  return `${dm(s)} – ${dm(last)}`;
}

/** The period a figure was read for and the one it is compared with, in a few words. */
export function figurePeriods(block: BriefingRangeBlock): { current: string; previous: string } {
  return {
    current: periodShort(block.start, block.end, block.period),
    previous: periodShort(block.previous_start, block.previous_end, block.period),
  };
}

/** A range's figures as both pages print them: its own and nothing else. A block stored before 2026-10-23 kept an
 *  ended metric's other-period figure among its own (`anchored`); it is read here as the server now says it — not
 *  measured, with the day its data ends — so a stored edition reads by the same rule. */
export function ownFigures(block: BriefingRangeBlock): BriefingRangeBlock {
  if (!block.measured.some(m => m.anchored)) return block;
  return {
    ...block,
    measured: block.measured.filter(m => !m.anchored),
    unmeasured: [
      ...block.measured.filter(m => m.anchored).map(m => ({
        name: m.name, metric: m.metric, data_ends: m.anchored!.data_ends,
        reason: `its data ends ${m.anchored!.data_ends}, before this range`,
      })),
      ...block.unmeasured,
    ],
  };
}

/** A reason as the start of a sentence a reader finishes: "its dates cannot be set by rule: its table has …" → "Its
 *  dates cannot be set by rule: its table has …". */
export const sentence = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** "29 Jun 2025" from an ISO day. */
export function dayWords(iso: string): string {
  if (!iso) return "";
  const d = at(iso);
  return `${dm(d)} ${d.getUTCFullYear()}`;
}

/** A part-covered span as a reader says it: "2025-06-30 to 2025-06-30" → "30 Jun 2025"; "2024-04-01 to 2024-04-05" →
 *  "1–5 Apr 2024". Anything it does not recognise is returned as it came. */
export function spanWords(span: string | null | undefined): string {
  const m = /^(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})$/.exec((span ?? "").trim());
  if (!m) return span ?? "";
  const [a, b] = [at(m[1]), at(m[2])];
  if (a.getTime() === b.getTime()) return dayWords(m[1]);
  const year = b.getUTCFullYear();
  if (a.getUTCMonth() === b.getUTCMonth() && a.getUTCFullYear() === year) return `${a.getUTCDate()}–${dm(b)} ${year}`;
  return `${dm(a)} – ${dm(b)} ${year}`;
}

/** Where a set of data-ends falls, as one phrase: "Jun 2025", or "Apr 2024 to Jun 2025". */
export function endsWords(days: string[]): string {
  const sorted = days.filter(Boolean).slice().sort();
  if (!sorted.length) return "";
  const month = (iso: string) => { const d = at(iso); return `${MONTH[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const [first, last] = [month(sorted[0]), month(sorted[sorted.length - 1])];
  return first === last ? first : `${first} to ${last}`;
}
