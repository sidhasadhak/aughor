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
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { TraceFlow, eventForNode } from "@/components/agentops/TraceFlow";
import { doorOf, faceOf, guardVerdict, originOf } from "@/components/agentops/RunNodes";
import { BUILTIN_AGENT_FIELD } from "@/lib/api";
import type { SessionEvent, TimelineNode, TraceFlowEdge } from "@/lib/api";

/** What the component handed the renderer on the most recent render. */
const handoff: { nodes: RFLike[]; edges: RFLike[] }[] = [];
/** Every viewport move the component asked for. */
const fits: string[] = [];
/** Every prop the canvas was handed, not just nodes/edges — the interaction flags live
 *  here and are invisible to a nodes-and-edges assertion. */
const canvasProps: Record<string, unknown>[] = [];
const fakeRf = {
  fitView: () => { fits.push("fit"); },
  setCenter: () => { fits.push("center"); },
  getZoom: () => 1,
};
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
  const Stub = (props: {
    nodes: RFLike[]; edges: RFLike[]; nodeTypes: Record<string, React.ComponentType<RFLike>>;
    onInit?: (rf: unknown) => void;
  }) => {
    const { nodes, edges, nodeTypes, onInit } = props;
    handoff.push({ nodes, edges });
    canvasProps.push(props as unknown as Record<string, unknown>);
    // Hand the component an instance ONCE, so the re-fit it performs is observable.
    // Without this `rf` stays null, the effect returns early, and a test asserting the
    // viewport does not jump would pass with the jump fully intact.
    const inited = React.useRef(false);
    React.useEffect(() => {
      if (inited.current) return;
      inited.current = true;
      onInit?.(fakeRf);
    }, [onInit]);
    // Each node rendered through ITS OWN registered type. Hard-wiring `traceNode` here
    // would have quietly dropped every band card the folding feature draws — a stub that
    // renders less than the canvas does is a test that passes on a blank screen.
    return (
      <Provider>
        <div data-testid="canvas">
          {nodes.map(n => {
            const Card = nodeTypes?.[String(n.type ?? "traceNode")];
            return Card ? <Card key={String(n.id)} {...n} /> : null;
          })}
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
/** The rail is hidden until asked for — it is a companion to the canvas, not a frame
 *  around it. Tests that read it open it first, the way a reader would. */
const showRail = () => fireEvent.click(screen.getByText("Timeline"));
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
  canvasProps.length = 0;
  fits.length = 0;
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
      ev2({ kind: "guardrail", [BUILTIN_AGENT_FIELD]: "explorer", conn_id: "workspace" }),
    ]);
    expect(origin.requested).toBe(false);
    expect(origin.service).toBeNull();
    expect(origin.builtinAgent).toBe("explorer");
    expect(origin.connId).toBe("workspace");
  });

  it("finds the origin fields on whichever row first carries them", () => {
    // The head row of a real run carries the session but names no built-in agent; that
    // arrives rows later. Reading only `events[0]` returns null for half of them.
    const origin = originOf([
      ev2({ kind: "user_request", session_id: "slack:C1:17" }),
      ev2({ kind: "llm_call", [BUILTIN_AGENT_FIELD]: "analyst", job_id: "b64b31b9" }),
    ]);
    expect(origin).toMatchObject({
      service: "Slack", builtinAgent: "analyst", jobId: "b64b31b9", requested: true,
    });
  });
});

describe("the timeline rail", () => {
  const three = [node("intake"), node("plan"), node("answer")];

  it("indexes every drawn node, so a canvas wider than the pane stays navigable", () => {
    render(<TraceFlow timeline={timeline(three)} edges={[]} />);
    showRail();
    for (const name of ["intake", "plan", "answer"]) {
      expect(rail().getByText(name)).toBeInTheDocument();
    }
  });

  it("opens a node's detail from its rail row", () => {
    render(
      <TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]}
                 events={[ev2({ span_id: "a", payload: { pick: "from-the-rail" } })]} />,
    );
    showRail();
    expect(screen.queryByText(/from-the-rail/)).toBeNull();

    fireEvent.click(rail().getByText("a"));
    expect(screen.getByText(/from-the-rail/)).toBeInTheDocument();
  });

  it("states the run's origin rather than drawing a trigger nothing recorded", () => {
    render(
      <TraceFlow timeline={timeline(three)} edges={[]}
                 events={[ev2({ kind: "tool_call", [BUILTIN_AGENT_FIELD]: "watcher" })]} />,
    );
    showRail();
    expect(rail().getByText(/inside the platform/)).toBeInTheDocument();
    expect(rail().getByText("watcher")).toBeInTheDocument();
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
    total_tokens: null, row_count: null, retries: null, job_id: null,
    [BUILTIN_AGENT_FIELD]: null,
    role: null, fallback: null, payload: null,
    ...over,
  } as SessionEvent;
}

