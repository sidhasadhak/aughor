/**
 * Agent Ops' layers by the id a link names them with — `?tab=agentic-ops&layer=…`.
 *
 * The ids are frozen: links, bookmarks and the URL the shell writes all name them, so a label may change and an id
 * never does. The first is the Overview — the layer the workspace opens on.
 *
 * A layer that folded into another is still a door: the Activity tab folded into the Overview (2026-10-13), and
 * `?layer=activity` — in a bookmark, a link someone was sent, the UI study's own list of screens — lands on the
 * Overview rather than on nothing. Its live events and traces are at the Overview's foot.
 */
export const AGENT_OPS_LAYERS = [
  "fleet", "agents", "attention", "automations", "hub", "departures", "duties", "action-centre", "developer",
] as const;

export type AgentOpsLayer = (typeof AGENT_OPS_LAYERS)[number];

/** The Overview: where the workspace opens, and where every drill to a trace or a live event lands. */
export const OVERVIEW_LAYER: AgentOpsLayer = AGENT_OPS_LAYERS[0];

const LAYERS: ReadonlySet<string> = new Set<string>(AGENT_OPS_LAYERS);

/** A layer that is gone, and the one that holds what it showed. */
const FOLDED: ReadonlyMap<string, AgentOpsLayer> = new Map<string, AgentOpsLayer>([["activity", OVERVIEW_LAYER]]);

/** The layer a link's `layer=` names, a folded one resolved to where it went; null when it names none. */
export function agentOpsLayerOf(id: string | null | undefined): AgentOpsLayer | null {
  if (!id) return null;
  if (LAYERS.has(id)) return id as AgentOpsLayer;
  return FOLDED.get(id) ?? null;
}
