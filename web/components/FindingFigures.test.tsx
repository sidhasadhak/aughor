// @vitest-environment jsdom
/**
 * A result of one row is its figures, read in a line — not a table (2026-10-02): "if it's a single
 * number being displayed, does one really need a table? How un-intelligent is that?" Q1's units sold
 * and revenue each came back as one cell and were drawn as collapsed one-row tables with a totals
 * toggle and copy buttons around a single value.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FindingFigures, figureValue, isOneRecord } from "@/components/FindingFigures";
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
