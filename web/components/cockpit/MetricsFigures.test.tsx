// @vitest-environment jsdom
/**
 * The Metrics cockpit as figures (`design-mockups/cockpit-day-figures.html`). The fixture is LuxExperience's September
 * 2026 as the live cockpit measured it (2026-10-13): one figure of the period's own, three read for earlier months
 * because their data stops there, four that cannot be measured for a period.
 */
import { describe, expect, it, vi } from "vitest";

import type { BriefingRangeBlock, BriefingRangeMeasure } from "@/lib/api";
import { fireEvent, render, screen, within } from "@/lib/testing";

const api = vi.hoisted(() => ({ readExpectedNext: vi.fn(async () => ({ target: null, items: [], why: "" })) }));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const nav = vi.hoisted(() => ({ requestTab: vi.fn() }));
vi.mock("@/lib/navigate", async original => ({ ...(await original<typeof import("@/lib/navigate")>()), ...nav }));

const { MetricsFigures } = await import("@/components/cockpit/MetricsFigures");

const fig = (over: Partial<BriefingRangeMeasure>): BriefingRangeMeasure => ({
  name: "", metric: "", unit: "EUR", time_kind: "flow", confirmed: true, current: 1, previous: 1, last_year: null, rel: 0,
  rel_last_year: null, status: "final", ...over,
});
const older = (covers: string, compared: string, ends: string) =>
  ({ start: "", end: "", data_ends: ends, covers, compared_with: compared, why: `its data ends ${ends}, before this range` });
const REASON = "its dates cannot be set by rule: its table has no date the profiler recognised";

// As the server sends it (2026-10-23): a range's figures are its own, so a metric whose data ended has none — its
// not-measured row names the day its data ends.
const ended = (name: string, metric: string, ends: string) =>
  ({ name, metric, reason: `its data ends ${ends}, before this range`, data_ends: ends });

const PERIOD: Omit<BriefingRangeBlock, "measured" | "unmeasured"> = {
  period: "month", key: "k", preset: "previous_month", label: "Last month", start: "2026-09-01", end: "2026-10-01",
  last_day: "2026-09-30", previous_start: "2026-08-01", previous_end: "2026-08-31", last_year_start: null, last_year_end: null,
  as_of: "2026-10-13", lag_days: 12, lag_source: "default", still_moving: [], covers: "September 2026",
  compared_with: "August 2026", last_year_label: null,
};
const AOV = fig({ name: "Average Order Value (AOV)", metric: "aov", current: 581, previous: 598, rel: -0.0284,
  current_text: "€581", previous_text: "€598" });
const NOT_SET = ["Item Return Rate", "Gross Margin %", "Marketing ROAS", "Session Conversion Rate"].map(name => ({ name, reason: REASON }));

const LUX: BriefingRangeBlock = {
  ...PERIOD,
  measured: [AOV],
  unmeasured: [
    ended("Clienteling-Influenced GMV per Interaction", "gmv_int", "2025-06-29"),
    ended("Markdown Penetration", "markdown", "2024-04-05"),
    ended("Average Inventory Weeks of Cover", "cover", "2025-06-30"),
    ...NOT_SET,
  ],
};

// The same month stored before the rule: each ended metric read over its own last month, among the figures.
const LUX_STORED: BriefingRangeBlock = {
  ...PERIOD,
  measured: [
    fig({ name: "Clienteling-Influenced GMV per Interaction", metric: "gmv_int", current: 15098, previous: 13156, rel: 0.1476,
      current_text: "€15,098", previous_text: "€13,156", anchored: older("May 2025", "April 2025", "2025-06-29") }),
    fig({ name: "Markdown Penetration", metric: "markdown", unit: "ratio 0..1", current: 1, previous: 1, rel: 0,
      current_text: "100%", previous_text: "100%", anchored: older("March 2024", "February 2024", "2024-04-05") }),
    AOV,
    fig({ name: "Average Inventory Weeks of Cover", metric: "cover", time_kind: "stock", current: 11.73, previous: null, rel: null,
      current_text: "11.73", previous_text: "no value", current_partial: "2025-06-30 to 2025-06-30",
      anchored: older("June 2025", "May 2025", "2025-06-30") }),
  ],
  unmeasured: NOT_SET,
};

