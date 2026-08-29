/**
 * The transport's one non-obvious job: Aughor's REPLACE-semantic partials
 * (each `*_delta` frame carries the full text-so-far) must fold into an
 * APPEND-semantic stream (every yield is added to the Slack message). Feeding
 * cumulative frames and asserting the joined output has no duplication is the
 * whole point of this file.
 */
import { describe, expect, it } from "vitest";

import { createAskStream } from "./aughor.js";

function sseResponse(frames: Record<string, unknown>[]): Response {
  const body = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

async function drain(iter: AsyncIterable<string>): Promise<string[]> {
  const out: string[] = [];
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
});
