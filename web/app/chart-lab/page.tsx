"use client";

/**
 * /chart-lab — a dev-only visual harness for the ECharts engine.
 *
 * Renders every ported chart type with fixed sample data so the new engine can
 * be eyeballed (and screenshotted for visual-regression) WITHOUT a backend or a
 * connected warehouse. This is the testability surface the recommendation called
 * for. Safe to delete once the migration lands; not linked from the app.
 */

import { useMemo } from "react";
import {
  EChart,
  lineOption, multiLineOption, barOption, groupedBarOption,
  stackedBarOption, pieOption, scatterOption, buildAutoOption,
  comboOption, heatmapOption, treemapOption, paretoOption,
  type Row,
} from "@/components/charts/echarts";

const MONTHS = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06", "2024-07", "2024-08"];
const REGIONS = ["North", "South", "East", "West"];

// Deterministic sample data (no randomness → stable screenshots).
const revByMonth: Row[] = MONTHS.map((m, i) => ({ month: m, revenue: 120_000 + i * 28_000 + (i % 3) * 14_000 }));

const revByRegionMonth: Row[] = MONTHS.flatMap((m, i) =>
  REGIONS.map((region, ri) => ({ month: m, region, revenue: 30_000 + ri * 18_000 + i * (6_000 + ri * 1_500) })),
);

const gmvByCategory: Row[] = [
  ["Apparel", 4_200_000], ["Electronics", 3_100_000], ["Home", 2_400_000], ["Beauty", 1_800_000],
  ["Grocery", 1_500_000], ["Toys", 900_000], ["Sports", 720_000], ["Books", 410_000],
].map(([category, gmv]) => ({ category, gmv }));

const paymentMix: Row[] = [
  ["Card", 5_400_000], ["Wallet", 2_900_000], ["BNPL", 1_300_000], ["Bank", 820_000], ["Cash", 240_000],
].map(([method, amount]) => ({ method, amount }));

const revProfit: Row[] = REGIONS.map((region, i) => ({ region, revenue: 900_000 + i * 220_000, profit: 180_000 + i * 40_000 }));

// Combo: a magnitude (revenue) + a 0–1 rate (margin_rate) → dual axis earns its keep.
const revMargin: Row[] = REGIONS.map((region, i) => ({ region, revenue: 900_000 + i * 220_000, margin_rate: 0.18 + i * 0.06 }));

const priceRating: Row[] = Array.from({ length: 18 }, (_, i) => ({
  price: 12 + i * 4.5,
  rating: 3.2 + Math.min(1.6, i * 0.11) - (i % 4) * 0.18,
}));

// Auto-inference demo: a raw {columns, rows} table → inferChartType picks line.
const autoCols = ["order_date", "orders"];
const autoRows = MONTHS.map((m, i) => [m, 800 + i * 120 + (i % 2) * 60]);

function Card({ title, height = 300, children }: { title: string; height?: number; children: React.ReactNode }) {
  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8, fontFamily: "var(--font-ui)" }}>{title}</div>
      <div style={{ height }}>{children}</div>
    </div>
  );
}

export default function ChartLab() {
  const auto = useMemo(() => buildAutoOption(autoCols, autoRows, { title: "Auto-inferred (line)" }), []);
  return (
    <div style={{ padding: 24, background: "var(--bg-0)", minHeight: "100vh" }}>
      <h1 style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)", marginBottom: 4, fontFamily: "var(--font-ui)" }}>
        ECharts Chart-Lab
      </h1>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 20, fontFamily: "var(--font-ui)" }}>
        New Apache ECharts engine + Aughor token theme — every ported chart type on fixed sample data.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        <Card title="Line — revenue by month">
          <EChart option={lineOption({ rows: revByMonth, x: "month", ys: ["revenue"], xKind: "time" })} height={270} />
        </Card>
        <Card title="Area — revenue by month">
          <EChart option={lineOption({ rows: revByMonth, x: "month", ys: ["revenue"], xKind: "time" }, true)} height={270} />
        </Card>
        <Card title="Multi-line — revenue by region over time">
          <EChart option={multiLineOption({ rows: revByRegionMonth, x: "month", ys: ["revenue"], color: "region", xKind: "time" })} height={270} />
        </Card>
        <Card title="Stacked bar — revenue composition by region">
          <EChart option={stackedBarOption({ rows: revByRegionMonth, x: "month", ys: ["revenue"], color: "region", xKind: "time" })} height={270} />
        </Card>
        <Card title="Bar — GMV by category (sorted)">
          <EChart option={barOption({ rows: gmvByCategory, x: "category", ys: ["gmv"], labels: true })} height={270} />
        </Card>
        <Card title="Grouped bar — revenue vs profit by region">
          <EChart option={groupedBarOption({ rows: revProfit, x: "region", ys: ["revenue", "profit"] })} height={270} />
        </Card>
        <Card title="Pie / donut — payment mix">
          <EChart option={pieOption({ rows: paymentMix, x: "method", ys: ["amount"] })} height={270} />
        </Card>
        <Card title="Scatter — price vs rating">
          <EChart option={scatterOption({ rows: priceRating, x: "price", ys: ["rating"] })} height={270} />
        </Card>
        <Card title="Combo — revenue (bar) + margin rate (line)">
          <EChart option={comboOption({ rows: revMargin, x: "region", ys: ["revenue", "margin_rate"] })} height={270} />
        </Card>
        <Card title="Heatmap — revenue by region × month">
          <EChart option={heatmapOption({ rows: revByRegionMonth, x: "month", ys: ["revenue"], color: "region", xKind: "time" })} height={270} />
        </Card>
        <Card title="Treemap — GMV by category">
          <EChart option={treemapOption({ rows: gmvByCategory, x: "category", ys: ["gmv"] })} height={270} />
        </Card>
        <Card title="Pareto — GMV concentration (80/20)">
          <EChart option={paretoOption({ rows: gmvByCategory, x: "category", ys: ["gmv"] })} height={270} />
        </Card>
        {auto && (
          <Card title={`Auto-inference → ${auto.type}`}>
            <EChart option={auto.option} height={270} />
          </Card>
        )}
      </div>
    </div>
  );
}
