import { describe, expect, it } from "vitest";

import { cellOrigin } from "./SheetGrid";
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
