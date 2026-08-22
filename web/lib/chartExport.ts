/**
 * chartExport.ts — "download this chart as a PNG", once, for either engine.
 *
 * Chart.tsx and ResultChartCard.tsx each carried their own copy of this: same background
 * token, same filename slug, same anchor dance, both typed to ECharts' synchronous
 * `getDataURL`. Vega produces its image asynchronously, so the duplicate would have had to
 * be fixed twice and would have drifted. One helper, one async-tolerant instance type.
 */

export interface PngOptions {
  type?: string;
  pixelRatio?: number;
  backgroundColor?: string;
}

/** What a chart engine has to expose for the rest of the app to export it. */
export interface ChartInstance {
  getDataURL: (o?: PngOptions) => string | Promise<string>;
}

/** The card surface a chart sits on — a PNG with a transparent ground reads as broken
 *  wherever it is pasted, so both engines export onto this. */
export function chartExportBackground(fallback = "#161A20"): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue("--bg-2").trim() || fallback;
}

export async function downloadChartPng(
  inst: ChartInstance | null | undefined,
  title: string,
): Promise<void> {
  if (!inst) return;
  const url = await Promise.resolve(
    inst.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: chartExportBackground() }),
  );
  if (!url) return;
  const fname = (title || "chart").replace(/[^a-z0-9]+/gi, "_").toLowerCase() + ".png";
  const a = Object.assign(document.createElement("a"), { href: url, download: fname });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
