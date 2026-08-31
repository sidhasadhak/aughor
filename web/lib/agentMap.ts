/**
 * DS-5 · an agent's world, as a graph.
 *
 * **This is not a canvas for an agent.** ROADMAP §4.1 refused that with evidence, and the
 * refusal stands: an agent is one record — a scope and a stance — whose parts have no
 * producer/consumer relation, so there is no second node for an edge to terminate on. What
 * DOES have relations is everything the agent is wired TO: the connection it answers on,
 * the documents and packs it reads, the doors it can be reached through, the chains it
 * operates, the alerts that watch it. The record stays a form; its SYSTEM is a graph, and
 * every edge here is a field that already exists in the data.
 *
 * Read-first. Nothing on this map edits anything — it answers "what is this agent plugged
 * into, and what would I have to open to change it".
 *
 * Pure, and positions included, for this repo's standing reason: jsdom renders zero
 * ReactFlow edges no matter what it is handed, so everything a test must be able to catch
 * has to live in a function that never mounts a canvas.
 *
 * **Layout is computed, never simulated** — TraceFlow's rule, and for its reason: the same
 * agent opened twice must look identical. Scope enters from the LEFT and reach leaves to
 * the RIGHT, the same grammar the automation canvas gives its ports, so a reader who has
 * seen one canvas already knows which way this one flows.
 */

export type MapKind =
  | "agent" | "connection" | "documents" | "packs"
  | "chat" | "slack" | "automation" | "alert";

/** Where clicking a node goes. Only destinations that actually exist are offered — a node
 *  that opens nothing is honest; one that opens the wrong place is not. */
export type MapTarget =
  | { to: "connection"; id: string }
  | { to: "automations"; id: string }
  | { to: "integrations" }
  | { to: "attention" };

export interface MapNode {
  id: string;
  kind: MapKind;
  title: string;
  /** The one line under the title. Never invented — every value here is a field. */
  detail: string;
  /** Real, but not currently doing anything: paused, disabled, muted. */
  muted?: boolean;
  /** Something the reader should not have to infer. Rendered, not logged. */
  warn?: string;
  target?: MapTarget;
  x: number;
  y: number;
}

export interface MapEdge {
  id: string;
  from: string;
  to: string;
  /** A relation the agent does not own — a chain that merely delegates ONE step to it. */
  dashed?: boolean;
}

/** The shapes this reads. Deliberately structural rather than the imported API types: the
 *  builder needs four fields off an automation and two off a bot, and saying so keeps a
 *  test from constructing a whole `Automation` to assert one filter. */
export interface AgentWorld {
  agent: {
    id: string; name: string; enabled: boolean;
    connection_id: string; schema_scope: string;
    doc_ids: string[]; pack_ids: string[];
  };
  /** The connection's human name, when the roster has been read. Falls back to the id. */
  connectionName?: string;
  bots: { id: string; name: string; enabled?: boolean; agent_id?: string }[];
  automations: {
    id: string; name: string; enabled: boolean; agent_id?: string;
    effects: { config?: Record<string, unknown> }[];
  }[];
  alerts: { id: string; name: string; agent_id: string; enabled: boolean }[];
}

export interface MapLayout {
  /** Card width — passed in so the one true value can live with the cards themselves. */
  cardW?: number;
  /** Vertical distance between stacked cards. */
  rowH?: number;
  /** Cards per column before a group wraps into a second one. */
  perColumn?: number;
}

const DEFAULTS = { cardW: 218, rowH: 96, perColumn: 6 };

/**
 * Stack `count` cards in columns of at most `perColumn`, centred on y = 0, marching away
 * from the agent in `dir` (-1 left, +1 right). Returns one position per index.
 *
 * Centring each column independently is deliberate: a side with seven cards reads as two
 * balanced columns rather than one long one and a stub.
 */
function placeColumn(
  count: number, dir: -1 | 1, opts: Required<MapLayout>,
): { x: number; y: number }[] {
  const { cardW, rowH, perColumn } = opts;
  const gap = cardW + 90;
  const columns = Math.max(1, Math.ceil(count / perColumn));
  const perCol = Math.ceil(count / columns);
  return Array.from({ length: count }, (_, i) => {
    const col = Math.floor(i / perCol);
    const row = i % perCol;
    const inThisCol = Math.min(perCol, count - col * perCol);
    return {
      x: dir * gap * (col + 1),
      y: (row - (inThisCol - 1) / 2) * rowH,
    };
  });
}

/**
 * The agent, and everything it is wired to.
 *
 * The two automation relations are kept apart on purpose. `Automation.agent_id` means the
 * chain RUNS AS this agent (VA-9b); an effect's `agent_id` means some other chain hands
 * this agent one step (VA-2 delegation). Collapsing them into "3 automations" would put a
 * chain the agent does not own in the same sentence as one it does.
 */
