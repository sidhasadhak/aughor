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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogueMetric, Metric } from "@/lib/api";

const getMetrics = vi.fn();
const getMetricCatalogue = vi.fn();
const getDefinitionReport = vi.fn();
const getMetricAudit = vi.fn();
const requestTab = vi.fn();
const getMetricProposals = vi.fn();
const bindPack = vi.fn();
const getMyAccess = vi.fn(async () => ({ actor: "ana@example.com", signed_in: false }));
const RETAIL = {
  manifest: { name: "Retail and e-commerce" },
  entities: {
    cart: { description: "One shopping cart a visitor created.", expects: {}, attributes: {
      converted_order_id: { type: "id", description: "The order this cart became; empty when abandoned." } } },
    order_item: { description: "One line of one order.", expects: {}, attributes: {
      returned_at: { type: "timestamp", description: "When the line was returned; empty when it was not." } } },
  },
  metrics: [],
};
const LUX_TABLES = [
  { name: "lux.web_sessions", row_count: null, columns: [
    { name: "session_id", type: "TEXT", is_fk: false }, { name: "order_id", type: "TEXT", is_fk: false },
    { name: "converted", type: "BOOLEAN", is_fk: false }] },
  { name: "lux.order_items", row_count: null, columns: [
    { name: "order_item_id", type: "TEXT", is_fk: false }, { name: "returned", type: "BOOLEAN", is_fk: false }] },
];

vi.mock("@/lib/api", () => ({
  getMetrics: (...a: unknown[]) => getMetrics(...a),
  getMetricCatalogue: (...a: unknown[]) => getMetricCatalogue(...a),
  getDefinitionReport: (...a: unknown[]) => getDefinitionReport(...a),
  getMetricAudit: (...a: unknown[]) => getMetricAudit(...a),
  getMyAccess: () => getMyAccess(),
  getMetricProposals: (...a: unknown[]) => getMetricProposals(...a),
  getPackDetail: vi.fn(async () => RETAIL),
  getPackBinding: vi.fn(async () => null),
  getSchemaRich: vi.fn(async () => ({ tables: LUX_TABLES, joins: [], isolated: [], warnings: [] })),
  proposePackBindings: vi.fn(async () => ({ fully_groundable: false, groundable_roles: 1, total: 2,
    proposals: {
      order_item: { role: "order_item", table: "lux.order_items", confidence: 0.8, evidence: "name", bound: true },
      cart: { role: "cart", table: null, confidence: 0, bound: false,
              evidence: "no table is named for cart — choose its table, or this warehouse may not hold it" },
    } })),
  bindPack: (...a: unknown[]) => bindPack(...a),
  getOntologyKeys: vi.fn(async () => ({ entities: [], metrics: [] })),
  materialiseMetric: vi.fn(), removeProposal: vi.fn(), restoreProposal: vi.fn(), promoteMetric: vi.fn(),
  createMetric: vi.fn(), updateMetric: vi.fn(), deleteMetric: vi.fn(), validateMetric: vi.fn(),
  getMetricFreshness: vi.fn(), transitionMetric: vi.fn(), generateMetricSql: vi.fn(), confirmMetricEntity: vi.fn(),
}));
vi.mock("@/lib/navigate", () => ({ requestTab: (...a: unknown[]) => requestTab(...a) }));

