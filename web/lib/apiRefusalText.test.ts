/**
 * A refusal the server explains as an OBJECT reaches the screen as a sentence.
 *
 * 2026-10-07, the metric editor: pressing Approve on an Uber metric showed "[object Object]" under
 * the buttons. Approving a metric is high-risk, so the approval gate answered 428 with
 * `{error: "approval_required", action, hint, …}`, and `transitionMetric` did `new Error(detail)`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { transitionMetric } from "./api";

function refuse(status: number, detail: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail }), { status })));
}

afterEach(() => vi.unstubAllGlobals());

/** The error a call rejected with — and a failure of its own when it did not reject. */
async function failure(call: Promise<unknown>): Promise<Error> {
  try {
    await call;
  } catch (e) {
    return e as Error;
  }
  throw new Error("expected the call to be refused");
}

describe("a structured refusal is read, not stringified", () => {
  it("the approval gate's 428 says approval comes first, naming the action", async () => {
    refuse(428, { error: "approval_required", action: "metric.approve", scope: "rides", risk: "high",
                  hint: "High-risk action 'metric.approve' requires approval." });
    const err = await failure(transitionMetric("rides", "approve", "user1", "workspace"));
    expect(err.message).not.toContain("[object Object]");
    expect(err.message).toBe('This needs approval first: approve "metric.approve" in the approval prompt, then try again.');
  });

  it("a {code, why} refusal shows its why", async () => {
    refuse(403, { code: "ORGANISATION_SCOPE_DENIED", why: "'org:b' is another organisation's scope" });
    const err = await failure(transitionMetric("rides", "approve", "user1", "org:b"));
    expect(err.message).toBe("'org:b' is another organisation's scope");
  });

  it("a plain sentence and an unexplained refusal still read as before", async () => {
    refuse(404, "Metric 'rides' not found for connection 'workspace'.");
    expect((await failure(transitionMetric("rides", "approve", "u"))).message)
      .toBe("Metric 'rides' not found for connection 'workspace'.");
    refuse(500, { unexpected: true });
    expect((await failure(transitionMetric("rides", "approve", "u"))).message)
      .toBe("Changing the metric's state failed (500)");
  });
});
