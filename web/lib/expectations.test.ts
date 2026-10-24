/** Arc ED, ED-3 — an expectations step's rows to its config and back. */
import { describe, expect, it } from "vitest";

import { blankRow, fromConfig, toConfig, type ExpectationRow } from "./expectations";

const row = (over: Partial<ExpectationRow>): ExpectationRow => ({ ...blankRow(), ...over });

describe("an expectations step's config", () => {
  it("names each row by its column and kind, uniquely, and carries only the values its kind takes", () => {
    const out = toConfig("ecommerce.orders", [
      row({ column: "order_id" }),
      row({ column: "order_id" }),
      row({ kind: "in_list", column: "status", first: " shipped, delivered ", criticality: "error" }),
      row({ kind: "range", column: "total_amount", first: "0", second: "" }),
      row({ kind: "foreign_key", column: "customer_id", first: "customers", second: "customer_id" }),
      row({ kind: "row_count_drift", column: "", first: "20" }),
    ]);
    expect(out.map(x => x.name)).toEqual([
      "order_id not null", "order_id not null 2", "status in list", "total_amount range",
      "customer_id foreign key", "orders row count drift"]);
    expect(out[0]).toEqual({ name: "order_id not null", table: "ecommerce.orders", kind: "not_null",
                             column: "order_id", criticality: "warn" });
    expect(out[2].args).toEqual({ values: ["shipped", "delivered"] });
    expect(out[2].criticality).toBe("error");
    expect(out[3].args).toEqual({ min: 0 });
    expect(out[4].args).toEqual({ references: "customers", references_column: "customer_id" });
    expect(out[5]).not.toHaveProperty("column");
    expect(out[5].args).toEqual({ max_change_pct: 20 });
  });

  it("reads a stored config back into the rows it came from", () => {
    const rows = [row({ kind: "range", column: "total_amount", first: "1", second: "500" }),
                  row({ kind: "freshness", column: "order_date", first: "24" })];
    expect(fromConfig(toConfig("orders", rows))).toEqual({ table: "orders", rows });
    expect(fromConfig(undefined)).toEqual({ table: "", rows: [] });
  });
});
