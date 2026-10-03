/**
 * A chart's caption names what it draws (2026-10-03): Q2's revenue bars were captioned "Revenue and average
 * order value by category", and Q3's change chart named three measures over the one it drew.
 */
import { describe, expect, it } from "vitest";
import { chartCaption } from "@/components/charts/caption";

const Q2_TITLE = "Revenue and average order value by category — 4 Mar – 3 Sep 2026";
const Q2 = { columns: ["category", "revenue", "average_order_value"],
             rows: [["Outerwear & Coats", "237836.63", "150.82"], ["Jeans", "214128.38", "102.26"],
                    ["Sweaters", "147374.61", "78.35"], ["Intimates", "85036.08", "36.72"]] };
const Q3_TITLE = "Monthly revenue by month, prev month revenue and revenue change where status = Complete — Aug 2025 – Aug 2026";
const Q3 = { columns: ["month", "monthly_revenue", "prev_month_revenue", "revenue_change"],
             rows: [["2025-08-01", "55965.77", "NULL", "NULL"], ["2025-09-01", "50543.93", "55965.77", "-5421.84"],
                    ["2025-10-01", "58007.77", "50543.93", "7463.84"], ["2025-11-01", "64251.70", "58007.77", "6243.93"]] };

describe("a chart's caption", () => {
  it("names the one measure a two-scale chart draws, keeping the title's period", () => {
    expect(chartCaption(Q2_TITLE, Q2.columns, Q2.rows, "auto")).toBe("Revenue by category — 4 Mar – 3 Sep 2026");
  });

  it("names the change a change chart draws, with the title's filter", () => {
    expect(chartCaption(Q3_TITLE, Q3.columns, Q3.rows, "auto"))
      .toBe("Revenue change by month where status = Complete — Aug 2025 – Aug 2026");
  });

  it("keeps the title where the chart draws every measure, or where a chart type was chosen", () => {
    const one = { columns: ["category", "revenue"], rows: [["Jeans", "10"], ["Swim", "8"], ["Socks", "3"]] };
    expect(chartCaption("Revenue by category — Jul 2026", one.columns, one.rows, "auto")).toBe("Revenue by category — Jul 2026");
    expect(chartCaption(Q2_TITLE, Q2.columns, Q2.rows, "bar")).toBe(Q2_TITLE);
    expect(chartCaption("", Q2.columns, Q2.rows, "auto")).toBe("");
  });
});
