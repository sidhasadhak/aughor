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

// As the server sends it (2026-10-23): a range's figures are its own, so a metric whose data ended rides on its
// not-measured row with the figure for the month it last covers (`latest`) — the Cockpit puts it back on a card.
const ended = (name: string, ends: string, latest: BriefingRangeMeasure) =>
  ({ name, metric: latest.metric, reason: `its data ends ${ends}, before this range`, data_ends: ends, latest });

const LUX: BriefingRangeBlock = {
  period: "month", key: "k", preset: "previous_month", label: "Last month", start: "2026-09-01", end: "2026-10-01",
  last_day: "2026-09-30", previous_start: "2026-08-01", previous_end: "2026-08-31", last_year_start: null, last_year_end: null,
  as_of: "2026-10-13", lag_days: 12, lag_source: "default", still_moving: [], covers: "September 2026",
  compared_with: "August 2026", last_year_label: null,
  measured: [
    fig({ name: "Average Order Value (AOV)", metric: "aov", current: 581, previous: 598, rel: -0.0284,
      current_text: "€581", previous_text: "€598" }),
  ],
  unmeasured: [
    ended("Clienteling-Influenced GMV per Interaction", "2025-06-29", fig({ name: "Clienteling-Influenced GMV per Interaction",
      metric: "gmv_int", current: 15098, previous: 13156, rel: 0.1476,
      current_text: "€15,098", previous_text: "€13,156", anchored: older("May 2025", "April 2025", "2025-06-29") })),
    ended("Markdown Penetration", "2024-04-05", fig({ name: "Markdown Penetration", metric: "markdown", unit: "ratio 0..1",
      current: 1, previous: 1, rel: 0, current_text: "100%", previous_text: "100%",
      anchored: older("March 2024", "February 2024", "2024-04-05") })),
    ended("Average Inventory Weeks of Cover", "2025-06-30", fig({ name: "Average Inventory Weeks of Cover", metric: "cover",
      time_kind: "stock", current: 11.73, previous: null, rel: null, current_text: "11.73", previous_text: "no value",
      current_partial: "2025-06-30 to 2025-06-30", anchored: older("June 2025", "May 2025", "2025-06-30") })),
    ...["Item Return Rate", "Gross Margin %", "Marketing ROAS", "Session Conversion Rate"].map(name => ({ name, reason: REASON })),
  ],
};

describe("the Metrics cockpit, figures first", () => {
  it("leads with what moved — the period's own figure — against its comparison, as two bars", async () => {
    render(<MetricsFigures connectionId="dcc63d83" schema="luxexperience" block={LUX} />);
    const hero = await screen.findByTestId("cockpit-hero");
    expect(hero).toHaveTextContent("Average Order Value (AOV)");
    expect(within(hero).getByTestId("cockpit-hero-value")).toHaveTextContent("€581");
    expect(hero).toHaveTextContent("▼ 3%");
    expect(within(hero).getByTestId("cockpit-hero-bars")).toHaveTextContent("1–30 Aug€598Sep 2026€581");
    // GMV per interaction moved more (+15%), but it is May 2025's figure, so it does not lead
    expect(hero).not.toHaveTextContent("Clienteling");
  });

  it("says each older figure's own month on its card, and a part-covered one's span", async () => {
    render(<MetricsFigures connectionId="dcc63d83" block={LUX} />);
    expect(await screen.findByTestId("figure-older-gmv_int")).toHaveTextContent("May 2025");
    expect(screen.getByTestId("figure-gmv_int")).toHaveTextContent("vs April 2025");
    expect(screen.getByTestId("figure-cover")).toHaveTextContent("June 2025");
    expect(screen.getByTestId("figure-cover")).toHaveTextContent("covers only 30 Jun 2025");
    // the hero is not repeated as a figure
    expect(screen.queryByTestId("figure-aov")).toBeNull();
  });

  it("draws the unmeasured as hatched cards and says why once, under Needs you, with the way to set them", async () => {
    render(<MetricsFigures connectionId="dcc63d83" block={LUX} />);
    expect(await screen.findAllByTestId("figure-unmeasured")).toHaveLength(4);
    const needs = screen.getByTestId("cockpit-needs");
    expect(needs).toHaveAttribute("data-waiting", "true");
    const row = within(needs).getByTestId("needs-unmeasured");
    expect(row).toHaveTextContent("4 approved metrics can't be measured for a period");
    expect(row).toHaveTextContent("Item Return Rate, Gross Margin %, Marketing ROAS, Session Conversion Rate");
    expect(within(needs).getAllByTestId("needs-unmeasured")).toHaveLength(1);       // one reason, said once
    fireEvent.click(within(row).getByRole("button", { name: "Set their dates" }));
    expect(nav.requestTab).toHaveBeenCalledWith("semantic", { conn: "dcc63d83" });
    expect(within(needs).getByTestId("needs-older")).toHaveTextContent(
      "3 figures are from before this period");
    expect(within(needs).getByTestId("needs-older")).toHaveTextContent("their data stops Apr 2024 to Jun 2025");
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
