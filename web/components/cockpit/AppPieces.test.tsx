// @vitest-environment jsdom

/**
 * The pieces the picker adds, drawn (Arc AP-4; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4) — through the cockpit's
 * own renderer, the object door mocked. The door here lists the columns asked for in the reverse order, so a piece that
 * reads a property by its place among its props, not by its path, says the wrong thing and fails. A list's cards say each
 * object by the properties named, or "Order 101" by its key; a sort the cards do not show is asked for beside them; a map
 * places only what has coordinates and says what it left out; a timeline's open bar runs to today; a choose-one finds at
 * the door by the words typed and keeps the chosen one's name; a search narrows every piece over its entity; and a detail
 * follows a click in any of them — by the piece's key, even once that piece names its choice.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedCockpit } from "@/components/cockpit/ComposedCockpit";
import type { CockpitHostState } from "@/lib/cockpit/hostState";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
// the map's Vega is a canvas jsdom cannot draw: what the piece hands it is what is asserted
const vega = vi.hoisted(() => ({ calls: [] as { spec: Record<string, unknown>; onSelect?: (d: Record<string, unknown>) => void }[] }));
vi.mock("@/components/charts/vega/VegaChart", () => ({
  VegaChart: (p: { spec: Record<string, unknown>; onSelect?: (d: Record<string, unknown>) => void }) => {
    vega.calls.push(p);
    return <div data-testid="vega-stub" />;
  },
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const HOST: CockpitHostState = { range: { status: "standing" }, cards: {} };

type Row = Record<string, string | number | null>;
const DATA: Record<string, Record<string, Row>> = {
  distribution_center: {
    1: { name: "Memphis TN", latitude: 35.1174, longitude: -89.9711 },
    2: { name: "Chicago IL", latitude: 41.8369, longitude: -87.6847 },
    3: { name: "Nowhere", latitude: null, longitude: null },
  },
  order: {
    101: { status: "Processing", created_at: "2026-10-01 10:00:00+00", shipped_at: null, revenue: 25, gender: "F" },
    102: { status: "Shipped", created_at: "2026-09-28 10:00:00+00", shipped_at: "2026-09-30 10:00:00+00", revenue: 1250.5, gender: "M" },
  },
};
const TYPE: Record<string, [string, string, string]> = {              // type, unit, role
  latitude: ["FLOAT64", "", "key"], longitude: ["FLOAT64", "", "flag"], name: ["STRING", "", "dimension"],
  status: ["STRING", "", "dimension"], gender: ["STRING", "", "dimension"], revenue: ["FLOAT64", "USD", "measure"],
  created_at: ["TIMESTAMP", "", "timestamp"], shipped_at: ["TIMESTAMP", "", "timestamp"],
};

type Asked = { entity: string; columns?: string[]; order_by?: string; descending?: boolean; filters?: { path: string; op: string; value: unknown }[] };
/** The door: the objects whose properties hold the words a `contains` looks for, each column asked for — in reverse. */
function listing(b: Asked) {
  const columns = [...(b.columns ?? [])].reverse().map(path => ({
    name: path, path, label: path, type: TYPE[path]?.[0] ?? "STRING", unit: TYPE[path]?.[1] ?? "", role: TYPE[path]?.[2] ?? "", edited: false,
  }));
  const holds = (r: Row) => (b.filters ?? []).every(f => f.op !== "contains" || String(r[f.path] ?? "").toLowerCase().includes(String(f.value).toLowerCase()));
  const rows = Object.entries(DATA[b.entity] ?? {}).filter(([, r]) => holds(r)).map(([pk, r]) => [pk, ...columns.map(c => r[c.path] ?? null)]);
  return { path: "listed", object_type: b.entity, type_id: b.entity, key: "id", title: "", segment_said: "", columns,
    names: ["id", ...columns.map(c => c.name)], rows, total: rows.length, offset: 0, limit: 50, plan: [], caveats: [], error: null };
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vega.calls = [];
  objects.listObjects.mockImplementation(async (b: Asked) => listing(b));
  objects.queryObjects.mockResolvedValue({ path: "compiled", columns: [], rows: [["2"]], caveats: [], error: null });
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [] });
  objects.getDeclaredActions.mockResolvedValue({});
  objects.getObjectPage.mockImplementation(async (type: string, pk: string) => ({
    path: "object", object_type: type, type_id: type, type_name: type, pk, key: "id", title: `${type} ${pk}`,
    properties: [{ name: "id", display_name: "Id", value: pk }], links: [], actions: [],
  }));
});

