/**
 * DS-5 — the agent's world, asserted at the handoff.
 *
 * jsdom draws zero ReactFlow edges no matter what it is handed, so a test that mounted
 * this map could not fail. Everything worth catching is therefore in `toMapFlow`: which
 * relations exist, which are the agent's OWN versus merely pointed at it, and the two
 * facts a reader must not have to infer — an agent with no documents sees none at all,
 * and a paused agent answers nothing.
 */
import { describe, expect, it } from "vitest";

import { toMapFlow, type AgentWorld } from "@/lib/agentMap";

const agent = (over: Partial<AgentWorld["agent"]> = {}): AgentWorld["agent"] => ({
  id: "ua_1", name: "Sales Reporter", enabled: true,
  connection_id: "conn_1", schema_scope: "thelook",
  doc_ids: ["d1"], pack_ids: [], ...over,
});

const world = (over: Partial<AgentWorld> = {}): AgentWorld => ({
  agent: agent(), bots: [], automations: [], alerts: [], ...over,
});

const auto = (over: Partial<AgentWorld["automations"][number]> = {}) =>
  ({ id: "a1", name: "Daily sales", enabled: true, effects: [], ...over });

const byId = (nodes: { id: string }[]) => new Set(nodes.map(n => n.id));

describe("the agent and its scope", () => {
  it("puts the agent at the centre", () => {
    const { nodes } = toMapFlow(world());
    const centre = nodes.find(n => n.id === "agent")!;
    expect([centre.x, centre.y]).toEqual([0, 0]);
    expect(centre.title).toBe("Sales Reporter");
  });

  it("names the connection and the schema it is scoped to", () => {
    const { nodes } = toMapFlow(world({ connectionName: "theLook" }));
    const conn = nodes.find(n => n.id === "connection")!;
    expect(conn.title).toBe("theLook");
    expect(conn.detail).toBe("schema thelook");
    expect(conn.target).toEqual({ to: "connection", id: "conn_1" });
  });

  it("says an unbound agent answers on whatever asked, and offers nothing to open", () => {
    const { nodes } = toMapFlow(world({ agent: agent({ connection_id: "", schema_scope: "" }) }));
    const conn = nodes.find(n => n.id === "connection")!;
    expect(conn.muted).toBe(true);
    expect(conn.target).toBeUndefined();
  });

  it("carries the empty-documents disclosure onto the map", () => {
    // Attaching none is NOT neutral: the retrieval seam fails closed, so an agent with no
    // documents sees FEWER than asking with no agent. Create Agent says this on the step;
    // a reader arriving at the map later must not have to remember it.
    const { nodes } = toMapFlow(world({ agent: agent({ doc_ids: [] }) }));
    const docs = nodes.find(n => n.id === "documents")!;
    expect(docs.warn).toContain("fewer than asking with no agent");
  });

  it("says nothing alarming when documents ARE attached", () => {
    const { nodes } = toMapFlow(world());
    expect(nodes.find(n => n.id === "documents")!.warn).toBeUndefined();
  });

  it("draws packs only when there are some", () => {
    expect(byId(toMapFlow(world()).nodes).has("packs")).toBe(false);
    const withPacks = toMapFlow(world({ agent: agent({ pack_ids: ["p1", "p2"] }) }));
    expect(withPacks.nodes.find(n => n.id === "packs")!.detail).toBe("2 attached");
  });
});

describe("the doors", () => {
  it("always draws chat, because every enabled agent answers there", () => {
    expect(byId(toMapFlow(world()).nodes).has("door:chat")).toBe(true);
  });

  it("says a paused agent answers nothing, rather than drawing a live door", () => {
    const { nodes } = toMapFlow(world({ agent: agent({ enabled: false }) }));
    const chat = nodes.find(n => n.id === "door:chat")!;
    expect(chat.muted).toBe(true);
    expect(chat.detail).toContain("answers nothing");
  });

  it("draws only the Slack bots that are doors onto THIS agent", () => {
    const { nodes } = toMapFlow(world({
      bots: [{ id: "b1", name: "Sales bot", agent_id: "ua_1" },
             { id: "b2", name: "Someone else's", agent_id: "ua_2" }],
    }));
    expect(byId(nodes).has("bot:b1")).toBe(true);
    expect(byId(nodes).has("bot:b2")).toBe(false);
  });

  it("dims a disabled bot instead of hiding it — the door exists, it is shut", () => {
    const { nodes } = toMapFlow(world({
      bots: [{ id: "b1", name: "Sales bot", agent_id: "ua_1", enabled: false }],
    }));
    expect(nodes.find(n => n.id === "bot:b1")!.muted).toBe(true);
  });
});

