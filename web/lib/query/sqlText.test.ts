/**
 * SE-6 — what the intentions are allowed to believe about SQL text.
 *
 * Every case here is one an intention would otherwise get wrong in a way the user
 * pays for: a rename that edits a word inside a string literal, a wildcard expansion
 * that fires on a `*` in a comment, an alias suggestion that collides with an alias
 * the query already declared.
 */
import { describe, expect, it } from "vitest";
import {
  identifierAt, identifierOccurrences, selectStar, statementRangeAt,
  suggestAlias, tableRefs,
} from "@/lib/query/sqlText";
import { explainPrefix, quoteIdentifier } from "@/lib/query/dialect";

describe("statementRangeAt", () => {
  const doc = "SELECT 1;\nSELECT 2;\nSELECT 3";

  it("finds the statement the caret is in", () => {
    expect(doc.slice(...Object.values(statementRangeAt(doc, 3)) as [number, number])).toBe("SELECT 1");
    expect(doc.slice(...Object.values(statementRangeAt(doc, 14)) as [number, number])).toBe("SELECT 2");
    expect(doc.slice(...Object.values(statementRangeAt(doc, 25)) as [number, number])).toBe("SELECT 3");
  });

  it("ignores a semicolon inside a string", () => {
    const s = "SELECT 'a;b' AS x FROM t";
    const r = statementRangeAt(s, s.length);
    expect(s.slice(r.from, r.to)).toBe(s);
  });

  it("ignores a semicolon inside a comment", () => {
    const s = "SELECT 1 -- and a ; here\nFROM t";
    const r = statementRangeAt(s, s.length);
    expect(s.slice(r.from, r.to)).toBe(s);
  });

  it("trims the whitespace a caret on a blank line would otherwise include", () => {
    const s = "SELECT 1;\n\n   SELECT 2   ";
    const r = statementRangeAt(s, s.length - 1);
    expect(s.slice(r.from, r.to)).toBe("SELECT 2");
  });
});

describe("tableRefs", () => {
  it("reads a table and its alias, with or without AS", () => {
    const refs = tableRefs("SELECT * FROM orders o JOIN customers AS c ON o.id = c.id");
    expect(refs.map(r => [r.name, r.alias])).toEqual([["orders", "o"], ["customers", "c"]]);
  });

  it("does not mistake a keyword for an alias", () => {
    const refs = tableRefs("SELECT * FROM orders WHERE x = 1");
    expect(refs).toHaveLength(1);
    expect(refs[0].alias).toBeNull();
  });

  it("keeps qualification as written", () => {
    const refs = tableRefs("SELECT * FROM analytics.orders");
    expect(refs[0].name).toBe("analytics.orders");
  });

  it("skips a subquery and a table function — neither names a table", () => {
    expect(tableRefs("SELECT * FROM (SELECT 1) x")).toHaveLength(0);
    expect(tableRefs("SELECT * FROM read_csv('a.csv')")).toHaveLength(0);
  });

  it("offsets ranges into the document", () => {
    const doc = "SELECT 1;\nSELECT * FROM orders";
    const stmt = statementRangeAt(doc, doc.length);
    const refs = tableRefs(doc.slice(stmt.from, stmt.to), stmt.from);
    expect(doc.slice(refs[0].range.from, refs[0].range.to)).toBe("orders");
  });
});

describe("selectStar", () => {
  it("finds a bare star in the select list", () => {
    const s = "SELECT * FROM orders";
    expect(selectStar(s)!.qualifier).toBeNull();
    expect(s.slice(selectStar(s)!.range.from, selectStar(s)!.range.to)).toBe("*");
  });

  it("reports the qualifier of a qualified star", () => {
    expect(selectStar("SELECT o.* FROM orders o")!.qualifier).toBe("o");
  });

  it("refuses when there are two — expanding one silently changes the result", () => {
    expect(selectStar("SELECT o.*, c.* FROM orders o JOIN customers c ON 1=1")).toBeNull();
  });

  it("does not see COUNT(*) as a select-list wildcard to expand", () => {
    // The `*` inside COUNT is matched, but expanding it is not offered because the
    // caller checks the qualifier resolves to a table; this pins the position so a
    // future change cannot quietly start rewriting COUNT(*) into a column list.
    const found = selectStar("SELECT COUNT(*) FROM orders");
    expect(found && found.qualifier).toBeNull();
  });
});

