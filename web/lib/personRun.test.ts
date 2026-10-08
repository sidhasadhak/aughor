/**
 * A run a person starts is capped at the month's exploration budget (2026-10-08). When the budget is spent the
 * API refuses with the reason (409 budget_spent); the person is asked, and only a yes runs it anyway.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { BudgetSpentError, setRunPastBudgetQuestion, startExplorer } from "@/lib/api";

const spent = { detail: { reason: "budget_spent", message: "the connection's monthly exploration budget of 50,000 tokens is spent" } };

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("a person's run past a spent budget", () => {
  it("asks, and runs it anyway only on a yes", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return urls.length === 1 ? respond(409, spent) : respond(200, { ok: true });
    }));
    const asked: string[] = [];
    setRunPastBudgetQuestion(m => { asked.push(m); return true; });
    await expect(startExplorer("wh")).resolves.toEqual({ ok: true });
    expect(asked[0]).toContain("50,000 tokens is spent");
    expect(urls[1]).toMatch(/\/exploration\/wh\/start\?run_anyway=true$/);
  });

  it("a no runs nothing and says why", async () => {
    const calls = vi.fn(async () => respond(409, spent));
    vi.stubGlobal("fetch", calls);
    setRunPastBudgetQuestion(() => false);
    await expect(startExplorer("wh", "marts")).rejects.toBeInstanceOf(BudgetSpentError);
    expect(calls).toHaveBeenCalledTimes(1);
  });

  it("any other refusal is said as itself, never asked about", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(409, { detail: "already running" })));
    const ask = vi.fn(() => true);
    setRunPastBudgetQuestion(ask);
    await expect(startExplorer("wh")).rejects.toThrow("already running");
    expect(ask).not.toHaveBeenCalled();
  });
});
