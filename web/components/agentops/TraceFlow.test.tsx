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
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { TraceFlow, eventForNode } from "@/components/agentops/TraceFlow";
import { doorOf, faceOf, guardVerdict, originOf } from "@/components/agentops/RunNodes";
import type { SessionEvent, TimelineNode, TraceFlowEdge } from "@/lib/api";

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

/** Queries scoped to the CANVAS. VA-4e added a rail that indexes the same nodes by name,
 *  so an unscoped `getByText("supervisor")` now matches the card AND its rail row — and
 *  a bare `getAllByText` would pass just as happily if the card had vanished and only
 *  the rail were left. Scoping keeps each assertion about the surface it names. */
const canvas = () => within(screen.getByTestId("canvas"));
const rail = () => within(screen.getByTestId("timeline-rail"));

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
      expect(canvas().getByText(name)).toBeInTheDocument();
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
    expect(canvas().getByText("a")).toBeInTheDocument();
    expect(screen.queryByText(/recorded no nodes to draw/i)).not.toBeInTheDocument();
  });
});

describe("node details — the row a card was built from", () => {
  const ev = (over: Partial<SessionEvent> = {}): SessionEvent => ({
    seq: 0, at: "2026-08-24T10:00:00Z", trace_id: "t1", kind: "tool_call", name: "search",
    span_id: "a", parent_span_id: null, ok: true, duration_ms: 12, error_class: null,
    investigation_id: null, session_id: null, user_id: null, agent_id: null, conn_id: null,
    provider: null, model: null, prompt_tokens: null, completion_tokens: null,
    total_tokens: null, row_count: null, retries: null, job_id: null,
    role: null, fallback: null, payload: null,
    ...over,
  } as SessionEvent);

  it("matches a node to its row by span before sequence", () => {
    // A frame without a span has only its seq to be found by, so seq has to work — but
    // preferring it would pair a node with whatever row shares its number.
    const n = node("a", { span_id: "span-a", seq: 7 });
    const bySeq = ev({ span_id: "other", seq: 7, kind: "wrong-row" });
    const bySpan = ev({ span_id: "span-a", seq: 99, kind: "right-row" });

    expect(eventForNode(n, [bySeq, bySpan])?.kind).toBe("right-row");
    expect(eventForNode(node("b", { span_id: null, seq: 7 }), [bySeq])?.kind).toBe("wrong-row");
    expect(eventForNode(node("c", { span_id: "nope", seq: 42 }), [bySeq])).toBeNull();
  });

  it("shows the payload only once a reader asks for it", () => {
    render(
      <TraceFlow
        timeline={timeline([node("a", { span_id: "a" })])}
        edges={[]}
        events={[ev({ span_id: "a", payload: { question: "why did revenue drop" } })]}
      />,
    );

    // Collapsed: a canvas of open panels is not a canvas.
    expect(screen.queryByText(/why did revenue drop/)).toBeNull();

    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText(/why did revenue drop/)).toBeInTheDocument();
  });

  it("opens one node at a time", () => {
    render(
      <TraceFlow
        timeline={timeline([node("a", { span_id: "a" }), node("b", { span_id: "b" })])}
        edges={[]}
        events={[ev({ span_id: "a", payload: { pick: "first" } }),
                 ev({ span_id: "b", payload: { pick: "second" } })]}
      />,
    );

    const toggles = screen.getAllByText("Details");
    fireEvent.click(toggles[0]);
    expect(screen.getByText(/first/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Details")[0]);
    expect(screen.getByText(/second/)).toBeInTheDocument();
    expect(screen.queryByText(/"pick": "first"/)).toBeNull();
  });

  it("says when there is no row behind a node, rather than showing an empty panel", () => {
    render(<TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]} events={[]} />);

    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText(/No stored row matched this node/)).toBeInTheDocument();
  });

  it("names capture being OFF, because that is not the same as having nothing to say", () => {
    render(
      <TraceFlow
        timeline={timeline([node("a", { span_id: "a" })])}
        edges={[]}
        events={[ev({ span_id: "a", content_captured: false })]}
      />,
    );

    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText(/prompt_capture was off/)).toBeInTheDocument();
  });
});

/**
 * VA-4e — the typed faces.
 *
 * These are pure classifications over rows we already store, so they are asserted
 * directly rather than through the canvas: a face that resolves wrongly renders a
 * plausible card, and a rendering test would pass on the wrong picture.
 */
