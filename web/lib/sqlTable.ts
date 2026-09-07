/* ── SQL-result table keying (the law behind SqlResultTable) ────────────────
   Data keys are POSITIONAL, never the column name: a result can legally carry
   two columns with the same name (a join, a headerless import named 0,1,2…),
   and name-keyed rows silently collapsed the duplicate's values while React
   warned about duplicate keys (seen live in the Catalog sample grid,
   2026-09-07). The name is what the reader sees; the position is the key. */

/** The stable data key for column position `idx`. */
export function sqlColKey(idx: number): string {
  return `c${idx}`;
}

/** Row arrays → row objects keyed positionally. No two columns can collide,
 *  so no value can be silently dropped — the defect this module exists for. */
export function sqlRowObjects(
  columns: string[], rows: unknown[][],
): Array<Record<string, unknown>> {
  return rows.map((r, i) => ({
    key: i,
    ...Object.fromEntries(columns.map((_c, j) => [sqlColKey(j), r[j]])),
  }));
}