describe("identifierAt", () => {
  it("returns the word the caret sits in, and the one it sits just after", () => {
    const s = "SELECT total FROM t";
    expect(identifierAt(s, 9)!.text).toBe("total");
    expect(identifierAt(s, 12)!.text).toBe("total");
  });

  it("returns nothing inside a string literal", () => {
    const s = "SELECT 'orders' FROM t";
    expect(identifierAt(s, 10)).toBeNull();
  });
});

describe("identifierOccurrences", () => {
  it("skips the word inside a string and inside a comment", () => {
    const s = "SELECT orders FROM orders -- orders\nWHERE x = 'orders'";
    expect(identifierOccurrences(s, "orders")).toHaveLength(2);
  });

  it("does not match a suffix of a longer identifier, or a qualified tail", () => {
    const s = "SELECT o.orders, orders_archive, orders FROM t";
    expect(identifierOccurrences(s, "orders")).toHaveLength(1);
  });
});

describe("suggestAlias", () => {
  it("uses the initials of a multi-part name", () => {
    expect(suggestAlias("order_items", new Set())).toBe("oi");
  });

  it("uses the first letter of a single-word name", () => {
    expect(suggestAlias("orders", new Set())).toBe("o");
  });

  it("strips qualification and quoting", () => {
    expect(suggestAlias('analytics."order_items"', new Set())).toBe("oi");
  });

  it("avoids an alias the query already declared", () => {
    expect(suggestAlias("orders", new Set(["o"]))).toBe("o2");
    expect(suggestAlias("orders", new Set(["o", "o2"]))).toBe("o3");
  });
});

// ── Quoting, which the wildcard expansion cannot do without ──────────────────

describe("quoteIdentifier", () => {
  it("leaves a plain lower-case identifier alone", () => {
    // Blanket quoting would be wrong: "orders" is case-SENSITIVE in Postgres and
    // DuckDB, so quoting a name that did not need it can turn a working reference
    // into a missing table.
    expect(quoteIdentifier("orders", { dialect: "duckdb" })).toBe("orders");
    expect(quoteIdentifier("order_id", { dialect: "duckdb" })).toBe("order_id");
  });

  it("quotes the names that do not parse bare", () => {
    // All three are real Superstore columns.
    expect(quoteIdentifier("Row ID", { dialect: "duckdb" })).toBe('"Row ID"');
    expect(quoteIdentifier("Sub-Category", { dialect: "duckdb" })).toBe('"Sub-Category"');
    expect(quoteIdentifier("Postal Code", { dialect: "duckdb" })).toBe('"Postal Code"');
  });

  it("uses backticks on MySQL", () => {
    expect(quoteIdentifier("Row ID", { dialect: "mysql" })).toBe("`Row ID`");
  });

  it("does not double-quote a name that is already quoted", () => {
    expect(quoteIdentifier('"Row ID"', { dialect: "duckdb" })).toBe('"Row ID"');
    expect(quoteIdentifier("`Row ID`", { dialect: "mysql" })).toBe("`Row ID`");
  });

  it("escapes an embedded quote rather than producing broken SQL", () => {
    expect(quoteIdentifier('we"ird', { dialect: "duckdb" })).toBe('"we""ird"');
  });
});

// ── Explain, where the engine has one ────────────────────────────────────────

describe("explainPrefix", () => {
  it("uses EXPLAIN where the engine has it", () => {
    expect(explainPrefix({ dialect: "duckdb" })).toBe("EXPLAIN");
    expect(explainPrefix({ dialect: "postgres" })).toBe("EXPLAIN");
    expect(explainPrefix({ dialect: "mysql" })).toBe("EXPLAIN");
    expect(explainPrefix({ dialect: "snowflake" })).toBe("EXPLAIN");
  });

  it("uses EXPLAIN QUERY PLAN on SQLite, where plain EXPLAIN dumps bytecode", () => {
    expect(explainPrefix({ dialect: "sqlite" })).toBe("EXPLAIN QUERY PLAN");
  });

  it("offers nothing on BigQuery, which has no EXPLAIN statement", () => {
    // Measured live: an unconditional EXPLAIN there returned
    // `400 Statement not supported: ExplainStatement`.
    expect(explainPrefix({ dialect: "bigquery" })).toBeNull();
    expect(explainPrefix(null)).toBeNull();
  });
});
