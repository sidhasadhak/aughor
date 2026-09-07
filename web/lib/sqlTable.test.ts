/**
 * SQL-table keying — the duplicate-column defect seen live in the Catalog
 * sample grid (React: "two children with the same key, `0`"). Two claims:
 * keys are positional so same-named columns can never collide, and — the half
 * React never warned about — both duplicate columns' VALUES survive into the
 * row object instead of last-wins collapsing.
 */
import { describe, expect, it } from "vitest";
import { sqlColKey, sqlRowObjects } from "@/lib/sqlTable";

describe("sqlRowObjects", () => {
  it("keeps both values of a duplicated column name", () => {
    const rows = sqlRowObjects(["0", "0"], [["left", "right"]]);
    expect(rows[0][sqlColKey(0)]).toBe("left");
    expect(rows[0][sqlColKey(1)]).toBe("right");
  });

  it("produces unique keys regardless of column names", () => {
    const keys = ["a", "a", "count", "count"].map((_, i) => sqlColKey(i));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("keys rows by index and preserves order", () => {
    const rows = sqlRowObjects(["x"], [[1], [2]]);
    expect(rows.map(r => r.key)).toEqual([0, 1]);
    expect(rows.map(r => r[sqlColKey(0)])).toEqual([1, 2]);
  });

  it("a data column literally named 'key' cannot clobber the row key", () => {
    // The live specimen (2026-09-07): a music dataset's `key` column (musical
    // key, 0–11) was spread OVER the row's React key, so 85k rows keyed by 12
    // values — 176 duplicate-key errors on one sample grid. Positional data
    // keys make the collision structurally impossible.
    const rows = sqlRowObjects(["track_id", "key"], [["t1", 5], ["t2", 5]]);
    expect(rows.map(r => r.key)).toEqual([0, 1]);
    expect(rows.map(r => r[sqlColKey(1)])).toEqual([5, 5]);
  });
});
