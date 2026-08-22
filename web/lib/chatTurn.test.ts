/**
 * The projection's tests — CA-1.
 *
 * Two contracts, both the reducer used to hold implicitly and this file makes
 * explicit:
 *
 *   1. COVERAGE. Every name in the declared part vocabulary either projects
 *      into the turn or is named as an explicit fallback. The reducer's closed
 *      switch could drop a frame silently; here a dropped name is a FAILING
 *      TEST, which is the whole point of the migration.
 *
 *   2. PARITY. A frame sequence fed through the REAL adapter and the REAL SDK
 *      accumulation (`readUIMessageStream`, not a hand-rolled stand-in) projects
 *      to the same turn the reducer built from the same frames — field by
 *      field, for the quick path, the deep path, the gates and the error tail.
 */

import { describe, expect, it } from "vitest";

import { readUIMessageStream } from "ai";

import { DECLARED_DATA_PARTS } from "./aughorUIDataTypes";
import {
  FALLBACK_PARTS,
  PROJECTED_PARTS,
  projectThread,
  projectTurn,
  type AughorUIMessage,
} from "./chatTurn";
import { adaptFrames, type AughorFrame } from "./uiMessageAdapter";

/** Frames → adapter chunks → the SDK's own accumulator → the final UIMessage. */
async function messageFrom(frames: AughorFrame[]): Promise<AughorUIMessage> {
  const { chunks } = adaptFrames(frames);
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
  let last: AughorUIMessage | undefined;
  for await (const state of readUIMessageStream<AughorUIMessage>({
    stream,
    onError: () => { /* the error chunk's text is asserted via the data part */ },
    terminateOnError: false,
  })) {
    last = state;
  }
  if (!last) throw new Error("stream produced no message");
  return last;
}

function userMsg(id: string, text: string, mode?: "ask" | "investigate"): AughorUIMessage {
  return {
    id,
    role: "user",
    parts: [{ type: "text", text }],
    ...(mode ? { metadata: { mode } } : {}),
  } as AughorUIMessage;
}

describe("coverage: the declared vocabulary has no unclaimed name", () => {
  it("every declared part projects or falls back, explicitly", () => {
    const unclaimed = [...DECLARED_DATA_PARTS].filter(
      (name) => !PROJECTED_PARTS.has(name) && !FALLBACK_PARTS.has(name),
    );
    // A name here means a backend frame renders NOTHING — add a projector to
    // PART_PROJECTORS or (deliberately, with a reason) add it to FALLBACK_PARTS.
    expect(unclaimed).toEqual([]);
  });

  it("nothing is claimed twice — a fallback that also projects hides its rendering", () => {
    const both = [...FALLBACK_PARTS].filter((name) => PROJECTED_PARTS.has(name));
    expect(both).toEqual([]);
  });
});

