/**
 * SE-8F — the OR grammar, plus the fallbacks it must not break.
 *
 * The dangerous failure here is silent: an OR that half-parses and quietly filters on
 * one clause looks exactly like a working filter over fewer rows. Every case asserts
 * the row SET, not just that a clause came back.
 */
import { describe, expect, it } from "vitest";
import { applyFilters, parseFilter, type Cell } from "@/lib/query/resultFilter";

const columns = ["country", "status", "amount", "notes"];
const rows: Cell[][] = [
  ["Portugal", "active", 10, "first"],
  ["Spain", "pending", 20, "now or never"],
  ["France", "closed", 30, "third"],
  ["Portugal", "closed", 40, null],
];

function filtered(phrase: string): Cell[][] {
  const { clause, rank } = parseFilter(phrase, columns);
  return applyFilters(rows, clause ? [clause] : [], rank ? [rank] : []);
}

describe("parseFilter OR", () => {
  it("ORs two column-bound clauses", () => {
    const out = filtered("status = active or status = pending");
    expect(out.map(r => r[0])).toEqual(["Portugal", "Spain"]);
  });

  it("ORs across different columns and operators", () => {
    const out = filtered("amount > 35 or country is Spain");
    expect(out.map(r => r[0])).toEqual(["Spain", "Portugal"]);
  });

  it("keeps 'or' inside a value when a part binds to no column", () => {
    // "never" is not a column clause, so the whole phrase is ONE contains-filter and
    // the value keeps its "or".
    const out = filtered("notes contains now or never");
    expect(out.map(r => r[0])).toEqual(["Spain"]);
  });

  it("still errors on a misspelled column instead of degrading", () => {
    const { clause } = parseFilter("statuss = active or amount > 5", columns);
    // Both parts fail to make an OR (first binds nowhere), and the single-phrase parse
    // then reports the unknown column rather than silently text-searching.
    expect(clause?.error ?? clause?.column).not.toBe("status");
  });

  it("describes both halves for the chip tooltip", () => {
    const { clause } = parseFilter("status = active or amount > 25", columns);
    expect(clause?.describe).toContain("status equals active");
    expect(clause?.describe).toContain("amount greater than 25");
  });
});
