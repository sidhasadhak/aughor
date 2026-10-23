/**
 * A cockpit started from an object (2026-10-10): a reader's filters in the object door's words, a chart's window and
 * axis, how a figure is written, and the cockpit a person's ticks make — always one the cockpit's rules accept.
 */
import { describe, expect, it } from "vitest";

import type { CockpitFromObject } from "@/lib/api";
import {
  anyFilter, cellText, chosenWords, conditionsFor, dayLabel, daysBefore, figureText, onDays, plural, ticks, toggled, windowEnd, type Filters, inLastWindow, propertyLabel, typeWord, dataTypeWord,
} from "@/lib/cockpit/objectView";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { everything, holdsAPiece, objectCockpitSpec } from "@/lib/cockpit/start";

describe("a reader's filters", () => {
  it("choose and unchoose a value, and leave nothing behind when the last one goes", () => {
    let f: Filters = {};
    f = toggled(f, "Order", "status", "Shipped");
    f = toggled(f, "order", "status", "Complete");
    expect(f).toEqual({ order: { status: ["Shipped", "Complete"] } });
    f = toggled(toggled(f, "order", "status", "Shipped"), "order", "status", "Complete");
    expect(f).toEqual({});
    expect(anyFilter(f)).toBe(false);
  });

  it("become `in` conditions — leaving out the one a list is counted for, so choosing one never hides the rest", () => {
    const f: Filters = { order: { status: ["Shipped"], "order_to_user.country": ["China", "Brasil"] } };
    expect(conditionsFor(f, "Order")).toEqual([
      { path: "status", op: "in", values: ["Shipped"] },
      { path: "order_to_user.country", op: "in", values: ["China", "Brasil"] },
    ]);
    expect(conditionsFor(f, "order", "status")).toEqual([{ path: "order_to_user.country", op: "in", values: ["China", "Brasil"] }]);
    expect(conditionsFor(f, "Customer")).toEqual([]);
    expect(chosenWords(f, "order")).toBe("Shipped, China, Brasil");
  });
});

describe("a chart of objects per day", () => {
  const today = new Date(Date.UTC(2026, 9, 10, 15));

  it("ends today, or the day after the last one the objects hold when they stop before it", () => {
    expect(windowEnd("2026-10-12 08:00:00", today)).toBe("2026-10-10");     // rows dated ahead of today
    expect(windowEnd("2024-12-30", today)).toBe("2024-12-31");              // an old dataset
    expect(windowEnd(null, today)).toBe("2026-10-10");
  });

  it("lays rows on every day of its window, a day with none at zero", () => {
    const days = daysBefore("2026-10-10", 3);
    expect(days).toEqual(["2026-10-07", "2026-10-08", "2026-10-09"]);
    expect(onDays(days, [["2026-10-07 00:00:00+00:00", "60"], ["2026-10-09", "496"]])).toEqual([60, 0, 496]);
    expect(dayLabel("2026-09-10")).toBe("Sep 10");
  });

  it("draws a round axis that reaches past the highest bar", () => {
    expect(ticks(1631)).toEqual([0, 1000, 2000]);
    expect(ticks(496)).toEqual([0, 200, 400, 600]);
    expect(ticks(0)).toEqual([0]);
    for (const max of [3, 17, 250, 1631, 98765]) expect(ticks(max).at(-1)).toBeGreaterThanOrEqual(max);
  });
});

describe("a table cell", () => {
  const now = new Date(Date.UTC(2026, 9, 10, 15));

  it("writes a moment short — its time this year, its year otherwise — and in UTC, as the warehouse holds it", () => {
    expect(cellText("2026-10-10 00:32:11+00:00", "TIMESTAMP", now)).toBe("Oct 10, 00:32");
    expect(cellText("2024-05-16 09:49:39+00:00", "TIMESTAMP", now)).toBe("May 16, 2024");
    expect(cellText("2026-09-01", "DATE", now)).toBe("Sep 1");
  });

  it("writes a number with separators and at most two decimals, and nothing as a dash", () => {
    expect(cellText("32.990001678466", "FLOAT64", now)).toBe("32.99");
    expect(cellText("125080", "INT64", now)).toBe("125,080");
    expect(cellText(null, "FLOAT64", now)).toBe("—");
    expect(cellText("Shipped", "STRING", now)).toBe("Shipped");
  });
});

describe("a figure", () => {
  it("writes a count with separators, money short, anything else to two decimals", () => {
    expect(figureText(125080, "count", "number", "$")).toBe("125,080");
    expect(figureText(10804567.74, "sum", "money", "$")).toBe("$10.80M");
    expect(figureText(153, "sum", "money", "€")).toBe("€153.00");
    expect(figureText(1.4503677, "avg", "number", "$")).toBe("1.45");
    expect(figureText(null, "count", "number", "$")).toBe("—");
  });

  it("names a count by its plural", () => {
    expect(["Order", "Category", "Address", "Day"].map(plural)).toEqual(["Orders", "Categories", "Addresses", "Days"]);
  });
});

