/**
 * The cockpit's values a query of the person's own reads (Arc AP-8): written `{{name}}` in the statement, sent as the
 * page holds them now, and bound by the engine — never pasted into the statement (`aughor/cockpit/queries.py` `bind`).
 */
import { ISO_DAY } from "@/lib/cockpit/catalog";
import type { ValueNow } from "@/lib/cockpit/sets";

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
 *  cannot be read: a name the cockpit holds no value of, or one that holds nothing yet. */
export function valuesFor(names: string[], defs: Record<string, { kind: string; label?: string }> | null | undefined,
  valueOf: (name: string) => ValueNow): { values: ValuesSent } | { waiting: string; label: string } | { reading: true } | { refused: string } {
  const values: ValuesSent = {};
  for (const name of names) {
    const def = defs?.[name];
    if (!def) return { refused: `It reads {{${name}}}, and this cockpit holds no value of that name.` };
    const now = valueOf(name);
    if ("refused" in now) return { refused: `It reads ${def.label ?? name}, which cannot be read: ${now.refused}` };
    if ("waiting" in now) return { waiting: now.waiting, label: def.label ?? name };
    if ("reading" in now) return now;
    if (now.value === null || now.value === undefined || now.value === "") return { refused: `It reads ${def.label ?? name}, which holds nothing yet.` };
    values[name] = { kind: def.kind, value: now.value };
  }
  return { values };
}

/** Whether `v` is a value of `kind`: a whole number of days, one or more; a number; words, at most 120; or a day. */
export function valueFits(kind: string, v: unknown): boolean {
  if (kind === "days") return typeof v === "number" && Number.isInteger(v) && v >= 1;
  if (kind === "number") return typeof v === "number" && Number.isFinite(v);
  if (kind === "date") return typeof v === "string" && ISO_DAY.test(v) && !Number.isNaN(Date.parse(v));
  return typeof v === "string" && v.trim() !== "" && v.length <= 120;
}

/** What a reader typed, as a value of `kind` — or null when it is not one. */
export function typedValue(kind: string, text: string): unknown {
  const t = text.trim();
  const v = kind === "days" || kind === "number" ? (t === "" ? Number.NaN : Number(t)) : t;
  return valueFits(kind, v) ? v : null;
}
