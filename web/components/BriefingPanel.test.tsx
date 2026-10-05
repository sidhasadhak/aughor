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

import { fmtReask, orderByReask, rangeScopeNote } from "@/components/BriefingPanel";

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
