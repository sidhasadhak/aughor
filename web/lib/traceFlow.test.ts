/**
 * VA-5 — the node view's forest.
 *
 * Built from the EDGES the backend sends rather than by re-reading `parent_span_id`, so
 * the picture and the contract cannot drift. These guard the two shapes that would break
 * a reader rather than merely look wrong: a node drawn twice, and a cycle that recurses
 * until the panel dies.
 */
import { describe, expect, it } from "vitest";

import { buildForest } from "@/components/agentops/TraceFlow";
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
