/**
 * The adapter's first tests — CI-1d.
 *
 * The C1 spike shipped with ZERO tests and zero consumers, and its central
 * claim (that its hand-written types were "structurally identical" to the AI
 * SDK's) turned out to be wrong in three ways. That is the shape of failure
 * this file exists to prevent: a module that looks correct because nothing ever
 * ran it — the same failure as the Langfuse backend that reported itself
 * enabled while shipping nothing.
 *
 * These assert BEHAVIOUR against the real `ai@7` chunk protocol, not that the
 * adapter calls the methods we think it calls.
 */

import { describe, expect, it } from "vitest";

import { AughorToUIMessage, adaptFrames, isDeclaredDataPart } from "./uiMessageAdapter";

/** Concatenate every text-delta for a given part id, in order. */
function textFor(chunks: ReturnType<typeof adaptFrames>["chunks"], id?: string): string {
  return chunks
    .filter((c) => c.type === "text-delta" && (id === undefined || c.id === id))
    .map((c) => (c as { delta: string }).delta)
    .join("");
}

const kinds = (chunks: ReturnType<typeof adaptFrames>["chunks"]) => chunks.map((c) => c.type);

describe("replace → append (the trap this module exists to solve)", () => {
  it("emits only the new suffix, so a growing partial does not duplicate its prefix", () => {
    const { chunks } = adaptFrames([
      { event: "start", data: { investigation_id: "inv1" } },
      { event: "narrative_delta", data: { narrative: "The" } },
      { event: "narrative_delta", data: { narrative: "The re" } },
      { event: "narrative_delta", data: { narrative: "The revenue rose" } },
      { event: "done", data: {} },
    ]);
    // The bug this prevents renders "TheThe reThe revenue rose".
    expect(textFor(chunks)).toBe("The revenue rose");
  });

  it("emits no delta when a partial repeats unchanged", () => {
    const { chunks } = adaptFrames([
      { event: "narrative_delta", data: { narrative: "same" } },
      { event: "narrative_delta", data: { narrative: "same" } },
    ]);
    expect(chunks.filter((c) => c.type === "text-delta")).toHaveLength(1);
  });

  it("starts a NEW text block when a partial rewrites its own prefix", () => {
    const { chunks } = adaptFrames([
      { event: "narrative_delta", data: { narrative: "Revenue fell" } },
      { event: "narrative_delta", data: { narrative: "Margin rose" } }, // re-synthesis
    ]);
    const starts = chunks.filter((c) => c.type === "text-start");
    const ends = chunks.filter((c) => c.type === "text-end");
    expect(starts).toHaveLength(2);
    expect(ends).toHaveLength(1); // the first block closed before the second opened

    // The two blocks carry different ids — a spliced edit would reuse one id.
    const ids = [...new Set(starts.map((c) => (c as { id: string }).id))];
    expect(ids).toHaveLength(2);
    expect(textFor(chunks, ids[1])).toBe("Margin rose");
  });

  it("keeps headline and narrative on separate part ids", () => {
    const { chunks } = adaptFrames([
      { event: "narrative_delta", data: { narrative: "body" } },
      { event: "headline_delta", data: { headline: "title" } },
    ]);
    const ids = [...new Set(chunks.filter((c) => c.type === "text-start")
      .map((c) => (c as { id: string }).id))];
    expect(ids).toHaveLength(2);
  });
});

describe("message framing (the chunks the spike never emitted)", () => {
  it("opens with `start` and closes with `finish`", () => {
    const k = kinds(adaptFrames([
      { event: "start", data: {} },
      { event: "narrative_delta", data: { narrative: "hi" } },
      { event: "done", data: {} },
    ]).chunks);
    expect(k[0]).toBe("start");
    expect(k.at(-1)).toBe("finish");
  });

  it("opens the message even when no wire `start` frame arrives first", () => {
    const k = kinds(adaptFrames([{ event: "narrative_delta", data: { narrative: "hi" } }]).chunks);
    expect(k[0]).toBe("start");
  });

  it("closes every open text block before finishing", () => {
    const k = kinds(adaptFrames([
      { event: "narrative_delta", data: { narrative: "hi" } },
      { event: "done", data: {} },
    ]).chunks);
    expect(k.indexOf("text-end")).toBeGreaterThan(-1);
    expect(k.indexOf("text-end")).toBeLessThan(k.indexOf("finish"));
  });
});

