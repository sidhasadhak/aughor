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
  counterOption, funnelOption, histogramOption, boxplotOption, sankeyOption, waterfallOption,
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

// ── Chart-grammar exhibits (flag chart.exhibit_grammar) — the Genie-report semantics ──
// Severity-ramped rate ranking + reference lines (the "lowest load factors" exhibit).
const loadFactors: Row[] = ([
  ["GVA-DEL", 65.2], ["ZRH-EZE", 67.4], ["ZRH-BOS", 67.7], ["GVA-EZE", 68.1],
  ["ZRH-BKK", 68.9], ["ZRH-BOM", 69.4], ["ZRH-HKG", 71.0], ["ZRH-SIN", 72.9],
] as [string, number][]).map(([route, load_factor_pct]) => ({ route, load_factor_pct }));

// Cost-like metric (delay) → the severity ramp switches to the red family.
const routeDelays: Row[] = ([
  ["ZRH-LCY", 15.6], ["GVA-LHR", 13.9], ["ZRH-CDG", 12.4], ["ZRH-FRA", 11.2],
  ["GVA-AMS", 10.1], ["ZRH-VIE", 8.9], ["ZRH-MAD", 7.4],
] as [string, number][]).map(([route, avg_delay_min]) => ({ route, avg_delay_min }));

// Entity scatter: identity labels (id column) + hue = aircraft type + quadrant dividers.
const delayScatter: Row[] = ([
  ["HB-JBF", "A320", 22, 16.9], ["HB-JBE", "A320", 20, 15.8], ["HB-JAT", "A220-300", 10, 16.1],
  ["HB-JDK", "A350-900", 7, 15.6], ["HB-JBN", "A320", 20, 14.0], ["HB-JDO", "B777-300ER", 15, 13.8],
  ["HB-JAW", "A220-300", 21, 13.9], ["HB-JCH", "A321", 5, 13.6], ["HB-JCL", "A321", 7, 13.5],
  ["HB-JCJ", "A330-300", 10, 13.6], ["HB-JBJ", "A320", 17, 13.5], ["HB-JCE", "B777-300ER", 46, 13.6],
] as [string, string, number, number][]).map(
  ([aircraft_id, aircraft_type, flight_count, avg_delay_min]) =>
    ({ aircraft_id, aircraft_type, flight_count, avg_delay_min }));

// ── native-fit viz types (2026-07 wave) + the Databricks color-binding examples ──
// Aircraft example mirrors the two Databricks screenshots: the SAME load-factor ranking,
// coloured categorically by haul (long/short → legend) or continuously by revenue (gradient).
const aircraftPerf: Row[] = ([
  ["A350-900", 71.2, 302000, "long"], ["B777-300ER", 74.6, 268000, "long"],
  ["A340-300", 76.1, 254000, "long"], ["A320", 78.4, 96000, "short"],
  ["A330-300", 77.9, 231000, "long"], ["A321", 78.8, 88000, "short"],
  ["A220-300", 79.1, 72000, "short"], ["A220-100", 78.7, 64000, "short"],
] as [string, number, number, string][]).map(
  ([aircraft_type, load_factor_pct, revenue_per_flight, haul]) => ({ aircraft_type, load_factor_pct, revenue_per_flight, haul }));

// Funnel — an onboarding drop-off.
const funnelStages: Row[] = ([
  ["Visited", 48000], ["Signed up", 21500], ["Activated", 12800], ["Subscribed", 5400], ["Renewed", 3100],
] as [string, number][]).map(([stage, users]) => ({ stage, users }));

// Histogram — order-value distribution (raw values, one row each; deterministic spread).
const orderValues: Row[] = Array.from({ length: 240 }, (_, i) =>
  ({ order_value: Math.round(Math.abs(40 + 55 * Math.sin(i * 0.7) + (i % 11) * 6 + (i % 3) * 14) + 8) }));