describe("node faces", () => {
  const n = (over: Partial<TimelineNode>) => node("x", over);

  it("recognises a guardrail before the timeline's catch-all bucket does", () => {
    // The timeline files a guardrail under `kind: "event"` because it carries no span.
    // Consulting `kind` first would draw the run's PII checks as anonymous dots.
    expect(faceOf(n({ event_kind: "guardrail", kind: "event" }))).toBe("guardrail");
  });

  it("gives the request and the response their own faces", () => {
    expect(faceOf(n({ event_kind: "user_request", kind: "frame" }))).toBe("trigger");
    expect(faceOf(n({ event_kind: "final_response", kind: "frame" }))).toBe("response");
  });

  it("prefers a delegation over the model it happened to run", () => {
    // A delegated hop IS a model call; drawn as one, the hand-off disappears.
    const delegated = n({
      kind: "model", event_kind: "llm_call",
      delegation: { path: "a/b", depth: 1, agent_id: "ag", agent_name: "researcher" },
    });
    expect(faceOf(delegated)).toBe("delegation");
  });

  it("reads a guardrail's verdict off the payload the guard wrote", () => {
    expect(guardVerdict(ev2({ payload: { blocked: true, detail: "refuse", found: 3 } })))
      .toEqual({ blocked: true, action: "refuse", found: 3 });
    // A row with no payload is "allowed, nothing found" — not a crash and not a block.
    expect(guardVerdict(null)).toEqual({ blocked: false, action: "", found: 0 });
  });
});

describe("where a run came from", () => {
  it("names the door from the session id's provider prefix", () => {
    expect(doorOf("slack:C0BTN5BDUQ1:1788011380.135369")?.service).toBe("Slack");
    // An unrecognised prefix is the web app — a real answer, not a shrug.
    expect(doorOf("sess-1291")?.service).toBe("Web");
    // NO session id is a different fact from "the web", and stays distinguishable.
    expect(doorOf(null)).toBeNull();
  });

  it("reports a run started inside the platform as exactly that", () => {
    // Measured across 14 live runs: only /ask and /chat write a `user_request`. A canvas
    // exploration opens on a guardrail, a monitor on a tool call. Claiming a trigger for
    // those would put a head node on the canvas that nothing recorded.
    const origin = originOf([
      ev2({ kind: "guardrail", charter_id: "scout", conn_id: "workspace" }),
    ]);
    expect(origin.requested).toBe(false);
    expect(origin.service).toBeNull();
    expect(origin.charter).toBe("scout");
    expect(origin.connId).toBe("workspace");
  });

  it("finds the origin fields on whichever row first carries them", () => {
    // The head row of a real run carries the session but no charter; the charter arrives
    // rows later. Reading only `events[0]` returns null for half of them.
    const origin = originOf([
      ev2({ kind: "user_request", session_id: "slack:C1:17" }),
      ev2({ kind: "llm_call", charter_id: "analyst", job_id: "b64b31b9" }),
    ]);
    expect(origin).toMatchObject({
      service: "Slack", charter: "analyst", jobId: "b64b31b9", requested: true,
    });
  });
});

describe("the timeline rail", () => {
  const three = [node("intake"), node("plan"), node("answer")];

  it("indexes every drawn node, so a canvas wider than the pane stays navigable", () => {
    render(<TraceFlow timeline={timeline(three)} edges={[]} />);
    for (const name of ["intake", "plan", "answer"]) {
      expect(rail().getByText(name)).toBeInTheDocument();
    }
  });

  it("opens a node's detail from its rail row", () => {
    render(
      <TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]}
                 events={[ev2({ span_id: "a", payload: { pick: "from-the-rail" } })]} />,
    );
    expect(screen.queryByText(/from-the-rail/)).toBeNull();

    fireEvent.click(rail().getByText("a"));
    expect(screen.getByText(/from-the-rail/)).toBeInTheDocument();
  });

  it("states the run's origin rather than drawing a trigger nothing recorded", () => {
    render(
      <TraceFlow timeline={timeline(three)} edges={[]}
                 events={[ev2({ kind: "tool_call", charter_id: "worker" })]} />,
    );
    expect(rail().getByText(/inside the platform/)).toBeInTheDocument();
    expect(rail().getByText("worker")).toBeInTheDocument();
  });
});

/** A session-event fixture for the blocks above, which sit outside the closure that
 *  owns the original one. */
function ev2(over: Partial<SessionEvent> = {}): SessionEvent {
  return {
    seq: 0, at: "2026-08-24T10:00:00Z", trace_id: "t1", kind: "tool_call", name: "search",
    span_id: null, parent_span_id: null, ok: true, duration_ms: 12, error_class: null,
    investigation_id: null, session_id: null, user_id: null, agent_id: null, conn_id: null,
    provider: null, model: null, prompt_tokens: null, completion_tokens: null,
    total_tokens: null, row_count: null, retries: null, job_id: null, charter_id: null,
    role: null, fallback: null, payload: null,
    ...over,
  } as SessionEvent;
}
