/**
 * The exhibit rules. The one that matters most is the last group: whatever is
 * trimmed has to SAY it was trimmed, because a reader cannot tell the first
 * five rows of nine hundred from the whole result by looking.
 */
import { describe, expect, it } from "vitest";

import {
  cell, csvFilename, deepLink, fitsInline, gfmTable, renderGrid, toCsv, worthShowing,
} from "./artifacts.js";

describe("cell", () => {
  it("renders null as empty, never as the word", () => {
    // The connector already renders SQL NULL as the literal string "NULL" in one
    // place; a second surface doing it would make an absent value read as data.
    expect(cell(null)).toBe("");
    expect(cell(undefined)).toBe("");
    expect(cell(0)).toBe("0");
    expect(cell(false)).toBe("false");
    expect(cell({ a: 1 })).toBe('{"a":1}');
  });
});

describe("gfmTable", () => {
  it("renders a header, a rule and one row per record", () => {
    expect(gfmTable({ columns: ["region", "revenue"], rows: [["East", 12], ["West", 9]] })).toBe(
      ["| region | revenue |", "| --- | --- |", "| East | 12 |", "| West | 9 |"].join("\n"),
    );
  });

  it("escapes pipes and newlines — one value must not become two columns", () => {
    const md = gfmTable({ columns: ["note"], rows: [["a|b"], ["two\nlines"]] });
    expect(md).toContain("| a\\|b |");
    expect(md).toContain("| two lines |");
    expect(md.split("\n")).toHaveLength(4);
  });
});

describe("toCsv", () => {
  it("quotes only what needs quoting, and doubles inner quotes (RFC 4180)", () => {
    expect(toCsv({
      columns: ["a", "b"],
      rows: [["plain", 'has "quotes"'], ["has,comma", "has\nnewline"]],
    })).toBe([
      "a,b",
      'plain,"has ""quotes"""',
      '"has,comma","has\nnewline"',
    ].join("\n"));
  });
});

describe("worthShowing", () => {
  it("a single cell is not an exhibit — the prose already said it", () => {
    expect(worthShowing({ columns: ["revenue"], rows: [[1200000]] })).toBe(false);
    expect(worthShowing({ columns: ["metric", "value"], rows: [["revenue", 1200000]] })).toBe(false);
  });

  it("a shape is: more than one row, or a breakdown's worth of columns", () => {
    expect(worthShowing({ columns: ["region", "revenue"], rows: [["E", 1], ["W", 2]] })).toBe(true);
    expect(worthShowing({ columns: ["a", "b", "c"], rows: [[1, 2, 3]] })).toBe(true);
    expect(worthShowing({ columns: [], rows: [] })).toBe(false);
  });
});

describe("renderGrid", () => {
  const cols = (n: number) => Array.from({ length: n }, (_, i) => `c${i}`);
  const rows = (n: number, w: number) => Array.from({ length: n }, (_, r) => cols(w).map((_, c) => r * w + c));

  it("narrow and short renders whole, with nothing attached", () => {
    const out = renderGrid({ columns: ["region", "revenue"], rows: [["East", 12], ["West", 9]] });
    expect(out.csv).toBeNull();
    expect(out.markdown).toContain("| East | 12 |");
  });

  it("narrow but long previews, attaches the rest, and says how many it showed", () => {
    const out = renderGrid({ columns: cols(3), rows: rows(40, 3) });
    expect(out.markdown).toContain("Showing 5 of 40 rows");
    expect(out.csv).not.toBeNull();
    // The CSV carries every row plus its header — the preview is the only trim.
    expect(out.csv!.split("\n")).toHaveLength(41);
  });

  it("wide grids get no table at all — a wide table's first rows are as unreadable as all of them", () => {
    const out = renderGrid({ columns: cols(9), rows: rows(3, 9) });
    expect(out.markdown).toBe("_3 rows × 9 columns — attached as CSV._");
    expect(out.markdown).not.toContain("|");
    expect(out.csv).not.toBeNull();
  });

  it("an empty grid renders nothing rather than an empty table", () => {
    expect(renderGrid({ columns: ["a"], rows: [] })).toEqual({ markdown: "", csv: null });
    expect(renderGrid({ columns: [], rows: [[1]] })).toEqual({ markdown: "", csv: null });
  });

  it("the inline boundary is exact", () => {
    expect(fitsInline({ columns: cols(6), rows: rows(10, 6) })).toBe(true);
    expect(fitsInline({ columns: cols(7), rows: rows(10, 7) })).toBe(false);
    expect(fitsInline({ columns: cols(6), rows: rows(11, 6) })).toBe(false);
  });
});

describe("deepLink", () => {
  it("points at the conversation, with the thread id encoded", () => {
    // A Slack thread id carries colons; unencoded they survive, but encoding is
    // what makes the link independent of how a future id is shaped.
    expect(deepLink("https://aughor.example.com", "slack:C0BT:1788011380.135369"))
      .toBe("https://aughor.example.com/chat?chat=slack%3AC0BT%3A1788011380.135369");
  });

  it("tolerates a trailing slash on the host", () => {
    expect(deepLink("http://localhost:3000/", "s")).toBe("http://localhost:3000/chat?chat=s");
  });
});

describe("csvFilename", () => {
  it("derives a readable, Slack-safe name from the question", () => {
    expect(csvFilename("Why did revenue dip in Q3?")).toBe("why-did-revenue-dip-in-q3.csv");
    expect(csvFilename("???")).toBe("result.csv");
    expect(csvFilename("x".repeat(200)).length).toBeLessThanOrEqual(44);
  });
});
