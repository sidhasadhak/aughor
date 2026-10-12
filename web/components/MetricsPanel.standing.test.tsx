// @vitest-environment jsdom
/**
 * The Metrics tab opens on where its metrics stand (CLARITY, 2026-10-12): four figures, then "Needs you" with a button
 * for each metric it is about, each button opening that metric's row on the view that fixes it.
 *
 * The user asked why LuxExperience's metrics "had not popped up": four of its eight approved metrics had no date
 * column, so none of them could be measured for a period, and nothing on the screen said so. These pin that it is said,
 * at the top, with the way to fix it on the row — and that a read which failed is said as a failure, never as nothing.
 */
import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogueMetric, Metric } from "@/lib/api";

const getMetrics = vi.fn();
const getMetricCatalogue = vi.fn();
const getDefinitionReport = vi.fn();
const getMetricAudit = vi.fn();
const requestTab = vi.fn();

vi.mock("@/lib/api", () => ({
  getMetrics: (...a: unknown[]) => getMetrics(...a),
  getMetricCatalogue: (...a: unknown[]) => getMetricCatalogue(...a),
  getDefinitionReport: (...a: unknown[]) => getDefinitionReport(...a),
  getMetricAudit: (...a: unknown[]) => getMetricAudit(...a),
  getMyAccess: vi.fn(async () => ({ actor: "ana@example.com", signed_in: false })),
  getMetricProposals: vi.fn(async () => ({ statements: [], statement_note: "", candidates: [], note: "" })),
  getOntologyKeys: vi.fn(async () => ({ entities: [], metrics: [] })),
  materialiseMetric: vi.fn(), removeProposal: vi.fn(), restoreProposal: vi.fn(), promoteMetric: vi.fn(),
  createMetric: vi.fn(), updateMetric: vi.fn(), deleteMetric: vi.fn(), validateMetric: vi.fn(),
  getMetricFreshness: vi.fn(), transitionMetric: vi.fn(), generateMetricSql: vi.fn(), confirmMetricEntity: vi.fn(),
}));
vi.mock("@/lib/navigate", () => ({ requestTab: (...a: unknown[]) => requestTab(...a) }));

import { MetricsPanel } from "@/components/MetricsPanel";

/** The app draws every screen inside a Radix Theme; the detail's tabs and Tools menu need one. */
const view = (ui: ReactElement) => render(<Theme>{ui}</Theme>);

function row(over: Partial<CatalogueMetric> = {}): CatalogueMetric {
  return {
    name: "m", label: "M", source: "defined", state: "defined", sql: "SELECT 1", unit: "", definition: "", grain: "",
    dimensions: [], tables: [], anti_patterns: [], pack_id: "", required_roles: [], missing_roles: [], sane_range: null,
    why_it_matters: "", reason: "", status: "approved", version: 1, owner: "", editable: true, schema: "lux", ...over,
  };
}
function metric(over: Partial<Metric> = {}): Metric {
  return {
    name: "m", label: "M", sql: "SELECT 1", tables: [], dimensions: [], filters: [], unit: null, caveats: null,
    target_value: null, warning_threshold: null, critical_threshold: null, target_period: null, benchmark_source: null,
    owner: null, freshness_sla: null, freshness_check_sql: null, quality_tests: [], lineage: [], wrong_usage_examples: [],
    approved_by: "ana", approved_at: "2026-10-12T15:22:23+00:00", status: "approved", version: 1,
    connection: "c1", schema_name: null, home_schema: "lux", ...over,
  };
}

const dated = { time_kind: "flow" as const, time_column: "orders.order_date" };
const STORED = [
  metric({ name: "aov", label: "Average Order Value", ...dated }),
  metric({ name: "gross_margin", label: "Gross Margin %" }),
  metric({ name: "roas", label: "Marketing ROAS" }),
  metric({ name: "delivery", label: "Average Delivery Time", status: "proposed", approved_at: null, approved_by: null,
           proposed_by: "ana", proposed_at: "2026-10-08T07:33:36+00:00", ...dated }),
];
const ROWS = [
  ...STORED.map(m => row({ name: m.name, label: m.label, status: m.status ?? "" })),
  row({ name: "cart_conv", label: "Cart-to-order conversion rate", source: "industry", state: "needs_binding", status: "",
        editable: false, pack_id: "retail", missing_roles: ["cart"] }),
];

const REPORT = {
  metric: "delivery", connection_id: "c1", status: "proposed", version: 1, advisory: true, taken_at: "",
  predecessor: { outcome: "clean", summary: "Nothing approved before it.", findings: [], detail: {} },
  execution: { outcome: "unavailable", summary: "The warehouse did not answer.", findings: [], detail: {} },
  declaration: { outcome: "clean", summary: "Declares what it reads.", findings: [], detail: {} },
  segments: { outcome: "not_applicable", summary: "No segments.", findings: [], detail: {} },
  population: { mode: "unpinnable", reason: "the table has no snapshot", token: "", tables: [], taken_at: "" },
  defects: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  getMetrics.mockResolvedValue(STORED);
  getMetricCatalogue.mockResolvedValue({ connection_id: "c1", metrics: ROWS, counts: { total: ROWS.length } });
  getDefinitionReport.mockResolvedValue(REPORT);
  getMetricAudit.mockResolvedValue([]);
});