/** A cockpit of one section holding the elements given, by key. */
function desk(elements: Record<string, { type: string; props: Record<string, unknown>; children?: string[] }>) {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["desk"] },
      desk: { type: "Section", props: { title: "Desk" }, children: Object.keys(elements).filter(k => !Object.values(elements).some(e => e.children?.includes(k))) },
      ...Object.fromEntries(Object.entries(elements).map(([k, e]) => [k, { children: [], ...e }])),
    },
  };
}
const draw = (spec: unknown) => render(
  <ComposedCockpit spec={spec} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" cockpitId="thelook:desk" />);
const listed = () => objects.listObjects.mock.calls.map(c => c[0] as Asked);
const lastVega = () => vega.calls.at(-1)!;

describe("an object list", () => {
  it("says each object by the properties named, found by path — its key when it names no title — and chooses on a click", async () => {
    draw(desk({
      list: { type: "ObjectList", props: { entity: "order", figure: "revenue", mark: "status", sort: "gender", descending: true } },
      detail: { type: "ObjectDetail", props: { follows: "list" } },
    }));
    await waitFor(() => expect(screen.getAllByTestId("object-list-card")).toHaveLength(2));
    const [first] = screen.getAllByTestId("object-list-card");
    expect(first).toHaveTextContent("Order 101");
    expect(screen.getByTestId("object-list")).toHaveTextContent(/^Orders/);
    expect(within(first).getByTestId("object-list-figure")).toHaveTextContent("$25.00");
    expect(within(first).getByTestId("object-list-mark")).toHaveTextContent("Processing");
    // the door sorts by a listed property only: the sort the cards do not show is asked for beside them
    expect(listed()[0]).toMatchObject({ entity: "order", columns: ["revenue", "status", "gender"], order_by: "gender", descending: true });
    fireEvent.click(first);
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("order", "101", "thelook", undefined));
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();
  });
});

describe("a map", () => {
  it("places each object by its coordinates, found by path, leaves out one with none and says so, and chooses on a click", async () => {
    draw(desk({
      map: { type: "ObjectMap", props: { entity: "distribution_center", lat: "latitude", lng: "longitude", label: "name" } },
      detail: { type: "ObjectDetail", props: { follows: "map" } },
    }));
    await waitFor(() => expect(screen.getByTestId("vega-stub")).toBeInTheDocument());
    const layer = (lastVega().spec.layer as { data: { values?: { pk: string; lat: number; lng: number; name: string; chosen: boolean }[] } }[])[1];
    expect(layer.data.values!.map(p => [p.pk, p.name, p.lat, p.lng])).toEqual([["1", "Memphis TN", 35.1174, -89.9711], ["2", "Chicago IL", 41.8369, -87.6847]]);
    // an empty coordinate is no place — never 0, 0 off Africa — and the reader is told it was not drawn
    expect(screen.getByTestId("object-map-total")).toHaveTextContent("2 placed");
    expect(screen.getByTestId("object-map")).toHaveTextContent(/^Distribution centers/);   // the ontology's name, never "distribution_center"
    expect(screen.getByText(/1 with no coordinates are not drawn/)).toBeInTheDocument();
    const fit = (lastVega().spec.projection as { fit?: { geometry: { coordinates: number[][] } } }).fit;
    expect(fit?.geometry.coordinates).toHaveLength(4);
    // with the charts' autosize "fit", a fitted projection collapses every place to (0, 0) — measured in Vega itself
    expect(lastVega().spec.autosize).toEqual({ type: "none" });
    lastVega().onSelect!({ pk: "2" });
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("distribution_center", "2", "thelook", undefined));
    await waitFor(() => expect((lastVega().spec.layer as { data: { values?: { pk: string; chosen: boolean }[] } }[])[1].data.values!.find(p => p.pk === "2")!.chosen).toBe(true));
  });
});

