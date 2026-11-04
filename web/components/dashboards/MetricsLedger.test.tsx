// @vitest-environment jsdom
/**
 * The Metrics dashboard as a ledger (`design-mockups/metric-ledger-lux.html`). All splits by area and nothing else; Key
 * movements is the same rows, what is outside its usual range, most concerning first; a metric opens in its own row.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BriefingRangeBlock, BriefingRangeMeasure } from "@/lib/api";
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";

const api = vi.hoisted(() => ({
  readExpectedNext: vi.fn(), readMetricTrend: vi.fn(), readBriefingEdition: vi.fn(), getMetricCoverage: vi.fn(), writeBriefingEdition: vi.fn(),
}));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const nav = vi.hoisted(() => ({ requestTab: vi.fn() }));
vi.mock("@/lib/navigate", async original => ({ ...(await original<typeof import("@/lib/navigate")>()), ...nav }));

const { MetricsLedger } = await import("@/components/dashboards/MetricsLedger");

const SALES = { id: "orders_sales", name: "Orders & sales", order: 0 }, RETURNS = { id: "returns", name: "Returns", order: 1 };
const MARGIN = { id: "margin_pricing", name: "Margin & pricing", order: 2 }, TRAFFIC = { id: "traffic", name: "Traffic & conversion", order: 5 };
const CRM = { id: "crm", name: "CRM & consent", order: 8 };

const fig = (over: Partial<BriefingRangeMeasure>): BriefingRangeMeasure => ({
  name: "", metric: "", unit: "EUR", time_kind: "flow", confirmed: true, current: 100, previous: 90, last_year: 80, rel: 0.11, rel_last_year: 0.25, status: "final", ...over,
});

const BLOCK: BriefingRangeBlock = {
  period: "month", key: "oct", preset: "last_month", label: "Last month", start: "2026-10-01", end: "2026-11-01", last_day: "2026-10-31",
  previous_start: "2026-09-01", previous_end: "2026-10-01", last_year_start: "2025-10-01", last_year_end: "2025-11-01", as_of: "2026-11-04",
  lag_days: 1, lag_source: "default", still_moving: [], covers: "October 2026", compared_with: "September 2026", last_year_label: "a year earlier",
  measured: [
    fig({ name: "GMV (EUR)", metric: "gmv", current: 712125, previous: 721755, last_year: 704142, rel: -0.013, rel_last_year: 0.011, better: "up", area: SALES }),
    fig({ name: "Average Order Value", metric: "aov", current: 623, previous: 581, last_year: 518, rel: 0.072, rel_last_year: 0.2, better: "up", area: SALES }),
    fig({ name: "Net Revenue (EUR, after refunds)", metric: "net", current: 507948, previous: 417910, last_year: 423430, rel: 0.215, rel_last_year: 0.2, better: "up", area: SALES }),
    fig({ name: "Item Return Rate", metric: "returns", unit: "ratio 0..1", time_kind: "cohort", current: 0.206, previous: 0.185, last_year: 0.175, status: "provisional", better: "down", area: RETURNS }),
    fig({ name: "Gross Margin on Items", metric: "items", unit: "%", current: 47.14, previous: 43.97, last_year: 45.07, better: "up", area: MARGIN }),
    fig({ name: "Gross Margin %", metric: "margin", unit: "%", current: 47.14, previous: 43.97, last_year: 45.07, better: "up", area: MARGIN }),
    fig({ name: "Session Conversion Rate", metric: "conv", unit: "ratio 0..1", current: 0.0212, previous: 0.0233, last_year: 0.0238, better: "up", area: TRAFFIC }),
  ],
  unmeasured: [
    { name: "Markdown Penetration", metric: "md", reason: "its data ends 2024-04-05, before this range", data_ends: "2024-04-05", area: MARGIN },
    { name: "Email open rate", metric: "o", reason: "its data ends 2025-05-19, before this range", data_ends: "2025-05-19", area: CRM },
    { name: "Email click rate", metric: "c", reason: "its data ends 2025-05-19, before this range", data_ends: "2025-05-19", area: CRM },
    { name: "Cart abandonment", metric: "cart", reason: "its dates are not set", area: SALES },
  ],
} as unknown as BriefingRangeBlock;

const months = (values: number[]) => values.map((value, i) => ({ start: new Date(Date.UTC(2025, 9 + i, 1)).toISOString().slice(0, 10), last_day: "", label: `month ${i}`, value, value_text: "", partial: null, current: false, settling: false }));
const RISING = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2];
const FALLING = [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1];
const FLAT = [5, 5, 5, 5, 5, 5, 5, 4, 6, 4, 6, 5, 5];
const TRENDS: Record<string, unknown> = {
  gmv: { series: months(FLAT), usual: { mean: 5, low: 4, high: 6, n: 6, z: 0.1, outside: "" }, tables: ["orders"], why: "" },
  aov: { series: months(RISING), usual: { mean: 1, low: 0.9, high: 1.1, n: 6, z: 1.4, outside: "above" }, why: "", tables: [] },
  net: { series: months(FLAT), usual: { mean: 5, low: 4, high: 6, n: 6, z: 0.1, outside: "" }, why: "", tables: ["orders", "returns"] },
  returns: { series: months(RISING), usual: { mean: 1, low: 0.9, high: 1.1, n: 6, z: 1.8, outside: "above" }, same_age: true, why: "", tables: [] },
  items: { series: months([44, 45, 46, 45, 44, 45, 44, 46, 46, 44, 44, 44, 47]), usual: { mean: 45, low: 44, high: 46, n: 6, z: 2.2, outside: "above" }, why: "", tables: [] },
  margin: { series: months([44, 45, 46, 45, 44, 45, 44, 46, 46, 44, 44, 44, 47]), usual: { mean: 45, low: 44, high: 46, n: 6, z: 2.2, outside: "above" }, why: "", tables: [] },
  conv: { series: months(FALLING), usual: { mean: 2, low: 1.9, high: 2.1, n: 6, z: -1.6, outside: "below" }, why: "", tables: [] },
};
const EDITION = {
  built: true, scope_key: "c", period: { start: "2026-10-01", last_day: "2026-10-31", measured: [{ id: "net_fig", metric: "net", why: "What is kept after returns are refunded." }] },
  sources: { a1: { id: "a1", kind: "analysis", facts: { completed: "3 Nov", confidence: "MEDIUM", inv_id: "b52cba32" } } },
  blocks: [{ id: "c1", type: "context", source: "a1", text: "Unarrived returns explain most or all of the rise in net revenue." }],
};
const EXPECTED = { why: "", target: { start: "2026-11-01", last_day: "2026-11-30", label: "November 2026", settles_on: "1 Dec" },
  items: [{ metric: "net", name: "Net", why: "", expected: { low: 352780, high: 502831, mid: 427805, text: "352,780 to 502,831", must_say: ["6 earlier ranges, each read as its rows stand today: 352,780 to 502,831 at 80% stated coverage", "on this metric the interval held 1 of 4 times"], state: "open", n: 6, held: 1, cases: 4, coverage: 0.8, claim_id: "", scored_against: null } }] };

const show = (block = BLOCK) => render(<MetricsLedger connectionId="c" schema="lux" block={block} />);
const rows = () => screen.getAllByTestId(/^ledger-row-/).map(r => r.getAttribute("data-testid")!.replace("ledger-row-", ""));
const settled = () => waitFor(() => expect(screen.getByTestId("ledger-tally")).toHaveTextContent("key movement"));

beforeEach(() => {
  vi.clearAllMocks();
  api.readMetricTrend.mockImplementation(async (_c: string, metric: string) => TRENDS[metric]);
  api.readExpectedNext.mockResolvedValue(EXPECTED);
  api.readBriefingEdition.mockResolvedValue(EDITION);
  api.getMetricCoverage.mockResolvedValue({ areas: [
    { name: "Payments & risk", has_data: true, metrics: [] }, { name: "Service", has_data: true, metrics: [] },
    { name: "Receivables", has_data: false, metrics: [] }, { name: "Orders & sales", has_data: true, metrics: [{}] }] });
});

describe("All", () => {
  it("splits entirely by area, in the order the industry reads them, each row keeping its place", async () => {
    show();
    await settled();
    const table = within(screen.getByRole("table"));
    const heads = table.getAllByRole("row").map(r => r.textContent ?? "").filter(t => /^(Orders|Returns|Margin|Traffic|CRM)/.test(t));
    expect(heads.map(h => h.split(/\d/)[0])).toEqual(["Orders & sales", "Returns", "Margin & pricing", "Traffic & conversion", "CRM & consent"]);
    expect(rows()).toEqual(["gmv", "aov", "net", "returns", "items", "margin", "conv"]);
    expect(table.queryByText(/outside its usual range/i)).toBeNull();    // no group of its own: that is the other tab
    expect(table.getAllByRole("row").some(r => r.textContent === "Orders & sales3 · 1 key movement · 1 not measured")).toBe(true);
  });

  it("never moves a row, however late its trend arrives", async () => {
    let finish: (v: unknown) => void = () => {};
    api.readMetricTrend.mockImplementation((_c: string, metric: string) => (metric === "conv" ? new Promise(r => { finish = r; }) : Promise.resolve(TRENDS[metric])));
    show();
    await waitFor(() => expect(screen.getByTestId("ledger-row-aov")).toHaveAttribute("data-key", "true"));
    const before = rows();
    finish(TRENDS.conv);
    await settled();
    expect(rows()).toEqual(before);
    expect(screen.getByTestId("ledger-row-conv")).toHaveAttribute("data-key", "true");
  });

  it("keeps what was not measured in its area, one row per reason, and says why", async () => {
    show();
    await settled();
    const said = screen.getAllByTestId("ledger-not-measured").map(r => r.textContent);
    expect(said).toEqual(expect.arrayContaining(["Markdown PenetrationData ended Apr 2024", "Email open rate, Email click rateData ended May 2025"]));
  });

  it("says what the data holds that no metric reads, and only that", async () => {
    show();
    expect((await screen.findByTestId("ledger-untouched")).textContent).toBe("The data also holds Payments & risk and Service, with no metric reading them yet.");
  });

  it("prints each figure with its unit and colours only what left its usual range", async () => {
    show();
    await settled();
    const aov = within(screen.getByTestId("ledger-row-aov"));
    expect(aov.getByText("€623")).toBeInTheDocument();
    expect(aov.getByText("▲ 7.2%").style.color).toBe("var(--grn4)");
    expect(within(screen.getByTestId("ledger-row-gmv")).getByText("▼ 1.3%").style.color).toBe("var(--t2)");
    expect(within(screen.getByTestId("ledger-row-returns")).getByText("▲ 2.1 pts").style.color).toBe("var(--red4)");   // up is bad here
    expect(within(screen.getByTestId("ledger-row-conv")).getByText("▼ 0.21 pts").style.color).toBe("var(--red4)");
  });

  it("gives a metric nobody has said a direction for no colour", async () => {
    const block = { ...BLOCK, measured: [fig({ name: "Average Order Value", metric: "aov", area: SALES })], unmeasured: [] } as unknown as BriefingRangeBlock;
    show(block);
    await settled();
    expect(within(screen.getByTestId("ledger-row-aov")).getByText("▲ 11%").style.color).toBe("var(--t2)");
  });
});

describe("Key movements", () => {
  it("is the rows outside their usual range, what is bad first, furthest first, each with its area", async () => {
    show();
    await settled();
    fireEvent.click(screen.getByRole("radio", { name: "Key movements 5" }));
    expect(rows()).toEqual(["returns", "conv", "items", "margin", "aov"]);
    expect(within(screen.getByTestId("ledger-row-returns")).getByText("Returns")).toBeInTheDocument();
    expect(screen.queryByTestId("ledger-not-measured")).toBeNull();
  });

  it("counts them in the line above the table, once they are known", async () => {
    show();
    expect(screen.getByTestId("ledger-tally")).not.toHaveTextContent("key movement");
    await settled();
    expect(screen.getByTestId("ledger-tally")).toHaveTextContent("7 measured · 5 key movements · 1 still settling · 4 not measured");
  });

  it("does not count a month still under way", async () => {
    show({ ...BLOCK, measured: BLOCK.measured.map(m => ({ ...m, status: "to_date" as const })) });
    await settled();
    expect(screen.getByTestId("ledger-tally")).toHaveTextContent("0 key movements");
    expect(within(screen.getByTestId("ledger-row-conv")).getByTestId("ledger-readout")).toHaveTextContent("Under way, so not read against its usual range");
  });
});

describe("a row", () => {
  it("does not call a figure not at equal age a key movement, and keeps its name readable", async () => {
    const young = fig({ name: "Revenue", metric: "aov", status: "provisional", better: "up", area: SALES, equal_age: { equal: false, why: "part of any difference is its age" } });
    show({ ...BLOCK, measured: [young], unmeasured: [] } as BriefingRangeBlock);
    await waitFor(() => expect(screen.getByTestId("ledger-tally")).toHaveTextContent("0 key movements"));
    const row = within(screen.getByTestId("ledger-row-aov"));
    expect(row.getByText("not at equal age")).toHaveAttribute("title", "part of any difference is its age");
    expect(row.queryByText("still settling")).toBeNull();
    expect(row.getByTestId("ledger-readout")).toHaveTextContent("Not read against its usual range");
    fireEvent.click(row.getByRole("button", { name: "Revenue" }));
    const open = within(await screen.findByTestId("ledger-reasons"));
    expect(open.getByText(/This figure is not held against it/)).toBeInTheDocument();
    expect(open.queryByText(/^Above its usual range/)).toBeNull();
  });

  it("says what it means in a line, and names a twin", async () => {
    show();
    await settled();
    const says = (m: string) => within(screen.getByTestId(`ledger-row-${m}`)).getByTestId("ledger-readout").textContent;
    expect(says("returns")).toBe("Above usual at this age, highest in 13 months");
    expect(says("conv")).toBe("Below usual, lowest in 13 months");
    expect(says("gmv")).toBe("In usual range");
    await waitFor(() => expect(says("margin")).toBe("Reads the same as Gross Margin on Items"));
  });

  it("opens in its own row: how it reads, what the platform knows, how it is measured", async () => {
    show();
    await settled();
    expect(screen.queryByTestId("ledger-reasons")).toBeNull();
    fireEvent.click(within(screen.getByTestId("ledger-row-net")).getByRole("button", { name: "Net Revenue (EUR, after refunds)" }));
    const open = within(await screen.findByTestId("ledger-reasons"));
    expect(open.getByText(/Inside its usual range of/)).toBeInTheDocument();
    expect(open.getByText("Unarrived returns explain most or all of the rise in net revenue.")).toBeInTheDocument();
    expect(open.getByText("What is kept after returns are refunded.")).toBeInTheDocument();
    const band = open.getByText(/Expected Nov 2026: €352,780 – €502,831/);
    expect(band).toHaveTextContent("A band from its own past, not a target, stated to hold 80% of the time. From 6 earlier ranges, each read as its rows stand today. On this metric it has held 1 of 4 times.");
    expect(band).not.toHaveTextContent("2026-11-01");
    expect(open.getByRole("img", { name: /Net Revenue/ })).toHaveTextContent("Oct ’25");
    expect(open.getByRole("img", { name: /Net Revenue/ })).not.toHaveTextContent("2025-10");
    fireEvent.click(open.getByRole("button", { name: "Open the deep analysis" }));
    expect(nav.requestTab).toHaveBeenCalledWith("chat", { run: "b52cba32" });
  });

  it("offers the platform's work on the row itself", async () => {
    show();
    await settled();
    fireEvent.click(await within(screen.getByTestId("ledger-row-net")).findByRole("button", { name: "deep analysis" }));
    expect(await screen.findByTestId("ledger-reasons")).toBeInTheDocument();
  });

  it("says plainly when the platform has nothing, and tells apart no Briefing from none of its words", async () => {
    show();
    await settled();
    fireEvent.click(within(screen.getByTestId("ledger-row-conv")).getByRole("button", { name: "Session Conversion Rate" }));
    expect(within(await screen.findByTestId("ledger-reasons")).getByText("The Briefing for this range says nothing of this metric.")).toBeInTheDocument();
  });

  it("says on the row when a band has been wrong more often than right, and only then", async () => {
    show();
    await settled();
    expect(within(screen.getByTestId("ledger-row-net")).getByText("held 1 of 4")).toBeInTheDocument();
    expect(within(screen.getByTestId("ledger-row-gmv")).queryByText(/^held/)).toBeNull();
  });

  it("names itself in full when its name is cut short", async () => {
    show();
    await settled();
    expect(within(screen.getByTestId("ledger-row-net")).getByRole("button", { name: "Net Revenue (EUR, after refunds)" })).toHaveAttribute("title", "Net Revenue (EUR, after refunds)");
  });

  it("finds the Briefing for a dashboard's previous month, kept under last month", async () => {
    show({ ...BLOCK, preset: "previous_month" } as BriefingRangeBlock);
    await settled();
    expect(api.readBriefingEdition).toHaveBeenCalledWith("c", { preset: "last_month" }, undefined, "lux");
    expect(await within(screen.getByTestId("ledger-row-net")).findByRole("button", { name: "deep analysis" })).toBeInTheDocument();
  });

  it("does not offer another month's Briefing as this one's", async () => {
    api.readBriefingEdition.mockResolvedValue({ ...EDITION, period: { ...EDITION.period, start: "2026-09-01", last_day: "2026-09-30" } });
    show({ ...BLOCK, preset: "previous_month" } as BriefingRangeBlock);
    await settled();
    await waitFor(() => expect(api.readBriefingEdition).toHaveBeenCalled());
    fireEvent.click(within(screen.getByTestId("ledger-row-net")).getByRole("button", { name: "Net Revenue (EUR, after refunds)" }));
    const open = within(await screen.findByTestId("ledger-reasons"));
    expect(open.getByText(/No Briefing has been written for this range/)).toBeInTheDocument();
    expect(open.queryByText(/Unarrived returns/)).toBeNull();
  });

  it("says when no Briefing was written for the range", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, period: EDITION.period });
    show();
    await settled();
    fireEvent.click(within(screen.getByTestId("ledger-row-net")).getByRole("button", { name: "Net Revenue (EUR, after refunds)" }));
    expect(within(await screen.findByTestId("ledger-reasons")).getByText(/No Briefing has been written for this range/)).toBeInTheDocument();
  });
});

describe("reading the page", () => {
  it("books the period's expected bands, reads the Briefing already written, and writes nothing", async () => {
    show();
    await settled();
    expect(api.readExpectedNext).toHaveBeenCalledWith("c", { preset: "last_month" }, "lux");
    expect(api.readBriefingEdition).toHaveBeenCalledWith("c", { preset: "last_month" }, undefined, "lux");
    expect(api.writeBriefingEdition).not.toHaveBeenCalled();
    expect(screen.getByRole("columnheader", { name: "Expected Nov 2026" })).toBeInTheDocument();
    expect(within(screen.getByTestId("ledger-row-net")).getByText("€352,780 – €502,831")).toBeInTheDocument();
  });

  it("reads at most four trends at once, however many metrics there are", async () => {
    let now = 0, most = 0;
    api.readMetricTrend.mockImplementation(async (_c: string, metric: string) => {
      now += 1; most = Math.max(most, now);
      await new Promise(r => setTimeout(r, 1));
      now -= 1;
      return TRENDS[metric];
    });
    show();
    await settled();
    expect(api.readMetricTrend).toHaveBeenCalledTimes(7);
    expect(most).toBeLessThanOrEqual(4);
  });

  it("says a trend it could not read, and the rest of the page stands", async () => {
    api.readMetricTrend.mockImplementation(async (_c: string, metric: string) => {
      if (metric === "gmv") throw new Error("the warehouse did not answer");
      return TRENDS[metric];
    });
    show();
    await settled();
    expect(within(screen.getByTestId("ledger-row-gmv")).getByTestId("ledger-readout")).toHaveTextContent("Its earlier ranges could not be read");
    expect(within(screen.getByTestId("ledger-row-aov")).getByTestId("ledger-readout")).toHaveTextContent("Above usual");
  });

  it("finds a metric across what was and was not measured, and says how many", async () => {
    show();
    await settled();
    fireEvent.change(screen.getByRole("textbox", { name: "Find a metric" }), { target: { value: "margin" } });
    expect(rows()).toEqual(["items", "margin"]);
    expect(screen.getByTestId("ledger-found")).toHaveTextContent("2 of 11");
    fireEvent.change(screen.getByRole("textbox", { name: "Find a metric" }), { target: { value: "email" } });
    expect(screen.getAllByTestId("ledger-not-measured").map(r => r.textContent)).toEqual(["Email open rate, Email click rateData ended May 2025"]);
    fireEvent.change(screen.getByRole("textbox", { name: "Find a metric" }), { target: { value: "zzz" } });
    expect(screen.getByTestId("ledger-none")).toHaveTextContent("No metric matches “zzz”.");
  });

  it("takes Needs you to what was not measured, and back", async () => {
    show();
    await settled();
    const needs = within(screen.getByTestId("needs-unmeasured"));
    expect(needs.getByText("4 approved metrics are not measured for Oct 2026")).toBeInTheDocument();
    expect(needs.getByText("3 have no data this recent, 1 for another reason")).toBeInTheDocument();
    fireEvent.click(needs.getByRole("button", { name: "See them" }));
    expect(screen.queryAllByTestId(/^ledger-row-/)).toEqual([]);
    expect(screen.getAllByTestId("ledger-not-measured")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Open in the Semantic Layer" }));
    expect(nav.requestTab).toHaveBeenCalledWith("semantic", { conn: "c" });
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(rows()).toHaveLength(7);
  });

  it("says nothing needs a person when every metric is measured", async () => {
    show({ ...BLOCK, unmeasured: [] });
    await settled();
    expect(screen.getByTestId("dashboard-needs")).toHaveTextContent("Nothing needs you — every approved metric is measured for this period");
  });
});