// Box plot — delivery time distribution per region (repeated values per group).
const deliveryTimes: Row[] = REGIONS.flatMap((region, ri) =>
  Array.from({ length: 14 }, (_, k) => ({ region, delivery_hrs: 24 + ri * 8 + (k % 5) * 6 + (k % 2) * 4 - (k % 3) * 3 })));

// Sankey — flow from acquisition channel → device (two dimensions + a measure).
const channelDevice: Row[] = ([
  ["Paid search", "Mobile", 3200], ["Paid search", "Desktop", 1800], ["Organic", "Mobile", 2600],
  ["Organic", "Desktop", 2100], ["Social", "Mobile", 2900], ["Social", "Desktop", 700],
  ["Email", "Desktop", 1400], ["Email", "Mobile", 900],
] as [string, string, number][]).map(([channel, device, sessions]) => ({ channel, device, sessions }));

// Waterfall — an ARR bridge (signed contributions building to the total).
const arrBridge: Row[] = ([
  ["Starting ARR", 1200000], ["New", 340000], ["Expansion", 180000], ["Contraction", -90000], ["Churn", -160000],
] as [string, number][]).map(([stage, arr_delta]) => ({ stage, arr_delta }));

// ── Tier-2 (forecast · gantt · geo) + scatter/line colour binding ──
const projectPlan: Row[] = ([
  ["Discovery", "Research", "2024-01-05", "2024-02-10"], ["Design", "Research", "2024-02-01", "2024-03-15"],
  ["Backend build", "Build", "2024-03-01", "2024-05-20"], ["Frontend build", "Build", "2024-03-20", "2024-06-10"],
  ["Beta", "Launch", "2024-06-05", "2024-07-05"], ["GA launch", "Launch", "2024-07-01", "2024-08-01"],
] as [string, string, string, string][]).map(([task, phase, start_date, end_date]) => ({ task, phase, start_date, end_date }));
const revByCountry: Row[] = ([
  ["United States", 4200000], ["China", 3100000], ["India", 1400000], ["Germany", 1800000],
  ["Japan", 1500000], ["United Kingdom", 1200000], ["Brazil", 760000], ["Australia", 520000],
] as [string, number][]).map(([country, revenue]) => ({ country, revenue }));
const salesByCity: Row[] = ([
  ["New York", 40.71, -74.01, 9200], ["London", 51.51, -0.13, 7400], ["Tokyo", 35.68, 139.69, 8100],
  ["Singapore", 1.35, 103.82, 4300], ["Sao Paulo", -23.55, -46.63, 5200], ["Mumbai", 19.08, 72.88, 6100],
] as [string, number, number, number][]).map(([city, lat, lon, sales]) => ({ city, lat, lon, sales }));
// Stores: 3 measures + region → scatter coloured by region (cat) or volume (continuous).
const storeScatter: Row[] = ([
  ["Aloha", "West", 42, 4.6, 9200], ["Cedar", "East", 33, 4.8, 15300], ["Echo", "North", 25, 4.9, 21000],
  ["Fern", "North", 64, 4.0, 3300], ["Haze", "South", 39, 4.7, 11800], ["Jade", "East", 29, 4.85, 18400],
  ["Kite", "North", 61, 3.95, 3900], ["Lark", "South", 44, 4.5, 8600], ["Bay", "West", 58, 4.2, 4100],
] as [string, string, number, number, number][]).map(([store, region, price, rating, volume]) => ({ store, region, price, rating, volume }));

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
        <Card title="Exhibit grammar — severity ramp (rate) + benchmark ref lines" height={400}>
          <Chart
            {...toTable(loadFactors, ["route", "load_factor_pct"])}
            chartType="bar_horizontal" chrome={false} showLabels
            columnUnits={{ load_factor_pct: "percent" }}
            exhibit={{
              color: { mode: "severity" },
              ref_lines: [
                { value: 74.5, label: "Long-haul avg", kind: "global_avg" },
                { value: 71.0, label: "Peer median", kind: "peer_median" },
              ],
            }}
          />
        </Card>
        <Card title="Exhibit grammar — cost metric → red severity family" height={370}>
          <Chart
            {...toTable(routeDelays, ["route", "avg_delay_min"])}
            chartType="bar_horizontal" chrome={false} showLabels
            exhibit={{ color: { mode: "severity" } }}
          />
        </Card>
        <Card title="Exhibit grammar — entity scatter: labels + type hue + quadrant" height={340}>
          <Chart
            {...toTable(delayScatter, ["aircraft_id", "aircraft_type", "flight_count", "avg_delay_min"])}
            chartType="scatter" chrome={false}
            exhibit={{ label_points: true, quadrant: { x: 20, y: 14.5 } }}
          />
        </Card>
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        Native-fit viz types (2026-07 wave) — Counter · Funnel · Histogram · Box · Sankey · Waterfall
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        New pure builders, zero new dependencies (ECharts modules registered in EChart.tsx). Each is offered
        in the viz editor only when the data shape supports it.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        <Card title="Counter — total revenue (KPI)">
          <EChart option={counterOption({ rows: revByMonth, x: "month", ys: ["revenue"] })} height={200} />
        </Card>
        <Card title="Funnel — onboarding drop-off">
          <EChart option={funnelOption({ rows: funnelStages, x: "stage", ys: ["users"], labels: true })} height={270} />
        </Card>
        <Card title="Histogram — order-value distribution (240 orders)">
          <EChart option={histogramOption({ rows: orderValues, x: "order_value", ys: ["order_value"] })} height={270} />
        </Card>
        <Card title="Box plot — delivery hours by region">
          <EChart option={boxplotOption({ rows: deliveryTimes, x: "region", ys: ["delivery_hrs"] })} height={270} />
        </Card>
        <Card title="Sankey — acquisition channel → device">
          <EChart option={sankeyOption({ rows: channelDevice, x: "channel", color: "device", ys: ["sessions"] })} height={270} />
        </Card>
        <Card title="Waterfall — ARR bridge (signed contributions)">
          <EChart option={waterfallOption({ rows: arrBridge, x: "stage", ys: ["arr_delta"], labels: true })} height={270} />
        </Card>
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        Color binding — colour marks by a chosen field (the Databricks &quot;Color&quot;)
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        The two screenshots: the SAME load-factor ranking, coloured categorically by <code>haul</code>
        (dimension → discrete legend) or continuously by <code>revenue_per_flight</code> (measure → gradient legend).
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        <Card title="Categorical — colour by haul (dimension → legend)" height={370}>
          <Chart
            {...toTable(aircraftPerf, ["aircraft_type", "load_factor_pct", "revenue_per_flight", "haul"])}
            chartType="bar_horizontal" chrome={false} showLabels columnUnits={{ load_factor_pct: "percent" }}
            exhibit={{ color: { mode: "categorical", field: "haul", name: "Haul type" } }}
          />
        </Card>
        <Card title="Continuous — colour by revenue/flight (measure → gradient)" height={370}>
          <Chart
            {...toTable(aircraftPerf, ["aircraft_type", "load_factor_pct", "revenue_per_flight", "haul"])}
            chartType="bar_horizontal" chrome={false} showLabels columnUnits={{ load_factor_pct: "percent" }}
            exhibit={{ color: { mode: "continuous", field: "revenue_per_flight", name: "Revenue / flight" } }}
          />
        </Card>
        <Card title="Scatter — colour by region (dimension → legend)" height={300}>
          <Chart {...toTable(storeScatter, ["store", "region", "price", "rating", "volume"])}
            chartType="scatter" chrome={false} exhibit={{ color: { mode: "categorical", field: "region", name: "Region" } }} />
        </Card>
        <Card title="Scatter — colour by volume (measure → gradient)" height={300}>
          <Chart {...toTable(storeScatter, ["store", "region", "price", "rating", "volume"])}
            chartType="scatter" chrome={false} exhibit={{ color: { mode: "continuous", field: "volume", name: "Volume" } }} />
        </Card>
        <Card title="Line — colour by region → multi-line" height={300}>
          <Chart {...toTable(revByRegionMonth, ["month", "region", "revenue"])}
            chartType="line" chrome={false} exhibit={{ color: { mode: "categorical", field: "region", name: "Region" } }} />
        </Card>
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        Tier-2 viz types — Line (forecast) · Gantt · Choropleth · Point map
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        The heavier-infra set. Forecast is a deterministic least-squares projection; the maps lazy-load a
        world geojson from <code>/geo/world.json</code> only when first rendered (zero main-bundle cost).
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 16 }}>
        <Card title="Line (forecast) — revenue projected + 95% band" height={300}>
          <Chart {...toTable(revByMonth, ["month", "revenue"])} chartType="line_forecast" chrome={false} />
        </Card>
        <Card title="Gantt — project plan (tasks coloured by phase)" height={300}>
          <Chart {...toTable(projectPlan, ["task", "phase", "start_date", "end_date"])} chartType="gantt" chrome={false} />
        </Card>
        <Card title="Choropleth — revenue by country" height={320}>
          <Chart {...toTable(revByCountry, ["country", "revenue"])} chartType="choropleth" chrome={false} />
        </Card>
        <Card title="Point map — sales by city (bubble size)" height={320}>
          <Chart {...toTable(salesByCity, ["city", "lat", "lon", "sales"])} chartType="point_map" chrome={false} />
        </Card>
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
          { t: "composition over time → 100%-stacked (share by segment)", p: {
              ...toTable(MONTHS.flatMap((m) => [
                { month: m, segment: "luxury", share_pct: 40 + (MONTHS.indexOf(m)) },
                { month: m, segment: "mid", share_pct: 35 },
                { month: m, segment: "off-price", share_pct: 25 - (MONTHS.indexOf(m)) },
              ]), ["month", "segment", "share_pct"]),
              chartType: "auto" } },
          { t: "many-group trend → small multiples (8 brands)", p: {
              ...toTable(MONTHS.flatMap((m, mi) => Array.from({ length: 8 }, (_, b) => (
                { month: m, brand: `Brand ${b + 1}`, revenue: 100 + b * 12 + mi * (5 + b) + (mi % 2) * 8 }
              ))), ["month", "brand", "revenue"]),
              chartType: "auto" } },
        ].map((d, i) => (
          <div key={`pct-${i}`} style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 4, fontFamily: "var(--font-ui)" }}>{d.t}</div>
            <Chart title={d.t} {...d.p} />
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", margin: "28px 0 4px", fontFamily: "var(--font-ui)" }}>
        &lt;ResultChartCard&gt; — clean chart, edit in the side panel (hover the pencil)
      </h2>
      <p style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16, fontFamily: "var(--font-ui)" }}>
        The chart renders clean; hover and click the pencil to open the Databricks-style viz editor —
        Metric / Dimension / Aggregation (grain-aware — try SUM on the rate), chart type, transform, and table/pivot.
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

      <p style={{ fontSize: 12, color: "var(--t3)", margin: "16px 0 8px", fontFamily: "var(--font-ui)" }}>
        Exhibit survival: the spec rides inside <code>chart_config</code> on the quick path, and choosing a
        Display nulls that config — the ramp + ref line must SURVIVE the switch (they are semantics, not field roles).
      </p>
      <div style={{ background: "var(--bg-1)", border: "1px solid var(--chart-axis)", borderRadius: 10, padding: 14, maxWidth: 720 }}>
        <ResultChartCard
          title="Load factor by route (exhibit inside chart_config)"
          {...toTable(loadFactors, ["route", "load_factor_pct"])}
          chartConfig={{
            exhibit: {
              color: { mode: "severity" },
              ref_lines: [{ value: 74.5, label: "Long-haul avg", kind: "global_avg" }],
            },
          }}
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
