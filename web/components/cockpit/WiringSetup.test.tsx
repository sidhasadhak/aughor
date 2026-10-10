// @vitest-environment jsdom

/**
 * Wiring a cockpit in the builder (Arc AP-2 and AP-3; design-mockups/cockpit-builder.html screens 3 and 4). The Data tab
 * lists the sets with what each holds now and what reads it, the choices and the values; a set is built from what the
 * ontology offers and taken away only when nothing reads it; a piece's setup says what it reads and what it chooses; a
 * button's parameter is offered only sources that hold its entity. Every read is mocked — no test reaches an API.
 */
import { choose, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ButtonsSetup } from "@/components/cockpit/ButtonsSetup";
import { PieceSetup } from "@/components/cockpit/PieceSetup";
import { DataPane, SetSetup, ValueSetup } from "@/components/cockpit/WiringSetup";
import type { CockpitSpec } from "@/lib/cockpit/edit";

const objects = vi.hoisted(() => ({ queryObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getDeclaredActions: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const types = vi.hoisted(() => ({ getObjectType: vi.fn(), getProcesses: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));

const prop = (name: string, role: string, data_type = "STRING") =>
  ({ name, display_name: name.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase()), role, data_type, unit: "", is_key: name === "id", null_rate: 0, description: "", source: {} });
const ORDER = { id: "order", segments: ["overdue_dispatch", "returned_orders"], links: [],
  properties: [prop("id", "key", "INT64"), prop("status", "dimension"), prop("created_at", "timestamp", "TIMESTAMP"), prop("shipped_at", "timestamp", "TIMESTAMP")] };

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    values: { window: { label: "Window", kind: "days", value: 14 } },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      items: { label: "Items", entity: "order_item" },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Desk" }, children: ["fig", "table", "buttons"] },
      fig: { type: "ObjectFigure", props: { set: "waiting", label: "Waiting", agg: "count" }, children: [] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order" }, children: [] },
      buttons: { type: "ActionButtons", props: { buttons: [{ action: "open_case" }] }, children: [] },
    },
  };
}

let conn = 0;
beforeEach(() => {
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: { segment?: string }) => ({ path: "compiled", rows: [[b.segment ? "1327" : "6619"]], caveats: [], error: null }));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Customer Order" }, { object_type: "order_item", id: "OrderItem", display_name: "Order Line" }] });
  objects.getDeclaredActions.mockResolvedValue({
    open_case: { id: "open_case", display_name: "Open a case", description: "", entity: "order", object_type: "order", kind: "annotate", risk: "low", edits: [],
      params: [{ name: "order", display_name: "Order", data_type: "VARCHAR", required: true, default_value: null, kind: "object", object_type: "order", description: "" },
        { name: "assignee", display_name: "Who has it", data_type: "VARCHAR", required: true, default_value: null, kind: "value", object_type: "", description: "" }] },
  });
  types.getObjectType.mockImplementation(async () => ORDER);
});

describe("the Data tab", () => {
  it("lists each set with what it starts from, what it holds now and how much reads it; the choices; the values", async () => {
    render(<DataPane spec={desk()} selected={null} onSelect={vi.fn()} onChange={vi.fn()} connectionId={`c${++conn}`} />);
    const sets = screen.getAllByTestId("data-set");
    expect(sets.map(s => s.dataset.name)).toEqual(["placed", "waiting", "items"]);
    await waitFor(() => expect(sets[1]).toHaveTextContent("1,327"));
    expect(sets[1]).toHaveTextContent("Placed · overdue dispatch");
    expect(sets[1]).toHaveTextContent("read by 2");
    expect(sets[0]).toHaveTextContent("read by 1");                                          // Waiting starts from it
    expect(screen.getByTestId("data-choice")).toHaveTextContent("chosen order");
    expect(screen.getByTestId("data-value")).toHaveTextContent("14 days");
  });

  it("adds a set and a value by hand, chosen at once", async () => {
    const onChange = vi.fn(), onSelect = vi.fn();
    render(<DataPane spec={desk()} selected={null} onSelect={onSelect} onChange={onChange} connectionId={`c${++conn}`} />);
    fireEvent.click(screen.getByTestId("data-new-set"));
    // a cockpit whose every piece reads a set still offers one: it starts from the entity its sets read
    expect(onChange.mock.calls[0][0].sets["new-set"]).toEqual({ label: "New set", entity: "order" });
    expect(onSelect).toHaveBeenCalledWith("set:new-set");
    fireEvent.click(screen.getByTestId("data-new-value"));
    expect(onChange.mock.calls[1][0].values["window-2"]).toEqual({ label: "Window", kind: "days", value: 14 });
  });
});

