// @vitest-environment jsdom

/**
 * The builder's Setup (Arc AP-1; the study's receipt: "Change the Order cockpit's chart to split by status and its
 * table's columns, with no spec written by hand"). Each field offers what the ontology declares for the entity — read
 * here from a stand-in shaped as theLook's Order is served, its roles and its two links to the customer — and hands back
 * the next spec with the version's note. Nothing is typed as a spec.
 */
import { choose, fireEvent, optionsOf, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fieldsFor, PieceSetup, type EntityFields } from "@/components/cockpit/PieceSetup";
import type { CockpitSpec } from "@/lib/cockpit/edit";

const types = vi.hoisted(() => ({ getObjectType: vi.fn(), getProcesses: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), getDeclaredActions: vi.fn(async () => ({})) }));

const prop = (name: string, role: string, data_type = "STRING", unit = "", is_key = false) =>
  ({ name, display_name: name.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase()), role, data_type, unit, is_key, null_rate: 0, description: "", source: {} });
const ORDER = {
  id: "order", segments: ["active_orders", "returned_orders"],
  properties: [prop("order_id", "key", "INT64", "", true), prop("status", "dimension"), prop("gender", "dimension"),
    prop("created_at", "timestamp", "TIMESTAMP"), prop("shipped_at", "timestamp", "TIMESTAMP"), prop("num_of_item", "ordinal", "INT64"),
    prop("revenue", "measure", "FLOAT64", "USD"), prop("line_count", "measure", "")],
  links: [
    { name: "order_to_user", kind: "to-one", traversable: true, to: "user", to_name: "Customer" },
    { name: "placed_by", kind: "to-one", traversable: true, to: "user", to_name: "Customer" },
    { name: "order_to_order_item", kind: "to-many", traversable: true, to: "order_item", to_name: "Order Line" },
  ],
};
const USER = { id: "user", segments: [], links: [], properties: [prop("id", "key", "INT64", "", true), prop("country", "dimension"), prop("age", "measure", "INT64")] };

let conn = 0;
/** The setup for one element, on a connection of its own — what an entity offers is read once per connection. */
function setUp(spec: CockpitSpec, selected: string) {
  const onChange = vi.fn();
  render(<PieceSetup spec={spec} selected={selected} onChange={onChange} connectionId={`conn-${++conn}`} schema="thelook" />);
  return onChange;
}

function cockpit(extra: Record<string, unknown> = {}): CockpitSpec {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }, { path: "gender", label: "Gender" }] }, children: [] },
      sec: { type: "Section", props: { title: "Orders" }, children: ["figure", "chart", "table"] },
      figure: { type: "ObjectFigure", props: { entity: "order", label: "Orders", agg: "count" }, children: [] },
      chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", ...extra }, children: [] },
      table: { type: "ObjectTable", props: { entity: "order", columns: ["status", "order_to_user.country"] }, children: [] },
    },
  };
}

beforeEach(() => {
  types.getObjectType.mockReset();
  types.getObjectType.mockImplementation(async (t: string) => (t === "order" ? ORDER : USER));
});

describe("an objects table", () => {
  it("lists the entity's properties and its customer's, ticks its columns in their order, and keeps the link it reads", async () => {
    setUp(cockpit(), "table");
    const cols = await screen.findByTestId("setup-columns");
    const ticked = within(cols).getAllByRole("checkbox").filter(c => c.getAttribute("aria-checked") === "true")
      .map(c => c.getAttribute("aria-label"));
    // the country is read through the link the table names — offered as itself, never as a second Country or raw words
    expect(ticked).toEqual(["Status", "Country via Customer"]);
    expect(within(cols).queryByLabelText("order to user.country")).toBeNull();
    expect(within(cols).getByLabelText("Revenue")).toBeInTheDocument();
    expect(within(cols).queryByLabelText("Order id")).toBeNull();                 // the key is listed beside every object
  });

  it("adds a column at the end and takes one off, each as the next spec", async () => {
    const onChange = setUp(cockpit(), "table");
    fireEvent.click(within(await screen.findByTestId("setup-columns")).getByLabelText("Shipped at"));
    expect(onChange.mock.calls[0][0].elements.table.props.columns).toEqual(["status", "order_to_user.country", "shipped_at"]);
    expect(onChange.mock.calls[0][1]).toBe("a table's columns chosen by hand");
    fireEvent.click(within(screen.getByTestId("setup-columns")).getByLabelText("Status"));
    expect(onChange.mock.calls[1][0].elements.table.props.columns).toEqual(["order_to_user.country"]);
  });

  it("lists a segment, or every object again, and sorts newest first once it sorts at all", async () => {
    const onChange = setUp(cockpit(), "table");
    await screen.findByTestId("setup-columns");
    await choose(screen.getByLabelText("Segment"), "returned_orders");
    expect(onChange.mock.calls[0][0].elements.table.props.segment).toBe("returned_orders");
    await choose(screen.getByLabelText("Sorted by"), "created_at");
    expect(onChange.mock.calls[1][0].elements.table.props).toMatchObject({ sort: "created_at", descending: true });
  });
});

