// @vitest-environment jsdom

/**
 * A wired cockpit, drawn (Arc AP-2; the study's receipt: "The dispatch desk of the mockup built by hand, numbers equal
 * to the door's"). Through the cockpit's own renderer with the object door mocked: each piece asks the door for its set —
 * the segment and the conditions down the sets it starts from, a value's days in place — a figure's click switches the
 * list and lets go of what was chosen in it, a row's click chooses the object a detail and a linked set read, ticks
 * collect. And the arc's falsifier: a cockpit drawn before the wiring asks the door for exactly what it asked before.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import type { CockpitHostState } from "@/lib/cockpit/hostState";
import type { ObjectQueryRequest } from "@/lib/objects";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const HOST: CockpitHostState = { range: { status: "standing" }, cards: {} };

const DESK = {
  root: "cockpit",
  values: { window: { label: "Window", kind: "days", value: 14 } },
  sets: {
    placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
    waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
    late: { label: "Shipped late", from: "placed", segment: "late_dispatch" },
    lines: { label: "Its lines", entity: "order_item", linked_to: { choice: "chosen-order", path: "order_id" } },
  },
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Dispatch desk" }, children: ["filters", "today"] },
    filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] },
    today: { type: "Section", props: { title: "Dispatch desk" }, children: ["fig-waiting", "fig-late", "table", "detail", "lines"] },
    "fig-waiting": { type: "ObjectFigure", props: { set: "waiting", of: "placed", shows: "shown", label: "Waiting past the promise", agg: "count" }, children: [] },
    "fig-late": { type: "ObjectFigure", props: { set: "late", shows: "shown", label: "Shipped late", agg: "count" }, children: [] },
    table: { type: "ObjectTable", props: { set: "waiting", set_from: "shown", chooses: "chosen-order", ticks: "ticked-orders", columns: ["status"] }, children: [] },
    detail: { type: "ObjectDetail", props: { follows: "chosen-order" }, children: [] },
    lines: { type: "ObjectTable", props: { set: "lines", columns: ["sale_price"] }, children: [] },
  },
};

const IN_14 = { path: "created_at", op: "in_last", value: 14 };
const count = (b: ObjectQueryRequest) => (b.segment === "overdue_dispatch" ? "1327" : b.segment === "late_dispatch" ? "759" : "6619");

function answer(b: ObjectQueryRequest) {
  const rows = b.by?.[0] ? [["Processing", "40"], ["Shipped", "60"]] : [[count(b)]];
  return { path: "compiled", columns: [], rows, caveats: [], error: null };
}

const listing = (b: { entity: string; segment?: string; filters?: unknown[] }) => ({
  path: "listed", object_type: b.entity, type_id: b.entity === "order" ? "Order" : "OrderItem", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }],
  names: ["id", "status"],
  rows: b.entity === "order_item" ? [["68304", "Processing"]] : b.segment === "late_dispatch" ? [["900", "Shipped"]] : [["38330", "Processing"], ["79251", "Processing"]],
  total: b.entity === "order_item" ? 1 : b.segment === "late_dispatch" ? 759 : 1327, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => answer(b));
  objects.listObjects.mockImplementation(async (b: { entity: string; segment?: string }) => listing(b));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
  objects.getDeclaredActions.mockResolvedValue({});
  objects.getObjectPage.mockImplementation(async (_t: string, pk: string) => ({
    path: "object", object_type: "order", type_id: "Order", type_name: "Order", pk, key: "id", title: `Order ${pk}`,
    properties: [{ name: "id", display_name: "Order Id", value: pk }], links: [], actions: [],
  }));
});

const draw = (spec: unknown = DESK) => render(
  <ComposedCockpit spec={spec} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" cockpitId="thelook:desk" />);
const asked = () => objects.queryObjects.mock.calls.map(c => c[0] as ObjectQueryRequest);
const listed = () => objects.listObjects.mock.calls.map(c => c[0] as { entity: string; segment: string; filters: unknown[] });
const figure = (label: string) => screen.getAllByTestId("object-figure").find(f => f.textContent?.startsWith(label)) as HTMLElement;
const tables = () => screen.getAllByTestId("object-table");

describe("a wired cockpit", () => {
  it("asks the door for each piece's set: its segment and every condition down the sets it starts from", async () => {
    draw();
    await waitFor(() => expect(figure("Waiting past the promise").textContent).toContain("1,327"));
    expect(figure("Waiting past the promise").textContent).toContain("of 6,619 placed");
    expect(asked()).toContainEqual({ object_type: "order", segment: "overdue_dispatch", measures: [{ name: "v", agg: "count", path: "" }], filters: [IN_14] });
    expect(asked()).toContainEqual({ object_type: "order", measures: [{ name: "v", agg: "count", path: "" }], filters: [IN_14] });
    await waitFor(() => expect(listed()).toContainEqual(expect.objectContaining({ entity: "order", segment: "overdue_dispatch", filters: [IN_14] })));
  });

  it("switches the list on a figure's click — lit while it is shown — and lets go of what was chosen and ticked in it", async () => {
    draw();
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 79251" }));
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("order", "38330", "thelook", undefined));
    expect(screen.getAllByTestId("object-figure-shows")[0]).toHaveAttribute("aria-pressed", "true");     // its own set, before a click
    fireEvent.click(screen.getAllByTestId("object-figure-shows")[1]);
    await waitFor(() => expect(listed().at(-1)).toMatchObject({ entity: "order", segment: "late_dispatch" }));
    expect(screen.getAllByTestId("object-figure-shows")[1]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByTestId("object-figure-shows")[0]).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(screen.getByText("Choose a row in the table to see it here.")).toBeInTheDocument());
    expect(screen.queryByTestId("object-table-ticked")).toBeNull();
  });

  it("chooses the object a detail follows and a linked set reads, on a row's click — and waits for one before", async () => {
    draw();
    await waitFor(() => expect(screen.getByTestId("object-table-waiting")).toHaveTextContent("Choose an order in its table to see its lines here."));
    expect(listed().some(b => b.entity === "order_item")).toBe(false);                      // nothing is read before a choice
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    await waitFor(() => expect(listed()).toContainEqual(expect.objectContaining({ entity: "order_item", filters: [{ path: "order_id", op: "=", value: "38330" }] })));
    await waitFor(() => expect(screen.getByTestId("object-detail")).toHaveTextContent("Order 38330"));
  });

  it("never shows the lines of the order chosen before while the next one's are read", async () => {
    draw();
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    await waitFor(() => expect(screen.getByText("68304")).toBeInTheDocument());             // 38330's line
    fireEvent.click(screen.getAllByTestId("object-figure-shows")[1]);                        // the list switched: let go
    await waitFor(() => expect(screen.getByTestId("object-table-waiting")).toBeInTheDocument());
    // the next order's lines are on their way, and stay on their way
    objects.listObjects.mockImplementation(async (b: { entity: string; segment?: string; filters?: unknown[] }) =>
      (b.entity === "order_item" ? new Promise(() => {}) : listing(b)));
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(1));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);               // order 900
    await waitFor(() => expect(listed()).toContainEqual(expect.objectContaining({ entity: "order_item", filters: [{ path: "order_id", op: "=", value: "900" }] })));
    expect(screen.queryByText("68304")).toBeNull();
  });

  it("ticks at most the fifty one press runs on, across its pages", async () => {
    const pageOf = (b: { entity: string; offset?: number; limit?: number }) => {
      const from = b.offset ?? 0;
      const ids = Array.from({ length: Math.min(b.limit ?? 6, 60 - from) }, (_, i) => String(from + i + 1));
      return { ...listing(b), rows: ids.map(id => [id, "Processing"]), total: 60, offset: from };
    };
    objects.listObjects.mockImplementation(async (b: { entity: string; offset?: number; limit?: number }) => pageOf(b));
    draw({ root: "cockpit", values: DESK.values, sets: { placed: DESK.sets.placed, waiting: DESK.sets.waiting }, elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["today"] },
      today: { type: "Section", props: { title: "Desk" }, children: ["table"] },
      table: { type: "ObjectTable", props: { set: "waiting", ticks: "ticked-orders", columns: ["status"] }, children: [] } } });
    for (let page = 0; page < 9; page++) {
      const first = String(page * 6 + 1);
      await waitFor(() => expect(screen.getByRole("checkbox", { name: `Tick ${first}` })).toBeInTheDocument());
      const boxes = screen.getAllByRole("checkbox", { name: /^Tick / });
      for (const box of page < 8 ? boxes : boxes.slice(0, 2)) fireEvent.click(box);
      if (page < 8) fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    }
    expect(screen.getByTestId("object-table-ticked")).toHaveTextContent("50 ticked (the most one press runs on)");
    expect(screen.getByRole("checkbox", { name: "Tick 50" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Tick 51" })).toBeDisabled();               // the 51st may not be ticked
    expect(screen.getByRole("checkbox", { name: "Tick 50" })).not.toBeDisabled();           // a ticked one may be let go
  });

  it("collects ticks in a table that names them, and clears them", async () => {
    draw();
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: /^Tick / })).toHaveLength(2));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 79251" }));
    expect(screen.getByTestId("object-table-ticked")).toHaveTextContent("2 ticked");
    fireEvent.click(within(screen.getByTestId("object-table-ticked")).getByRole("button", { name: "Clear" }));
    expect(screen.queryByTestId("object-table-ticked")).toBeNull();
  });

  it("narrows a set of the filtered entity by the reader's filters, and says Not filtered on one over another", async () => {
    draw();
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Status: Processing" }));
    const status = { path: "status", op: "in", values: ["Processing"] };
    await waitFor(() => expect(asked()).toContainEqual({ object_type: "order", segment: "overdue_dispatch", measures: [{ name: "v", agg: "count", path: "" }], filters: [IN_14, status] }));
    // the reader's choice let go of the chosen order, so the lines wait again; and they are another entity: not filtered
    await waitFor(() => expect(screen.getAllByTestId("not-filtered")).toHaveLength(1));
  });
});

describe("a cockpit drawn before the wiring (the arc's falsifier)", () => {
  const PLAIN = {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] },
      sec: { type: "Section", props: { title: "Orders", columns: 3 }, children: ["count", "chart", "table"] },
      count: { type: "ObjectFigure", props: { entity: "order", label: "Orders", agg: "count", format: "number" }, children: [] },
      chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", days: 7 }, children: [] },
      table: { type: "ObjectTable", props: { entity: "order", segment: "overdue_dispatch", columns: ["status"] }, children: [] },
    },
  };

  it("asks the object door for exactly what it asked before sets — not a key more", async () => {
    objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => (b.measures[0].agg === "max"
      ? { path: "compiled", columns: [], rows: [["2026-10-09 23:10:00"]], caveats: [], error: null } : answer(b)));
    draw(PLAIN);
    await waitFor(() => expect(asked().some(b => b.grain === "day")).toBe(true));
    await waitFor(() => expect(listed().length).toBeGreaterThan(0));
    const bodies = new Set(asked().map(b => JSON.stringify(b)));
    const day = asked().find(b => b.grain === "day")!;
    // the bodies the pieces asked before Arc AP-2 — keys and their order, exactly
    expect(bodies).toEqual(new Set([
      // the filter column's own list — its code untouched by the wiring
      JSON.stringify({ object_type: "order", measures: [{ name: "n", agg: "count" }], by: ["status"], filters: [], order_by: "n", descending: true, limit: 51 }),
      JSON.stringify({ object_type: "order", measures: [{ name: "n", agg: "count" }] }),
      JSON.stringify({ object_type: "order", measures: [{ name: "v", agg: "count", path: "" }] }),
      JSON.stringify({ object_type: "order", measures: [{ name: "t", agg: "max", path: "created_at" }] }),
      JSON.stringify({ object_type: "order", measures: [{ name: "n", agg: "count", path: "" }], time: "created_at", grain: "day", start: day.start, end: day.end, filters: [] }),
    ]));
    expect(listed()[0]).toEqual({ entity: "order", segment: "overdue_dispatch", columns: ["status"], order_by: "", descending: false, offset: 0, limit: 6, filters: [] });
  });
});
