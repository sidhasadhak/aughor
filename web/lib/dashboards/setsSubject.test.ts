/**
 * Arc FA-2 and FA-4 in the set algebra (`lib/dashboards/sets.ts`): a set as a reader's page reads it, for the server's
 * reading of "Ask about this set" — an author's value the author's whatever is sent, a reader's theirs while it fits —
 * and a set kept as a segment: its conditions down the sets it starts from with the author's values in place, or a
 * refusal in one sentence for each thing a segment cannot hold.
 */
import { describe, expect, it } from "vitest";

import { readerSet, segmentId, segmentRule, type WireSpec } from "@/lib/dashboards/sets";

const spec = (sets: WireSpec["sets"], values: WireSpec["values"] = {}): WireSpec => ({ sets, values, elements: {} });

const DESK = spec({
  placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
  waiting: { label: "Waiting", from: "placed", where: [{ path: "status", op: "in", values: ["Processing", "Pending"] }, { path: "shipped_at", op: "is_null" }] },
  mine: { label: "Mine", entity: "order", where: [{ path: "status", op: "=", value_from: "status" }] },
  lines: { label: "Its lines", entity: "order_item", linked_to: { choice: "chosen-order", path: "order_id" } },
}, {
  window: { label: "Window", kind: "days", value: 14 },
  status: { label: "Status", kind: "text", value: "Shipped", from: { by: "reader" } },
});

describe("a set as the reader's page reads it", () => {
  it("keeps the author's value whatever the page sends, and takes the reader's while it fits", () => {
    expect(readerSet(DESK, "waiting", { window: 3 }, {})).toEqual({
      entity: "order", segment: "", label: "Waiting",
      filters: [{ path: "status", op: "in", values: ["Processing", "Pending"] }, { path: "shipped_at", op: "is_null" }, { path: "created_at", op: "in_last", value: 14 }],
    });
    expect(readerSet(DESK, "mine", { status: "Cancelled" }, {})).toMatchObject({ filters: [{ path: "status", op: "=", value: "Cancelled" }] });
    expect(readerSet(DESK, "mine", { status: 7 }, {})).toMatchObject({ filters: [{ path: "status", op: "=", value: "Shipped" }] });
    expect(readerSet(DESK, "mine", {}, {})).toMatchObject({ filters: [{ path: "status", op: "=", value: "Shipped" }] });
  });

  it("reads what a chosen object links to from the page's choice, and waits on one it did not send", () => {
    expect(readerSet(DESK, "lines", {}, { "chosen-order": "38330" })).toMatchObject({ entity: "order_item", filters: [{ path: "order_id", op: "=", value: "38330" }] });
    expect(readerSet(DESK, "lines", {}, {})).toEqual({ waiting: "chosen-order" });
    expect(readerSet(DESK, "nothing", {}, {})).toEqual({ refused: "This dashboard holds no set named \"nothing\"." });
  });

  it("says a value the page counts and did not send", () => {
    const counted = spec({ big: { label: "Big", entity: "order", where: [{ path: "items", op: ">=", value_from: "n" }] } },
      { n: { label: "How many", kind: "number", from: { by: "count", set: "big" } } });
    const r = readerSet(counted, "big", {}, {});
    expect(r).toHaveProperty("refused");
    expect((r as { refused: string }).refused).toContain("the page did not send what \"How many\" holds now.");
    expect(readerSet(counted, "big", { n: 12 }, {})).toMatchObject({ filters: [{ path: "items", op: ">=", value: 12 }] });
  });
});

describe("a set kept as a segment", () => {
  it("flattens the conditions down the sets it starts from, with the author's values in place", () => {
    expect(segmentRule(DESK, "waiting")).toEqual({
      entity: "order", label: "Waiting",
      conditions: [{ path: "status", op: "in", values: ["Processing", "Pending"] }, { path: "shipped_at", op: "is_null" },
        { path: "created_at", op: "in_last", value: 14 }],
    });
    expect(segmentId("Waiting past the promise")).toBe("waiting_past_the_promise");
    expect(segmentId("14 days late")).toBe("set_14_days_late");
  });

  it.each([
    ["mine", "The set \"Mine\" reads \"Status\", a value the reader sets on the page, and a segment's conditions are fixed."],
    ["lines", "The set \"Its lines\" is linked to the object a reader chooses, and a segment holds the same objects for everyone."],
  ])("refuses %s in a sentence", (name, sentence) => {
    expect(segmentRule(DESK, name)).toEqual({ refused: sentence });
  });

  it("refuses a set that reaches other objects, is combined, keeps a segment, reads a count or a chosen object, or holds no condition", () => {
    const more = spec({
      base: { label: "Base", entity: "order", where: [{ path: "status", op: "=", value: "Shipped" }] },
      reach: { label: "Their customers", from: "base", traverse: { link: "placed_by", entity: "user" } },
      both: { label: "Both", from: "base", combine: { op: "both", set: "base" } },
      late: { label: "Late", entity: "order", segment: "overdue_dispatch" },
      after: { label: "After late", from: "late", where: [{ path: "status", op: "=", value: "Shipped" }] },
      big: { label: "Big", entity: "order", where: [{ path: "items", op: ">=", value_from: "n" }] },
      picked: { label: "Like it", entity: "order", where: [{ path: "status", op: "=", value_from: "its" }] },
      every: { label: "Every order", entity: "order" },
    }, {
      n: { label: "How many", kind: "number", from: { by: "count", set: "base" } },
      its: { label: "Its status", kind: "text", from: { by: "chosen", choice: "chosen-order", path: "status" } },
    });
    const said = (n: string) => (segmentRule(more, n) as { refused: string }).refused;
    expect(said("reach")).toBe("The set \"Their customers\" gets the objects its objects link to, and a segment keeps one entity's objects by their own properties.");
    expect(said("both")).toBe("The set \"Both\" is combined with another set, and a segment is one list of conditions that all hold.");
    expect(said("after")).toBe("The set \"After late\" starts from \"Late\", which keeps the segment \"overdue dispatch\", and a segment is declared from conditions alone.");
    expect(said("big")).toBe("The set \"Big\" reads \"How many\", which is counted on the page, and a segment's conditions are fixed, never read.");
    expect(said("picked")).toBe("The set \"Like it\" reads \"Its status\" off the object a reader chooses, and a segment's conditions are fixed.");
    expect(said("every")).toBe("The set \"Every order\" keeps no conditions, and a segment is declared from at least one.");
  });
});
