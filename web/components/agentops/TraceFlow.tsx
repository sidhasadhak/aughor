"use client";

/**
 * VA-5 · the node view — one run drawn as the graph it actually is.
 *
 * **Why this is not the waterfall.** The waterfall answers "where did the time go",
 * laying every node on one axis. It cannot answer "what ran under what", because a time
 * axis flattens nesting by construction: a delegate's work and its supervisor's occupy
 * the same stretch of wall clock and end up side by side. This view answers the second
 * question and gives up the first.
 *
 * **Why it can exist now.** Until delegation shipped, a trace had almost no real
 * parentage — which is why `flow_edges` originally returned `zip(nodes, nodes[1:])`.
 * Rendering that as a graph would have drawn a straight line and called it one. The
 * edges are structural now, so there is something to draw.
 *
 * **Why no canvas library.** A run DAG is a forest: root nodes in sequence, children
 * nested under a parent. That is a tree with an ordering, and a tree renders as nested
 * DOM — which stays selectable, searchable and readable to a screen reader, the same
 * reasoning the waterfall's positioned divs were built on. Reaching for a graph canvas
 * would add a dependency and take all of that away to draw a shape the document model
 * already expresses. (The refusal recorded against a node CANVAS was about authoring
 * agents; this is a read-only view of a run that happened. Different question — but the
 * dependency answer lands the same way.)
 *
 * The latency between consecutive root nodes is rendered ON the connector, because that
 * number is what turns boxes-and-arrows into a reading of where a run waited.
 */
import { useMemo } from "react";

import type { TimelineNode, TraceFlowEdge, TraceTimeline } from "@/lib/api";
import { formatCount } from "@/lib/format";

const KIND_COLOR: Record<string, string> = {
  model: "var(--chart-1)",
  tool: "var(--chart-2)",
  frame: "var(--chart-3)",
  error: "var(--red4)",
  event: "var(--chart-6)",
  delegation: "var(--chart-4)",
};

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
 * A cycle would otherwise recurse forever, so a node already placed is never placed
 * again — malformed data should render short, not hang the panel.
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

function NodeCard({ node, depth }: { node: FlowNode; depth: number }) {
  const color = KIND_COLOR[node.kind] ?? "var(--chart-6)";
  const u = node.usage;
  const failed = node.ok === false;

  return (
    <div style={{ marginLeft: depth === 0 ? 0 : 20 }}>
      <div
        className="aug-fs-ui"
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "6px 10px", marginBottom: 4,
          borderLeft: `2px solid ${failed ? "var(--red4)" : color}`,
          background: "var(--bg-2)", borderRadius: "var(--r-chip)",
        }}
      >
        <span style={{ color: "var(--t1)", fontWeight: 500 }}>{node.name}</span>

        {node.delegation && (
          // The hop's own identity. `path` is the value the runtime refuses cycles on,
          // so what is drawn here and what was refused there cannot disagree.
          <span
            title={`delegation path: ${node.delegation.path}`}
            style={{
              color: "var(--chart-4)", border: "1px solid var(--chart-4)",
              borderRadius: "var(--r-pill)", padding: "0 6px",
            }}
          >
            {node.delegation.agent_name}
            {node.delegation.depth != null && ` · d${node.delegation.depth}`}
          </span>
        )}

        <span style={{ color: "var(--t3)", marginLeft: "auto" }}>{ms(node.duration_ms)}</span>

        {u && u.total_tokens != null && (
          // §6.1's per-node usage block: prompt / completion / total.
          <span
            style={{ color: "var(--t4)" }}
            title={`prompt ${u.prompt_tokens ?? "—"} · completion ${u.completion_tokens ?? "—"}`}
          >
            {formatCount(u.total_tokens)} tok
          </span>
        )}

        {failed && <span style={{ color: "var(--red4)" }}>{node.error_class || "failed"}</span>}
      </div>

      {node.children.map(c => <NodeCard key={c.id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export function TraceFlow({
  timeline,
  edges,
}: {
  timeline: TraceTimeline;
  edges: TraceFlowEdge[];
}) {
  const forest = useMemo(
    () => buildForest(timeline.nodes ?? [], edges ?? []),
    [timeline.nodes, edges],
  );
  // Latency belongs to the edge INTO a node, keyed by its target.
  const gapInto = useMemo(() => {
    const m = new Map<string, number | null>();
    for (const e of edges ?? []) if (e.kind === "next") m.set(e.to, e.latency_ms);
    return m;
  }, [edges]);

  if (!forest.length) {
    return (
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        This run recorded no nodes to draw.
      </div>
    );
  }

  const nested = forest.some(n => n.children.length > 0);

  return (
    <div>
      {!nested && (
        // Say it plainly rather than presenting a chain as a graph. A run that never
        // delegated genuinely has no structure to show, and the waterfall reads better.
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 8 }}>
          This run is a single sequence — nothing nested inside anything else. The
          Waterfall shows the same nodes against time.
        </div>
      )}
      {forest.map((n, i) => {
        const gap = i === 0 ? null : gapInto.get(n.id);
        return (
          <div key={n.id}>
            {i > 0 && (
              <div
                className="aug-fs-xs"
                style={{ color: "var(--t4)", padding: "1px 0 3px 10px" }}
              >
                ↓ {gap == null ? "—" : ms(gap)}
              </div>
            )}
            <NodeCard node={n} depth={0} />
          </div>
        );
      })}
    </div>
  );
}
