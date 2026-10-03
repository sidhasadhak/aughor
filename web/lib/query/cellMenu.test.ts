/**
 * DE-5b / DE-5c (ROADMAP §3.51) — the cell menu and value picker SPEAK the filter grammar.
 *
 * The receipt that matters is the round trip: a phrase the menu writes for a cell, parsed by
 * the same grammar the chip bar uses, must select exactly the rows that hold that cell's
 * value — including values with commas, quotes and the word `or`, which an unquoted phrase
 * would split or misread.
 */
import { describe, expect, it } from "vitest";
import {
  distinctFromRows, filterPhrase, jsonLiteral, phraseValue, pickedPhrase, singleTable, sqlLiteral,
} from "./cellMenu";
import { applyFilters, parseFilter, type Cell } from "./resultFilter";

const COLS = ["status", "total", "note"];
const ROWS: Cell[][] = [
  ["Complete", 10, "a"],
  ["Shipped", 5, null],
  ["Complete", 7, "now or never"],
  [null, 1, "x, y"],
  ["", 2, 'say "hi"'],
];

/** The rows the chip bar would show for one phrase. */
function select(phrase: string): Cell[][] {
  const { clause, rank } = parseFilter(phrase, COLS);
  expect(clause?.error, phrase).toBeUndefined();
  return applyFilters(ROWS, clause ? [clause] : [], rank ? [rank] : []);
}

describe("filterPhrase round-trips through the grammar", () => {
  it("filter to this value selects the rows holding it", () => {
    expect(filterPhrase("status", "Complete", "is")).toBe('status = "Complete"');
    expect(select(filterPhrase("status", "Complete", "is"))).toEqual([ROWS[0], ROWS[2]]);
  });

  it("exclude this value drops only the rows holding it", () => {
    expect(filterPhrase("status", "Complete", "isnot")).toBe('status != "Complete"');
    expect(select(filterPhrase("status", "Complete", "isnot"))).toEqual([ROWS[1], ROWS[3], ROWS[4]]);
  });

  it("a number is a number again on the far side", () => {
    expect(select(filterPhrase("total", 10, "is"))).toEqual([ROWS[0]]);
    expect(select(filterPhrase("total", 7, "isnot"))).toHaveLength(4);
  });

  it("null tests are the grammar's null tests, and a NULL cell's filter-to IS the null test", () => {
    expect(filterPhrase("status", "Complete", "null")).toBe("status is null");
    expect(filterPhrase("status", "Complete", "notnull")).toBe("status is not null");
    expect(filterPhrase("status", null, "is")).toBe("status is null");
    expect(filterPhrase("status", null, "isnot")).toBe("status is not null");
    // The grammar counts "" with NULL on purpose (resultFilter.ts: isnull); the menu inherits that.
    expect(select("status is null")).toEqual([ROWS[3], ROWS[4]]);
    expect(select("status is not null")).toEqual([ROWS[0], ROWS[1], ROWS[2]]);
  });

  it("a value with a comma, a quote or the word `or` stays ONE value", () => {
    expect(select(filterPhrase("note", "now or never", "is"))).toEqual([ROWS[2]]);
    expect(select(filterPhrase("note", "x, y", "is"))).toEqual([ROWS[3]]);
    expect(phraseValue('say "hi"')).toBe("'say \"hi\"'");
    expect(select(filterPhrase("note", 'say "hi"', "is"))).toEqual([ROWS[4]]);
  });

  it("names the column exactly as the result spells it", () => {
    expect(filterPhrase("Order Date", "2024-01-01", "is")).toBe('Order Date = "2024-01-01"');
    const { clause } = parseFilter(filterPhrase("Order Date", "x", "is"), ["id", "Order Date"]);
    expect(clause?.column).toBe("Order Date");
  });
});