/* ── stacking a run of like nodes ───────────────────────────────────────────────
 *
 * `lib/traceFlow.test.ts` proves the rule. These prove the component ACTS on it — the
 * same split this file exists for, and the same defect it was written to catch: a
 * correct pure function whose result never reaches the canvas.
 */
describe("stacked nodes", () => {
  /** A long run of one thing, which is what a stack is for. */
  const sameKind = (n: number, name = "gemini-3.1-flash-lite") =>
    Array.from({ length: n }, (_, i) =>
      node(`m${i}`, { event_kind: "llm_call", name }));

  it("hands the canvas ONE card for a run of like nodes", () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    expect(drawn().nodes).toHaveLength(1);
    expect(drawn().nodes[0].type).toBe("bandNode");
  });

  it("wears the face of the thing it stacks, and says how many", () => {
    // Every node inside is this node; the only new information is how many and how long.
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    expect(canvas().getByText("×30")).toBeInTheDocument();
    expect(canvas().getByText("gemini-3.1-flash-lite")).toBeInTheDocument();
    expect(canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes"))
      .toBeInTheDocument();
  });

  it("draws the ordinary node card, not a shrunken summary of one", () => {
    // The default card is what a reader already knows how to read, and every node in the
    // stack IS that node. An earlier pass replaced it with a condensed two-line summary
    // to save vertical room the layout was not short of; this locks that back.
    const stacked = Array.from({ length: 30 }, (_, i) =>
      node(`m${i}`, { event_kind: "llm_call", name: "gemini-3.1-flash-lite" }));
    render(<TraceFlow timeline={timeline(stacked)} edges={[]} />);
    const card = canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes");
    // The ordinary card in its default state is name · duration · Details. The condensed
    // summary this replaced had no Details affordance at all, so its presence is what
    // separates "the node, stacked" from "a card about the node".
    expect(within(card).getByText("Details")).toBeInTheDocument();
    expect(within(card).getByText("gemini-3.1-flash-lite")).toBeInTheDocument();
    expect(within(card).getByText("×30")).toBeInTheDocument();
  });

  it("shows the stack's TOTAL duration, the one number a single face would get wrong", () => {
    const stacked = Array.from({ length: 30 }, (_, i) =>
      node(`m${i}`, { event_kind: "llm_call", name: "gemini", duration_ms: 100 }));
    render(<TraceFlow timeline={timeline(stacked)} edges={[]} />);
    const band = drawn().nodes.find(n => n.type === "bandNode");
    const bandData = band!.data as { card: { node: TimelineNode } };
    expect(bandData.card.node.duration_ms).toBe(3000);
  });

  it("does NOT stack like nodes that something else came between", () => {
    // The rule, in the user's own words: two model calls with an ask between them are
    // two cards, because they are not one after the other.
    const nodes = [
      ...sameKind(12),
      node("ask", { event_kind: "user_request", name: "ask" }),
      ...sameKind(12).map(n => node(`b${n.id}`, { event_kind: "llm_call", name: "gemini-3.1-flash-lite" })),
    ];
    render(<TraceFlow timeline={timeline(nodes)} edges={[]} />);
    const types = drawn().nodes.map(n => n.type);
    expect(types.filter(t => t === "bandNode")).toHaveLength(2);
    expect(types.filter(t => t === "traceNode")).toHaveLength(1);
  });

  it("leaves a run that already fits completely alone", () => {
    // The median trace measured is ten nodes. Folding what a reader can already see
    // would be a control changing a picture nobody was struggling with.
    render(<TraceFlow timeline={timeline([node("a"), node("b")])} edges={[]} />);
    expect(drawn().nodes.map(n => n.type)).toEqual(["traceNode", "traceNode"]);
  });

  it("expands every node in the stack when the card is clicked", () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    fireEvent.click(canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes"));
    expect(drawn().nodes).toHaveLength(30);
    expect(drawn().nodes.every(n => n.type === "traceNode")).toBe(true);
  });

  it("offers the way back on the first card, and only there", () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    fireEvent.click(canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes"));
    // One chip, not thirty — the clutter this feature exists to remove.
    expect(canvas().getAllByLabelText("Collapse these 30 repeats")).toHaveLength(1);
  });

  it("re-stacks when that chip is used", () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    fireEvent.click(canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes"));
    fireEvent.click(canvas().getByLabelText("Collapse these 30 repeats"));
    expect(drawn().nodes).toHaveLength(1);
    expect(drawn().nodes[0].type).toBe("bandNode");
  });

  it("turns stacking off entirely on request, and shows every node", () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    fireEvent.click(screen.getByText("Grouped"));
    expect(drawn().nodes).toHaveLength(30);
    expect(screen.getByText("Group repeats")).toBeInTheDocument();
  });

  it("keeps the chain joined across a stack", () => {
    // The run's own `next` edges connect real nodes, so the two reaching into a stacked
    // run vanish with its members — leaving the stack floating unless replaced.
    const nodes = [node("head", { event_kind: "tool_call", name: "start" }), ...sameKind(30)];
    const edges = nodes.slice(0, -1).map((n, i) => edge(n.id, nodes[i + 1].id, "next"));
    render(<TraceFlow timeline={timeline(nodes)} edges={edges} />);
    const ids = new Set(drawn().nodes.map(n => String(n.id)));
    expect(ids.size).toBe(2);
    for (const e of drawn().edges) {
      expect(ids.has(String(e.source))).toBe(true);
      expect(ids.has(String(e.target))).toBe(true);
    }
    expect(drawn().edges.some(e => String(e.source) === "head")).toBe(true);
  });

  it("draws a failed node as itself, never inside a stack", () => {
    const nodes = [...sameKind(12),
      node("boom", { event_kind: "llm_call", name: "gemini-3.1-flash-lite", ok: false }),
      ...sameKind(12).map(n => node(`b${n.id}`,
        { event_kind: "llm_call", name: "gemini-3.1-flash-lite" }))];
    render(<TraceFlow timeline={timeline(nodes)} edges={[]} />);
    const cards = drawn().nodes;
    expect(cards.filter(n => n.type === "bandNode")).toHaveLength(2);
    const failed = cards.filter(n => n.type === "traceNode");
    expect(failed.map(n => n.id)).toEqual(["boom"]);
    // Reading order, not x alone: a flat run wraps into a block now, so "after" means
    // further down the rows and then further along them.
    const orderOf = (n: RFLike) => {
      const p = n.position as { x: number; y: number };
      return p.y * 1e6 + p.x;
    };
    const bandOrder = cards.filter(n => n.type === "bandNode").map(orderOf)
      .sort((a, b) => a - b);
    expect(orderOf(failed[0])).toBeGreaterThan(bandOrder[0]);
    expect(orderOf(failed[0])).toBeLessThan(bandOrder[1]);
    const failedData = failed[0].data as { node: TimelineNode };
    expect(failedData.node.ok).toBe(false);
  });
});