describe("the chains — two relations, never collapsed", () => {
  it("draws a chain that RUNS AS this agent", () => {
    const { nodes } = toMapFlow(world({ automations: [auto({ agent_id: "ua_1" })] }));
    expect(nodes.find(n => n.id === "auto:a1")!.detail).toBe("runs as this agent");
  });

  it("draws a chain that merely hands this agent ONE STEP", () => {
    // VA-2 delegation: the automation runs as somebody else, but one of its effects is
    // this agent's work. Collapsing the two into "2 automations" would put a chain the
    // agent does not own in the same sentence as one it does.
    const { nodes, edges } = toMapFlow(world({
      automations: [auto({ agent_id: "ua_other", effects: [{ config: { agent_id: "ua_1" } }] })],
    }));
    expect(nodes.find(n => n.id === "auto:a1")!.detail).toBe("one step runs as this agent");
    // Drawn as a weaker tie, because the agent does not own it.
    expect(edges.find(e => e.to === "auto:a1")!.dashed).toBe(true);
  });

  it("does not draw a chain that has nothing to do with this agent", () => {
    const { nodes } = toMapFlow(world({
      automations: [auto({ agent_id: "ua_other", effects: [{ config: { agent_id: "ua_x" } }] })],
    }));
    expect(byId(nodes).has("auto:a1")).toBe(false);
  });

  it("counts a chain once when it BOTH runs as the agent and delegates a step to it", () => {
    // Otherwise the same automation appears twice, and two nodes sharing an id is a
    // React key collision as well as a lie about how many chains there are.
    const { nodes } = toMapFlow(world({
      automations: [auto({ agent_id: "ua_1", effects: [{ config: { agent_id: "ua_1" } }] })],
    }));
    expect(nodes.filter(n => n.id === "auto:a1")).toHaveLength(1);
    expect(nodes.find(n => n.id === "auto:a1")!.detail).toBe("runs as this agent");
  });

  it("keeps an effect with no agent from matching an agent whose id is empty", () => {
    // `String(undefined ?? "")` is `""`, and an agent id is never empty — but a future
    // caller passing a blank id must not suddenly own every chain in the workspace.
    const { nodes } = toMapFlow(world({
      agent: agent({ id: "" }),
      automations: [auto({ agent_id: "ua_other", effects: [{}] })],
    }));
    expect(byId(nodes).has("auto:a1")).toBe(false);
  });
});

describe("the watchers", () => {
  it("draws only the alert rules aimed at this agent", () => {
    const { nodes } = toMapFlow(world({
      alerts: [{ id: "r1", name: "Slow answers", agent_id: "ua_1", enabled: true },
               { id: "r2", name: "Every agent", agent_id: "", enabled: true }],
    }));
    expect(byId(nodes).has("alert:r1")).toBe(true);
    expect(byId(nodes).has("alert:r2")).toBe(false);
  });
});

describe("the layout", () => {
  it("is deterministic — the same agent twice looks identical", () => {
    // TraceFlow's rule, and its reason: a surface you read to understand something must
    // not rearrange itself between visits.
    const w = world({ bots: [{ id: "b1", name: "Bot", agent_id: "ua_1" }] });
    expect(toMapFlow(w).nodes).toEqual(toMapFlow(w).nodes);
  });

  it("puts scope on the left and reach on the right", () => {
    // The same grammar the automation canvas gives its ports: in from the left, out to
    // the right. A reader who has seen one canvas already knows which way this flows.
    const { nodes } = toMapFlow(world({ bots: [{ id: "b1", name: "Bot", agent_id: "ua_1" }] }));
    expect(nodes.find(n => n.id === "connection")!.x).toBeLessThan(0);
    expect(nodes.find(n => n.id === "bot:b1")!.x).toBeGreaterThan(0);
  });

  it("wraps a long side into a second column rather than one long stalk", () => {
    const bots = Array.from({ length: 9 }, (_, i) =>
      ({ id: `b${i}`, name: `Bot ${i}`, agent_id: "ua_1" }));
    const { nodes } = toMapFlow(world({ bots }));
    const xs = new Set(nodes.filter(n => n.kind === "slack").map(n => n.x));
    expect(xs.size).toBe(2);
  });

  it("centres each column on the agent", () => {
    const { nodes } = toMapFlow(world({
      bots: [{ id: "b1", name: "A", agent_id: "ua_1" }],  // chat + 1 bot = 2 on the right
    }));
    const right = nodes.filter(n => n.x > 0).map(n => n.y).sort((a, b) => a - b);
    expect(right[0]).toBe(-right[right.length - 1]);
  });
});

describe("the edges", () => {
  it("connects every node to the agent, and nothing to anything else", () => {
    const { nodes, edges } = toMapFlow(world({
      bots: [{ id: "b1", name: "Bot", agent_id: "ua_1" }],
      automations: [auto({ agent_id: "ua_1" })],
    }));
    expect(edges).toHaveLength(nodes.length - 1);
    for (const e of edges) expect(e.from === "agent" || e.to === "agent").toBe(true);
  });

  it("points scope INTO the agent and reach OUT of it", () => {
    const { edges } = toMapFlow(world({ bots: [{ id: "b1", name: "Bot", agent_id: "ua_1" }] }));
    expect(edges.find(e => e.id === "e:connection")!.to).toBe("agent");
    expect(edges.find(e => e.id === "e:bot:b1")!.from).toBe("agent");
  });
});