describe("the Metrics cockpit, figures first", () => {
  it("leads with what moved — the period's own figure — against its comparison, as two bars", async () => {
    render(<MetricsFigures connectionId="dcc63d83" schema="luxexperience" block={LUX} />);
    const hero = await screen.findByTestId("cockpit-hero");
    expect(hero).toHaveTextContent("Average Order Value (AOV)");
    expect(within(hero).getByTestId("cockpit-hero-value")).toHaveTextContent("€581");
    expect(hero).toHaveTextContent("▼ 3%");
    expect(within(hero).getByTestId("cockpit-hero-bars")).toHaveTextContent("1–30 Aug€598Sep 2026€581");
    expect(hero).not.toHaveTextContent("Clienteling");
  });

  it.each([["as the server sends it", LUX], ["as a stored block kept it", LUX_STORED]])(
    "shows a metric whose data ended as a hatched card saying when — never a figure from its own month (%s)", async (_, block) => {
      render(<MetricsFigures connectionId="dcc63d83" block={block} />);
      const cards = await screen.findAllByTestId("figure-unmeasured");
      expect(cards.map(c => c.textContent)).toEqual([
        "Clienteling-Influenced GMV per Interaction—data ended Jun 2025",
        "Markdown Penetration—data ended Apr 2024",
        "Average Inventory Weeks of Cover—data ended Jun 2025",
        ...NOT_SET.map(u => `${u.name}—not measured`)]);
      expect(cards[0]).toHaveAttribute("title", "Its data ends 2025-06-29, before this range");
      for (const metric of ["gmv_int", "markdown", "cover"]) expect(screen.queryByTestId(`figure-${metric}`)).toBeNull();
      expect(screen.getByTestId("metrics-figures")).not.toHaveTextContent(/€15,098|May 2025|March 2024/);
      expect(screen.getByTestId("cockpit-hero")).toHaveTextContent("Average Order Value (AOV)");
    });

  it("draws the unmeasured as hatched cards and says why once, under Needs you, with the way to set them", async () => {
    render(<MetricsFigures connectionId="dcc63d83" block={LUX} />);
    expect(await screen.findAllByTestId("figure-unmeasured")).toHaveLength(7);
    const needs = screen.getByTestId("cockpit-needs");
    expect(needs).toHaveAttribute("data-waiting", "true");
    const row = within(needs).getByTestId("needs-unmeasured");
    expect(row).toHaveTextContent("4 approved metrics can't be measured for a period");
    expect(row).toHaveTextContent("Item Return Rate, Gross Margin %, Marketing ROAS, Session Conversion Rate");
    expect(within(needs).getAllByTestId("needs-unmeasured")).toHaveLength(1);       // one reason, said once
    fireEvent.click(within(row).getByRole("button", { name: "Set their dates" }));
    expect(nav.requestTab).toHaveBeenCalledWith("semantic", { conn: "dcc63d83" });
    const gone = within(needs).getByTestId("needs-ended");
    expect(gone).toHaveTextContent("3 approved metrics have no data for this period");
    expect(gone).toHaveTextContent("Clienteling-Influenced GMV per Interaction, Markdown Penetration, Average Inventory Weeks of Cover"
      + " — their data stops Apr 2024 to Jun 2025");
    expect(within(gone).queryByRole("button")).toBeNull();          // no setting brings their rows back
  });

  it("keeps the whole table behind Details, mounted — so its expected-next bands are still asked for", async () => {
    render(<MetricsFigures connectionId="dcc63d83" block={LUX} />);
    const table = await screen.findByTestId("cockpit-table");
    expect(table).not.toBeVisible();
    expect(api.readExpectedNext).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("cockpit-details"));
    expect(table).toBeVisible();
    expect(within(table).getByText("Measured for September 2026 · against August 2026")).toBeInTheDocument();
  });
});
