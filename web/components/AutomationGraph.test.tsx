/**
 * VA-4b · the client half — asserted at the HANDOFF, not on rendered edges.
 *
 * ReactFlow measures its container before it will draw an edge, and jsdom reports every
 * element as 0×0 — so an assertion on rendered `.react-flow__edge` elements cannot fail.
 * `TraceFlow.test.tsx` proved that the expensive way: suppressing every edge in the
 * component left all 260 tests green. The whole point of this wave is the distinction
 * between a data edge and a sequence edge, so testing it in a way that cannot fail would
 * be worse than not testing it.
 *
 * The renderer is therefore stubbed and the assertions sit on `toFlow` — the nodes and
 * edges the component computes and passes down.
 */
import { describe, expect, it } from "vitest";

import { positionChanges, toFlow, type AutomationGraphData } from "@/components/AutomationGraph";

const graph = (over: Partial<AutomationGraphData> = {}): AutomationGraphData => ({
  mode: "structure",
  nodes: [
    { id: "trigger", type: "trigger", label: "When", detail: "schedule · 0 9 * * 1" },
    { id: "ask", type: "effect", kind: "brief", label: "ask", detail: "why?" },
    { id: "post", type: "effect", kind: "slack_post", label: "post", detail: "C1" },
  ],
  edges: [
    { from: "trigger", to: "ask", type: "sequence" },
    { from: "ask", to: "post", type: "sequence" },
    { from: "ask", to: "post", type: "data", label: "answer" },
  ],
  ...over,
});

const dataEdges = (g: AutomationGraphData) =>
  toFlow(g).edges.filter(e => (e.data as { edgeType?: string })?.edgeType === "data");
const seqEdges = (g: AutomationGraphData) =>
  toFlow(g).edges.filter(e => (e.data as { edgeType?: string })?.edgeType === "sequence");

