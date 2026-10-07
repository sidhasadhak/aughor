import { describe, expect, it } from "vitest";

import type { CatalogueMetric } from "@/lib/api";
import { metricStanding, normalizeMetricName } from "@/lib/metricStanding";

const row = (over: Partial<CatalogueMetric>): CatalogueMetric => ({
  name: "", label: "", source: "explorer", state: "proposed", sql: "", unit: "", definition: "",
  grain: "", dimensions: [], tables: [], anti_patterns: [], pack_id: "", required_roles: [],
  missing_roles: [], sane_range: null, why_it_matters: "", reason: "", status: "", version: 0,
  owner: "", editable: false, ...over,
});

describe("metricStanding", () => {
  it("normalises names the way the catalogue does", () => {
    expect(normalizeMetricName("Average Booking Value (ABV)")).toBe("average_booking_value_abv");
  });

  it("an explorer suggestion is proposed, never approved", () => {
    const rows = [row({ name: "average_booking_value_abv", label: "Average Booking Value (ABV)" })];
    expect(metricStanding("Average Booking Value (ABV)", rows)).toBe("proposed");
  });

  it("a defined metric is approved only when its status says so", () => {
    expect(metricStanding("Revenue", [row({ name: "revenue", state: "defined", status: "approved" })])).toBe("approved");
    expect(metricStanding("Revenue", [row({ name: "revenue", state: "defined", status: "draft" })])).toBe("draft");
  });

  it("a tile the catalogue does not list says so", () => {
    expect(metricStanding("Ride Completion Rate", [row({ name: "revenue" })])).toBe("absent");
  });
});
