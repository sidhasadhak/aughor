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
});
