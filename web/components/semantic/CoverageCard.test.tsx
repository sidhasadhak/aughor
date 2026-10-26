// @vitest-environment jsdom
/**
 * Arc MC — the coverage view on the Metrics tab (the user, 2026-10-26: "only 12 proposed metrics.. not even 50% of the
 * matrix"). The areas a business like this one is read by, in the map's order, each with its data, its metrics and its
 * proposals; an area is covered only by an approved metric whose figures move; a proposal a gate refused says why and
 * is never offered for adoption. Absent while the view is off.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getMetricCoverage: vi.fn(), runMetricCoverage: vi.fn(), writeMetricCoverage: vi.fn(), getMetricProposals: vi.fn(),
  adoptMetrics: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { CoverageCard, gateLine, proposalsOf } from "./CoverageCard";
import type { CatalogueMetric, CoverageArea, MetricCoverage } from "@/lib/api";
import { standingChip, standingOf } from "@/lib/semanticMetrics";

const area = (id: string, name: string, over: Partial<CoverageArea> = {}): CoverageArea => ({
  id, name, question: `${name}?`, pack_id: "retail", generic: false, order: 0, patterns: [], recipes: [], state: "uncovered",
  has_data: true, rows: 1000, tables: [{ name: id, rows: 1000, dated: true, why: `its name says ${id}` }], metrics: [],
  proposals: 0, adoptable: 0, failed: 0, declined: 0, said: [], ...over,
});

const COVERAGE: MetricCoverage = {
  connection_id: "dcc63d83", schema: "luxexperience", industry_pack: "retail",
  areas: [
    area("orders_sales", "Orders & sales", { state: "covered", metrics: [
      { name: "gmv", label: "GMV", status: "approved", why: "it is the knowledge base's GMV", moves: { ok: true, why: "" } }] }),
    area("returns", "Returns", { proposals: 2, adoptable: 1, failed: 1, metrics: [
      { name: "return_rate", label: "Return rate", status: "approved", why: "its name says return",
        moves: { ok: false, why: "it reads 1 in every one of the last 6 months with figures" } }],
      said: ["Return rate does not cover it: it reads 1 in every one of the last 6 months with figures"] }),
    area("clienteling_events", "Clienteling & events", { state: "no_data", has_data: false, rows: 0, tables: [],
      said: ["the knowledge base carries no pattern for this area yet — a package can add one"] }),
  ],
  unplaced_tables: ["countries", "dim_date"], said: [],
  counts: { areas: 3, with_data: 2, covered: 1, uncovered: 1, unchecked: 0, patterns: 40 },
  proposals: [
    { name: "refund_value", label: "Refund value", area: "returns", source: "pattern", pattern: "refund_rate",
      pattern_title: "Refund Rate", state: "gate_failed", reason: "it moves — no: it reads 0",
      gates: { runs: { ok: true, why: "" }, moves: { ok: false, why: "it reads 0 in every one of the last 6 months" } },
      sql: "SELECT SUM(refund_eur) FROM returns", time_column: "returns.return_date", definition: "" },
    { name: "item_return_rate_v2", label: "Item return rate", area: "returns", source: "pattern", pattern: "ec_return_rate",
      pattern_title: "Order Return Rate", state: "proposed", reason: "",
      gates: { runs: { ok: true, why: "" }, moves: { ok: true, why: "" }, twin: { ok: null, why: "" } },
      sql: "SELECT 1", time_column: "order_items.created_at", definition: "" },
  ],
  run: { run_at: "2026-10-26T18:00:00+00:00", why: "the connection was profiled", said: [],
         spend: { calls: 4, model: "test-model", at: "2026-10-26T18:00:00+00:00", why: "the connection was profiled", areas: [] } },
  flags: { "metrics.coverage_proposals": true, "metrics.coverage_writer": true, "metrics.blind_spot_proposals": false },
};

const catalogueRow = (over: Partial<CatalogueMetric>): CatalogueMetric => ({
  name: "m", label: "M", source: "coverage", state: "proposed", sql: "SELECT 1", unit: "", definition: "", grain: "",
  dimensions: [], tables: [], anti_patterns: [], pack_id: "", required_roles: [], missing_roles: [], sane_range: null,
  why_it_matters: "", reason: "", status: "", version: 0, owner: "", editable: false, schema: "luxexperience", ...over,
});

beforeEach(() => {
  Object.values(api).forEach(f => f.mockReset());
  api.getMetricCoverage.mockResolvedValue(COVERAGE);
  api.getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", note: "", candidates: [] });
});

describe("CoverageCard", () => {
  it("is absent while the coverage view is off", async () => {
    api.getMetricCoverage.mockResolvedValue(null);
    const { container } = render(<CoverageCard connId="dcc63d83" rows={[]} onAdopted={() => {}} />);
    await waitFor(() => expect(api.getMetricCoverage).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="metric-coverage"]')).toBeNull();
  });

  it("lists the areas in the map's order, each with its state, and says the model calls made", async () => {
    render(<CoverageCard connId="dcc63d83" schema="luxexperience" rows={[]} onAdopted={() => {}} />);
    const card = await screen.findByTestId("metric-coverage");
    expect(card).toHaveTextContent("1 of 2 areas with data covered");
    const areas = within(card).getAllByTestId("coverage-area");
    expect(areas.map(a => a.getAttribute("data-area"))).toEqual(["orders_sales", "returns", "clienteling_events"]);
    expect(within(areas[0]).getByTestId("coverage-state")).toHaveTextContent("covered");
    expect(within(areas[1]).getByTestId("coverage-state")).toHaveTextContent("no working metric");
    expect(within(areas[1]).getByText("1 ready · 1 failed")).toBeInTheDocument();
    expect(screen.getByTestId("coverage-unplaced")).toHaveTextContent("Placed in no area: countries, dim_date.");
    expect(screen.getByTestId("coverage-spend")).toHaveTextContent("test-model: 4 model calls, one per area");
    expect(screen.getByTestId("coverage-spend")).toHaveTextContent("the connection was profiled");
  });

  it("opens an area with its data, the metric that never moves, and each proposal's checks", async () => {
    render(<CoverageCard connId="dcc63d83" rows={[]} onAdopted={() => {}} />);
    const returns = (await screen.findAllByTestId("coverage-area"))[1];
    fireEvent.click(within(returns).getByRole("button"));
    const detail = within(returns).getByTestId("coverage-detail");
    expect(detail).toHaveTextContent("Return rate does not cover it: it reads 1 in every one");
    expect(within(detail).getByText("never moves")).toBeInTheDocument();
    const proposals = within(detail).getAllByTestId("coverage-proposal");
    expect(proposals[0]).toHaveTextContent("Item return rate");                         // what passed comes first
    expect(proposals[0]).toHaveTextContent("passed every check");
    expect(proposals[1]).toHaveTextContent("failed a check");
    expect(proposals[1]).toHaveTextContent("moves: no — it reads 0 in every one of the last 6 months");
  });

  it("reads the approved figures again when an area's are not checked yet", async () => {
    const unchecked = { ...COVERAGE, areas: [area("orders_sales", "Orders & sales", { state: "unchecked" })] };
    api.getMetricCoverage.mockResolvedValueOnce(unchecked).mockResolvedValueOnce(COVERAGE);
    render(<CoverageCard connId="dcc63d83" rows={[]} onAdopted={() => {}} />);
    await waitFor(() => expect(api.getMetricCoverage).toHaveBeenLastCalledWith("dcc63d83", undefined, true));
  });

  it("proposes by code on a click, on a thread, and says to read it again", async () => {
    api.runMetricCoverage.mockResolvedValue({ started: true });
    render(<CoverageCard connId="dcc63d83" rows={[]} onAdopted={() => {}} />);
    fireEvent.click(await screen.findByText("Propose by code"));
    expect(await screen.findByTestId("coverage-note")).toHaveTextContent("Proposing — each proposal's figures are read");
  });
});

describe("a coverage proposal", () => {
  it("orders an area's proposals passed first, and says a failed gate in its own words", () => {
    expect(proposalsOf(COVERAGE, "returns").map(p => p.name)).toEqual(["item_return_rate_v2", "refund_value"]);
    expect(gateLine(COVERAGE.proposals[1].gates)).toBe("✓ runs · moves — not read: not a twin");
  });

  it("that a gate refused stands as failed a check, with the reason on hover, and is not adoptable", () => {
    const r = catalogueRow({ state: "gate_failed", reason: "it moves — no: it reads 1" });
    const standing = standingOf(r, null);
    expect(standing).toBe("check_failed");
    const chip = standingChip({ row: r, key: "k", standing, stored: null, duplicate: false } as never);
    expect(chip).toEqual({ tone: "amber", text: "failed a check", title: "it moves — no: it reads 1" });
  });
});
