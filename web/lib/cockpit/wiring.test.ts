/**
 * A cockpit wired as an App (Arc AP-2 and AP-3; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.1b, §4.3, §4.5): what a
 * set reads down the sets it starts from, the choices a reader makes and who reads each, the rules that hold the wiring
 * by name, what a press of a button runs, and the edits that build sets and values by hand. The spec is the dispatch
 * desk of the approved mockup, on theLook's names.
 */
import { describe, expect, it } from "vitest";

import { MAX_SETS, MAX_TICKED_RUNS } from "@/lib/cockpit/catalog";
import { dropWire, freshWireName, putSet, putValue, type CockpitSpec } from "@/lib/cockpit/edit";
import { planRuns, pressSaid, runsOf, type ParamDecl, type RunContext } from "@/lib/cockpit/runs";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { choicesOf, doorConditions, isRefused, pieceSet, readSet, readersOf, wiring, type SetRead } from "@/lib/cockpit/sets";

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    values: { window: { label: "Window", kind: "days", value: 14 } },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      shipped: { label: "Shipped", from: "placed", where: [{ path: "shipped_at", op: "not_null" }] },
      late: { label: "Shipped late", from: "shipped", segment: "late_dispatch" },
      lines: { label: "Its lines", entity: "order_item", linked_to: { choice: "chosen-order", path: "order_id" } },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Dispatch desk" }, children: ["filters", "today"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] },
      today: { type: "Section", props: { title: "Dispatch desk" }, children: ["fig-waiting", "fig-late", "chart", "table", "detail", "lines", "buttons"] },
      "fig-waiting": { type: "ObjectFigure", props: { set: "waiting", of: "placed", shows: "shown", label: "Waiting past the promise", agg: "count" }, children: [] },
      "fig-late": { type: "ObjectFigure", props: { set: "late", of: "shipped", shows: "shown", label: "Shipped late", agg: "count" }, children: [] },
      chart: { type: "ObjectChart", props: { set: "waiting", label: "Waiting, by the day placed", time: "created_at", days: 14 }, children: [] },
      table: { type: "ObjectTable", props: { set: "waiting", set_from: "shown", chooses: "chosen-order", ticks: "ticked-orders", sort: "created_at" }, children: [] },
      detail: { type: "ObjectDetail", props: { follows: "chosen-order" }, children: [] },
      lines: { type: "ObjectTable", props: { set: "lines", columns: ["sale_price"] }, children: [] },
      buttons: { type: "ActionButtons", props: { buttons: [
        { action: "open_case", params: { order: { from: "chosen-order" }, assignee: { ask: true } }, after: { read: ["waiting"] } },
        { action: "flag_for_review", params: { order: { from: "ticked-orders" } } },
      ] }, children: [] },
    },
  };
}
const issues = (s: unknown) => checkCockpitSpec(s).issues.map(i => i.message);
const read = (s: CockpitSpec, n: string) => readSet(s, n) as SetRead;

