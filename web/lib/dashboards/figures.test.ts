import { describe, expect, it } from "vitest";

import type { BriefingRangeBlock, BriefingRangeMeasure, BriefingRangeUnmeasured } from "@/lib/api";
import { endsWords, ownFigures, periodShort, spanWords } from "@/lib/dashboards/figures";

const m = (over: Partial<BriefingRangeMeasure>): BriefingRangeMeasure => ({
  name: "Revenue", metric: "revenue", unit: "$", time_kind: "flow", confirmed: true, current: 110, previous: 100,
  last_year: null, rel: 0.1, rel_last_year: null, status: "final", current_text: "$110", previous_text: "$100", ...over,
});

const block = (measured: BriefingRangeMeasure[], unmeasured: BriefingRangeUnmeasured[] = []): BriefingRangeBlock => ({
  period: "month", key: "k", preset: "previous_month", label: "Last month", start: "2026-09-01", end: "2026-10-01",
  last_day: "2026-09-30", previous_start: "2026-08-01", previous_end: "2026-08-31", last_year_start: null, last_year_end: null,
  as_of: "2026-10-13", lag_days: 12, lag_source: "default", still_moving: [], covers: "September 2026",
  compared_with: "August 2026", last_year_label: null, measured, unmeasured,
});

describe("a period in a few words", () => {
  it("names a whole month, a day, a span inside a month and one across months — from an exclusive end", () => {
    expect(periodShort("2026-09-01", "2026-10-01", "month")).toBe("Sep 2026");
    // a span inside a month says its days (a month still under way is held to the same days of the one before);
    // a whole month is compared with the whole month before, which reads as that month (`aughor/briefing/ranges.py`)
    expect(periodShort("2026-08-01", "2026-08-31", "month")).toBe("1–30 Aug");
    expect(periodShort("2026-08-01", "2026-09-01", "month")).toBe("Aug 2026");
    expect(periodShort("2026-09-24", "2026-09-25", "day")).toBe("Thu 24 Sep");
    expect(periodShort("2026-09-28", "2026-10-05", "week")).toBe("28 Sep – 4 Oct");
    expect(periodShort("2025-01-01", "2026-01-01", "year")).toBe("2025");
  });

  it("says a part-covered span and where stopped data ends, as a reader says dates", () => {
    expect(spanWords("2025-06-30 to 2025-06-30")).toBe("30 Jun 2025");
    expect(spanWords("2024-04-01 to 2024-04-05")).toBe("1–5 Apr 2024");
    expect(endsWords(["2025-06-29", "2024-04-05", "2025-06-30"])).toBe("Apr 2024 to Jun 2025");
    expect(endsWords(["2025-06-29"])).toBe("Jun 2025");
  });
});

describe("a range's figures are its own (2026-10-23)", () => {
  // A block stored before the rule kept an ended metric's other-period figure among its own.
  const gmv = m({ metric: "gmv", name: "GMV", rel: 0.15, anchored: { start: "2025-06-01", end: "2025-07-01", data_ends: "2025-06-29",
    covers: "June 2025", compared_with: "May 2025", why: "" } });
  const stored = block([m({}), gmv], [{ name: "ROAS", reason: "its data has no rows in this range" }]);

  it("reads a stored block's other-period figure as not measured, with the day its data ends", () => {
    const own = ownFigures(stored);
    expect(own.measured.map(x => x.metric)).toEqual(["revenue"]);
    expect(own.unmeasured).toEqual([
      { name: "GMV", metric: "gmv", data_ends: "2025-06-29", reason: "its data ends 2025-06-29, before this range" },
      { name: "ROAS", reason: "its data has no rows in this range" }]);
  });

  it("hands back the same block when every figure is its own", () => {
    const plain = block([m({})], [{ name: "ROAS", reason: "its data has no rows in this range" }]);
    expect(ownFigures(plain)).toBe(plain);
  });
});