describe("terminal invariants", () => {
  it("surfaces the investigation id for drop-recovery", () => {
    const r = adaptFrames([{ event: "start", data: { investigation_id: "inv-42" } }]);
    expect(r.investigationId).toBe("inv-42");
  });

  it("emits nothing after a terminal frame", () => {
    const a = new AughorToUIMessage();
    a.feed({ event: "done", data: {} });
    const after = a.feed({ event: "narrative_delta", data: { narrative: "late" } });
    expect(after.chunks).toEqual([]);
    expect(after.terminal).toBe(true);
  });

  it("turns an error frame into an `error` chunk carrying the message", () => {
    const { chunks, terminal } = adaptFrames([
      { event: "error", data: { message: "boom" } },
    ]);
    const err = chunks.find((c) => c.type === "error") as { errorText: string } | undefined;
    expect(err?.errorText).toBe("boom");
    expect(terminal).toBe(true);
  });

  it("a report frame is terminal and carries the WHOLE payload as one data part", () => {
    const { chunks, terminal } = adaptFrames([
      { event: "narrative_delta", data: { narrative: "partial…" } },
      { event: "answer_report", data: { headline: "Revenue rose", figures: [1, 2] } },
    ]);
    expect(terminal).toBe(true);
    const part = chunks.find((c) => c.type === "data-answer_report") as
      | { data: Record<string, unknown> } | undefined;
    expect(part?.data.headline).toBe("Revenue rose");
    // the partial's block was closed before the report replaced it
    expect(kinds(chunks).indexOf("text-end")).toBeLessThan(kinds(chunks).indexOf("data-answer_report"));
  });

  it("abort leaves a dropped turn well-formed", () => {
    const a = new AughorToUIMessage();
    a.feed({ event: "narrative_delta", data: { narrative: "half a sent" } });
    const k = a.abort("connection lost").map((c) => c.type);
    expect(k).toContain("text-end");
    expect(k).toContain("abort");
    expect(a.abort()).toEqual([]); // idempotent
  });
});

describe("the unknown-frame path (why an open model beats a closed switch)", () => {
  it("forwards a declared advisory frame as its typed data part", () => {
    const { chunks } = adaptFrames([{ event: "sql", data: { sql: "SELECT 1" } }]);
    expect(kinds(chunks)).toContain("data-sql");
  });

  it("forwards an UNDECLARED frame through the escape hatch, naming it", () => {
    // The reducer's closed switch can only warn here; a data part actually
    // reaches the shell, which may ignore it but cannot be unaware of it.
    // It rides under the DECLARED `unknown_frame` name — `data-${anything}`
    // does not type-check against a closed map, and an `as` that silences the
    // emit site still fails at the consume site.
    const { chunks } = adaptFrames([{ event: "frame_from_the_future", data: { x: 1 } }]);
    const part = chunks.find((c) => c.type === "data-unknown_frame");
    expect(part).toBeDefined();
    // Narrowed by the discriminant — no cast, which is the property being tested.
    if (part?.type !== "data-unknown_frame") throw new Error("unreachable");
    expect(part.data.event).toBe("frame_from_the_future");
    expect(part.data.payload.x).toBe(1);
    expect(isDeclaredDataPart("frame_from_the_future")).toBe(false);
  });

  it("knows which names are declared", () => {
    expect(isDeclaredDataPart("guard_receipt")).toBe(true);
    expect(isDeclaredDataPart("nope")).toBe(false);
  });

  it("skips a DELIBERATELY silent frame instead of calling it unrecognised", () => {
    // `compiled` is in the reducer's UNRENDERED_FRAMES. A live run surfaced it
    // through the escape hatch, which would render deliberate silence as a gap
    // — the exact ambiguity that list was created to end.
    const { chunks } = adaptFrames([{ event: "compiled", data: { n: 1 } }]);
    expect(chunks.filter((c) => c.type.startsWith("data-"))).toHaveLength(0);
  });

  it("still surfaces a frame that is in NEITHER list", () => {
    // The skip above must not become a general silencer.
    const { chunks } = adaptFrames([{ event: "brand_new_frame", data: {} }]);
    expect(chunks.some((c) => c.type === "data-unknown_frame")).toBe(true);
  });
});

