/**
 * The table edge (CP-5). The bot formats nothing: it asks the platform's one table builder
 * with Slack's encodings and posts what comes back. So these tests pin the REQUEST (the grid,
 * the three numbers that are this door's, the connection whose currency a money column reads
 * in) and that every way of not getting an answer degrades to "no table message", never to a
 * table the bot drew itself. What the table LOOKS like is pinned in Python, beside the rule
 * (`tests/unit/test_exhibit_formatter.py`).
 */
import { describe, expect, it } from "vitest";

import { createTableRenderer, csvFilename, MAX_INLINE_COLS, MAX_INLINE_ROWS, PREVIEW_ROWS } from "./artifacts.js";

const GRID = { columns: ["region", "revenue"], rows: [["East", 54496.64009666443], ["West", 9]] as unknown[][] };

describe("createTableRenderer", () => {
  it("asks the platform with Slack's encodings, and posts what it formatted", async () => {
    let seen: { url: string; body: Record<string, unknown> } | null = null;
    const render = createTableRenderer(
      { AUGHOR_API_URL: "http://api.test/", AUGHOR_API_KEY: "k", AUGHOR_CONNECTION_ID: "thelook" },
      async (url, init) => {
        seen = { url: String(url), body: JSON.parse(String(init?.body)) };
        expect((init?.headers as Record<string, string>)["x-api-key"]).toBe("k");
        return Response.json({ show: true, markdown: "| Region | Revenue |\n| --- | --- |\n| East | $54,496.64 |", csv: null });
      },
    );
    const table = await render(GRID);
    expect(seen!.url).toBe("http://api.test/exhibits/table");
    expect(seen!.body).toEqual({
      ...GRID,
      max_cols: MAX_INLINE_COLS, max_rows: MAX_INLINE_ROWS, preview_rows: PREVIEW_ROWS,
      rest: "the full result is attached as CSV",
      connection_id: "thelook",
    });
    expect(table).toEqual({ markdown: "| Region | Revenue |\n| --- | --- |\n| East | $54,496.64 |", csv: null });
  });

  it("carries the CSV when the platform says the markdown does not hold every row", async () => {
    const render = createTableRenderer({}, async () =>
      Response.json({ show: true, markdown: "_Showing 5 of 60 rows — the full result is attached as CSV._", csv: "a,b\n1,2" }));
    expect(await render(GRID)).toEqual({
      markdown: "_Showing 5 of 60 rows — the full result is attached as CSV._", csv: "a,b\n1,2" });
  });

  it("a grid not worth showing, an empty grid, a failed or absent door — no table, never a homemade one", async () => {
    const quiet = createTableRenderer({}, async () => Response.json({ show: false, markdown: "", csv: null }));
    expect(await quiet(GRID)).toBeNull();

    let called = false;
    const empty = createTableRenderer({}, async () => { called = true; return Response.json({ show: true }); });
    expect(await empty({ columns: [], rows: [] })).toBeNull();
    expect(called).toBe(false);

    const failed = createTableRenderer({}, async () => new Response("boom", { status: 500 }));
    expect(await failed(GRID)).toBeNull();

    const down = createTableRenderer({}, async () => { throw new Error("ECONNREFUSED"); });
    expect(await down(GRID)).toBeNull();
  });
});

describe("csvFilename", () => {
  it("is safe to upload and still says what it is", () => {
    expect(csvFilename("Why did revenue dip in Q3?")).toBe("why-did-revenue-dip-in-q3.csv");
    expect(csvFilename("???")).toBe("result.csv");
    expect(csvFilename("x".repeat(200)).length).toBeLessThanOrEqual(44);
  });
});
