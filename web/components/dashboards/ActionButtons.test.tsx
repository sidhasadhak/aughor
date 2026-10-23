// @vitest-environment jsdom

/**
 * Action buttons on a dashboard (Arc AP-3; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.5). Drawn through the dashboard's
 * own renderer with the object door and the action door mocked. Every run is one call to the declared action's own door
 * — so its criteria, risk and approval hold on each — and a press says on its row what ran, what waits for approval and
 * what was refused, and why. A button that cannot run says why, or is hidden; it never guesses an object.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { DashboardHostState } from "@/lib/dashboards/hostState";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(),
  runOrPropose: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };
const ORDER = { name: "order", display_name: "Order", data_type: "VARCHAR", required: true, default_value: null, kind: "object", object_type: "order", description: "" };
const ACTIONS = {
  open_case: { id: "open_case", display_name: "Open a case", description: "Open a case on a late order, with who has it.", entity: "order", object_type: "order",
    kind: "annotate", risk: "low", edits: [], params: [ORDER, { ...ORDER, name: "assignee", display_name: "Who has it", kind: "value", object_type: "" }] },
  flag_for_review: { id: "flag_for_review", display_name: "Flag for review", description: "", entity: "order", object_type: "Order", kind: "annotate", risk: "high", edits: [],
    params: [ORDER, { ...ORDER, name: "reason", display_name: "Reason", kind: "value", object_type: "", required: false, default_value: "" }] },
};

function spec(buttons: unknown[]) {
  return {
    root: "cockpit",
    sets: { waiting: { label: "Waiting", entity: "order", segment: "overdue_dispatch" } },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Desk" }, children: ["table", "buttons"] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order", ticks: "ticked-orders" }, children: [] },
      buttons: { type: "ActionButtons", props: { buttons }, children: [] },
    },
  };
}
const OPEN = { action: "open_case", params: { order: { from: "chosen-order" }, assignee: { ask: true } }, after: { read: ["waiting"] } };
const FLAG = { action: "flag_for_review", params: { order: { from: "ticked-orders" } } };

const listing = (total = 2, rows = [["38330", "Processing"], ["79251", "Processing"]]) => ({
  path: "listed", object_type: "order", type_id: "Order", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }], names: ["id", "status"],
  rows, total, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  objects.listObjects.mockImplementation(async () => listing());
  objects.getDeclaredActions.mockResolvedValue(ACTIONS);
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [] });
  objects.runOrPropose.mockResolvedValue({ status: "ran", outcome: {} });
});

const draw = (buttons: unknown[]) => render(<ComposedDashboard spec={spec(buttons)} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" />);
const row = (i: number) => screen.getAllByTestId("object-table-row")[i];
const said = () => screen.getAllByTestId("action-buttons-said").map(s => s.textContent);

describe("a button on a dashboard", () => {
  it("is disabled and says why until what it runs on is chosen or ticked — or is hidden, as its author chose", async () => {
    draw([OPEN, FLAG, { ...FLAG, label: "Hidden one", blocked: "hide" }]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Open a case" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Flag for review" })).toBeDisabled();
    expect(said()).toEqual(["Choose an order first.", "Tick at least one order."]);
    expect(screen.queryByRole("button", { name: "Hidden one" })).toBeNull();
  });

  it("runs once on the chosen order, asking in its form what it must, through the action's own door — then the pieces read again", async () => {
    draw([OPEN]);
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(row(0));
    fireEvent.click(screen.getByRole("button", { name: "Open a case" }));
    const form = await screen.findByTestId("action-buttons-form");
    expect(form).toHaveTextContent("Order 38330");
    const run = within(form).getByTestId("action-buttons-run");
    expect(run).toBeDisabled();                                                             // who has it is needed
    fireEvent.change(within(form).getByLabelText("Who has it"), { target: { value: "Dispatch team" } });
    const reads = objects.listObjects.mock.calls.length;
    await act(async () => { fireEvent.click(run); });
    expect(objects.runOrPropose).toHaveBeenCalledTimes(1);
    expect(objects.runOrPropose).toHaveBeenCalledWith("open_case", { order: "38330", assignee: "Dispatch team" }, "thelook", undefined,
      "from a dashboard's button: Open a case");
    await waitFor(() => expect(said()).toEqual(["Done."]));
    await waitFor(() => expect(objects.listObjects.mock.calls.length).toBeGreaterThan(reads));   // read again
  });

  it("runs once per ticked order, each its own — a high-risk action proposing each for approval", async () => {
    objects.runOrPropose.mockResolvedValue({ status: "proposed", inbox_id: "i1" });
    draw([FLAG]);
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: /^Tick / })).toHaveLength(2));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 79251" }));
    fireEvent.click(screen.getByRole("button", { name: "Flag for review" }));
    const form = await screen.findByTestId("action-buttons-form");
    expect(form).toHaveTextContent("2 ticked orders");
    expect(form).toHaveTextContent("high risk · proposed for approval, each on its own");
    await act(async () => { fireEvent.click(within(form).getByTestId("action-buttons-run")); });
    expect(objects.runOrPropose.mock.calls.map(c => c[1])).toEqual([{ order: "38330" }, { order: "79251" }]);
    await waitFor(() => expect(said()).toEqual(["2 wait for approval in Actions."]));
  });

  it("says a refused run with why, beside the ones that ran", async () => {
    objects.runOrPropose.mockResolvedValueOnce({ status: "ran", outcome: {} })
      .mockResolvedValueOnce({ status: "refused", message: "its criteria did not hold: the order is closed" });
    draw([{ ...FLAG, ask: "run" }]);
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: /^Tick / })).toHaveLength(2));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 79251" }));
    fireEvent.click(screen.getByRole("button", { name: "Flag for review" }));
    // the reason may be left, but the form still asks it first: an optional question is still a question
    const form = await screen.findByTestId("action-buttons-form");
    await act(async () => { fireEvent.click(within(form).getByTestId("action-buttons-run")); });
    await waitFor(() => expect(said()).toEqual(["Ran on 1 order. 1 refused: its criteria did not hold: the order is closed."]));
  });

  it("runs on a set's objects read at the press, saying how many — and refuses more than fifty", async () => {
    draw([{ action: "flag_for_review", params: { order: { set: "waiting" }, reason: { value: "past the promise" } } }]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Flag for review" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Flag for review" }));
    const form = await screen.findByTestId("action-buttons-form");
    expect(form).toHaveTextContent("every order in waiting · 2 now");
    await act(async () => { fireEvent.click(within(form).getByTestId("action-buttons-run")); });
    expect(objects.runOrPropose.mock.calls.map(c => c[1])).toEqual([{ reason: "past the promise", order: "38330" }, { reason: "past the promise", order: "79251" }]);
    await waitFor(() => expect(screen.queryByTestId("action-buttons-form")).toBeNull());
    objects.listObjects.mockImplementation(async () => listing(1327));
    fireEvent.click(screen.getByRole("button", { name: "Flag for review" }));
    await waitFor(() => expect(said().join(" ")).toMatch(/waiting holds 1,327; a press runs on at most 50/));
    // and nothing opens: never a form whose Run would run on the first fifty of 1,327, or do nothing
    expect(screen.queryByTestId("action-buttons-form")).toBeNull();
    expect(objects.runOrPropose).toHaveBeenCalledTimes(2);
  });

  it("says an action that is not declared here, and a server that failed — never as a refusal the action made", async () => {
    objects.runOrPropose.mockResolvedValue({ status: "refused", message: "HTTP 500" });
    draw([{ action: "not_declared" }, OPEN]);
    expect(await screen.findByTestId("action-button-missing")).toHaveTextContent("The action “not_declared” is not declared here.");
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(row(1));
    fireEvent.click(screen.getByRole("button", { name: "Open a case" }));
    const form = await screen.findByTestId("action-buttons-form");
    fireEvent.change(within(form).getByLabelText("Who has it"), { target: { value: "Dispatch team" } });
    await act(async () => { fireEvent.click(within(form).getByTestId("action-buttons-run")); });
    await waitFor(() => expect(said().join(" ")).toMatch(/^It did not run: the server failed while running it \(HTTP 500\)/));
    expect(said().join(" ")).not.toMatch(/refused/);                                       // a failure, never a refusal
  });
});
