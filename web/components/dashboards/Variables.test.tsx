// @vitest-environment jsdom

/**
 * Variables on a dashboard, drawn (Arc AP-8; design-mockups/cockpit-builder.html screens 11–12). Through the dashboard's own
 * renderer with the object door and the card run mocked: a value the reader sets is a control on the page, kept in their
 * browser; every set that reads it, and every query of the person's own that reads it, is read again with it; a value
 * counted from a set is counted at the object door, and one read off the object a reader chose waits until one is
 * chosen. What cannot be read says why, in its place — never a zero, never "reading" for ever.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { CardRunResult, DashboardCard } from "@/lib/api";
import type { DashboardHostState } from "@/lib/dashboards/hostState";
import type { ObjectQueryRequest } from "@/lib/objects";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const api = vi.hoisted(() => ({ runCard: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };
const KEY = "aughor:cockpit-values:thelook:sales";

const SPEC = {
  root: "cockpit",
  values: {
    window: { label: "Window", kind: "days", value: 14, from: { by: "reader", options: [7, 14, 30, 90] } },
    country: { label: "Country", kind: "text", value: "China", from: { by: "reader" } },
    status: { label: "Its status", kind: "text", from: { by: "chosen", choice: "chosen-order", path: "status" } },
    "placed-count": { label: "Placed count", kind: "number", from: { by: "count", set: "placed" } },
  },
  sets: {
    placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
    "in-country": { label: "Placed in the country", from: "placed", where: [{ path: "user.country", op: "=", value_from: "country" }] },
    like: { label: "Like the chosen", entity: "order", where: [{ path: "status", op: "=", value_from: "status" }] },
    many: { label: "Many items", entity: "order", where: [{ path: "num_of_item", op: ">=", value_from: "placed-count" }] },
  },
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Sales desk" }, children: ["sec"] },
    sec: { type: "Section", props: { title: "Sales" }, children: ["table", "like", "many", "q"] },
    table: { type: "ObjectTable", props: { set: "in-country", chooses: "chosen-order", columns: ["status"] }, children: [] },
    like: { type: "ObjectTable", props: { set: "like", columns: ["status"] }, children: [] },
    many: { type: "ObjectTable", props: { set: "many", columns: ["status"] }, children: [] },
    q: { type: "Card", props: { card: "q1" }, children: [] },
  },
};
const QUERY = "SELECT SUM(sale_price) AS sales FROM orders WHERE country = {{country}} AND created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL {{window}} DAY)";
const card = (sql = QUERY) => ({
  id: "q1", title: "Sales in the country", kind: "kpi", own: true, connection_id: "thelook", scope: "user", scope_ref: "default", source: "authored",
  sql, thresholds: {}, provenance: {}, links: [],
  render: { shown: { as: "figure", summed: true, series: [{ column: "sales", agg: "sum" }], label: "" }, columns: [{ name: "sales", type: "DOUBLE" }] },
  refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] },
}) as unknown as DashboardCard;
const figureRun = (value: number): CardRunResult => ({ columns: [], rows: [], row_count: 0, caveats: [], error: null, value, duration_ms: 812,
  refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] },
  shown: { as: "figure", value, label: "Sales", said: [] } } as unknown as CardRunResult);

const listing = (b: { entity: string }) => ({
  path: "listed", object_type: b.entity, type_id: "Order", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }], names: ["id", "status"],
  rows: [["38330", "Processing"], ["79251", "Shipped"]], total: 2, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => ({ path: "compiled", columns: [], rows: [[b.object_type === "order" ? "6619" : "0"]], caveats: [], error: null }));
  objects.listObjects.mockImplementation(async (b: { entity: string }) => listing(b));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
  objects.getDeclaredActions.mockResolvedValue({});
  objects.getObjectPage.mockImplementation(async (_t: string, pk: string) => ({
    path: "object", object_type: "order", type_id: "Order", type_name: "Order", pk, key: "id", title: `Order ${pk}`,
    properties: [{ name: "id", display_name: "Order Id", value: pk }, { name: "status", display_name: "Status", value: pk === "38330" ? "Processing" : "Shipped" }],
    links: [], actions: [],
  }));
  api.runCard.mockImplementation(async (_id: string, _r: unknown, opts: { values?: Record<string, { value: unknown }> }) =>
    figureRun(opts.values?.country?.value === "Brasil" ? 92197 : 203868));
});

const draw = (spec: unknown = SPEC, cards = [{ card: card() }]) => render(
  <ComposedDashboard spec={spec} cards={cards} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" dashboardId="thelook:sales" />);
const listedFor = (path: string) => objects.listObjects.mock.calls.map(c => c[0] as { filters: { path: string; op: string; value?: unknown }[] })
  .map(b => b.filters.find(f => f.path === path)).filter(Boolean);
const runs = () => api.runCard.mock.calls.map(c => (c[2] as { values?: unknown }).values);
const value = (name: string) => screen.getAllByTestId("dashboard-value").find(v => v.getAttribute("data-name") === name) as HTMLElement;
const tables = () => screen.getAllByTestId("object-table");

describe("a value the reader sets", () => {
  it("is a control on the page — choices side by side, or a box — and each set and query that reads it is read again", async () => {
    draw();
    expect(within(value("window")).getByRole("radio", { name: "14" })).toHaveAttribute("aria-checked", "true");
    expect(within(value("country")).getByRole("textbox", { name: "Country" })).toHaveValue("China");
    expect(screen.getAllByTestId("dashboard-value").map(v => v.getAttribute("data-name"))).toEqual(["window", "country"]);   // only the reader's
    await waitFor(() => expect(listedFor("created_at").at(-1)).toEqual({ path: "created_at", op: "in_last", value: 14 }));
    expect(listedFor("user.country").at(-1)).toEqual({ path: "user.country", op: "=", value: "China" });
    await waitFor(() => expect(runs().at(-1)).toEqual({ country: { kind: "text", value: "China" }, window: { kind: "days", value: 14 } }));
    await waitFor(() => expect(screen.getByTestId("query-tile-figure")).toHaveTextContent("203,868"));

    fireEvent.click(within(value("window")).getByRole("radio", { name: "30" }));
    await waitFor(() => expect(listedFor("created_at").at(-1)).toEqual({ path: "created_at", op: "in_last", value: 30 }));
    await waitFor(() => expect(runs().at(-1)).toEqual({ country: { kind: "text", value: "China" }, window: { kind: "days", value: 30 } }));
    expect(JSON.parse(localStorage.getItem(KEY) ?? "{}")).toEqual({ window: 30 });                // the reader's browser, theirs

    const box = within(value("country")).getByRole("textbox", { name: "Country" });
    fireEvent.change(box, { target: { value: "Brasil" } });
    fireEvent.blur(box);
    await waitFor(() => expect(listedFor("user.country").at(-1)).toEqual({ path: "user.country", op: "=", value: "Brasil" }));
    await waitFor(() => expect(screen.getByTestId("query-tile-figure")).toHaveTextContent("92,197"));

    fireEvent.click(within(value("window")).getByTestId("dashboard-value-reset"));
    await waitFor(() => expect(listedFor("created_at").at(-1)).toEqual({ path: "created_at", op: "in_last", value: 14 }));
    expect(JSON.parse(localStorage.getItem(KEY) ?? "{}")).toEqual({ country: "Brasil" });
    expect(within(value("window")).queryByTestId("dashboard-value-reset")).toBeNull();
  });

  it("takes only a value of its kind, and says what it takes — nothing is read again for one it does not", async () => {
    draw();
    await waitFor(() => expect(runs()).toHaveLength(1));
    const box = within(value("country")).getByRole("textbox", { name: "Country" });
    fireEvent.change(box, { target: { value: "   " } });
    fireEvent.blur(box);
    expect(within(value("country")).getByTestId("dashboard-value-wrong")).toHaveTextContent("Some words, at most 120.");
    expect(runs()).toHaveLength(1);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("is the author's again when what the reader's browser remembers is no longer a choice offered", async () => {
    localStorage.setItem(KEY, JSON.stringify({ window: 60, country: "Japan" }));
    draw();
    await waitFor(() => expect(listedFor("created_at").at(-1)).toEqual({ path: "created_at", op: "in_last", value: 14 }));
    expect(listedFor("user.country").at(-1)).toEqual({ path: "user.country", op: "=", value: "Japan" });
  });

  it("draws nothing on a dashboard whose values are all its author's, and its pieces ask the door as before", async () => {
    const plain = { root: "cockpit", values: { window: { label: "Window", kind: "days", value: 14 } }, sets: { placed: SPEC.sets.placed },
      elements: { cockpit: SPEC.elements.cockpit, sec: { ...SPEC.elements.sec, children: ["table"] },
        table: { type: "ObjectTable", props: { set: "placed", columns: ["status"] }, children: [] } } };
    draw(plain, []);
    await waitFor(() => expect(objects.listObjects).toHaveBeenCalled());
    expect(screen.queryByTestId("dashboard-values")).toBeNull();
    expect(objects.listObjects.mock.calls[0][0]).toMatchObject({ entity: "order", filters: [{ path: "created_at", op: "in_last", value: 14 }] });
    expect(api.runCard).not.toHaveBeenCalled();
  });
});

describe("a value counted, or read off the object chosen", () => {
  it("counts its set at the object door and compares the sets that read it with the count", async () => {
    draw();
    await waitFor(() => expect(objects.queryObjects).toHaveBeenCalledWith(
      { object_type: "order", measures: [{ name: "n", agg: "count" }], filters: [{ path: "created_at", op: "in_last", value: 14 }] }, "thelook", undefined));
    await waitFor(() => expect(listedFor("num_of_item").at(-1)).toEqual({ path: "num_of_item", op: ">=", value: 6619 }));
  });

  it("says why when the count cannot be read, in the place of what reads it", async () => {
    objects.queryObjects.mockImplementation(async () => ({ path: "refused", refused: "Order is not served here.", available: [] }));
    draw();
    await waitFor(() => expect(screen.getByText(/reads the value "placed-count", which cannot be read: Order is not served here\./)).toBeInTheDocument());
  });

  it("waits until one is chosen, then reads its property off the object's page", async () => {
    draw();
    await waitFor(() => expect(within(tables()[1]).getByTestId("object-table-waiting")).toHaveTextContent("Choose an order in its table"));
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[1]);
    await waitFor(() => expect(objects.getObjectPage).toHaveBeenCalledWith("order", "79251", "thelook", undefined));
    await waitFor(() => expect(listedFor("status").at(-1)).toEqual({ path: "status", op: "=", value: "Shipped" }));
  });

  it("says a property withheld from the reader is withheld, never reading it as nothing", async () => {
    objects.getObjectPage.mockImplementation(async (_t: string, pk: string) => ({
      path: "object", object_type: "order", type_id: "Order", type_name: "Order", pk, key: "id", title: `Order ${pk}`, links: [], actions: [],
      properties: [{ name: "status", display_name: "Status", value: null, withheld: "only support reads it" }],
    }));
    draw();
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    await waitFor(() => expect(screen.getByText(/which cannot be read: Status is withheld from you: only support reads it/)).toBeInTheDocument());
    expect(listedFor("status")).toEqual([]);
  });
});

describe("a query of the person's own that reads values", () => {
  it("waits on the choice a value it reads waits on, then runs with what the object holds", async () => {
    draw(SPEC, [{ card: card("SELECT COUNT(*) AS n FROM orders WHERE status = {{status}}") }]);
    await waitFor(() => expect(screen.getByTestId("query-tile-waiting")).toHaveTextContent("Choose an order in its table — this reads Its status from it."));
    expect(api.runCard).not.toHaveBeenCalled();
    await waitFor(() => expect(within(tables()[0]).getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(within(tables()[0]).getAllByTestId("object-table-row")[0]);
    await waitFor(() => expect(runs().at(-1)).toEqual({ status: { kind: "text", value: "Processing" } }));
  });

  it("says in its place why it cannot run when it reads a value the dashboard does not hold, and asks nothing", async () => {
    draw(SPEC, [{ card: card("SELECT 1 WHERE x = {{nowhere}}") }]);
    expect(await screen.findByTestId("query-tile-unread")).toHaveTextContent("It reads {{nowhere}}, and this dashboard holds no value of that name.");
    expect(api.runCard).not.toHaveBeenCalled();
  });

  it("is run again with the page's values by its own Refresh, never the page's bare run", async () => {
    const onRefresh = vi.fn();
    render(<ComposedDashboard spec={SPEC} cards={[{ card: card() }]} host={HOST} doors={{ onRefresh }} connectionId="thelook" dashboardId="thelook:sales" />);
    await waitFor(() => expect(runs()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(runs()).toHaveLength(2));
    expect(runs()[1]).toEqual(runs()[0]);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("holds its room as set up while it waits, so the page does not jump when it is read", async () => {
    api.runCard.mockImplementation(() => new Promise(() => {}));
    const chart = card();
    (chart.render as { shown: Record<string, unknown> }).shown = { as: "bar", summed: true, x: "day", bucket: "day", series: [{ column: "sales", agg: "sum" }] };
    draw(SPEC, [{ card: chart }]);
    expect(await screen.findByTestId("query-tile-reading")).toHaveTextContent("Reading…");
    expect(screen.getByTestId("dashboard-card")).toHaveAttribute("data-size", "wide");          // a chart, as it was set up
  });

  it("never draws what it read for the values before while it reads for the new ones", async () => {
    draw();
    await waitFor(() => expect(screen.getByTestId("query-tile-figure")).toHaveTextContent("203,868"));
    api.runCard.mockImplementation(() => new Promise(() => {}));
    fireEvent.click(within(value("window")).getByRole("radio", { name: "90" }));
    expect(await screen.findByTestId("query-tile-reading")).toBeInTheDocument();
    expect(screen.queryByTestId("query-tile-figure")).toBeNull();
  });
});

describe("a set read whole (Arc AP-8b)", () => {
  it("asks the door for the customers of the waiting orders as one set — with the reader's window in it, read again when it changes", async () => {
    const spec = { ...SPEC, values: { window: SPEC.values.window }, sets: { placed: SPEC.sets.placed,
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      theirs: { label: "Their customers", from: "waiting", traverse: { link: "placed_by", entity: "user" } } },
      elements: { cockpit: SPEC.elements.cockpit, sec: { ...SPEC.elements.sec, children: ["custs"] },
        custs: { type: "ObjectTable", props: { set: "theirs", columns: ["country"] }, children: [] } } };
    draw(spec, []);
    const asked = () => objects.listObjects.mock.calls.map(c => c[0] as { entity: string; filters: unknown[] }).filter(b => b.entity === "user");
    await waitFor(() => expect(asked().at(-1)?.filters).toEqual([{ path: "", op: "in_set", sets: [{ entity: "order", segment: "overdue_dispatch",
      filters: [{ path: "created_at", op: "in_last", value: 14 }], via: "placed_by" }] }]));
    fireEvent.click(within(value("window")).getByRole("radio", { name: "7" }));
    await waitFor(() => expect(asked().at(-1)?.filters).toEqual([{ path: "", op: "in_set", sets: [{ entity: "order", segment: "overdue_dispatch",
      filters: [{ path: "created_at", op: "in_last", value: 7 }], via: "placed_by" }] }]));
  });
});
