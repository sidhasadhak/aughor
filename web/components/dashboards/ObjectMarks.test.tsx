// @vitest-environment jsdom

/**
 * Rows marked by a declared rule (the Grist study §10). Drawn through the dashboard's own
 * renderer with the object door mocked: a table's `marked` names a segment the ontology declares, the rows on screen
 * that segment admits carry the mark, and the legend beside the title says what it marks and how many of the listing's
 * objects — both read through the door as `in_set`, never worked out from the page. A mark the door refuses says so in
 * the legend's place, and no row is marked.
 */
import { render, screen, waitFor } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ComposedDashboard } from "@/components/dashboards/ComposedDashboard";
import type { DashboardHostState } from "@/lib/dashboards/hostState";
import { cardsDashboardSpec } from "@/lib/dashboards/start";
import type { ObjectQueryRequest } from "@/lib/objects";

const objects = vi.hoisted(() => ({ listObjects: vi.fn(), queryObjects: vi.fn(), cachedObjectCatalog: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

// a new dashboard's own root and section, as the builder starts one, holding the one piece
const SPEC = (marked: Record<string, unknown> | null, piece = "ObjectTable") => {
  const spec = cardsDashboardSpec("Orders", []);
  Object.values(spec.elements).find(e => e.type === "Section")!.children = ["table"];
  spec.elements.table = { type: piece, props: { entity: "order", ...(piece === "ObjectTable" ? { columns: ["status"] } : { title: "status" }),
    ...(marked ? { marked } : {}) }, children: [] };
  return spec;
};
const HOST: DashboardHostState = { range: { status: "standing" }, cards: {} };

const KEYS = ["48211", "48377", "48902", "49010"];
// the rows the segment admits, of those on screen; and how many of the listing's 6,366 it admits in all
const LATE = new Set(["48377", "49010"]);
const LATE_IN_ALL = 1275;
let refuse = false;

type Filter = { path?: string; op?: string; values?: string[]; sets?: { entity: string; segment: string }[] };
const inSet = (b: { filters?: unknown[] }) => (b.filters ?? []).find(f => (f as Filter).op === "in_set") as Filter | undefined;

function listing(b: { filters?: unknown[] }) {
  const keyed = (b.filters ?? []).find(f => (f as Filter).op === "in" && (f as Filter).path === "order_id") as Filter | undefined;
  const rows = inSet(b) && keyed ? keyed.values!.filter(k => LATE.has(k)).map(k => [k, "Processing"])
    : KEYS.map(k => [k, "Processing"]);
  return {
    path: "listed", object_type: "order", type_id: "Order", key: "order_id", title: "", segment_said: "",
    columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }],
    names: ["order_id", "status"], rows, total: inSet(b) ? null : 6366, offset: 0, limit: 6, plan: [], caveats: [], error: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  refuse = false;
  objects.listObjects.mockImplementation(async (b: { filters?: unknown[] }) => listing(b));
  objects.queryObjects.mockImplementation(async (b: ObjectQueryRequest) => refuse
    ? { path: "refused", refused: 'The order type declares no segment "late_dispatch".' }
    : { path: "compiled", columns: [], rows: [[String(inSet(b) ? LATE_IN_ALL : 6366)]], caveats: [], error: null });
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
});

const draw = (marked: Record<string, unknown> | null, piece?: string) => render(
  <ComposedDashboard spec={SPEC(marked, piece)} cards={[]} host={HOST} doors={{ onRefresh: vi.fn() }} connectionId="thelook" schema="thelook" />);
const marked = () => screen.getAllByTestId("object-table-row").filter(r => r.getAttribute("data-marked") === "true")
  .map(r => r.textContent ?? "");

describe("rows marked by a declared rule", () => {
  it("marks the rows on screen its segment admits, and says how many of the listing's it marks", async () => {
    draw({ segment: "late_dispatch", tone: "warn", label: "Late dispatch" });
    await waitFor(() => expect(marked()).toEqual([expect.stringContaining("48377"), expect.stringContaining("49010")]));
    expect(screen.getByTestId("object-mark-legend")).toHaveTextContent("Late dispatch — 1,275 of 6,366");
    // both reads ask the door for a set of the listing's own entity kept to the declared segment
    const asked = objects.listObjects.mock.calls.map(c => c[0] as { filters?: unknown[] }).find(b => inSet(b));
    expect(inSet(asked!)).toMatchObject({ path: "", sets: [{ entity: "order", segment: "late_dispatch" }] });
    expect(inSet(objects.queryObjects.mock.calls[0][0] as ObjectQueryRequest)).toMatchObject(
      { sets: [{ entity: "order", segment: "late_dispatch" }] });
  });

  it("marks a list's cards the same way", async () => {
    draw({ segment: "late_dispatch", tone: "warn", label: "Late dispatch" }, "ObjectList");
    // the cards are titled by status, so which are marked is read by place: the second and the fourth key
    await waitFor(() => expect(screen.getAllByTestId("object-list-card").map(c => c.getAttribute("data-marked") === "true"))
      .toEqual([false, true, false, true]));
    expect(screen.getByTestId("object-mark-legend")).toHaveTextContent("Late dispatch — 1,275 of 6,366");
  });

  it("names the segment in words when the mark has no label", async () => {
    draw({ segment: "late_dispatch", tone: "bad" });
    await waitFor(() => expect(screen.getByTestId("object-mark-legend")).toHaveTextContent("Late dispatch — 1,275 of 6,366"));
  });

  it("says a mark the door refuses cannot be marked, and marks no row", async () => {
    refuse = true;
    draw({ segment: "late_dispatch", tone: "warn", label: "Late dispatch" });
    await waitFor(() => expect(screen.getByTestId("object-mark-legend")).toHaveTextContent("Late dispatch cannot be marked"));
    expect(screen.getByTestId("object-mark-legend")).toHaveAttribute("title", 'The order type declares no segment "late_dispatch".');
  });

  it("asks nothing and draws no legend for a table that marks nothing", async () => {
    draw(null);
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(4));
    expect(screen.queryByTestId("object-mark-legend")).toBeNull();
    expect(marked()).toEqual([]);
    expect(objects.queryObjects).not.toHaveBeenCalled();
    expect(objects.listObjects).toHaveBeenCalledTimes(1);
  });
});
