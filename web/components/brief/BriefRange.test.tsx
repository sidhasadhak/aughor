// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BriefingRangeBlock } from "@/lib/api";

import { RangeControl, RangeMeasures, rangeStats } from "./BriefRange";

// theLook, 17–26 August 2026 as built live on 2026-09-25 (Arc BR-3)
const BLOCK: BriefingRangeBlock = {
  period: "range", key: "range:custom:2026-08-17..2026-08-26", preset: "custom", label: "Custom range",
  start: "2026-08-17", end: "2026-08-27", last_day: "2026-08-26",
  previous_start: "2026-08-03", previous_end: "2026-08-13",
  last_year_start: "2025-08-18", last_year_end: "2025-08-28", as_of: "2026-09-25",
  lag_days: 15, lag_source: "beyond_horizon", still_moving: ["events", "order_items"],
  covers: "2026-08-17 to 2026-08-26 (10 days)",
  compared_with: "the same 10 days 2 weeks earlier, 2026-08-03 to 2026-08-12",
  last_year_label: "a year earlier, 2025-08-18 to 2025-08-27",
  measured: [
    { name: "Revenue", metric: "revenue", unit: "$", time_kind: "flow", confirmed: false,
      current: 136923, previous: 124840, last_year: 60223, rel: 0.0968, rel_last_year: 1.274,
      status: "final", current_text: "$136,923", previous_text: "$124,840", last_year_text: "$60,223" },
    { name: "Return rate", metric: "return_rate", unit: "ratio 0..1", time_kind: "cohort", confirmed: false,
      current: 0.142857, previous: 0.151255, last_year: 0.161491, rel: -0.0555, rel_last_year: -0.115,
      status: "provisional", current_text: "14.3%", previous_text: "15.1%", last_year_text: "16.1%" },
  ],
  unmeasured: [
    { name: "AOV", reason: "no approved definition; approve one in the Semantic Layer to measure it" },
    { name: "Gross margin", reason: "no approved definition; approve one in the Semantic Layer to measure it" },
  ],
};

describe("RangeMeasures", () => {
  it("states a share's change in points, the status, and one line per reason", () => {
    render(<RangeMeasures block={BLOCK} />);
    expect(screen.getByText("-0.8 pts")).toBeTruthy();
    expect(screen.getByText("+10%")).toBeTruthy();
    expect(screen.getByText("Provisional")).toBeTruthy();
    expect(screen.getByText(/events, order_items\s+were still changing 14 days/)).toBeTruthy();
    const notMeasured = screen.getAllByText(/^Not measured:/);
    expect(notMeasured).toHaveLength(1);
    expect(notMeasured[0].textContent).toContain("AOV, Gross margin — no approved definition");
  });

  it("says what was measured and as of when", () => {
    expect(rangeStats(BLOCK)).toBe("2 measured · 2 not measured · as of 2026-09-25");
  });
});

describe("RangeControl", () => {
  it("asks for a custom range only once both days are picked, first before last", () => {
    const onChange = vi.fn();
    render(<RangeControl value={{ preset: "standing" }} onChange={onChange} />);
    fireEvent.click(screen.getByText("Custom"));
    const show = screen.getByText("Show");
    expect((show as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("First day"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Last day"), { target: { value: "2026-08-26" } });
    fireEvent.click(show);
    expect(onChange).toHaveBeenCalledWith({ preset: "custom", start: "2026-08-17", end: "2026-08-26" });
    fireEvent.click(screen.getByText("Month"));
    expect(onChange).toHaveBeenLastCalledWith({ preset: "last_month" });
  });
});
