// @vitest-environment jsdom
/**
 * A result of one row is its figures, read in a line — not a table (2026-10-02): "if it's a single
 * number being displayed, does one really need a table? How un-intelligent is that?" Q1's units sold
 * and revenue each came back as one cell and were drawn as collapsed one-row tables with a totals
 * toggle and copy buttons around a single value.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FindingFigures, figureValue, isOneRecord, isStated, unstatedFigures } from "@/components/FindingFigures";
import { setOrgSettingsCache } from "@/lib/orgSettings";
import type { OrgSettings } from "@/lib/api";

afterEach(() => setOrgSettingsCache(null));

describe("one value as a figure", () => {
  it("as its table cell would read — money to the cent, a share as a percentage, a key as written", () => {
    setOrgSettingsCache({ currency_code: "USD" } as OrgSettings);
    expect(figureValue("total_revenue", "359224.30043935776")).toBe("$359,224.30");
    expect(figureValue("monthly_revenue", "117163.3701043129")).toBe("$117,163.37");  // names a month; is money
    expect(figureValue("units_sold", "7027")).toBe("7,027");
    expect(figureValue("repeat_rate", "0.0937")).toBe("9.4%");
    expect(figureValue("year", "2025")).toBe("2025");
    expect(figureValue("category", "Jeans")).toBe("Jeans");
    expect(figureValue("units_sold", null)).toBe("—");
  });
});

describe("what counts as one record", () => {
  it("one row of a few columns — a wider row, or more rows, stays a table", () => {
    expect(isOneRecord(["units_sold"], [["7027"]])).toBe(true);
    expect(isOneRecord(["a", "b", "c", "d", "e", "f"], [[1, 2, 3, 4, 5, 6]])).toBe(true);
    expect(isOneRecord(["a", "b", "c", "d", "e", "f", "g"], [[1, 2, 3, 4, 5, 6, 7]])).toBe(false);
    expect(isOneRecord(["units_sold"], [["1"], ["2"]])).toBe(false);
    expect(isOneRecord([], [[]])).toBe(false);
  });
});

describe("the figures", () => {
  it("read each value beside its label", () => {
    render(<FindingFigures columns={["total_revenue", "units_sold"]} row={["359224.30043935776", "7027"]} />);
    expect(screen.getByText("Total Revenue")).toBeTruthy();
    expect(screen.getByText("359,224.30")).toBeTruthy();
    expect(screen.getByText("7,027")).toBeTruthy();
  });
});

/** A figure the answer already states is not printed again (2026-10-02) — however the writer rounded it. */
describe("a value the answer states", () => {
  it("in the forms a writer puts it", () => {
    expect(isStated("revenue was $359,224.30", "359224.30043935776")).toBe(true);
    expect(isStated("revenue was €359.2K", 359224.3)).toBe(true);
    expect(isStated("about 0.36 million", 359224.3)).toBe(true);
    expect(isStated("7,027 units were sold", "7027")).toBe(true);
    expect(isStated("a repeat rate of 9.4%", 0.0937)).toBe(true);
    expect(isStated("up 18.51% on June", 18.51)).toBe(true);
    expect(isStated("fell by $5,421.84", -5421.84)).toBe(true);
    expect(isStated("Outerwear led", "Outerwear")).toBe(true);
  });

  it("and not a different number, a zero, or a digit inside a code", () => {
    expect(isStated("7,028 units were sold", "7027")).toBe(false);
    expect(isStated("revenue was $359,224.40", 359224.3)).toBe(false);
    expect(isStated("0 orders were cancelled", 0.4)).toBe(false);
    expect(isStated("in Q3", 3)).toBe(false);
    expect(isStated("revenue rose", null)).toBe(false);
  });
});

describe("the figures an answer leaves out", () => {
  it("are the unstated values; none when it states every measure, whatever it calls the key", () => {
    expect(unstatedFigures(["units_sold", "orders"], ["7027", "6012"], "7,027 units")).toEqual([1]);
    expect(unstatedFigures(["order_month", "monthly_revenue"], ["2026-07-01", "117163.37"], "July: $117,163.37")).toEqual([]);
    expect(unstatedFigures(["order_month", "monthly_revenue"], ["2026-07-01", "117163.37"], "July rose")).toEqual([0, 1]);
    expect(unstatedFigures(["top_category"], ["Outerwear"], "one category led")).toEqual([0]);
  });

  it("are all that is drawn", () => {
    render(<FindingFigures columns={["units_sold", "orders"]} row={["7027", "6012"]} answer="7,027 units were sold" />);
    expect(screen.queryByText("7,027")).toBeNull();
    expect(screen.getByText("6,012")).toBeTruthy();
  });
});
