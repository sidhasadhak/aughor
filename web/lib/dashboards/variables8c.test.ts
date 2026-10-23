/**
 * Arc AP-8c — the rest of the variables (docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9.2): a value of yes or no and a
 * list; a value summed over a set's objects; and one read from the first value of a query the dashboard places (every
 * row's, for a list). A set keeps objects among a list by "in" and "not in", and compares yes or no by "=" and "!=". A
 * query's value is read as its kind says, or the reason it cannot be is said — never a value made up to fill one.
 */
import { describe, expect, it } from "vitest";

import type { DashboardSpec } from "@/lib/dashboards/edit";
import { checkDashboardSpec } from "@/lib/dashboards/rules";
import { readSet, readersOf, readsItself, valueReads, valueRing, wiring, type SetRead, type ValueNow } from "@/lib/dashboards/sets";
import { queryValue, typedValue, valueFits, valueWords, valuesFor } from "@/lib/dashboards/values";

function desk(): DashboardSpec {
  return {
    root: "cockpit",
    values: {
      countries: { label: "Countries", kind: "list", value: ["China", "Brasil"], from: { by: "reader", options: ["China", "Brasil", "Japan"] } },
      late: { label: "Late only", kind: "yesno", value: true },
      spend: { label: "Spend", kind: "number", from: { by: "sum", set: "waiting", path: "total_amount" } },
      top: { label: "Top country", kind: "text", from: { by: "query", card: "c-top" } },
    },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "user.country", op: "in", value_from: "countries" }] },
      waiting: { label: "Waiting", from: "placed", where: [{ path: "is_late", op: "=", value_from: "late" }] },
      "top-orders": { label: "In the top country", entity: "order", where: [{ path: "user.country", op: "=", value_from: "top" }] },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Sales desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Waiting" }, children: ["table", "card"] },
      table: { type: "ObjectTable", props: { set: "waiting", columns: ["status"] }, children: [] },
      card: { type: "Card", props: { card: "c-top" }, children: [] },
    },
  };
}
const issues = (s: unknown) => checkDashboardSpec(s).issues.map(i => i.message);
const now = (held: Record<string, ValueNow>) => (name: string): ValueNow => held[name] ?? { value: null };

describe("a value of yes or no, and a list", () => {
  it("fits, is typed, and is said as its kind", () => {
    expect([valueFits("yesno", true), valueFits("yesno", "yes"), valueFits("yesno", 1)]).toEqual([true, false, false]);
    expect(valueFits("list", ["a", 2])).toBe(true);
    expect([valueFits("list", []), valueFits("list", ["a", "a"]), valueFits("list", ["a", true]), valueFits("list", "a"),
      valueFits("list", Array.from({ length: 31 }, (_, i) => i))]).toEqual([false, false, false, false, false]);
    expect(typedValue("list", " China, 3 ,China, ,Japan")).toEqual(["China", 3, "Japan"]);
    expect(typedValue("list", " , ")).toBeNull();
    expect([typedValue("yesno", "Yes"), typedValue("yesno", "no"), typedValue("yesno", "maybe")]).toEqual([true, false, null]);
    expect([valueWords("yesno", false), valueWords("list", ["a", 2]), valueWords("number", 3)]).toEqual(["No", "a, 2", "3"]);
  });

  it("a set keeps objects among a list, and compares yes or no", () => {
    const r = readSet(desk(), "waiting", now({ countries: { value: ["Japan"] }, late: { value: false } })) as SetRead;
    expect(r.where).toEqual([{ path: "is_late", op: "=", value: false }, { path: "user.country", op: "in", values: ["Japan"] }]);
    // with no page to ask, the ones the author starts from
    expect((readSet(desk(), "placed") as SetRead).where).toEqual([{ path: "user.country", op: "in", values: ["China", "Brasil"] }]);
  });

  it("refuses a list compared but by in or not_in, and in with a value that is not a list — said once", () => {
    const eq = desk();
    eq.sets!.placed.where = [{ path: "user.country", op: "=", value_from: "countries" }];
    expect(issues(eq).join(" ")).toContain('compares user.country with the list "countries". A list keeps objects among it: in or not_in.');
    const among = desk();
    among.sets!.placed.where = [{ path: "user.country", op: "not_in", value_from: "late" }];
    const said = issues(among).join(" ");
    expect(said).toContain('keeps user.country among the value "late", which is not a list');
    expect(said.match(/not a list/g)).toHaveLength(1);
    const ordered = desk();
    ordered.sets!.waiting.where = [{ path: "is_late", op: ">", value_from: "late" }];
    expect(issues(ordered).join(" ")).toContain('the yes or no "late". Yes or no is compared with = or !=.');
  });

  it("holds what its kind holds, and a reader's list starts among the choices offered", () => {
    expect(issues(desk())).toEqual([]);
    const word = desk();
    word.values!.late = { label: "Late only", kind: "yesno", value: "yes" };
    expect(issues(word).join(" ")).toContain('The value "late" is yes or no and holds "yes".');
    const offered = desk();
    offered.values!.late = { label: "Late only", kind: "yesno", value: true, from: { by: "reader", options: ["maybe"] } };
    expect(issues(offered).join(" ")).toContain("the reader chooses Yes or No, and it offers no other choices");
    const empty = desk();
    empty.values!.countries = { label: "Countries", kind: "list", value: [] };
    expect(issues(empty).join(" ")).toContain('The value "countries" is a list and holds []');
    const stray = desk();
    stray.values!.countries = { ...stray.values!.countries, value: ["China", "Peru"] };
    expect(issues(stray).join(" ")).toContain('starts from ["Peru"], which is not one of the choices it offers');
    const scalar = desk();
    scalar.values!.top = { label: "Top", kind: "text", value: ["a"] };
    expect(issues(scalar).join(" ")).toContain('The value "top" is words and holds a list.');
    const boolWord = desk();
    boolWord.values!.top = { label: "Top", kind: "text", value: true };
    expect(issues(boolWord).join(" ")).toContain('The value "top" is words and holds yes.');
  });
});

