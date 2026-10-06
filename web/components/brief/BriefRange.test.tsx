// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BriefingRangeBlock } from "@/lib/api";

import { RangeControl, RangeMeasures, RangeMeasuresExpected, RangeSections, rangeStats, rangeTop } from "./BriefRange";
import { MetricDetailHost, whyQuestion } from "./MetricDetail";

const api = vi.hoisted(() => ({ readMetricTrend: vi.fn(), readExpectedNext: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

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
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    const show = screen.getByText("Show");
    expect((show as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("First day"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Last day"), { target: { value: "2026-08-26" } });
    fireEvent.click(show);
    expect(onChange).toHaveBeenCalledWith({ preset: "custom", start: "2026-08-17", end: "2026-08-26" });
    fireEvent.click(screen.getByRole("radio", { name: "Month" }));
    expect(onChange).toHaveBeenLastCalledWith({ preset: "last_month" });
  });
});

describe("rangeTop (BR-9 shares the hero's figures with the Key Metrics row)", () => {
  const measure = (metric: string, rel: number | null) => ({
    metric, name: metric, unit: "count", time_kind: "flow", time_source: null, confirmed: false,
    current: 1, previous: 1, last_year: null, rel, rel_last_year: null, status: "final",
    current_partial: false, previous_partial: false, sql: "", current_text: "1", previous_text: "1", last_year_text: null,
  });
  it("is the largest moves first, at most four, so the row can show the rest", () => {
    const block = { measured: [measure("a", 0.1), measure("b", -0.5), measure("c", null), measure("d", 0.3), measure("e", 0.2)] };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(rangeTop(block as any).map(m => m.metric)).toEqual(["b", "d", "e", "a"]);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(rangeTop(block as any, 2).map(m => m.metric)).toEqual(["b", "d"]);
  });
});


describe("Data health (removed 2026-10-05)", () => {
  it("is not a section: the Status column says which figures can still change", () => {
    render(<><RangeMeasures block={BLOCK} /><RangeSections block={{ ...BLOCK, recipe: "custom" }} /></>);
    expect(screen.queryByText("Data health")).toBeNull();
    expect(screen.queryByText(/is provisional — it can still change/)).toBeNull();
    expect(screen.getByText("Provisional")).toBeTruthy();
  });

  it("still says so when the range's own sections could not be built", () => {
    render(<RangeSections block={{ ...BLOCK, recipe_error: "its recipe sections could not be built (ValueError)" }} />);
    expect(screen.getByTestId("range-recipe-error").textContent).toContain("could not be built (ValueError)");
  });
});

describe("a metric opens beside the page", () => {
  const TREND = {
    metric: "revenue", found: true, name: "Revenue", unit: "$", definition: "SUM(sale_price)", tables: ["order_items"],
    filters: ["status <> 'Cancelled'"], caveats: "", owner: "", approved_by: "Finance", version: 3, time_kind: "flow",
    time_source: "set automatically: created_at is the main date of order_items", confirmed: false, why: "", period: BLOCK,
    series: [
      { start: "2026-08-03", last_day: "2026-08-12", label: "2026-08-03 to 2026-08-12", value: 124840, value_text: "$124,840", partial: null, current: false },
      { start: "2026-08-17", last_day: "2026-08-26", label: "2026-08-17 to 2026-08-26", value: 136923, value_text: "$136,923", partial: null, current: true },
    ],
  };
  const MOVED = { ...BLOCK, moves: [{ metric: "revenue", name: "Revenue", dimension: "category", group: "Outerwear", current: 9, previous: 6,
    change: 0.5, n: 40, share: false, current_text: "$9", previous_text: "$6", change_text: "+50%" }] };

  beforeEach(() => { api.readMetricTrend.mockReset(); api.readMetricTrend.mockResolvedValue(TREND); });

  it("no host, no door: the table reads as it always did and asks for nothing", () => {
    render(<RangeMeasures block={BLOCK} />);
    expect(screen.queryByRole("button", { name: "Revenue" })).toBeNull();
    expect(api.readMetricTrend).not.toHaveBeenCalled();
  });

  it("opens the trend, what moved inside it and how it is measured — and can be taken away as a table", async () => {
    const asked: string[] = [];
    render(
      <MetricDetailHost connectionId="thelook" schema="thelook" pageKey="briefing" onAskWhy={q => asked.push(q)}>
        <RangeMeasures block={MOVED} />
      </MetricDetailHost>);
    expect(screen.queryByTestId("metric-detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Revenue" }));
    const drawer = await screen.findByTestId("metric-detail");
    // the trend is read for the range the table was measured for — a custom one by its days
    expect(api.readMetricTrend).toHaveBeenCalledWith("thelook", "revenue",
      { preset: "custom", start: "2026-08-17", end: "2026-08-26" }, "thelook", undefined);
    await waitFor(() => expect(drawer.textContent).toContain("2026-08-17 to 2026-08-26 (this range)"));
    expect(drawer.textContent).toContain("category: Outerwear");
    expect(drawer.textContent).toContain("SUM(sale_price)");
    expect(drawer.textContent).toContain("not yet confirmed by a person");
    // the question is the reader's to ask; asking it closes the drawer
    fireEvent.click(screen.getByRole("button", { name: "Ask why it moved" }));
    expect(asked).toEqual([whyQuestion(MOVED.measured[0], MOVED)]);
    expect(asked[0]).toContain("Why did Revenue change by +10%");
    expect(screen.queryByTestId("metric-detail")).toBeNull();
  });

  it("says why when the earlier ranges could not be read, and Esc puts it away", async () => {
    api.readMetricTrend.mockResolvedValue({ ...TREND, series: [], why: "its query failed: Binder Error" });
    render(
      <MetricDetailHost connectionId="thelook" pageKey="briefing">
        <RangeMeasures block={BLOCK} />
      </MetricDetailHost>);
    fireEvent.click(screen.getByRole("button", { name: "Return rate" }));
    const drawer = await screen.findByTestId("metric-detail");
    await waitFor(() => expect(drawer.textContent).toContain("could not be read: its query failed: Binder Error"));
    expect(screen.queryByRole("button", { name: "Ask why it moved" })).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("metric-detail")).toBeNull();
  });
});


