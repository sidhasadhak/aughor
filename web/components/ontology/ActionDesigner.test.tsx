// @vitest-environment jsdom

/**
 * The action designer (2026-10-09, approved as drawn after the usability walk-through, job 2). A person decides an
 * action in words — what it is about, what a press does, what the person pressing it says, when it may be pressed, who
 * decides — and sees it read as declaring would read it: how many objects allow a press, and a press dry-run on a real
 * one. Declaring, publishing the release and putting the button on the cockpits a person ticks follow from the page.
 * These assert on the REQUESTS the page makes: a form that renders a field and drops it from the body looks the same.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { choose, render, screen, waitFor, within } from "@/lib/testing";
import type { ActionPreview, ProcessCandidates, TypeMapRow } from "@/lib/objectTypes";

const calls = vi.hoisted(() => ({
  candidates: vi.fn(), preview: vi.fn(), declare: vi.fn(), release: vi.fn(), publish: vi.fn(), types: vi.fn(),
  declared: vi.fn(), cockpits: vi.fn(), cockpit: vi.fn(), keep: vi.fn(), tab: vi.fn(), ok: vi.fn(), err: vi.fn(),
}));

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getProcessCandidates: calls.candidates, previewAction: calls.preview, declareAction: calls.declare,
  getRelease: calls.release, publishRelease: calls.publish, getTypeMap: calls.types,
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getDeclaredActions: calls.declared, listCockpits: calls.cockpits, getCockpit: calls.cockpit, keepCockpit: calls.keep,
}));
vi.mock("@/lib/navigate", () => ({ requestTab: calls.tab }));
vi.mock("@/components/ui/toast", () => ({ toast: { success: calls.ok, error: calls.err } }));

import { ActionDesigner, placesIn, withAction } from "@/components/ontology/ActionDesigner";

const TYPES = [{ id: "Order", display_name: "Order", rows: 124978 },
               { id: "User", display_name: "User", rows: 100000 }] as unknown as TypeMapRow[];
const CANDIDATES = {
  entity: "Order", label: "Order", api_name: "order", objects: 124978, table: "orders", key: "order_id", moments: [], unread: [],
  states: [{ property: "status", label: "Status", values: [{ value: "Shipped", objects: 37243 }, { value: "Processing", objects: 25061 },
    { value: "Cancelled", objects: 18733 }] }],
} as unknown as ProcessCandidates;
/** Late dispatch as it stands: the board, the overdue table and one order beside it. */
const LATE = { root: "cockpit", elements: {
  cockpit: { type: "Cockpit", props: { title: "Late dispatch" }, children: ["sec"] },
  sec: { type: "Section", props: { title: "Dispatch", columns: 3 }, children: ["board", "table-overdue_dispatch", "detail-table-overdue_dispatch"] },
  board: { type: "ProcessBoard", props: { process: "order_fulfilment" }, children: [] },
  "table-overdue_dispatch": { type: "ObjectTable", props: { entity: "Order", segment: "overdue_dispatch", columns: ["status", "created_at"] }, children: [] },
  "detail-table-overdue_dispatch": { type: "ObjectDetail", props: { follows: "table-overdue_dispatch" }, children: [] },
} };
const PREVIEW: ActionPreview = {
  entity: "Order", objects: 124978, allowed: 25061, uncounted: "", unread: [],
  segments: [{ segment: "overdue_dispatch", objects: 25051, allowed: 25051 }],
  sample: { key: "6", status: "allowed", message: "", properties: { status: "Processing", created_at: "2026-09-22" },
            edits: [{ property: "escalated_to_carrier", value: "yes", note: "Missed pickup" }], call: null },
};

function designer(entity = "Order") {
  return render(<ActionDesigner connectionId="c1" schema="s" types={TYPES} entity={entity} onClose={() => {}} />);
}