import { MetricsPanel } from "@/components/MetricsPanel";
import { choose, optionsOf } from "@/lib/testing";
import { forgetMe } from "@/lib/useMe";

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
        editable: false, pack_id: "retail", missing_roles: ["cart"],
        sql: "SUM(CASE WHEN {{role.cart.converted_order_id}} IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)" }),
  row({ name: "return_rate", label: "Return rate", source: "industry", state: "needs_binding", status: "",
        editable: false, pack_id: "retail", missing_roles: ["order_item"],
        sql: "SUM(CASE WHEN {{role.order_item.returned_at}} IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)" }),
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
  getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", candidates: [], note: "" });
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

  it("binds an unbound industry metric's roles here, in a dialog — never a trip to Settings", async () => {
    // 2026-10-13: "Bind roles" went to Settings ▸ System, where an industry package showed no way to bind at all.
    const user = userEvent.setup();
    bindPack.mockResolvedValue({ verified: true });
    view(<MetricsPanel connId="c1" schema="lux" />);
    await user.click(await within(await screen.findByTestId("needs-not_bound")).findByRole("button", { name: "Bind roles" }));
    const dialog = await screen.findByTestId("bind-roles");
    expect(requestTab).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("Bind the Retail and e-commerce package here · lux");
    expect(dialog).toHaveTextContent("Its metrics are recipes written over roles, not over your tables.");
    // Return rate needs a timestamp; order_items has only a true/false `returned` — not offered, and said.
    const item = await within(dialog).findByTestId("bind-role-order_item");
    expect(within(item).getByTestId("bind-none-order_item-returned_at")).toHaveTextContent(
      "No timestamp column on order_items — a true/false column would count every row");
    expect(within(dialog).getByTestId("bind-stuck")).toHaveTextContent("Return rate can't be bound to this data as it stands");
    expect(within(dialog).getByRole("button", { name: "Write the SQL of Return rate" })).toBeInTheDocument();
    // Nothing was proposed for the cart, and the row says why rather than leaving an empty select to puzzle over.
    expect(within(dialog).getByTestId("bind-unproposed-cart")).toHaveTextContent(
      "nothing proposed — no table is named for cart — choose its table, or this warehouse may not hold it");
    // The cart: choose its table and the column for the one attribute the recipe reads, then bind.
    await choose(within(dialog).getByRole("combobox", { name: "Table for cart" }), "lux.web_sessions");
    await choose(await within(dialog).findByRole("combobox", { name: "Column for cart.converted_order_id" }), "order_id");
    await user.click(within(dialog).getByRole("button", { name: "Bind 1 of 2 roles" }));
    await waitFor(() => expect(bindPack).toHaveBeenCalled());
    const [pack, conn, bindings, schema] = bindPack.mock.calls[0];
    expect([pack, conn, schema]).toEqual(["retail", "c1", "lux"]);
    expect(bindings).toEqual({ cart: expect.objectContaining({ table: "lux.web_sessions", columns: { converted_order_id: "order_id" } }) });
    expect(await within(dialog).findByTestId("bind-result")).toHaveTextContent("Bound and checked");
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

describe("who proposed it", () => {
  afterEach(() => forgetMe());

  it("is 'you' when the reader proposed it — on the Needs-you row and on its approval", async () => {
    forgetMe();
    getMyAccess.mockResolvedValueOnce({ actor: "ana", signed_in: false });
    const user = userEvent.setup();
    view(<MetricsPanel connId="c1" />);
    const review = await screen.findByTestId("needs-review");
    await waitFor(() => expect(review).toHaveTextContent("proposed by you"));
    await user.click(within(review).getByRole("button", { name: "Review" }));
    const governance = await screen.findByTestId("metric-governance");
    expect(governance).toHaveTextContent("proposed by you");
    expect(governance).not.toHaveTextContent("by ana");
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


describe("the date a metric is measured by", () => {
  // LuxExperience, 2026-10-13: "Date, timestamp or other date format columns do not appear as [a] drop down".
  const openDates = async () => {
    const user = userEvent.setup();
    view(<MetricsPanel connId="c1" />);
    await user.click(await within(await screen.findByTestId("needs-no_date")).findByRole("button", { name: "Gross Margin %" }));
    return screen.findByTestId("metric-dates");
  };
  const cand = (grain: string, type: string, extra: object = {}) =>
    ({ grain, table: grain.split(".").slice(0, -1).join("."), column: grain.split(".").pop(), type, primary: false, ...extra });

  it("is chosen from a list of the proposals — a day kept as text among them, said to be text", async () => {
    getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", note: "",
      candidates: [cand("orders.order_date", "date", { primary: true }), cand("orders.shipped_at", "timestamp"),
                   cand("orders.order_day", "text", { text: true })] });
    const dates = await openDates();
    const pick = await within(dates).findByRole("combobox", { name: "Date column" });
    expect(optionsOf(pick).map(o => o.text)).toEqual([
      "Choose the date…", "orders.order_date · main date · date", "orders.shipped_at · timestamp",
      "orders.order_day · text, read as a date", "Another column — type it…"]);
    await choose(pick, "orders.order_day");
    expect(await within(dates).findByTestId("metric-date-text")).toHaveTextContent("order_day is kept as text");
    expect(within(dates).queryByRole("textbox", { name: /Date column/ })).toBeNull();
  });

  it("can still be typed when none of the proposals is the one", async () => {
    getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", note: "",
      candidates: [cand("orders.order_date", "date"), cand("orders.shipped_at", "timestamp")] });
    const dates = await openDates();
    await choose(await within(dates).findByRole("combobox", { name: "Date column" }), "\u0000another");
    expect(await within(dates).findByRole("textbox", { name: "Date column, typed" })).toBeInTheDocument();
  });

  it("says where the date is when the definition's own table has none, and opens its SQL", async () => {
    getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", candidates: [],
      reachable: [{ grain: "orders.order_date", table: "orders", column: "order_date", via: "order_id", from: "order_items", type: "date" }],
      note: "order_items has no date of its own — orders.order_date is one join away (on order_id); to be measured by it, the definition must read orders" });
    const dates = await openDates();
    await waitFor(() => expect(within(dates).getByTestId("metric-date-proposals")).toHaveTextContent("order_items has no date of its own"));
    const away = within(dates).getByTestId("metric-date-reachable");
    expect(away).toHaveTextContent("orders.order_date (on order_id)");
    await userEvent.setup().click(within(away).getByRole("button", { name: "Edit the SQL" }));
    expect(screen.getByRole("tab", { name: /Edit/ })).toHaveAttribute("aria-selected", "true");
  });
});