describe("a chart", () => {
  it("is split by a category its objects hold, and how many values it draws is chosen", async () => {
    const onChange = setUp(cockpit(), "chart");
    await screen.findByTestId("setup-split");
    await choose(screen.getByLabelText("Split by"), "status");
    const [next, note] = onChange.mock.calls[0];
    expect(next.elements.chart.props).toMatchObject({ split: "status" });
    expect(next.elements.chart.props.top).toBeUndefined();                      // five, as a chart that says none draws
    expect(note).toBe("a chart's split chosen by hand");
  });

  it("measures a sum of a number, written as money when its unit is a currency, and counts again with no measure said", async () => {
    const onChange = setUp(cockpit(), "chart");
    await screen.findByTestId("setup-split");
    await choose(screen.getByLabelText("Measure"), "sum");
    expect(onChange.mock.calls[0][0].elements.chart.props).toMatchObject({ agg: "sum", path: "revenue", format: "money" });
    onChange.mockClear();
    const counted = cockpit({ agg: "sum", path: "revenue", format: "money" });
    render(<PieceSetup spec={counted} selected="chart" onChange={onChange} connectionId={`conn-${++conn}`} />);
    await waitFor(() => expect(screen.getAllByLabelText("Measure")).toHaveLength(2));
    await choose(screen.getAllByLabelText("Measure")[1], "count");
    const props = onChange.mock.calls[0][0].elements.chart.props;
    expect(props.agg).toBeUndefined();
    expect(props.path).toBeUndefined();
    expect(props.format).toBeUndefined();
  });

  it("offers no split while it measures what does not add up", async () => {
    setUp(cockpit({ agg: "avg", path: "num_of_item" }), "chart");
    await screen.findByTestId("setup-split");
    expect(screen.getByLabelText("Split by")).toBeDisabled();
    expect(screen.getByTestId("setup-split")).toHaveTextContent("A split stacks its bars");
  });

  it("splits only what adds up: once split, its measures are a count or a sum", async () => {
    setUp(cockpit({ split: "status" }), "chart");
    await screen.findByTestId("setup-split");
    fireEvent.keyDown(screen.getByLabelText("Measure"), { key: "ArrowDown" });
    const offered = screen.getAllByRole("option").map(o => o.getAttribute("data-value"));
    fireEvent.keyDown(screen.getByLabelText("Measure"), { key: "Escape" });
    expect(offered).toEqual(["count", "sum"]);
  });
});

describe("a figure", () => {
  it("averages money first once its measure is an average — the order's average value — and any number when chosen", async () => {
    const onChange = setUp(cockpit(), "figure");
    await waitFor(() => expect(screen.getByLabelText("Measure")).toBeInTheDocument());
    await choose(screen.getByLabelText("Measure"), "avg");
    expect(onChange.mock.calls[0][0].elements.figure.props).toMatchObject({ agg: "avg", path: "revenue", format: "money" });
    onChange.mockClear();
    render(<PieceSetup spec={{ ...cockpit(), elements: { ...cockpit().elements, figure: { type: "ObjectFigure", props:
      { entity: "order", label: "Items", agg: "avg", path: "revenue", format: "money" }, children: [] } } }}
      selected="figure" onChange={onChange} connectionId={`conn-${++conn}`} />);
    await waitFor(() => expect(screen.getAllByLabelText("Of")).toHaveLength(1));
    await choose(screen.getByLabelText("Of"), "num_of_item");
    expect(onChange.mock.calls[0][0].elements.figure.props).toMatchObject({ agg: "avg", path: "num_of_item" });
    expect(onChange.mock.calls[0][0].elements.figure.props.format).toBeUndefined();     // items are not money
  });
});

