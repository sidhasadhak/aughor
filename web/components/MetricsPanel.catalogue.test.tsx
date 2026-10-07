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
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogueMetric } from "@/lib/api";

const getMetrics = vi.fn();
const getMetricCatalogue = vi.fn();
const materialiseMetric = vi.fn();
const removeProposal = vi.fn();
const restoreProposal = vi.fn();

vi.mock("@/lib/api", () => ({
  getMetrics: (...a: unknown[]) => getMetrics(...a),
  getMetricCatalogue: (...a: unknown[]) => getMetricCatalogue(...a),
  materialiseMetric: (...a: unknown[]) => materialiseMetric(...a),
  removeProposal: (...a: unknown[]) => removeProposal(...a),
  restoreProposal: (...a: unknown[]) => restoreProposal(...a),
  promoteMetric: vi.fn(),
  getMyAccess: vi.fn(async () => ({ actor: "ana@example.com", signed_in: false })),
  createMetric: vi.fn(),
  updateMetric: vi.fn(),
  deleteMetric: vi.fn(),
  validateMetric: vi.fn(),
  getMetricFreshness: vi.fn(),
  transitionMetric: vi.fn(),
  getMetricAudit: vi.fn(),
  getMetricProposals: vi.fn(async () => ({ statements: [], statement_note: "", candidates: [], note: "" })),
  generateMetricSql: vi.fn(),
}));

import { MetricsPanel } from "@/components/MetricsPanel";

function row(over: Partial<CatalogueMetric> = {}): CatalogueMetric {
  return {
    name: "gmv", label: "Gross Merchandise Value", source: "explorer", state: "proposed",
    sql: "SUM(sale_price)", unit: "EUR", definition: "Total sales volume.", grain: "",
    dimensions: [], tables: ["order_items"], anti_patterns: [], pack_id: "",
    required_roles: [], missing_roles: [], sane_range: null,
    why_it_matters: "Primary indicator of scale.", reason: "", status: "", version: 0, owner: "",
    editable: false, schema: "*", ...over,
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
    expect(getMetricCatalogue).toHaveBeenCalledWith("c1", undefined);
    expect(getMetrics).toHaveBeenCalledWith("c1");
  });

  it("asks for the dataset in scope — the explorer proposes per schema", async () => {
    render(<MetricsPanel connId="c1" schema="uber_ncr" />);
    await screen.findByText("Gross Merchandise Value");
    expect(getMetricCatalogue).toHaveBeenCalledWith("c1", "uber_ncr");
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
    expect(await screen.findByText(/names financial_period/)).toBeInTheDocument();
  });

  it("offers every way forward for a recipe this connection has not bound — never a dead end", async () => {
    // The user, 2026-10-07: "no 'this requires binding' — that's a dead end with no action possible".
    const user = userEvent.setup();
    materialiseMetric.mockResolvedValue({
      name: "net_interest_margin", label: "Net interest margin", sql: "", connection: "c1",
      schema_name: "*", home_schema: "*", tables: [], dimensions: [], filters: [], quality_tests: [],
      lineage: ["industry: banking"], wrong_usage_examples: [], status: "draft", version: 0,
    });
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Net interest margin"));
    const write = await screen.findByRole("button", { name: /Write its SQL for this connection/i });
    expect(write).toBeEnabled();
    expect(screen.getByRole("button", { name: /Bind its roles/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^Remove$/i })).toBeEnabled();
    await user.click(write);
    expect(materialiseMetric).toHaveBeenCalledWith("c1", "net_interest_margin", "*");
  });

  it("removes a proposal on a confirmed click, and lists it to restore", async () => {
    const user = userEvent.setup();
    removeProposal.mockResolvedValue({});
    render(<MetricsPanel connId="c1" />);
    await user.click(await screen.findByText("Gross Merchandise Value"));
    await user.click(await screen.findByRole("button", { name: /^Remove$/i }));
    expect(removeProposal).not.toHaveBeenCalled();
    getMetricCatalogue.mockResolvedValue({
      connection_id: "c1", metrics: CATALOGUE.filter((r) => r.name !== "gmv"), counts: { total: 2 },
      removed: [{ connection: "c1", schema_name: "*", name: "gmv", label: "Gross Merchandise Value",
                  source: "explorer", by: "ana@example.com", at: "2026-10-07T20:00:00+00:00" }],
    });
    await user.click(screen.getByRole("button", { name: /Remove — sure/i }));
    expect(removeProposal).toHaveBeenCalledWith("c1", "gmv", "*");
    await user.click(await screen.findByRole("button", { name: /Removed here \(1\)/ }));
    expect(screen.getByText(/removed by ana@example.com on 2026-10-07/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Restore/ }));
    expect(restoreProposal).toHaveBeenCalledWith("c1", "gmv", "*");
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
    expect(materialiseMetric).toHaveBeenCalledWith("c1", "gmv", "*");
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

describe("a rejected formula is not a missing one", () => {
  // theLook's six metrics all HAD formulas and lost them to the build-time audit. Shown
  // as "Needs a formula" they read as never-written, sending the reader to supply SQL —
  // which would not help, because on that connection nothing binds.
  const REJECTED = row({
    name: "gmv", label: "Gross Merchandise Value", source: "explorer",
    state: "formula_rejected", sql: "",
    reason: "does not bind: Table \"order_items\" must be qualified with a dataset",
  });

  beforeEach(() => {
    getMetricCatalogue.mockResolvedValue({
      connection_id: "c1", metrics: [REJECTED],
      counts: { total: 1, defined: 0, industry: 0, explorer: 1, formula_rejected: 1 },
    });
  });

  it("says the formula was rejected, not that one is needed", async () => {
    render(<MetricsPanel connId="c1" />);
    expect(await screen.findByText("Formula rejected")).toBeInTheDocument();
    expect(screen.queryByText("Needs a formula")).not.toBeInTheDocument();
  });

  it("carries the audit's own reason, so the reader learns it is the connection", async () => {
    render(<MetricsPanel connId="c1" />);
    const chip = await screen.findByText("Formula rejected");
    expect(chip).toHaveAttribute("title", expect.stringContaining("must be qualified"));
  });
});

describe("only the newest read is shown", () => {
  // 2026-10-07: the tab mounts before the scope bar knows its schema, so a read naming no schema
  // and the schema's own read race. The page said "Showing the metrics for amazon" over the two
  // defined rows of the read that named none — whichever answered last won.
  it("a read naming no schema that answers last does not replace the schema's own list", async () => {
    let answerUnscoped: (v: unknown) => void = () => {};
    getMetricCatalogue.mockImplementation((_conn: string, schema?: string) => schema
      ? Promise.resolve({ connection_id: "c1", metrics: [row({ name: "rides", label: "Ride Completion Rate" })],
                          counts: { total: 1, explorer: 1 } })
      : new Promise((resolve) => { answerUnscoped = resolve; }));
    const { rerender } = render(<MetricsPanel connId="c1" />);
    await waitFor(() => expect(getMetricCatalogue).toHaveBeenCalledWith("c1", undefined));
    rerender(<MetricsPanel connId="c1" schema="uber_ncr" />);
    await screen.findByText("Ride Completion Rate");

    await act(async () => {
      answerUnscoped({ connection_id: "c1", counts: { total: 1, defined: 1 },
                       metrics: [row({ name: "daily", label: "Daily Gross Revenue", source: "defined", state: "defined" })] });
    });
    expect(screen.getByText("Ride Completion Rate")).toBeInTheDocument();
    expect(screen.queryByText("Daily Gross Revenue")).not.toBeInTheDocument();
  });
});
