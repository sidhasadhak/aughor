// @vitest-environment jsdom

/**
 * A breakdown (the Grist study §10, mockup design-mockups/dashboard-breakdown.html). Drawn through the dashboard's own
 * renderer with the object door mocked on theLook's figures: the largest groups first, the rest one Other row, the
 * objects with no value their own row, and the line beneath saying the groups add up to the whole — or that they do
 * not. A click on a group is the filter column's: the figure beside it narrows, the breakdown keeps every group (its own
 * grouping is never in its own query) and ticks the chosen one.
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

const SPEC = (breakdown: Record<string, unknown>) => ({
  root: "cockpit",
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["sec"] },
    sec: { type: "Section", props: { title: "Orders" }, children: ["orders", "by-country"] },
    orders: { type: "ObjectFigure", props: { entity: "order", label: "Orders", agg: "count" }, children: [] },
    "by-country": { type: "ObjectBreakdown", props: { entity: "order", label: "Revenue by customer country", by: "placed_by.country",
      measures: [{ agg: "count" }, { agg: "sum", path: "revenue", format: "money" }], top: 5, ...breakdown }, children: [] },
  },
});
const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };

// theLook's orders by customer country, as the mockup read them through the door (counts, revenue), and the whole
const GROUPS: [string | null, number, number][] = [
  ["China", 42604, 3670000], ["United States", 28327, 2430000], ["Brasil", 18439, 1610000], ["South Korea", 6629, 571000],
  ["France", 5899, 506000], ["United Kingdom", 5670, 489000], ["Germany", 5215, 454000], ["Spain", 4864, 414000],
  ["Poland", 5000, 260000], [null, 2749, 405000],
];
const WHOLE = [125396, 10809000];
let leak = 0;   // an object the door counts in the whole and in no group — the falsifier's case

const chosen = (b: ObjectQueryRequest) => (b.filters ?? []).find(f => (f as { path?: string }).path === "placed_by.country"
  && (f as { op?: string }).op === "in") as { values: string[] } | undefined;

function answer(b: ObjectQueryRequest) {
  const pick = chosen(b);
  const rows = (b.by?.[0] === "placed_by.country"
    ? GROUPS.map(([v, n, r]) => [v, String(n), String(r)])
    : pick ? [[String(GROUPS.find(g => g[0] === pick.values[0])?.[1] ?? 0), "0"]] : [[String(WHOLE[0] + leak), String(WHOLE[1])]]);
  return { path: "compiled", columns: [], rows, caveats: [], error: null };
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  leak = 0;
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => answer(b));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
});

const draw = (breakdown: Record<string, unknown> = {}) => render(
  <ComposedDashboard spec={SPEC(breakdown)} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook"
    dashboardId="thelook:breakdown" />);
const rows = () => screen.getAllByTestId("object-breakdown-row");
const names = () => rows().map(r => (r.textContent ?? "").replace(/\s+/g, " "));

describe("a breakdown", () => {
  it("shows the largest groups, the rest as Other, the objects with no value — and says they add up to the whole", async () => {
    draw();
    await waitFor(() => expect(rows().length).toBe(7));
    expect(names()[0]).toMatch(/^China\s*42,604/);
    // the four after the top five, folded: 5,670 + 5,215 + 4,864 + 5,000 orders
    expect(names()[5]).toMatch(/^Other · 4 countries\s*20,749/);
    expect(names()[6]).toMatch(/^No value\s*2,749/);
    expect(screen.getByTestId("object-breakdown-foot")).toHaveTextContent(
      /^9 countries · 125,396 · \$10\.81M — every order is in one row\.$/);
  });

  it("says when its groups do not add up to the whole, rather than drawing a total that cannot be", async () => {
    leak = 6;
    draw();
    await waitFor(() => expect(screen.getByTestId("object-breakdown-foot")).toHaveTextContent(
      "The groups hold 125,396 of 125,402 — some objects are in no row."));
  });

  it("narrows the dashboard on a click, keeps every group and ticks the chosen one; a second click lets go", async () => {
    draw();
    await waitFor(() => expect(rows().length).toBe(7));
    fireEvent.click(rows()[0]);
    await waitFor(() => expect(screen.getByTestId("object-figure-value")).toHaveTextContent("42,604"));
    // the breakdown's own query never carries its own grouping: every group is still there, China ticked
    const own = objects.queryObjects.mock.calls.map(c => c[0] as ObjectQueryRequest).filter(b => b.by?.[0] === "placed_by.country");
    expect(own.every(b => !chosen(b))).toBe(true);
    expect(rows().length).toBe(7);
    expect(rows()[0]).toHaveAttribute("data-on", "true");
    expect(screen.getByTestId("object-breakdown-chosen")).toHaveTextContent("Chosen: China — click it again to let go.");
    fireEvent.click(rows()[0]);
    await waitFor(() => expect(screen.getByTestId("object-figure-value")).toHaveTextContent("125,396"));
    expect(screen.queryByTestId("object-breakdown-chosen")).toBeNull();
  });

  it("never lets Other or No value be chosen, and says why", async () => {
    draw();
    await waitFor(() => expect(rows().length).toBe(7));
    fireEvent.click(rows()[5]);
    fireEvent.click(rows()[6]);
    expect(screen.queryByTestId("object-breakdown-chosen")).toBeNull();
    expect(rows()[5]).toHaveAttribute("title", "Other cannot be chosen — choose its groups in a filter column");
    expect(rows()[6]).toHaveAttribute("title", "Objects with no value cannot be chosen");
  });

  it("asks the door for Other's average, which no sum of groups can give", async () => {
    draw({ measures: [{ agg: "count" }, { agg: "avg", path: "revenue" }] });
    await waitFor(() => expect(rows().length).toBe(7));
    const other = objects.queryObjects.mock.calls.map(c => c[0] as ObjectQueryRequest)
      .find(b => (b.filters ?? []).some(f => (f as { op?: string }).op === "not_in"));
    expect(other).toBeTruthy();
    expect((other!.filters ?? []).find(f => (f as { op?: string }).op === "not_in")).toMatchObject(
      { path: "placed_by.country", values: ["China", "United States", "Brasil", "South Korea", "France"] });
  });

  it("shows bars alone when asked, with the same rows", async () => {
    draw({ show: "bars" });
    await waitFor(() => expect(rows().length).toBe(7));
    expect(within(rows()[0]).getByText("China")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
