/** Arc ED, ED-3 — an expectations step's rows, as a person edits them, and the config the server validates.
 *  Pure: everything a test must catch lives here, out of the component. One table per step, so a row is a kind, a
 *  column and the one or two values its kind needs; the server takes names and values only (never SQL). */

export type ExpectationKind =
  | "not_null" | "unique" | "foreign_key" | "in_list" | "range" | "freshness"
  | "row_count_drift" | "accepted_values_drift";

export interface ExpectationRow {
  kind: ExpectationKind;
  column: string;
  /** in_list: the values; range: min; freshness: hours; foreign_key: the table it references; drift: the limit. */
  first: string;
  /** range: max; foreign_key: the column it references. */
  second: string;
  criticality: "warn" | "error";
}

/** Each kind in words, and what its two value boxes ask for ("" when the kind takes none). */
export const EXPECTATION_KINDS: { kind: ExpectationKind; words: string; column: boolean; first: string; second: string }[] = [
  { kind: "not_null", words: "is never empty", column: true, first: "", second: "" },
  { kind: "unique", words: "never repeats", column: true, first: "", second: "" },
  { kind: "foreign_key", words: "always matches a row of another table", column: true,
    first: "the table it matches", second: "the column it matches" },
  { kind: "in_list", words: "is one of these values", column: true, first: "values, separated by commas", second: "" },
  { kind: "range", words: "stays in a range", column: true, first: "at least", second: "at most" },
  { kind: "freshness", words: "has a newest value within so many hours", column: true, first: "hours", second: "" },
  { kind: "row_count_drift", words: "row count moves by no more than a share", column: false,
    first: "percent change allowed (50)", second: "" },
  { kind: "accepted_values_drift", words: "gains no new values", column: true, first: "new values allowed (0)", second: "" },
];

export const blankRow = (): ExpectationRow =>
  ({ kind: "not_null", column: "", first: "", second: "", criticality: "warn" });

const num = (s: string): number | string => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : s.trim());

/** The rows as the step's `expectations` config: each named by its kind and column, unique within the step. */
export function toConfig(table: string, rows: ExpectationRow[]): Record<string, unknown>[] {
  const taken = new Set<string>();
  return rows.map(r => {
    const base = `${r.column || table.split(".").pop() || "table"} ${r.kind.replace(/_/g, " ")}`;
    let name = base;
    for (let n = 2; taken.has(name); n++) name = `${base} ${n}`;
    taken.add(name);
    const args: Record<string, unknown> = {};
    if (r.kind === "in_list") args.values = r.first.split(",").map(v => v.trim()).filter(Boolean);
    if (r.kind === "range") {
      if (r.first.trim()) args.min = num(r.first);
      if (r.second.trim()) args.max = num(r.second);
    }
    if (r.kind === "freshness" && r.first.trim()) args.max_age_hours = num(r.first);
    if (r.kind === "foreign_key") { args.references = r.first.trim(); args.references_column = r.second.trim(); }
    if (r.kind === "row_count_drift" && r.first.trim()) args.max_change_pct = num(r.first);
    if (r.kind === "accepted_values_drift" && r.first.trim()) args.max_new = num(r.first);
    return { name, table: table.trim(), kind: r.kind, ...(r.column.trim() ? { column: r.column.trim() } : {}),
             ...(Object.keys(args).length ? { args } : {}), criticality: r.criticality };
  });
}

/** A stored config read back into the editor: its table, and one row per expectation. */
export function fromConfig(raw: unknown): { table: string; rows: ExpectationRow[] } {
  const list = Array.isArray(raw) ? (raw as Record<string, unknown>[]) : [];
  const table = String(list.find(x => x && x.table)?.table ?? "");
  const rows = list.map(x => {
    const args = (x.args ?? {}) as Record<string, unknown>;
    const kind = (String(x.kind ?? "not_null") as ExpectationKind);
    const first = kind === "in_list" ? ((args.values as unknown[]) ?? []).join(", ")
      : kind === "range" ? String(args.min ?? "") : kind === "freshness" ? String(args.max_age_hours ?? "")
      : kind === "foreign_key" ? String(args.references ?? "") : kind === "row_count_drift" ? String(args.max_change_pct ?? "")
      : kind === "accepted_values_drift" ? String(args.max_new ?? "") : "";
    const second = kind === "range" ? String(args.max ?? "") : kind === "foreign_key" ? String(args.references_column ?? "") : "";
    return { kind, column: String(x.column ?? ""), first, second,
             criticality: (x.criticality === "error" ? "error" : "warn") as "warn" | "error" };
  });
  return { table, rows };
}
