import { describe, expect, it } from "vitest";

import {
  asksForAChange, filterWords, lastChangeWords, monthWeeks, monthWords, opsFor, rowNoun, rowsQuery, rowsWord, shiftMonth,
  showDate, showValue, totalWords, typedValue, valueCondition, viewCount, whenWords, type SheetColumn,
} from "./sheets";

const col = (over: Partial<SheetColumn>): SheetColumn => ({
  id: "c1", name: "x", kind: "text", integer: false, description: "", role: "stored", source: "", currency: "",
  choices: [], hidden: false, expression: "", link: null, via: "", of: "", sheet: "", key: "", by: "", how: "",
  made_by: "", ...over,
});

describe("how a sheet's values are shown", () => {
  it("reads a date from its own text, never through the viewer's clock", () => {
    expect(showDate("2017-10-18", false)).toBe("Oct 18, 2017");
    expect(showDate("2017-10-02 10:56:33", true)).toBe("Oct 2, 2017 10:56");
    expect(showDate("2017-10-02 00:30:00", true)).toBe("Oct 2, 2017 00:30");
  });

  it("shows money in the column's currency, and empty as empty — never as zero", () => {
    expect(showValue("118.70", col({ kind: "money", currency: "BRL" }))).toBe("R$118.70");
    expect(showValue("118.70", col({ kind: "money", currency: "" }))).toBe("118.70");
    expect(showValue(null, col({ kind: "money", currency: "BRL" }))).toBe("");
    expect(showValue(99441, col({ kind: "number", integer: true }))).toBe("99,441");
    expect(showValue(true, col({ kind: "yesno" }))).toBe("Yes");
  });

  it("sends Yes/No as a boolean and everything else as typed, empty as a clear", () => {
    expect(typedValue("yes", "yesno")).toBe(true);
    expect(typedValue("No", "yesno")).toBe(false);
    expect(typedValue("  ", "text")).toBeNull();
    expect(typedValue(" 1,234 ", "number")).toBe("1,234");
  });

  it("says a column's totals over the rows shown", () => {
    const money = col({ kind: "money", currency: "BRL" });
    expect(totalWords({ filled: 3, sum: "168.59", average: 56.19666 }, money, 3)).toBe("sum R$168.59 · avg R$56.20");
    expect(totalWords({ filled: 2, earliest: "2016-10-20", latest: "2018-08-13" }, col({ kind: "date" }), 2))
      .toBe("earliest Oct 20, 2016");
    expect(totalWords({ filled: 0 }, money, 4)).toBe("empty");
    expect(totalWords({ filled: 5, distinct: 8 }, col({ kind: "choice" }), 5)).toBe("8 values");
  });
});

describe("filters and views", () => {
  it("offers the ops a kind can answer", () => {
    expect(opsFor("date")).toContain("before");
    expect(opsFor("text")).not.toContain("before");
    expect(opsFor("choice")).toContain("not_in");
  });

  it("says a filter in words", () => {
    const columns = [col({ id: "c3", name: "order_status", kind: "choice" }),
      col({ id: "c5", name: "estimate", kind: "date" })];
    expect(filterWords([{ column: "c3", op: "not_in", value: ["delivered", "canceled"] },
      { column: "c5", op: "before", value: "2018-10-17" }], columns))
      .toBe("order_status is none of delivered, canceled · estimate before Oct 17, 2018");
  });

  it("puts only what is set on the rows URL", () => {
    expect(rowsQuery({})).toBe("");
    expect(rowsQuery({ view: "all", offset: 0, limit: 200 })).toBe("?view=all&limit=200");
    expect(rowsQuery({ filter: [{ column: "c1", op: "is", value: "a" }] }))
      .toBe("?filter=%5B%7B%22column%22%3A%22c1%22%2C%22op%22%3A%22is%22%2C%22value%22%3A%22a%22%7D%5D");
  });

  it("counts a view against its sheet", () => {
    expect(viewCount(1729, 99441)).toBe("1,729 of 99,441 rows");
    expect(viewCount(5, 5)).toBe("5 rows");
  });
});

describe("a question or a change", () => {
  it("reads an instruction as a change and anything else as a question", () => {
    expect(asksForAChange("Flag the ones that still need following up.")).toBe(true);
    expect(asksForAChange("Add a column for who followed up")).toBe(true);
    expect(asksForAChange("Show only the open ones")).toBe(true);
    expect(asksForAChange("How many orders arrived late?")).toBe(false);
    expect(asksForAChange("Which states order the most")).toBe(false);
    expect(asksForAChange("add up the payments?")).toBe(false);   // a question mark asks
  });
});

describe("a sheet's rows in its own words", () => {
  it("calls the rows by the sheet's name, the way its first view does", () => {
    expect(rowNoun("Olist orders")).toBe("orders");
    expect(rowNoun("Budget")).toBe("rows");
    expect(rowsWord(96478, "Olist orders")).toBe("96,478 orders");
    expect(rowsWord(1, "Olist orders")).toBe("1 order");
  });

  it("says a last change plainly: the making by who and when, anything else by what", () => {
    const now = new Date("2026-10-27T12:00:00");
    const made = { id: "a", what: "made from olist_orders_dataset.csv", by: "user:ana", at: "2026-10-27T09:35:00", origin: "" };
    expect(lastChangeWords(made, "user:ana", now)).toBe("made by you · today");
    expect(lastChangeWords(made, "user:bo", now)).toBe("made by ana · today");
    const paid = { ...made, what: "Paid: sum of Olist payments per order_id", at: "2026-10-26T09:00:00" };
    expect(lastChangeWords(paid, "user:bo", now)).toBe("Paid: sum of Olist payments per order_id · ana · yesterday");
    expect(whenWords("2025-03-04T10:00:00", now)).toBe("Mar 4, 2025");
    expect(whenWords("2026-03-04T10:00:00", now)).toBe("Mar 4");
  });
});

describe("a view's layouts", () => {
  it("lays a month out Monday first, with the days outside it blank", () => {
    const weeks = monthWeeks("2018-09");
    expect(weeks[0]).toEqual(["", "", "", "", "", "2018-09-01", "2018-09-02"]);   // the 1st was a Saturday
    expect(weeks.flat().filter(Boolean)).toHaveLength(30);
    expect(weeks.every(w => w.length === 7)).toBe(true);
    expect(shiftMonth("2018-12", 1)).toBe("2019-01");
    expect(shiftMonth("2018-01", -1)).toBe("2017-12");
    expect(monthWords("2018-09")).toBe("September 2018");
  });

  it("narrows to a group's value as the server counted it — empty as empty, never as the text 'null'", () => {
    const status = col({ id: "c3", kind: "choice" });
    expect(valueCondition(status, "shipped")).toEqual({ column: "c3", op: "is", value: "shipped" });
    expect(valueCondition(status, null)).toEqual({ column: "c3", op: "empty" });
  });

  it("says a rule's marks and a day in words, and offers a date and time by its day", () => {
    const est = col({ id: "c5", name: "order_estimated_delivery_date", kind: "date" });
    const rule = { id: "r1", name: "Late", conditions: [], tone: "amber" as const, made_by: "" };
    expect(filterWords([{ column: "", op: "marked", value: "r1" }], [est], [rule])).toBe("marked Late");
    expect(filterWords([{ column: "", op: "marked", value: "gone" }], [est], [rule])).toBe("marked by a rule that was taken off");
    expect(filterWords([{ column: "c5", op: "on", value: "2018-09-04" }], [est])).toBe("order_estimated_delivery_date on Sep 4, 2018");
    expect(opsFor("datetime")[0]).toBe("on");
  });
});
