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

/* ── folding a repeated stretch ─────────────────────────────────────────────────
 *
 * Measured over the four longest traces on the live instance (239, 118, 104, 71 root
 * nodes): a long run is a SHORT CYCLE repeated, not many different things. The 239-node
 * one is `llm · llm · sql.execute · pii`, forty-eight times.
 *
 * That is why these test a cycle and not a stack of identical nodes. Folding consecutive
 * IDENTICAL nodes — the obvious reading — takes 239 to 144, because the kinds interleave
 * and no one kind ever runs more than three deep. Folding the cycle takes it to 12.
 */

/** One step of the measured cycle. */
const step = (id: string, kind: string, name: string, over: Partial<TimelineNode> = {}) =>
  node(id, { event_kind: kind, name, ...over });

/** `reps` turns of `llm · llm · sql · pii`, the shape every long trace measured has. */
const cycle = (reps: number): TimelineNode[] =>
  Array.from({ length: reps }, (_, r) => [
    step(`m${r}a`, "llm_call", "gemini-3.1-flash-lite"),
    step(`m${r}b`, "llm_call", "gemini-3.1-flash-lite"),
    step(`t${r}`, "tool_call", "sql.execute"),
    step(`g${r}`, "guardrail", "pii"),
  ]).flat();

const roots = (nodes: TimelineNode[]) => buildForest(nodes, []);

describe("foldRepeats", () => {
  it("folds the measured cycle into one band", () => {
    const items = foldRepeats(roots(cycle(12)));
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "band", period: 4, reps: 12 });
  });

  it("keeps a short run exactly as it is", () => {
    // The median trace is 10 nodes. Folding must not touch what already fits.
    const items = foldRepeats(roots([step("a", "llm_call", "m"), step("b", "tool_call", "t")]));
    expect(items.map(i => i.kind)).toEqual(["node", "node"]);
  });

  it("prefers the SMALLEST period — three of `A B`, not one of `A B A B A B`", () => {
    // A reader counting iterations means the small one.
    const ab = Array.from({ length: 3 }, (_, r) => [
      step(`a${r}`, "llm_call", "m"), step(`b${r}`, "tool_call", "t"),
    ]).flat();
    expect(foldRepeats(roots(ab))[0]).toMatchObject({ period: 2, reps: 3 });
  });

  it("never folds a stretch that is not contiguous", () => {
    // A band occupies ONE position in a chain that means order. Gathering scattered
    // nodes of the same kind would draw a sequence that never ran.
    const seq = [...cycle(3), step("odd", "tool_call", "export.pptx"), ...cycle(3)];
    const items = foldRepeats(roots(seq));
    expect(items.map(i => i.kind)).toEqual(["band", "node", "band"]);
    expect(items.flatMap(i => (i.kind === "band" ? i.members.map(m => m.id) : [i.node.id])))
      .toEqual(seq.map(n => n.id));
  });

  it("preserves the run's order exactly, band or not", () => {
    const seq = [step("head", "llm_call", "m"), ...cycle(5), step("tail", "tool_call", "t")];
    const flat = foldRepeats(roots(seq))
      .flatMap(i => (i.kind === "band" ? i.members.map(m => m.id) : [i.node.id]));
    expect(flat).toEqual(seq.map(n => n.id));
  });

  it("refuses to fold two nodes into a band nobody would click", () => {
    const items = foldRepeats(roots([step("a", "llm_call", "m"), step("a2", "llm_call", "m")]));
    expect(items.map(i => i.kind)).toEqual(["node", "node"]);
  });

  it("folds a plain repeated node when there are enough of them", () => {
    // The Blender case — a stack of one repeated step — falls out of the same algorithm
    // at period 1 rather than needing a rule of its own.
    const items = foldRepeats(roots(
      Array.from({ length: 6 }, (_, i) => step(`m${i}`, "llm_call", "gemini"))));
    expect(items[0]).toMatchObject({ kind: "band", period: 1, reps: 6 });
  });
});

describe("a fold never hides a failure", () => {
  it("draws a failed node as itself and breaks the band around it", () => {
    // The one thing a reader is looking for must never be one click further away than
    // everything else.
    const seq = [...cycle(3), step("boom", "tool_call", "sql.execute", { ok: false }),
                 ...cycle(3)];
    const items = foldRepeats(roots(seq));
    expect(items.map(i => i.kind)).toEqual(["band", "node", "band"]);
    const alone = items[1];
    expect(alone.kind === "node" && alone.node.id).toBe("boom");
  });

  it("treats an error_class as a failure even when ok is true", () => {
    const seq = [...cycle(3), step("warned", "guardrail", "pii", { error_class: "Refused" }),
                 ...cycle(3)];
    const items = foldRepeats(roots(seq));
    expect(items[1].kind === "node" && items[1].node.id).toBe("warned");
  });

  it("never puts a failure inside any band, however the run is shaped", () => {
    const seq = [...cycle(2), step("boom", "llm_call", "gemini-3.1-flash-lite", { ok: false }),
                 ...cycle(2)];
    const inBands = foldRepeats(roots(seq))
      .flatMap(i => (i.kind === "band" ? i.members : []));
    expect(inBands.every(m => m.ok !== false && !m.error_class)).toBe(true);
  });
});

describe("bandAsNode", () => {
  it("sums what the whole stretch took, so a slow loop still reads as slow", () => {
    const items = foldRepeats(roots(cycle(10)));
    const band = items[0];
    if (band.kind !== "band") throw new Error("expected a band");
    // 40 members at 1ms each — the fixture's duration.
    expect(bandAsNode(band).duration_ms).toBe(40);
  });

  it("carries an id of its own so the layout and the edge filter need no changes", () => {
    const items = foldRepeats(roots(cycle(10)));
    const band = items[0];
    if (band.kind !== "band") throw new Error("expected a band");
    expect(bandAsNode(band).id).toBe(band.id);
    expect(bandAsNode(band).id).not.toBe(band.members[0].id);
  });
});