/* ── keeping the reader's place ─────────────────────────────────────────────── */

/** The re-fit is deferred a frame (ReactFlow measures after commit), so an assertion
 *  made straight after a click runs BEFORE the fit would have happened and passes with
 *  the jump fully intact — this pair did exactly that until the frames were flushed. */
const settleFrames = async () => {
  for (let i = 0; i < 3; i++) {
    await new Promise(resolve => requestAnimationFrame(() => resolve(null)));
  }
};

describe("the viewport when a stack opens", () => {
  const sameKind = (n: number) =>
    Array.from({ length: n }, (_, i) =>
      node(`m${i}`, { event_kind: "llm_call", name: "gemini-3.1-flash-lite" }));

  it("does NOT re-fit — the card under the cursor stays where it was", async () => {
    // Reported from the browser: expanding a stack jumped the viewport, losing the very
    // node the reader had just clicked. The re-fit was keyed on the DRAWN nodes, which
    // are exactly what expanding changes.
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    await waitFor(() => expect(fits.length).toBeGreaterThan(0));  // the mount fit
    fits.length = 0;

    fireEvent.click(canvas().getByLabelText("Expand 30 stacked gemini-3.1-flash-lite nodes"));
    await waitFor(() => expect(drawn().nodes).toHaveLength(30));
    await settleFrames();
    expect(fits).toEqual([]);
  });

  it("does not re-fit when stacking is switched off either", async () => {
    render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    await waitFor(() => expect(fits.length).toBeGreaterThan(0));
    fits.length = 0;
    fireEvent.click(screen.getByText("Grouped"));
    await waitFor(() => expect(drawn().nodes).toHaveLength(30));
    await settleFrames();
    expect(fits).toEqual([]);
  });

  it("STILL re-fits when the run itself changes", async () => {
    // The control. Without it this pair passes just as well with the re-fit deleted —
    // and a canvas that never fits opens every new run at the previous one's pan.
    const { rerender } = render(<TraceFlow timeline={timeline(sameKind(30))} edges={[]} />);
    await waitFor(() => expect(fits.length).toBeGreaterThan(0));
    fits.length = 0;
    rerender(<TraceFlow timeline={timeline([node("other", { name: "another run" })])} edges={[]} />);
    await waitFor(() => expect(fits).toContain("fit"));
  });
});

