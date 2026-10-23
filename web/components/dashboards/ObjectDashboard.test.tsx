// @vitest-environment jsdom

/**
 * A cockpit started from an object (2026-10-10), drawn through the cockpit's own renderer with every door it reads
 * mocked. What it shows: a reader's click in the filter column narrows the figure, the chart and the table over the
 * same entity — and only for that reader, remembered in their browser under the cockpit's id; a list of values is
 * counted under the OTHER filters, never its own; a piece the filters cannot narrow says "Not filtered" while one is
 * on; and the whole is said beside the narrowed figure.
 */
import { fireEvent, render, screen, waitFor } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { DashboardHostState } from "@/lib/dashboards/hostState";
import type { ObjectQueryRequest } from "@/lib/objects";

const objects = vi.hoisted(() => ({
  queryObjects: vi.fn(), listObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getObjectPage: vi.fn(), getDeclaredActions: vi.fn(),
}));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const SPEC = {
  root: "cockpit",
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec"] },
    filters: { type: "ObjectFilters", props: { entity: "order", properties: [
      { path: "status", label: "Status" }, { path: "order_to_user.country", label: "Customer country", via: "Customer" }] }, children: [] },
    sec: { type: "Section", props: { title: "Orders", columns: 3 }, children: ["count", "revenue", "chart", "table", "people"] },
    count: { type: "ObjectFigure", props: { entity: "order", label: "Orders", agg: "count", format: "number" }, children: [] },
    revenue: { type: "ObjectFigure", props: { entity: "order", label: "Revenue", agg: "sum", path: "revenue", format: "money" }, children: [] },
    chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", days: 7, size: "full" }, children: [] },
    table: { type: "ObjectTable", props: { entity: "order", columns: ["status"] }, children: [] },
    people: { type: "ObjectTable", props: { entity: "customer", columns: ["country"] }, children: [] },
  },
};
const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };

const narrowed = (b: ObjectQueryRequest) => (b.filters ?? []).length > 0;

function answer(b: ObjectQueryRequest) {
  const m = b.measures[0];
  let rows: unknown[][];
  if (b.by?.[0] === "status") rows = [["Shipped", "37838"], ["Complete", "31335"], ["Cancelled", "18513"]];
  else if (b.by?.[0]) rows = narrowed(b) ? [["China", "3900"]] : [["China", "12917"], ["Brasil", "5389"]];
  else if (m.agg === "max") rows = [["2026-10-09 23:10:00"]];
  else if (b.grain === "day") rows = [[b.start, narrowed(b) ? "60" : "194"]];
  else if (m.agg === "sum") rows = [[narrowed(b) ? "3270000" : "10804567.74"]];
  else rows = [[narrowed(b) ? "37838" : "125080"]];
  return { path: "compiled", columns: [], rows, caveats: [], error: null };
}

const listing = (entity: string) => ({
  path: "listed", object_type: entity, type_id: entity === "order" ? "Order" : "Customer", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }],
  names: ["id", "status"], rows: [["1", "Shipped"]], total: 1, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => answer(b));
  objects.listObjects.mockImplementation(async (b: { entity: string }) => listing(b.entity));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [
    { object_type: "order", id: "Order", display_name: "Order" }, { object_type: "customer", id: "Customer", display_name: "Customer" }] });
  objects.getDeclaredActions.mockResolvedValue({});
});

const draw = () => render(
  <ComposedDashboard spec={SPEC} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" dashboardId="thelook:orders-1a2b" />);

const figure = (label: string) => screen.getAllByTestId("object-figure").find(f => f.textContent?.startsWith(label)) as HTMLElement;
const asked = () => objects.queryObjects.mock.calls.map(c => c[0] as ObjectQueryRequest);

describe("a dashboard started from an object", () => {
  it("draws the filter column, the whole as figures, and says how many objects there are", async () => {
    draw();
    await waitFor(() => expect(screen.getByTestId("object-filter-count").textContent).toBe("125,080 orders"));
    expect(screen.getAllByTestId("object-facet")).toHaveLength(2);
    expect(screen.getByText("via Customer")).toBeTruthy();
    await waitFor(() => expect(figure("Orders").textContent).toContain("125,080"));
    expect(figure("Revenue").textContent).toContain("$10.80M");
    expect(screen.queryByTestId("not-filtered")).toBeNull();
  });

  it("narrows every piece over the entity on a click, and says the whole beside each figure", async () => {
    draw();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Status: Shipped" }));
    await waitFor(() => expect(screen.getByTestId("object-filter-count").textContent).toBe("37,838 of 125,080 orders"));
    await waitFor(() => expect(figure("Orders").textContent).toContain("37,838of 125,080"));
    expect(figure("Revenue").textContent).toContain("$3.27Mof $10.80M");
    const shipped = { path: "status", op: "in", values: ["Shipped"] };
    await waitFor(() => expect(objects.listObjects).toHaveBeenCalledWith(
      expect.objectContaining({ entity: "order", filters: [shipped] }), "thelook", undefined));
    await waitFor(() => expect(screen.getByTestId("object-chart-legend").textContent).toContain("Shipped"));
    expect(asked().some(b => b.grain === "day" && JSON.stringify(b.filters) === JSON.stringify([shipped]))).toBe(true);
  });

  it("counts a list of values under the other filters, never its own", async () => {
    draw();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Status: Shipped" }));
    await waitFor(() => expect(asked().some(b => b.by?.[0] === "order_to_user.country" && narrowed(b))).toBe(true));
    expect(asked().filter(b => b.by?.[0] === "status").every(b => !narrowed(b))).toBe(true);
    // the other values of the list it was chosen from are still there to choose
    expect(screen.getByRole("checkbox", { name: "Status: Complete" })).toBeTruthy();
  });

  it("says Not filtered on a piece over another entity while a filter is on", async () => {
    draw();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Status: Shipped" }));
    await waitFor(() => expect(screen.getAllByTestId("not-filtered")).toHaveLength(1));
    const cells = screen.getAllByTestId("dashboard-piece-cell");
    const chip = screen.getByTestId("not-filtered");
    expect(cells.find(c => c.contains(chip))?.getAttribute("data-element")).toBe("people");
  });

  it("remembers a reader's filters in their browser, under the dashboard, and clears them", async () => {
    const first = draw();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Status: Shipped" }));
    await waitFor(() => expect(localStorage.getItem("aughor:cockpit-filters:thelook:orders-1a2b")).toBe('{"order":{"status":["Shipped"]}}'));
    first.unmount();
    draw();
    await waitFor(() => expect(screen.getByTestId("object-filter-count").textContent).toBe("37,838 of 125,080 orders"));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(screen.getByTestId("object-filter-count").textContent).toBe("125,080 orders"));
    expect(localStorage.getItem("aughor:cockpit-filters:thelook:orders-1a2b")).toBe("{}");
  });

  it("does not draw a section's heading that only repeats the dashboard's name", async () => {
    draw();
    await screen.findAllByTestId("object-figure");
    expect(screen.queryByText("Orders", { selector: ".aug-fs-h2" })).toBeNull();
  });
});