describe("the payload the text channel cannot carry (CA-1)", () => {
  // The reducer read structure off settled and terminal frames that a text
  // channel or a bare error string drops. Each of these is a field the
  // projection (`chatTurn.ts`) reconstitutes — losing the part loses the field.

  it("stamps every text block with its channel, so the projection can tell them apart", () => {
    const { chunks } = adaptFrames([
      { event: "headline_delta", data: { headline: "Total" } },
      { event: "narrative_delta", data: { narrative: "It rose" } },
      { event: "report_delta", data: { executive_summary: "Deep prose" } },
    ]);
    const channels = chunks
      .filter((c) => c.type === "text-start")
      .map((c) => (c as { providerMetadata?: { aughor?: { channel?: string } } })
        .providerMetadata?.aughor?.channel);
    expect(channels).toEqual(["headline", "narrative", "report"]);
  });

  it("a settled narrative rides as data too — anomalies/trend/confidence survive", () => {
    const { chunks } = adaptFrames([
      { event: "narrative", data: { narrative: "Up 4%", anomalies: ["spike"], trend: "up", confidence: "high" } },
    ]);
    expect(textFor(chunks)).toBe("Up 4%");
    const part = chunks.find((c) => c.type === "data-narrative") as
      | { data: Record<string, unknown> } | undefined;
    expect(part?.data.anomalies).toEqual(["spike"]);
  });

  it("normalises the legacy `insight` spelling onto `narrative`", () => {
    const { chunks } = adaptFrames([{ event: "insight", data: { insight: "legacy words" } }]);
    expect(chunks.some((c) => c.type === "data-narrative")).toBe(true);
    expect(chunks.some((c) => (c.type as string) === "data-insight")).toBe(false);
  });

  it("deltas stay text-only — no data part per keystroke", () => {
    const { chunks } = adaptFrames([{ event: "headline_delta", data: { headline: "Tot" } }]);
    expect(chunks.filter((c) => c.type.startsWith("data-"))).toHaveLength(0);
  });

  it("an error frame's typed tail (Wave R4) rides as data beside the error chunk", () => {
    const { chunks } = adaptFrames([
      { event: "error", data: { message: "rate limited", reason: "rate_limited", retryable: true, recovery: "retry", hint: "Try again." } },
    ]);
    const part = chunks.find((c) => c.type === "data-error") as
      | { data: Record<string, unknown> } | undefined;
    expect(part?.data.reason).toBe("rate_limited");
    expect(chunks.some((c) => c.type === "error")).toBe(true);
  });

  it("a done that names the Trust Receipt rides as data; a bare done stays partless", () => {
    const withReceipt = adaptFrames([{ event: "done", data: { has_receipt: true, inv_id: "abc" } }]);
    const part = withReceipt.chunks.find((c) => c.type === "data-done") as
      | { data: Record<string, unknown> } | undefined;
    expect(part?.data.inv_id).toBe("abc");

    const bare = adaptFrames([{ event: "done", data: {} }]);
    expect(bare.chunks.some((c) => c.type === "data-done")).toBe(false);
  });

  it("a gate frame (P3/P4 pause) closes the message cleanly instead of reading as a drop", () => {
    // The upstream ends at a gate without a `done`; before this the route's
    // "ended without a terminal frame" abort fired on every deliberate pause.
    const { chunks, terminal } = adaptFrames([
      { event: "plan_pending", data: { investigation_id: "inv9", sub_questions: [] } },
    ]);
    expect(terminal).toBe(true);
    expect(chunks.some((c) => c.type === "data-plan_pending")).toBe(true);
    expect(kinds(chunks).at(-1)).toBe("finish");
    expect(chunks.some((c) => c.type === "abort")).toBe(false);
  });
});

