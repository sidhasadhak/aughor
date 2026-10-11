/**
 * Shapes in the starter (Arc AP-5; design-mockups/cockpit-builder.html screens 1 and 7). Each shape the server says an
 * object fits becomes a cockpit the rules accept, laid out as the mockup lays it out — read here from proposals shaped as
 * theLook's are served: an order's queue past its dispatch promise, a case's queue on its status, the distribution
 * centres on a map, a customer as one object, inventory on a timeline.
 */
import { describe, expect, it } from "vitest";

import type { CockpitFromObject, ShapeSignals } from "@/lib/api";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { mapSpec, oneObjectSpec, queueSpec, shapeHolds, shapeSpec, timelineSpec } from "@/lib/cockpit/shapes";

type Spec = { elements: Record<string, { type: string; props: Record<string, unknown>; children: string[] }>; sets?: Record<string, Record<string, unknown>>; values?: Record<string, { value: number }> };

function proposal(entity: string, name: string, signals: Partial<ShapeSignals>, extra: Partial<CockpitFromObject> = {}): CockpitFromObject {
  return {
    connection_id: "thelook", schema_name: "thelook", entity, type_id: entity, name, title: `${name}s`, total: 100,
    filters: [{ path: "status", label: "Status", via: "", values: [["Shipped", 60]] }],
    figures: [{ label: `${name}s`, agg: "count", path: "", format: "number", value: 100 }],
    chart: null, table: { columns: ["status", "created_at"], labels: ["Status", "Created at"] }, actions: [], caveats: [],
    signals: { entity, type_id: entity, name, label: "", queue: null, actions: [], places: null, moments: null, one: null,
      lines: null, window: 14, measured: {}, ...signals },
    ...extra,
  };
}

const ORDER = proposal("order", "Customer Order", {
  queue: { kind: "promise", process: "order_fulfilment", noun: "dispatch", placed: "created_at", reached: "shipped_at", stage: "shipped",
    overdue: "overdue_dispatch", late: "late_dispatch", promise: "2 days" },
  actions: [{ id: "open_case", label: "Open a case", params: [{ name: "order", source: "chosen" }, { name: "assignee", source: "ask" }] },
    { id: "flag_for_review", label: "Flag for review", params: [{ name: "order", source: "chosen" }] }],
  lines: { entity: "order_item", type_id: "OrderItem", path: "order_id", label: "Order Line" },
  moments: { start: "created_at", end: "shipped_at" },
}, { filters: [{ path: "status", label: "Status", via: "", values: [["Processing", 60]] },
  { path: "placed_by.country", label: "Customer country", via: "Customer", values: [["China", 30]] }] });
const CASE = proposal("case", "Case", {
  queue: { kind: "states", status: "status", final: ["resolved"], moves: "open → working → resolved" },
  actions: [{ id: "start_work_on_case", label: "Start work", params: [{ name: "case", source: "chosen" }] }],
}, { filters: [{ path: "assignee", label: "Assignee", via: "", values: [["amit", 1]] }], table: { columns: ["about", "status"], labels: ["About", "Status"] } });
const CENTRE = proposal("distribution_center", "Distribution Center", { label: "name", places: { lat: "latitude", lng: "longitude", via: "" } },
  { filters: [], table: { columns: ["name"], labels: ["Name"] } });
const CUSTOMER = proposal("user", "Customer", { label: "first_name", one: { label: "first_name", kinds: 3, links: [
  { entity: "order", type_id: "Order", path: "user_id", label: "Customer Order", listable: true },
  { entity: "event", type_id: "Event", path: "user_id", label: "Event Log", listable: false }] } });
const STOCK = proposal("inventory_item", "Inventory Item", { moments: { start: "created_at", end: "sold_at" } });

const valid = (spec: unknown) => expect(checkCockpitSpec(spec).issues.map(i => i.message)).toEqual([]);