describe("what an object is called", () => {
  it("is its key as it is when the key says its type already — a case, never \"Case case-…\"", async () => {
    DATA.case = { "case-7530088c": { status: "resolved" } };
    draw(desk({ queue: { type: "ObjectList", props: { entity: "case", mark: "status" } } }));
    await waitFor(() => expect(screen.getAllByTestId("object-list-card")).toHaveLength(1));
    expect(screen.getByTestId("object-list-card")).toHaveTextContent(/^case-7530088c/);
    delete DATA.case;
  });
});

describe("a timeline", () => {
  it("draws each object from one moment to the next, the latest first, an open one to today, and says so", async () => {
    draw(desk({ line: { type: "ObjectTimeline", props: { entity: "order", start: "created_at", end: "shipped_at" } } }));
    await waitFor(() => expect(screen.getAllByTestId("object-timeline-lane")).toHaveLength(2));
    expect(listed()[0]).toMatchObject({ columns: ["created_at", "shipped_at"], order_by: "created_at", descending: true });
    const [open, shut] = screen.getAllByTestId("object-timeline-lane");
    expect(open).toHaveTextContent("Order 101");
    expect(open).toHaveAttribute("data-open", "true");
    expect(shut).not.toHaveAttribute("data-open");
    expect(shut.querySelector("title")?.textContent).toBe("Order 102: Sep 28 – Sep 30");
    expect(screen.getByText(/A bar still open runs to today/)).toBeInTheDocument();
  });
});

describe("choose one", () => {
  it("finds at the door by the words typed, chooses for the pieces that follow, and keeps the chosen one's name", async () => {
    draw(desk({
      pick: { type: "ChooseOne", props: { entity: "distribution_center", chooses: "chosen-centre", label: "name" } },
      detail: { type: "ObjectDetail", props: { follows: "chosen-centre" } },
    }));
    await waitFor(() => expect(screen.getAllByTestId("choose-one-option")).toHaveLength(3));
    fireEvent.change(screen.getByRole("textbox", { name: /Find/ }), { target: { value: "chi" } });
    await waitFor(() => expect(screen.getAllByTestId("choose-one-option").map(b => b.textContent)).toEqual(["Chicago IL"]));
    expect(listed().at(-1)!.filters).toContainEqual({ path: "name", op: "contains", value: "chi" });
    fireEvent.click(screen.getByText("Chicago IL"));
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("distribution_center", "2", "thelook", undefined));
    fireEvent.change(screen.getByRole("textbox", { name: /Find/ }), { target: { value: "mem" } });
    await waitFor(() => expect(screen.getAllByTestId("choose-one-option").map(b => b.textContent)).toEqual(["Memphis TN"]));
    expect(screen.getByTestId("choose-one-chosen")).toHaveTextContent("Chicago IL");
    expect(screen.getByTestId("choose-one")).toHaveTextContent(/^Choose a distribution center/);   // the title stays while one is chosen
  });
});

describe("search", () => {
  it("narrows every piece over its entity to the objects whose property holds the words, once they settle", async () => {
    draw(desk({
      find: { type: "ObjectSearch", props: { entity: "order", path: "status", label: "Find orders" } },
      list: { type: "ObjectList", props: { entity: "order", title: "status" } },
    }));
    await waitFor(() => expect(screen.getAllByTestId("object-list-card")).toHaveLength(2));
    fireEvent.change(screen.getByRole("textbox", { name: "Find orders" }), { target: { value: "ship" } });
    await waitFor(() => expect(screen.getAllByTestId("object-list-card")).toHaveLength(1));
    expect(listed().at(-1)).toMatchObject({ entity: "order", filters: [{ path: "status", op: "contains", value: "ship" }] });
    expect(screen.getByTestId("object-search")).toHaveTextContent("holds “ship”");
  });
});

