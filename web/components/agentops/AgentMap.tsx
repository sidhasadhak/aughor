"use client";

/**
 * DS-5 · the agent's Map — what it is plugged into, and what it runs.
 *
 * **Still not a canvas for an agent.** §4.1's refusal stands and this does not touch it:
 * the record keeps its form (Configure), and what gets drawn here is the agent's SYSTEM —
 * the connection it answers on, the documents and packs it reads, the doors it can be
 * reached through, the chains it operates, the alerts watching it. Every edge is a field
 * that already exists; nothing here is inferred and nothing here is editable.
 *
 * Called **Map** deliberately. "Design" is the automation card's button and the automation
 * canvas's own mode label, both one click away, and "Canvas" is the Data Canvas — a tab
 * borrowing either word would promise an editor this surface is not.
 *
 * The assembly is deliberately client-side: every list it reads was already being fetched
 * for this panel or is a small whole-set endpoint the app already calls elsewhere. That is
 * VA-4d's lesson — check whether the substrate is merely unfed before building a plane to
 * feed it. Two TypeScript fields and three filters bought the whole thing.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background, Handle, MarkerType, Position, ReactFlow,
  type Edge as RFEdge, type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { CARD_W, FieldRow } from "@/components/agentops/RunNodes";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import {
  getAutomations, getConnections, getSlackBots, listAgentAlertRules,
  type AgentAlertRule, type Automation, type Connection, type SlackBotSummary,
  type UserAgent,
} from "@/lib/api";
import { toMapFlow, type MapKind, type MapNode, type MapTarget } from "@/lib/agentMap";

/** One hue and one glyph per kind of thing an agent is wired to.
 *
 *  Its own table rather than an extension of `RunNodes`' `FACE_META`: that one is the
 *  vocabulary of a RUN (trigger, model, guardrail, tool), derived per event and never
 *  stored. These are objects, not moments, and folding them into the run's list would put
 *  two meanings behind one word. Six kinds against the six `--chart` tokens `lint:palette`
 *  validates. */
const MAP_META: Record<MapKind, { icon: IconName; color: string }> = {
  agent: { icon: "robot", color: "var(--chart-1)" },
  connection: { icon: "plug", color: "var(--chart-5)" },
  documents: { icon: "brief", color: "var(--chart-6)" },
  packs: { icon: "layers", color: "var(--chart-6)" },
  chat: { icon: "chat", color: "var(--chart-2)" },
  slack: { icon: "send", color: "var(--chart-2)" },
  automation: { icon: "bolt", color: "var(--chart-3)" },
  alert: { icon: "shield", color: "var(--chart-4)" },
};

interface MapNodeData extends Record<string, unknown> {
  node: MapNode;
  onOpen?: () => void;
}