describe("a queue", () => {
  it("waits past the promise in a window the author sets, figures switching the list, oldest first, filled actions", () => {
    const spec = queueSpec(ORDER, ORDER.signals!) as Spec;
    valid(spec);
    expect(spec.elements.cockpit.props.title).toBe("Dispatch desk");
    expect(spec.values).toEqual({ window: { label: "Window", kind: "days", value: 14 } });
    expect(spec.sets).toMatchObject({
      placed: { entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { from: "placed", segment: "overdue_dispatch" },
      done: { from: "placed", where: [{ path: "shipped_at", op: "not_null" }] },
      late: { from: "done", segment: "late_dispatch" },
      lines: { entity: "order_item", linked_to: { choice: "chosen-order", path: "order_id" } },
    });
    expect(spec.elements.filters.props).toMatchObject({ entity: "order", set: "waiting" });
    expect(spec.elements.table.props).toMatchObject({ set: "waiting", set_from: "shown", chooses: "chosen-order", ticks: "ticked-order", sort: "created_at", descending: false });
    expect(["fig-waiting", "fig-late", "fig-done"].map(k => spec.elements[k].props.shows)).toEqual(["shown", "shown", "shown"]);
    // what waits is all at one status: the chart splits by the customer's country, never by status
    expect(spec.elements.chart.props).toMatchObject({ set: "waiting", time: "created_at", days: 14, split: "placed_by.country", top: 3 });
    expect(spec.elements.detail.props.follows).toBe("chosen-order");
    expect(spec.elements.buttons.props.buttons).toEqual([
      { action: "open_case", label: "Open a case", primary: true, params: { order: { from: "chosen-order" }, assignee: { ask: true } }, after: { read: ["waiting"] } },
      { action: "flag_for_review", label: "Flag for review", params: { order: { from: "chosen-order" } }, after: { read: ["waiting"] } },
    ]);
  });

  it("looks back over the days a person picks, its chart drawn over the same days", () => {
    const week = shapeSpec("queue", { ...ORDER, signals: { ...ORDER.signals!, window: 7 } }) as Spec;
    valid(week);
    expect(week.values!.window.value).toBe(7);
    expect(week.elements.chart.props.days).toBe(7);
  });

  it("waits on a platform-owned type's status a move still leaves, with no window and no promise", () => {
    const spec = queueSpec(CASE, CASE.signals!) as Spec;
    valid(spec);
    expect(spec.elements.cockpit.props.title).toBe("Case queue");
    expect(spec.values).toBeUndefined();
    expect(spec.sets!.waiting).toEqual({ label: "Not resolved", entity: "case", where: [{ path: "status", op: "not_in", values: ["resolved"] }] });
    expect(spec.elements.table.props.set_from).toBeUndefined();
    expect(spec.elements.buttons.props.buttons).toEqual([
      { action: "start_work_on_case", label: "Start work", primary: true, params: { case: { from: "chosen-case" } }, after: { read: ["waiting"] } }]);
  });
});

describe("the other shapes", () => {
  it("places the centres on a map, called by their name, the chosen one beside it", () => {
    const spec = mapSpec(CENTRE, CENTRE.signals!) as Spec;
    valid(spec);
    expect(spec.elements.map.props).toMatchObject({ entity: "distribution_center", lat: "latitude", lng: "longitude", label: "name" });
    expect(spec.elements.detail.props.follows).toBe("map");
    expect(spec.elements.cockpit.children).toEqual(["desk"]);          // no category to filter by, no filter column
  });

  it("finds one customer by name, its properties beside, a table of each kind that links to it", () => {
    const spec = oneObjectSpec(CUSTOMER, CUSTOMER.signals!) as Spec;
    valid(spec);
    expect(spec.elements.cockpit.props.title).toBe("A customer");
    expect(spec.elements.choose.props).toMatchObject({ entity: "user", chooses: "chosen-user", label: "first_name" });
    expect(Object.values(spec.sets!)).toEqual([
      { label: "Its customer orders", entity: "order", linked_to: { choice: "chosen-user", path: "user_id" } },
      { label: "Its event logs", entity: "event", linked_to: { choice: "chosen-user", path: "user_id" } }]);
    // its orders are listed; its events declare no key, and are counted
    expect([spec.elements["linked-0"].type, spec.elements["linked-1"].type]).toEqual(["ObjectTable", "ObjectFigure"]);
    expect(spec.elements["linked-1"].props).toMatchObject({ label: "Its event logs", agg: "count" });
  });

  it("draws inventory on a timeline, in stock to sold, the chosen one beside it", () => {
    const spec = timelineSpec(STOCK, STOCK.signals!) as Spec;
    valid(spec);
    expect(spec.elements.timeline.props).toMatchObject({ start: "created_at", end: "sold_at" });
    expect(spec.elements.detail.props.follows).toBe("timeline");
  });

  it("makes an overview of the proposal as before, and nothing of a shape the object holds nothing for", () => {
    valid(shapeSpec("overview", ORDER));
    expect(mapSpec(ORDER, ORDER.signals!)).toBeNull();
    expect(oneObjectSpec(ORDER, ORDER.signals!)).toBeNull();
    expect(queueSpec(STOCK, STOCK.signals!)).toBeNull();
  });

  it("says what each shape holds, a line a piece", () => {
    expect(shapeHolds("queue", ORDER)).toEqual([
      "Filter column · Status · Customer country", "Figure · Waiting past the promise", "Figure · Shipped late", "Figure · Shipped",
      "Chart · Waiting, by the day placed", "The list, oldest first — a click chooses, a tick collects", "The chosen one — its properties",
      "Table · Its order lines", "Buttons · Open a case · Flag for review — filled from the chosen one"]);
    expect(shapeHolds("overview", ORDER)).toEqual([]);
  });
});
