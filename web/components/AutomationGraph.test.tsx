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

import { toFlow, type AutomationGraphData } from "@/components/AutomationGraph";

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
