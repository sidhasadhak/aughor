"use client";

/**
 * VA-5 · the node view — one run drawn as a canvas of nodes, left to right.
 *
 * **Why this is not the waterfall.** The waterfall answers "where did the time go",
 * laying every node on one axis. It cannot answer "what ran under what", because a time
 * axis flattens nesting by construction: a delegate's work and its supervisor's occupy
 * the same stretch of wall clock and end up side by side. This answers the second
 * question and gives up the first.
 *
 * **Why it can exist now.** Until delegation shipped, a trace had almost no real
 * parentage — which is why `flow_edges` originally returned `zip(nodes, nodes[1:])`.
 * Rendering that as a graph would have drawn a straight line and called it one. The
 * edges are structural now, so there is something to draw.
 *
 * **Layout is deterministic, not simulated.** A run has an inherent reading order — the
 * sequence it happened in — so positions are computed, never settled by a force. The
 * same run opened twice looks identical, which is the property a debugging surface needs
 * and a force-directed graph cannot promise. Roots form a horizontal spine in `seq`
 * order; a node's children hang one column to the right, stacked, and the next root
 * starts clear of the whole subtree.
 *
 * (An earlier version of this file rendered a nested list and argued that avoided a
 * dependency. It did not: `@xyflow/react` has been in this app since #178 and drives two
 * other canvases. The argument was wrong on the facts, so the canvas is the better
 * answer — same library, same design system, and pan/zoom/fit come with it.)
 */
import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { SessionEvent, TimelineNode, TraceFlowEdge, TraceTimeline } from "@/lib/api";
import { formatCount } from "@/lib/format";

const KIND_COLOR: Record<string, string> = {
  model: "var(--chart-1)",
  tool: "var(--chart-2)",
  frame: "var(--chart-3)",
  error: "var(--red4)",
  event: "var(--chart-6)",
  delegation: "var(--chart-4)",
};

/** Card geometry. Columns are wide enough for a model id; rows clear a usage block. */
const COL_W = 260;
const ROW_H = 132;

function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}

interface FlowNode extends TimelineNode {
  children: FlowNode[];
}

/**
 * Roots in `seq` order, each carrying its children.
 *
 * Built from the EDGES rather than by re-reading `parent_span_id`, so the picture and
 * the contract cannot drift: whatever the backend calls a child edge is what nests here.
 */
export function buildForest(nodes: TimelineNode[], edges: TraceFlowEdge[]): FlowNode[] {
  const byId = new Map<string, FlowNode>(nodes.map(n => [n.id, { ...n, children: [] }]));
  const claimed = new Set<string>();
  const parentOf = new Map<string, string>();

  /** Would linking parent→child close a loop? Walk up from the prospective parent. */
  const wouldCycle = (parentId: string, childId: string): boolean => {
    let p: string | undefined = parentId;
    for (let hops = 0; p && hops <= nodes.length; hops++) {
      if (p === childId) return true;
      p = parentOf.get(p);
    }
    return false;
  };

  for (const e of edges) {
    if (e.kind !== "child") continue;
    const parent = byId.get(e.from);
    const child = byId.get(e.to);
    if (!parent || !child || claimed.has(child.id) || parent.id === child.id) continue;
    // A cycle is refused EDGE BY EDGE rather than detected afterwards. Claiming both
    // ends first and cleaning up later loses them: with a→b and b→a every node is some
    // node's child, the root list comes back empty, and the whole run disappears from
    // the view. Dropping the edge that closes the loop keeps the run readable and costs
    // only the one relationship that could not be true.
    if (wouldCycle(parent.id, child.id)) continue;
    parent.children.push(child);
    parentOf.set(child.id, parent.id);
    claimed.add(child.id);
  }
  return nodes.filter(n => !claimed.has(n.id)).map(n => byId.get(n.id)!).filter(Boolean);
}

/** `{id: {col, row}}` for every node. Pure, and exported so the layout is testable
 *  without mounting a canvas. */
