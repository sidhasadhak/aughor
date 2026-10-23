/**
 * The dashboard's values a query of the person's own reads (Arc AP-8): written `{{name}}` in the statement, sent as the
 * page holds them now, and bound by the engine — never pasted into the statement (`aughor/dashboards/queries.py` `bind`).
 */
import { ISO_DAY, MAX_LIST } from "@/lib/dashboards/catalog";
import type { ValueNow } from "@/lib/dashboards/sets";

/** A value in a query: `{{window}}` — the server's own spelling of one, a value's name as the spec holds it. */
const VALUE_IN_SQL = /\{\{\s*([a-z][a-z0-9_-]{0,39})\s*\}\}/g;

/** The values a statement reads, by name, each once, in the order it names them. */
export function valuesRead(sql: string | null | undefined): string[] {
  const out: string[] = [];
  for (const m of (sql ?? "").matchAll(VALUE_IN_SQL)) if (!out.includes(m[1])) out.push(m[1]);
  return out;
}

/** What a query is sent for its values: each as the page holds it now, with its kind. */
export type ValuesSent = Record<string, { kind: string; value: unknown }>;

/** The values a query reads as the page holds them now — or the choice one waits on, one still being read, or why one
 *  cannot be read: a name the dashboard holds no value of, or one that holds nothing yet. */
export function valuesFor(names: string[], defs: Record<string, { kind: string; label?: string }> | null | undefined,
  valueOf: (name: string) => ValueNow): { values: ValuesSent } | { waiting: string; label: string } | { reading: true } | { refused: string } {
  const values: ValuesSent = {};
  for (const name of names) {
    const def = defs?.[name];
    if (!def) return { refused: `It reads {{${name}}}, and this dashboard holds no value of that name.` };
    const now = valueOf(name);
    if ("refused" in now) return { refused: `It reads ${def.label ?? name}, which cannot be read: ${now.refused}` };
    if ("waiting" in now) return { waiting: now.waiting, label: def.label ?? name };
    if ("reading" in now) return now;
    if (now.value === null || now.value === undefined || now.value === "" || (Array.isArray(now.value) && !now.value.length)) {
      return { refused: `It reads ${def.label ?? name}, which holds nothing yet.` };
    }
    values[name] = { kind: def.kind, value: now.value };
  }
  return { values };
}

/** One item a list holds: a number, or words, at most 120. */
const fitsItem = (x: unknown) => (typeof x === "number" && Number.isFinite(x)) || (typeof x === "string" && x.trim() !== "" && x.length <= 120);

/** Whether `v` is a value of `kind`: a whole number of days, one or more; a number; words, at most 120; a day; yes or no
 *  (Arc AP-8c); or a list of one to 30 numbers or words, each once. */
export function valueFits(kind: string, v: unknown): boolean {
  if (kind === "yesno") return typeof v === "boolean";
  if (kind === "list") {
    return Array.isArray(v) && v.length >= 1 && v.length <= MAX_LIST && v.every(fitsItem)
      && new Set(v.map(x => JSON.stringify(x))).size === v.length;
  }
  if (kind === "days") return typeof v === "number" && Number.isInteger(v) && v >= 1;
  if (kind === "number") return typeof v === "number" && Number.isFinite(v);
  if (kind === "date") return typeof v === "string" && ISO_DAY.test(v) && !Number.isNaN(Date.parse(v));
  return typeof v === "string" && v.trim() !== "" && v.length <= 120;
}

/** What a reader typed, as a value of `kind` — or null when it is not one. A list is typed with a comma between its items,
 *  each a number when it reads as one; yes or no as "yes" or "no". */
export function typedValue(kind: string, text: string): unknown {
  const t = text.trim();
  if (kind === "yesno") return /^(yes|true)$/i.test(t) ? true : /^(no|false)$/i.test(t) ? false : null;
  if (kind === "list") {
    const items = t.split(",").map(x => x.trim()).filter(Boolean).map(x => (x !== "" && Number.isFinite(Number(x)) ? Number(x) : x));
    const unique = [...new Map(items.map(x => [JSON.stringify(x), x])).values()];
    return valueFits(kind, unique) ? unique : null;
  }
  const v = kind === "days" || kind === "number" ? (t === "" ? Number.NaN : Number(t)) : t;
  return valueFits(kind, v) ? v : null;
}

/** A value as words: a list with a comma between its items, yes or no as "Yes" or "No". */
export function valueWords(kind: string, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (kind === "yesno" || typeof v === "boolean") return v ? "Yes" : "No";
  return Array.isArray(v) ? v.join(", ") : String(v);
}

/** Arc AP-8c — a value read from a query of the dashboard's own: the first row's value of `column` (none, its first column),
 *  as a value of `kind` — or, for a list, that value of every row. Or why it cannot be: the query failed, returned no row,
 *  has no such column, returns more rows than a list holds, or returns something that is not a value of its kind. Never
 *  a value made up to fill one it lacks. */
export function queryValue(kind: string, column: string | null | undefined,
  run: { columns?: string[]; rows?: unknown[][]; error?: string | null } | null | undefined): { value: unknown } | { refused: string } {
  if (!run) return { refused: "The query did not run." };
  if (run.error) return { refused: `The query failed: ${run.error}` };
  const cols = run.columns ?? [];
  const at = column ? cols.indexOf(column) : 0;
  if (at < 0 || !cols.length) return { refused: column ? `The query returns no column ${column}.` : "The query returns no column." };
  const rows = run.rows ?? [];
  if (!rows.length) return { refused: "The query returns no row." };
  const as = (x: unknown): unknown => {
    if (x === null || x === undefined) return null;
    if (kind === "days" || kind === "number") return typeof x === "number" ? x : typeof x === "string" && x.trim() !== "" ? Number(x) : Number.NaN;
    if (kind === "yesno") return x === true || x === "true" || x === 1 ? true : x === false || x === "false" || x === 0 ? false : null;
    if (kind === "date") return typeof x === "string" ? x.slice(0, 10) : null;
    return typeof x === "number" ? x : String(x);
  };
  if (kind === "list") {
    if (rows.length > MAX_LIST) return { refused: `The query returns ${rows.length} rows, and a list holds at most ${MAX_LIST}.` };
    const items = [...new Map(rows.map(r => as(r[at])).filter(x => x !== null && x !== "").map(x => [JSON.stringify(x), x])).values()];
    return valueFits("list", items) ? { value: items } : { refused: "The query returns nothing a list holds." };
  }
  const v = as(rows[0][at]);
  if (v === null) return { refused: "The query's first value is empty." };
  return valueFits(kind, v) ? { value: v } : { refused: `The query's first value is ${JSON.stringify(rows[0][at])}, not ${KIND_WORDS[kind] ?? kind}.` };
}

const KIND_WORDS: Record<string, string> = {
  days: "a whole number of days", number: "a number", text: "words", date: "a day", yesno: "yes or no", list: "a list",
};
