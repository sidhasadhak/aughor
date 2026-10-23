// @vitest-environment jsdom
/**
 * Adopting the proposals in one door (2026-10-23; the Olist study, Gaps 21, 22 and 24): every proposal with a
 * formula is ticked and dated by the platform's first date, a person can untick one or change a date, and one
 * button approves the set — what was not adopted is listed with its reason.
 */
import { change, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getMetricProposals: vi.fn(), adoptMetrics: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { AdoptProposals, adoptable } from "./AdoptProposals";
import type { CatalogueMetric } from "@/lib/api";

const row = (name: string, label: string, extra: Partial<CatalogueMetric> = {}) => ({
  name, label, source: "explorer", state: "proposed", sql: "SUM(price)", tables: ["olist.olist_orders_dataset"], schema: "olist",
  unit: "", definition: "", grain: "", dimensions: [], anti_patterns: [], pack_id: "", required_roles: [], missing_roles: [],
  sane_range: null, why_it_matters: "", reason: "", status: "", version: 0, owner: "", editable: false, ...extra,
}) as CatalogueMetric;

const ROWS = [row("gmv", "GMV"), row("aov", "AOV"), row("nps", "NPS", { sql: "" }), row("rev", "Revenue", { source: "defined", state: "defined" })];
const PURCHASE = "olist.olist_orders_dataset.order_purchase_timestamp";
const APPROVED = "olist.olist_orders_dataset.order_approved_at";

beforeEach(() => {
  api.getMetricProposals.mockReset();
  api.adoptMetrics.mockReset();
  api.getMetricProposals.mockResolvedValue({ statements: [], statement_note: "", note: "",
    candidates: [{ grain: PURCHASE }, { grain: APPROVED }] });
});

describe("AdoptProposals", () => {
  it("offers only proposals with a formula", () => {
    expect(adoptable(ROWS).map(r => r.name)).toEqual(["gmv", "aov"]);
  });

  it("adopts the ticked set with the dates chosen, and says what was not adopted", async () => {
    api.adoptMetrics.mockResolvedValue({ scope: "olist: GMV", adopted: [{ name: "gmv", label: "GMV" }],
      skipped: [{ name: "x", label: "Late rate", reason: "it has no date — choose the column it is dated by" }] });
    const onDone = vi.fn();
    render(<AdoptProposals connId="workspace" schema="olist" rows={ROWS} onDone={onDone} />);
    expect(screen.getByTestId("adopt-proposals")).toHaveTextContent("2 proposals with a formula are ready to adopt");
    fireEvent.click(screen.getByText("Choose and date them"));
    await waitFor(() => expect(screen.getAllByLabelText(/^Date for /)).toHaveLength(2));
    expect(screen.getByLabelText("Date for GMV").getAttribute("data-value")).toBe(PURCHASE);    // the business date first
    change(screen.getByLabelText("Date for AOV"), { target: { value: APPROVED } });
    fireEvent.click(screen.getByLabelText("Adopt GMV"));                                          // untick GMV
    fireEvent.click(screen.getByText("Approve 1 metric"));
    await waitFor(() => expect(api.adoptMetrics).toHaveBeenCalledWith("workspace", "olist", [{ name: "aov", time_column: APPROVED }]));
    const result = await screen.findByTestId("adopt-result");
    expect(within(result).getByText("Approved: GMV.")).toBeInTheDocument();
    expect(result).toHaveTextContent("Late rate was not adopted: it has no date — choose the column it is dated by");
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("is absent when nothing is adoptable", () => {
    const { container } = render(<AdoptProposals connId="workspace" rows={[ROWS[2], ROWS[3]]} onDone={() => {}} />);
    expect(container.querySelector('[data-testid="adopt-proposals"]')).toBeNull();
  });
});