describe("what a set reads", () => {
  it("is its entity, its segment and every condition down the sets it starts from, a value's in its place", () => {
    expect(read(desk(), "waiting")).toEqual({
      name: "waiting", label: "Waiting", entity: "order", segment: "overdue_dispatch",
      where: [{ path: "created_at", op: "in_last", value: 14 }], linkedTo: null, chain: ["waiting", "placed"],
    });
    expect(read(desk(), "late")).toMatchObject({
      entity: "order", segment: "late_dispatch", chain: ["late", "shipped", "placed"],
      where: [{ path: "shipped_at", op: "not_null" }, { path: "created_at", op: "in_last", value: 14 }],
    });
  });

  it("refuses a ring, a set it starts from that is not there, two segments, and a value that is not days for days", () => {
    const ring = desk();
    ring.sets!.placed = { label: "Placed", from: "shipped" };
    expect((readSet(ring, "shipped") as { refused: string }).refused).toMatch(/"shipped" → "placed" → "shipped" start from each other in a ring/);
    const gone = desk();
    delete gone.sets!.placed;
    expect((readSet(gone, "waiting") as { refused: string }).refused).toMatch(/starts from "placed", which this dashboard does not hold/);
    const two = desk();
    two.sets!.placed.segment = "active_orders";
    expect((readSet(two, "waiting") as { refused: string }).refused).toMatch(/keeps two segments/);
    const word = desk();
    word.values!.window = { label: "Window", kind: "text", value: "fortnight" };
    expect((readSet(word, "placed") as { refused: string }).refused).toMatch(/not a number of days/);
    // one thing a set starts from, and one object it follows, however it is written
    const both = desk();
    both.sets!.placed = { label: "Placed", entity: "order", from: "shipped" };
    expect((readSet(both, "placed") as { refused: string }).refused).toMatch(/names an entity and a set it starts from/);
    const twice = desk();
    twice.sets!.mine = { label: "Mine", from: "lines", linked_to: { choice: "chosen-order", path: "order_id" } };
    expect((readSet(twice, "mine") as { refused: string }).refused).toMatch(/linked to two chosen objects/);
  });

  it("waits on the chosen object it links to, and reads its key once one is chosen", () => {
    const lines = read(desk(), "lines");
    expect(doorConditions(lines, () => null)).toEqual({ waiting: "chosen-order" });
    expect(doorConditions(lines, c => (c === "chosen-order" ? "38330" : null))).toEqual({
      filters: [{ path: "order_id", op: "=", value: "38330" }] });
  });

  it("is, for a piece, the set a figure shows in its stead, else its own, else every object of its entity", () => {
    const s = desk();
    expect((pieceSet(s, s.elements.table.props, () => "late") as SetRead).name).toBe("late");
    expect((pieceSet(s, s.elements.table.props, () => null) as SetRead).name).toBe("waiting");
    expect(pieceSet(s, { entity: "order", segment: "overdue_dispatch" })).toMatchObject({ name: "", entity: "order", segment: "overdue_dispatch", where: [] });
    expect(isRefused(pieceSet(s, {}))).toBe(true);
  });
});

describe("the choices a reader makes, and what reads each", () => {
  it("names the object chosen and the ones ticked in a table — with its entity — and the set a figure shows", () => {
    const c = choicesOf(desk());
    expect(c.get("chosen-order")).toEqual({ name: "chosen-order", kind: "chosen", madeBy: ["table"], entity: "order" });
    expect(c.get("ticked-orders")).toMatchObject({ kind: "ticked", entity: "order" });
    expect(c.get("shown")).toMatchObject({ kind: "shown", madeBy: ["fig-waiting", "fig-late"] });
  });

  it("says what reads a set, a choice or a value — pieces and sets — so nothing read is taken away", () => {
    const s = desk();
    expect(readersOf(s, "waiting")).toEqual({ elements: ["fig-waiting", "chart", "table", "buttons"], sets: [], values: [] });
    expect(readersOf(s, "placed")).toEqual({ elements: ["fig-waiting"], sets: ["waiting", "shipped"], values: [] });
    expect(readersOf(s, "chosen-order")).toEqual({ elements: ["detail", "buttons"], sets: ["lines"], values: [] });
    expect(readersOf(s, "window")).toEqual({ elements: [], sets: ["placed"], values: [] });
  });

  it("hands the server each set as the door reads it and each button's sources with their kind and entity", () => {
    const w = wiring(desk());
    expect(w.sets.lines).toEqual({ entity: "order_item", segment: "", filters: [{ path: "order_id", op: "=", value: "probe" }] });
    expect(w.buttons[0]).toEqual({ element: "buttons", index: 0, action: "open_case",
      params: { order: { source: "chosen", entity: "order" }, assignee: { source: "ask", entity: "" } } });
    expect(w.buttons[1].params.order).toEqual({ source: "ticked", entity: "order" });
  });
});

