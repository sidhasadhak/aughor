/**
 * VA-5 — the node view's forest.
 *
 * Built from the EDGES the backend sends rather than by re-reading `parent_span_id`, so
 * the picture and the contract cannot drift. These guard the two shapes that would break
 * a reader rather than merely look wrong: a node drawn twice, and a cycle that recurses
 * until the panel dies.
 */
import { describe, expect, it } from "vitest";

import {
  bandAsNode, buildForest, foldRepeats, layoutForest,
} from "@/components/agentops/TraceFlow";
import type { TimelineNode, TraceFlowEdge } from "@/lib/api";

const node = (id: string, over: Partial<TimelineNode> = {}): TimelineNode => ({
  id, seq: 0, span_id: id, parent_span_id: null, name: id, event_kind: "tool_call",
  kind: "tool", at: null, ended_at: null, offset_ms: 0, duration_ms: 1, ok: true,
  error_class: null, row_count: null, model: null, provider: null, role: null,
  fallback: null, delegation: null,
  usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null },
  ...over,
} as TimelineNode);

const child = (from: string, to: string): TraceFlowEdge =>
  ({ from, to, latency_ms: null, kind: "child" });

describe("buildForest", () => {
  it("nests a child under its parent and keeps it out of the roots", () => {
    const forest = buildForest([node("sup"), node("hop")], [child("sup", "hop")]);

    expect(forest.map(n => n.id)).toEqual(["sup"]);
    expect(forest[0].children.map(n => n.id)).toEqual(["hop"]);
  });

  it("keeps root order stable", () => {
    const forest = buildForest([node("a"), node("b"), node("c")], []);
    expect(forest.map(n => n.id)).toEqual(["a", "b", "c"]);
  });

  it("hangs two hops off one supervisor", () => {
    const forest = buildForest(
      [node("sup"), node("x"), node("y")],
      [child("sup", "x"), child("sup", "y")],
    );
    expect(forest[0].children.map(n => n.id)).toEqual(["x", "y"]);
  });

  it("never places a node twice, even if two parents claim it", () => {
    // A node rendered under two parents is a node the reader counts twice.
    const forest = buildForest(
      [node("p1"), node("p2"), node("kid")],
      [child("p1", "kid"), child("p2", "kid")],
    );
    const placed = forest.flatMap(function walk(n): string[] {
      return [n.id, ...n.children.flatMap(walk)];
    });
    expect(placed.filter(id => id === "kid")).toHaveLength(1);
  });

  it("survives a cycle instead of recursing until the panel dies", () => {
    const forest = buildForest(
      [node("a"), node("b")],
      [child("a", "b"), child("b", "a")],
    );
    // Whatever it draws, it must terminate and must not lose both nodes.
    expect(forest.length).toBeGreaterThan(0);
  });

  it("ignores a self-edge", () => {
    const forest = buildForest([node("x")], [child("x", "x")]);
    expect(forest.map(n => n.id)).toEqual(["x"]);
    expect(forest[0].children).toEqual([]);
  });

  it("ignores an edge naming a node that is not in the trace", () => {
    const forest = buildForest([node("a")], [child("ghost", "a"), child("a", "ghost")]);
    expect(forest.map(n => n.id)).toEqual(["a"]);
    expect(forest[0].children).toEqual([]);
  });

  it("ignores sequence edges — they are the flow, not the nesting", () => {
    const forest = buildForest(
      [node("a"), node("b")],
      [{ from: "a", to: "b", latency_ms: 12, kind: "next" }],
    );
    expect(forest.map(n => n.id)).toEqual(["a", "b"]);
  });
});

/**
 * The canvas layout.
 *
 * Deterministic on purpose: a run has an inherent reading order, so the same trace
 * opened twice must look identical. A force-directed graph cannot promise that, which
 * is why positions are computed rather than settled.
 */
describe("layoutForest", () => {
  const forest = (nodes: TimelineNode[], edges: TraceFlowEdge[]) =>
    layoutForest(buildForest(nodes, edges));

  it("puts roots on one horizontal spine in order", () => {
    const pos = forest([node("a"), node("b"), node("c")], []);
    expect(pos.get("a")).toEqual({ col: 0, row: 0 });
    expect(pos.get("b")).toEqual({ col: 1, row: 0 });
    expect(pos.get("c")).toEqual({ col: 2, row: 0 });
  });

  it("hangs children one column right, stacked", () => {
    const pos = forest(
      [node("sup"), node("x"), node("y")],
      [child("sup", "x"), child("sup", "y")],
    );
    expect(pos.get("sup")).toEqual({ col: 0, row: 0 });
    expect(pos.get("x")).toEqual({ col: 1, row: 1 });
    expect(pos.get("y")).toEqual({ col: 1, row: 2 });
  });

  it("starts the next root clear of the whole subtree", () => {
    // The collision this guards: a root placed at col+1 would land on top of the
    // previous root's children.
    const pos = forest(
      [node("sup"), node("kid"), node("after")],
      [child("sup", "kid")],
    );
    expect(pos.get("kid")!.col).toBe(1);
    expect(pos.get("after")!.col).toBeGreaterThan(1);
  });

  it("gives a grandchild its own column and its own row", () => {
    const pos = forest(
      [node("a"), node("b"), node("c")],
      [child("a", "b"), child("b", "c")],
    );
    expect(pos.get("b")).toEqual({ col: 1, row: 1 });
    expect(pos.get("c")).toEqual({ col: 2, row: 2 });
  });

  it("never places two nodes on the same spot", () => {
    const pos = forest(
      [node("r1"), node("k1"), node("k2"), node("r2"), node("k3")],
      [child("r1", "k1"), child("r1", "k2"), child("r2", "k3")],
    );
    const seen = [...pos.values()].map(p => `${p.col},${p.row}`);
    expect(new Set(seen).size).toBe(seen.length);
  });

  it("is stable — the same run laid out twice is identical", () => {
    const ns = [node("a"), node("b")];
    const es = [child("a", "b")];
    expect([...forest(ns, es).entries()]).toEqual([...forest(ns, es).entries()]);
  });
});

