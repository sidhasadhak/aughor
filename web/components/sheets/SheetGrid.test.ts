import { describe, expect, it } from "vitest";

import { cellOrigin, navTarget, planClear, planPaste, rangeOf, rangeWords, width } from "./SheetGrid";
import type { Sheet, SheetColumn } from "@/lib/sheets";

const col = (over: Partial<SheetColumn>): SheetColumn => ({
  id: "c1", name: "order_status", kind: "choice", integer: false, description: "", role: "stored", source: "order_status",
  currency: "", choices: [], hidden: false, expression: "", link: null, via: "", of: "", sheet: "", key: "", by: "",
  how: "", made_by: "", ...over,
});
const SHEET = {
  me: "user:ana", source: { kind: "file", file: "olist_orders_dataset.csv", rows: 99441 },
  columns: [col({ id: "c2", name: "customer_id", source: "customer_id", kind: "link" })],
} as unknown as Sheet;

describe("the cell bar says where a value came from, from what the grid holds", () => {
  it("names the file's row for a value as imported", () => {
    expect(cellOrigin(SHEET, col({}), 7)).toBe("Imported from olist_orders_dataset.csv, row 7 · not changed since");
  });

  it("names who set it, and how many times it changed", () => {
    expect(cellOrigin(SHEET, col({}), 7, { by: "user:ana", at: "2026-10-27T09:00:00Z", version: 1 }))
      .toMatch(/^Set by you · .+$/);
    expect(cellOrigin(SHEET, col({}), 7, { by: "user:bo", at: "2026-10-27T09:00:00Z", version: 3 }))
      .toMatch(/^Set by bo · .+ · changed 3 times$/);
  });

  it("says what a derived value is read from, and a row added in the sheet", () => {
    expect(cellOrigin(SHEET, col({ role: "computed", expression: "price * 2" }), 1)).toBe("Computed from price * 2");
    expect(cellOrigin(SHEET, col({ role: "lookup", via: "c2" }), 1)).toBe("Read from another sheet through customer_id");
    expect(cellOrigin(SHEET, col({ role: "total", description: "the sum of payment_value" }), 1)).toBe("The sum of payment_value");
    expect(cellOrigin(SHEET, col({}), 99442)).toBe("Typed in");
  });
});

describe("a range of cells", () => {
  const cols = ["c1", "c2", "c3"];
  it("runs from where Shift began to the active cell, in either direction, and one cell is no range", () => {
    expect(rangeOf({ row: 9, column: "c3", index: 8 }, { row: 3, column: "c1", index: 2 }, cols))
      .toEqual({ rows: [2, 8], cols: [0, 2] });
    expect(rangeOf({ row: 3, column: "c2", index: 2 }, { row: 3, column: "c2", index: 2 }, cols)).toBeNull();
    // the grouped grid places no row in the view, so its selection is one cell
    expect(rangeOf({ row: 3, column: "c1" }, { row: 9, column: "c3" }, cols)).toBeNull();
  });

  it("says its size, and sums money in its currency over the rows read — saying when some were not", () => {
    const price = col({ id: "c2", name: "price", kind: "money", currency: "BRL" });
    const range = { rows: [0, 2] as [number, number], cols: [1, 1] as [number, number] };
    expect(rangeWords(range, { cols: [price], rows: [["10.00"], ["20.50"], [null]], unread: 0 }))
      .toBe("3 rows × 1 column · 3 cells · sum R$30.50 of 2 values");
    expect(rangeWords(range, { cols: [price], rows: [["10.00"]], unread: 2 }))
      .toBe("3 rows × 1 column · 3 cells · sum R$10.00 of 1 value in the 1 row read");
    const status = col({ id: "c1", kind: "choice" });
    expect(rangeWords({ rows: [0, 1], cols: [0, 1] }, { cols: [status, price], rows: [["a", "1"], ["b", "2"]], unread: 0 }))
      .toBe("2 rows × 2 columns · 4 cells");
  });
});

