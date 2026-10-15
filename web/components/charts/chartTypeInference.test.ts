/**
 * chartTypeInference.test.ts — a per-category summary with date bounds is a category grid.
 *
 * The LuxExperience check "Do Event and Platform really join on these keys?" (d14f276b, 2026-10-15)
 * returned one row per platform — attendance records, events, and the first and last event date —
 * and the inference read the two dates as a time axis: five dots, one per platform, scattered over
 * the years. The dates bound each row; the measure is by platform.
 */
import { describe, expect, it } from "vitest";
import { inferChartType } from "./chartTypeInference";

const COLUMNS = ["ep", "ap", "records", "ev", "mn", "mx"];
const ROWS = [
  ["MR PORTER", "MR PORTER", "476", "18", "2020-05-29", "2024-08-05"],
  ["Mytheresa", "Mytheresa", "377", "17", "2020-01-22", "2024-12-11"],
  ["NET-A-PORTER", "NET-A-PORTER", "185", "9", "2021-06-29", "2024-04-29"],
  ["THE OUTNET", "THE OUTNET", "321", "11", "2020-04-03", "2024-11-25"],
  ["YOOX", "YOOX", "283", "11", "2020-02-01", "2024-09-17"],
];

describe("a per-category summary with date bounds", () => {
  it("is drawn by category, never scattered over its date bounds", () => {
    const got = inferChartType(COLUMNS, ROWS);
    expect(got).not.toBeNull();
    expect(got!.type).not.toMatch(/line|scatter|heatmap|small-multiples/);
    expect(got!.xCol).toBe(0);
  });

  it("still reads a genuine series — one category over many dates — as a trend", () => {
    const columns = ["platform", "day", "records"];
    const rows = [
      ["MR PORTER", "2024-01-01", "10"], ["MR PORTER", "2024-02-01", "12"], ["MR PORTER", "2024-03-01", "9"],
      ["YOOX", "2024-01-01", "4"], ["YOOX", "2024-02-01", "6"], ["YOOX", "2024-03-01", "5"],
    ];
    const got = inferChartType(columns, rows);
    expect(got).not.toBeNull();
    expect(got!.xCol).toBe(1);
  });
});
