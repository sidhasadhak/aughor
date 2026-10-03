/**
 * The registry read and the heartbeat (Arc AO-2a) — the two things this process says to
 * Aughor, driven with a fake fetch so the headers and the body are read, not assumed.
 */
import { describe, expect, it } from "vitest";

import { createHeartbeat, createRegistry } from "./registry.js";

type Call = { url: string; init?: RequestInit };

function fakeFetch(status: number, body: unknown = {}) {
  const calls: Call[] = [];
  const impl = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(body), { status,
      headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { calls, impl };
}

describe("the registry read", () => {
  it("sends the supervisor key and keeps only enabled bots with both tokens", async () => {
    const { calls, impl } = fakeFetch(200, { bots: [
      { id: "a", enabled: true, bot_token: "xoxb", app_token: "xapp" },
      { id: "b", enabled: false, bot_token: "xoxb", app_token: "xapp" },
      { id: "c", enabled: true, bot_token: "", app_token: "xapp" },
    ] });
    const read = createRegistry({ AUGHOR_API_URL: "http://api/", AUGHOR_RUNTIME_KEY: "k1" }, impl);
    const bots = await read();
    expect(bots.map(b => b.id)).toEqual(["a"]);
    expect(calls[0].url).toBe("http://api/slack-bots/runtime");
    expect((calls[0].init?.headers as Record<string, string>)["x-aughor-runtime-key"]).toBe("k1");
  });

  it("names the remedy on a 503", async () => {
    const { impl } = fakeFetch(503);
    await expect(createRegistry({ AUGHOR_API_URL: "http://api" }, impl)()).rejects.toThrow(
      /supervisor key/);
  });
});

describe("the heartbeat", () => {
  const beat = { supervisor_id: "host:1:now", running: ["a"], failed: [{ id: "b", error: "boom" }],
    reconcile_ms: 30_000 };

  it("POSTs what is listening, with the same key the registry read sends", async () => {
    const { calls, impl } = fakeFetch(200, { ok: true });
    const post = createHeartbeat({ AUGHOR_API_URL: "http://api", AUGHOR_RUNTIME_KEY: "k1" }, impl);
    expect(await post(beat)).toBe(true);
    expect(calls[0].url).toBe("http://api/slack-bots/runtime/heartbeat");
    expect(calls[0].init?.method).toBe("POST");
    expect((calls[0].init?.headers as Record<string, string>)["x-aughor-runtime-key"]).toBe("k1");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(beat);
  });

  it("never throws — a refused or unreachable API is a false, not a crash", async () => {
    const refused = createHeartbeat({ AUGHOR_API_URL: "http://api" }, fakeFetch(503).impl);
    expect(await refused(beat)).toBe(false);
    const down = createHeartbeat({ AUGHOR_API_URL: "http://api" },
      (async () => { throw new Error("ECONNREFUSED"); }) as unknown as typeof fetch);
    expect(await down(beat)).toBe(false);
  });
});