/** Name it, mark the order, allow it on Processing only. */
async function escalate(user: ReturnType<typeof userEvent.setup>) {
  expect(screen.getByTestId("action-designer-status").textContent).toBe("Name the action.");   // never a silent dead end
  await user.type(screen.getByLabelText("Action name"), "Escalate to carrier");
  expect(screen.getByTestId("action-designer-status").textContent).toBe("Name the mark a press leaves on an order.");
  await user.type(screen.getByLabelText("The mark's name"), "Escalated to carrier");
  await waitFor(() => expect(calls.candidates).toHaveBeenCalledWith("c1", "Order", "s"));
  await choose(screen.getByLabelText("Add a condition"), "status");
  await user.click(screen.getByRole("button", { name: "Processing · 25,061" }));
  await user.type(screen.getByLabelText("Try it with: Reason"), "Missed pickup");
}

const lastAsked = () => calls.preview.mock.calls.at(-1)?.[1];

describe("the action designer", () => {
  beforeEach(() => {
    Object.values(calls).forEach(f => f.mockReset());
    calls.candidates.mockResolvedValue(CANDIDATES);
    calls.preview.mockResolvedValue(PREVIEW);
    calls.declared.mockResolvedValue({ flag_for_review: { id: "flag_for_review", display_name: "Flag for review", params: [] } });
    calls.cockpits.mockResolvedValue({ cockpits: [{ cockpit_id: "late-dispatch", title: "Late dispatch", retired: false }] });
    calls.cockpit.mockResolvedValue({ cockpit: { spec: LATE } });
    try { localStorage.clear(); } catch { /* jsdom keeps one */ }
  });

  it("reads a draft written in words as declaring would — no refund rule, a mark on the order, its condition from the data", async () => {
    const user = userEvent.setup();
    designer();
    await escalate(user);
    await waitFor(() => expect(lastAsked()?.said).toEqual({ reason: "Missed pickup" }), { timeout: 3000 });
    const asked = lastAsked();
    expect(asked.id).toBe("escalate_to_carrier");
    expect(asked.segments).toEqual(["overdue_dispatch"]);                       // Late dispatch's table, found by itself
    expect(asked.action).toMatchObject({
      kind: "annotate", risk: "low", object_type: "Order",
      params: [{ name: "order", kind: "object", object_type: "Order" }, { name: "reason", kind: "value", data_type: "VARCHAR", required: true }],
      submission_criteria: [{ expr: 'order.status in ["Processing"]',
                              message: "Escalate to carrier is only for an order whose status is Processing." }],
      edits: [{ object: "order", property: "escalated_to_carrier", value: "yes", note: "{reason}" }],
    });
    expect(JSON.stringify(asked)).not.toMatch(/amount_eur|refund/i);
    await waitFor(() => expect(screen.getByTestId("action-allowed").textContent).toBe("25,061 orders allow it now · 99,917 don't"));
    const press = screen.getByTestId("action-press").textContent ?? "";
    expect(press).toContain("Allowed");
    expect(press).toContain("Escalated to carrier reads “yes”, with the note “Missed pickup”");
    expect(screen.getByTestId("action-places").textContent).toContain("Late dispatch — beside overdue dispatch: 25,051 of 25,051 allow it");
  });

  it("says when the button would sit beside objects that cannot be pressed", async () => {
    calls.preview.mockResolvedValue({ ...PREVIEW, segments: [{ segment: "overdue_dispatch", objects: 25051, allowed: 25000 }] });
    const user = userEvent.setup();
    designer();
    await escalate(user);
    await waitFor(() => expect(screen.getByTestId("action-checks").textContent)
      .toContain("51 of the 25,051 overdue dispatch the button sits beside can't be pressed"), { timeout: 3000 });
  });

  it("declares through the approval gate in words, publishes the release, and puts the button and its column on the cockpit ticked", async () => {
    calls.declare.mockRejectedValueOnce(new Error("428 approval_required: ontology.override")).mockResolvedValueOnce(undefined);
    calls.release.mockResolvedValue({ published: { number: 4 }, draft: [{}] });
    calls.publish.mockResolvedValue({ number: 5, id: "r5", restated_claims: [] });
    calls.keep.mockResolvedValue({});
    const user = userEvent.setup();
    designer();
    await escalate(user);
    await waitFor(() => expect(lastAsked()?.said).toEqual({ reason: "Missed pickup" }), { timeout: 3000 });
    await user.click(screen.getByTestId("action-review"));
    await user.click(screen.getByTestId("action-declare"));
    await waitFor(() => expect(calls.err).toHaveBeenCalled());
    expect(calls.err.mock.calls[0][0]).toBe("Waiting for approval");            // never "HTTP 428"
    expect(calls.err.mock.calls[0][1].description).not.toMatch(/428/);
    await user.click(screen.getByTestId("action-declare"));
    await waitFor(() => expect(calls.declare).toHaveBeenCalledTimes(2));
    expect(calls.declare.mock.calls[1].slice(0, 2)).toEqual(["c1", "escalate_to_carrier"]);
    await user.click(await screen.findByTestId("action-publish"));
    await waitFor(() => expect(screen.getByTestId("action-designer-state").textContent).toBe("Published in release 5"));
    await user.click(screen.getByTestId("action-place"));
    await waitFor(() => expect(calls.keep).toHaveBeenCalled());
    const [conn, cockpitId, spec, note] = calls.keep.mock.calls[0];
    expect([conn, cockpitId, note]).toEqual(["c1", "late-dispatch", "Added the action Escalate to carrier"]);
    const els = (spec as typeof LATE).elements as Record<string, { type: string; props: Record<string, unknown>; children: string[] }>;
    const button = els["detail-table-overdue_dispatch"].children.map(k => els[k]);
    expect(button).toEqual([{ type: "ActionButton", props: { action: "escalate_to_carrier" }, children: [] }]);
    expect(els["table-overdue_dispatch"].props.columns).toEqual(["status", "created_at", "escalated_to_carrier"]);
    expect(screen.getByTestId("action-placed").textContent).toContain("The button is on Late dispatch.");
  });

  it("asks for the call, its check and how it is taken back only when the action calls another system", async () => {
    const user = userEvent.setup();
    designer();
    await user.type(screen.getByLabelText("Action name"), "Open a carrier claim");
    expect(screen.queryByTestId("action-call")).toBeNull();
    await user.click(within(screen.getByTestId("action-does")).getByRole("button", { name: /Call another system/ }));
    const call = within(screen.getByTestId("action-call"));
    expect((call.getByLabelText("Address") as HTMLInputElement).value).toBe("");          // nothing pre-filled
    expect(screen.getByTestId("action-designer-status").textContent).toBe("Give the address the call is sent to — it begins https://.");
    await user.type(call.getByLabelText("Address"), "https://carrier.example/claims");
    await user.type(call.getByLabelText("The read that checks it"), "SELECT 1");
    await waitFor(() => expect(lastAsked()?.action.kind).toBe("side_effect"), { timeout: 3000 });
    expect(lastAsked().action).toMatchObject({
      risk: "high", reversibility: "irreversible", verification: { sql: "SELECT 1", expects: "rows" },
      side_effects: [{ kind: "http", config: { method: "POST", url: "https://carrier.example/claims" } }],
    });
    expect(lastAsked().action.edits).toBeUndefined();
    expect(lastAsked().action.undo).toBeUndefined();
  });
});

