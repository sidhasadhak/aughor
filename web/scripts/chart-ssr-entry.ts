/**
 * chart-ssr-entry.ts — the headless print renderer, on Vega.
 *
 * Reads one JSON payload from stdin:
 *   { charts: [{ columns, rows, chart_type, chart_config, exhibit, column_units, title,
 *                labels, width, height }], money_symbol }
 * and writes { svgs: [string | null, …] } — one SVG per requested chart, null where the
 * data has no honest chart, which is the same verdict the browser reaches because this IS
 * the browser's resolver.
 *
 * Phase 5d. This used to bundle ECharts (825 KB) purely to draw a PDF's charts. Vega renders
 * SVG headlessly with no DOM shim, so the print path and the screen path now run the same
 * two functions over the same specs — and geo, which the ECharts print path skipped because
 * it needed a ~1 MB registered map, works here: the base map is just another data URL.
 *
 * The print theme is the LIGHT token set, because a PDF is a light-surface artifact.
 */
import * as vega from "vega";
import * as vl from "vega-lite";
import { resolveVegaSpec } from "../components/charts/vega/resolveSpec";
import { resolveTier3Spec } from "../components/charts/vega/tier3";
import { buildVegaConfig, buildVegaRuntimeConfig, printVegaTokens } from "../components/charts/vega/config";
import { setOrgSettingsCache } from "../lib/orgSettings";
import type { OrgSettings } from "../lib/api";

interface ChartRequest {
  columns?: string[];
  rows?: unknown[][];
  chart_type?: string | null;
  chart_config?: Record<string, unknown> | null;
  exhibit?: Record<string, unknown> | null;
  column_units?: Record<string, string> | null;
  title?: string | null;
  labels?: boolean;
  width?: number;
  height?: number;
}

const TOKENS = printVegaTokens();
const VL_CONFIG = buildVegaConfig(TOKENS);
const VEGA_CONFIG = buildVegaRuntimeConfig(TOKENS);

async function renderOne(req: ChartRequest): Promise<string | null> {
  const columns = req.columns ?? [];
  const rows = req.rows ?? [];
  const chartType = String(req.chart_type ?? "auto");
  const width = req.width && req.width > 0 ? req.width : 760;

  /**
   * Geo is refused in print, as it was under ECharts — but for a reason worth stating,
   * because the failure is silent otherwise. The base map is fetched from `/geo/world.json`,
   * a relative URL with no base in Node, so the request simply yields nothing: Vega renders
   * an empty shape container and a colour legend reading "NaN to NaN", which is a
   * well-formed SVG of nothing. A null sends the export to the data table instead, which is
   * the honest fallback. Inlining the ~1 MB geojson would double the bundle to fix a chart
   * type the ledger has never once recorded.
   */
  if (chartType === "choropleth" || chartType === "point_map" || chartType === "point-map") return null;

  // Tier 3 first — hand-authored Vega, parsed as written.
  const t3 = resolveTier3Spec({ columns, rows, chartType, title: req.title ?? null });
  if (t3) {
    const height = req.height && req.height > 0 ? req.height : Math.min(Math.max(t3.defaultH, 200), 560);
    const runtime = vega.parse({ ...t3.spec, width, height } as Parameters<typeof vega.parse>[0],
                               VEGA_CONFIG as Parameters<typeof vega.parse>[1]);
    const view = new vega.View(runtime, { renderer: "none" });
    const svg = await view.toSVG();
    view.finalize();
    return svg;
  }

  const resolved = resolveVegaSpec({
    columns, rows, chartType,
    exhibit: req.exhibit ?? null,
    columnUnits: req.column_units ?? null,
    showLabels: req.labels !== false,
    title: req.title ?? null,
  });
  if (!resolved) return null;

  const height = req.height && req.height > 0 ? req.height : Math.min(Math.max(resolved.defaultH, 200), 560);
  const compiled = vl.compile({ ...resolved.spec, width, height } as Parameters<typeof vl.compile>[0],
                              { config: VL_CONFIG }).spec;
  const view = new vega.View(vega.parse(compiled), { renderer: "none" });
  const svg = await view.toSVG();
  view.finalize();
  return svg;
}

// The resolver reads the org currency from the client cache; headless, the export passes
// the resolved SYMBOL and this shim maps it back to a code so the print axis shows
// "CHF 34.7M" exactly as the app did.
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
  const svgs: (string | null)[] = [];
  for (const req of payload.charts ?? []) {
    try {
      svgs.push(await renderOne(req));
    } catch (e) {
      process.stderr.write(`chart-ssr: ${String(e)}\n`);
      svgs.push(null);
    }
  }
  process.stdout.write(JSON.stringify({ svgs }));
}

void main();