describe("quick-path parity (the reducer's ask-mode fields)", () => {
  const frames: AughorFrame[] = [
    { event: "start", data: { investigation_id: "inv-1" } },
    { event: "route", data: { depth: "quick", mode: "direct", tier: "simple", why: "lookup" } },
    { event: "sql", data: { sql: "SELECT region, SUM(x) FROM t GROUP BY 1" } },
    { event: "columns", data: { columns: ["region", "total"] } },
    { event: "rows", data: { rows: [["West", 10], ["East", 7]] } },
    { event: "chart_type", data: { chart_type: "bar" } },
    { event: "tables_used", data: { tables: ["t"] } },
    { event: "headline_delta", data: { headline: "West leads" } },
    { event: "headline", data: { headline: "West leads at 10" } },
    { event: "narrative", data: { narrative: "West is ahead.", anomalies: ["East dipped"], trend: "up", confidence: "high" } },
    { event: "followups", data: { questions: ["Break down by month?"] } },
    { event: "analysis", data: { intent: "compare regions", steps: ["group", "sum"] } },
    { event: "receipt_id", data: { receipt_id: "led-9" } },
    { event: "done", data: { has_receipt: true, inv_id: "inv-1" } },
  ];

  it("projects every field the reducer accumulated", async () => {
    const t = projectTurn("which region leads?", await messageFrom(frames));
    expect(t.status).toBe("done");
    expect(t.mode).toBe("ask");
    expect(t.sql).toContain("GROUP BY");
    expect(t.columns).toEqual(["region", "total"]);
    expect(t.rows).toHaveLength(2);
    expect(t.chartType).toBe("bar");
    expect(t.tablesUsed).toEqual(["t"]);
    expect(t.headline).toBe("West leads at 10");
    expect(t.headlineStream).toBeNull(); // the settled value cleared the stream
    expect(t.narrative).toEqual({
      narrative: "West is ahead.", anomalies: ["East dipped"], trend: "up", confidence: "high",
    });
    expect(t.followups).toEqual(["Break down by month?"]);
    expect(t.analysis).toEqual({ intent: "compare regions", steps: ["group", "sum"] });
    expect(t.publicReceiptId).toBe("led-9");
    expect(t.receiptId).toBe("inv-1"); // done carried has_receipt
    expect(t.route?.depth).toBe("quick");
  });

  it("streams the partial while streaming, and only then", async () => {
    const partial = await messageFrom([
      { event: "headline_delta", data: { headline: "West le" } },
      { event: "narrative_delta", data: { narrative: "It looks" } },
    ]);
    const streaming = projectTurn("q", partial, { streaming: true });
    expect(streaming.status).toBe("loading");
    expect(streaming.headlineStream).toBe("West le");
    expect(streaming.narrativeStream).toBe("It looks");

    // The same message no longer streaming (a dropped tail): the words the user
    // watched are promoted rather than vanishing.
    const settled = projectTurn("q", partial, { streaming: false });
    expect(settled.headline).toBe("West le");
    expect(settled.narrativeStream).toBeNull();
  });
});

describe("deep-path parity (the reducer's investigate-mode fields)", () => {
  it("routes deep, accumulates phases, lands the terminal report", async () => {
    const msg = await messageFrom([
      { event: "start", data: { investigation_id: "inv-7" } },
      { event: "route", data: { depth: "deep", mode: "investigate", tier: "complex", why: "causal" } },
      { event: "phase_complete", data: { phase: { phase_id: "baseline", findings: [] } } },
      { event: "phase_complete", data: { phase: { phase_id: "decomposition", findings: [] } } },
      { event: "report_delta", data: { executive_summary: "So far…" } },
      { event: "answer_report", data: {
        answer_report: { headline: "Bots did it", phases: [] },
        query_mode: "investigate",
        investigation_id: "inv-7",
      } },
    ]);
    const t = projectTurn("why did traffic move?", msg);
    expect(t.mode).toBe("investigate"); // the route receipt set it
    expect(t.phases.map((p) => p.phase_id)).toEqual(["baseline", "decomposition"]);
    expect(t.deepReport?.headline).toBe("Bots did it");
    expect(t.reportStream).toBeNull(); // the terminal report replaced the partial
    expect(t.investigationId).toBe("inv-7");
    expect(t.queryMode).toBe("investigate");
    expect(t.status).toBe("done");
  });

  it("keeps the live synthesis prose on its own channel while streaming", async () => {
    const msg = await messageFrom([
      { event: "report_delta", data: { executive_summary: "Deep prose so far" } },
      { event: "narrative_delta", data: { narrative: "quick prose" } },
    ]);
    const t = projectTurn("q", msg, { streaming: true });
    expect(t.reportStream).toBe("Deep prose so far");
    expect(t.narrativeStream).toBe("quick prose");
  });

  it("surfaces a direct report's first query like Quick mode", async () => {
    const msg = await messageFrom([
      { event: "report", data: {
        report: { headline: "42 rows" },
        query_mode: "direct",
        query_history: [{ sql: "SELECT 1", columns: ["c"], rows: [[1]] }],
      } },
      { event: "done", data: {} },
    ]);
    const t = projectTurn("q", msg);
    expect(t.sql).toBe("SELECT 1");
    expect(t.columns).toEqual(["c"]);
    expect(t.queryMode).toBe("direct");
  });
});

