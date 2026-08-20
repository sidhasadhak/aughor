/**
 * chart-ssr-entry.ts — the headless print renderer (CA-4 "one renderer").
 *
 * Reads one JSON payload from stdin:
 *   { charts: [{ columns, rows, chart_type, chart_config, exhibit,
 *                column_units, title, labels, width, height }] }
 * and writes one JSON payload to stdout: { svgs: [string | null, …] } — one
 * SVG string per requested chart, null where the data has no honest chart
 * (the same verdict the browser reaches, because this IS the browser's
 * resolver: resolveChartOption + the same builders + the same theme, bundled
 * by `npm run build:chart-ssr` into aughor/export/chart_ssr.bundle.mjs and
 * invoked by the Python export path as a node subprocess (§5-3a).
 *
 * The print theme is the LIGHT token set (a PDF is a light-surface artifact).
 */
import * as echarts from "echarts/core";
import {
  LineChart, BarChart, PieChart, ScatterChart, HeatmapChart, TreemapChart,
  FunnelChart, SankeyChart, BoxplotChart, CustomChart,
} from "echarts/charts";
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  MarkLineComponent, VisualMapComponent, AxisPointerComponent, GraphicComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { resolveChartOption } from "../components/charts/resolveOption";
import { AUGHOR_THEME_NAME, buildAughorTheme, printChartTokens } from "../components/charts/echarts/theme";
import { setOrgSettingsCache } from "../lib/orgSettings";
import { setChartMode } from "../components/charts/echarts/palette";
import type { OrgSettings } from "../lib/api";

echarts.use([
  LineChart, BarChart, PieChart, ScatterChart, HeatmapChart, TreemapChart,
  FunnelChart, SankeyChart, BoxplotChart, CustomChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  MarkLineComponent, VisualMapComponent, AxisPointerComponent, GraphicComponent,
  SVGRenderer,
]);
// No MapChart/GeoComponent: choropleth/point-map need a ~1MB geojson the print
// path deliberately skips — those findings fall back to their data table.
echarts.registerTheme(AUGHOR_THEME_NAME, buildAughorTheme(printChartTokens()));
setChartMode("light"); // print is a light-surface artifact — deemph/sign/series resolve light

interface ChartRequest {
  columns: string[];
  rows: unknown[][];
  chart_type?: string | null;
  chart_config?: Record<string, unknown> | null;
  exhibit?: Record<string, unknown> | null;
  column_units?: Record<string, string> | null;
  title?: string | null;
  labels?: boolean;
  width?: number;
  height?: number;
}

function renderOne(req: ChartRequest): string | null {
  const resolved = resolveChartOption({
    columns: req.columns ?? [],
    rows: req.rows ?? [],
    chartType: req.chart_type ?? "auto",
    chartConfig: req.chart_config ?? null,
    columnUnits: req.column_units ?? null,
    exhibit: (req.exhibit ?? null) as never,
    showLabels: req.labels !== false,
  });
  if (!resolved) return null;
  const hint = String(req.chart_type ?? "").toLowerCase();
  if (hint === "choropleth" || hint === "point_map") return null; // no geo layer in print
  const width = req.width && req.width > 0 ? req.width : 760;
  const height = req.height && req.height > 0 ? req.height : Math.min(Math.max(resolved.defaultH, 200), 560);
  const chart = echarts.init(null, AUGHOR_THEME_NAME, { renderer: "svg", ssr: true, width, height });
  try {
    const option = { ...resolved.option, animation: false } as Parameters<typeof chart.setOption>[0];
    if (req.title) (option as { title?: unknown }).title = { text: req.title };
    chart.setOption(option);
    return (chart as unknown as { renderToSVGString: () => string }).renderToSVGString();
  } finally {
    chart.dispose();
  }
}

// The resolver reads the org currency from the client cache; headless, the
// export passes the resolved SYMBOL and this shim maps it back to a code so
// the print axis shows "CHF 34.7M" exactly as the app did.
const SYMBOL_TO_CODE: Record<string, string> = {
  "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR",
  "A$": "AUD", "C$": "CAD", "CHF": "CHF", "S$": "SGD", "R$": "BRL", "R": "ZAR",
};
function applyMoneySymbol(sym: string | undefined): void {
  const s = (sym ?? "").trim();
  if (!s) return;
  const code = SYMBOL_TO_CODE[s] ?? (/^[A-Za-z]{3}$/.test(s) ? s.toUpperCase() : null);
  if (code) setOrgSettingsCache({ currency_code: code } as OrgSettings);
}

async function main(): Promise<void> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const payload = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}") as
    { charts?: ChartRequest[]; money_symbol?: string };
  applyMoneySymbol(payload.money_symbol);
  const svgs = (payload.charts ?? []).map((req) => {
    try {
      return renderOne(req);
    } catch (e) {
      process.stderr.write(`chart-ssr: ${String(e)}\n`);
      return null;
    }
  });
  process.stdout.write(JSON.stringify({ svgs }));
}

void main();