describe("the rules a wired dashboard is held to", () => {
  it("accept the dispatch desk", () => {
    expect(issues(desk())).toEqual([]);
  });

  const broken = (change: (s: CockpitSpec) => void) => { const s = desk(); change(s); return issues(s).join(" "); };

  it("refuse a set, a value or a choice named that the dashboard does not hold", () => {
    expect(broken(s => { s.elements.chart.props.set = "nowhere"; })).toMatch(/reads the set "nowhere", which this dashboard does not hold/);
    expect(broken(s => { s.elements["fig-late"].props.of = "nowhere"; })).toMatch(/said beside the set "nowhere"/);
    expect(broken(s => { s.sets!.placed.where![0].value_from = "nowhere"; })).toMatch(/reads the value "nowhere"/);
    expect(broken(s => { s.elements.detail.props.follows = "nowhere"; })).toMatch(/follows "nowhere", which is neither/);
    expect(broken(s => { s.sets!.lines.linked_to!.choice = "ticked-orders"; })).toMatch(/no click chooses "ticked-orders"/);
  });

  it("refuse a condition that does not say what its operator needs", () => {
    expect(broken(s => { s.sets!.shipped.where = [{ path: "shipped_at", op: "not_null", value: 3 }]; })).toMatch(/compares with nothing/);
    expect(broken(s => { s.sets!.shipped.where = [{ path: "status", op: "in" }]; })).toMatch(/lists no values/);
    expect(broken(s => { s.sets!.shipped.where = [{ path: "created_at", op: "in_last", value: 0 }]; })).toMatch(/whole number of days/);
    expect(broken(s => { s.sets!.shipped.where = [{ path: "status", op: "=" }]; })).toMatch(/compares with nothing/);
  });

  it("hold one name to one thing, and an object to the one table that chooses it", () => {
    expect(broken(s => { s.elements.table.props.chooses = "waiting"; })).toMatch(/names a set or a value and a choice/);
    expect(broken(s => { s.elements.lines.props.chooses = "chosen-order"; })).toMatch(/An object is chosen or ticked in one piece/);
    expect(broken(s => { s.elements.table.props.ticks = "chosen-order"; })).toMatch(/A choice is one kind of thing/);
    expect(broken(s => { s.values!.waiting = { label: "Waiting", kind: "days", value: 3 }; })).toMatch(/"waiting" names a set and a value. One name is one thing/);
  });

  it("hold a filter column's counts to a set the dashboard holds, of what it filters", () => {
    expect(broken(s => { s.elements.filters.props.set = "waiting"; })).toBe("");
    expect(broken(s => { s.elements.filters.props.set = "nowhere"; })).toMatch(/counts within the set "nowhere", which this dashboard does not hold/);
    expect(broken(s => { s.elements.filters.props.set = "lines"; })).toMatch(/filters order and counts within "lines", a set of order_item/);
  });

  it("refuse days that are not a whole number, one or more", () => {
    expect(broken(s => { s.values!.window.value = 2.5; })).toMatch(/counts 2.5 days. Days are a whole number, one or more/);
    expect(broken(s => { s.values!.window.value = 0; })).toMatch(/counts 0 days/);
    expect(broken(s => { s.values!.window.value = 30; })).toBe("");
  });

  it("hold a piece to one thing it reads", () => {
    expect(broken(s => { s.elements.chart.props.entity = "order"; })).toMatch(/names an entity and a set/);
    expect(broken(s => { s.elements.table.props.segment = "returned_orders"; })).toMatch(/A set keeps its own segment/);
    expect(broken(s => { delete s.elements.table.props.set; })).toMatch(/names neither an entity nor a set/);
    expect(broken(s => { s.elements.table.props.set_from = "chosen-order"; })).toMatch(/no figure shows a set there/);
    expect(broken(s => { delete s.elements["fig-late"].props.set; s.elements["fig-late"].props.entity = "order"; })).toMatch(/switches a list reads a set/);
  });

  it("refuse a button whose source is not a chosen or ticked object, or a set that is not there", () => {
    const buttons = (s: CockpitSpec) => (s.elements.buttons.props.buttons as { params: Record<string, unknown>; after?: { read: string[] } }[]);
    expect(broken(s => { buttons(s)[0].params.order = { from: "shown" }; })).toMatch(/not an object a click chooses or ticks collect/);
    expect(broken(s => { buttons(s)[0].params.order = { set: "nowhere" }; })).toMatch(/from the set "nowhere"/);
    expect(broken(s => { buttons(s)[0].after = { read: ["nowhere"] }; })).toMatch(/reads the set "nowhere" again/);
  });

  it("count sets, and still refuse a key a spec does not hold", () => {
    const many = desk();
    for (let i = 0; i < MAX_SETS; i++) many.sets![`extra-${i}`] = { label: `Extra ${i}`, entity: "order" };
    expect(issues(many).join(" ")).toMatch(new RegExp(`It holds at most ${MAX_SETS}`));
    expect(issues({ ...desk(), wires: {} }).join(" ")).toMatch(/The spec carries "wires"/);
  });

  it("leave a dashboard that is not wired exactly as it was judged", () => {
    const plain = desk();
    delete plain.sets; delete plain.values;
    for (const k of ["fig-waiting", "fig-late", "chart", "table", "lines", "buttons", "detail"]) delete plain.elements[k];
    plain.elements.today.children = ["t"];
    plain.elements.t = { type: "ObjectTable", props: { entity: "order", segment: "overdue_dispatch" }, children: [] };
    expect(issues(plain)).toEqual([]);
  });
});

