// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import type { BriefingRangeBlock } from "@/lib/api";

import { MetricsCockpit } from "./MetricsCockpit";

const api = vi.hoisted(() => ({ measureRange: vi.fn(), readExpectedNext: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const block = (key: string, covers: string, value: string): BriefingRangeBlock => ({
  period: "month", key, preset: "previous_month", label: "Last month", start: "2026-09-01", end: "2026-10-01",
  last_day: "2026-09-30", previous_start: "2026-08-01", previous_end: "2026-09-01", last_year_start: null,
  last_year_end: null, as_of: "2026-10-08", lag_days: 1, lag_source: "default", still_moving: [], covers,
  compared_with: "the period before", last_year_label: null, unmeasured: [],
  measured: [{ name: "Revenue", metric: "revenue", unit: "$", time_kind: "flow", confirmed: false, current: 1,
    previous: 1, last_year: null, rel: 0, rel_last_year: null, status: "final", current_text: value, previous_text: "$1" }],
});

describe("the metrics cockpit while a new period is read", () => {
  it("says which period is being read, dims the old figures, and clears when the new ones arrive", async () => {
    api.readExpectedNext.mockResolvedValue({ target: null, items: [], why: "" });
    api.measureRange.mockResolvedValueOnce({ period: block("k1", "September 2026", "$300"), from_briefing: false, measured_at: "2026-10-08T10:00:00Z", scope_key: "c" });
    const view = render(<MetricsCockpit connectionId="c" rangesOn value={{ preset: "previous_month" }} onChange={() => {}} />);
    // the figure on its card (the full table, behind Details, holds it too)
    expect(await within(await screen.findByTestId("cockpit-figures")).findByText("$300")).toBeTruthy();
    expect(screen.getByTestId("cockpit-range").textContent).toBe("September 2026 · final");

    let arrive: (v: unknown) => void = () => {};
    api.measureRange.mockReturnValueOnce(new Promise(r => { arrive = r; }));
    view.rerender(<MetricsCockpit connectionId="c" rangesOn value={{ preset: "current_week" }} onChange={() => {}} />);
    expect(await screen.findByText("Loading the metrics for Current week…")).toBeTruthy();
    expect(screen.getByTestId("cockpit-range").textContent).toBe("Current week · reading…");
    expect(screen.getByTestId("metrics-body").getAttribute("aria-busy")).toBe("true");

    arrive({ period: { ...block("k2", "the week of 2026-10-05 so far, 2026-10-05 to 2026-10-07", "$90"), under_way: true },
      from_briefing: false, measured_at: "2026-10-08T10:01:00Z", scope_key: "c" });
    expect(await within(await screen.findByTestId("cockpit-figures")).findByText("$90")).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Loading the metrics for Current week…")).toBeNull());
    expect(screen.getByTestId("cockpit-range").textContent).toBe("the week of 2026-10-05 so far, 2026-10-05 to 2026-10-07 · to date");
    expect(screen.getByTestId("metrics-body").getAttribute("aria-busy")).toBeNull();
  });
});

describe("the metrics cockpit when the data cannot be reached (LuxExperience, 2026-10-23)", () => {
  // The Postgres was down: the server said so as a "headline metrics" row under not-measured, the cockpit showed
  // "1 approved metric can't be measured for a period · Set their dates", and the user approved Repeat Purchase
  // Rate to clear it — and came back to the same row. It is said of the data now, and nothing asks for a metric.
  const down = { ...block("k3", "September 2026", "$1"), measured: [], unmeasured: [],
                 unreachable: "the connection could not be opened (OperationalError)" };

  it("says the data could not be reached — never a metric to approve or date — and reads again on Try again", async () => {
    api.readExpectedNext.mockResolvedValue({ target: null, items: [], why: "" });
    api.measureRange.mockResolvedValueOnce({ period: down, from_briefing: false, measured_at: "2026-10-23T04:16:10Z", scope_key: "c" });
    render(<MetricsCockpit connectionId="c" rangesOn value={{ preset: "previous_month" }} onChange={() => {}} />);
    const said = await screen.findByTestId("metrics-unreachable");
    expect(said).toHaveTextContent("The data could not be reached, so nothing was measured — the connection could not be opened (OperationalError).");
    expect(said).toHaveTextContent("No metric needs anything from you");
    expect(screen.queryByTestId("cockpit-needs")).toBeNull();
    expect(screen.queryByText(/approve|Set their dates|can't be measured/i)).toBeNull();

    api.measureRange.mockResolvedValueOnce({ period: block("k3", "September 2026", "$300"), from_briefing: false,
                                             measured_at: "2026-10-23T05:00:00Z", scope_key: "c" });
    within(said).getByRole("button", { name: "Try again" }).click();
    expect(await within(await screen.findByTestId("cockpit-figures")).findByText("$300")).toBeTruthy();
    expect(screen.queryByTestId("metrics-unreachable")).toBeNull();
  });
});
