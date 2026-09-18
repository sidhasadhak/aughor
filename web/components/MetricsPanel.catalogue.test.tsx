// @vitest-environment jsdom
/**
 * The Metrics sub-tab lists the metrics that apply to ONE connection.
 *
 * Asked for 2026-09-18: "per connection list of metrics derived by the explorer agent …
 * combination of Industry type that user selects in the settings + plus analysis of the
 * explorer agent and its judgement … in a table format and expanded upon click so that it
 * could be edited."
 *
 * Before this the panel called `getMetrics()` with no argument, so it showed every metric
 * on every connection, and neither the industry packages nor the explorer's own proposals
 * reached it at all.
 *
 * What these pin is the honesty of the table, not its looks: "applicable" and "available"
 * are different claims, and a row that blurred them would be the confident-wrong report in
 * miniature.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogueMetric } from "@/lib/api";

const getMetrics = vi.fn();
const getMetricCatalogue = vi.fn();
const materialiseMetric = vi.fn();

vi.mock("@/lib/api", () => ({
  getMetrics: (...a: unknown[]) => getMetrics(...a),
  getMetricCatalogue: (...a: unknown[]) => getMetricCatalogue(...a),
  materialiseMetric: (...a: unknown[]) => materialiseMetric(...a),
  createMetric: vi.fn(),
  updateMetric: vi.fn(),
  deleteMetric: vi.fn(),
  validateMetric: vi.fn(),
  getMetricFreshness: vi.fn(),
  transitionMetric: vi.fn(),
  getMetricAudit: vi.fn(),
}));

import { MetricsPanel } from "@/components/MetricsPanel";

function row(over: Partial<CatalogueMetric> = {}): CatalogueMetric {
  return {
    name: "gmv", label: "Gross Merchandise Value", source: "explorer", state: "proposed",
    sql: "SUM(sale_price)", unit: "EUR", definition: "Total sales volume.", grain: "",
    dimensions: [], tables: ["order_items"], anti_patterns: [], pack_id: "",
    required_roles: [], missing_roles: [], sane_range: null,
    why_it_matters: "Primary indicator of scale.", status: "", version: 0, owner: "",
    editable: false, ...over,
  };
}

const CATALOGUE = [
  row({ name: "gmv", label: "Gross Merchandise Value", source: "explorer" }),
  row({
    name: "net_interest_margin", label: "Net interest margin", source: "industry",
    state: "needs_binding", missing_roles: ["financial_period"], pack_id: "banking",
    sql: "SUM({{role.financial_period.x}})", tables: [],
  }),
  row({
    name: "return_rate", label: "Return Rate", source: "defined", state: "defined",
    status: "draft", editable: true,
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
  getMetrics.mockResolvedValue([
    { name: "return_rate", label: "Return Rate", sql: "x", connection: "c1", tables: [],
      dimensions: [], filters: [], quality_tests: [], lineage: [], wrong_usage_examples: [],
      status: "draft", version: 0 },
  ]);
  getMetricCatalogue.mockResolvedValue({
    connection_id: "c1", metrics: CATALOGUE,
    counts: { total: 3, defined: 1, industry: 1, explorer: 1, needs_binding: 1, needs_formula: 0 },
  });
});

describe("the list is scoped to the connection", () => {
  it("asks the catalogue for THIS connection", async () => {
    render(<MetricsPanel connId="c1" />);
    await screen.findByText("Gross Merchandise Value");
    expect(getMetricCatalogue).toHaveBeenCalledWith("c1");
    expect(getMetrics).toHaveBeenCalledWith("c1");
  });

  it("says nothing applies rather than showing another connection's metrics", async () => {
    getMetricCatalogue.mockResolvedValue({ connection_id: "c1", metrics: [], counts: {} });
    render(<MetricsPanel connId="c1" />);
    expect(await screen.findByText(/Nothing applies to this connection yet/)).toBeInTheDocument();
  });
});

describe("a row says where it came from and whether it can be computed", () => {
  it("shows all three sources", async () => {
    render(<MetricsPanel connId="c1" />);
    await screen.findByText("Gross Merchandise Value");
    expect(screen.getByText("Explorer")).toBeInTheDocument();
    expect(screen.getByText("Industry")).toBeInTheDocument();
    expect(screen.getByText("Defined")).toBeInTheDocument();
  });

  it("marks an unbound industry recipe rather than implying it is available", async () => {
    render(<MetricsPanel connId="c1" />);
    await screen.findByText("Net interest margin");
    expect(screen.getByText("Needs binding")).toBeInTheDocument();
  });
});

describe("opening a row", () => {
  it("expands in place and names the roles a blocked recipe is missing", async () => {
    const user = userEvent.setup();
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Net interest margin"));
    expect(await screen.findByText(/has not bound financial_period/)).toBeInTheDocument();
  });

  it("refuses to customise a recipe this connection cannot compute", async () => {
    const user = userEvent.setup();
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Net interest margin"));
    const btn = await screen.findByRole("button", { name: /Customise for this connection/i });
    expect(btn).toBeDisabled();
    expect(materialiseMetric).not.toHaveBeenCalled();
  });

  it("copies a computable one on request, scoped to the connection", async () => {
    const user = userEvent.setup();
    materialiseMetric.mockResolvedValue({
      name: "gmv", label: "Gross Merchandise Value", sql: "SUM(sale_price)", connection: "c1",
      tables: [], dimensions: [], filters: [], quality_tests: [], lineage: ["explorer"],
      wrong_usage_examples: [], status: "draft", version: 0,
    });
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Gross Merchandise Value"));
    await user.click(await screen.findByRole("button", { name: /Customise for this connection/i }));
    expect(materialiseMetric).toHaveBeenCalledWith("c1", "gmv");
  });

  it("surfaces a refusal instead of failing silently", async () => {
    const user = userEvent.setup();
    materialiseMetric.mockRejectedValue(new Error("needs financial_period bound"));
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Gross Merchandise Value"));
    await user.click(await screen.findByRole("button", { name: /Customise for this connection/i }));
    expect(await screen.findByText(/needs financial_period bound/)).toBeInTheDocument();
  });
});

describe("a published range is provenance, not a measurement", () => {
  it("says who published it and that it is not your data", async () => {
    const user = userEvent.setup();
    getMetricCatalogue.mockResolvedValue({
      connection_id: "c1",
      metrics: [row({
        name: "nim", label: "Net interest margin", source: "industry", state: "proposed",
        pack_id: "banking", sane_range: { min: 0.01, max: 0.034, basis: "FDIC 2026 Q2", sources: ["fdic-qbp"] },
      })],
      counts: { total: 1 },
    });
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Net interest margin"));
    const range = await screen.findByText(/FDIC 2026 Q2/);
    expect(range).toBeInTheDocument();
    expect(screen.getByText(/not a measurement of your data/i)).toBeInTheDocument();
  });
});
