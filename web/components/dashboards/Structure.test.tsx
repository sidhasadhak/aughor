// @vitest-environment jsdom

/**
 * A structure of pieces, drawn and built (Arc AP-4; the user, 2026-10-11: "a widget based structure would be really
 * helpful"; design-mockups/cockpit-builder.html screens 5, 8 and 9). Sections laid out side by side by their widths, one
 * under another, or as tabs; an empty section that offers a piece or a split in the builder and is drawn as nothing for
 * a reader; the builder's split, copy and width, one twelfth at a time; and the piece picker, which places every piece
 * by hand with a first setup the rules accept — or says why it cannot. Every read is mocked.
 */
import { act, choose, cleanup, fireEvent, optionsOf, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardBuilder } from "@/components/dashboards/DashboardBuilder";
import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import { PiecePicker } from "@/components/dashboards/PiecePicker";
import type { DashboardSpec } from "@/lib/dashboards/edit";
import type { DashboardHostState } from "@/lib/dashboards/hostState";
import { checkDashboardSpec } from "@/lib/dashboards/rules";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getDeclaredActions: vi.fn(), getObjectPage: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const types = vi.hoisted(() => ({ getObjectType: vi.fn(), getProcesses: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const prop = (name: string, role: string, data_type = "STRING") =>
  ({ name, display_name: name.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase()), role, data_type, unit: "", is_key: name === "id", null_rate: 0, description: "", source: {} });
const ORDER = { id: "Order", object_type: "order", segments: [], links: [],
  properties: [prop("id", "key", "INT64"), prop("status", "dimension"), prop("created_at", "timestamp", "TIMESTAMP"), prop("num_of_item", "ordinal", "INT64")] };

beforeEach(() => {
  vi.clearAllMocks();
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Customer Order" }] });
  objects.getDeclaredActions.mockResolvedValue({ open_case: { id: "open_case", display_name: "Open a case", entity: "order", object_type: "order", params: [] } });
  objects.queryObjects.mockResolvedValue({ path: "compiled", columns: [], rows: [["12"]], caveats: [], error: null });
  objects.listObjects.mockResolvedValue({ path: "listed", object_type: "order", type_id: "Order", key: "id", title: "", segment_said: "",
    columns: [], names: ["id"], rows: [], total: 0, offset: 0, limit: 6, plan: [], caveats: [], error: null });
  types.getObjectType.mockResolvedValue(ORDER);
  types.getProcesses.mockResolvedValue({ processes: [{ id: "order_fulfilment", entity: "order", stages: [] }], rules: [] });
});

const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };

/** The desk split in two, side by side: the list's section, 8 wide, and an empty one, 4 wide. */
function split(): DashboardSpec {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["body"] },
      body: { type: "Section", props: { layout: "columns" }, children: ["left", "right"] },
      left: { type: "Section", props: { title: "Today", grid: 12, w: 8 }, children: ["note"] },
      right: { type: "Section", props: { title: "New section", grid: 12, w: 4 }, children: [] },
      note: { type: "Note", props: { text: "Oldest first", w: 6, h: 3 }, children: [] },
    },
  };
}