describe("the keys move as a spreadsheet's do", () => {
  const view = { rows: 1000, cols: 11, page: 20 };
  const at = { index: 50, col: 4 };
  const plain = { meta: false, shift: false };
  const meta = { meta: true, shift: false };
  it("Tab and Shift+Tab go across, held at the ends", () => {
    expect(navTarget("Tab", at, view, plain)).toEqual({ index: 50, col: 5 });
    expect(navTarget("Tab", at, view, { meta: false, shift: true })).toEqual({ index: 50, col: 3 });
    expect(navTarget("Tab", { index: 50, col: 10 }, view, plain)).toEqual({ index: 50, col: 10 });
  });
  it("Home and End go to the row's ends; with Cmd or Ctrl, to the view's first and last cell", () => {
    expect(navTarget("Home", at, view, plain)).toEqual({ index: 50, col: 0 });
    expect(navTarget("End", at, view, plain)).toEqual({ index: 50, col: 10 });
    expect(navTarget("Home", at, view, meta)).toEqual({ index: 0, col: 0 });
    expect(navTarget("End", at, view, meta)).toEqual({ index: 999, col: 10 });
  });
  it("Cmd or Ctrl with an arrow goes to that edge; Page Up and Down a screen of rows", () => {
    expect(navTarget("ArrowDown", at, view, meta)).toEqual({ index: 999, col: 4 });
    expect(navTarget("ArrowUp", at, view, meta)).toEqual({ index: 0, col: 4 });
    expect(navTarget("ArrowRight", at, view, meta)).toEqual({ index: 50, col: 10 });
    expect(navTarget("PageDown", at, view, plain)).toEqual({ index: 70, col: 4 });
    expect(navTarget("PageUp", { index: 5, col: 4 }, view, plain)).toEqual({ index: 0, col: 4 });
    expect(navTarget("a", at, view, plain)).toBeNull();
  });
});

describe("a paste lays the clipboard's cells from the active cell", () => {
  const cols = [col({ id: "a", name: "order_id", kind: "text" }), col({ id: "b", name: "Paid", kind: "money" }),
    col({ id: "c", name: "Days overdue", kind: "number", role: "computed" }), col({ id: "d", name: "Followed up", kind: "yesno" })];
  const rowAt = (i: number) => (i < 100 ? [i + 1] : undefined);     // rows 0..99 read; the view holds 150
  const view = { columns: cols, rows: 150, rowAt };

  it("down and across, each value read as its column's kind, the range it covers said", () => {
    const plan = planPaste("o1\t12.50\no2\t7\r\n", { index: 3, col: 0 }, null, view);
    expect(plan.cells).toEqual([
      { row: 4, column: "a", value: "o1" }, { row: 4, column: "b", value: "12.50" },
      { row: 5, column: "a", value: "o2" }, { row: 5, column: "b", value: "7" },
    ]);
    expect(plan.covers).toEqual({ rows: [3, 4], cols: [0, 1] });
    expect(plan.left).toEqual([]);
  });

  it("one value over a range fills it", () => {
    const plan = planPaste("yes", { index: 0, col: 3 }, { rows: [0, 2], cols: [3, 3] }, view);
    expect(plan.cells.map(c => [c.row, c.value])).toEqual([[1, true], [2, true], [3, true]]);
  });

  it("says what it left out: a computed column, columns past the last, rows past the end and rows not read", () => {
    expect(planPaste("x\ty\tz", { index: 0, col: 1 }, null, view).left).toContain("Days overdue keeps its own values");
    expect(planPaste("1\t2\t3", { index: 0, col: 2 }, null, view).left)
      .toEqual(["1 column past the last shown was left out", "Days overdue keeps its own values"]);
    expect(planPaste("a\nb\nc", { index: 148, col: 0 }, null, view).left)
      .toEqual(["1 row past the last row was left out", "2 rows not read yet were left out"]);
  });
});

describe("Delete empties the cells people fill", () => {
  const cols = [col({ id: "a", name: "order_id", kind: "text" }), col({ id: "c", name: "Days overdue", role: "computed" })];
  it("every cell of the range, a computed column kept and said, rows not read left as they are", () => {
    const plan = planClear({ rows: [98, 101], cols: [0, 1] }, { columns: cols, rowAt: (i: number) => (i < 100 ? [i + 1] : undefined) });
    expect(plan.cells).toEqual([{ row: 99, column: "a", value: null }, { row: 100, column: "a", value: null }]);
    expect(plan.left).toEqual(["2 rows not read yet were left as they are", "Days overdue keeps its own values"]);
  });
});

describe("a width the person gave a column", () => {
  it("wins over its kind's, held between the least and the most", () => {
    expect(width({ ...col({ kind: "text" }), width: 333 })).toBe(333);
    expect(width({ ...col({ kind: "text" }), width: 5 })).toBe(60);
    expect(width({ ...col({ kind: "text" }), width: 5000 })).toBe(800);
    expect(width(col({ kind: "yesno", name: "ok" }))).toBe(90);
  });
});