describe("gates and the error tail", () => {
  it("a plan gate projects as a settled turn holding the plan", async () => {
    const msg = await messageFrom([
      { event: "plan_pending", data: {
        investigation_id: "inv-3",
        sub_questions: [{ id: "s1", question: "?", purpose: "", expected_output: "" }],
        chain_length: 1, estimated_tokens: 900,
      } },
    ]);
    const t = projectTurn("q", msg);
    expect(t.status).toBe("done"); // paused, not spinning — the resume is its own turn
    expect(t.planPending?.investigationId).toBe("inv-3");
    expect(t.planPending?.subQuestions).toHaveLength(1);
  });

  it("an error frame carries its typed tail into the turn", async () => {
    const msg = await messageFrom([
      { event: "narrative_delta", data: { narrative: "half an ans" } },
      { event: "error", data: { message: "rate limited", reason: "rate_limited", retryable: true, recovery: "retry", hint: "Try again." } },
    ]);
    const t = projectTurn("q", msg);
    expect(t.status).toBe("error");
    expect(t.error).toBe("rate limited");
    expect(t.errorDetail).toEqual({ reason: "rate_limited", retryable: true, recovery: "retry", hint: "Try again." });
  });

  it("a transport-level failure becomes the turn's error tail", () => {
    const t = projectTurn("q", undefined, { transportError: "backend unreachable: ECONNREFUSED" });
    expect(t.status).toBe("error");
    expect(t.error).toContain("backend unreachable");
    expect(t.errorDetail).toBeNull(); // nothing classified it — no invented recovery
  });
});

describe("projectThread — the pairing rule", () => {
  it("pairs user→assistant and leaves a trailing question loading", async () => {
    const answer = await messageFrom([
      { event: "headline", data: { headline: "Done." } },
      { event: "done", data: {} },
    ]);
    const thread = projectThread(
      [userMsg("u1", "first?", "ask"), { ...answer, id: "a1" }, userMsg("u2", "second?", "investigate")],
      { streaming: true },
    );
    expect(thread).toHaveLength(2);
    expect(thread[0].turn.question).toBe("first?");
    expect(thread[0].turn.status).toBe("done");
    expect(thread[0].turn.headline).toBe("Done.");
    expect(thread[1].turn.question).toBe("second?");
    expect(thread[1].turn.mode).toBe("investigate"); // the send's declared mode
    expect(thread[1].turn.status).toBe("loading");
    expect(thread[1].turn.id).toBe("u2"); // keyed by the user message — stable from the send
  });

  it("only the LAST turn wears the transport error", async () => {
    const answer = await messageFrom([
      { event: "headline", data: { headline: "Fine." } },
      { event: "done", data: {} },
    ]);
    const thread = projectThread(
      [userMsg("u1", "ok?"), { ...answer, id: "a1" }, userMsg("u2", "boom?")],
      { transportError: "backend unreachable" },
    );
    expect(thread[0].turn.status).toBe("done");
    expect(thread[1].turn.status).toBe("error");
  });
});

describe("the escape hatch stays an escape hatch", () => {
  it("an unknown frame reaches the message as data-unknown_frame and is NOT projected", async () => {
    const msg = await messageFrom([
      { event: "frame_from_the_future", data: { x: 1 } },
      { event: "done", data: {} },
    ]);
    expect(msg.parts.some((p) => p.type === "data-unknown_frame")).toBe(true);
    // The projection leaves it alone; PartsMessage renders it as a labelled block.
    const t = projectTurn("q", msg);
    expect(t.status).toBe("done");
  });
});