describe("pickedPhrase", () => {
  it("one value is `=`, several are `in`", () => {
    expect(pickedPhrase("status", ["Complete"])).toBe('status = "Complete"');
    expect(pickedPhrase("status", ["Complete", "Shipped"])).toBe('status in "Complete", "Shipped"');
    expect(select(pickedPhrase("status", ["Complete", "Shipped"]))).toEqual([ROWS[0], ROWS[1], ROWS[2]]);
  });

  it("a picked NULL rides as an or-clause the grammar's OR accepts", () => {
    const phrase = pickedPhrase("status", ["Shipped", null]);
    expect(phrase).toBe('status = "Shipped" or status is null');
    expect(select(phrase)).toEqual([ROWS[1], ROWS[3], ROWS[4]]);
    expect(pickedPhrase("status", [null])).toBe("status is null");
  });

  it("a value `in` would split or drop is said as its own clause", () => {
    // `in` splits on commas and drops an empty entry — so these go through `=` instead.
    const phrase = pickedPhrase("note", ["x, y", "a"]);
    expect(phrase).toBe('note = "x, y" or note = "a"');
    expect(select(phrase)).toEqual([ROWS[0], ROWS[3]]);
    expect(pickedPhrase("status", ["", "Shipped"])).toBe('status = "" or status = "Shipped"');
  });

  it("nothing picked is an empty phrase", () => {
    expect(pickedPhrase("status", [])).toBe("");
  });
});

describe("copy forms", () => {
  it("sqlLiteral quotes and escapes text, leaves numbers and booleans bare, says NULL", () => {
    expect(sqlLiteral("it's")).toBe("'it''s'");
    expect(sqlLiteral(10)).toBe("10");
    expect(sqlLiteral(true)).toBe("TRUE");
    expect(sqlLiteral(null)).toBe("NULL");
    expect(sqlLiteral(Number.NaN)).toBe("NULL");
  });

  it("jsonLiteral pretty-prints a cell that already holds JSON and quotes any other text", () => {
    expect(jsonLiteral('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(jsonLiteral("[1,2]")).toBe("[\n  1,\n  2\n]");
    expect(jsonLiteral("{not json")).toBe('"{not json"');
    expect(jsonLiteral(null)).toBe("null");
    expect(jsonLiteral(3)).toBe("3");
  });
});

describe("distinctFromRows", () => {
  it("counts each value, most frequent first, and keeps NULL apart from the empty string", () => {
    expect(distinctFromRows(ROWS, 0)).toEqual([
      { value: "Complete", count: 2 },
      { value: "", count: 1 },
      { value: "Shipped", count: 1 },
      { value: null, count: 1 },
    ]);
  });

  it("keeps a number apart from its text twin", () => {
    const rows: Cell[][] = [[1], ["1"], [1]];
    expect(distinctFromRows(rows, 0)).toEqual([{ value: 1, count: 2 }, { value: "1", count: 1 }]);
  });

  it("treats a short row as NULL in the missing column, and lists NULL after a real value of the same count", () => {
    expect(distinctFromRows([["a"], ["b", "c"]], 1)).toEqual([{ value: "c", count: 1 }, { value: null, count: 1 }]);
  });
});

describe("singleTable — the one table a statement reads, or null", () => {
  it("names a bare, schema-qualified or quoted table", () => {
    expect(singleTable("select * from orders")).toEqual({ table: "orders", schema: undefined });
    expect(singleTable("SELECT a, b FROM shop.orders WHERE x = 1 LIMIT 10")).toEqual({ table: "orders", schema: "shop" });
    expect(singleTable('select * from "shop"."orders"')).toEqual({ table: "orders", schema: "shop" });
    expect(singleTable("select * from `p.d.t`")).toEqual({ table: "t", schema: "d" });
    expect(singleTable("select * from [dbo].[orders]")).toEqual({ table: "orders", schema: "dbo" });
  });

  it("is null for a join, a set operation, a CTE, a subquery or no FROM at all", () => {
    expect(singleTable("select * from a join b on a.id = b.id")).toBeNull();
    expect(singleTable("select * from a union all select * from b")).toBeNull();
    expect(singleTable("with t as (select 1) select * from t")).toBeNull();
    expect(singleTable("select * from (select * from orders) x")).toBeNull();
    expect(singleTable("select 1")).toBeNull();
    expect(singleTable("")).toBeNull();
  });

  it("is null when two FROMs appear, and ignores a FROM inside a comment", () => {
    expect(singleTable("select * from a where id in (select id from b)")).toBeNull();
    expect(singleTable("-- from legacy\nselect * from orders /* not from here */")).toEqual({ table: "orders", schema: undefined });
  });
});