describe("what a press runs", () => {
  const ORDER: ParamDecl = { name: "order", display_name: "Order", data_type: "VARCHAR", required: true, default_value: null, kind: "object", object_type: "order", description: "" };
  const WHO: ParamDecl = { name: "assignee", display_name: "Who has it", data_type: "VARCHAR", required: true, default_value: null, kind: "value", object_type: "", description: "" };
  const WHY: ParamDecl = { name: "reason", display_name: "Reason", data_type: "VARCHAR", required: false, default_value: "", kind: "value", object_type: "", description: "" };
  const ctx = (chosen: string | null, ticked: string[] = []): RunContext => ({
    kindOf: c => (c === "chosen-order" ? "chosen" : c === "ticked-orders" ? "ticked" : c === "shown" ? "shown" : undefined),
    chosen: c => (c === "chosen-order" && chosen ? { pk: chosen, typeId: "Order", objectType: "order" } : null),
    ticked: c => (c === "ticked-orders" ? ticked.map(pk => ({ pk, typeId: "Order", objectType: "order" })) : []),
  });

  it("runs once on the object chosen, asking what the form asks — and not before one is chosen", () => {
    const b = { action: "open_case", params: { order: { from: "chosen-order" }, assignee: { ask: true as const } } };
    expect(planRuns(b, [ORDER, WHO], ctx(null))).toEqual({ blocked: "Choose an order first." });
    const plan = planRuns(b, [ORDER, WHO], ctx("38330"));
    expect(plan).toMatchObject({ fixed: { order: "38330" }, each: null, set: null, asks: [WHO] });
    expect(runsOf(plan as Exclude<typeof plan, { blocked: string }>, { assignee: "Dispatch team" })).toEqual([{ order: "38330", assignee: "Dispatch team" }]);
  });

  it("runs once per ticked object, each its own, at most fifty", () => {
    const b = { action: "flag_for_review", params: { order: { from: "ticked-orders" } } };
    expect(planRuns(b, [ORDER, WHY], ctx(null, []))).toEqual({ blocked: "Tick at least one order." });
    const plan = planRuns(b, [ORDER, WHY], ctx(null, ["1", "2"]));
    expect(runsOf(plan as Exclude<typeof plan, { blocked: string }>, { reason: "" })).toEqual([{ order: "1" }, { order: "2" }]);
    const many = Array.from({ length: MAX_TICKED_RUNS + 1 }, (_, i) => String(i));
    expect(planRuns(b, [ORDER, WHY], ctx(null, many))).toEqual({ blocked: `${MAX_TICKED_RUNS + 1} are ticked; a press runs on at most ${MAX_TICKED_RUNS}.` });
  });

  it("runs on a set's objects as they are read at the press, a value the same every time", () => {
    const b = { action: "flag_for_review", params: { order: { set: "waiting" }, reason: { value: "past the promise" } } };
    const plan = planRuns(b, [ORDER, WHY], ctx(null));
    expect(plan).toMatchObject({ set: { param: "order", set: "waiting" }, fixed: { reason: "past the promise" }, asks: [] });
    expect(runsOf(plan as Exclude<typeof plan, { blocked: string }>, {}, ["7", "8", "9"])).toHaveLength(3);
  });

  it("never guesses an object: an object wired to nothing, or a source no table makes, stops the button and says why", () => {
    expect(planRuns({ action: "x" }, [ORDER], ctx("1"))).toEqual({ blocked: "Order is wired to no chosen object, ticked objects or set." });
    expect(planRuns({ action: "x", params: { order: { from: "shown" } } }, [ORDER], ctx("1"))).toMatchObject({ blocked: expect.stringMatching(/which no table chooses or ticks/) });
    const two = { action: "x", params: { order: { from: "ticked-orders" }, other: { set: "waiting" } } };
    expect(planRuns(two, [ORDER, { ...ORDER, name: "other" }], ctx(null, ["1"]))).toEqual({ blocked: "Two parameters run once per object; one may." });
    const setFirst = { action: "x", params: { order: { set: "waiting" }, other: { from: "ticked-orders" } } };
    expect(planRuns(setFirst, [ORDER, { ...ORDER, name: "other" }], ctx(null, ["1"]))).toEqual({ blocked: "Two parameters run once per object; one may." });
  });

  it("asks what is needed before what may be left", () => {
    const plan = planRuns({ action: "x", params: { order: { from: "chosen-order" } } }, [ORDER, WHY, WHO], ctx("1"));
    expect((plan as { asks: ParamDecl[] }).asks.map(p => p.name)).toEqual(["assignee", "reason"]);
  });

  it("says what a press did — how many ran, how many wait for approval, how many were refused and why", () => {
    expect(pressSaid([{ status: "ran" }], "order")).toBe("Done.");
    expect(pressSaid([{ status: "ran" }, { status: "ran" }], "order")).toBe("Ran on 2 orders.");
    expect(pressSaid([{ status: "proposed" }, { status: "proposed" }], "order")).toBe("2 wait for approval in Actions.");
    expect(pressSaid([{ status: "ran" }, { status: "refused", message: "the order is closed" }], "order"))
      .toBe("Ran on 1 order. 1 refused: the order is closed.");
  });

  it("says a server that failed as a failure, beside what ran — never as a refusal the action made", () => {
    const failed = { status: "failed" as const, message: "the server failed while running it (HTTP 500)" };
    expect(pressSaid([failed], "order")).toBe("It did not run: the server failed while running it (HTTP 500).");
    expect(pressSaid([{ status: "ran" }, failed, failed], "order")).toBe("Ran on 1 order. 2 did not run: the server failed while running it (HTTP 500).");
    expect(pressSaid([{ status: "refused", message: "its criteria did not hold" }, failed], "order"))
      .toBe("1 refused: its criteria did not hold. 1 did not run: the server failed while running it (HTTP 500).");
  });
});

