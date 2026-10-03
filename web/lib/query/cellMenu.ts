/**
 * DE-5b / DE-5c (ROADMAP §3.51) — what a cell can do to the filter chips, and what a column's
 * values are, as pure functions the grid and its tests share.
 *
 * The right-click menu and the value picker never filter the rows themselves: they SPEAK the
 * filter grammar (`resultFilter.ts`) and hand a phrase to the chip bar, so a filter made by a
 * click is the same object as one typed — removable, chainable, visible as a chip, and
 * round-tripped by the same parser. A value is quoted the way `stripQuotes` unquotes, and a
 * phrase names the column exactly as the result spells it, so `resolveColumn` finds it first.
 */
import type { Cell } from "@/lib/query/resultFilter";

/** The glyph for a real SQL NULL. Distinct from "" on purpose; shared by the grid, its menu and
 *  its picker so a NULL reads the same everywhere a cell is named. */
export const NULL_GLYPH = "∅";

/** A value as the filter grammar takes it: quoted so a value with spaces, commas or the word
 *  `or` stays one value. Double quotes unless the value holds one, then single; a value holding
 *  both is left bare, and still reads as one value in a `=` phrase. */
export function phraseValue(v: Cell): string {
  const s = v === null ? "" : String(v);
  if (!s.includes('"')) return `"${s}"`;
  if (!s.includes("'")) return `'${s}'`;
  return s;
}

export type FilterKind = "is" | "isnot" | "null" | "notnull";

/** The phrase for one cell: `status = "Complete"`, `status != "Complete"`, `status is null`,
 *  `status is not null`. A NULL cell's "filter to this" IS the null test. */
export function filterPhrase(column: string, value: Cell, kind: FilterKind): string {
  if (kind === "null" || (kind === "is" && value === null)) return `${column} is null`;
  if (kind === "notnull" || (kind === "isnot" && value === null)) return `${column} is not null`;
  return kind === "is" ? `${column} = ${phraseValue(value)}` : `${column} != ${phraseValue(value)}`;
}

/** The phrase for a picked set of values: one value is `=`, several are `in`, and a picked NULL
 *  rides as an `or … is null` clause — the grammar's OR, which stands when every part binds.
 *  `in` splits its list on commas and drops an empty entry, so a picked value holding a comma
 *  or an empty string is said as its own `= …` clause instead, and the clauses OR together. */
export function pickedPhrase(column: string, values: readonly Cell[]): string {
  const real = values.filter((v): v is Exclude<Cell, null> => v !== null);
  const parts: string[] = [];
  const listable = real.every(v => { const s = String(v); return s !== "" && !s.includes(","); });
  if (real.length === 1 || !listable) parts.push(...real.map(v => `${column} = ${phraseValue(v)}`));
  else if (real.length > 1) parts.push(`${column} in ${real.map(phraseValue).join(", ")}`);
  if (values.some(v => v === null)) parts.push(`${column} is null`);
  return parts.join(" or ");
}

/** The value as a SQL literal, for pasting into the editor: strings quoted and escaped, numbers
 *  and booleans bare, NULL as NULL. */
export function sqlLiteral(v: Cell): string {
  if (v === null) return "NULL";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "NULL";
  if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
  return `'${v.replace(/'/g, "''")}'`;
}

/** The value as JSON — the one form a nested object or array in a cell is already in. */
export function jsonLiteral(v: Cell): string {
  if (typeof v === "string") {
    const t = v.trim();
    if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
      try { return JSON.stringify(JSON.parse(t), null, 2); } catch { /* a string that looks like JSON */ }
    }
  }
  return JSON.stringify(v);
}

export interface DistinctValue { value: Cell; count: number }

/** The distinct values of one column of the rows, most frequent first, then by text, with NULL
 *  after any real value of the same count. */
export function distinctFromRows(rows: readonly Cell[][], idx: number): DistinctValue[] {
  const counts = new Map<string, DistinctValue>();
  for (const r of rows) {
    const v = r[idx] ?? null;
    const key = v === null ? "\u0000null" : `${typeof v}:${String(v)}`;
    const hit = counts.get(key);
    if (hit) hit.count += 1;
    else counts.set(key, { value: v, count: 1 });
  }
  return Array.from(counts.values()).sort((a, b) =>
    b.count - a.count
    || Number(a.value === null) - Number(b.value === null)
    || String(a.value ?? "").localeCompare(String(b.value ?? "")));
}

export interface SingleTable { table: string; schema?: string }

/** The one table a statement reads, when it reads exactly one and joins nothing — the case in
 *  which a result column can be looked up in the warehouse by name. `null` otherwise: a join, a
 *  union, a CTE or a subquery means the column's values are not any one table's to list. */
export function singleTable(sql: string): SingleTable | null {
  const text = (sql || "").replace(/--[^\n]*/g, " ").replace(/\/\*[\s\S]*?\*\//g, " ");
  if (/\b(join|union|intersect|except|with)\b/i.test(text)) return null;
  const froms = Array.from(text.matchAll(/\bfrom\s+([`"[]?[\w.]+[`"\]]?(?:\.[`"[]?[\w]+[`"\]]?)*)/gi));
  if (froms.length !== 1) return null;
  if (/\bfrom\s*\(/i.test(text)) return null;
  const ref = froms[0][1].replace(/[`"[\]]/g, "");
  const parts = ref.split(".").filter(Boolean);
  if (!parts.length) return null;
  const table = parts[parts.length - 1];
  const schema = parts.length > 1 ? parts[parts.length - 2] : undefined;
  return { table, schema };
}
