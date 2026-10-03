/**
 * The chart edge (CP-5). The bot no longer rasterizes: `POST /charts/png` runs the
 * platform's one rasterizer, and this file only carries the bytes. So the tests pin the
 * request (one grammar, drawn where it is defined, in the org's currency) and that every
 * way of not getting a PNG — 204, a dead API, a body that is not a PNG, a 500 — returns
 * null, so the caller posts its data table alone.
 */
import { describe, expect, it } from "vitest";

import { createChartRenderer } from "./chart.js";

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("IHDR…")]);

const request = {
  columns: ["region", "revenue"],
  rows: [["East", 12], ["West", 9]] as unknown[][],
  chart_type: "bar",
  chart_config: {},
  title: "Revenue by region",
};

describe("createChartRenderer", () => {
  it("asks the platform for the PNG — one rasterizer, the platform's", async () => {
    let seen: { url: string; body: unknown } | null = null;
    const render = createChartRenderer(
      { AUGHOR_API_URL: "http://api.test", AUGHOR_API_KEY: "k", AUGHOR_CONNECTION_ID: "lux" },
      async (url, init) => {
        seen = { url: String(url), body: JSON.parse(String(init?.body)) };
        expect((init?.headers as Record<string, string>)["x-api-key"]).toBe("k");
        return new Response(PNG, { status: 200, headers: { "content-type": "image/png" } });
      },
    );
    const png = await render(request);
    expect(seen!.url).toBe("http://api.test/charts/png");
    // The connection rides along so the door can resolve the org's currency —
    // the symbol is never on the `/ask` wire for a headless caller to relay.
    expect(seen!.body).toEqual({ ...request, connection_id: "lux" });
    expect(png).toEqual(PNG);
  });

  it("204 means the data has no honest chart — not an error to report", async () => {
    const render = createChartRenderer({}, async () => new Response(null, { status: 204 }));
    expect(await render(request)).toBeNull();
  });

  it("a down door, a body that is not a PNG, and a failed render all degrade to the table", async () => {
    const down = createChartRenderer({}, async () => { throw new Error("ECONNREFUSED"); });
    expect(await down(request)).toBeNull();

    const wrong = createChartRenderer({}, async () => new Response("<svg/>", { status: 200 }));
    expect(await wrong(request)).toBeNull();

    const failed = createChartRenderer({}, async () => new Response("boom", { status: 500 }));
    expect(await failed(request)).toBeNull();
  });
});
