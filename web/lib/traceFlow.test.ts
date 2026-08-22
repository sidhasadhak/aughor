/**
 * VA-5 — the node view's forest.
 *
 * Built from the EDGES the backend sends rather than by re-reading `parent_span_id`, so
 * the picture and the contract cannot drift. These guard the two shapes that would break
 * a reader rather than merely look wrong: a node drawn twice, and a cycle that recurses
 * until the panel dies.
 */
import { describe, expect, it } from "vitest";

import { buildForest, layoutForest } from "@/components/agentops/TraceFlow";
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
