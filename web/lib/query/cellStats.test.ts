/**
 * SE-6 — the two ways a selection summary lies, pinned.
 *
 * Both are easy to write by accident and impossible to spot on screen: a NULL folded
 * in as zero drags an average down without changing the row count, and a "numeric"
 * column detected by parsing the text turns a zero-padded id into an integer and sums
 * a column of identifiers into a figure that looks like money.
 */
import { describe, expect, it } from "vitest";
import { cellStats, selectionToTsv, statText } from "@/lib/query/cellStats";

describe("cellStats", () => {
  it("counts nulls apart and keeps them out of every statistic", () => {
    const s = cellStats([10, null, 20, null], true);
    expect(s.count).toBe(4);
    expect(s.nulls).toBe(2);
    expect(s.numeric).toEqual({ n: 2, sum: 30, avg: 15, min: 10, max: 20 });
  });

  it("reports no average at all for an all-null selection", () => {
    const s = cellStats([null, null], true);
    expect(s.nulls).toBe(2);
    expect(s.numeric).toBeNull();   // not 0 — there is nothing to average
  });

  it("refuses to do arithmetic on a column the schema does not call numeric", () => {
    // '00417' parses as 417. Summing a column of order ids produces a number that
    // looks like a total and means nothing.
    const s = cellStats(["00417", "00418"], false);
    expect(s.numeric).toBeNull();
    expect(s.distinct).toBe(2);
  });

  it("counts distinct values, treating a number and its text form as one value", () => {
    expect(cellStats([1, "1", 2], false).distinct).toBe(2);
  });

  it("ignores a non-finite value in a numeric column rather than poisoning the sum", () => {
    const s = cellStats([1, "not a number", 3], true);
    expect(s.numeric).toEqual({ n: 2, sum: 4, avg: 2, min: 1, max: 3 });
  });
});

describe("statText", () => {
  it("keeps integers exact and cuts float noise to six significant figures", () => {
    expect(statText(1234567)).toBe("1,234,567");
    expect(statText(1 / 3)).toBe("0.333333");
  });

  it("says nothing rather than NaN", () => {
    expect(statText(NaN)).toBe("—");
    expect(statText(Infinity)).toBe("—");
  });
});

describe("selectionToTsv", () => {
  it("renders NULL as an empty field, not as the text 'null'", () => {
    expect(selectionToTsv([[1, null], [2, "x"]])).toBe("1\t\n2\tx");
  });

  it("flattens embedded tabs and newlines so a cell cannot become two", () => {
    expect(selectionToTsv([["a\tb\nc"]])).toBe("a b c");
  });
});
