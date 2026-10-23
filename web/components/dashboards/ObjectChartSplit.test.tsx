// @vitest-environment jsdom

/**
 * A chart split by a property (Arc AP-1; the study's receipt: "Change the Order cockpit's chart to split by status").
 * Drawn through the cockpit's own renderer with the object door mocked: each day's bar stacks the property's most common
 * values — read from every object — and folds the rest into Other; a value keeps its colour while a reader narrows,
 * even where the narrowed objects rank the values differently; and the narrowed bars stand before the whole as a line.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { DashboardHostState } from "@/lib/dashboards/hostState";
import type { ObjectQueryRequest } from "@/lib/objects";

const objects = vi.hoisted(() => ({ queryObjects: vi.fn(), cachedObjectCatalog: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const SPEC = (chart: Record<string, unknown>) => ({
  root: "cockpit",
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec"] },
    filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "placed_by.country", label: "Country", via: "Customer" }] }, children: [] },
    sec: { type: "Section", props: { title: "Orders" }, children: ["chart"] },
    chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", days: 7, size: "full", ...chart }, children: [] },
  },
});
const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };

const narrowed = (b: ObjectQueryRequest) => (b.filters ?? []).length > 0;
const dayAfter = (d: string) => new Date(Date.parse(`${d}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);

function answer(b: ObjectQueryRequest) {
  let rows: unknown[][];
  const first = String(b.start ?? "");
  if (b.measures[0].agg === "max") rows = [["2026-10-09 23:10:00"]];
  else if (b.grain === "day" && b.by?.[0] === "status") {
    // every object: Shipped leads, then Complete; the narrowed ones (China) rank Complete first
    rows = narrowed(b)
      ? [[first, "Complete", "50"], [first, "Shipped", "10"]]
      : [[first, "Shipped", "100"], [first, "Complete", "80"], [first, "Returned", "10"],
         [dayAfter(first), "Shipped", "90"], [dayAfter(first), "Complete", "70"], [dayAfter(first), "Cancelled", "5"]];
  } else if (b.grain === "day") rows = [[first, narrowed(b) ? "60" : "190"]];
  else if (b.by?.[0]) rows = [["China", "4000"], ["Brasil", "2000"]];
  else rows = [[narrowed(b) ? "4000" : "125080"]];
  return { path: "compiled", columns: [], rows, caveats: [], error: null };
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => answer(b));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
});

const draw = (chart: Record<string, unknown>) => render(
  <ComposedDashboard spec={SPEC(chart)} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" dashboardId="thelook:split" />);

/** Each drawn day's segments, bottom up, as the colours they are filled with. */
const fills = () => screen.getAllByTestId("object-chart-bar").map(bar =>
  within(bar).queryAllByTestId("object-chart-segment").map(p => p.getAttribute("fill")));
const legend = () => screen.getByTestId("object-chart-legend").textContent ?? "";

describe("a chart split by a property", () => {
  it("stacks its most common values in fixed colours and folds the rest into Other", async () => {
    draw({ split: "status", top: 3 });
    await waitFor(() => expect(fills().some(f => f.length > 0)).toBe(true));
    expect(legend()).toMatch(/^Shipped.*Complete.*Returned.*Other$/);
    const days = fills().filter(f => f.length);
    // the three that hold the most over the window, in their colours; Cancelled, the fourth, folded into Other
    expect(days[0]).toEqual(["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"]);
    expect(days[1]).toEqual(["var(--chart-1)", "var(--chart-2)", "var(--chart-deemph)"]);
    expect(objects.queryObjects.mock.calls.some(([b]) => (b as ObjectQueryRequest).by?.[0] === "status")).toBe(true);
  });

  it("keeps each value's colour while a reader narrows, though the narrowed objects rank them otherwise", async () => {
    draw({ split: "status", top: 3 });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Country: China" }));
    await waitFor(() => expect(objects.queryObjects.mock.calls.some(([b]) =>
      (b as ObjectQueryRequest).by?.[0] === "status" && narrowed(b as ObjectQueryRequest))).toBe(true));
    // China's Complete (50) outnumbers its Shipped (10): Shipped is still the first colour, Complete the second
    await waitFor(() => expect(fills().filter(f => f.length)[0]).toEqual(["var(--chart-1)", "var(--chart-2)"]));
    expect(legend()).toMatch(/^Shipped.*Complete.*Returned.*All orders$/);
    expect(document.querySelector('[data-testid="object-chart-svg"] polyline')).not.toBeNull();   // the whole, as a line
  });

  it("measures a sum per day and writes it as money", async () => {
    objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => {
      if (b.measures[0].agg === "sum" && b.grain === "day") return { path: "compiled", columns: [], rows: [[b.start, "1234.5"]], caveats: [], error: null };
      return answer(b);
    });
    draw({ agg: "sum", path: "revenue", format: "money" });
    await waitFor(() => expect(screen.getAllByTestId("object-chart-segment").length).toBeGreaterThan(0));
    const asked = objects.queryObjects.mock.calls.map(([b]) => b as ObjectQueryRequest).find(b => b.grain === "day");
    expect(asked?.measures).toEqual([{ name: "n", agg: "sum", path: "revenue" }]);
    expect(screen.getByTestId("object-chart-svg").textContent).toMatch(/\$/);
  });

  it("without a split or a measure draws as it did before: one colour, counted", async () => {
    draw({});
    await waitFor(() => expect(fills().some(f => f.length > 0)).toBe(true));
    expect(fills().filter(f => f.length)).toEqual([["var(--chart-1)"]]);
    expect(screen.queryByTestId("object-chart-legend")).toBeNull();
    const asked = objects.queryObjects.mock.calls.map(([b]) => b as ObjectQueryRequest).find(b => b.grain === "day");
    expect(asked?.measures).toEqual([{ name: "n", agg: "count", path: "" }]);
    expect(asked?.by).toBeUndefined();
  });
});
