import { describe, expect, it } from "vitest";

import { noveltyLabel, noveltyOutOf, noveltyShare } from "@/lib/novelty";

describe("a finding's novelty, on the explorer's own 1–5 scale", () => {
  it("names the top of the scale High — theLook's six fives read 'Notable' when the Briefing counted to 10", () => {
    expect([5, 4, 3, 2, 1].map(noveltyLabel)).toEqual(["High", "Notable", "Mid", "Low", "Low"]);
  });

  it("fills a meter to the end at 5 and says the score out of 5", () => {
    expect(noveltyShare(5)).toBe(1);
    expect(noveltyShare(1)).toBeCloseTo(0.2);
    expect(noveltyOutOf(4)).toBe("4 of 5");
  });
});