describe("what each metric is expected to read next", () => {
  const EXPECTED = {
    why: "", target: { start: "2026-08-27", last_day: "2026-09-05", label: "2026-08-27 to 2026-09-05", settles_on: "2026-09-18" },
    items: [
      { metric: "revenue", name: "Revenue", why: "", expected: { claim_id: "p1", low: 120000, mid: 131000, high: 142000,
        text: "$120,000 to $142,000", state: "open", scored_against: null, n: 6,
        must_say: ["6 earlier ranges, each read at the same age: $120,000 to $142,000 at 80% stated coverage", "on this metric the interval held 3 of 4 times"] } },
      { metric: "return_rate", name: "Return rate", expected: null, why: "only 2 earlier ranges held a reading; 3 are the least a band is drawn from" },
    ],
  };

  beforeEach(() => { api.readExpectedNext.mockReset(); api.readMetricTrend.mockReset(); api.readMetricTrend.mockResolvedValue(new Promise(() => undefined)); });

  it("states the band beside the figure, says which is not predicted and why, and when it is checked", () => {
    render(<RangeMeasures block={BLOCK} expected={EXPECTED} />);
    expect(screen.getByText("Expected next")).toBeTruthy();
    expect(screen.getByText("$120,000 to $142,000").getAttribute("title")).toContain("the interval held 3 of 4 times");
    expect(screen.getByText("not predicted").getAttribute("title")).toBe("only 2 earlier ranges held a reading; 3 are the least a band is drawn from");
    expect(screen.getByTestId("range-expected-note").textContent).toContain("for 2026-08-27 to 2026-09-05");
    expect(screen.getByTestId("range-expected-note").textContent).toContain("checked on 2026-09-18");
  });

  it("has no such column for a range to date, and says why", () => {
    render(<RangeMeasures block={BLOCK} expected={{ target: null, items: [], why: "a range to date is not predicted: its next reading is the same range, longer" }} />);
    expect(screen.queryByText("Expected next")).toBeNull();
    expect(screen.getByTestId("range-expected-note").textContent).toContain("Nothing is predicted from this range: a range to date");
  });

  it("asks for the bands of the range on the page, and carries one into the metric's drawer", async () => {
    api.readExpectedNext.mockResolvedValue(EXPECTED);
    render(
      <MetricDetailHost connectionId="thelook" schema="thelook" pageKey="briefing">
        <RangeMeasuresExpected connectionId="thelook" schema="thelook" block={BLOCK} />
      </MetricDetailHost>);
    expect(screen.queryByText("Expected next")).toBeNull();                     // the table stands while the bands are read
    expect(await screen.findByText("$120,000 to $142,000")).toBeTruthy();
    expect(api.readExpectedNext).toHaveBeenCalledWith("thelook", { preset: "custom", start: "2026-08-17", end: "2026-08-26" }, "thelook", undefined);
    fireEvent.click(screen.getByRole("button", { name: "Revenue" }));
    const drawer = await screen.findByTestId("metric-detail");
    expect(drawer.textContent).toContain("Expected next — 2026-08-27 to 2026-09-05");
    expect(drawer.textContent).toContain("Checked on 2026-09-18.");
  });
});
