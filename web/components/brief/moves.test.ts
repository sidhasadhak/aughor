/**
 * The Briefing's "numbers that moved" rows. The case these defend hardest is the first: a
 * move is read from the series' last two buckets, never from the whole-history value query
 * beside it — printed as now/prior, those two would announce a collapse that never happened.
 */
import { describe, expect, it } from "vitest";

import { buildMoveRow } from "@/components/brief/moves";

const monthly = (values: number[], receipt = "chart-receipt-abc123") => ({
  columns: ["month", "value"],
  rows: values.map((v, i) => [`2025-0${i + 1}-01`, String(v)]),
  error: null,
  receipt_id: receipt,
});

describe("buildMoveRow", () => {
  it("reads now and prior from the series, and keeps the overall value as overall", () => {
    const row = buildMoveRow({
      name: "Gross Merchandise Value (GMV)", unit: "EUR", sym: "€", valueSql: "SELECT SUM(gmv_eur) FROM orders",
      value: { columns: ["sum"], rows: [["45437544"]], error: null, receipt_id: "value-receipt" },
      chart: monthly([1_000_000, 1_100_000, 1_210_000]),
    });
    expect(row.state).toBe("ready");
    expect(row.overall).toBe("€45.4M");
    expect(row.now).toBe("€1.2M");
    expect(row.prior).toBe("€1.1M");
    expect(row.delta).toEqual({ text: "+10.0%", sign: 1, favorable: true });
    // The figures on the row came from the series, so its receipt is the series'.
    expect(row.receiptId).toBe("chart-receipt-abc123");
    expect(row.nowLabel).toMatch(/2025/);
    expect(row.priorLabel).toMatch(/2025/);
  });

  it("reads a rising return rate as unfavourable, in points", () => {
    const row = buildMoveRow({
      name: "Item Return Rate", unit: "ratio 0-1", sym: "€", valueSql: "SELECT 1",
      value: { columns: ["r"], rows: [["0.26"]], error: null },
      chart: monthly([0.2, 0.22, 0.25]),
    });
    expect(row.now).toBe("25.0%");
    expect(row.delta).toEqual({ text: "+3.0pts", sign: 1, favorable: false });
  });

  it("keeps a breakdown that is not a time series as a value with no move", () => {
    const row = buildMoveRow({
      name: "Average CSAT Score", unit: "1-5 scale", sym: "€", valueSql: "SELECT 1",
      value: { columns: ["avg"], rows: [["4.08"]], error: null, receipt_id: "value-receipt" },
      chart: { columns: ["platform", "avg_csat"], rows: [["web", "4.1"], ["ios", "4.0"], ["android", "3.9"]], error: null },
    });
    expect(row.state).toBe("ready");
    expect(row.overall).toBe("4.08");
    expect(row.series).toBeUndefined();
    expect(row.delta).toBeUndefined();
    expect(row.receiptId).toBe("value-receipt");
  });

  it("drops a metric whose value query failed — the reason, and no figure", () => {
    const row = buildMoveRow({
      name: "Financial Refund Rate", unit: "ratio 0-1", sym: "€", valueSql: "SELECT 1",
      value: new Error("Binder Error: column refund_eur not found"),
      chart: null,
    });
    expect(row.state).toBe("dropped");
    expect(row.reason).toMatch(/Binder Error/);
    expect(row.overall).toBeUndefined();
    expect(row.now).toBeUndefined();
  });

  it("drops a value outside its declared range instead of printing it", () => {
    const row = buildMoveRow({
      name: "Conversion Rate", unit: "ratio 0-1", sym: "€", valueSql: "SELECT 1",
      value: { columns: ["r"], rows: [["3.4"]], error: null },
    });
    expect(row.state).toBe("dropped");
    expect(row.reason).toMatch(/declared range/);
  });
});
