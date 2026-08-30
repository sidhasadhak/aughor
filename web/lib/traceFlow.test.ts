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
  bandAsNode, buildForest, foldRepeats, layoutForest, layoutGrid,
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
  // `kind` mirrors `event_kind`, because `faceOf` reads `kind` for a model call and
  // `event_kind` for the rest — a fixture that set only one filed every model call under
  // the tool face, and the row heights sized to it.
  node(id, {
    event_kind: kind,
    kind: kind === "llm_call" ? "model" : kind === "tool_call" ? "tool" : kind,
    name, ...over,
  });

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

/* ── a flat run is a block, not a line ──────────────────────────────────────── */

const CELL = { w: 260, h: 138 };
const asItems = (nodes: TimelineNode[]) =>
  roots(nodes).map(node => ({ kind: "node" as const, node }));

describe("layoutGrid", () => {
  it("wraps a long sequence into roughly a square instead of one long row", () => {
    // 68 cards in a row is what no zoom could read. The aspect ratio solves
    // cols·w ≈ rows·h, so the shape comes from the cards rather than a chosen number.
    const items = asItems(Array.from({ length: 68 }, (_, i) => step(`n${i}`, "tool_call", "t")));
    const pos = layoutGrid(items, new Set(), CELL);
    const xs = [...pos.values()].map(p => p.x);
    const ys = [...pos.values()].map(p => p.y);
    const width = Math.max(...xs) + CELL.w;
    const height = Math.max(...ys) + CELL.h;
    expect(width / height).toBeGreaterThan(0.5);
    expect(width / height).toBeLessThan(2);
  });

  it("SNAKES, so every step is to a neighbour and never across the block", () => {
    // Wrapping each row back to the left margin draws one long diagonal per row over
    // every card on the canvas — measured on a 68-card run, and worse than the long line
    // it replaced. Snaking puts the end of a row directly above the start of the next.
    const items = asItems(Array.from({ length: 20 }, (_, i) => step(`n${i}`, "tool_call", "t")));
    const pos = layoutGrid(items, new Set(), CELL);
    const inOrder = items.map(i => pos.get(i.node.id)!);
    for (let i = 1; i < inOrder.length; i++) {
      const prev = inOrder[i - 1];
      const cur = inOrder[i];
      const sameRow = cur.y === prev.y;
      // Along a row: one column across. Between rows: the same column, one row down.
      const step_ = sameRow
        ? Math.abs(cur.x - prev.x) <= CELL.w + 40 && cur.x !== prev.x
        : cur.x === prev.x && cur.y > prev.y;
      expect(step_).toBe(true);
    }
  });

  it("gives a row the height of its TALLEST card, so nothing collides", () => {
    // Rows were spaced 138px while a model call draws 154 — every model card overlapped
    // the row beneath it, which is what made the first block layout unreadable.
    const items = asItems([
      ...Array.from({ length: 7 }, (_, i) => step(`t${i}`, "tool_call", "sql")),
      step("big", "llm_call", "gemini"),
      ...Array.from({ length: 7 }, (_, i) => step(`u${i}`, "tool_call", "sql")),
    ]);
    const pos = layoutGrid(items, new Set(), CELL);
    // The row holding the tall card is the one that has to grow; the all-tool rows stay
    // short, which is the point of sizing a row to its own contents.
    const bigY = pos.get("big")!.y;
    const rows = [...new Set([...pos.values()].map(p => p.y))].sort((a, b) => a - b);
    const next = rows.find(y => y > bigY);
    expect(next).toBeDefined();
    expect(next! - bigY).toBeGreaterThanOrEqual(160);
    // And a short row stays short — a constant tall enough for everything would waste
    // most of the block on whitespace.
    const shortGaps = rows.slice(1).map((y, i) => y - rows[i]).filter(g => g < 160);
    expect(shortGaps.length).toBeGreaterThan(0);
  });

  it("puts a short run on one row and leaves it alone", () => {
    const items = asItems([step("a", "tool_call", "t"), step("b", "llm_call", "m")]);
    const pos = layoutGrid(items, new Set(), CELL);
    expect(new Set([...pos.values()].map(p => p.y)).size).toBe(1);
  });
});

describe("an opened stack grows downward", () => {
  const withStack = () => {
    const nodes = [
      step("head", "tool_call", "start"),
      ...Array.from({ length: 5 }, (_, i) => step(`m${i}`, "llm_call", "gemini")),
      step("tail", "tool_call", "end"),
    ];
    return foldRepeats(roots(nodes));
  };

  it("stacks its members in ONE column, one row-height apart", () => {
    const items = withStack();
    const band = items.find(i => i.kind === "band");
    if (!band || band.kind !== "band") throw new Error("expected a stack");
    const pos = layoutGrid(items, new Set([band.id]), CELL);
    const members = band.members.map(m => pos.get(m.id)!);
    expect(new Set(members.map(p => p.x)).size).toBe(1);
    // Evenly spaced by the card's own height — a constant would collide, which is the
    // defect that made the first block layout unreadable.
    const steps = members.slice(1).map((p, i) => p.y - members[i].y);
    expect(new Set(steps).size).toBe(1);
    expect(steps[0]).toBeGreaterThanOrEqual(160);
  });

  it("does not move the stack itself, or anything before it", () => {
    // The whole point of growing downward: what the reader was looking at stays put.
    // Cards in LATER rows do shift down — the row has to make room somewhere, and down
    // is the only direction that does not reorder the run.
    const items = withStack();
    const band = items.find(i => i.kind === "band");
    if (!band || band.kind !== "band") throw new Error("expected a stack");
    const closed = layoutGrid(items, new Set(), CELL);
    const open = layoutGrid(items, new Set([band.id]), CELL);
    expect(open.get("head")).toEqual(closed.get("head"));
    // The stack's own first card is exactly where the collapsed stack was.
    expect(open.get(band.members[0].id)).toEqual(closed.get(band.id));
  });

  it("gives the row enough height for the tallest stack opened in it", () => {
    const items = withStack();
    const band = items.find(i => i.kind === "band");
    if (!band || band.kind !== "band") throw new Error("expected a stack");
    const open = layoutGrid(items, new Set([band.id]), CELL);
    // Nothing may be drawn on top of the opened column.
    const lastMember = open.get(band.members[band.members.length - 1].id)!;
    const others = [...open.entries()]
      .filter(([id]) => !band.members.some(m => m.id === id))
      .map(([, p]) => p);
    for (const o of others) {
      const overlaps = o.x === lastMember.x && o.y > 0 && o.y <= lastMember.y;
      expect(overlaps).toBe(false);
    }
  });
});