describe("sets and values, by hand", () => {
  it("names a new one from its label, never as anything the dashboard already uses", () => {
    expect(freshWireName(desk(), "Returned recently")).toBe("returned-recently");
    expect(freshWireName(desk(), "Waiting")).toBe("waiting-2");
    expect(freshWireName(desk(), "Chosen order")).toBe("chosen-order-2");
    expect(freshWireName(desk(), "!!!")).toBe("set");
  });

  it("adds and changes a set and a value, and every edit leaves a dashboard the rules accept", () => {
    let s = putSet(desk(), "returned", { label: "Returned", from: "placed", segment: "returned_orders" });
    s = putValue(s, "top", { label: "Top", kind: "number", value: 3 });
    expect(issues(s)).toEqual([]);
    expect(read(s, "returned")).toMatchObject({ entity: "order", segment: "returned_orders" });
  });

  it("takes away only what nothing reads", () => {
    expect(dropWire(desk(), "placed").sets?.placed).toBeDefined();
    expect(dropWire(desk(), "window").values?.window).toBeDefined();
    const s = putSet(desk(), "spare", { label: "Spare", entity: "order" });
    expect(dropWire(s, "spare").sets?.spare).toBeUndefined();
    const lone = putValue({ ...desk(), values: {} }, "spare", { label: "Spare", kind: "text", value: "x" });
    expect("values" in dropWire({ ...lone, sets: { placed: { label: "Placed", entity: "order" } } }, "spare")).toBe(false);
  });
});
