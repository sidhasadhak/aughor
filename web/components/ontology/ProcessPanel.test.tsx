// @vitest-environment jsdom

/**
 * ON-9 — a declared process, as its measurement counted it.
 *
 * The panel is a reading of `GET /ontology/processes`, so what these pin is that the reading does not drift from the
 * numbers: a breach count and its denominator shown exactly (a person checks them against a query, so "10.4K" would be
 * a lie of rounding), the percentiles of the move from the stage before, a stage reached BEFORE the one before it
 * named in red, a flag shown where the data never or always breaks a promise — and that withdrawing takes two clicks
 * and says which process it withdrew.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ProcessDetail } from "@/lib/objectTypes";

const deleteProcess = vi.fn(async (..._args: unknown[]) => undefined);
const listed: { processes: ProcessDetail[] } = { processes: [] };

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getProcesses: async () => ({ connection_id: "c1", schema_name: "s", processes: listed.processes, rules: [] }),
  deleteProcess: (...a: unknown[]) => deleteProcess(...a),
}));

import { ProcessPanel } from "@/components/ontology/ProcessPanel";

const noDerived = { segments: [], properties: [], metrics: [] };

const olist: ProcessDetail = {
  id: "order_to_delivery", display_name: "Order to delivery", description: "", entity: "order", entity_id: "Order",
  owner: "operations", origin: "human", provenance: "", objects: 99441, verified: true,
  note: "99,441 Order objects; 4 of 4 stages reached; 2 promises measured", measured_at: "2026-09-13T10:00:00+00:00",
  stages: [
    { name: "placed", display_name: "placed", anchor: { timestamp: "order_purchase_timestamp" }, reached: 99441, share: 1,
      verified: true, note: "", transition: null, promise: null },
    { name: "approved", display_name: "approved", anchor: { timestamp: "order_approved_at" }, reached: 99281,
      share: 0.998391, verified: true, note: "", promise: null,
      transition: { from: "placed", both: 99281, skipped: 0, out_of_order: 0, p50_days: 0, p90_days: 1, p95_days: 2,
                    lag: "approved_lag_days" } },
    { name: "dispatched", display_name: "dispatched", anchor: { timestamp: "order_delivered_carrier_date" }, reached: 97658,
      share: 0.982069, verified: true, note: "",
      transition: { from: "approved", both: 97644, skipped: 14, out_of_order: 1359, p50_days: 2, p90_days: 6, p95_days: 8,
                    lag: "dispatch_lag_days" },
      promise: { name: "dispatch", kind: "deadline", deadline: "shipping_limit_date", within_days: null,
                 grain: "order_item", grain_id: "OrderItem", via: "order_item_to_order", target: null, objects: 112650,
                 reached: 111456, breached: 10423, kept: 101033, open: 1194, open_overdue: 1100, breach_rate: 0.093517,
                 as_of: "2018-09-11 19:48:28", verified: true, flags: [], note: "", segment: "late_dispatch",
                 metric: "dispatch_breach_rate" } },
    { name: "delivered", display_name: "delivered", anchor: { timestamp: "order_delivered_customer_date" }, reached: 96476,
      share: 0.970183, verified: true, note: "",
      transition: { from: "dispatched", both: 96475, skipped: 1, out_of_order: 23, p50_days: 7, p90_days: 20,
                    p95_days: 27, lag: "delivery_lag_days" },
      promise: { name: "delivery", kind: "deadline", deadline: "order_estimated_delivery_date", within_days: null,
                 grain: "order", grain_id: "Order", via: "", target: null, objects: 99441, reached: 96476, breached: 7827,
                 kept: 88649, open: 2965, open_overdue: 2960, breach_rate: 0.08113, as_of: "2018-10-17 13:22:46",
                 verified: true, flags: [], note: "", segment: "late_delivery", metric: "delivery_breach_rate" } },
  ],
  derived: {
    segments: [{ name: "late_dispatch", kind: "segment", source: "the dispatch promise of process order_to_delivery",
                 description: "the OrderItem objects that broke the dispatch promise", usable: true }],
    metrics: [{ name: "dispatch_breach_rate", kind: "metric", source: "the dispatch promise of process order_to_delivery",
                description: "the share of the OrderItem objects that broke it", usable: true }],
    properties: [],
  },
};

function panel(extra: Partial<Parameters<typeof ProcessPanel>[0]> = {}) {
  return render(
    <ProcessPanel connectionId="c1" schema="s" processId="order_to_delivery" version={0} onOpenType={() => {}}
      onClose={() => {}} onChanged={() => {}} {...extra} />);
}

describe("ProcessPanel — a process as the data counted it", () => {
  beforeEach(() => {
    listed.processes = [olist];
    deleteProcess.mockClear();
  });

  it("reads each stage, the move from the stage before, and each promise with its exact counts", async () => {
    panel();
    expect(await screen.findByText("Order to delivery")).toBeTruthy();
    expect(screen.getAllByTestId("process-stage")).toHaveLength(4);
    expect(screen.getByText("10,423 of 111,456 that reached dispatched broke it")).toBeTruthy();
    expect(screen.getAllByTestId("process-promise-rate").map((n) => n.textContent)).toEqual(["9.35% broken", "8.11% broken"]);
    expect(screen.getByText(/from approved: p50 2 · p90 6 · p95 8 days/)).toBeTruthy();
    expect(screen.getByText(/1,359 before approved/)).toBeTruthy();
    expect(screen.getByText(/1,194 not dispatched yet · 1,100 already past it as of 2018-09-11 19:48:28/)).toBeTruthy();
    expect(screen.getByText("late_dispatch · dispatch_breach_rate")).toBeTruthy();
    expect(screen.queryAllByTestId("process-promise-flag")).toHaveLength(0);
  });

  it("names a promise the data never breaks in red, rather than reading it as kept", async () => {
    const flagged = structuredClone(olist);
    flagged.stages[3].promise!.flags = ["never broken: none of the 96,476 Order objects that reached delivered went past it"];
    listed.processes = [flagged];
    panel();
    expect((await screen.findByTestId("process-promise-flag")).textContent).toMatch(/^never broken/);
  });

  it("opens the type a promise is kept per", async () => {
    const onOpenType = vi.fn();
    panel({ onOpenType });
    await userEvent.click(await screen.findByRole("button", { name: "order_item" }));
    expect(onOpenType).toHaveBeenCalledWith("order_item");
  });

  it("withdraws only on the second click, then closes", async () => {
    const onClose = vi.fn();
    const onChanged = vi.fn();
    panel({ onClose, onChanged });
    const withdraw = await screen.findByTestId("process-withdraw");
    await userEvent.click(withdraw);
    expect(deleteProcess).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId("process-withdraw"));
    await waitFor(() => expect(deleteProcess).toHaveBeenCalledWith("c1", "order_to_delivery", "s"));
    expect(onChanged).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("says so when the process is gone", async () => {
    listed.processes = [];
    panel();
    expect(await screen.findByText("No process “order_to_delivery”")).toBeTruthy();
    expect(noDerived.segments).toHaveLength(0);
  });
});