function MapCard({ data }: { data: MapNodeData }) {
  const { node, onOpen } = data;
  const meta = MAP_META[node.kind];
  const isAgent = node.kind === "agent";
  return (
    <div style={{
      width: isAgent ? CARD_W + 40 : CARD_W,
      borderRadius: 8, background: "var(--bg-2)",
      border: `1px solid ${isAgent ? meta.color : "var(--b1)"}`,
      borderLeft: `3px solid ${meta.color}`,
      opacity: node.muted ? 0.62 : 1,
      paddingBottom: 5,
    }}>
      {/* Both handles on every card, invisible: the map is read-only, and a port that
          cannot be dragged from should not look like one. They exist only so the edges
          have somewhere to land. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 9px 3px" }}>
        <span style={{ color: meta.color, display: "flex" }}>
          <Icon name={meta.icon} size={12} />
        </span>
        <span className={isAgent ? "aug-fs-sm" : "aug-fs-xs"}
          style={{ color: "var(--t1)", fontWeight: 600, overflow: "hidden",
                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.title}
        </span>
      </div>

      <FieldRow label="" value={node.detail} />

      {/* A fact the reader must not have to infer — carried from the record, not coined
          here (Create Agent says the same thing in the same words on its own step). */}
      {node.warn && (
        <div className="aug-fs-xs" style={{ color: "var(--amb5)", padding: "1px 9px 2px",
          lineHeight: 1.4 }}>
          {node.warn}
        </div>
      )}

      {onOpen && (
        <div style={{ padding: "2px 5px 0" }}>
          <Button variant="ghost" size="xs" className="nodrag"
            aria-label={`Open ${node.title}`} onClick={onOpen}>
            Open <Icon name="next" size={10} />
          </Button>
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { mapCard: MapCard };

export interface AgentMapProps {
  agent: UserAgent;
  /** Where a node goes when opened. Absent handlers simply render no Open control —
   *  a button that leads nowhere teaches the reader the map is decorative. */
  onOpenConnection?: (connectionId: string) => void;
  onOpenAutomations?: (automationId: string) => void;
  onOpenIntegrations?: () => void;
  onOpenAttention?: () => void;
}

export function AgentMap({
  agent, onOpenConnection, onOpenAutomations, onOpenIntegrations, onOpenAttention,
}: AgentMapProps) {
  const [bots, setBots] = useState<SlackBotSummary[]>([]);
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [alerts, setAlerts] = useState<AgentAlertRule[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  /** Which spokes could not be READ. An unreadable list is not an empty one, and a map
   *  that drew "no chains" because a request failed would be asserting a zero it never
   *  measured — this repo's most-repeated way of being confidently wrong. */
  const [unread, setUnread] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    const miss = (what: string) => () => {
      if (live) setUnread(prev => (prev.includes(what) ? prev : [...prev, what]));
    };
    setUnread([]);
    getSlackBots().then(b => { if (live) setBots(b); }).catch(miss("Slack doors"));
    getAutomations().then(a => { if (live) setAutomations(a); }).catch(miss("chains"));
    listAgentAlertRules().then(r => { if (live) setAlerts(r); }).catch(miss("alerts"));
    getConnections().then(c => { if (live) setConnections(c); }).catch(miss("connections"));
    return () => { live = false; };
  }, [agent.id]);

  const open = useCallback((target: MapTarget): (() => void) | undefined => {
    if (target.to === "connection" && onOpenConnection) {
      return () => onOpenConnection(target.id);
    }
    if (target.to === "automations" && onOpenAutomations) {
      return () => onOpenAutomations(target.id);
    }
    if (target.to === "integrations" && onOpenIntegrations) return onOpenIntegrations;
    if (target.to === "attention" && onOpenAttention) return onOpenAttention;
    return undefined;
  }, [onOpenConnection, onOpenAutomations, onOpenIntegrations, onOpenAttention]);

  const flow = useMemo(() => {
    const { nodes, edges } = toMapFlow({
      agent: {
        id: agent.id, name: agent.name, enabled: agent.enabled,
        connection_id: agent.connection_id, schema_scope: agent.schema_scope,
        doc_ids: agent.doc_ids, pack_ids: agent.pack_ids,
      },
      connectionName: connections.find(c => c.id === agent.connection_id)?.name,
      bots, automations, alerts,
    }, { cardW: CARD_W });

    const rfNodes: RFNode[] = nodes.map(n => ({
      id: n.id, type: "mapCard", position: { x: n.x, y: n.y },
      data: { node: n, onOpen: n.target ? open(n.target) : undefined } as MapNodeData,
    }));
    const rfEdges: RFEdge[] = edges.map(e => ({
      id: e.id, source: e.from, target: e.to,
      style: {
        stroke: e.dashed ? "var(--t4)" : "var(--b2)",
        strokeWidth: e.dashed ? 1 : 1.5,
        ...(e.dashed ? { strokeDasharray: "4 4" } : {}),
      },
      markerEnd: { type: MarkerType.ArrowClosed,
                   color: e.dashed ? "var(--t4)" : "var(--b2)" },
    }));
    return { nodes: rfNodes, edges: rfEdges };
  }, [agent, bots, automations, alerts, connections, open]);

  return (
    <div style={{ height: 460, border: "1px solid var(--border)", borderRadius: 8,
                  overflow: "hidden", position: "relative" }}>
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ minZoom: 0.4, maxZoom: 1, padding: 0.18 }}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={1.4}
      >
        <Background gap={18} size={1.2} color="var(--b1)" />
      </ReactFlow>
      {unread.length > 0 && (
        <div className="aug-fs-xs" style={{ position: "absolute", left: 8, bottom: 8,
          color: "var(--amb5)", background: "var(--amb1)", border: "1px solid var(--amb2)",
          borderRadius: "var(--r-chip)", padding: "3px 10px" }}>
          could not read {unread.join(", ")} — this map is missing what they hold
        </div>
      )}
    </div>
  );
}

export default AgentMap;