describe("the figures", () => {
  it("say what is approved and measured, what waits, and what can't be measured", async () => {
    view(<MetricsPanel connId="c1" />);
    const measured = await screen.findByTestId("fig-measured");
    expect(within(measured).getByTestId("fig-measured-value")).toHaveTextContent("1");
    expect(measured).toHaveTextContent("of 3 approved");
    expect(screen.getByTestId("fig-review-value")).toHaveTextContent("1");
    expect(screen.getByTestId("fig-unmeasured-value")).toHaveTextContent("2");
    expect(screen.getByTestId("fig-unmeasured")).toHaveTextContent("no date column");
  });
});

describe("Needs you", () => {
  it("lists a proposal first, then the approved metrics with no date, then the unbound industry metric", async () => {
    view(<MetricsPanel connId="c1" />);
    const needs = await screen.findByTestId("metrics-needs");
    const kinds = within(needs).getAllByTestId(/^needs-/).map(el => el.getAttribute("data-testid"));
    expect(kinds).toEqual(["needs-review", "needs-no_date", "needs-not_bound"]);
    expect(within(needs).getByText("2 approved metrics can't be measured for a period")).toBeInTheDocument();
    // Said once, a button per metric — not one row each.
    expect(within(screen.getByTestId("needs-no_date")).getByRole("button", { name: "Gross Margin %" })).toBeInTheDocument();
    expect(within(screen.getByTestId("needs-no_date")).getByRole("button", { name: "Marketing ROAS" })).toBeInTheDocument();
  });

  it("opens a metric with no date straight on its date form", async () => {
    const user = userEvent.setup();
    view(<MetricsPanel connId="c1" />);
    await user.click(await within(await screen.findByTestId("needs-no_date")).findByRole("button", { name: "Gross Margin %" }));
    expect(await screen.findByRole("textbox", { name: "Date column" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Dates/ })).toHaveAttribute("aria-selected", "true");
  });

  it("opens a proposal on its approval, with the report above the decision", async () => {
    const user = userEvent.setup();
    view(<MetricsPanel connId="c1" />);
    await user.click(await within(await screen.findByTestId("needs-review")).findByRole("button", { name: "Review" }));
    const report = await screen.findByTestId("metric-report");
    const approve = screen.getByRole("button", { name: "Approve" });
    // A3: the report is read before the control that acts on it.
    expect(report.compareDocumentPosition(approve) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // "Could not check" is said, in the weight of a finding.
    expect(within(report).getByText("unavailable")).toBeInTheDocument();
    expect(within(report).getByText(/Population: unpinnable/)).toBeInTheDocument();
  });

  it("sends an unbound industry metric to where its roles are bound", async () => {
    const user = userEvent.setup();
    view(<MetricsPanel connId="c1" />);
    await user.click(await within(await screen.findByTestId("needs-not_bound")).findByRole("button", { name: "Bind roles" }));
    expect(requestTab).toHaveBeenCalledWith("settings", { settings: "system" });
  });

  it("is one muted line when nothing needs a person", async () => {
    getMetrics.mockResolvedValue([metric({ name: "aov", label: "Average Order Value", ...dated })]);
    getMetricCatalogue.mockResolvedValue({ connection_id: "c1", metrics: [row({ name: "aov", label: "Average Order Value" })], counts: { total: 1 } });
    view(<MetricsPanel connId="c1" />);
    const needs = await screen.findByTestId("metrics-needs");
    expect(needs).toHaveAttribute("data-waiting", "false");
    expect(needs).toHaveTextContent("Nothing needs you");
  });
});

describe("a read that failed says so", () => {
  it("the catalogue: a failure with a retry, never 'nothing applies'", async () => {
    getMetricCatalogue.mockRejectedValue(new Error("Failed to fetch the metric catalogue"));
    view(<MetricsPanel connId="c1" />);
    expect(await screen.findByText(/Failed to fetch the metric catalogue/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing applies/)).not.toBeInTheDocument();
  });

  it("the definitions: approved rows are 'not checked', and the figures say why", async () => {
    getMetrics.mockRejectedValue(new Error("down"));
    view(<MetricsPanel connId="c1" />);
    await waitFor(() => expect(screen.getAllByText("not checked").length).toBe(3));
    expect(screen.getByTestId("fig-measured")).toHaveTextContent("3 not checked");
    expect(screen.getByTestId("fig-unmeasured")).toHaveTextContent("the definitions could not be read");
    // Nothing is claimed to lack a date it was never read to have.
    expect(screen.queryByTestId("needs-no_date")).not.toBeInTheDocument();
  });

  it("the definitions, with nothing else waiting: Needs you says why it is quiet", async () => {
    getMetrics.mockRejectedValue(new Error("down"));
    getMetricCatalogue.mockResolvedValue({ connection_id: "c1", metrics: [row({ name: "aov", label: "Average Order Value" })], counts: { total: 1 } });
    view(<MetricsPanel connId="c1" />);
    expect(await screen.findByTestId("metrics-needs")).toHaveTextContent("the definitions could not be read");
  });
});
