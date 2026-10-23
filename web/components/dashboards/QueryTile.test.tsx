// @vitest-environment jsdom

/**
 * A card of a person's own query, drawn through the cockpit's own renderer (Arc AP-7): as it was set up — a chart, a
 * figure, a table — never by its result's shape; what the run left out said beneath it; a query that cannot be read
 * said in its place and counted by the builder's checks. A run from a server with queries off draws as every card did.
 */
import { render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { CardRunResult, DashboardCard } from "@/lib/api";
import type { DashboardHostState } from "@/lib/dashboards/hostState";

const vega = vi.hoisted(() => ({ specs: [] as Record<string, unknown>[] }));
vi.mock("@/components/charts/vega/VegaChart", () => ({
  VegaChart: (p: { spec: Record<string, unknown> }) => { vega.specs.push(p.spec); return <div data-testid="vega-stub" />; },
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };
const shown = (as: string, extra: Record<string, unknown> = {}) => ({ as, summed: true, x: "day", bucket: "day", series: [{ column: "sales", agg: "sum" }],
  split: "country", top: 4, segments: "stacked", running: false, labels: false, columns: [], sort: "", descending: true, label: "", ...extra });
const card = (as: string) => ({
  id: "q1", title: "Sales by day, by country", kind: as === "figure" ? "kpi" : "chart", own: true, connection_id: "thelook", scope: "user",
  scope_ref: "default", source: "authored", sql: "SELECT 1", thresholds: {}, provenance: {}, links: [],
  render: { shown: shown(as), columns: [] }, refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] },
}) as unknown as DashboardCard;
const run = (extra: Partial<CardRunResult>): CardRunResult => ({ columns: [], rows: [], row_count: 0, caveats: [], error: null, value: null,
  refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] }, duration_ms: 1089.8, ...extra } as CardRunResult);
const desk = { root: "cockpit", elements: {
  cockpit: { type: "Cockpit", props: { title: "Sales desk" }, children: ["sec"] },
  sec: { type: "Section", props: { title: "This fortnight" }, children: ["c"] },
  c: { type: "Card", props: { card: "q1" }, children: [] },
} };
const draw = (c: DashboardCard, r: CardRunResult, onReadState = vi.fn()) => render(
  <ComposedDashboard spec={desk} cards={[{ card: c, run: r }]} host={HOST} doors={{ onRefresh: vi.fn(), onReadState }} connectionId="thelook" />);

describe("a card of a person's own query", () => {
  it("is drawn as the chart it was set up as — even a date series, which every other card draws as a line", () => {
    vega.specs = [];
    draw(card("bar"), run({ columns: ["x", "s", "v0"], rows: [["2026-10-09", "China", 2012]], shown: {
      as: "bar", x: { name: "day", kind: "date", bucket: "day" }, series: ["China", "Other"], other: true,
      points: [{ x: "2026-10-09", s: "China", v: 2012 }, { x: "2026-10-09", s: "Other", v: 1626 }, { x: "2026-10-10", s: "China", v: 49363 }],
      said: ["Only the first 2,000 groups are drawn; split by fewer values or put the dates in larger buckets."] } }));
    const tile = screen.getByTestId("query-tile-chart").closest("[data-testid='dashboard-tile']") as HTMLElement;
    expect(tile).toHaveAttribute("data-shape", "rows");
    expect(screen.getByTestId("dashboard-card")).toHaveAttribute("data-size", "wide");          // a chart takes two columns
    expect(within(tile).getByTestId("vega-stub")).toBeInTheDocument();
    const [layer] = vega.specs.at(-1)!.layer as { mark: { type: string }; encoding: { y: { stack: unknown } } }[];
    expect(layer.mark.type).toBe("bar");
    expect(layer.encoding.y.stack).toBe("zero");
    expect(within(tile).getByTestId("query-tile-said")).toHaveTextContent("Only the first 2,000 groups are drawn");
    expect(tile).toHaveTextContent("Your query · 1.1 s · read straight from the tables");
  });

  it("is a figure with its label, or a table of the columns it shows, each cell written as its type reads", () => {
    draw(card("figure"), run({ value: 618820, shown: { as: "figure", value: 618820, label: "Sales, last 14 days", said: [] } }));
    expect(screen.getByTestId("query-tile-figure")).toHaveTextContent("618,820");
    expect(screen.getByTestId("query-tile-figure")).toHaveTextContent("Sales, last 14 days");
    expect(screen.getByTestId("dashboard-card")).toHaveAttribute("data-size", "small");          // a figure, one
  });

  it("shows a table's typed columns, its numbers to the right", () => {
    draw(card("table"), run({ shown: { as: "table", columns: [{ name: "country", type: "VARCHAR" }, { name: "sales", type: "DOUBLE" }],
      rows: [["China", 203868.4], ["United States", 140950]], more: true, said: ["The first 200 rows; the query returns more."] } }));
    const table = screen.getByTestId("query-tile-table");
    expect(within(table).getAllByRole("row").map(r => r.textContent)).toEqual(["countrysales", "China203,868.4", "United States140,950"]);
    expect(within(table).getAllByRole("columnheader")[1]).toHaveStyle({ textAlign: "right" });
    expect(screen.getByTestId("query-tile-said")).toHaveTextContent("The first 200 rows");
  });

  it("says in its place why it cannot be read, and the builder's checks count it as one to fix", async () => {
    const onReadState = vi.fn();
    draw(card("bar"), run({ shown: null, error: "This query reads orders straight from its table, and Order has a row policy: a query cannot be narrowed to each reader. Read Order through a set instead." }), onReadState);
    expect(screen.getByTestId("query-tile-unread")).toHaveTextContent("This query cannot be read: This query reads orders straight from its table");
    await waitFor(() => expect(onReadState).toHaveBeenCalledWith("c", { status: "refused", reason: expect.stringContaining("Sales by day, by country: This query reads orders") }));
  });

  it("is drawn as every card was when the server ran it with queries off — the run says nothing of how it is shown", () => {
    draw(card("bar"), run({ columns: ["n"], rows: [[42]], value: 42 }));
    expect(screen.queryByTestId("query-tile-chart")).toBeNull();
    expect(screen.getByTestId("dashboard-tile")).toHaveAttribute("data-shape", "figure");
  });
});
