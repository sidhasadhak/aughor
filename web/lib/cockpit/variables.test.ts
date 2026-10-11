/**
 * Variables on a cockpit (Arc AP-8; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9.2): a value comes from its author,
 * the reader on the page, a set's count or a property of the object a reader chose; a set compares any value as its
 * kind allows; and a query of the person's own reads one as `{{name}}`, sent as the page holds it now. The rules hold
 * each value's shape by where it comes from, and refuse a value counted from a set that reads it back.
 */
import { describe, expect, it } from "vitest";

import type { CockpitSpec } from "@/lib/cockpit/edit";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { doorConditions, readSet, readersOf, valueRing, wiring, type SetRead, type ValueNow } from "@/lib/cockpit/sets";
import { typedValue, valueFits, valuesFor, valuesRead } from "@/lib/cockpit/values";

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    values: {
      window: { label: "Window", kind: "days", value: 14, from: { by: "reader", options: [7, 14, 30, 90] } },
      country: { label: "Country", kind: "text", value: "China", from: { by: "reader" } },
      "waiting-count": { label: "Waiting count", kind: "number", from: { by: "count", set: "waiting" } },
      status: { label: "Its status", kind: "text", from: { by: "chosen", choice: "chosen-order", path: "status" } },
      since: { label: "Since", kind: "date", value: "2026-09-01" },
    },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      "in-country": { label: "Waiting in the country", from: "waiting", where: [{ path: "user.country", op: "=", value_from: "country" }] },
      like: { label: "Like the chosen", entity: "order", where: [{ path: "status", op: "=", value_from: "status" }] },
      recent: { label: "Since", entity: "order", where: [{ path: "created_at", op: ">=", value_from: "since" }] },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Sales desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Waiting" }, children: ["table", "country-table"] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order", columns: ["status"] }, children: [] },
      "country-table": { type: "ObjectTable", props: { set: "in-country", columns: ["status"] }, children: [] },
    },
  };
}
const issues = (s: unknown) => checkCockpitSpec(s).issues.map(i => i.message);
const now = (held: Record<string, ValueNow>) => (name: string): ValueNow => held[name] ?? { value: null };

describe("a set reads each value as the page holds it now", () => {
  it("compares the reader's own in place of the one the author set, down every set it starts from", () => {
    const r = readSet(desk(), "in-country", now({ window: { value: 30 }, country: { value: "Brasil" } })) as SetRead;
    expect(r.where).toEqual([{ path: "user.country", op: "=", value: "Brasil" }, { path: "created_at", op: "in_last", value: 30 }]);
    expect(doorConditions(r, () => null)).toEqual({ filters: r.where });
    // with no page to ask, the value it starts from
    expect((readSet(desk(), "in-country") as SetRead).where).toEqual([{ path: "user.country", op: "=", value: "China" },
      { path: "created_at", op: "in_last", value: 14 }]);
  });

  it("waits on the choice a chosen object's value reads, or the value still being read, and says what cannot be read", () => {
    const waiting = readSet(desk(), "like", now({ status: { waiting: "chosen-order" } })) as SetRead;
    expect(doorConditions(waiting, () => null)).toEqual({ waiting: "chosen-order" });
    const reading = readSet(desk(), "like", now({ status: { reading: true } })) as SetRead;
    expect(doorConditions(reading, () => "38330")).toEqual({ reading: true });
    expect(readSet(desk(), "like", now({ status: { refused: "Status is withheld from you: support only" } })))
      .toEqual({ refused: 'The set "like" reads the value "status", which cannot be read: Status is withheld from you: support only' });
    expect((readSet(desk(), "recent", now({ since: { value: "2026-09-01" } })) as SetRead).where)
      .toEqual([{ path: "created_at", op: ">=", value: "2026-09-01" }]);
  });

  it("hands the server each value that is not the author's, and compiles every set with a stand-in of its kind", () => {
    const w = wiring(desk());
    expect(w.values).toEqual({
      window: { by: "reader" }, country: { by: "reader" }, "waiting-count": { by: "count", set: "waiting" },
      status: { by: "chosen", choice: "chosen-order", path: "status", entity: "order" },
    });
    expect(w.sets.like).toEqual({ entity: "order", segment: "", filters: [{ path: "status", op: "=", value: "probe" }] });
    expect(w.sets["in-country"]).toMatchObject({ filters: [{ path: "user.country", op: "=", value: "China" }, { path: "created_at", op: "in_last", value: 14 }] });
  });

  it("says a value counted from a set, or read from a choice, reads that set or choice — so neither is taken away", () => {
    expect(readersOf(desk(), "waiting").values).toEqual(["waiting-count"]);
    expect(readersOf(desk(), "chosen-order").values).toEqual(["status"]);
    expect(readersOf(desk(), "country")).toEqual({ elements: [], sets: ["in-country"], values: [] });
  });
});

