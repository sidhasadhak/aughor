// @vitest-environment jsdom
/**
 * Idea 3 — a period brief shows what it MEASURED for the period: each headline metric with
 * the server's own formatted values and the change, a comparison the data only partly covers
 * with no change stated, and every metric it could not measure with the reason. The shape is
 * the backend's `aughor/knowledge/period_brief.py` block.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PeriodMeasures, PeriodSwitch, periodUnavailable } from "@/components/brief/BriefPeriod";
import type { BriefingPeriodBlock } from "@/lib/api";

const block = (over: Partial<BriefingPeriodBlock> = {}): BriefingPeriodBlock => ({
  period: "week",
  label: "Weekly",
  covers: "the week 2026-09-14 to 2026-09-20",
  compared_with: "the week before, 2026-09-07 to 2026-09-13",
  start: "2026-09-14",
  last_day: "2026-09-20",
  lag_days: 1,
  lag_source: "default",
  measured: [
    { name: "Gross Merchandise Value", unit: "USD", current: 33000, previous: 33019, rel: -0.000575,
      current_text: "$33,000", previous_text: "$33,019" },
    { name: "Items Sold", unit: "count", current: 17200, previous: 5738, rel: null,
      previous_partial: "2024-09-01 to 2024-12-31", current_text: "17,200", previous_text: "5,738" },
  ],
  unmeasured: [{ name: "Top statuses", reason: "its first column is not a date" }],
  ...over,
});

describe("PeriodMeasures", () => {
  it("shows the server's values, the change, and says what it could not measure", () => {
    render(<PeriodMeasures block={block()} />);
    expect(screen.getByText(/Measured for the week 2026-09-14 to 2026-09-20/)).toBeTruthy();
    expect(screen.getByText("$33,000")).toBeTruthy();
    expect(screen.getByText("-0.1%")).toBeTruthy();
    expect(screen.getByText("no change stated: comparison covers only 2024-09-01 to 2024-12-31")).toBeTruthy();
    expect(screen.getByText(/Not measured: Top statuses — its first column is not a date/)).toBeTruthy();
    expect(screen.queryByText(/still settling/)).toBeNull();
  });

  it("says why the period ends before today when the source settles slowly", () => {
    render(<PeriodMeasures block={block({ lag_days: 8, lag_source: "learned" })} />);
    expect(screen.getByText(/Ends 8 days before today: newer days are still settling, a lag the platform measured/)).toBeTruthy();
  });
});

describe("periodUnavailable", () => {
  it("names the period and every reason, never 'run an exploration'", () => {
    const text = periodUnavailable(block({ measured: [] }));
    expect(text).toBe("Nothing to brief on for the week 2026-09-14 to 2026-09-20 — Top statuses: its first column is not a date.");
  });
});

describe("PeriodSwitch", () => {
  it("offers the standing brief and the four periods, and reports the choice", () => {
    const onChange = vi.fn();
    render(<PeriodSwitch value="history" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Standing" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(onChange).toHaveBeenCalledWith("month");
  });
});
