"use client";

/**
 * /chart-lab — a dev-only visual harness for the ECharts engine.
 *
 * Renders every ported chart type with fixed sample data so the new engine can
 * be eyeballed (and screenshotted for visual-regression) WITHOUT a backend or a
 * connected warehouse. This is the testability surface the recommendation called
 * for. Safe to delete once the migration lands; not linked from the app.
 */

import { useEffect, useMemo } from "react";
import {
  EChart,
  lineOption, multiLineOption, barOption, groupedBarOption,
  stackedBarOption, pieOption, scatterOption, buildAutoOption,
  comboOption, heatmapOption, treemapOption, paretoOption,
  type Row,
} from "@/components/charts/echarts";
import { Chart } from "@/components/Chart";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { getEffectiveSettings } from "@/lib/api";
import { setOrgSettingsCache } from "@/lib/orgSettings";
import { KpiStripView, buildKpi, KPI_ACCENTS, type Kpi } from "@/components/brief/IndustryKpiStrip";

/** Object rows → SQL-shaped [columns, rows[][]] for the <Chart> component. */
function toTable(objs: Row[], cols: string[]): { columns: string[]; rows: unknown[][] } {
  return { columns: cols, rows: objs.map((o) => cols.map((c) => o[c])) };
}

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
  // The harness reflects the configured org settings (currency symbol, date format)
  // so the formatters can be eyeballed — fetched once, like the real app does on load.
  useEffect(() => { getEffectiveSettings().then(setOrgSettingsCache).catch(() => {}); }, []);
  const auto = useMemo(() => buildAutoOption(autoCols, autoRows, { title: "Auto-inferred (line)" }), []);
  // KPI scorecard demo — built via the real buildKpi() so the delta units (pts/%/×),
  // direction-aware favorability colour, sparklines, AND click-to-expand are exercised.
  const KMONTHS = ["2022-01-01", "2022-02-01", "2022-03-01", "2022-04-01", "2022-05-01", "2022-06-01"];
  // value column named per metric (money ones embed a source currency) so the chart's
  // currency relabel + symbol get exercised, like real chart_sql output.
  const mkChart = (vals: number[], col: string) => ({ columns: ["month", col], rows: vals.map((v, i) => [KMONTHS[i], v] as unknown[]) });
  const KSERIES = {
    margin: [0.51, 0.50, 0.498, 0.495, 0.494, 0.470],
    aov: [69.5, 70.2, 69.9, 70.0, 69.77, 69.35],
    repeat: [0.24, 0.25, 0.258, 0.262, 0.254, 0.285],
    cac: [17.5, 18.2, 18.9, 19.2, 19.54, 21.14],
    roas: [3.5, 3.6, 3.7, 3.75, 3.78, 4.18],
  };
  const kpiDemo = [
    buildKpi({ name: "Gross Margin Rate", raw: 0.470, unit: "ratio 0-1", accent: KPI_ACCENTS[0], series: KSERIES.margin, chart: mkChart(KSERIES.margin, "margin_rate") }),
    buildKpi({ name: "Avg Order Value", raw: 69.35, unit: "USD", sym: "$", accent: KPI_ACCENTS[1], series: KSERIES.aov, chart: mkChart(KSERIES.aov, "aov_usd") }),
    buildKpi({ name: "Repeat Purchase Rate", raw: 0.285, unit: "ratio 0-1", accent: KPI_ACCENTS[2], series: KSERIES.repeat, chart: mkChart(KSERIES.repeat, "repeat_rate") }),
    buildKpi({ name: "Acquisition Cost (CAC)", raw: 21.14, unit: "USD", sym: "$", accent: KPI_ACCENTS[3], series: KSERIES.cac, chart: mkChart(KSERIES.cac, "cac_usd") }),
    buildKpi({ name: "Blended ROAS", raw: 4.18, unit: "ratio", accent: KPI_ACCENTS[4], series: KSERIES.roas, chart: mkChart(KSERIES.roas, "roas") }),
  ].filter(Boolean) as Kpi[];
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

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        &lt;Chart&gt; component — end-to-end (column resolution → dispatch → chrome)
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        Raw {`{columns, rows}`} through the real component the app uses. Hover for the labels/download toolbar.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        {[
          { t: "auto timeseries → line", p: { ...toTable(revByMonth, ["month", "revenue"]) } },
          { t: "auto categorical → horizontal bar", p: { ...toTable(gmvByCategory, ["category", "gmv"]) } },
          { t: "auto date+series → multi-line", p: { ...toTable(revByRegionMonth, ["month", "region", "revenue"]) } },
          { t: "change metric → diverging bar", p: { ...toTable([
              { region: "North", mom_change: 0.12 }, { region: "South", mom_change: -0.08 },
              { region: "East", mom_change: 0.21 }, { region: "West", mom_change: -0.15 },
            ], ["region", "mom_change"]) } },
          { t: "backend chartConfig (bar)", p: { ...toTable(revByMonth, ["month", "revenue"]), chartConfig: { type: "bar", x_field: "month", y_field: "revenue" } } },
          { t: "custom: $ format + no legend", p: { ...toTable(revProfit, ["region", "revenue", "profit"]), custom: { format: "$,.0f", legend: "none" as const } } },
        ].map((d, i) => (
          <div key={i} style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 4, fontFamily: "var(--font-ui)" }}>{d.t}</div>
            <Chart title={d.t} {...d.p} />
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        percent unit hint + adaptive bar sizing + labels (report fixes #1–#3)
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        A rate stored as a fraction in <code>metric_total</code> (name matches no share regex). With
        <code> columnUnits=&#123;metric_total:&quot;percent&quot;&#125;</code> the axis + labels read &quot;40.5%&quot;, not &quot;0.4&quot;. The 2-bar
        cut stays compact; bars keep a fixed max thickness.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        {[
          { t: "return rate by platform (5 bars, % + labels)", p: {
              ...toTable([
                { platform: "Luxury Pavilion", metric_total: 0.405 }, { platform: "Boutique Prime", metric_total: 0.382 },
                { platform: "StyleHub", metric_total: 0.341 }, { platform: "Marketplace", metric_total: 0.310 },
                { platform: "Off-price Outlet", metric_total: 0.270 },
              ], ["platform", "metric_total"]),
              chartType: "bar_horizontal", columnUnits: { metric_total: "percent" } as Record<string, string>, showLabels: true } },
          { t: "luxury vs off-price (2 bars → compact)", p: {
              ...toTable([
                { platform: "Luxury platforms", metric_total: 0.405 }, { platform: "Off-price", metric_total: 0.270 },
              ], ["platform", "metric_total"]),
              chartType: "bar_horizontal", columnUnits: { metric_total: "percent" } as Record<string, string>, showLabels: true } },
          { t: "share of returns by reason (pct_of_total, already 0–100)", p: {
              ...toTable([
                { reason: "size / fit", pct_of_total: 42.2 }, { reason: "not as expected", pct_of_total: 21.9 },
                { reason: "changed mind", pct_of_total: 19.9 }, { reason: "quality", pct_of_total: 10.2 },
                { reason: "late delivery", pct_of_total: 5.9 },
              ], ["reason", "pct_of_total"]),
              chartType: "bar_horizontal", columnUnits: { pct_of_total: "percent" } as Record<string, string>, showLabels: true } },
          { t: "composition → donut (≤6 parts): returns by condition", p: {
              ...toTable([
                { condition: "resellable", pct_of_total: 79.7 }, { condition: "minor_refurbish", pct_of_total: 14.1 },
                { condition: "reject", pct_of_total: 6.3 },
              ], ["condition", "pct_of_total"]),
              chartType: "pie", columnUnits: { pct_of_total: "percent" } as Record<string, string>, showLabels: true } },
        ].map((d, i) => (
          <div key={`pct-${i}`} style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 4, fontFamily: "var(--font-ui)" }}>{d.t}</div>
            <Chart title={d.t} {...d.p} />
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        &lt;ResultChartCard&gt; — inline controls + chart⇄table toggle
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        Re-pivot in place: pick Metric / Dimension / Aggregation (grain-aware — try SUM on the rate) and flip to the table.
      </p>
      <div style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14, maxWidth: 720 }}>
        <ResultChartCard
          title="Revenue & margin by region × channel"
          {...toTable(
            ["North", "South", "East"].flatMap((region) =>
              ["Web", "Store"].map((channel, ci) => ({
                region, channel,
                revenue: 200_000 + region.length * 30_000 + ci * 90_000,
                margin_rate: 0.2 + ci * 0.08,
              })),
            ),
            ["region", "channel", "revenue", "margin_rate"],
          )}
        />
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        &lt;KpiStripView&gt; — key-metrics scorecard (semantic deltas + sparklines)
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        Delta colour is direction-aware: a rising CAC is red (cost up = bad), a falling margin is red, a rising repeat-rate is green.
      </p>
      <div style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14 }}>
        <KpiStripView industry="DTC Beauty E-commerce" period="MoM" kpis={kpiDemo} />
      </div>
    </div>
  );
}