describe("a detail", () => {
  it("follows a table by its key even once the table names its choice — the click lands under the name", async () => {
    draw(desk({
      table: { type: "ObjectTable", props: { entity: "order", chooses: "chosen-order", columns: ["status"] } },
      detail: { type: "ObjectDetail", props: { follows: "table" } },
    }));
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(screen.getAllByTestId("object-table-row")[1]);
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("order", "102", "thelook", undefined));
  });
});

describe("what a piece waiting on a choice says", () => {
  it("names where the choice is made — on a map — and what the set holds, said once", async () => {
    draw({
      root: "cockpit",
      sets: { held: { label: "Products of the chosen centre", entity: "order", linked_to: { choice: "chosen-centre", path: "status" } } },
      elements: {
        cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["desk"] },
        desk: { type: "Section", props: { title: "Desk" }, children: ["map", "products"] },
        map: { type: "ObjectMap", props: { entity: "distribution_center", chooses: "chosen-centre", lat: "latitude", lng: "longitude" }, children: [] },
        products: { type: "ObjectTable", props: { set: "held", columns: ["status"] }, children: [] },
      },
    });
    await waitFor(() => expect(screen.getByTestId("object-table-waiting")).toHaveTextContent(
      "Choose a distribution center on its map to see its products here."));
  });
});

describe("a drawer", () => {
  const drawn = () => ({
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["desk", "drawer"] },
      desk: { type: "Section", props: { title: "Desk" }, children: ["list"] },
      list: { type: "ObjectList", props: { entity: "order", chooses: "chosen-order", title: "status" }, children: [] },
      drawer: { type: "Drawer", props: { title: "The order", opens_on: "chosen-order" }, children: ["detail"] },
      detail: { type: "ObjectDetail", props: { follows: "chosen-order" }, children: [] },
    },
  });

  it("opens beside the page on a click that chooses, and closes — letting go — on its close or on Escape", async () => {
    draw(drawn());
    await waitFor(() => expect(screen.getAllByTestId("object-list-card")).toHaveLength(2));
    expect(screen.queryByTestId("cockpit-drawer")).toBeNull();
    fireEvent.click(screen.getAllByTestId("object-list-card")[1]);
    const drawer = await screen.findByTestId("cockpit-drawer");
    expect(drawer).toHaveAttribute("role", "dialog");
    expect(drawer).toHaveAccessibleName("The order");
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("order", "102", "thelook", undefined));
    fireEvent.click(screen.getByTestId("cockpit-drawer-close"));
    await waitFor(() => expect(screen.queryByTestId("cockpit-drawer")).toBeNull());
    expect(screen.getAllByTestId("object-list-card")[1]).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getAllByTestId("object-list-card")[0]);
    await screen.findByTestId("cockpit-drawer");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("cockpit-drawer")).toBeNull());
  });

  it("is drawn open in the builder, after the page, offering a piece", async () => {
    const onAddPiece = vi.fn();
    render(<ComposedCockpit spec={drawn()} cards={[]} host={HOST} doors={{ onRefresh: vi.fn(), onSelect: vi.fn(), onAddPiece }} connectionId="thelook" />);
    const drawer = await screen.findByTestId("cockpit-drawer");
    expect(drawer).toHaveAttribute("data-editing", "true");
    expect(drawer).toHaveTextContent("opens beside the page when “chosen order” is chosen");
    expect(within(drawer).getByTestId("object-detail")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByTestId("drawer-add"));
    expect(onAddPiece).toHaveBeenCalledWith("drawer");
  });
});