/* ── the guardrail filter ───────────────────────────────────────────────────── */
describe("guardrails that allowed", () => {
  const withGuards = () => {
    // Distinct `seq` per node: `eventForNode` matches on span first and SEQUENCE second,
    // so a fixture where every node is seq 0 hands one event to all of them — which is
    // how the blocked-guardrail case first "passed" for the wrong reason.
    const nodes = [
      node("q", { seq: 1, event_kind: "user_request", name: "ask" }),
      node("g1", { seq: 2, event_kind: "guardrail", name: "pii", span_id: "g1" }),
      node("m1", { seq: 3, event_kind: "llm_call", kind: "model", name: "gemini" }),
      node("g2", { seq: 4, event_kind: "guardrail", name: "pii", span_id: "g2" }),
      node("t1", { seq: 5, event_kind: "tool_call", name: "sql.execute" }),
    ];
    const edges = nodes.slice(0, -1).map((n, i) => edge(n.id, nodes[i + 1].id, "next"));
    return { nodes, edges };
  };

  it("hides them by DEFAULT — a third of every canvas, carrying no decision", () => {
    const { nodes, edges } = withGuards();
    render(<TraceFlow timeline={timeline(nodes)} edges={edges} />);
    const ids = drawn().nodes.map(n => String(n.id));
    expect(ids).not.toContain("g1");
    expect(ids).not.toContain("g2");
    expect(ids).toEqual(expect.arrayContaining(["q", "m1", "t1"]));
  });

  it("says how many it took away, and brings them back on request", () => {
    // A control that vanishes once it has done its job leaves the reader unable to ask
    // what it removed.
    const { nodes, edges } = withGuards();
    render(<TraceFlow timeline={timeline(nodes)} edges={edges} />);
    fireEvent.click(screen.getByText("2 guardrails hidden"));
    expect(drawn().nodes.map(n => String(n.id))).toEqual(
      expect.arrayContaining(["q", "g1", "m1", "g2", "t1"]));
    expect(screen.getByText("Guardrails shown")).toBeInTheDocument();
  });

  it("NEVER hides one that blocked", () => {
    // A filter about noise must not swallow an outcome.
    const { nodes, edges } = withGuards();
    render(
      <TraceFlow timeline={timeline(nodes)} edges={edges}
                 events={[ev2({ seq: 2, span_id: "g1", kind: "guardrail",
                                payload: { blocked: true } })]} />,
    );
    const ids = drawn().nodes.map(n => String(n.id));
    expect(ids).toContain("g1");
    expect(ids).not.toContain("g2");
  });

  it("never hides one that FAILED either", () => {
    const { nodes, edges } = withGuards();
    nodes[1] = node("g1", { seq: 2, event_kind: "guardrail", name: "pii", ok: false });
    render(<TraceFlow timeline={timeline(nodes)} edges={edges} />);
    expect(drawn().nodes.map(n => String(n.id))).toContain("g1");
  });

  it("keeps the chain joined across what it removed", () => {
    // The run's own `next` edges ran THROUGH the hidden nodes, so without a bridge the
    // cards either side are left floating with no line into them.
    const { nodes, edges } = withGuards();
    render(<TraceFlow timeline={timeline(nodes)} edges={edges} />);
    const ids = new Set(drawn().nodes.map(n => String(n.id)));
    for (const e of drawn().edges) {
      expect(ids.has(String(e.source))).toBe(true);
      expect(ids.has(String(e.target))).toBe(true);
    }
    // q → m1 → t1: every card after the first has something pointing at it.
    for (const id of ["m1", "t1"]) {
      expect(drawn().edges.some(e => String(e.target) === id)).toBe(true);
    }
  });
});

// ── §3.8 · the canvas does not offer a drag it cannot keep ──────────────────────────

describe("interaction affordances", () => {
  /** The last set of props the canvas was handed. */
  const lastProps = () => canvasProps[canvasProps.length - 1] ?? {};

  it("hands the canvas nodesDraggable={false}", () => {
    render(<TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]} />);
    // ReactFlow DEFAULTS this to true, so the assertion is on the explicit false — an
    // `undefined` here means dragging is on, which is the bug this pins.
    expect(lastProps().nodesDraggable).toBe(false);
  });

  it("does not offer connection handles either", () => {
    render(<TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]} />);
    expect(lastProps().nodesConnectable).toBe(false);
  });

  it("still hands nodes down, so this is not a blank canvas passing vacuously", () => {
    // Guard against the assertions above being satisfied by a canvas that renders
    // nothing: a stub handed no nodes would have `undefined` flags too.
    render(<TraceFlow timeline={timeline([node("a", { span_id: "a" })])} edges={[]} />);
    expect(drawn().nodes.length).toBeGreaterThan(0);
  });
});
