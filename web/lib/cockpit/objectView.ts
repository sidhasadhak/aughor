/**
 * The arithmetic of a cockpit started from an object (2026-10-10, design-mockups/cockpit-from-object.html): what a
 * reader's filters become in the object door's words, where a chart of objects per day starts and ends, its axis, and
 * how a figure is written. No React and no fetch, so the logic tests hold all of it.
 *
 * A reader's filters are their own (the user, 2026-10-10): held per cockpit in their browser, never in the spec.
 */
import { columnTypeKind, compactNumber, formatCount, formatMetricValue, formatMoney } from "@/lib/format";
import { currencySymbol } from "@/lib/orgSettings";

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

/** The window a set's own "in the last N days" on `path` gives a chart drawn across `path` (Arc AP-2): exactly those N
 *  days, today (UTC) included, as the object door counts them — `{ end }` exclusive, the day after today. Null when the
 *  set counts no last days on that property, and the chart finds its window from the objects it holds. */
export function inLastWindow(conditions: readonly { path: string; op: string; value?: unknown }[], path: string,
  today: Date = new Date()): { end: string; days: number } | null {
  const c = conditions.find(x => x.path === path && x.op === "in_last" && Number.isInteger(x.value) && Number(x.value) >= 1);
  if (!c) return null;
  const t = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
  return { end: iso(addDays(t, 1)), days: Number(c.value) };
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

/** A split's value as a reader reads it: nothing is "None". */
export const splitValue = (v: unknown): string =>
  (v === null || v === undefined || v === "" || v === "NULL" ? "None" : String(v));

/** The values a split draws, most first by what they hold over the whole window — `top` of them. Rows are
 *  `(period, value, measure)`. Read from every object, never the reader's narrowed ones, so a value keeps its place and
 *  its colour while a reader filters (Arc AP-1). */
export function topValues(rows: unknown[][], top: number): string[] {
  const total = new Map<string, number>();
  for (const r of rows) {
    const v = splitValue(r[1]);
    total.set(v, (total.get(v) ?? 0) + (Number(r[2]) || 0));
  }
  return [...total.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, top).map(([v]) => v);
}

/** Rows of `(period, value, measure)` laid on the window's days: for each day, the measure of each of `values` in their
 *  order and, last, everything else folded into Other. A day with no row holds nothing. */
export function splitOnDays(days: string[], rows: unknown[][], values: string[]): number[][] {
  const at = new Map(values.map((v, i) => [v, i]));
  const grid = new Map(days.map(d => [d, new Array<number>(values.length + 1).fill(0)]));
  for (const r of rows) {
    const day = grid.get(String(r[0]).slice(0, 10));
    if (!day) continue;
    day[at.get(splitValue(r[1])) ?? values.length] += Number(r[2]) || 0;
  }
  return days.map(d => grid.get(d) ?? new Array<number>(values.length + 1).fill(0));
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
export function cellText(v: unknown, type: string | null | undefined, now: Date = new Date(), unit = "", role = ""): string {
  if (v === null || v === undefined || v === "" || v === "NULL") return "—";
  if (v === true || v === "true" || v === "True") return "yes";
  if (v === false || v === "false" || v === "False") return "no";
  // a key names an object: written as it is, never as a quantity (63981, not 63,981)
  if (role === "key") return String(v);
  const kind = columnTypeKind(type);
  if (kind === "num") {
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    // a currency the ontology declares (ISO 4217): $25.00, never 25
    if (/^[A-Z]{3}$/.test(unit)) return formatMoney(n, currencySymbol(unit));
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

/** A property as a reader reads its name: the ontology's display name, or a raw one spelled out — "Flagged for review",
 *  never "flagged_for_review". A display name the ontology gives is kept as it is. */
export function propertyLabel(display: string | null | undefined, name = ""): string {
  const raw = (display || name || "").trim();
  if (!/^[a-z0-9_]+$/.test(raw)) return raw;
  const spaced = raw.replace(/_+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** An entity's id as one noun: "Order", "Order item" — what a list's key column is headed by. */
export function typeWord(typeId: string | null | undefined): string {
  const spaced = (typeId ?? "").replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A column's type as a person reads it: text, a number, a date, a moment, yes or no — never VARCHAR. */
export function dataTypeWord(type: string | null | undefined): string {
  const kind = columnTypeKind(type);
  if (kind === "bool") return "yes or no";
  if (kind === "num") return "number";
  if (kind === "date") return "date";
  if (kind === "time") return "date and time";
  return "text";
}