const PROPOSAL: CockpitFromObject = {
  connection_id: "c", schema_name: "s", entity: "order", type_id: "Order", name: "Order", title: "Orders", total: 125080,
  filters: [
    { path: "status", label: "Status", via: "", values: [["Shipped", 37838], ["Complete", 31335]] },
    { path: "order_to_user.country", label: "Customer country", via: "Customer", values: [["China", 42841]] },
  ],
  figures: [
    { label: "Orders", agg: "count", path: "", format: "number", value: 125080 },
    { label: "Revenue", agg: "sum", path: "revenue", format: "money", value: 10804567.74 },
  ],
  chart: { time: "created_at", label: "Orders per day", days: 30, end: "2026-10-10", bars: [1, 2, 3] },
  table: { columns: ["status", "created_at", "revenue"], labels: ["Status", "Created At", "Revenue"] },
  actions: [{ id: "flag_for_review", label: "Flag for review" }],
  caveats: [],
};

describe("the dashboard a person's ticks make", () => {
  it("lays everything out as the approved mockup does, and the rules accept it", () => {
    const spec = objectCockpitSpec(PROPOSAL, everything(PROPOSAL)) as { root: string; elements: Record<string, { type: string; props: Record<string, unknown>; children: string[] }> };
    expect(checkCockpitSpec(spec).issues).toEqual([]);
    const els = spec.elements;
    expect(els.cockpit.children).toEqual(["filters", "sec"]);
    expect(els.filters.props.properties).toEqual([
      { path: "status", label: "Status" }, { path: "order_to_user.country", label: "Customer country", via: "Customer" }]);
    expect(els.sec.children).toEqual(["figure-0", "figure-1", "chart", "table", "detail"]);
    expect(els.sec.props.title).toBe(els.cockpit.props.title);          // so its heading is not drawn
    expect(els["figure-0"].props).toEqual({ entity: "order", label: "Orders", agg: "count", format: "number", size: "small" });
    expect(els.detail.children).toEqual(["action-flag_for_review"]);
    // the table lists the newest objects first, by the date its chart reads
    expect(els.table.props).toMatchObject({ sort: "created_at", descending: true });
  });

  it("is accepted whatever is left out, as long as something is there to narrow", () => {
    const all = everything(PROPOSAL);
    const choices = [
      { ...all, filters: [] }, { ...all, figures: [], chart: false }, { ...all, table: false, actions: [] },
      { ...all, figures: [1], chart: false, table: false }, { ...all, actions: [] },
    ];
    for (const c of choices) {
      expect(holdsAPiece(c, PROPOSAL)).toBe(true);
      expect(checkCockpitSpec(objectCockpitSpec(PROPOSAL, c)).issues).toEqual([]);
    }
    // nothing to narrow: the starter makes no cockpit of it (an empty section is a builder's, since Arc AP-4, not a start)
    const nothing = { ...all, figures: [], chart: false, table: false };
    expect(holdsAPiece(nothing, PROPOSAL)).toBe(false);
  });
});

describe("a chart over a set that counts its own last days (Arc AP-2)", () => {
  const today = new Date(Date.UTC(2026, 9, 11, 0, 50));                 // 00:50 UTC on 11 October
  it("draws exactly those days, today included — never where the objects happen to stop", () => {
    expect(inLastWindow([{ path: "created_at", op: "in_last", value: 14 }], "created_at", today)).toEqual({ end: "2026-10-12", days: 14 });
    expect(daysBefore("2026-10-12", 14)[0]).toBe("2026-09-28");          // the door's first day: today less 13
  });
  it("is none when the set counts no last days on the chart's own date", () => {
    expect(inLastWindow([{ path: "shipped_at", op: "in_last", value: 14 }], "created_at", today)).toBeNull();
    expect(inLastWindow([{ path: "created_at", op: ">=", value: "2026-09-28" }], "created_at", today)).toBeNull();
    expect(inLastWindow([{ path: "created_at", op: "in_last", value: 2.5 }], "created_at", today)).toBeNull();
    expect(inLastWindow([], "created_at", today)).toBeNull();
  });
});

describe("what a reader reads in a cell or a heading (Arc AP-2, scenarios on theLook)", () => {
  it("writes money the ontology declares as money, and every other number as it was", () => {
    expect(cellText(25, "FLOAT64", undefined, "USD")).toBe("$25.00");
    expect(cellText("35.17", "FLOAT64", undefined, "USD")).toBe("$35.17");
    expect(cellText(35.17, "FLOAT64", undefined, "days")).toBe("35.17");
    expect(cellText(2, "INT64")).toBe("2");
    expect(cellText(63981, "INT64", undefined, "", "key")).toBe("63981");                 // a key, never a quantity
    expect(cellText(63981, "INT64")).toBe("63,981");
  });
  it("spells out a raw property name and keeps one the ontology gives", () => {
    expect(propertyLabel("flagged_for_review")).toBe("Flagged for review");
    expect(propertyLabel("", "order_id")).toBe("Order id");
    expect(propertyLabel("Created At", "created_at")).toBe("Created At");
  });
  it("heads a list's key column by what each row is", () => {
    expect(typeWord("Order")).toBe("Order");
    expect(typeWord("OrderItem")).toBe("Order item");
    expect(typeWord("distribution_center")).toBe("Distribution center");
  });
  it("says a column's type in words, never VARCHAR", () => {
    expect(dataTypeWord("VARCHAR")).toBe("text");
    expect(dataTypeWord("INT64")).toBe("number");
    expect(dataTypeWord("TIMESTAMP")).toBe("date and time");
    expect(dataTypeWord("BOOLEAN")).toBe("yes or no");
  });
});