describe("the rules a value is held to", () => {
  it("passes the desk: every source, each value of its kind", () => {
    expect(issues(desk())).toEqual([]);
  });

  it.each([
    ["an author's value that holds nothing", { label: "W", kind: "days" }, "holds nothing. A value you set holds one to start from"],
    ["a reader's value that holds nothing", { label: "W", kind: "days", from: { by: "reader" } }, "holds nothing. A value the reader sets holds one"],
    ["a count that holds one of its own", { label: "W", kind: "number", value: 3, from: { by: "count", set: "waiting" } }, "is counted and holds one of its own"],
    ["a chosen object's value that holds one", { label: "W", kind: "text", value: "x", from: { by: "chosen", choice: "chosen-order", path: "status" } }, "is read from the object chosen and holds one"],
    ["a day written another way", { label: "W", kind: "date", value: "11/10/2026" }, "is a day and holds \"11/10/2026\". A day is written 2026-10-11"],
    ["a count that is not a number", { label: "W", kind: "text", from: { by: "count", set: "waiting" } }, "counts a set, so it holds a number — not words"],
    ["a count of a set the cockpit lacks", { label: "W", kind: "number", from: { by: "count", set: "nowhere" } }, "counts the set \"nowhere\", which this cockpit does not hold"],
    ["a property of a choice no click makes", { label: "W", kind: "text", from: { by: "chosen", choice: "nobody", path: "status" } }, "and no click chooses \"nobody\""],
    ["a reader's choice of the wrong kind", { label: "W", kind: "days", value: 7, from: { by: "reader", options: [7, "fortnight"] } }, "holds \"fortnight\". A days holds a number"],
    ["a start that is not among the choices", { label: "W", kind: "days", value: 10, from: { by: "reader", options: [7, 14] } }, "starts from 10, which is not one of the choices it offers"],
    ["the same choice twice", { label: "W", kind: "days", value: 7, from: { by: "reader", options: [7, 7] } }, "offers the same choice twice"],
  ])("refuses %s", (_what, value, says) => {
    const s = desk();
    s.values!.extra = value as never;
    expect(issues(s).join(" ")).toContain(says);
  });

  it("refuses a value compared as its kind does not allow", () => {
    const words = desk();
    words.sets!["in-country"].where = [{ path: "user.country", op: ">", value_from: "country" }];
    expect(issues(words).join(" ")).toContain('the word "country". A word is compared with = or !=');
    const days = desk();
    days.sets!.recent.where = [{ path: "created_at", op: ">=", value_from: "window" }];
    expect(issues(days).join(" ")).toContain('the days "window". Days are counted back by in_last');
    const list = desk();
    list.sets!.recent.where = [{ path: "status", op: "in", value_from: "country" }];
    expect(issues(list).join(" ")).toContain("A value is compared with =, !=, >, >=, <, <= or counted back by in_last");
  });

  it("refuses a value counted from a set that, down the sets and values it reads, reads that value back", () => {
    const s = desk();
    s.sets!.placed.where = [{ path: "item_count", op: ">=", value_from: "waiting-count" }];
    expect(valueRing(s)).toEqual(["waiting-count", "waiting", "placed", "waiting-count"]);
    expect(issues(s).join(" ")).toContain('"waiting-count" → "waiting" → "placed" → "waiting-count" read each other in a ring');
    expect(valueRing(desk())).toBeNull();
  });
});

describe("a query's values", () => {
  it("are the names it reads as {{name}}, each once, in the order it names them — the server's own spelling", () => {
    expect(valuesRead("SELECT {{country}}, {{ window }}, {{country}}, {{Bad}}, {{9x}}, {{chosen-order}}")).toEqual(["country", "window", "chosen-order"]);
    expect(valuesRead(null)).toEqual([]);
  });

  it("are sent as the page holds them now, with their kinds — or what one waits on, or why one cannot be read", () => {
    const defs = desk().values!;
    expect(valuesFor(["country", "window"], defs, now({ country: { value: "Brasil" }, window: { value: 30 } })))
      .toEqual({ values: { country: { kind: "text", value: "Brasil" }, window: { kind: "days", value: 30 } } });
    expect(valuesFor(["status"], defs, now({ status: { waiting: "chosen-order" } }))).toEqual({ waiting: "chosen-order", label: "Its status" });
    expect(valuesFor(["waiting-count"], defs, now({ "waiting-count": { reading: true } }))).toEqual({ reading: true });
    expect(valuesFor(["waiting-count"], defs, now({ "waiting-count": { refused: "The door is down." } })))
      .toEqual({ refused: "It reads Waiting count, which cannot be read: The door is down." });
    expect(valuesFor(["country"], defs, now({ country: { value: "" } }))).toEqual({ refused: "It reads Country, which holds nothing yet." });
    expect(valuesFor(["nowhere"], defs, now({}))).toEqual({ refused: "It reads {{nowhere}}, and this cockpit holds no value of that name." });
  });

  it("take what a reader types only when it is a value of their kind", () => {
    expect([typedValue("days", "14"), typedValue("days", "2.5"), typedValue("days", "0"), typedValue("days", "")]).toEqual([14, null, null, null]);
    expect([typedValue("number", "-2.5"), typedValue("number", "many")]).toEqual([-2.5, null]);
    expect([typedValue("date", "2026-10-11"), typedValue("date", "2026-13-40"), typedValue("date", "11/10/2026")]).toEqual(["2026-10-11", null, null]);
    expect([typedValue("text", "  China "), typedValue("text", "   "), typedValue("text", "x".repeat(121))]).toEqual(["China", null, null]);
    expect(valueFits("number", Number.POSITIVE_INFINITY)).toBe(false);
  });
});
