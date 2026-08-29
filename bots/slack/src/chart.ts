/**
 * RC-2 — the turn's chart, as a PNG Slack will actually show.
 *
 * The grammar stays single-sourced: the SVG comes from Aughor's `/charts/svg`
 * door, which runs the SAME Vega resolver the browser and the PDF use, so the
 * picture posted to a thread is the picture the platform would have drawn. What
 * happens HERE is only the last conversion — SVG to PNG — and it happens here
 * for two reasons.
 *
 * Slack does not preview SVG; it files it as an attachment nobody opens. And
 * the repo's one rasterizer (`svg_to_png`, reportlab's renderPM) needs a
 * backend that is absent far more often than present — it is dead on this
 * machine right now, which is why PPTX chart images degrade in silence. resvg
 * ships prebuilt binaries and needs no system library, so the conversion lives
 * at the edge that actually knows the destination's format.
 *
 * Every failure returns null and the caller falls back to its data table. A
 * chart is the nice-to-have half of an answer; the numbers are the answer.
 */
import { Resvg } from "@resvg/resvg-js";

/** 2× the renderer's 760pt default — legible on a retina screen without bloating the upload. */
const PNG_WIDTH = 1520;

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
    let svg: string;
    try {
      const res = await fetchImpl(`${base}/charts/svg`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {}),
        },
        body: JSON.stringify({ ...req, connection_id: connection }),
      });
      // 204 is the renderer's honest "this data has no chart worth drawing" —
      // the same verdict the browser reaches — not an error to report.
      if (res.status === 204 || !res.ok) return null;
      svg = await res.text();
      if (!svg.trim().startsWith("<svg")) return null;
    } catch {
      return null; // the API is down; the answer already went out without a picture
    }

    try {
      return Buffer.from(
        new Resvg(svg, { fitTo: { mode: "width", value: PNG_WIDTH } }).render().asPng(),
      );
    } catch {
      return null;
    }
  };
}
