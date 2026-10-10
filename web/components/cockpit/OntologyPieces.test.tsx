// @vitest-environment jsdom

/**
 * Arc OC-4's chain, as a test: a late dispatch cockpit — a process board, an objects table of the overdue objects, a
 * detail that follows it with a declared action's button — drawn through the cockpit's own renderer, every door the
 * pieces read mocked (no test here reaches an API). What it shows: the board's count and the table's total are the
 * two numbers the server gave, a row opens in the detail, running the action reads every piece again so the edit
 * shows in the table and the detail, and an action that needs approval is proposed instead, and said so.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import { ranSaid } from "@/components/cockpit/OntologyPieces";
import type { CockpitHostState } from "@/lib/cockpit/hostState";

const objects = vi.hoisted(() => ({
  listObjects: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(), runOrPropose: vi.fn(),
}));
const types = vi.hoisted(() => ({ getProcesses: vi.fn() }));

vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const SPEC = {
  root: "cockpit",
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Late dispatch" }, children: ["sec"] },
    sec: { type: "Section", props: { title: "Fulfilment" }, children: ["board", "table", "detail"] },
    board: { type: "ProcessBoard", props: { process: "order_fulfilment" }, children: [] },
    table: { type: "ObjectTable", props: { entity: "Order", segment: "overdue_dispatch", columns: ["status", "flagged_for_review"] }, children: [] },
    detail: { type: "ObjectDetail", props: { follows: "table" }, children: ["flag"] },
    flag: { type: "ActionButton", props: { action: "flag_for_review" }, children: [] },
  },
};
const HOST: CockpitHostState = { range: { status: "standing" }, cards: {} };

const PROCESS = {
  id: "order_fulfilment", display_name: "Order fulfilment", entity: "order", entity_id: "Order", measured_at: "2026-10-09T12:00:00Z",
  stages: [
    { name: "placed", display_name: "placed", reached: 124978, share: 1, transition: null, promise: null },
    { name: "shipped", display_name: "shipped", reached: 81184, share: 0.6496, transition: { p50_days: 2 },
      promise: { name: "dispatch", kind: "within_days", within_days: 2, deadline: "", grain_id: "Order", breach_rate: 0.182,
                 open_overdue: 3, as_of: "2026-10-09", verified: true, overdue_segment: "overdue_dispatch" } },
  ],
};

let flagged = new Set<string>();
const page = () => ({
  path: "listed", object_type: "order", type_id: "Order", key: "order_id", title: "", segment_said: "still waiting",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false },
            { name: "flagged_for_review", path: "flagged_for_review", label: "flagged_for_review", type: "BOOLEAN", edited: true }],
  names: ["order_id", "status", "flagged_for_review"],
  rows: ["48211", "48377", "48902"].map(k => [k, "Processing", flagged.has(k) ? "true" : null]),
  total: 3, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});
const objectPage = (pk: string) => ({
  path: "object", object_type: "order", type_id: "Order", type_name: "Order", key: "order_id", pk, title: null,
  connection_id: "thelook", schema_name: "thelook",
  properties: [
    { name: "order_id", value: pk, display_name: "order_id", semantic_type: "", data_type: "", unit: "", description: "" },
    { name: "status", value: "Processing", display_name: "status", semantic_type: "", data_type: "", unit: "", description: "" },
    ...(flagged.has(pk) ? [{ name: "flagged_for_review", value: "true", display_name: "flagged_for_review", semantic_type: "",
      data_type: "", unit: "", description: "",
      overlay: { by: "ana", at: "", note: "check with carrier", origin: "action:flag_for_review", provenance: "ana via flag_for_review", id: "e1" } }] : []),
  ],
  links: [], caveats: [], related: {},
});
const ACTION = {
  id: "flag_for_review", display_name: "Flag for review", description: "", entity: "", object_type: "Order", kind: "annotate",
  risk: "low", edits: [{ object: "order", property: "flagged_for_review", value: "true", note: "" }],
  params: [{ name: "order", display_name: "Order", data_type: "VARCHAR", required: true, default_value: null, kind: "object",
             object_type: "Order", description: "" }],
};

beforeEach(() => {
  flagged = new Set();
  vi.clearAllMocks();
  types.getProcesses.mockResolvedValue({ processes: [PROCESS], rules: [] });
  objects.listObjects.mockImplementation(async () => page());
  objects.getObjectPage.mockImplementation(async (_t: string, pk: string) => objectPage(pk));
  objects.getDeclaredActions.mockResolvedValue({ flag_for_review: ACTION });
});

const draw = () => render(<ComposedCockpit spec={SPEC} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" schema="thelook" />);

describe("a late dispatch cockpit (Arc OC-4)", () => {
  it("draws the board's stages and promise, and the table's total is the count the board shows", async () => {
    draw();
    const board = await screen.findByTestId("process-board");
    expect(within(board).getAllByTestId("process-stage").map(s => s.textContent)).toEqual([
      expect.stringContaining("124,978"), expect.stringContaining("81,184")]);
    expect(within(board).getByTestId("process-overdue").textContent).toContain("3 open and overdue");
    expect((await screen.findByTestId("object-table-total")).textContent).toBe("3");
    expect(objects.listObjects).toHaveBeenCalledWith(expect.objectContaining(
      { entity: "Order", segment: "overdue_dispatch", columns: ["status", "flagged_for_review"] }), "thelook", "thelook");
  });

  it("a row opens in the detail; running the action reads every piece again, and the edit shows in both", async () => {
    objects.runOrPropose.mockImplementation(async (_a: string, params: Record<string, unknown>) => {
      flagged.add(String(params.order));
      return { status: "ran", outcome: {} };
    });
    draw();
    const detail = () => screen.getByTestId("object-detail");
    expect(within(await screen.findByTestId("object-detail")).getByText("Choose a row in the table to see it here.")).toBeTruthy();
    fireEvent.click((await screen.findAllByTestId("object-table-row"))[1]);
    await waitFor(() => expect(within(detail()).getByText("48377")).toBeTruthy());
    const button = await within(detail()).findByRole("button", { name: /Flag for review/ });
    await act(async () => { fireEvent.click(button); });
    // Arc OC-6 — the version of the property the action sets, as this detail read it: none set yet, so 0
    expect(objects.runOrPropose).toHaveBeenCalledWith("flag_for_review", { order: "48377" }, "thelook", "thelook",
      "from a cockpit, on Order 48377", { flagged_for_review: 0 });
    await waitFor(() => expect(within(detail()).getByTestId("object-detail-edit").textContent).toContain("ana via flag_for_review"));
    const rows = screen.getAllByTestId("object-table-row").map(r => r.textContent);
    expect(rows[1]).toContain("yes");
    expect(rows[0]).not.toContain("yes");
    expect(within(detail()).getByTestId("action-button-said").textContent).toBe("Done.");
  });

  it("a run says what its check found, and a failed check is never read as done", async () => {
    objects.runOrPropose.mockResolvedValue({ status: "ran", outcome: {},
      verification: { status: "failed", why: "no row returned — the change is not visible" } });
    draw();
    fireEvent.click((await screen.findAllByTestId("object-table-row"))[0]);
    const button = await screen.findByRole("button", { name: /Flag for review/ });
    await act(async () => { fireEvent.click(button); });
    expect((await screen.findByTestId("action-button-said")).textContent)
      .toBe("It ran, but its check failed: no row returned — the change is not visible.");
    expect(ranSaid({ status: "passed", why: "1 row returned" })).toBe("Done — its check passed: 1 row returned.");
    expect(ranSaid({ status: "unavailable", why: "the read failed" })).toBe("Done — its check could not be read: the read failed.");
    expect(ranSaid({ status: "not_declared" })).toBe("Done.");
    expect(ranSaid({ status: "waits_for_a_person", why: "1 call it makes did not go out and waits for a person in Sends — refused" }))
      .toBe("It ran, but 1 call it makes did not go out and waits for a person in Sends — refused.");
    expect(ranSaid({ status: "pending", why: "1 call waits in the outbox; the action's check runs when it lands" }))
      .toBe("Done — 1 call waits in the outbox; the action's check runs when it lands.");
  });

  it("an action that needs approval is proposed in Actions, and nothing is written", async () => {
    objects.runOrPropose.mockResolvedValue({ status: "proposed", inbox_id: "p1" });
    draw();
    fireEvent.click((await screen.findAllByTestId("object-table-row"))[0]);
    const button = await screen.findByRole("button", { name: /Flag for review/ });
    await act(async () => { fireEvent.click(button); });
    expect((await screen.findByTestId("action-button-said")).textContent).toBe("It needs approval — proposed in Actions.");
    expect(screen.getAllByTestId("object-table-row").every(r => !r.textContent?.includes("yes"))).toBe(true);
  });

  it("a board says how many left the process, and that they are not counted open", async () => {
    types.getProcesses.mockResolvedValue({ processes: [{ ...PROCESS, leaves: { property: "status", values: ["Cancelled"],
      left: 18726, missing: [], unknown: 0, note: "" } }], rules: [] });
    draw();
    expect((await screen.findByTestId("process-leaves")).textContent)
      .toContain("18,726 left the process when status is Cancelled — they are not open, and never overdue");
  });

  it("a process the connection does not declare is said where the board stands", async () => {
    types.getProcesses.mockResolvedValue({ processes: [], rules: [] });
    draw();
    expect((await screen.findAllByTestId("ontology-piece-unread"))[0].textContent).toContain("order_fulfilment");
  });
});
