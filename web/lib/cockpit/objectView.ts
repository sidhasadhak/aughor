/**
 * The arithmetic of a cockpit started from an object (2026-10-10, design-mockups/cockpit-from-object.html): what a
 * reader's filters become in the object door's words, where a chart of objects per day starts and ends, its axis, and
 * how a figure is written. No React and no fetch, so the logic tests hold all of it.
 *
 * A reader's filters are their own (the user, 2026-10-10): held per cockpit in their browser, never in the spec.
 */
import { columnTypeKind, compactNumber, formatCount, formatMetricValue, formatMoney } from "@/lib/format";

/** A reader's filters: entity → property path → the values chosen. */
export type Filters = Record<string, Record<string, string[]>>;

/** The key an entity's filters are held under: a piece may name it by id or by api name. */
export const entityKey = (entity: string): string => entity.toLowerCase();

/** "Order" → "Orders", "Category" → "Categories" — `plural` in `aughor/cockpit/from_object.py`. */
export function plural(word: string): string {
  const w = word.trim();
  if (!w) return w;
  if (w.endsWith("y") && !/(ay|ey|oy|uy)$/i.test(w)) return `${w.slice(0, -1)}ies`;
  return w + (/(s|x|z|ch|sh)$/.test(w) ? "es" : "s");
}

/** Choose or unchoose one value. A property with nothing chosen leaves the map, and so does an entity. */
export function toggled(filters: Filters, entity: string, path: string, value: string): Filters {
  const e = entityKey(entity);
  const now = filters[e]?.[path] ?? [];
  const values = now.includes(value) ? now.filter(v => v !== value) : [...now, value];
  const props = { ...(filters[e] ?? {}), [path]: values };
  if (!values.length) delete props[path];
  const next = { ...filters, [e]: props };
  if (!Object.keys(props).length) delete next[e];
  return next;
}

/** The object door's conditions for an entity's pieces — every chosen property as `in`, but `except`: a filter's own
 *  values are counted narrowed by the OTHER filters, never by itself, or choosing one would hide the rest. */
export function conditionsFor(filters: Filters, entity: string, except?: string): Record<string, unknown>[] {
  return Object.entries(filters[entityKey(entity)] ?? {})
    .filter(([path, values]) => path !== except && values.length > 0)
    .map(([path, values]) => ({ path, op: "in", values }));
}

/** Whether any filter is on, anywhere in the cockpit. */
export const anyFilter = (filters: Filters): boolean =>
  Object.values(filters).some(props => Object.values(props).some(v => v.length > 0));

/** What a filtered series is called in a legend: the values chosen, "Shipped" or "Shipped, Complete". */
export function chosenWords(filters: Filters, entity: string): string {
  return Object.values(filters[entityKey(entity)] ?? {}).flat().join(", ");
}

const iso = (d: Date): string => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number): Date => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + n));
const utcDay = (s: string): Date | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
};

/** Where a chart's window ends (exclusive, an ISO day): today, so the last day drawn is the last whole one — or the
 *  day after the last one the objects hold, when they stop before today (`window_end` in `from_object.py`). */
export function windowEnd(last: string | null | undefined, today: Date = new Date()): string {
  const t = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
  const l = last ? utcDay(String(last)) : null;
  return iso(l && addDays(l, 1) < t ? addDays(l, 1) : t);
}

/** The days of a window, oldest first, as ISO days: `days` of them, ending the day before `end`. */
export function daysBefore(end: string, days: number): string[] {
  const e = utcDay(end);
  if (!e) return [];
  return Array.from({ length: days }, (_, i) => iso(addDays(e, i - days)));
}

/** Rows of `(period, count)` laid on the window's days — a day with no row is a day with none. */
export function onDays(days: string[], rows: unknown[][]): number[] {
  const by = new Map(rows.map(r => [String(r[0]).slice(0, 10), Number(r[1]) || 0]));
  return days.map(d => by.get(d) ?? 0);
}

/** A round axis: 0 up to at least `max` in three or four steps of 1, 2, 2.5 or 5 × a power of ten. */
export function ticks(max: number): number[] {
  if (!(max > 0)) return [0];
  const raw = max / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw) ?? 10 * pow;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => +(i * step).toFixed(6));
}

/** A day as an axis or tooltip reads it: "Sep 10". */
export function dayLabel(day: string): string {
  const d = utcDay(day);
  return d ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : day;
}

/** A figure's value as a reader reads it: a count with separators, money short ($10.80M), any other to two decimals. */
export function figureText(value: number | null | undefined, agg: string, format: string | null | undefined, sym: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (format === "money") return Math.abs(value) >= 1e3 ? `${value < 0 ? "-" : ""}${sym}${compactNumber(Math.abs(value), 2)}` : formatMoney(value, sym);
  if (agg === "count" || agg === "count_distinct") return formatCount(Math.round(value));
  return formatMetricValue(value);
}

/** A table cell as a reader reads it, by its column's SQL type: a moment as "Oct 10, 00:32" (with its year when it is
 *  not this year's — "May 16, 2024"), a number with separators and at most two decimals, a flag as yes or no, nothing
 *  as "—". Moments are read and written in UTC, as the warehouse holds them. */
export function cellText(v: unknown, type: string | null | undefined, now: Date = new Date()): string {
  if (v === null || v === undefined || v === "" || v === "NULL") return "—";
  if (v === true || v === "true" || v === "True") return "yes";
  if (v === false || v === "false" || v === "False") return "no";
  const kind = columnTypeKind(type);
  if (kind === "num") {
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n.toLocaleString("en-US", { maximumFractionDigits: Number.isInteger(n) ? 0 : 2 });
  }
  if (kind === "date" || kind === "time") {
    const s = String(v);
    const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s}T00:00:00Z` : s.replace(" ", "T").replace(/\+00(:00)?$/, "Z"));
    if (Number.isNaN(d.getTime())) return s;
    const thisYear = d.getUTCFullYear() === now.getUTCFullYear();
    const timed = /\d{2}:\d{2}/.test(s);
    const day = d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC", ...(thisYear ? {} : { year: "numeric" }) });
    return thisYear && timed ? `${day}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}` : day;
  }
  return String(v);
}
