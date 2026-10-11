/** A set's read time, said as a person reads it (Arc AP-6 — the Data tab says how long the door took to count a set). */
import { describe, expect, it } from "vitest";

import { formatSeconds } from "@/lib/format";

describe("formatSeconds", () => {
  it("says hundredths under a second, tenths under a minute, minutes after — and nothing for no time at all", () => {
    expect(formatSeconds(421)).toBe("0.42 s");
    expect(formatSeconds(3140)).toBe("3.1 s");
    expect(formatSeconds(125_000)).toBe("2 min 5 s");
    expect(formatSeconds(125_400)).toBe("2 min 5 s");
    expect(formatSeconds(Number.NaN)).toBe("—");
    expect(formatSeconds(-1)).toBe("—");
  });
});
