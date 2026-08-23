// @vitest-environment jsdom
/**
 * VA-5's node view, rendered.
 *
 * `lib/traceFlow.test.ts` covers `buildForest`/`layoutForest` thoroughly, and every one
 * of those tests passed while the canvas drew ZERO edges — because a pure function
 * returning the right forest says nothing about whether the component hands that forest
 * to the renderer. This file is the other half: what a reader would actually see.
 *
 * ReactFlow measures its container before it will draw an edge, and jsdom reports every
 * element as 0×0 — measured here: with the real renderer it emits the `react-flow__edges`
 * container and ZERO `.react-flow__edge` elements, no matter how many edges it is given.
 * So an assertion on rendered edges cannot fail, and the first draft of this file proved
 * it: suppressing every edge in the component left all 260 tests green, which is exactly
 * the defect this harness exists to catch.
 *
 * The renderer is therefore stubbed and the assertion moved to the HANDOFF — the nodes
 * and edges the component computes and passes down. That is where the bug lived: the
 * forest was right and the canvas got nothing. Geometry stays a browser question.
 */
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { TraceFlow } from "@/components/agentops/TraceFlow";
import type { TimelineNode, TraceFlowEdge } from "@/lib/api";

/** What the component handed the renderer on the most recent render. */
const handoff: { nodes: RFLike[]; edges: RFLike[] }[] = [];
type RFLike = Record<string, unknown>;

// Partial: only the canvas is replaced. `Handle`, `Position` and `MarkerType` stay real,
// so the node cards under test are the ones that ship.
vi.mock("@xyflow/react", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  // The real provider, because the real `Handle` inside each card demands one. Stubbing
  // Handle instead would mean the cards under test are not the cards that ship.
  const Provider = actual.ReactFlowProvider as React.ComponentType<{
    children?: React.ReactNode;
  }>;
  const Stub = ({ nodes, edges, nodeTypes }: {
    nodes: RFLike[]; edges: RFLike[]; nodeTypes: Record<string, React.ComponentType<RFLike>>;
  }) => {
    handoff.push({ nodes, edges });
    const Card = nodeTypes?.traceNode;
    return (
      <Provider>
        <div data-testid="canvas">
          {Card ? nodes.map(n => <Card key={String(n.id)} {...n} />) : null}
        </div>
      </Provider>
    );
  };
  return { ...actual, ReactFlow: Stub };
});

const drawn = () => handoff[handoff.length - 1] ?? { nodes: [], edges: [] };

const node = (id: string, over: Partial<TimelineNode> = {}): TimelineNode => ({
  id, seq: 0, span_id: id, parent_span_id: null, name: id, event_kind: "tool_call",
  kind: "tool", at: null, ended_at: null, offset_ms: 0, duration_ms: 1, ok: true,
  error_class: null, row_count: null, model: null, provider: null, role: null,
  fallback: null, delegation: null,
  usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null },
  ...over,
} as TimelineNode);

const edge = (from: string, to: string, kind: "child" | "next" = "child"): TraceFlowEdge =>
  ({ from, to, latency_ms: null, kind });

const timeline = (nodes: TimelineNode[]) => ({ nodes } as never);

beforeAll(() => {
  // ReactFlow refuses to render until it has measured; jsdom implements neither of
  // these. Stubbed rather than mocked away, so the component under test is the real one.
  class NoopObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", NoopObserver);
  vi.stubGlobal("IntersectionObserver", NoopObserver);
  if (!("DOMMatrixReadOnly" in globalThis)) {
    vi.stubGlobal("DOMMatrixReadOnly", class { m22 = 1 });
  }
  Object.defineProperty(HTMLElement.prototype, "offsetHeight",
    { configurable: true, value: 400 });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth",
    { configurable: true, value: 800 });
});

beforeEach(() => {
  handoff.length = 0;
});

describe("TraceFlow", () => {
  it("says so when a run recorded nothing to draw", () => {
    render(<TraceFlow timeline={timeline([])} edges={[]} />);
    expect(screen.getByText(/recorded no nodes to draw/i)).toBeInTheDocument();
  });

  it("draws a card for every node in the run", () => {
    render(
      <TraceFlow
        timeline={timeline([node("supervisor"), node("researcher"), node("writer")])}
        edges={[edge("supervisor", "researcher"), edge("supervisor", "writer")]}
      />,
    );
    for (const name of ["supervisor", "researcher", "writer"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("tells a flat run it is flat instead of presenting a chain as a graph", () => {
    render(
      <TraceFlow
        timeline={timeline([node("one"), node("two")])}
        edges={[edge("one", "two", "next")]}
      />,
    );
    expect(screen.getByText(/single sequence/i)).toBeInTheDocument();
  });

  it("drops the flat-run notice once something nests", () => {
    render(
      <TraceFlow
        timeline={timeline([node("sup"), node("hop")])}
        edges={[edge("sup", "hop")]}
      />,
    );
    expect(screen.queryByText(/single sequence/i)).not.toBeInTheDocument();
  });

  it("hands the canvas every edge it was given", () => {
    // The defect this whole harness was built for: the forest was correct and the
    // canvas received nothing. Suppressing the edge list must fail a test.
    render(
      <TraceFlow
        timeline={timeline([node("sup"), node("a"), node("b")])}
        edges={[edge("sup", "a"), edge("sup", "b"), edge("a", "b", "next")]}
      />,
    );
    expect(drawn().edges).toHaveLength(3);
    expect(drawn().edges.map(e => `${e.source}->${e.target}`)).toEqual(
      ["sup->a", "sup->b", "a->b"]);
  });

  it("puts a latency only on the edges where waiting is what happened", () => {
    // A child runs INSIDE its parent, so a number on a `child` edge would be a duration
    // posing as a wait. The rule is in the component; nothing asserted it.
    render(
      <TraceFlow
        timeline={timeline([node("sup"), node("kid"), node("after")])}
        edges={[
          { from: "sup", to: "kid", latency_ms: 900, kind: "child" } as TraceFlowEdge,
          { from: "kid", to: "after", latency_ms: 250, kind: "next" } as TraceFlowEdge,
        ]}
      />,
    );
    const [childEdge, nextEdge] = drawn().edges;
    expect(childEdge.label).toBeUndefined();
    expect(nextEdge.label).toBeDefined();
  });

  it("drops an edge pointing at a node that was never drawn", () => {
    // An edge to a missing node is a line into empty space.
    render(
      <TraceFlow
        timeline={timeline([node("a")])}
        edges={[edge("a", "ghost")]}
      />,
    );
    expect(drawn().edges).toHaveLength(0);
    expect(drawn().nodes).toHaveLength(1);
  });

  it("still draws the nodes when a cycle would otherwise eat the run", () => {
    // The forest builder survives cycles; this is the half that was never checked —
    // that surviving means DRAWING them, not silently returning an empty canvas.
    render(
      <TraceFlow
        timeline={timeline([node("a"), node("b")])}
        edges={[edge("a", "b"), edge("b", "a")]}
      />,
    );
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.queryByText(/recorded no nodes to draw/i)).not.toBeInTheDocument();
  });
});