/* ── stacking a run of like nodes ───────────────────────────────────────────────
 *
 * A stack means N of the SAME thing. Two model calls in a row are one stack of two; two
 * model calls with a tool call between them are two separate cards, however alike they
 * look — they are not one after the other, and similarity alone is not a reason to draw
 * them as one.
 *
 * An earlier draft folded the repeating CYCLE (`llm · llm · sql · pii` ×48 as one card).
 * It compressed harder — 239 nodes to 12 cards against 144 this way — and it was wrong:
 * a card standing for four kinds of work is a summary wearing a stack's clothes, and a
 * reader cannot tell from its face what expanding it will show.
 */

const step = (id: string, kind: string, name: string, over: Partial<TimelineNode> = {}) =>
  node(id, { event_kind: kind, name, ...over });

const roots = (nodes: TimelineNode[]) => buildForest(nodes, []);

/** The shape of the rule, in the user's own words. */
const askLlmLlmAsk = () => [
  step("ask1", "user_request", "ask"),
  step("m1", "llm_call", "gemini"),
  step("m2", "llm_call", "gemini"),
  step("ask2", "user_request", "ask"),
];

describe("foldRepeats", () => {
  it("stacks the two adjacent nodes and leaves the two separated ones alone", () => {
    // ask · llm · llm · ask → the llms stack; the asks do not, because they are not one
    // after the other. Similarity is not adjacency.
    const items = foldRepeats(roots(askLlmLlmAsk()));
    expect(items.map(i => i.kind)).toEqual(["node", "band", "node"]);
    const band = items[1];
    expect(band.kind === "band" && band.members.map(m => m.id)).toEqual(["m1", "m2"]);
  });

  it("never stacks like nodes that something else came between", () => {
    const items = foldRepeats(roots([
      step("m1", "llm_call", "gemini"),
      step("t1", "tool_call", "sql.execute"),
      step("m2", "llm_call", "gemini"),
    ]));
    expect(items.map(i => i.kind)).toEqual(["node", "node", "node"]);
  });

  it("stacks on the NAME as well as the kind — two different models are two cards", () => {
    const items = foldRepeats(roots([
      step("a", "llm_call", "gemini"),
      step("b", "llm_call", "claude"),
    ]));
    expect(items.map(i => i.kind)).toEqual(["node", "node"]);
  });

  it("stacks a long run of one thing into one card", () => {
    const items = foldRepeats(roots(
      Array.from({ length: 12 }, (_, i) => step(`m${i}`, "llm_call", "gemini"))));
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "band", reps: 12 });
  });

  it("leaves a lone node as a lone node", () => {
    const items = foldRepeats(roots([step("only", "llm_call", "gemini")]));
    expect(items.map(i => i.kind)).toEqual(["node"]);
  });

  it("preserves the run's order exactly, stacked or not", () => {
    const seq = [...askLlmLlmAsk(), step("t", "tool_call", "sql.execute"),
                 step("m3", "llm_call", "gemini"), step("m4", "llm_call", "gemini")];
    const flat = foldRepeats(roots(seq))
      .flatMap(i => (i.kind === "band" ? i.members.map(m => m.id) : [i.node.id]));
    expect(flat).toEqual(seq.map(n => n.id));
  });
});

describe("a stack never hides a failure", () => {
  it("draws a failed node as itself and breaks the run around it", () => {
    // The one thing a reader is looking for must never be one click further away than
    // everything else.
    const seq = [step("m1", "llm_call", "gemini"), step("m2", "llm_call", "gemini"),
                 step("boom", "llm_call", "gemini", { ok: false }),
                 step("m3", "llm_call", "gemini"), step("m4", "llm_call", "gemini")];
    const items = foldRepeats(roots(seq));
    expect(items.map(i => i.kind)).toEqual(["band", "node", "band"]);
    expect(items[1].kind === "node" && items[1].node.id).toBe("boom");
  });

  it("treats an error_class as a failure even when ok is true", () => {
    const seq = [step("g1", "guardrail", "pii"),
                 step("g2", "guardrail", "pii", { error_class: "Refused" }),
                 step("g3", "guardrail", "pii")];
    expect(foldRepeats(roots(seq)).map(i => i.kind)).toEqual(["node", "node", "node"]);
  });
});

describe("bandAsNode", () => {
  it("sums what the whole stack took, so a slow run of calls still reads as slow", () => {
    const band = foldRepeats(roots(
      Array.from({ length: 10 }, (_, i) => step(`m${i}`, "llm_call", "gemini"))))[0];
    if (band.kind !== "band") throw new Error("expected a stack");
    expect(bandAsNode(band).duration_ms).toBe(10);
  });

  it("carries an id of its own so the layout and the edge filter need no changes", () => {
    const band = foldRepeats(roots(
      Array.from({ length: 4 }, (_, i) => step(`m${i}`, "llm_call", "gemini"))))[0];
    if (band.kind !== "band") throw new Error("expected a stack");
    expect(bandAsNode(band).id).toBe(band.id);
    expect(bandAsNode(band).id).not.toBe(band.members[0].id);
  });
});