describe("where an action's button can sit", () => {
  it("is each object detail beside a table of the type — matched by id or name, in any case", () => {
    expect(placesIn("late-dispatch", "Late dispatch", LATE, ["order"])).toEqual([{
      cockpitId: "late-dispatch", title: "Late dispatch", detailKey: "detail-table-overdue_dispatch",
      tableKey: "table-overdue_dispatch", segment: "overdue_dispatch" }]);
    expect(placesIn("late-dispatch", "Late dispatch", LATE, ["User"])).toEqual([]);
  });

  it("gets the button once, and a mark's column once", () => {
    const [place] = placesIn("late-dispatch", "Late dispatch", LATE, ["Order"]);
    const twice = withAction(withAction(LATE, place, "escalate_to_carrier", "escalated_to_carrier"), place, "escalate_to_carrier", "escalated_to_carrier");
    const els = (twice as typeof LATE).elements as Record<string, { props: Record<string, unknown>; children: string[] }>;
    expect(els["detail-table-overdue_dispatch"].children).toHaveLength(1);
    expect(els["table-overdue_dispatch"].props.columns).toEqual(["status", "created_at", "escalated_to_carrier"]);
    expect((LATE.elements["table-overdue_dispatch"].props as { columns: string[] }).columns).toHaveLength(2);   // the spec read is never changed
  });
});
