/**
 * The transport's one non-obvious job: Aughor's REPLACE-semantic partials
 * (each `*_delta` frame carries the full text-so-far) must fold into an
 * APPEND-semantic stream (every yield is added to the Slack message). Feeding
 * cumulative frames and asserting the joined output has no duplication is the
 * whole point of this file.
 */
import { describe, expect, it } from "vitest";

import { createAskStream, type AskChunk } from "./aughor.js";

function sseResponse(frames: Record<string, unknown>[]): Response {
  const body = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

/** The prose half of the stream — the text a reader actually sees. */
async function drain(iter: AsyncIterable<AskChunk>): Promise<string[]> {
  const out: string[] = [];
  for await (const chunk of iter) if (typeof chunk === "string") out.push(chunk);
  return out;
}

/** Everything, cards included, in wire order. */
async function drainAll(iter: AsyncIterable<AskChunk>): Promise<AskChunk[]> {
  const out: AskChunk[] = [];
  for await (const chunk of iter) out.push(chunk);
  return out;
}

describe("createAskStream", () => {
  it("folds cumulative partials into suffix-only yields — no duplication", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "start", investigation_id: "inv-1" },
        { type: "headline_delta", headline: "East is" },
        { type: "headline_delta", headline: "East is flat." },
        { type: "narrative_delta", narrative: "Volume held" },
        { type: "narrative_delta", narrative: "Volume held steady." },
        { type: "done" },
      ]),
    );
    const chunks = await drain(ask("q", { sessionId: "slack:C1:t1" }));
    expect(chunks.join("")).toBe("East is flat.\n\nVolume held steady.");
  });

  it("settled text wins over its stream without repeating it", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "headline_delta", headline: "West leads" },
        { type: "headline", headline: "West leads in margin." },
        { type: "done" },
      ]),
    );
    const chunks = await drain(ask("q", { sessionId: "s" }));
    expect(chunks.join("")).toBe("West leads in margin.");
  });

  it("a deep turn lands as the report's own words", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "answer_report", answer_report: { headline: "Discounts drove the dip.", summary: "Machines discounting explains most of it." } },
        { type: "done" },
      ]),
    );
    const chunks = await drain(ask("q", { sessionId: "s" }));
    expect(chunks.join("")).toBe("Discounts drove the dip.\n\nMachines discounting explains most of it.");
  });

  it("an error frame ends the stream honestly", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "headline_delta", headline: "Part" },
        { type: "error", message: "the model is in quota cooldown" },
        { type: "headline_delta", headline: "Partial that must not appear" },
      ]),
    );
    const chunks = await drain(ask("q", { sessionId: "s" }));
    expect(chunks.join("")).toBe("Part\n\n⚠️ the model is in quota cooldown");
  });

  it("a rate-limit wall becomes one bounded sentence — hint first, raw text capped", async () => {
    const wall = Array(3).fill(`Error code: 429 - ${"x".repeat(400)}`).join(" · ");
    const withHint = createAskStream({}, async () =>
      sseResponse([{ type: "error", message: wall, hint: "retry in a minute — the model hit its per-minute limit" }]),
    );
    expect((await drain(withHint("q", { sessionId: "s" }))).join(""))
      .toBe("⚠️ retry in a minute — the model hit its per-minute limit");

    const noHint = createAskStream({}, async () =>
      sseResponse([{ type: "error", message: wall }]),
    );
    const text = (await drain(noHint("q", { sessionId: "s" }))).join("");
    expect(text.length).toBeLessThan(260);
    expect(text).toMatch(/^⚠️ Error code: 429/);
    expect(text).not.toContain(" · "); // one attempt, not the chain's whole retry log
  });

  it("a down API yields one plain sentence, not an exception", async () => {
    const ask = createAskStream({ AUGHOR_API_URL: "http://127.0.0.1:9" }, async () =>
      new Response("", { status: 503 }),
    );
    const chunks = await drain(ask("q", { sessionId: "s" }));
    expect(chunks.join("")).toMatch(/did not answer \(HTTP 503\)/);
  });

  it("sends the door the right request: /ask, auto depth, thread as conversation", async () => {
    let seen: { url: string; body: Record<string, unknown> } | null = null;
    const ask = createAskStream(
      { AUGHOR_API_URL: "http://api.test", AUGHOR_CONNECTION_ID: "conn-9", AUGHOR_API_KEY: "k" },
      async (url, init) => {
        seen = { url: String(url), body: JSON.parse(String(init?.body)) };
        expect((init?.headers as Record<string, string>)["x-api-key"]).toBe("k");
        return sseResponse([{ type: "done" }]);
      },
    );
    await drain(ask("why did revenue dip?", { sessionId: "slack:C9:42.1" }));
    expect(seen!.url).toBe("http://api.test/ask");
    expect(seen!.body).toMatchObject({
      question: "why did revenue dip?",
      connection_id: "conn-9",
      depth: "auto",
      session_id: "slack:C9:42.1",
    });
  });

  it("carries the asker so a Slack turn is attributed to a person (RC-4)", async () => {
    let body: Record<string, unknown> = {};
    const ask = createAskStream({ AUGHOR_API_URL: "http://api.test" }, async (_u, init) => {
      body = JSON.parse(String(init?.body));
      return sseResponse([{ type: "done" }]);
    });
    await drain(ask("q", { sessionId: "s", principalRef: "slack:U08N9EQ80UT" }));
    expect(body.principal_ref).toBe("slack:U08N9EQ80UT");
  });

  it("omits the asker entirely when the door does not know one", async () => {
    // Absent, a turn must be honestly unattributed. Sending an empty string would put a
    // blank in the actor field, which is the shape of the defect this wave fixed.
    let body: Record<string, unknown> = {};
    const ask = createAskStream({ AUGHOR_API_URL: "http://api.test" }, async (_u, init) => {
      body = JSON.parse(String(init?.body));
      return sseResponse([{ type: "done" }]);
    });
    await drain(ask("q", { sessionId: "s" }));
    expect("principal_ref" in body).toBe(false);
  });
});

