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
import { render, screen, waitFor } from "@/lib/testing";
import userEvent from "@testing-library/user-event";

import type { ImpactDetail, ProcessDetail } from "@/lib/objectTypes";

const deleteProcess = vi.fn(async (..._args: unknown[]) => undefined);
const previewImpact = vi.fn();
const declareImpact = vi.fn();
const listed: { processes: ProcessDetail[]; impacts: ImpactDetail[] } = { processes: [], impacts: [] };

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getProcesses: async () => ({ connection_id: "c1", schema_name: "s", processes: listed.processes, rules: [],
                               impacts: listed.impacts }),
  deleteProcess: (...a: unknown[]) => deleteProcess(...a),
  previewImpact: (...a: unknown[]) => previewImpact(...a),
  declareImpact: (...a: unknown[]) => declareImpact(...a),
}));

const keepCockpit = vi.fn(async (..._args: unknown[]) => ({ status: "kept", kept: true, version: 1 }));
const requestTab = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()), keepCockpit: (...a: unknown[]) => keepCockpit(...a),
}));
vi.mock("@/lib/navigate", () => ({ requestTab: (...a: unknown[]) => requestTab(...a) }));

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

  it("words a promise kept within hours as hours, not calendar days", async () => {
    const packed = structuredClone(olist);
    Object.assign(packed.stages[3].promise!, { kind: "within_hours", within_hours: 24, deadline: "" });
    listed.processes = [packed];
    panel();
    expect(await screen.findByText("The delivery promise — within 24 hours of the stage before")).toBeTruthy();
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


describe("ProcessPanel — a cockpit for a process published earlier", () => {
  // The walk-through (2026-10-09): Start a cockpit was offered only in the designer's session, right after publishing.
  beforeEach(() => { keepCockpit.mockClear(); requestTab.mockClear(); });

  it("starts one from the panel — the board, the objects past its first promise, one beside them — and opens on it", async () => {
    const dispatching = structuredClone(olist);
    dispatching.stages[2].promise!.overdue_segment = "overdue_dispatch";
    listed.processes = [dispatching];
    panel();
    await userEvent.click(await screen.findByTestId("process-start-cockpit"));
    await waitFor(() => expect(keepCockpit).toHaveBeenCalled());
    const [conn, id, spec, note] = keepCockpit.mock.calls[0] as [string, string, { elements: Record<string, { type: string; props: Record<string, unknown> }> }, string];
    expect([conn, note]).toEqual(["c1", "Started from the process Order to delivery"]);
    expect(id).toMatch(/^order-to-delivery-[0-9a-f]{6}$/);
    expect(Object.values(spec.elements).map(e => e.type)).toEqual(["Cockpit", "Section", "ProcessBoard", "ObjectTable", "ObjectDetail"]);
    expect(Object.values(spec.elements)[3].props).toMatchObject({ entity: "Order", segment: "overdue_dispatch" });
    expect(requestTab).toHaveBeenCalledWith("cockpit", { conn: "c1" });
  });

  it("is the board alone for a process whose promises name no overdue list, and says why — not that it promises nothing", async () => {
    listed.processes = [olist];
    panel();
    expect(await screen.findByText("Its board — its promises' overdue lists are not offered on this install.")).toBeTruthy();
    await userEvent.click(screen.getByTestId("process-start-cockpit"));
    await waitFor(() => expect(keepCockpit).toHaveBeenCalled());
    const spec = keepCockpit.mock.calls[0][2] as { elements: Record<string, { type: string }> };
    expect(Object.values(spec.elements).map(e => e.type)).toEqual(["Cockpit", "Section", "ProcessBoard"]);
  });

  it("says a process that promises nothing gets its board alone", async () => {
    const plain = structuredClone(olist);
    plain.stages.forEach(st => { st.promise = null; });
    listed.processes = [plain];
    panel();
    expect(await screen.findByText("Its board — it promises nothing, so there is nothing to list as overdue.")).toBeTruthy();
  });
});


// ── Arc OC-5 — what touches a stage, how objects move, and what bears on a promise ───────────────────────────────────

const IMPACT: ImpactDetail = {
  id: "late_lines_late_delivery", display_name: "Late lines, late delivery", description: "", owner: "",
  upstream: "order_to_delivery.dispatch", downstream: "order_to_delivery.delivery",
  upstream_label: "the dispatch promise of Order to delivery", downstream_label: "the delivery promise of Order to delivery",
  mechanism: "influence", formula: "", evidence: "", window_days: null, lead: "Order", path: "items", to_many: true,
  objects: 96476, upstream_broke: 6212, upstream_kept: 90264, rate_when_broke: 0.31, rate_when_kept: 0.066,
  lag_days: null, window: "all of the data, to 2018-10-17", as_of: "2018-10-17 13:22:46", verified: true, flags: [],
  note: "", reading: "where the dispatch promise of Order to delivery was broken, the delivery promise of Order to delivery was broken 31% of the time, against 7% where it was kept (6,212 and 90,264 Order)",
};

describe("Arc OC-5 on a process", () => {
  beforeEach(() => {
    previewImpact.mockReset();
    declareImpact.mockReset();
    const moved: ProcessDetail = {
      ...olist,
      stages: olist.stages.map((s) => s.name === "dispatched" ? {
        ...s, precedes: { approved: 1359, placed: 12 },
        roles: [{ entity: "Order", role: "goes through the process" },
                { entity: "OrderItem", role: "the lead object its promise is kept per", why: "every hop to-one" }] } : s),
      observed: [{ from_stage: "placed", to_stage: "approved", declared: true, objects: 99281 },
                 { from_stage: "approved", to_stage: "delivered", declared: false, objects: 14 }],
      conformance: { seen_only_in_data: ["approved → delivered"], never_observed: [], untimed: [] },
    };
    listed.processes = [moved];
    listed.impacts = [IMPACT];
  });

  it("names what a stage touches, every earlier stage it beats, and the moves nobody declared", async () => {
    panel();
    const roles = await screen.findByTestId("process-stage-roles");
    expect(roles.textContent).toContain("OrderItem(the lead object its promise is kept per)");
    expect(screen.getAllByTestId("process-stage-precedes").map((e) => e.textContent)).toEqual(["12 reached dispatched before placed"]);
    const moves = screen.getAllByTestId("process-move").map((e) => e.textContent);
    expect(moves[1]).toContain("approved → delivered14nobody declared it");
  });

  it("reads an impact on both of its promises, in its counts, and declares a new one only after counting it", async () => {
    const user = userEvent.setup();
    panel();
    const readings = await screen.findAllByTestId("impact-reading");
    expect(readings.map((r) => r.textContent)).toEqual([IMPACT.reading, IMPACT.reading]);     // downstream of dispatch, upstream of delivery
    previewImpact.mockResolvedValue({ ...IMPACT, reading: "counted reading" });
    declareImpact.mockResolvedValue(IMPACT);
    await user.click(screen.getAllByTestId("impact-new")[1]);                                  // on the delivery promise
    const declare = screen.getByTestId("impact-declare");
    expect(declare).toBeDisabled();                                                            // counted first
    await user.click(screen.getByTestId("impact-count"));
    expect(await screen.findByTestId("impact-counted")).toHaveTextContent("counted reading");
    expect(previewImpact.mock.calls[0][1]).toEqual({ id: "dispatch_bears_on_delivery", upstream: "order_to_delivery.dispatch",
                                                     downstream: "order_to_delivery.delivery", mechanism: "influence" });
    await user.click(declare);
    await waitFor(() => expect(declareImpact).toHaveBeenCalledTimes(1));
  });

  it("says once what was measured when an impact did not hold", async () => {
    const note = "of the 43,941 Order objects, 7,311 saw dispatch broken — the data does not show delivery broken more often";
    listed.impacts = [{ ...IMPACT, verified: false, note,
                        reading: `the dispatch promise of Order to delivery is declared to bear on the delivery promise — ${note}` }];
    panel();
    const lines = await screen.findAllByTestId("impact-line");
    for (const line of lines) expect(line.textContent!.split(note).length - 1).toBe(1);
  });

  it("opens the designer on the process to change it", async () => {
    const user = userEvent.setup();
    const onChangeProcess = vi.fn();
    panel({ onChangeProcess });
    await user.click(await screen.findByTestId("process-change"));
    expect(onChangeProcess.mock.calls[0][0].id).toBe("order_to_delivery");
  });
});
