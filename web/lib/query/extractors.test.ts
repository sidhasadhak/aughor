/**
 * SE-7 — a broken extractor does not look broken. It looks like data, one column to the
 * left of where it belongs, or a string that closes its own quote and becomes SQL.
 * Every case here is one of those.
 */
import { describe, expect, it } from "vitest";
import { EXTRACTORS, extractorById, guessTableName, sqlLiteral } from "@/lib/query/extractors";

const COLS = ["id", "name", "amount"];
const ROWS = [
  [1, "Acme, Inc.", 10.5],
  [2, null, 0],
  [3, "O'Brien\t& Sons\nLtd", -3],
] as const;

const render = (id: string, table?: string) =>
  extractorById(id).render(COLS, ROWS as never, table);

describe("every extractor", () => {
  it("emits a header row and one row per record", () => {
    for (const e of EXTRACTORS) {
      const out = e.render(COLS, ROWS as never);
      expect(out, e.id).toContain("Acme");
      // The apostrophe survives in some form in every format — as itself, or doubled.
      expect(out.includes("O'Brien") || out.includes("O''Brien"), e.id).toBe(true);
    }
  });

  it("never renders NULL as an empty string that reads as ''", () => {
    // CSV and TSV are the exception BY CONVENTION: an empty field is how those formats
    // spell "no value", and quoting the word NULL would make it the four-letter string.
    expect(render("json")).toContain('"name": null');
    expect(render("sql-insert")).toContain("NULL");
    expect(render("markdown")).toContain("∅");
    expect(render("pretty")).toContain("∅");
  });
});

describe("json", () => {
  it("is an array of objects keyed by column name", () => {
    expect(JSON.parse(render("json"))).toEqual([
      { id: 1, name: "Acme, Inc.", amount: 10.5 },
      { id: 2, name: null, amount: 0 },
      { id: 3, name: "O'Brien\t& Sons\nLtd", amount: -3 },
    ]);
  });

  it("keeps a repeated column rather than collapsing it", () => {
    const out = JSON.parse(extractorById("json").render(["a", "a"], [[1, 2]] as never));
    expect(out[0]).toEqual({ a: 1, a_1: 2 });
  });
});

describe("markdown", () => {
  it("escapes a pipe so it cannot end the cell early", () => {
    const out = extractorById("markdown").render(["a"], [["x|y"]] as never);
    expect(out).toContain("x\\|y");
  });

  it("flattens a newline so one value cannot become two rows", () => {
    expect(render("markdown").split("\n")).toHaveLength(5);   // header, rule, 3 rows
  });
});

describe("html", () => {
  it("escapes markup rather than emitting it", () => {
    const out = extractorById("html").render(["a"], [["<script>x</script>"]] as never);
    expect(out).toContain("&lt;script&gt;");
    expect(out).not.toContain("<script>x");
  });
});

describe("sql inserts", () => {
  it("doubles an embedded quote instead of closing the literal", () => {
    expect(sqlLiteral("O'Brien")).toBe("'O''Brien'");
  });

  it("writes numbers and booleans bare, and NULL unquoted", () => {
    expect(sqlLiteral(42)).toBe("42");
    expect(sqlLiteral(true)).toBe("TRUE");
    expect(sqlLiteral(null)).toBe("NULL");
    expect(sqlLiteral(NaN)).toBe("NULL");     // not the string "NaN"
  });

  it("targets the table the caller names and quotes only what needs it", () => {
    expect(render("sql-insert", "orders")).toContain("INSERT INTO orders (id, name, amount)");
    expect(extractorById("sql-insert").render(["Row ID"], [[1]] as never, "Order Items"))
      .toContain('INSERT INTO "Order Items" ("Row ID")');
  });
});

describe("pretty", () => {
  it("pads every column to its widest cell so the table lines up", () => {
    const lines = render("pretty").split("\n");
    // The SECOND column has to begin at the same character offset on every line —
    // that is what "lines up" means, and it is the only thing this format is for.
    const secondStarts = lines.map(l => l.length - l.replace(/^\S*\s+/, "").length);
    expect(new Set(secondStarts).size).toBe(1);
    expect(lines[0]).toMatch(/^id\s+name\s+amount$/);
  });
});

describe("guessTableName", () => {
  it("names the first table the query reads", () => {
    expect(guessTableName("SELECT * FROM analytics.orders o JOIN c ON 1=1")).toBe("analytics.orders");
  });

  it("falls back to something obviously a placeholder", () => {
    expect(guessTableName("SELECT 1")).toBe("my_table");
  });
});
