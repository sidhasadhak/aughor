/**
 * The approval gate, end to end at the fetch seam (2026-10-09). The walk-through had a person declare, approve in the
 * dialog, and press declare again: approving only allowlisted the action. Now the request the gate refused is held while
 * the person decides and, approved, sent once more — the call site's own `await` gets that answer.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const GATED = { detail: { error: "approval_required", action: "ontology.override", scope: "c1", risk: "high", hint: "h" } };
const answer = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let network: ReturnType<typeof vi.fn>;

async function load() {
  vi.resetModules();
  network = vi.fn();
  vi.stubGlobal("window", { fetch: network });
  return import("@/lib/approval");
}

describe("a request the approval gate holds", () => {
  beforeEach(() => { vi.useRealTimers(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("is sent again once approved, and the caller gets that answer — never a second press", async () => {
    const A = await load();
    network.mockResolvedValueOnce(answer(428, GATED)).mockResolvedValueOnce(answer(200, { id: "p1" }));
    A.onApprovalRequired(info => { expect(info.replays).toBe(true); info.settle?.(true); });
    A.installApprovalInterceptor();
    const init = { method: "PUT", body: JSON.stringify({ kind: "annotate" }) };
    const res = await window.fetch("https://api/ontology/processes", init);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ id: "p1" });
    expect(network.mock.calls).toEqual([["https://api/ontology/processes", init], ["https://api/ontology/processes", init]]);
  });

  it("returns the original refusal when the person does not approve", async () => {
    const A = await load();
    network.mockResolvedValueOnce(answer(428, GATED));
    A.onApprovalRequired(info => info.settle?.(false));
    A.installApprovalInterceptor();
    const res = await window.fetch("https://api/x", { method: "POST", body: "{}" });
    expect(res.status).toBe(428);
    expect((await res.json()).detail.error).toBe("approval_required");                  // the caller still reads it
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("is never sent again when its body cannot be re-read, and a second refusal is never looped", async () => {
    const A = await load();
    network.mockResolvedValue(answer(428, GATED));
    const seen: boolean[] = [];
    A.onApprovalRequired(info => { seen.push(!!info.replays); info.settle?.(true); });
    A.installApprovalInterceptor();
    const stream = new Blob(["x"]).stream();
    expect((await window.fetch("https://api/x", { method: "POST", body: stream, duplex: "half" } as RequestInit)).status).toBe(428);
    expect(network).toHaveBeenCalledTimes(1);
    expect((await window.fetch("https://api/x", { method: "POST", body: "{}" })).status).toBe(428);   // approved, refused again
    expect(network).toHaveBeenCalledTimes(3);                                                          // one replay, no loop
    expect(seen).toEqual([false, true]);
  });

  it("asks once for two requests held on the same approval, and passes any other 428 through untouched", async () => {
    const A = await load();
    let asked = 0;
    let approve: (() => void) | undefined;
    A.onApprovalRequired(info => { asked += 1; approve = () => info.settle?.(true); });
    A.installApprovalInterceptor();
    network.mockResolvedValueOnce(answer(428, GATED)).mockResolvedValueOnce(answer(428, GATED))
      .mockResolvedValue(answer(200, {}));
    const both = Promise.all([window.fetch("https://api/a", { method: "PUT", body: "1" }),
                              window.fetch("https://api/b", { method: "PUT", body: "2" })]);
    await vi.waitFor(() => expect(approve).toBeDefined());
    approve!();
    expect((await both).map(r => r.status)).toEqual([200, 200]);
    expect(asked).toBe(1);
    network.mockResolvedValueOnce(answer(428, { detail: { error: "precondition_failed" } }));
    expect((await window.fetch("https://api/c")).status).toBe(428);
    expect(asked).toBe(1);
  });

  it("with nobody to ask, returns the refusal at once", async () => {
    const A = await load();
    network.mockResolvedValueOnce(answer(428, GATED));
    A.installApprovalInterceptor();
    expect((await window.fetch("https://api/x", { method: "PUT", body: "{}" })).status).toBe(428);
  });
});
