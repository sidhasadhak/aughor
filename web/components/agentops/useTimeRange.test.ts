/**
 * What Agent Ops says its range is. A brushed range is said as its own two ends — "custom window" told the reader
 * neither when nor how long, and "window" is a retired word for a range (docs/GLOSSARY.md).
 */
import { describe, expect, it } from "vitest";

import { DEFAULT_RANGE, rangeLabel } from "./useTimeRange";

// Local times, so the words do not depend on the zone the suite runs in.
const at = (day: number, hour: number) => new Date(2026, 9, day, hour, 0).toISOString();
const words = (s: string) => s.replace(/\s/g, " ");

describe("rangeLabel", () => {
  it("says a brushed range as its two ends, the day once when both fall on it", () => {
    expect(words(rangeLabel({ key: "24h", since: at(12, 14), until: at(12, 15) }))).toBe("Oct 12, 02:00 PM – 03:00 PM");
    expect(words(rangeLabel({ key: "7d", since: at(12, 14), until: at(13, 9) })))
      .toBe("Oct 12, 02:00 PM – Oct 13, 09:00 AM");
  });

  it("says a named range in words", () => {
    expect(rangeLabel(DEFAULT_RANGE)).toBe("last 24 hours");
    expect(rangeLabel({ key: "7d", since: null, until: null })).toBe("last 7 days");
  });
});
