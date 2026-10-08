/**
 * How the explorer's phase reads to a person.
 *
 * The stored phase is a machine state — `canvas_needs_resume`, `is_unfinished` and the
 * boot recovery all key on it, and none of that changes here. This is only the word and
 * the colour on screen, and it needed changing because the word was doing harm.
 *
 * A run that ends without completing is recorded as `failed` whatever the cause, and the
 * engine's own most common reason is *"cancelled (budget exceeded or stopped) — progress
 * saved"*. Rendering that in red as FAILED overstated what the engine recorded: a live
 * deployment with 54 findings and a grounded briefing read as broken, and the reasonable
 * response to that is to throw the lot away and start again — which is exactly what the
 * user of it proposed doing.
 *
 * The half these tests defend hardest is the half that was NOT softened. A run that ended
 * with nothing behind it still says `failed`, in red. The split is the one already present
 * in the data — did this connection end up with work — so nothing here is a judgement
 * invented to make a number look kinder.
 */
import { describe, expect, it } from "vitest";

import { figureNote, fmtReask, orderByReask, rangeScopeNote, rowWords, viewSql, type RangeFigure } from "@/components/BriefingPanel";
import type { FindingReask } from "@/lib/api";

describe("rangeScopeNote (BR-9)", () => {
  it("says nothing on the standing view, where nothing is withheld", () => {
    expect(rangeScopeNote(false, null)).toBe("");
    expect(rangeScopeNote(false, { covers: "17–23 August 2026" })).toBe("");
  });
  it("names the range once its Briefing is on screen, and says 'this range' while pending", () => {
    expect(rangeScopeNote(true, { covers: "17–23 August 2026" })).toBe("all history, not 17–23 August 2026");
    expect(rangeScopeNote(true, null)).toBe("all history, not this range");
  });
});

describe("orderByReask (BR-7)", () => {
  const sig = (id: string) => ({ id });
  const r = (id: string, rel: number | null) => [id, { id, domain: "d", grain: "t.c", measure: "n", how: "value" as const,
    current: 1, previous: 1, rel, rows_current: 1, rows_previous: 1, sql: "" }] as const;
  it("puts the re-asked first by the size of the change, unknown change next, the rest in their standing order", () => {
    const byId = new Map([r("a", 0.1), r("b", -0.5), r("c", null)]);
    expect(orderByReask([sig("x"), sig("a"), sig("c"), sig("y"), sig("b")], s => s.id, byId).map(s => s.id))
      .toEqual(["b", "a", "c", "x", "y"]);
  });
});

describe("fmtReask (BR-7)", () => {
  it("shows a rate in 0..1 as a percentage, a large count compact, a small value plain, and nothing as a dash", () => {
    expect(fmtReask(0.1034, "return_rate")).toBe("10.3%");
    expect(fmtReask(181183, "sold_lines")).toBe("181.2K");
    expect(fmtReask(42.5, "avg_days")).toBe("42.5");
    expect(fmtReask(null, "n")).toBe("—");
  });
});

describe("a re-asked figure's detail draws the rows it is read from (2026-10-09)", () => {
  // theLook's Day view, measured live: the order-status finding re-asked for 2026-09-09 returned
  // five rows, Shipped 60 among them, while the open tile drew the finding's all-history chart.
  // The tile reads the row the finding names — Shipped — not the 217 the five rows add up to.
  const r: FindingReask = {
    id: "pinned__1", domain: "Key Questions", grain: "orders.created_at", measure: "order_count", how: "row", row: ["Shipped"],
    current: 60, previous: 52, rel: 0.154, rows_current: 5, rows_previous: 5,
    sql: "SELECT status, COUNT(*) AS order_count FROM (… 2026-09-09 …) GROUP BY 1",
    sql_previous: "SELECT status, COUNT(*) AS order_count FROM (… 2026-09-02 …) GROUP BY 1",
  };
  const fig: RangeFigure = { reask: r, covers: "2026-09-09 (Wednesday)", comparedWith: "the same weekday a week earlier, 2026-09-02" };

  it("runs the range's cut for the range, the compared cut for the compared range, the recorded SQL for all history", () => {
    expect(viewSql("range", "SELECT recorded", fig)).toBe(r.sql);
    expect(viewSql("compared", "SELECT recorded", fig)).toBe(r.sql_previous);
    expect(viewSql("history", "SELECT recorded", fig)).toBe("SELECT recorded");
    // A re-ask cached before the compared cut was carried has none to run.
    expect(viewSql("compared", "SELECT recorded", { ...fig, reask: { ...r, sql_previous: undefined } })).toBe("");
  });

  it("says which row the figure is, among the rows on screen, for the range it names", () => {
    expect(rowWords(r)).toBe("Shipped");
    expect(rowWords({ ...r, how: "value", row: null })).toBe("");
    expect(figureNote("range", fig)).toBe(
      "For 2026-09-09 (Wednesday), the finding's query returns the 5 rows below; 60 is order_count for Shipped, the row the finding names."
      + " The statement above is the finding as it was recorded, over all history.");
    expect(figureNote("compared", fig)).toBe(
      "For the same weekday a week earlier, 2026-09-02, the finding's query returns the 5 rows below; 52 is order_count for Shipped, the row the finding names.");
    expect(figureNote("history", fig)).toMatch(/^The finding's own evidence, as it was recorded: all history\./);
    // The standing view has no range figure to explain.
    expect(figureNote("history", null)).toBe("");
    // The named row is absent from this range's rows: said, not read as zero.
    expect(figureNote("range", { ...fig, reask: { ...r, current: null } })).toContain("returns the 5 rows below, and none is Shipped, the row the finding names.");
    expect(figureNote("range", { ...fig, reask: { ...r, current: null, rows_current: 0 } })).toContain("returns no rows, so none for Shipped");
  });

  it("reads a series of days as its total or mean, one row as one row, an anonymous column as its figure, and rows left undrawn", () => {
    const series = { ...fig, reask: { ...r, how: "total" as const, row: null, current: 217, rows_current: 7 } };
    expect(figureNote("range", series)).toContain("returns the 7 rows below; 217 is the total of order_count across them.");
    const mean = { ...fig, reask: { ...r, how: "mean" as const, row: null, measure: "return_rate", current: 11.4, rows_current: 7 } };
    expect(figureNote("range", mean)).toContain("11.4 is the mean of return_rate across them.");
    const one = { ...fig, reask: { ...r, how: "value" as const, row: null, measure: "f0_", current: 11106.34, rows_current: 1 } };
    expect(figureNote("range", one)).toContain("returns one row, and its figure is 11,106.34.");
    expect(figureNote("range", { ...fig, reask: { ...r, rows_current: 340 } }, 200)).toContain("the row the finding names. The first 200 are drawn.");
    expect(figureNote("range", { ...series, reask: { ...series.reask, current: null, rows_current: 0 } })).toContain("returns nothing to read a figure from.");
  });
});