describe("a set's setup", () => {
  it("says what it holds and what reads it, and is not taken away while something does", async () => {
    render(<SetSetup spec={desk()} name="waiting" onChange={vi.fn()} onGone={vi.fn()} connectionId={`c${++conn}`} />);
    await waitFor(() => expect(screen.getByTestId("set-holds")).toHaveTextContent("1,327"));
    expect(screen.getByTestId("setup-read-by")).toHaveTextContent("Figure · Waiting");
    expect(screen.getByTestId("setup-read-by")).toHaveTextContent("Objects table · Waiting");
    expect(screen.getByTestId("setup-wire-delete")).toBeDisabled();
  });

  it("is renamed, started from another set, kept to a segment, and given a condition — a date's counts back days", async () => {
    const onChange = vi.fn();
    render(<SetSetup spec={desk()} name="waiting" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} />);
    const name = screen.getByLabelText("The set's name");
    fireEvent.change(name, { target: { value: "Waiting past the promise" } });
    fireEvent.blur(name);
    expect(onChange.mock.calls[0][0].sets.waiting.label).toBe("Waiting past the promise");
    await waitFor(() => expect(screen.getByLabelText("Segment")).toBeInTheDocument());
    await choose(screen.getByLabelText("Segment"), "returned_orders");
    expect(onChange.mock.calls[1][0].sets.waiting.segment).toBe("returned_orders");
    await waitFor(() => expect(screen.getByLabelText("Add a condition")).toBeInTheDocument());
    await choose(screen.getByLabelText("Add a condition"), "shipped_at");
    expect(onChange.mock.calls[2][0].sets.waiting.where).toEqual([{ path: "shipped_at", op: "in_last", value: 14 }]);
    await choose(screen.getByLabelText("Starts from"), "entity:order");
    expect(onChange.mock.calls[3][0].sets.waiting).toEqual({ label: "Waiting", entity: "order", segment: "overdue_dispatch" });
  });

  it("is taken away once nothing reads it", () => {
    const onChange = vi.fn(), onGone = vi.fn();
    render(<SetSetup spec={desk()} name="items" onChange={onChange} onGone={onGone} connectionId={`c${++conn}`} />);
    fireEvent.click(screen.getByTestId("setup-wire-delete"));
    expect(onChange.mock.calls[0][0].sets.items).toBeUndefined();
    expect(onGone).toHaveBeenCalled();
  });

  it("links to the object a table chooses, through a property of its own", async () => {
    const onChange = vi.fn();
    render(<SetSetup spec={desk()} name="items" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} />);
    await choose(screen.getByLabelText("Linked to"), "chosen-order");
    expect(onChange.mock.calls[0][0].sets.items.linked_to).toMatchObject({ choice: "chosen-order" });
  });
});

describe("a value's setup", () => {
  it("changes its days, and keeps a value that is not a whole number of days out", () => {
    const onChange = vi.fn();
    render(<ValueSetup spec={desk()} name="window" onChange={onChange} onGone={vi.fn()} />);
    const v = screen.getByLabelText("The value");
    fireEvent.change(v, { target: { value: "30" } });
    fireEvent.blur(v);
    expect(onChange.mock.calls[0][0].values.window.value).toBe(30);
    fireEvent.change(v, { target: { value: "2.5" } });
    fireEvent.blur(v);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("setup-wire-delete")).toBeDisabled();                         // Placed reads it
  });
});

describe("a piece's wiring", () => {
  it("reads every object of its entity or a set; a click chooses for the cockpit; ticks collect", async () => {
    const onChange = vi.fn();
    render(<PieceSetup spec={desk()} selected="table" onChange={onChange} connectionId={`c${++conn}`} wiringOn />);
    await choose(screen.getByLabelText("Reads"), "entity:order");
    expect(onChange.mock.calls[0][0].elements.table.props).toEqual({ chooses: "chosen-order", entity: "order" });
    fireEvent.click(within(screen.getByTestId("setup-ticks")).getByRole("checkbox"));
    expect(onChange.mock.calls[1][0].elements.table.props.ticks).toBe("ticked-order");
    fireEvent.click(within(screen.getByTestId("setup-chooses")).getByRole("checkbox"));
    expect(onChange.mock.calls[2][0].elements.table.props.chooses).toBeUndefined();
  });

  it("is not offered while the install does not wire cockpits", () => {
    render(<PieceSetup spec={desk()} selected="table" onChange={vi.fn()} connectionId={`c${++conn}`} />);
    expect(screen.queryByTestId("setup-reads")).toBeNull();
    expect(screen.queryByTestId("setup-chooses")).toBeNull();
  });
});

describe("a button's setup", () => {
  it("offers a parameter only the sources that hold its entity, and fills a value from the form or the same every time", async () => {
    const onChange = vi.fn();
    render(<ButtonsSetup spec={desk()} k="buttons" onChange={onChange} connectionId={`c${++conn}`} />);
    await waitFor(() => expect(screen.getAllByTestId("setup-param")).toHaveLength(2));
    const order = screen.getByLabelText("Where Order comes from");
    fireEvent.keyDown(order, { key: "ArrowDown" });
    const offered = screen.getAllByRole("option").map(o => o.getAttribute("data-value"));
    fireEvent.keyDown(order, { key: "Escape" });
    // the chosen order and the sets of orders — never the set of order lines
    expect(offered).toEqual(expect.arrayContaining(["from:chosen-order", "set:placed", "set:waiting"]));
    expect(offered).not.toContain("set:items");
    await choose(order, "from:chosen-order");
    expect(onChange.mock.calls[0][0].elements.buttons.props.buttons[0].params).toEqual({ order: { from: "chosen-order" } });
    await choose(screen.getByLabelText("Where Who has it comes from"), "ask");
    expect(onChange.mock.calls[1][0].elements.buttons.props.buttons[0].params).toEqual({ assignee: { ask: true } });
  });

  it("asks first or runs, is disabled or hidden, and names the sets read again after it runs", async () => {
    const onChange = vi.fn();
    render(<ButtonsSetup spec={desk()} k="buttons" onChange={onChange} connectionId={`c${++conn}`} />);
    await waitFor(() => expect(screen.getAllByTestId("setup-param")).toHaveLength(2));
    fireEvent.click(screen.getByRole("checkbox", { name: "Read Waiting again" }));
    expect(onChange.mock.calls.at(-1)![0].elements.buttons.props.buttons[0].after).toEqual({ read: ["waiting"] });
  });
});