export function layoutForest(forest: FlowNode[]): Map<string, { col: number; row: number }> {
  const pos = new Map<string, { col: number; row: number }>();
  let col = 0;

  for (const root of forest) {
    pos.set(root.id, { col, row: 0 });
    // Depth-first, so a subtree reads top-to-bottom in the order it ran. `row` is a
    // running counter rather than the child's index: two children with children of
    // their own must not be dealt the same row.
    let row = 1;
    let widest = 0;
    const walk = (node: FlowNode, depth: number) => {
      for (const child of node.children) {
        pos.set(child.id, { col: col + depth, row: row++ });
        widest = Math.max(widest, depth);
        walk(child, depth + 1);
      }
    };
    walk(root, 1);
    // Clear the whole subtree before the next root, so columns never collide.
    col += widest + 1;
  }
  return pos;
}

/** The stored row behind a node, or null when nothing matched.
 *
 *  Matched on `span_id` first and `seq` second. A node IS an event — the timeline is
 *  built from these rows — but a frame without a span has only its sequence number to be
 *  found by, and matching on seq alone would pair a node with whatever row happened to
 *  share its number in a run that recorded spans out of order. */
export function eventForNode(node: TimelineNode, events: SessionEvent[]): SessionEvent | null {
  if (node.span_id) {
    const bySpan = events.find(e => e.span_id === node.span_id);
    if (bySpan) return bySpan;
  }
  return events.find(e => e.seq === node.seq) ?? null;
}

