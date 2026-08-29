/**
 * RC-5.3 — one process, N sockets, reconciled.
 *
 * The properties below are the ones a plausible supervisor gets wrong, and each has
 * cost someone a real outage somewhere:
 *
 *  - restarting a bot whose record did not change (drops a live thread for nothing)
 *  - letting ONE bad credential take down the whole fleet
 *  - tearing down working sockets when the registry is briefly unreachable
 *  - treating a rename as a credential change
 */
import { describe, expect, it, vi } from "vitest";

import { fingerprint, type BotRecord } from "./registry.js";
import { createSupervisor } from "./supervisor.js";

const rec = (over: Partial<BotRecord> = {}): BotRecord => ({
  id: "b1", name: "salesbot", enabled: true,
  agent_id: "ag-1", connection_id: "conn-a",
  bot_token: "xoxb-1", app_token: "xapp-1", signing_secret: "s1",
  agent_view: false,
  ...over,
});

/** A stand-in socket that records whether it was shut down. */
const fakeBot = () => {
  const bot = { down: false, shutdown: vi.fn(async () => { bot.down = true; }) };
  return bot;
};

describe("supervisor", () => {
  it("starts one socket per enabled record", async () => {
    const made: string[] = [];
    const s = createSupervisor({
      fetchBots: async () => [rec({ id: "a" }), rec({ id: "b" })],
      makeBot: (r) => { made.push(r.id); return fakeBot(); },
    });
    const out = await s.reconcile();
    expect(made).toEqual(["a", "b"]);
    expect(out.started).toEqual(["a", "b"]);
    expect(out.running).toBe(2);
  });

  it("is idempotent — an unchanged record keeps its socket", async () => {
    // The one that matters most: a reconcile tick every 30s must not drop the WebSocket
    // of everyone mid-thread just because the timer fired.
    const made: string[] = [];
    const bots = [rec({ id: "a" })];
    const s = createSupervisor({
      fetchBots: async () => bots,
      makeBot: (r) => { made.push(r.id); return fakeBot(); },
    });
    await s.reconcile();
    const second = await s.reconcile();
    expect(made).toEqual(["a"]);            // built once, not twice
    expect(second.started).toEqual([]);
    expect(second.restarted).toEqual([]);
  });

  it("restarts a bot whose credentials changed", async () => {
    let current = rec({ id: "a", bot_token: "xoxb-old" });
    const first = fakeBot();
    const made = [first, fakeBot()];
    let i = 0;
    const s = createSupervisor({
      fetchBots: async () => [current],
      makeBot: () => made[i++],
    });
    await s.reconcile();
    current = rec({ id: "a", bot_token: "xoxb-rotated" });
    const out = await s.reconcile();

    expect(out.restarted).toEqual(["a"]);
    expect(first.down).toBe(true);          // the stale socket was closed, not leaked
  });

  it("does NOT restart on a rename", async () => {
    // A name is a label. Dropping a live socket to change one would interrupt whoever
    // is mid-thread for a purely cosmetic edit.
    let current = rec({ id: "a", name: "old" });
    const made: number[] = [];
    const s = createSupervisor({
      fetchBots: async () => [current],
      makeBot: () => { made.push(1); return fakeBot(); },
    });
    await s.reconcile();
    current = rec({ id: "a", name: "new" });
    const out = await s.reconcile();
    expect(out.restarted).toEqual([]);
    expect(made).toHaveLength(1);
  });

  it("stops a bot that left the registry", async () => {
    let bots = [rec({ id: "a" }), rec({ id: "b" })];
    const built = new Map<string, ReturnType<typeof fakeBot>>();
    const s = createSupervisor({
      fetchBots: async () => bots,
      makeBot: (r) => { const b = fakeBot(); built.set(r.id, b); return b; },
    });
    await s.reconcile();
    bots = [rec({ id: "a" })];
    const out = await s.reconcile();

    expect(out.stopped).toEqual(["b"]);
    expect(built.get("b")!.down).toBe(true);
    expect(s.runningIds()).toEqual(["a"]);
  });

  it("one bad credential does not take down the fleet", async () => {
    const s = createSupervisor({
      fetchBots: async () => [rec({ id: "good" }), rec({ id: "bad" }), rec({ id: "good2" })],
      makeBot: (r) => {
        if (r.id === "bad") throw new Error("invalid_auth");
        return fakeBot();
      },
    });
    const out = await s.reconcile();

    expect(out.started.sort()).toEqual(["good", "good2"]);
    expect(out.failed).toEqual([{ id: "bad", error: "Error: invalid_auth" }]);
    expect(out.running).toBe(2);
  });

  it("retries a failed bot on the next tick, with no process restart", async () => {
    let broken = true;
    const s = createSupervisor({
      fetchBots: async () => [rec({ id: "a" })],
      makeBot: () => {
        if (broken) throw new Error("invalid_auth");
        return fakeBot();
      },
    });
    expect((await s.reconcile()).running).toBe(0);
    broken = false;                                  // the token is fixed in Aughor
    expect((await s.reconcile()).running).toBe(1);   // and it recovers on its own
  });

  it("keeps running sockets when the registry is unreachable", async () => {
    // A brief API blip is not the same as "there are no bots". Tearing the fleet down
    // on a failed read would turn a 5-second outage into a Slack-wide one.
    let fail = false;
    const s = createSupervisor({
      fetchBots: async () => {
        if (fail) throw new Error("ECONNREFUSED");
        return [rec({ id: "a" })];
      },
      makeBot: () => fakeBot(),
    });
    await s.reconcile();
    fail = true;
    const out = await s.reconcile();

    expect(out.running).toBe(1);
    expect(out.stopped).toEqual([]);
    expect(s.runningIds()).toEqual(["a"]);
  });

  it("shutdown closes every socket", async () => {
    const built: ReturnType<typeof fakeBot>[] = [];
    const s = createSupervisor({
      fetchBots: async () => [rec({ id: "a" }), rec({ id: "b" })],
      makeBot: () => { const b = fakeBot(); built.push(b); return b; },
    });
    await s.reconcile();
    await s.shutdown();
    expect(built.every((b) => b.down)).toBe(true);
    expect(s.runningIds()).toEqual([]);
  });

  it("a socket that will not close cleanly does not block the others", async () => {
    const stubborn = { shutdown: vi.fn(async () => { throw new Error("nope"); }) };
    const ok = fakeBot();
    let bots = [rec({ id: "stubborn" }), rec({ id: "ok" })];
    const s = createSupervisor({
      fetchBots: async () => bots,
      makeBot: (r) => (r.id === "stubborn" ? stubborn : ok),
    });
    await s.reconcile();
    bots = [];
    const out = await s.reconcile();
    expect(out.stopped.sort()).toEqual(["ok", "stubborn"]);
    expect(ok.down).toBe(true);
  });
});

describe("fingerprint", () => {
  it("changes for every field that changes what the socket is", () => {
    const base = rec();
    for (const change of [{ bot_token: "x" }, { app_token: "x" }, { signing_secret: "x" },
                          { agent_id: "x" }, { connection_id: "x" }, { agent_view: true }]) {
      expect(fingerprint({ ...base, ...change })).not.toBe(fingerprint(base));
    }
  });

  it("ignores the name", () => {
    expect(fingerprint(rec({ name: "a" }))).toBe(fingerprint(rec({ name: "b" })));
  });
});
