// @vitest-environment jsdom

/**
 * Arc AP-8c, drawn: a list the reader ticks from the choices offered, yes or no as a switch of two, a value summed over a
 * set at the object door, and one read from the first value of a query the dashboard places — run as written, with the
 * values it reads, never cut to the page's range. Through the dashboard's own renderer, the object door and the card run
 * mocked. What cannot be read says why in its place: a sum over nothing is not a zero; a query that is not placed, or
 * reads itself back, is said.
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

const SPEC = {
  root: "cockpit",
  values: {
    countries: { label: "Countries", kind: "list", value: ["China"], from: { by: "reader", options: ["China", "Brasil", "Japan"] } },
    late: { label: "Late only", kind: "yesno", value: true, from: { by: "reader" } },
    spend: { label: "Spend", kind: "number", from: { by: "sum", set: "placed", path: "sale_price" } },
    top: { label: "Top country", kind: "text", from: { by: "query", card: "q-top" } },
  },
  sets: {
    placed: { label: "Placed", entity: "order", where: [{ path: "user.country", op: "in", value_from: "countries" },
      { path: "is_late", op: "=", value_from: "late" }] },
    big: { label: "Big", entity: "order", where: [{ path: "sale_price", op: ">=", value_from: "spend" }] },
    "in-top": { label: "In the top country", entity: "order", where: [{ path: "user.country", op: "=", value_from: "top" }] },
  },
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Sales desk" }, children: ["sec"] },
    sec: { type: "Section", props: { title: "Sales" }, children: ["placed", "big", "in-top", "q"] },
    placed: { type: "ObjectTable", props: { set: "placed", columns: ["status"] }, children: [] },
    big: { type: "ObjectTable", props: { set: "big", columns: ["status"] }, children: [] },
    "in-top": { type: "ObjectTable", props: { set: "in-top", columns: ["status"] }, children: [] },
    q: { type: "Card", props: { card: "q-top" }, children: [] },
  },
};
const TOP = "SELECT country, COUNT(*) AS n FROM orders WHERE country IN ({{countries}}) GROUP BY 1 ORDER BY n DESC";
const card = (sql = TOP, id = "q-top") => ({
  id, title: "Top country", kind: "chart", own: true, connection_id: "thelook", scope: "user", scope_ref: "default", source: "authored",
  sql, thresholds: {}, provenance: {}, links: [],
  render: { shown: { as: "table" }, columns: [{ name: "country", type: "VARCHAR" }, { name: "n", type: "BIGINT" }] },
  refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] },
}) as unknown as DashboardCard;
const tableRun = (rows: unknown[][]): CardRunResult => ({ columns: ["country", "n"], rows, row_count: rows.length, caveats: [], error: null,
  value: null, duration_ms: 400, refresh: { cadence: "brief_cycle", last_run: "", last_value: null, prev_value: null, history: [] },
  shown: { as: "table", columns: ["country", "n"], rows, said: [] } } as unknown as CardRunResult);

const listing = (b: { entity: string }) => ({
  path: "listed", object_type: b.entity, type_id: "Order", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }], names: ["id", "status"],
  rows: [["38330", "Processing"]], total: 1, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

let summed: unknown = "1250.5";
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  summed = "1250.5";
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => ({ path: "compiled", columns: [], caveats: [], error: null,
    rows: [[b.measures[0]?.agg === "sum" ? summed : "6619"]] }));
  objects.listObjects.mockImplementation(async (b: { entity: string }) => listing(b));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
  objects.getDeclaredActions.mockResolvedValue({});
  objects.getObjectPage.mockResolvedValue({ path: "refused", refused: "not here" });
  api.runCard.mockImplementation(async (_id: string, _r: unknown, opts: { values?: Record<string, { value: unknown }> }) => {
    const asked = (opts.values?.countries?.value as string[] | undefined) ?? [];
    return tableRun(asked.includes("Brasil") ? [["Brasil", 235], ["China", 480]].sort((a, b) => (b[1] as number) - (a[1] as number)) : [["China", 480]]);
  });
});

const draw = (spec: unknown = SPEC, cards = [{ card: card() }]) => render(
  <ComposedDashboard spec={spec} cards={cards} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" dashboardId="thelook:sales" />);
const listed = (path: string) => objects.listObjects.mock.calls.map(c => c[0] as { filters: { path: string; op: string; value?: unknown; values?: unknown[] }[] })
  .map(b => b.filters.find(f => f.path === path)).filter(Boolean);
const value = (name: string) => screen.getAllByTestId("dashboard-value").find(v => v.getAttribute("data-name") === name) as HTMLElement;
const sums = () => objects.queryObjects.mock.calls.map(c => c[0] as ObjectQueryRequest).filter(b => b.measures[0]?.agg === "sum");

describe("a list and yes or no, set by the reader", () => {
  it("ticks the choices offered — one at least — and switches yes or no; every set that reads them is read again", async () => {
    draw();
    const china = within(value("countries")).getByRole("button", { name: "China" });
    expect(china).toHaveAttribute("aria-pressed", "true");
    expect(china).toBeDisabled();                                                    // a list holds one at least
    expect(within(value("late")).getByRole("radio", { name: "Yes" })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(listed("user.country").at(-1)).toEqual({ path: "user.country", op: "in", values: ["China"] }));
    expect(listed("is_late").at(-1)).toEqual({ path: "is_late", op: "=", value: true });

    fireEvent.click(within(value("countries")).getByRole("button", { name: "Brasil" }));
    await waitFor(() => expect(listed("user.country").at(-1)).toEqual({ path: "user.country", op: "in", values: ["China", "Brasil"] }));
    fireEvent.click(within(value("late")).getByRole("radio", { name: "No" }));
    await waitFor(() => expect(listed("is_late").at(-1)).toEqual({ path: "is_late", op: "=", value: false }));
    expect(JSON.parse(localStorage.getItem("aughor:cockpit-values:thelook:sales") ?? "{}")).toEqual({ countries: ["China", "Brasil"], late: false });
  });
});

describe("a list a reader kept", () => {
  it("is theirs only while every item is one the author still offers — else the author's", async () => {
    localStorage.setItem("aughor:cockpit-values:thelook:sales", JSON.stringify({ countries: ["China", "Peru"] }));
    draw();
    await waitFor(() => expect(listed("user.country").at(-1)).toEqual({ path: "user.country", op: "in", values: ["China"] }));
    expect(listed("user.country").some(f => (f?.values ?? []).includes("Peru"))).toBe(false);
  });
});

describe("a value summed over a set", () => {
  it("is added up at the object door over the set as the page reads it, and read by the sets that compare with it", async () => {
    draw();
    await waitFor(() => expect(sums().at(-1)).toMatchObject({ object_type: "order", measures: [{ name: "n", agg: "sum", path: "sale_price" }],
      filters: [{ path: "user.country", op: "in", values: ["China"] }, { path: "is_late", op: "=", value: true }] }));
    await waitFor(() => expect(listed("sale_price").at(-1)).toEqual({ path: "sale_price", op: ">=", value: 1250.5 }));
  });

  it("over no objects is none, said where it is read — never a zero", async () => {
    summed = null;
    draw();
    await waitFor(() => expect(screen.getAllByText(/The set holds no objects to add up/).length).toBeGreaterThan(0));
    expect(listed("sale_price")).toEqual([]);
  });
});

describe("a value read from a query", () => {
  it("is the first row's value, the query run as written with the values it reads — and read again when one changes", async () => {
    // the page is read for a range: the card's own tile runs for it, and the value's run never does
    render(<ComposedDashboard spec={SPEC} cards={[{ card: card() }]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook"
      dashboardId="thelook:sales" range={{ preset: "last_month" }} />);
    await waitFor(() => expect(listed("user.country").some(f => f?.op === "=" && f.value === "China")).toBe(true));
    const valued = api.runCard.mock.calls.filter(c => (c[2] as { values?: unknown }).values);
    expect(valued.map(c => c[1])).toContainEqual({ preset: "last_month" });      // the tile, for the page's range
    expect(valued.map(c => c[1])).toContain(null);                                   // the value, never cut to it
    expect((valued[0][2] as { values: unknown }).values).toEqual({ countries: { kind: "list", value: ["China"] } });
    fireEvent.click(within(value("countries")).getByRole("button", { name: "Brasil" }));
    await waitFor(() => expect(api.runCard.mock.calls.some(c =>
      JSON.stringify((c[2] as { values?: unknown }).values) === JSON.stringify({ countries: { kind: "list", value: ["China", "Brasil"] } }))).toBe(true));
  });

  it("that is not placed, or reads itself back, says so in place of what reads it", async () => {
    // the card it names is placed, and it is not one of the dashboard's cards the person has
    const { unmount } = draw(SPEC, []);
    await waitFor(() => expect(screen.getAllByText(/not a card this dashboard places/).length).toBeGreaterThan(0));
    unmount();
    draw(SPEC, [{ card: card("SELECT {{top}} AS country") }]);
    await waitFor(() => expect(screen.getAllByText(/Top country → Top country read each other in a ring/).length).toBeGreaterThan(0));
  });
});
