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
});
