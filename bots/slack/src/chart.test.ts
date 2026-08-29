/**
 * The chart edge. The rasterizer runs for real here — the Python `svg_to_png`
 * this replaces returns None on this machine (reportlab's renderPM needs a
 * cairo backend that will not build), and a chart path whose only proof is a
 * mock would have looked exactly as healthy. So one test converts an actual
 * Vega SVG and asserts real PNG bytes come out.
 *
 * Everything else is about degrading honestly: 204, a dead API, a body that
 * is not an SVG, and unrenderable markup all return null, and the caller
 * falls back to the data table.
 */
import { describe, expect, it } from "vitest";

import { createChartRenderer } from "./chart.js";

/** A minimal but real SVG — the shape `/charts/svg` returns. */
const SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">
  <rect x="0" y="20" width="40" height="40" fill="#1f77b4"/>
  <rect x="50" y="5" width="40" height="55" fill="#1f77b4"/>
</svg>`;

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const request = {
  columns: ["region", "revenue"],
  rows: [["East", 12], ["West", 9]] as unknown[][],
  chart_type: "bar",
  chart_config: {},
  title: "Revenue by region",
};

describe("createChartRenderer", () => {
  it("converts the door's SVG into real PNG bytes", async () => {
    const render = createChartRenderer({}, async () =>
      new Response(SVG, { status: 200, headers: { "content-type": "image/svg+xml" } }),
    );
    const png = await render(request);
    expect(png).not.toBeNull();
    expect(png!.subarray(0, 8)).toEqual(PNG_MAGIC);
    expect(png!.length).toBeGreaterThan(100);
  });

  it("asks the platform to draw it — one grammar, rendered where it is defined", async () => {
    let seen: { url: string; body: unknown } | null = null;
    const render = createChartRenderer(
      { AUGHOR_API_URL: "http://api.test", AUGHOR_API_KEY: "k", AUGHOR_CONNECTION_ID: "lux" },
      async (url, init) => {
        seen = { url: String(url), body: JSON.parse(String(init?.body)) };
        expect((init?.headers as Record<string, string>)["x-api-key"]).toBe("k");
        return new Response(SVG, { status: 200 });
      },
    );
    await render(request);
    expect(seen!.url).toBe("http://api.test/charts/svg");
    // The connection rides along so the door can resolve the org's currency —
    // the symbol is never on the `/ask` wire for a headless caller to relay.
    expect(seen!.body).toEqual({ ...request, connection_id: "lux" });
  });

  it("204 means the data has no honest chart — not an error to report", async () => {
    const render = createChartRenderer({}, async () => new Response(null, { status: 204 }));
    expect(await render(request)).toBeNull();
  });

  it("a down door, a non-SVG body, and unrenderable markup all degrade to the table", async () => {
    const down = createChartRenderer({}, async () => { throw new Error("ECONNREFUSED"); });
    expect(await down(request)).toBeNull();

    const wrong = createChartRenderer({}, async () => new Response("<html>nope</html>", { status: 200 }));
    expect(await wrong(request)).toBeNull();

    const broken = createChartRenderer({}, async () => new Response("<svg not xml at all", { status: 200 }));
    expect(await broken(request)).toBeNull();

    const failed = createChartRenderer({}, async () => new Response("boom", { status: 500 }));
    expect(await failed(request)).toBeNull();
  });
});
