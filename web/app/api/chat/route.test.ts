/**
 * `/api/chat` invariant tests — CI-1d.
 *
 * These stub the upstream rather than run a server, because the three
 * invariants are all about what happens when the upstream misbehaves — and a
 * healthy local backend is exactly the condition under which none of them fire.
 * Each case below is a bug someone already hit through this path.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

/** Read the handler's SSE body back into the chunk objects it encodes. */
async function chunksOf(res: Response): Promise<Record<string, unknown>[]> {
  const text = await res.text();
  return text
    .split("\n\n")
    .map((r) => r.split("\n").find((l) => l.startsWith("data:"))?.slice(5).trim())
    .filter((d): d is string => Boolean(d) && d !== "[DONE]")
    .map((d) => JSON.parse(d) as Record<string, unknown>);
}

function sse(body: string, init: ResponseInit = {}): Response {
  return new Response(body, {
    headers: { "content-type": "text/event-stream" },
    ...init,
  });
}

const ask = (question = "q") =>
  new Request("http://localhost/api/chat", {
    method: "POST",
    body: JSON.stringify({ question, connection_id: "c1" }),
  });

afterEach(() => vi.unstubAllGlobals());

describe("invariant 1 — anything that is not a live SSE body becomes an error chunk", () => {
  it("surfaces an HTML error page instead of spinning forever", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response("<html>502 Bad Gateway</html>", {
        status: 502, headers: { "content-type": "text/html" },
      }));
    const chunks = await chunksOf(await POST(ask()));
    const err = chunks.find((c) => c.type === "error");
    expect(err).toBeDefined();
    expect(String(err?.errorText)).toContain("502");
    // and the message is still well-formed
    expect(chunks.at(-1)?.type).toBe("finish");
  });

  it("carries the demo backend's refusal text verbatim — it is a PRODUCT surface", async () => {
    const refusal = "This demo shows completed analyses. To ask new questions, connect your own backend.";
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ detail: refusal, demo: true }), {
        status: 501, headers: { "content-type": "application/json" },
      }));
    const chunks = await chunksOf(await POST(ask()));
    const err = chunks.find((c) => c.type === "error");
    // Burying this under "Request failed (HTTP 501)" hides the one instruction
    // the reader needs.
    expect(String(err?.errorText)).toContain("connect your own backend");
  });

  it("reports an unreachable backend rather than throwing", async () => {
    vi.stubGlobal("fetch", async () => { throw new Error("ECONNREFUSED"); });
    const chunks = await chunksOf(await POST(ask()));
    expect(String(chunks.find((c) => c.type === "error")?.errorText)).toContain("ECONNREFUSED");
  });

  it("treats a 200 that is not an event-stream as an error", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    expect(await chunksOf(await POST(ask())).then((c) => c.some((x) => x.type === "error")))
      .toBe(true);
  });
});

describe("the happy path", () => {
  it("translates frames into a well-formed chunk stream", async () => {
    vi.stubGlobal("fetch", async () => sse(
      // Real wire format: bare `data:` records, frame name inside the payload.
      'data: {"type":"start","investigation_id":"i1"}\n\n'
      + 'data: {"type":"narrative_delta","narrative":"Rev"}\n\n'
      + 'data: {"type":"narrative_delta","narrative":"Revenue rose"}\n\n'
      + 'data: {"type":"done"}\n\n'));
    const chunks = await chunksOf(await POST(ask()));
    const kinds = chunks.map((c) => c.type);
    expect(kinds[0]).toBe("start");
    expect(kinds).toContain("text-start");
    expect(kinds.at(-1)).toBe("finish");

    // replace→append held across the proxy, not just in the unit test
    const text = chunks.filter((c) => c.type === "text-delta").map((c) => c.delta).join("");
    expect(text).toBe("Revenue rose");
  });

  it("emits nothing after a terminal frame", async () => {
    vi.stubGlobal("fetch", async () => sse(
      'data: {"type":"done"}\n\n'
      + 'data: {"type":"narrative_delta","narrative":"late"}\n\n'));
    const chunks = await chunksOf(await POST(ask()));
    expect(chunks.filter((c) => c.type === "text-delta")).toHaveLength(0);
  });
});

describe("a dropped upstream is not silence", () => {
  it("closes an unterminated message with an abort", async () => {
    // No `done` — the connection died mid-answer.
    vi.stubGlobal("fetch", async () => sse(
      'data: {"type":"narrative_delta","narrative":"half a sent"}\n\n'));
    const chunks = await chunksOf(await POST(ask()));
    const kinds = chunks.map((c) => c.type);
    // Leaving the text block open makes the SDK throw UIMessageStreamError.
    expect(kinds).toContain("text-end");
    expect(kinds).toContain("abort");
  });
});