describe("a structure, drawn", () => {
  it("lays sections side by side by their widths, and draws an empty one as nothing for a reader", () => {
    expect(checkDashboardSpec(split()).issues).toEqual([]);
    render(<ComposedDashboard spec={split()} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" />);
    expect(screen.getByTestId("dashboard-layout")).toHaveAttribute("data-layout", "columns");
    expect(screen.getAllByTestId("dashboard-layout-cell").map(c => c.dataset.w)).toEqual(["8", "4"]);
    expect(screen.queryByTestId("dashboard-empty-section")).toBeNull();
    expect(screen.getByText("Oldest first")).toBeInTheDocument();
  });

  it("offers an empty section a piece or a split in the builder — each empty section by its own key", () => {
    const two = split();
    two.elements.left.children = [];
    delete two.elements.note;
    const onAddPiece = vi.fn(), onLayOut = vi.fn();
    render(<ComposedDashboard spec={two} cards={[]} host={HOST} connectionId="thelook"
      doors={{ onRefresh: vi.fn(), onSelect: vi.fn(), onAddPiece, onLayOut }} />);
    const empties = screen.getAllByTestId("dashboard-empty-section");
    expect(empties.map(e => e.dataset.key)).toEqual(["left", "right"]);
    fireEvent.click(within(empties[1]).getByTestId("empty-section-add"));
    expect(onAddPiece).toHaveBeenCalledWith("right");
    fireEvent.click(within(empties[0]).getByTestId("empty-section-split"));
    fireEvent.click(within(empties[0]).getByTestId("empty-section-tabs"));
    expect(onLayOut).toHaveBeenCalledWith("left", "tabs");
  });

  it("draws tabs called by their sections' titles, one at a time, the others kept drawn", () => {
    const tabs = split();
    tabs.elements.body.props = { layout: "tabs" };
    delete tabs.elements.left.props.w; delete tabs.elements.right.props.w;
    tabs.elements.right.children = ["note2"];
    tabs.elements.note2 = { type: "Note", props: { text: "The second tab", w: 6, h: 3 }, children: [] };
    render(<ComposedDashboard spec={tabs} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" />);
    const tab = screen.getAllByTestId("dashboard-layout-tab");
    expect(tab.map(t => t.textContent)).toEqual(["Today", "New section"]);
    expect(screen.getByText("The second tab").closest('[role="tabpanel"]')).toHaveAttribute("hidden");
    fireEvent.click(tab[1]);
    expect(screen.getByText("The second tab").closest('[role="tabpanel"]')).not.toHaveAttribute("hidden");
    expect(screen.getByText("Oldest first").closest('[role="tabpanel"]')).toHaveAttribute("hidden");
  });
});

describe("a structure, built", () => {
  function build(spec: DashboardSpec, structureOn = true) {
    const onChange = vi.fn(), onAddPiece = vi.fn();
    const view = render(
      <DashboardBuilder spec={spec} onChange={onChange} connectionId="thelook" bar={null} structureOn={structureOn} onAddPiece={structureOn ? onAddPiece : undefined}>
        {() => <div data-testid="dashboard-stub" />}
      </DashboardBuilder>,
    );
    const line = (key: string) => screen.getAllByTestId("builder-line").find(b => b.dataset.key === key)!;
    return { onChange, onAddPiece, line, view };
  }

  it("splits a chosen section to its right, hands the dashboard on in columns, and chooses the new section", () => {
    const { onChange, line } = build(split());
    fireEvent.click(line("left"));
    fireEvent.click(screen.getByTestId("builder-split-right"));
    const [next, note] = onChange.mock.calls[0];
    expect(note).toBe("split right by hand");
    expect(next.elements.body.children).toHaveLength(3);
    const fresh = next.elements.body.children[1];
    expect(next.elements[fresh].props).toEqual({ title: "New section", grid: 12, w: 4 });
    expect(next.elements.left.props.w).toBe(4);
  });

  it("steps a section's width among columns one twelfth at a time, and copies a section beside it", () => {
    const { onChange, line } = build(split());
    fireEvent.click(line("right"));
    expect(screen.getByTestId("builder-width")).toHaveTextContent("4");
    fireEvent.click(screen.getByRole("button", { name: "Width: one grade more" }));
    expect(onChange.mock.calls[0][0].elements.right.props.w).toBe(5);
    fireEvent.click(screen.getByTestId("builder-duplicate"));
    expect(onChange.mock.calls[1][0].elements.body.children).toEqual(["left", "right", "right-2"]);
  });

  it("opens the piece picker for the section chosen, or the one a chosen piece sits in", () => {
    const { onAddPiece, line } = build(split());
    fireEvent.click(line("note"));
    fireEvent.click(screen.getByTestId("builder-add-piece"));
    expect(onAddPiece).toHaveBeenLastCalledWith("left");
    fireEvent.click(line("right"));
    fireEvent.click(screen.getByTestId("builder-add-piece"));
    expect(onAddPiece).toHaveBeenLastCalledWith("right");
  });

  it("offers none of it while the structure is off", () => {
    const { line } = build(split(), false);
    fireEvent.click(line("left"));
    expect(screen.queryByTestId("builder-split-right")).toBeNull();
    expect(screen.queryByTestId("builder-duplicate")).toBeNull();
    expect(screen.queryByTestId("builder-add-piece")).toBeNull();
  });
});

describe("the piece picker", () => {
  const desk = (): DashboardSpec => ({
    ...split(),
    sets: { late: { label: "Shipped late", entity: "order", segment: "late_dispatch" } },
  });
  function pick(spec: DashboardSpec, section: string | null = "right") {
    const onPlace = vi.fn(), onHandOff = vi.fn(), onClose = vi.fn();
    render(<PiecePicker spec={spec} section={section} connectionId="thelook" wiringOn onPlace={onPlace} onHandOff={onHandOff} onClose={onClose} />);
    const entry = (kind: string) => screen.getAllByTestId("piece-picker-entry").find(e => e.dataset.kind === kind)!;
    return { onPlace, onHandOff, onClose, entry };
  }

  it("offers under each entity only its own sets — the customers a set of orders reaches are offered under Customer (Arc AP-8b)", async () => {
    objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Customer Order" },
      { object_type: "user", id: "User", display_name: "Customer" }] });
    const spec = desk();
    spec.sets!.theirs = { label: "Their customers", from: "late", traverse: { link: "placed_by", entity: "user" } };
    pick(spec);
    await waitFor(() => expect(optionsOf(screen.getByLabelText("What it reads")).map(o => o.value)).toEqual(["order", "user"]));
    expect(optionsOf(screen.getByLabelText("Which of them")).map(o => o.text)).toEqual(["Every one", "Shipped late"]);
    await choose(screen.getByLabelText("What it reads"), "user");
    await waitFor(() => expect(optionsOf(screen.getByLabelText("Which of them")).map(o => o.text)).toEqual(["Every one", "Their customers"]));
  });

  it("places a figure of the set chosen in the section, filling it, and names the section by it", async () => {
    const { onPlace, entry } = pick(desk());
    await choose(screen.getByLabelText("Which of them"), "late");
    fireEvent.click(entry("ObjectFigure"));
    const [next, note] = onPlace.mock.calls[0];
    expect(note).toBe("figure placed by hand");
    const key = next.elements.right.children[0];
    expect(next.elements[key]).toMatchObject({ type: "ObjectFigure", props: { set: "late", label: "Shipped late", agg: "count", w: 6 } });
    expect(next.elements.right.props.title).toBe("Shipped late");
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  it("places a chart across the entity's own date, and a table with its first properties", async () => {
    const { onPlace, entry } = pick(desk());
    await waitFor(() => expect(entry("ObjectChart")).not.toBeDisabled());
    fireEvent.click(entry("ObjectChart"));
    const chart = onPlace.mock.calls[0][0];
    const key = chart.elements.right.children[0];
    expect(chart.elements[key].props).toMatchObject({ entity: "order", time: "created_at", days: 14, label: "Customer Orders, by created at" });
    expect(checkDashboardSpec(chart).issues).toEqual([]);
  });

  it("says why a piece cannot be placed here, and does not place it", async () => {
    const filtered = desk();
    filtered.elements.cockpit.children = ["filters", "body"];
    filtered.elements.filters = { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] };
    const { onPlace, entry } = pick(filtered);
    expect(entry("ObjectFilters")).toBeDisabled();
    expect(entry("ObjectFilters")).toHaveTextContent("The dashboard has its filter column. It holds one.");
    expect(entry("ObjectDetail")).toHaveTextContent("A detail follows a table, a list, a map or a timeline. Place one first.");
    fireEvent.click(entry("ObjectDetail"));
    expect(onPlace).not.toHaveBeenCalled();
  });

  it("places the filter column as the dashboard's first child, counting within the set chosen", async () => {
    const { onPlace, entry } = pick(desk());
    await choose(screen.getByLabelText("Which of them"), "late");
    await waitFor(() => expect(entry("ObjectFilters")).not.toBeDisabled());
    fireEvent.click(entry("ObjectFilters"));
    const next = onPlace.mock.calls[0][0];
    const first = next.elements.cockpit.children[0];
    expect(next.elements[first]).toMatchObject({ type: "ObjectFilters", props: { entity: "order", set: "late", properties: [{ path: "status", label: "Status" }, { path: "num_of_item", label: "Num of item" }] } });
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  // Arc AP-4 — the pieces the picker adds, each with a first setup read from what the entity holds
  const CENTRE = { id: "DistributionCenter", object_type: "distribution_center", segments: [], links: [],
    properties: [prop("id", "key", "INT64"), prop("name", "dimension"), prop("latitude", "key", "FLOAT64"), prop("longitude", "flag", "FLOAT64")] };
  const ITEM = { id: "OrderItem", object_type: "order_item", segments: [], links: [],
    properties: [prop("id", "key", "INT64"), prop("order_id", "key", "INT64"), prop("created_at", "timestamp", "TIMESTAMP"),
      prop("shipped_at", "timestamp", "TIMESTAMP"), prop("sale_price", "measure", "FLOAT64")] };
  const byName = () => {
    objects.cachedObjectCatalog.mockResolvedValue({ object_types: [
      { object_type: "order", id: "Order", display_name: "Customer Order" },
      { object_type: "distribution_center", id: "DistributionCenter", display_name: "Distribution center" },
      { object_type: "order_item", id: "OrderItem", display_name: "Order item" }] });
    types.getObjectType.mockImplementation(async (name: string) => ({ distribution_center: CENTRE, order_item: ITEM }[name] ?? ORDER));
  };
  /** Reads the entity named, once the catalog offers it. */
  const reads = async (entity: string) => {
    const select = screen.getByLabelText("What it reads");
    await waitFor(() => expect(optionsOf(select).map(o => o.value)).toContain(entity));
    await choose(select, entity);
  };
  const placed = (onPlace: ReturnType<typeof vi.fn>, at = 0) => {
    const next = onPlace.mock.calls[at][0] as DashboardSpec;
    return { next, el: next.elements[next.elements.right.children[0]] };
  };

  it("places a map of what holds a latitude and a longitude — whatever role the ontology gives them — named by its name", async () => {
    byName();
    const { onPlace, entry } = pick(desk());
    await reads("distribution_center");
    await waitFor(() => expect(entry("ObjectMap")).not.toBeDisabled());
    fireEvent.click(entry("ObjectMap"));
    const { next, el } = placed(onPlace);
    expect(el).toMatchObject({ type: "ObjectMap", props: { entity: "distribution_center", lat: "latitude", lng: "longitude", label: "name" } });
    expect(next.elements.right.props.title).toBe("Distribution centers");
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  it("says why an order has no map, no timeline and no choose-one, and places its list and its search called by what it holds", async () => {
    byName();
    const { onPlace, entry } = pick(desk());
    await waitFor(() => expect(entry("ObjectList")).not.toBeDisabled());
    expect(entry("ObjectMap")).toHaveTextContent("Customer Order holds no latitude and longitude to place it by.");
    expect(entry("ObjectTimeline")).toHaveTextContent("Customer Order holds fewer than two moments to draw a bar between.");
    expect(entry("ChooseOne")).toHaveTextContent("Customer Order holds no name to find one by.");
    fireEvent.click(entry("ObjectList"));
    const list = placed(onPlace);
    // no name: its cards are called by their key; the newest first
    expect(list.el.props).toEqual({ entity: "order", figure: "num_of_item", mark: "status", sort: "created_at", descending: true, w: 12, h: 8 });
    expect(checkDashboardSpec(list.next).issues).toEqual([]);
    fireEvent.click(entry("ObjectSearch"));
    const search = placed(onPlace, 1);
    expect(search.el.props).toMatchObject({ entity: "order", path: "status", label: "Find customer orders" });
    expect(search.next.elements.right.props.title).toBe("Search");
    expect(checkDashboardSpec(search.next).issues).toEqual([]);
  });

  it("places a timeline between an object's own two moments, and a choose-one that names its choice", async () => {
    byName();
    const first = pick(desk());
    await reads("order_item");
    await waitFor(() => expect(first.entry("ObjectTimeline")).not.toBeDisabled());
    fireEvent.click(first.entry("ObjectTimeline"));
    expect(placed(first.onPlace).el.props).toMatchObject({ entity: "order_item", start: "created_at", end: "shipped_at" });
    expect(checkDashboardSpec(placed(first.onPlace).next).issues).toEqual([]);
    await reads("distribution_center");
    await waitFor(() => expect(first.entry("ChooseOne")).not.toBeDisabled());
    fireEvent.click(first.entry("ChooseOne"));
    const chooser = placed(first.onPlace, 1);
    expect(chooser.el.props).toMatchObject({ entity: "distribution_center", chooses: "chosen-distribution-center", label: "name" });
    expect(chooser.next.elements.right.props.title).toBe("Choose a distribution center");
    expect(checkDashboardSpec(chooser.next).issues).toEqual([]);
  });

  it("places what a chosen object links to: a set of an order's lines and a table of it", async () => {
    byName();
    const chosen = desk();
    chosen.elements.left.children.push("orders");
    chosen.elements.orders = { type: "ObjectTable", props: { entity: "order", chooses: "chosen-order", w: 6, h: 8 }, children: [] };
    const { onPlace, entry } = pick(chosen);
    expect(entry("Linked")).toBeDisabled();
    await reads("order_item");
    await waitFor(() => expect(entry("Linked")).not.toBeDisabled());
    fireEvent.click(entry("Linked"));
    const { next, el } = placed(onPlace);
    expect(next.sets!["order-items-of-the-chosen-order"]).toEqual({ label: "Order items of the chosen order", entity: "order_item",
      linked_to: { choice: "chosen-order", path: "order_id" } });
    expect(el).toMatchObject({ type: "ObjectTable", props: { set: "order-items-of-the-chosen-order" } });
    expect(next.elements.right.props.title).toBe("Order items of the chosen order");
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  it("names a linked set between words — the chosen giving way before a word is cut", async () => {
    byName();
    const PRODUCT = { id: "Product", object_type: "product", segments: [], links: [],
      properties: [prop("id", "key", "INT64"), prop("name", "text"), prop("distribution_center_id", "key", "INT64")] };
    objects.cachedObjectCatalog.mockResolvedValue({ object_types: [
      { object_type: "distribution_center", id: "DistributionCenter", display_name: "Distribution center" },
      { object_type: "product", id: "Product", display_name: "Product" }] });
    types.getObjectType.mockImplementation(async (name: string) => ({ distribution_center: CENTRE, product: PRODUCT }[name] ?? ORDER));
    const s = desk();
    s.elements.left.children.push("centres");
    s.elements.centres = { type: "ObjectTable", props: { entity: "distribution_center", chooses: "chosen-distribution-center", w: 6, h: 8 }, children: [] };
    const { onPlace, entry } = pick(s);
    await reads("product");
    await waitFor(() => expect(entry("Linked")).not.toBeDisabled());
    fireEvent.click(entry("Linked"));
    const next = onPlace.mock.calls[0][0] as DashboardSpec;
    expect(Object.values(next.sets!).map(x => x.label)).toContain("Products of the distribution center");
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  it("offers neither a choose-one nor linked objects while the dashboard cannot be wired, and says so", async () => {
    byName();
    render(<PiecePicker spec={desk()} section="right" connectionId="thelook" wiringOn={false} onPlace={vi.fn()} onHandOff={vi.fn()} onClose={vi.fn()} />);
    const entry = (kind: string) => screen.getAllByTestId("piece-picker-entry").find(e => e.dataset.kind === kind)!;
    await waitFor(() => expect(entry("ObjectList")).not.toBeDisabled());
    expect(entry("ChooseOne")).toHaveTextContent("Choosing one for the pieces that follow it needs wiring, which is off here.");
    expect(entry("Linked")).toHaveTextContent("Linking to a chosen object needs wiring, which is off here.");
  });

  it("places a detail following a list by its key when the dashboard holds no table", async () => {
    byName();
    const listed = desk();
    listed.elements.left.children.push("queue");
    listed.elements.queue = { type: "ObjectList", props: { entity: "order", w: 6, h: 8 }, children: [] };
    const { onPlace, entry } = pick(listed);
    fireEvent.click(entry("ObjectDetail"));
    const { next, el } = placed(onPlace);
    expect(el).toMatchObject({ type: "ObjectDetail", props: { follows: "queue" } });
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  const ordersChosen = () => {
    const s = desk();
    s.elements.left.children.push("orders");
    s.elements.orders = { type: "ObjectTable", props: { entity: "order", chooses: "chosen-order", w: 6, h: 8 }, children: [] };
    return s;
  };

  it("opens the chosen one in a drawer beside the page, holding its detail", async () => {
    byName();
    const { onPlace, entry } = pick(ordersChosen());
    fireEvent.click(entry("Drawer"));
    const next = onPlace.mock.calls[0][0] as DashboardSpec;
    const key = next.elements.cockpit.children.at(-1)!;
    expect(next.elements[key]).toMatchObject({ type: "Drawer", props: { title: "The order", opens_on: "chosen-order" } });
    expect(next.elements[next.elements[key].children[0]]).toMatchObject({ type: "ObjectDetail", props: { follows: "chosen-order" } });
    expect(checkDashboardSpec(next).issues).toEqual([]);
  });

  it("offers no second drawer for a choice that opens one, and none inside a drawer", async () => {
    byName();
    const s = ordersChosen();
    s.elements.cockpit.children.push("drawer");
    s.elements.drawer = { type: "Drawer", props: { title: "The order", opens_on: "chosen-order" }, children: [] };
    const { entry } = pick(s, "drawer");
    expect(entry("Drawer")).toHaveTextContent("A drawer opens beside the page. It holds pieces, not a drawer.");
    expect(entry("ObjectTable")).not.toHaveTextContent("There is no section");
  });

  it("offers no second drawer on a choice that opens one already", async () => {
    byName();
    const s = ordersChosen();
    s.elements.cockpit.children.push("drawer");
    s.elements.drawer = { type: "Drawer", props: { title: "The order", opens_on: "chosen-order" }, children: [] };
    const { entry } = pick(s);
    expect(entry("Drawer")).toHaveTextContent("Each chosen object opens its drawer already.");
  });

  it("offers a query of your own only where queries are on, and hands it to the page for the same section (Arc AP-7)", async () => {
    const { onHandOff, entry } = pick(desk());
    expect(screen.getAllByTestId("piece-picker-entry").some(e => e.dataset.kind === "query")).toBe(false);
    cleanup();
    const handed = vi.fn();
    render(<PiecePicker spec={desk()} section="right" connectionId="thelook" wiringOn queriesOn onPlace={vi.fn()} onHandOff={handed} onClose={vi.fn()} />);
    const query = screen.getAllByTestId("piece-picker-entry").find(e => e.dataset.kind === "query")!;
    expect(query).toHaveTextContent("Your own query");
    fireEvent.click(query);
    expect(handed).toHaveBeenCalledWith("query", "right");
    expect(onHandOff).not.toHaveBeenCalled();
    void entry;
    await act(async () => {});
  });

  it("hands a note, a card, an image or a finding to the page's own composer, for the same section", async () => {
    const { onHandOff, entry } = pick(desk());
    fireEvent.click(entry("note"));
    expect(onHandOff).toHaveBeenCalledWith("note", "right");
    await act(async () => {});
  });
});
