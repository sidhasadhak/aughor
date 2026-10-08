/**
 * One measure, one approved definition (2026-10-08). Approving a metric that measures exactly what an
 * approved one does is refused with the other's name (409 same_as_approved); the person is asked, and only
 * a yes approves it anyway.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { setApproveTwinQuestion, transitionMetric } from "@/lib/api";

const twin = { detail: { reason: "same_as_approved", twin: { name: "return_rate", label: "Return rate" },
  message: "Item Return Rate measures exactly what Return rate measures — the same figure in each of the last 6 months, from the same tables" } };

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("approving a second definition of one measure", () => {
  it("asks, and approves it anyway only on a yes", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return bodies.length === 1 ? respond(409, twin) : respond(200, { metric: {}, audit: {} });
    }));
    const asked: string[] = [];
    setApproveTwinQuestion(m => { asked.push(m); return true; });
    await transitionMetric("item_return_rate", "approve", "thelook");
    expect(asked[0]).toContain("measures exactly what Return rate measures");
    expect(bodies[0].approve_anyway).toBeUndefined();
    expect(bodies[1]).toMatchObject({ action: "approve", connection: "thelook", approve_anyway: true });
  });

  it("a no approves nothing and says why", async () => {
    const calls = vi.fn(async () => respond(409, twin));
    vi.stubGlobal("fetch", calls);
    setApproveTwinQuestion(() => false);
    await expect(transitionMetric("item_return_rate", "approve", "thelook")).rejects.toThrow("measures exactly what Return rate measures");
    expect(calls).toHaveBeenCalledTimes(1);
  });

  it("any other refusal is said as itself, never asked about", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(409, { detail: "already approved" })));
    const ask = vi.fn(() => true);
    setApproveTwinQuestion(ask);
    await expect(transitionMetric("x", "approve", "thelook")).rejects.toThrow("already approved");
    expect(ask).not.toHaveBeenCalled();
  });
});
