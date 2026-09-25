/**
 * PX-1 — the digest tile's figure extraction. The live specimen: a finding about
 * revenue concentration that mentioned "2014" got the YEAR as its headline stat.
 * A year is a date, not a magnitude; when a finding's only numbers are years, the
 * honest tile shows no key figure at all.
 */
import { describe, expect, it } from "vitest";

import { extractKeyFigure } from "@/components/brief/keyFigure";

describe("extractKeyFigure", () => {
  it("prefers a percentage and quotes it at platform precision", () => {
    expect(extractKeyFigure("The top region accounts for 31.58% of gross sales")?.value)
      .toBe("31.58%");
  });

  it("still surfaces a large raw count", () => {
    expect(extractKeyFigure("Orders reached 3,704 in the busiest week")?.value)
      .toBe("3,704");
  });

  it("never headlines a bare year", () => {
    expect(extractKeyFigure(
      "Revenue is moderately concentrated by a single leading region since 2014"))
      .toBeNull();
  });

  it("a year loses to a real magnitude in the same sentence", () => {
    expect(extractKeyFigure("Since 2014, order volume grew to 12,400")?.value)
      .toBe("12,400");
  });

  it("a grouped figure that merely looks year-sized survives", () => {
    // "2,014" carries grouping — a count, not a calendar year.
    expect(extractKeyFigure("Returns hit 2,014 units")?.value).toBe("2,014");
  });

  // 2026-09-25 — the three spellings a float64 reached the Briefing tiles in
  // (docs/UI_UX_STUDY_2026-09-25.md §2.6): a bare magnitude, a bare decimal, e-notation.
  it("groups a magnitude the finding wrote without separators", () => {
    expect(extractKeyFigure("The query returns 180925 total sold items")?.value).toBe("180,925");
  });

  it("groups a decimal magnitude and keeps its cents", () => {
    expect(extractKeyFigure("Inventory cost is concentrated in Jeans at 1820497.55")?.value)
      .toBe("1,820,497.55");
  });

  it("expands scientific notation that leaked out of a float", () => {
    expect(extractKeyFigure("Department cost totals 7.49e+06 for Men")?.value).toBe("7,490,000");
  });

  it("leaves a year and a date alone", () => {
    expect(extractKeyFigure("Between 2026-06-25 and 2026-09-22 orders rose to 12400")?.value)
      .toBe("12,400");
  });
});