describe("the filter column", () => {
  it("adds a category, moves one, and keeps at least one", async () => {
    const onChange = setUp(cockpit(), "filters");
    const list = await screen.findByTestId("setup-filters");
    await choose(within(list).getByLabelText("Add a filter"), "placed_by.country");
    expect(onChange.mock.calls[0][0].elements.filters.props.properties.at(-1)).toEqual(
      { path: "placed_by.country", label: "Country", via: "Customer" });
    fireEvent.click(within(list).getByRole("button", { name: "Move Gender up" }));
    expect(onChange.mock.calls[1][0].elements.filters.props.properties.map((p: { path: string }) => p.path)).toEqual(["gender", "status"]);
    fireEvent.click(within(list).getByRole("button", { name: "Take Status off" }));
    expect(onChange.mock.calls[2][0].elements.filters.props.properties.map((p: { path: string }) => p.path)).toEqual(["gender"]);
  });
});

describe("what a piece is offered of a linked object", () => {
  const ef: EntityFields = {
    fields: [{ path: "status", label: "Status", role: "dimension", type: "STRING", unit: "" },
      { path: "placed_by.country", label: "Country", via: "Customer", role: "dimension", type: "STRING", unit: "" }],
    segments: [], links: [{ name: "order_to_user", to: "user" }, { name: "placed_by", to: "user" }], offeredFor: { user: "placed_by" },
  };

  it("is read through the link the piece already reads it by", () => {
    expect(fieldsFor(ef, ["order_to_user.country"]).map(f => f.path)).toEqual(["status", "order_to_user.country"]);
    expect(fieldsFor(ef, ["status"])).toBe(ef.fields);
    expect(fieldsFor(ef, [null, undefined, "nonsense.x"])).toBe(ef.fields);
  });
});