describe("createAskStream — RC-2", () => {
  it("progress frames ride the same stream as the prose, as task cards", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "start", investigation_id: "inv-7" },
        { type: "phase_progress", phase_id: "root_cause", done: 1, total: 3, current: "region" },
        { type: "phase_complete", phase: { phase_id: "root_cause", phase_name: "Root cause", status: "complete", summary: "Discounting explains 61%." } },
        { type: "headline", headline: "Discounts drove the dip." },
        { type: "done" },
      ]),
    );
    const all = await drainAll(ask("q", { sessionId: "s" }));

    // The prose is untouched by the cards riding beside it.
    expect(all.filter((c) => typeof c === "string").join("")).toBe("Discounts drove the dip.");

    const cards = all.filter((c) => typeof c !== "string");
    expect(cards).toEqual([
      { type: "task_update", id: "phase-root_cause", title: "Root cause", status: "in_progress", details: "Scanning region · 1/3" },
      { type: "task_update", id: "phase-root_cause", title: "Root cause", status: "complete", output: "Discounting explains 61%." },
    ]);
  });

  it("the turn's grid and chart reach the caller once it settles", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "start", investigation_id: "inv-9" },
        { type: "columns", columns: ["region", "revenue"] },
        { type: "rows", rows: [["East", 12], ["West", 9]] },
        { type: "chart_type", chart_type: "bar" },
        { type: "chart_config", chart_config: { exhibit: { kind: "ranked" } } },
        { type: "headline", headline: "East leads." },
        { type: "done" },
      ]),
    );
    const seen: unknown[] = [];
    await drain(ask("why?", { sessionId: "slack:C1:1", onTurn: (a) => seen.push(a) }));

    expect(seen).toEqual([{
      investigationId: "inv-9",
      question: "why?",
      sessionId: "slack:C1:1",
      columns: ["region", "revenue"],
      rows: [["East", 12], ["West", 9]],
      chartType: "bar",
      chartConfig: { exhibit: { kind: "ranked" } },
    }]);
  });

  it("a failed turn exhibits nothing — half a grid under a failure reads as an answer", async () => {
    const ask = createAskStream({}, async () =>
      sseResponse([
        { type: "columns", columns: ["region"] },
        { type: "rows", rows: [["East"]] },
        { type: "error", message: "the warehouse refused the query" },
      ]),
    );
    const seen: unknown[] = [];
    await drain(ask("q", { sessionId: "s", onTurn: (a) => seen.push(a) }));
    expect(seen).toEqual([]);
  });

  it("an abandoned run is CANCELLED, not merely dropped", async () => {
    // Since FL-1 detached the producer from its viewer, closing the stream no
    // longer stops the work — it only stops anyone watching it spend.
    const posted: { url: string; aborted: boolean }[] = [];
    const ctl = new AbortController();
    const ask = createAskStream({ AUGHOR_API_URL: "http://api.test" }, async (url, init) => {
      posted.push({ url: String(url), aborted: Boolean(init?.signal?.aborted) });
      if (String(url).endsWith("/cancel")) return new Response("{}", { status: 200 });
      return new Response(
        new ReadableStream<Uint8Array>({
          start(c) {
            const enc = new TextEncoder();
            c.enqueue(enc.encode('data: {"type":"start","investigation_id":"inv-live"}\n\n'));
            c.enqueue(enc.encode('data: {"type":"headline_delta","headline":"partial"}\n\n'));
            // Never closed: the run is still going when the reader walks away.
          },
        }),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    });

    for await (const chunk of ask("q", { sessionId: "s", signal: ctl.signal })) {
      if (typeof chunk === "string") { ctl.abort(); break; }
    }

    expect(posted.map((p) => p.url)).toEqual([
      "http://api.test/ask",
      "http://api.test/investigations/inv-live/cancel",
    ]);
    // The kill must outlive the request that was just abandoned.
    expect(posted[1].aborted).toBe(false);
  });

  it("a completed run is never cancelled", async () => {
    const urls: string[] = [];
    const ctl = new AbortController();
    const ask = createAskStream({ AUGHOR_API_URL: "http://api.test" }, async (url) => {
      urls.push(String(url));
      return sseResponse([
        { type: "start", investigation_id: "inv-done" },
        { type: "headline", headline: "Done." },
        { type: "done" },
      ]);
    });
    await drain(ask("q", { sessionId: "s", signal: ctl.signal }));
    ctl.abort(); // the turn is over; a later abort must not reach back
    expect(urls).toEqual(["http://api.test/ask"]);
  });
});