describe("a value summed over a set", () => {
  it("is a number over a set the dashboard holds, holds none of its own, and reads its set", () => {
    const words = desk();
    words.values!.spend = { label: "Spend", kind: "text", from: { by: "sum", set: "waiting", path: "total_amount" } };
    expect(issues(words).join(" ")).toContain('The value "spend" sums a set, so it holds a number — not words.');
    const gone = desk();
    gone.values!.spend = { label: "Spend", kind: "number", from: { by: "sum", set: "nowhere", path: "total_amount" } };
    expect(issues(gone).join(" ")).toContain('The value "spend" sums the set "nowhere", which this dashboard does not hold.');
    const own = desk();
    own.values!.spend = { label: "Spend", kind: "number", value: 3, from: { by: "sum", set: "waiting", path: "total_amount" } };
    expect(issues(own).join(" ")).toContain('The value "spend" is summed from a set and holds one of its own.');
    expect(readersOf(desk(), "waiting").values).toEqual(["spend"]);
  });

  it("refuses a sum over a set that reads it back, and tells the server the property and the entity it sums", () => {
    const ring = desk();
    ring.sets!.waiting.where = [{ path: "total_amount", op: ">=", value_from: "spend" }];
    expect(valueRing(ring)).toEqual(["spend", "waiting", "spend"]);
    expect(issues(ring).join(" ")).toContain("read each other in a ring: a value counted or summed from a set that reads it");
    expect(wiring(desk()).values.spend).toEqual({ by: "sum", set: "waiting", path: "total_amount", entity: "order" });
  });
});

describe("a value read from a query", () => {
  it("reads a card the dashboard places, never days, and holds none of its own", () => {
    const loose = desk();
    loose.values!.top = { label: "Top", kind: "text", from: { by: "query", card: "c-gone" } };
    expect(issues(loose).join(" ")).toContain('The value "top" reads the query "c-gone", which this dashboard does not place.');
    const days = desk();
    days.values!.top = { label: "Top", kind: "days", from: { by: "query", card: "c-top" } };
    expect(issues(days).join(" ")).toContain("a query's value is a number, not days");
    expect(wiring(desk()).values.top).toEqual({ by: "query", card: "c-top", kind: "text" });
  });

  it("is the first row's value of its column, as its kind — or why it cannot be", () => {
    const run = { columns: ["country", "n"], rows: [["China", "480"], ["Brasil", "235"]], error: null };
    expect(queryValue("text", null, run)).toEqual({ value: "China" });
    expect(queryValue("number", "n", run)).toEqual({ value: 480 });
    expect(queryValue("list", "country", run)).toEqual({ value: ["China", "Brasil"] });
    expect(queryValue("yesno", null, { columns: ["late"], rows: [[true]] })).toEqual({ value: true });
    expect(queryValue("date", null, { columns: ["d"], rows: [["2026-10-11T00:00:00"]] })).toEqual({ value: "2026-10-11" });
    expect(queryValue("number", "nope", run)).toEqual({ refused: "The query returns no column nope." });
    expect(queryValue("number", null, run)).toEqual({ refused: 'The query\'s first value is "China", not a number.' });
    expect(queryValue("text", null, { columns: ["c"], rows: [] })).toEqual({ refused: "The query returns no row." });
    expect(queryValue("text", null, { columns: ["c"], rows: [[null]] })).toEqual({ refused: "The query's first value is empty." });
    expect(queryValue("text", null, { error: "Table orders not found" })).toEqual({ refused: "The query failed: Table orders not found" });
    expect(queryValue("list", null, { columns: ["c"], rows: Array.from({ length: 31 }, (_, i) => [i]) }))
      .toEqual({ refused: "The query returns 31 rows, and a list holds at most 30." });
    expect(queryValue("text", null, null)).toEqual({ refused: "The query did not run." });
  });

  it("reads the values its query reads, and one that reads itself back is a ring", () => {
    const sqlOf = (sql: string) => (card: string) => (card === "c-top" ? sql : undefined);
    expect(valueReads(desk(), "top", sqlOf("SELECT c FROM t WHERE c IN ({{countries}})"))).toEqual(["countries"]);
    expect(valueReads(desk(), "spend")).toEqual(["late", "countries"]);
    expect(readsItself(desk(), "top", sqlOf("SELECT {{countries}}"))).toBeNull();
    expect(readsItself(desk(), "top", sqlOf("SELECT {{top}}"))).toEqual(["top", "top"]);
    const through = desk();
    through.values!.countries = { label: "Countries", kind: "list", from: { by: "query", card: "c-list" } };
    const both = (card: string) => (card === "c-top" ? "SELECT {{countries}}" : card === "c-list" ? "SELECT c FROM t WHERE {{top}} = c" : undefined);
    expect(readsItself(through, "top", both)).toEqual(["top", "countries", "top"]);
  });

  it("a query reading a list is sent the list; an empty one holds nothing yet", () => {
    const defs = { countries: { kind: "list", label: "Countries" } };
    expect(valuesFor(["countries"], defs, now({ countries: { value: ["China"] } })))
      .toEqual({ values: { countries: { kind: "list", value: ["China"] } } });
    expect(valuesFor(["countries"], defs, now({ countries: { value: [] } })))
      .toEqual({ refused: "It reads Countries, which holds nothing yet." });
  });
});