describe("the pieces the picker adds (Arc AP-4)", () => {
  const CENTRE = { id: "distribution_center", segments: [], links: [],
    properties: [prop("id", "key", "INT64", "", true), prop("name", "dimension"), prop("latitude", "key", "FLOAT64"), prop("longitude", "flag", "FLOAT64")] };
  function app(): CockpitSpec {
    return {
      root: "cockpit",
      elements: {
        cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
        sec: { type: "Section", props: { title: "Desk" }, children: ["list", "map", "line", "pick", "find"] },
        list: { type: "ObjectList", props: { entity: "order" }, children: [] },
        map: { type: "ObjectMap", props: { entity: "distribution_center", lat: "latitude", lng: "longitude" }, children: [] },
        line: { type: "ObjectTimeline", props: { entity: "order", start: "created_at", end: "shipped_at" }, children: [] },
        pick: { type: "ChooseOne", props: { entity: "distribution_center", chooses: "chosen-centre", label: "name" }, children: [] },
        find: { type: "ObjectSearch", props: { entity: "order", path: "status", label: "Find orders" }, children: [] },
      },
    };
  }
  const offered = (label: string) => optionsOf(screen.getByLabelText(label)).map(o => o.value);
  beforeEach(() => {
    types.getObjectType.mockImplementation(async (t: string) => (t === "order" ? ORDER : t === "distribution_center" ? CENTRE : USER));
  });

  it("calls a list's cards by its key until a name is chosen, and offers money first beside them and categories under", async () => {
    const onChange = setUp(app(), "list");
    await waitFor(() => expect(screen.getByLabelText("Called by")).toBeInTheDocument());
    expect(screen.getByText(/Its key, beside what it is — “Order 63981”/)).toBeInTheDocument();
    expect(offered("Called by")).not.toContain("revenue");                        // a number is said beside, never as a name
    expect(offered("Called by")).not.toContain("created_at");
    expect(offered("Beside it")[1]).toBe("revenue");                              // after "Nothing": money first
    expect(offered("Marked by")).toEqual(["", "status", "gender", "num_of_item", "placed_by.country"]);   // the customer's too
    await choose(screen.getByLabelText("Called by"), "status");
    expect(onChange.mock.calls[0]).toEqual([expect.objectContaining({}), "an object list set up by hand"]);
    expect(onChange.mock.calls[0][0].elements.list.props.title).toBe("status");
    await choose(screen.getByLabelText("Sorted by"), "created_at");
    expect(onChange.mock.calls[1][0].elements.list.props).toMatchObject({ sort: "created_at", descending: false });
  });

  it("places a map by numbers only — a latitude the ontology calls a key among them — and a timeline between moments only", async () => {
    setUp(app(), "map");
    await waitFor(() => expect(screen.getByLabelText("Latitude")).toBeInTheDocument());
    expect(offered("Latitude")).toEqual(["latitude", "longitude"]);
    expect(offered("Called by")).toEqual(["", "name"]);
  });

  it("draws a timeline between the moments its objects hold, and nothing else", async () => {
    const onChange = setUp(app(), "line");
    await waitFor(() => expect(screen.getByLabelText("From")).toBeInTheDocument());
    expect(offered("From")).toEqual(["created_at", "shipped_at"]);
    await choose(screen.getByLabelText("To"), "created_at");
    expect(onChange.mock.calls[0][0].elements.line.props.end).toBe("created_at");
  });

  it("finds a choose-one's object by its words, names the choice it makes, and searches only what holds words", async () => {
    setUp(app(), "pick");
    await screen.findByTestId("setup-found-by");
    expect(offered("Found by")).toEqual(["name"]);
    expect(screen.getByTestId("setup-found-by")).toHaveTextContent("It chooses “chosen centre”");
  });

  it("looks for a search's words in a property that holds text — never a number, a moment or a key", async () => {
    const onChange = setUp(app(), "find");
    await screen.findByTestId("setup-looks-in");
    expect(offered("Looks in")).toEqual(["status", "gender", "placed_by.country"]);
    await choose(screen.getByLabelText("Looks in"), "gender");
    expect(onChange.mock.calls[0]).toEqual([expect.objectContaining({}), "what a search looks in chosen by hand"]);
    expect(onChange.mock.calls[0][0].elements.find.props.path).toBe("gender");
  });

  it("names a drawer, and opens it on an object a click chooses — never moved into a section", async () => {
    const spec = app();
    spec.elements.list.props.chooses = "chosen-order";
    spec.elements.cockpit.children.push("drawer");
    spec.elements.drawer = { type: "Drawer", props: { title: "The order", opens_on: "chosen-order" }, children: [] };
    const onChange = setUp(spec, "drawer");
    await screen.findByTestId("setup-opens-on");
    expect(offered("Opens on")).toEqual(["chosen-order", "chosen-centre"]);
    expect(screen.queryByLabelText("In the section")).toBeNull();
    await choose(screen.getByLabelText("Opens on"), "chosen-centre");
    expect(onChange.mock.calls[0]).toEqual([expect.objectContaining({}), "what opens a drawer chosen by hand"]);
    expect(onChange.mock.calls[0][0].elements.drawer.props.opens_on).toBe("chosen-centre");
  });

  it("wires a list's click and ticks, and a map's click only — a map holds no ticks", async () => {
    render(<PieceSetup spec={app()} selected="list" onChange={vi.fn()} connectionId={`conn-${++conn}`} wiringOn />);
    await screen.findByTestId("setup-chooses");
    expect(screen.getByTestId("setup-ticks")).toHaveTextContent("A tick beside each card");
    expect(screen.getByTestId("setup-reads")).toBeInTheDocument();
    render(<PieceSetup spec={app()} selected="map" onChange={vi.fn()} connectionId={`conn-${++conn}`} wiringOn />);
    await waitFor(() => expect(screen.getAllByTestId("setup-chooses")).toHaveLength(2));
    expect(screen.getAllByTestId("setup-ticks")).toHaveLength(1);
    expect(screen.getAllByTestId("setup-chooses")[1]).toHaveTextContent("Chooses a place for a detail that follows this piece.");
  });
});
