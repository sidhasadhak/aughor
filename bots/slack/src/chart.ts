/**
 * RC-2 — the turn's chart, as a PNG Slack will actually show.
 *
 * Slack does not preview SVG; it files it as an attachment nobody opens. So the bot posts
 * a PNG — and since CP-5 it does not make one. The grammar was always single-sourced (the
 * SVG comes from the same Vega resolver the browser and the PDF use); the last conversion,
 * SVG to PNG, used to happen HERE too, with a second copy of resvg, and Arc CP's census
 * found the same transparent-background defect fixed twice in one day because of it. Now
 * `POST /charts/png` runs the platform's one rasterizer (`export.echarts.svg_to_png`, drawn
 * on white so a dark Slack theme cannot swallow the axis text) and this file only carries
 * the bytes.
 *
 * Every failure returns null and the caller posts its data table alone. A chart is the
 * nice-to-have half of an answer; the numbers are the answer.
 */

export interface ChartRequest {
  columns: string[];
  rows: unknown[][];
  chart_type: string;
  chart_config: Record<string, unknown>;
  title: string;
}

export type ChartRenderer = (req: ChartRequest) => Promise<Buffer | null>;

interface Env {
  AUGHOR_API_URL?: string;
  AUGHOR_API_KEY?: string;
  AUGHOR_CONNECTION_ID?: string;
}

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export function createChartRenderer(
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): ChartRenderer {
  const base = (env.AUGHOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  // The connection names the org whose currency the axis should read in. It is
  // never on the `/ask` wire, so the renderer supplies it the same way the ask
  // stream does — otherwise a euro business gets charts in bare numbers.
  const connection = env.AUGHOR_CONNECTION_ID ?? "workspace";

  return async function renderChart(req) {
    try {
      const res = await fetchImpl(`${base}/charts/png`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {}),
        },
        body: JSON.stringify({ ...req, connection_id: connection }),
      });
      // 204 is the platform's honest "this data has no chart worth drawing" (or no
      // raster could be made) — the same verdict the browser reaches, not an error.
      if (res.status === 204 || !res.ok) return null;
      const png = Buffer.from(await res.arrayBuffer());
      return png.subarray(0, 8).equals(PNG_MAGIC) ? png : null;
    } catch {
      return null; // the API is down; the answer already went out without a picture
    }
  };
}