describe("settled text frames render as PROSE, not as data blobs", () => {
  /**
   * Found by driving a browser, not by any gate. A turn with
   * `mode: {query_mode: "final_text"}` streams its answer as SETTLED `headline`
   * frames rather than `headline_delta` partials. With only the deltas mapped to
   * a text channel, the whole answer — prose, a markdown table, the numbers —
   * fell through to the data path and rendered as JSON in a `<pre>`. Present and
   * unreadable, which is worse than absent because it looks like it works.
   */
  it("routes a settled headline to text when no delta preceded it", () => {
    const { chunks } = adaptFrames([
      { event: "headline", data: { headline: "**AOV by Region**\n\n| Central | 426.59 |" } },
    ]);
    expect(textFor(chunks)).toContain("AOV by Region");
    // CA-1: the settled value ALSO rides as a data part (the projection's
    // authoritative copy) — the prose requirement is that the TEXT is text.
    expect(chunks.some((c) => c.type === "data-headline")).toBe(true);
  });

  it("does not double the text when a settled frame follows its own deltas", () => {
    // The common case: partials stream, then the settled frame repeats the whole
    // thing. Replace-semantics must extend, not re-emit.
    const { chunks } = adaptFrames([
      { event: "headline_delta", data: { headline: "Total" } },
      { event: "headline_delta", data: { headline: "Total orders" } },
      { event: "headline", data: { headline: "Total orders: 9,994" } },
    ]);
    expect(textFor(chunks)).toBe("Total orders: 9,994");
  });

  it("routes settled narrative and answer to the narrative channel", () => {
    for (const [event, field] of [["narrative", "narrative"], ["answer", "answer"]] as const) {
      const { chunks } = adaptFrames([{ event, data: { [field]: "the answer" } }]);
      expect(textFor(chunks)).toBe("the answer");
    }
  });

  it("still sends non-text frames to data parts", () => {
    // The fix must not turn every frame into text.
    const { chunks } = adaptFrames([{ event: "sql", data: { sql: "SELECT 1" } }]);
    expect(chunks.some((c) => c.type === "data-sql")).toBe(true);
    expect(textFor(chunks)).toBe("");
  });
});

describe("empty channels do not become empty text parts", () => {
  it("opens no block for a frame whose text field is empty", () => {
    const { chunks } = adaptFrames([{ event: "headline", data: { headline: "" } }]);
    expect(chunks.filter((c) => c.type === "text-start")).toHaveLength(0);
  });

  it("opens no block for a frame missing its text field entirely", () => {
    const { chunks } = adaptFrames([{ event: "narrative", data: {} }]);
    expect(chunks.filter((c) => c.type === "text-start")).toHaveLength(0);
  });

  it("still opens once real text arrives after an empty frame", () => {
    const { chunks } = adaptFrames([
      { event: "headline_delta", data: { headline: "" } },
      { event: "headline_delta", data: { headline: "Now there is text" } },
    ]);
    expect(chunks.filter((c) => c.type === "text-start")).toHaveLength(1);
    expect(textFor(chunks)).toBe("Now there is text");
  });

  it("leaves a message with no text at all well-formed", () => {
    const k = kinds(adaptFrames([
      { event: "headline", data: { headline: "" } },
      { event: "done", data: {} },
    ]).chunks);
    expect(k).toEqual(["start", "finish"]);
  });
});