export function toMapFlow(world: AgentWorld, layout: MapLayout = {}): {
  nodes: MapNode[]; edges: MapEdge[];
} {
  const opts = { ...DEFAULTS, ...layout };
  const { agent } = world;

  /** Does this `agent_id` field name THIS agent?
   *
   *  The empty-id guard is not defensive noise. Most automations carry `agent_id: ""`
   *  (they run as nobody in particular), and `""` is also what an absent effect field
   *  reads as — so an agent whose own id were blank would silently claim every unbound
   *  chain in the workspace and every effect that names no one. Caught by the test that
   *  asks for it; the whole map goes through this one predicate so it cannot come back
   *  in a filter someone adds later. */
  const mine = (id: string | undefined | null): boolean =>
    !!agent.id && String(id ?? "") === agent.id;

  /* ── what it is scoped to (enters from the left) ── */
  const scope: Omit<MapNode, "x" | "y">[] = [];

  scope.push(agent.connection_id
    ? {
      id: "connection", kind: "connection",
      title: world.connectionName || agent.connection_id,
      detail: agent.schema_scope ? `schema ${agent.schema_scope}` : "all schemas",
      target: { to: "connection", id: agent.connection_id },
    }
    : {
      id: "connection", kind: "connection", title: "Any connection",
      detail: "answers on whichever connection asked", muted: true,
    });

  scope.push({
    id: "documents", kind: "documents", title: "Documents",
    detail: agent.doc_ids.length
      ? `${agent.doc_ids.length} attached`
      : "none attached",
    muted: agent.doc_ids.length === 0,
    // The disclosure Create Agent already makes, in the same words, because a reader
    // arriving here should not have to remember it: attaching none is NOT neutral.
    warn: agent.doc_ids.length === 0
      ? "sees NO documents at all — fewer than asking with no agent"
      : undefined,
  });

  if (agent.pack_ids.length) {
    scope.push({
      id: "packs", kind: "packs", title: "Packs",
      detail: `${agent.pack_ids.length} attached`,
    });
  }

  /* ── how it is reached, and what it runs (leaves to the right) ── */
  const reach: Omit<MapNode, "x" | "y">[] = [];

  reach.push({
    id: "door:chat", kind: "chat", title: "Chat",
    detail: agent.enabled ? "answers when asked as this agent" : "paused — answers nothing",
    muted: !agent.enabled,
  });

  for (const bot of world.bots.filter(b => mine(b.agent_id))) {
    reach.push({
      id: `bot:${bot.id}`, kind: "slack", title: bot.name,
      detail: bot.enabled === false ? "Slack door · disabled" : "Slack door",
      muted: bot.enabled === false,
      target: { to: "integrations" },
    });
  }

  const operates = world.automations.filter(a => mine(a.agent_id));
  const delegated = world.automations.filter(a =>
    !mine(a.agent_id)
    && a.effects.some(e => mine(e.config?.agent_id as string | undefined)));

  for (const auto of operates) {
    reach.push({
      id: `auto:${auto.id}`, kind: "automation", title: auto.name,
      detail: auto.enabled ? "runs as this agent" : "paused · runs as this agent",
      muted: !auto.enabled,
      target: { to: "automations", id: auto.id },
    });
  }
  for (const auto of delegated) {
    reach.push({
      id: `auto:${auto.id}`, kind: "automation", title: auto.name,
      detail: auto.enabled ? "one step runs as this agent" : "paused · one step",
      muted: !auto.enabled,
      target: { to: "automations", id: auto.id },
    });
  }

  for (const rule of world.alerts.filter(r => mine(r.agent_id))) {
    reach.push({
      id: `alert:${rule.id}`, kind: "alert", title: rule.name,
      detail: rule.enabled ? "watches this agent" : "paused",
      muted: !rule.enabled,
      target: { to: "attention" },
    });
  }

  /* ── place them ── */
  const left = placeColumn(scope.length, -1, opts);
  const right = placeColumn(reach.length, 1, opts);

  const nodes: MapNode[] = [
    {
      id: "agent", kind: "agent", title: agent.name,
      detail: agent.enabled ? "active" : "paused",
      muted: !agent.enabled, x: 0, y: 0,
    },
    ...scope.map((n, i) => ({ ...n, ...left[i] })),
    ...reach.map((n, i) => ({ ...n, ...right[i] })),
  ];

  const edges: MapEdge[] = [
    ...scope.map(n => ({ id: `e:${n.id}`, from: n.id, to: "agent" })),
    ...reach.map(n => ({
      id: `e:${n.id}`, from: "agent", to: n.id,
      // A delegated chain is drawn as a weaker tie: the agent does not own it.
      dashed: n.detail.startsWith("one step") || n.detail.includes("· one step"),
    })),
  ];

  return { nodes, edges };
}
