/**
 * Binding a package's roles from the Semantic Layer (2026-10-13): what the recipes read, which columns can carry it, and
 * what is saved. Fixtures are the retail package's two recipes and LuxExperience's columns.
 */
import { describe, expect, it } from "vitest";

import type { PackDetail } from "@/lib/api";
import { bindingToSave, complete, fits, needsOf, tablesOf } from "@/lib/semanticBind";

const PACK = {
  manifest: { name: "Retail" },
  entities: {
    cart: { description: "A cart.", expects: {}, attributes: { converted_order_id: { type: "id", description: "" } } },
    order_item: { description: "A line.", expects: {}, attributes: {
      returned_at: { type: "timestamp", description: "" }, sale_price: { type: "money", description: "" } } },
  },
  metrics: [],
} as PackDetail;
const RECIPES = [
  { label: "Cart-to-order conversion rate", sql: "SUM(CASE WHEN {{role.cart.converted_order_id}} IS NOT NULL THEN 1 END)" },
  { label: "Return rate", sql: "SUM(CASE WHEN {{ role.order_item.returned_at }} IS NOT NULL THEN 1 END)" },
];

describe("what the recipes read", () => {
  it("is each role once, with only the attributes its recipes name", () => {
    expect(needsOf(RECIPES, PACK)).toEqual([
      { role: "cart", description: "A cart.", recipes: ["Cart-to-order conversion rate"],
        attributes: [{ name: "converted_order_id", type: "id", description: "" }] },
      { role: "order_item", description: "A line.", recipes: ["Return rate"],
        attributes: [{ name: "returned_at", type: "timestamp", description: "" }] },   // never sale_price: no recipe reads it
    ]);
  });
});

describe("which columns can carry an attribute", () => {
  it("takes a date, a time or a day kept as text for a timestamp — never a true/false column", () => {
    expect(fits("timestamp", "DATE", "return_date")).toBe(true);
    expect(fits("timestamp", "TIMESTAMP", "event_time")).toBe(true);
    expect(fits("timestamp", "TEXT", "session_start")).toBe(true);
    expect(fits("timestamp", "BOOLEAN", "returned")).toBe(false);       // IS NOT NULL would count every row
    expect(fits("timestamp", "TEXT", "platform")).toBe(false);
  });

  it("takes a number for money, and anything for an id", () => {
    expect(fits("money", "NUMERIC", "unit_price_eur")).toBe(true);
    expect(fits("money", "TEXT", "unit_price_eur")).toBe(false);
    expect(fits("id", "TEXT", "order_id")).toBe(true);
  });

  it("offers the schema's own tables, or every table when no schema is named", () => {
    const t = [{ name: "lux.a", row_count: null, columns: [] }, { name: "gold.b", row_count: null, columns: [] }];
    expect(tablesOf(t, "lux").map(x => x.name)).toEqual(["lux.a"]);
    expect(tablesOf(t).map(x => x.name)).toEqual(["lux.a", "gold.b"]);
  });
});

describe("what is saved", () => {
  const needs = needsOf(RECIPES, PACK);
  it("is the connection's binding with each role chosen whole laid over it — a half-chosen role is left as it was", () => {
    const existing = { customer: { table: "lux.customers", columns: { customer_id: "customer_id" } } };
    const out = bindingToSave(existing, needs, {
      cart: { table: "lux.web_sessions", columns: { converted_order_id: "order_id" } },
      order_item: { table: "lux.order_items", columns: {} },                       // no column for returned_at
    });
    expect(Object.keys(out).sort()).toEqual(["cart", "customer"]);
    expect(out.cart).toMatchObject({ table: "lux.web_sessions", columns: { converted_order_id: "order_id" }, confidence: 1 });
    expect(out.customer).toBe(existing.customer);
    expect(complete(needs[1], { table: "lux.order_items", columns: {} })).toBe(false);
  });
});