/** What a payload says, without pretending it says more than it does. */
function payloadText(event: SessionEvent | null): string | null {
  if (!event?.payload || Object.keys(event.payload).length === 0) return null;
  try {
    return JSON.stringify(event.payload, null, 2);
  } catch {
    return null;
  }
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <span style={{ color: "var(--t4)", flexShrink: 0 }}>{label}</span>
      <span style={{ color: "var(--t2)", textAlign: "right", overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

function NodeCard({ data }: {
  data: { node: TimelineNode; event: SessionEvent | null; open: boolean; onToggle: () => void };
}) {
  const node = data.node;
  const event = data.event;
  const open = data.open;
  const payload = open ? payloadText(event) : null;
  const color = KIND_COLOR[node.kind] ?? "var(--chart-6)";
  const failed = node.ok === false;
  const u = node.usage;
  const border = failed ? "var(--red4)" : color;

  return (
    <div
      className="aug-fs-ui"
      style={{
        width: COL_W - 40,
        background: "var(--bg-2)",
        border: `1px solid ${border}`,
        borderLeft: `3px solid ${border}`,
        borderRadius: "var(--r-chip)",
        overflow: "hidden",
      }}
    >
      {/* A custom node needs handles or its edges have nothing to anchor to and simply
          do not render — 14 nodes drew 0 edges before these existed. Hidden, because the
          anchor points are geometry, not something a reader of a finished run acts on. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px" }}>
        <span style={{ color: "var(--t1)", fontWeight: 500, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.name}
        </span>
        <span style={{ color: "var(--t3)", marginLeft: "auto", flexShrink: 0 }}>
          {ms(node.duration_ms)}
        </span>
      </div>

      {node.delegation && (
        // The hop's own identity. `path` is the value the runtime refuses cycles on, so
        // what is drawn here and what was refused there cannot disagree.
        <div style={{ padding: "0 8px 6px" }} title={`delegation path: ${node.delegation.path}`}>
          <span style={{ color: "var(--chart-4)", border: "1px solid var(--chart-4)",
                         borderRadius: "var(--r-pill)", padding: "0 6px" }}>
            {node.delegation.agent_name}
            {node.delegation.depth != null && ` · d${node.delegation.depth}`}
          </span>
        </div>
      )}

      {node.model && (
        <div style={{ display: "flex", justifyContent: "space-between",
                      padding: "3px 8px", borderTop: "1px solid var(--border)" }}>
          <span style={{ color: "var(--t4)" }}>Model</span>
          <span style={{ color: "var(--t2)" }}>{node.model}</span>
        </div>
      )}

      {u && (u.total_tokens != null || u.prompt_tokens != null) && (
        // §6.1's usage block, as three rows rather than one hover: the split between
        // prompt and completion is the number that tells you WHICH half to go and fix.
        <div style={{ borderTop: "1px solid var(--border)", padding: "3px 8px" }}>
          {([["Prompt", u.prompt_tokens], ["Completion", u.completion_tokens],
             ["Total", u.total_tokens]] as const).map(([label, v]) => (
            <div key={label} style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--t4)" }}>{label}</span>
              <span style={{ color: label === "Total" ? "var(--t1)" : "var(--t3)" }}>
                {v == null ? "—" : formatCount(v)}
              </span>
            </div>
          ))}
        </div>
      )}

      {failed && (
        <div style={{ padding: "3px 8px", color: "var(--red4)",
                      borderTop: "1px solid var(--border)" }}>
          {node.error_class || "failed"}
        </div>
      )}

      {/* The card summarises; this is the row it summarises FROM. Without it the canvas
          could say a call took 9.63s and cost 806 tokens and still not say what was
          asked or answered — which is the question a person opens a trace to settle. */}
      <button
        type="button"
        onClick={data.onToggle}
        className="nodrag aug-fs-xs"
        style={{
          width: "100%", display: "flex", justifyContent: "space-between",
          alignItems: "center", padding: "3px 8px", background: "none", cursor: "pointer",
          border: "none", borderTop: "1px solid var(--border)", color: "var(--t3)",
        }}
      >
        <span>{open ? "Hide details" : "Details"}</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div
          className="nodrag nowheel aug-fs-xs"
          style={{
            borderTop: "1px solid var(--border)", padding: "6px 8px",
            maxHeight: 260, overflowY: "auto", background: "var(--bg-1)",
          }}
        >
          {event ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <DetailRow label="Kind" value={event.kind} />
              <DetailRow label="At" value={event.at} />
              {node.offset_ms != null && <DetailRow label="Offset" value={ms(node.offset_ms)} />}
              {node.gap_ms != null && <DetailRow label="Waited before" value={ms(node.gap_ms)} />}
              {event.provider && <DetailRow label="Provider" value={event.provider} />}
              {event.role && <DetailRow label="Role" value={event.role} />}
              {event.fallback === true && <DetailRow label="Fallback" value="the primary backend refused" />}
              {event.retries != null && event.retries > 0 && (
                <DetailRow label="Retries" value={formatCount(event.retries)} />
              )}
              {event.row_count != null && <DetailRow label="Rows" value={formatCount(event.row_count)} />}
              {event.error_class && <DetailRow label="Error" value={event.error_class} />}

              {payload ? (
                <>
                  <span style={{ color: "var(--t4)", marginTop: 4 }}>Payload</span>
                  <pre style={{
                    margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere",
                    color: "var(--t2)", fontFamily: "var(--font-mono)",
                  }}>{payload}</pre>
                </>
              ) : (
                <span style={{ color: "var(--t4)", marginTop: 4 }}>
                  This row carries no payload.
                </span>
              )}

              {event.content_captured === false && (
                // Absence with a reason. "No prompt here" and "prompt capture was off"
                // call for different responses, and only one of them is a bug.
                <span style={{ color: "var(--t4)" }}>
                  Prompt content was not captured for this run (obs.prompt_capture was off).
                </span>
              )}
            </div>
          ) : (
            <span style={{ color: "var(--t4)" }}>
              No stored row matched this node, so there is nothing further to show.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { traceNode: NodeCard };

export function TraceFlow({
  timeline,
  edges,
  events = [],
}: {
  timeline: TraceTimeline;
  edges: TraceFlowEdge[];
  /** The trace's stored rows, so a node can show what it was built FROM. */
  events?: SessionEvent[];
}) {
  // One at a time. An expanded card overlays the row beneath it — the layout is a fixed
  // grid, so it cannot make room — and several open at once turns a readable canvas into
  // stacked panels. Opening one closes the last, which is also how a person reads a run.
  const [openId, setOpenId] = useState<string | null>(null);

  const { rfNodes, rfEdges, nested } = useMemo(() => {
    const forest = buildForest(timeline.nodes ?? [], edges ?? []);
    const pos = layoutForest(forest);
    const drawn = new Set(pos.keys());

    const rfNodes: RFNode[] = (timeline.nodes ?? [])
      .filter(n => drawn.has(n.id))
      .map(n => {
        const p = pos.get(n.id)!;
        const open = openId === n.id;
        return {
          id: n.id,
          type: "traceNode",
          position: { x: p.col * COL_W, y: p.row * ROW_H },
          data: {
            node: n,
            event: eventForNode(n, events),
            open,
            onToggle: () => setOpenId(cur => (cur === n.id ? null : n.id)),
          },
          draggable: true,
          // An open card has to sit above its neighbours, or the detail it exists to
          // show is drawn underneath the next node.
          zIndex: open ? 10 : 0,
        };
      });

    const rfEdges: RFEdge[] = (edges ?? [])
      .filter(e => drawn.has(e.from) && drawn.has(e.to))
      .map((e, i) => ({
        id: `${e.kind}-${i}-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        // The latency is rendered ON the edge — the detail that turns boxes-and-arrows
        // into a reading of where a run waited. Only `next` edges carry one: a child
        // runs INSIDE its parent, so a number there would be a duration posing as a wait.
        label: e.kind === "next" && e.latency_ms != null ? ms(e.latency_ms) : undefined,
        animated: false,
        style: {
          stroke: e.kind === "child" ? "var(--chart-4)" : "var(--b2)",
          strokeDasharray: e.kind === "child" ? "4 3" : undefined,
        },
        // No font-size here: an edge label is a style OBJECT, so it cannot take an
        // `aug-fs-*` class, and a raw literal is what the type scale exists to prevent.
        // The renderer's default is on-scale, so the honest move is to not set one.
        labelStyle: { fill: "var(--t3)" },
        labelBgStyle: { fill: "var(--bg-1)" },
        markerEnd: { type: MarkerType.ArrowClosed, color:
          e.kind === "child" ? "var(--chart-4)" : "var(--b2)" },
      }));

    return {
      rfNodes, rfEdges,
      nested: forest.some(n => n.children.length > 0),
    };
  }, [timeline.nodes, edges, events, openId]);

  if (!rfNodes.length) {
    return (
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        This run recorded no nodes to draw.
      </div>
    );
  }

  return (
    <div style={{ height: "100%", minHeight: 340, display: "flex", flexDirection: "column" }}>
      {!nested && (
        // Say it plainly rather than presenting a chain as a graph. A run that never
        // delegated genuinely has no structure to show, and the waterfall reads better.
        <div className="aug-fs-xs" style={{ color: "var(--t3)", paddingBottom: 6 }}>
          This run is a single sequence — nothing nested inside anything else. The
          Waterfall shows the same nodes against time.
        </div>
      )}
      <div style={{ flex: 1, minHeight: 300, border: "1px solid var(--border)",
                    borderRadius: "var(--r-chip)" }}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          fitView
          // Bounded, because an unbounded fit is not a view. A wide run fitted to the
          // container resolved to scale 0.2 — every card 7px tall and unreadable, which
          // is a picture of a run rather than a reading of one. Fit when the run is
          // small enough to fit legibly; otherwise stay legible and let the reader pan,
          // with fit-to-screen still one click away in the controls.
          fitViewOptions={{ minZoom: 0.55, maxZoom: 1, padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.2}
          maxZoom={1.6}
        >
          <Background gap={16} color="var(--border)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
