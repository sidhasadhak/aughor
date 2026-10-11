/**
 * A set read whole (Arc AP-8b; design-mockups/cockpit-builder.html screen 12): a set's linked objects — the customers of
 * the waiting orders — and a set combined with another, in either, in both, or in this one but not that. The one set
 * reader hands the object door each set whole (`in_set` / `not_in_set` with `sets`), so every condition of a set holds
 * on one object; what a nested set waits on — a chosen object, a value still read — waits for the whole.
 */
import { describe, expect, it } from "vitest";

import type { CockpitSpec } from "@/lib/cockpit/edit";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { doorConditions, isRefused, readSet, readersOf, valueRing, wiring, type SetRead, type ValueNow } from "@/lib/cockpit/sets";

const IN_14 = { path: "created_at", op: "in_last", value: 14 };

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    values: { window: { label: "Window", kind: "days", value: 14 }, country: { label: "Country", kind: "text", value: "China", from: { by: "reader" } } },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      customers: { label: "Their customers", from: "waiting", traverse: { link: "placed_by", entity: "user" } },
      chinese: { label: "In the country", entity: "user", where: [{ path: "country", op: "=", value_from: "country" }] },
      ticked: { label: "Ticked", entity: "order", where: [{ path: "status", op: "=", value: "Processing" }] },
      lone: { label: "Waiting, not ticked", from: "waiting", combine: { op: "but_not", set: "ticked" } },
      lines: { label: "Its lines", entity: "order_item", linked_to: { choice: "chosen-order", path: "order_id" } },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Desk" }, children: ["table", "custs"] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order", columns: ["status"] }, children: [] },
      custs: { type: "ObjectTable", props: { set: "customers", columns: ["country"] }, children: [] },
    },
  };
}
const door = (s: CockpitSpec, name: string, chosen: (c: string) => string | null = () => null, valueOf?: (v: string) => ValueNow) =>
  doorConditions(readSet(s, name, valueOf) as SetRead, chosen);
const WAITING = { entity: "order", segment: "overdue_dispatch", filters: [IN_14] };
const issues = (s: unknown) => checkCockpitSpec(s).issues.map(i => i.message);

describe("a set's linked objects", () => {
  it("are of the entity its link reaches, read as one set of its objects: every condition holds on the same order", () => {
    const r = readSet(desk(), "customers") as SetRead;
    expect(r).toMatchObject({ entity: "user", segment: "", chain: ["customers", "waiting", "placed"] });
    expect(door(desk(), "customers")).toEqual({ filters: [{ path: "", op: "in_set", sets: [{ ...WAITING, via: "placed_by" }] }] });
  });

  it("narrow further a set started from them, and hand the server each set the door reads", () => {
    const s = desk();
    s.sets!.far = { label: "Far customers", from: "customers", where: [{ path: "country", op: "=", value: "Brasil" }] };
    expect(door(s, "far")).toEqual({ filters: [{ path: "country", op: "=", value: "Brasil" },
      { path: "", op: "in_set", sets: [{ entity: "user", filters: [{ path: "", op: "in_set", sets: [{ ...WAITING, via: "placed_by" }] }] }] }] });
    expect(wiring(s).sets.far).toMatchObject({ entity: "user", segment: "" });
  });

  it("wait on the object a set inside waits on, and read it once one is chosen", () => {
    const s = desk();
    s.sets!.products = { label: "Its products", from: "lines", traverse: { link: "product", entity: "product" } };
    expect(door(s, "products")).toEqual({ waiting: "chosen-order" });
    expect(door(s, "products", c => (c === "chosen-order" ? "38330" : null))).toEqual({ filters: [{ path: "", op: "in_set",
      sets: [{ entity: "order_item", filters: [{ path: "order_id", op: "=", value: "38330" }], via: "product" }] }] });
  });
});

describe("a set combined with another", () => {
  it("is in both, or in this one but not that, beside its own conditions — or in either, as one condition", () => {
    expect(door(desk(), "lone")).toEqual({ filters: [IN_14, { path: "", op: "not_in_set", sets: [{ entity: "order", filters: [{ path: "status", op: "=", value: "Processing" }] }] }] });
    const s = desk();
    s.sets!.lone.combine = { op: "both", set: "ticked" };
    expect((door(s, "lone") as { filters: { op: string }[] }).filters.map(f => f.op)).toEqual(["in_last", "in_set"]);
    expect((readSet(s, "lone") as SetRead).segment).toBe("overdue_dispatch");                     // its own segment stays its own
    s.sets!.lone.combine = { op: "either", set: "ticked" };
    expect(door(s, "lone")).toEqual({ filters: [{ path: "", op: "in_set", sets: [
      WAITING, { entity: "order", filters: [{ path: "status", op: "=", value: "Processing" }] }] }] });
  });

  it("combines the customers of the waiting orders with the customers in the reader's country", () => {
    const s = desk();
    s.sets!.customers.combine = { op: "both", set: "chinese" };
    expect(door(s, "customers", () => null, v => (v === "country" ? { value: "Japan" } : { value: 14 }))).toEqual({ filters: [
      { path: "", op: "in_set", sets: [{ ...WAITING, via: "placed_by" }] },
      { path: "", op: "in_set", sets: [{ entity: "user", filters: [{ path: "country", op: "=", value: "Japan" }] }] }] });
    // a value it reads that is still read is waited on, whole
    expect(door(s, "customers", () => null, v => (v === "country" ? { reading: true } : { value: 14 }))).toEqual({ reading: true });
  });

  it("refuses a set of other objects, a ring of sets, and reading sets past four deep — each said", () => {
    const other = desk();
    other.sets!.lone.combine = { op: "both", set: "chinese" };
    expect((readSet(other, "lone") as { refused: string }).refused)
      .toBe('The set "lone" holds order objects and is combined with "chinese", which holds user. Sets combined hold the same entity.');
    expect(issues(other).join(" ")).toContain("Sets combined hold the same entity");
    const ring = desk();
    ring.sets!.ticked.combine = { op: "either", set: "lone" };
    expect((readSet(ring, "lone") as { refused: string }).refused).toMatch(/read each other in a ring/);
    expect(valueRing(ring)).toBeNull();
    const self = desk();
    self.sets!.lone.combine = { op: "both", set: "lone" };
    expect(isRefused(readSet(self, "lone"))).toBe(true);
    const deep = desk();
    for (let i = 0; i < 5; i++) deep.sets![`d${i}`] = { label: `D${i}`, entity: "order", combine: { op: "both", set: i ? `d${i - 1}` : "ticked" } };
    expect((readSet(deep, "d4") as { refused: string }).refused).toBe('The set "d4" reads sets more than 4 deep.');
  });

  it("says the set it is combined with reads it — so neither is taken away while the other reads it", () => {
    expect(readersOf(desk(), "ticked").sets).toEqual(["lone"]);
    expect(readersOf(desk(), "waiting").sets).toEqual(["customers", "lone"]);
  });

  it("passes the rules as the desk writes them", () => {
    expect(issues(desk())).toEqual([]);
  });
});