/**
 * VA-2 — a delegated hop is the delegate's work, not the turn's.
 *
 * The frames arrive on the same wire as everything else, carrying a `delegate` stamp.
 * Without routing they land on the turn itself, and because `sql` REPLACES rather than
 * accumulates, the delegate's query silently becomes "the query behind this answer" —
 * a question the supervisor never asked, attributed to the supervisor.
 */
describe("delegated hops", () => {
  const stamp = (over: Record<string, unknown> = {}) => ({
    sub_agent_id: "analyst",
    sub_agent_name: "Analyst",
    parent_agent_id: "",
    agent_path: "analyst",
    depth: 1,
    ...over,
  });

  it("keeps a delegate's SQL off the supervisor's turn", async () => {
    const msg = await messageFrom([
      { event: "sql", data: { sql: "SELECT supervisor" } },
      { event: "sql", data: { sql: "SELECT delegate", delegate: stamp() } },
    ]);
    const t = projectTurn("q", msg);

    expect(t.sql).toBe("SELECT supervisor");
    expect(t.delegations).toHaveLength(1);
    expect(t.delegations[0].work.sql).toBe("SELECT delegate");
  });

  it("carries who ran it", async () => {
    const msg = await messageFrom([
      { event: "sql", data: { sql: "SELECT 1", delegate: stamp() } },
    ]);
    const [hop] = projectTurn("q", msg).delegations;

    expect(hop.agentId).toBe("analyst");
    expect(hop.agentName).toBe("Analyst");
    expect(hop.agentPath).toBe("analyst");
    expect(hop.depth).toBe(1);
    expect(hop.frames).toEqual(["sql"]);
  });

  it("gives each agent its own hop and keeps them in arrival order", async () => {
    const msg = await messageFrom([
      { event: "sql", data: { sql: "A", delegate: stamp() } },
      { event: "sql", data: { sql: "B", delegate: stamp({
        sub_agent_id: "auditor", sub_agent_name: "Auditor",
        parent_agent_id: "analyst", agent_path: "analyst/auditor", depth: 2 }) } },
      { event: "guard_receipt", data: { guard: "grounding", delegate: stamp() } },
    ]);
    const hops = projectTurn("q", msg).delegations;

    expect(hops.map(h => h.agentId)).toEqual(["analyst", "auditor"]);
    expect(hops[0].work.sql).toBe("A");
    expect(hops[0].work.guardReceipts).toHaveLength(1);
    expect(hops[1].work.sql).toBe("B");
    expect(hops[1].parentAgentId).toBe("analyst");
    expect(hops[1].depth).toBe(2);
  });

  it("does not pool a delegate's receipts into the supervisor's evidence", async () => {
    const msg = await messageFrom([
      { event: "guard_receipt", data: { guard: "own" } },
      { event: "guard_receipt", data: { guard: "theirs", delegate: stamp() } },
    ]);
    const t = projectTurn("q", msg);

    expect(t.guardReceipts.map(r => r.guard)).toEqual(["own"]);
    expect(t.delegations[0].work.guardReceipts.map(r => r.guard)).toEqual(["theirs"]);
  });

  it("an undelegated turn has no hops at all", async () => {
    const msg = await messageFrom([{ event: "sql", data: { sql: "SELECT 1" } }]);
    expect(projectTurn("q", msg).delegations).toEqual([]);
  });

  it("ignores a stamp with no agent id rather than drawing an anonymous agent", async () => {
    // Half a stamp is worse than none: a nameless hop reads as the product not knowing
    // who ran the query.
    const msg = await messageFrom([
      { event: "sql", data: { sql: "SELECT 1", delegate: { depth: 1 } } },
    ]);
    const t = projectTurn("q", msg);

    expect(t.delegations).toEqual([]);
    expect(t.sql).toBe("SELECT 1");   // and it stays the turn's own work
  });
});