describe("AutomationGraph handoff", () => {
  it("passes every server node through, and infers none of its own", () => {
    // The server owns the graph. A client that adds a node is a second reader, and two
    // readers deriving the graph differently is how a picture and its run disagree.
    const { nodes } = toFlow(graph());
    expect(nodes.map(n => n.id)).toEqual(["trigger", "ask", "post"]);
  });

  it("draws a data edge and a sequence edge DIFFERENTLY", () => {
    // The distinction this whole wave exists to make: one carries a value, one only
    // means "runs after".
    const g = graph();
    const [data] = dataEdges(g);
    // trigger->ask, not ask->post: the latter is now correctly dropped because a data
    // edge already covers that pair.
    const seq = seqEdges(g).find(e => e.source === "trigger")!;

    expect(data.style?.strokeDasharray).toBeUndefined();
    expect(seq.style?.strokeDasharray).toBe("3 3");
    expect(data.style?.stroke).not.toEqual(seq.style?.stroke);
  });

  it("labels a data edge with the key it carries, and never labels a sequence edge", () => {
    const g = graph();
    expect(dataEdges(g)[0].label).toBe("answer");
    expect(seqEdges(g).every(e => e.label === undefined)).toBe(true);
  });

  it("gives every edge a distinct id", () => {
    const ids = toFlow(graph()).edges.map(e => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("drops a sequence edge that a data edge already covers", () => {
    // Found by driving the browser: both `ask->post` edges rendered on an IDENTICAL path
    // ("M443,36 C470,36 470,36 497,36"), the dashed one hidden under the solid one. A
    // data edge already implies "runs after" — you cannot consume what has not run — so
    // keeping both draws the same claim twice.
    const g = graph();               // has BOTH a sequence and a data ask->post
    const pairs = toFlow(g).edges.map(e => `${e.source}->${e.target}:${(e.data as { edgeType?: string })?.edgeType}`);
    expect(pairs).toContain("ask->post:data");
    expect(pairs).not.toContain("ask->post:sequence");
    expect(pairs).toContain("trigger->ask:sequence");   // an uncovered one still draws
  });

  it("keeps a sequence edge when no data flows across it", () => {
    const g = graph({ edges: [{ from: "ask", to: "post", type: "sequence" }] });
    expect(toFlow(g).edges).toHaveLength(1);
  });

  it("lays steps out left to right in the order they run", () => {
    // Deterministic, never simulated: the same automation opened twice looks identical.
    const xs = toFlow(graph()).nodes.map(n => n.position.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(new Set(xs).size).toBe(xs.length);
  });

  it("carries a run's status and produced keys onto the node", () => {
    const g = graph({
      mode: "execution",
      nodes: [
        { id: "trigger", type: "trigger", label: "When", detail: "cron" },
        { id: "ask", type: "effect", kind: "brief", label: "ask",
          status: "executed", produced: ["answer"] },
        { id: "post", type: "effect", kind: "slack_post", label: "post",
          status: "skipped", message: "upstream data unavailable" },
      ],
    });
    const byId = Object.fromEntries(toFlow(g).nodes.map(n => [n.id, n.data]));
    expect((byId.ask as { status: string }).status).toBe("executed");
    expect((byId.ask as { produced: string[] }).produced).toEqual(["answer"]);
    expect((byId.post as { status: string }).status).toBe("skipped");
  });

  it("is the SAME graph in both modes — only the decoration differs", () => {
    const structure = toFlow(graph());
    const execution = toFlow(graph({ mode: "execution" }));
    expect(execution.nodes.map(n => n.id)).toEqual(structure.nodes.map(n => n.id));
    expect(execution.edges.map(e => e.id)).toEqual(structure.edges.map(e => e.id));
  });

  it("renders an empty automation without inventing an edge", () => {
    const { nodes, edges } = toFlow(graph({ nodes: [], edges: [] }));
    expect(nodes).toEqual([]);
    expect(edges).toEqual([]);
  });
});

/* ── DS-6 · the route, at the handoff ───────────────────────────────────────────── */

describe("the route edge", () => {
  const routed = (over: Partial<AutomationGraphData> = {}): AutomationGraphData =>
    graph({
      nodes: [
        { id: "trigger", type: "trigger", label: "When", detail: "schedule" },
        { id: "alerts", type: "effect", kind: "slack_post", label: "alerts",
          when: ["numbers.answer is set"] },
        { id: "daily", type: "effect", kind: "slack_post", label: "daily",
          else_of: "alerts" },
      ],
      edges: [
        { from: "trigger", to: "alerts", type: "sequence" },
        { from: "alerts", to: "daily", type: "sequence" },
        { from: "alerts", to: "daily", type: "route", label: "otherwise" },
      ],
      ...over,
    });

  it("draws the route in its own style, labelled with the server's word", () => {
    const route = toFlow(routed()).edges
      .find(e => (e.data as { edgeType?: string })?.edgeType === "route")!;
    expect(route.label).toBe("otherwise");
    expect(route.style?.strokeDasharray).toBe("7 4");
    expect(route.style?.stroke).toBe("var(--chart-4)");
  });

  it("a route edge suppresses the sequence edge on its pair — it claims more", () => {
    const pairs = seqEdges(routed()).map(e => `${e.source}->${e.target}`);
    expect(pairs).not.toContain("alerts->daily");
  });

  it("the untaken arm's node data carries not_taken for the card to read", () => {
    const g = routed({ mode: "execution" });
    g.nodes[2].status = "skipped";
    g.nodes[2].not_taken = true;
    const byId = Object.fromEntries(toFlow(g).nodes.map(n => [n.id, n.data]));
    expect((byId.daily as { not_taken?: boolean }).not_taken).toBe(true);
  });
});

/* ── DS-7 · scheduling, at the handoff ──────────────────────────────────────────── */

describe("parallel scheduling on the execution graph", () => {
  it("hands the trigger card the scheduling so a rootless spine can say why", () => {
    const g = graph({ scheduling: "parallel" });
    const trigger = toFlow(g).nodes.find(n => n.id === "trigger")!;
    expect((trigger.data as { scheduling?: string }).scheduling).toBe("parallel");
    const step = toFlow(g).nodes.find(n => n.id === "ask")!;
    expect((step.data as { scheduling?: string }).scheduling).toBeUndefined();
  });

  it("draws exactly the sequence edges the server sent — the frontier's spine is the server's call", () => {
    // build_graph already prunes the spine to trigger→roots for a parallel
    // automation; the client must pass that through, not re-derive its own order.
    const g = graph({
      scheduling: "parallel",
      edges: [
        { from: "trigger", to: "ask", type: "sequence" },
        { from: "trigger", to: "post", type: "sequence" },
      ],
    });
    const pairs = seqEdges(g).map(e => `${e.source}->${e.target}`);
    expect(pairs).toEqual(["trigger->ask", "trigger->post"]);
  });
});

/* ── §3.8b · the change channel ──────────────────────────────────────────────
 *
 * The canvas passed `nodes` to ReactFlow with NO `onNodesChange`, which breaks
 * controlled mode: the library moved a card in its own store, our array never heard, and
 * the next parent render put it back where stale state said it was. Our own DS-4 comment
 * had recorded the symptom — "it does not fire here at all" — as a library quirk; it did
 * not fire because it was never passed.
 *
 * Asserted on `positionChanges` for this file's stated reason: jsdom reports every
 * element as 0×0, so a rendered-drag assertion could not fail.
 */
describe("positionChanges — what may flow back from the library", () => {
  const move = (id: string, x: number, y: number) =>
    ({ type: "position", id, position: { x, y }, dragging: true }) as never;

  it("collects a position so a drag is not reset by the next render", () => {
    expect(positionChanges([move("ask", 10, 20)])).toEqual({ ask: { x: 10, y: 20 } });
  });

  it("returns null when nothing moved, so no state write happens at all", () => {
    // The common case on a selection or dimension tick. Returning `{}` would set state
    // on every frame and re-run the design memo for nothing.
    expect(positionChanges([{ type: "select", id: "ask", selected: true } as never])).toBeNull();
  });

  it("ignores the final tick that carries no position", () => {
    // ReactFlow emits `dragging: false` with no `position`. Writing `undefined` through
    // would blank the card's coordinates at the exact moment the drag ends.
    expect(positionChanges([{ type: "position", id: "ask", dragging: false } as never]))
      .toBeNull();
  });

  it("REFUSES a non-position change even when it CARRIES a position", () => {
    // The type check is what this asserts, so the fixture has to make it load-bearing:
    // an `add`/`replace` change carries its node under `item`, and a first version of
    // this test used those — which have no `.position` at all, so deleting the type
    // check left the test green. The same shape as the bug it was meant to catch.
    // A change that is NOT a move but does carry coordinates is the honest fixture:
    // structure flows draft → canvas, and only position flows back.
    const carriesPosition = [
      { type: "replace", id: "ask", position: { x: 99, y: 99 } },
    ] as never[];
    expect(positionChanges(carriesPosition)).toBeNull();
  });

  it("ignores the structural changes the library also emits", () => {
    const structural = [
      { type: "remove", id: "ask" },
      { type: "dimensions", id: "post", dimensions: { width: 10, height: 10 } },
    ] as never[];
    expect(positionChanges(structural)).toBeNull();
  });

  it("keeps the last position when one node moves several times in a batch", () => {
    expect(positionChanges([move("ask", 1, 1), move("ask", 9, 9)]))
      .toEqual({ ask: { x: 9, y: 9 } });
  });

  it("carries every moved node — a multi-select drag moves more than one", () => {
    expect(positionChanges([move("ask", 1, 2), move("post", 3, 4)]))
      .toEqual({ ask: { x: 1, y: 2 }, post: { x: 3, y: 4 } });
  });
});
