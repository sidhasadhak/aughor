"use client";

/**
 * ArgumentGraph — the briefing's narrative layer as a node+edge lens (Slice 3 of the
 * briefing-cockpit initiative). Renders the deterministic {nodes, edges} the backend builds
 * from the impact-ranked drivers + the explorer's OWN typed edges (composition / drill).
 *
 * It is a LENS, not a replacement: the linear brief stays the default. The verdict is the apex;
 * every driver `supports` it; typed edges (chain/tension/confound/concentration/share) connect a
 * synthesis to its parent findings, and `explains_why` links a drill to the finding it explains.
 *
 * Layout is hand-rolled and deterministic (longest-path-to-verdict layering) — React Flow has no
 * auto-layout. Progressive disclosure starts at the verdict + top drivers so it never opens as a
 * hairball. A node click "pulls the thread" into an inline investigation (reusing the drill wiring).
 */
import { useMemo, useState } from "react";
import {
  ReactFlow, Background, Controls, Handle, Position, MarkerType,
  type Node, type Edge, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { ArgumentGraph as ArgumentGraphData, ArgumentGraphNode, ArgumentEdgeType } from "@/lib/api";

// How many drivers the collapsed view shows before "Show all" (verdict + top-N by impact).
const COLLAPSED_DRIVERS = 4;
const ROW_GAP = 140;
const COL_GAP = 270;

// Edge vocabulary → colour + short verb, so the relationship reads at a glance. Keyed to the
// backend ArgumentEdgeType union; every value uses a design token (no raw hex in the app).
const EDGE_STYLE: Record<ArgumentEdgeType, { color: string; label: string }> = {
  supports:      { color: "var(--b2)",    label: "" },
  chain:         { color: "var(--blue4)", label: "drives" },
  tension:       { color: "var(--amb4)",  label: "tension" },
  confound:      { color: "var(--red4)",  label: "confounds" },
  concentration: { color: "var(--vio4)",  label: "concentrates" },
  share:         { color: "var(--grn4)",  label: "shares" },
  explains_why:  { color: "var(--grn4)",  label: "explains" },
};

// ── Custom nodes ─────────────────────────────────────────────────────────────

// React Flow v12 requires node data to satisfy Record<string, unknown>; the imported
// ArgumentGraphNode is an interface (no implicit index signature), so intersect one in.
type FindingNodeData = ArgumentGraphNode & { onOpen?: () => void } & Record<string, unknown>;

function VerdictNode({ data }: NodeProps<Node<{ title: string }>>) {
  return (
    <div style={{
      maxWidth: 300, padding: "10px 14px", borderRadius: "var(--r3)",
      background: "color-mix(in srgb, var(--blue4) 12%, var(--bg-2))",
      border: "1px solid color-mix(in srgb, var(--blue4) 40%, var(--b1))",
      boxShadow: "0 0 0 1px color-mix(in srgb, var(--blue4) 20%, transparent)",
    }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--blue4)", marginBottom: 3 }}>
        Verdict
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.35, color: "var(--t1)" }}>{data.title}</div>
      {/* Verdict is the sink: evidence connects into its bottom. */}
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const COMPOSITION_TONE: Record<string, string> = {
  chain: "var(--blue4)", tension: "var(--amb4)", confound: "var(--red4)",
  concentration: "var(--vio4)", share: "var(--grn4)",
};

function FindingNode({ data }: NodeProps<Node<FindingNodeData>>) {
  const tone = data.composition_type ? (COMPOSITION_TONE[data.composition_type] ?? "var(--b2)") : null;
  return (
    <div
      onClick={data.onOpen}
      title={data.has_sql ? "Pull the thread — investigate this finding in place" : undefined}
      style={{
        width: 232, padding: "8px 11px", borderRadius: "var(--r3)",
        background: "var(--bg-2)",
        border: `1px solid ${data.cited ? "var(--blue4)" : "var(--b1)"}`,
        borderLeft: tone ? `3px solid ${tone}` : undefined,
        cursor: data.has_sql ? "pointer" : "default", opacity: data.plausibility ? 0.7 : 1,
      }}
    >
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
        <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--t4)" }}>
          {data.domain || "—"}
        </span>
        {data.composition_type && (
          <span style={{ fontSize: 8.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: tone ?? "var(--t3)" }}>
            {data.composition_type}
          </span>
        )}
        {data.cited && <span title="Cited by the verdict" style={{ fontSize: 9, color: "var(--blue4)" }}>◆</span>}
      </div>
      <div style={{ fontSize: 11, lineHeight: 1.4, color: "var(--t1)",
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {data.title}
      </div>
      <Handle type="source" position={Position.Top} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { verdict: VerdictNode, finding: FindingNode };

// ── Layout ───────────────────────────────────────────────────────────────────

/** Longest-path-to-verdict layering: verdict = row 0, its supporters row 1, their evidence row 2,
 *  … Deterministic and cycle-guarded. Returns a row index per visible node id. */
function layoutRows(nodes: ArgumentGraphNode[], edges: { source: string; target: string }[]): Map<string, number> {
  const verdictId = nodes.find(n => n.kind === "verdict")?.id;
  const outs = new Map<string, string[]>();
  edges.forEach(e => { const a = outs.get(e.source) ?? []; a.push(e.target); outs.set(e.source, a); });
  const cache = new Map<string, number>();
  const stack = new Set<string>();
  const row = (id: string): number => {
    if (id === verdictId) return 0;
    const c = cache.get(id); if (c != null) return c;
    if (stack.has(id)) return 1;                       // cycle guard (shouldn't happen on a DAG)
    stack.add(id);
    const t = outs.get(id) ?? [];
    const r = t.length ? 1 + Math.max(...t.map(row)) : 1;
    stack.delete(id); cache.set(id, r);
    return r;
  };
  const rows = new Map<string, number>();
  nodes.forEach(n => rows.set(n.id, row(n.id)));
  return rows;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ArgumentGraph({ graph, onOpenFinding }: {
  graph: ArgumentGraphData;
  /** Investigate the finding behind a node (reuses the briefing's pull-the-thread handler). */
  onOpenFinding: (insightId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);

  const drivers = useMemo(
    () => graph.nodes.filter(n => n.kind === "finding" && n.is_driver).sort((a, b) => b.impact - a.impact),
    [graph.nodes],
  );
  const hiddenCount = Math.max(0, graph.nodes.length - 1 - Math.min(drivers.length, COLLAPSED_DRIVERS));

  const { rfNodes, rfEdges } = useMemo(() => {
    const verdict = graph.nodes.find(n => n.kind === "verdict");
    const visible = new Set<string>();
    if (showAll) {
      graph.nodes.forEach(n => visible.add(n.id));
    } else {
      if (verdict) visible.add(verdict.id);
      drivers.slice(0, COLLAPSED_DRIVERS).forEach(n => visible.add(n.id));
    }
    const vNodes = graph.nodes.filter(n => visible.has(n.id));
    const vEdges = graph.edges.filter(e => visible.has(e.source) && visible.has(e.target));

    const rows = layoutRows(vNodes, vEdges);
    const byRow = new Map<number, ArgumentGraphNode[]>();
    vNodes.forEach(n => { const r = rows.get(n.id) ?? 1; const a = byRow.get(r) ?? []; a.push(n); byRow.set(r, a); });

    const pos = new Map<string, { x: number; y: number }>();
    [...byRow.entries()].forEach(([r, ns]) => {
      ns.sort((a, b) => b.impact - a.impact);
      const width = (ns.length - 1) * COL_GAP;
      ns.forEach((n, i) => pos.set(n.id, { x: i * COL_GAP - width / 2, y: r * ROW_GAP }));
    });

    const rfNodes: Node[] = vNodes.map(n => ({
      id: n.id,
      type: n.kind === "verdict" ? "verdict" : "finding",
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: n.kind === "verdict"
        ? { title: n.title }
        : { ...n, onOpen: n.has_sql ? () => onOpenFinding(n.id) : undefined },
      draggable: true,
    }));

    const rfEdges: Edge[] = vEdges.map((e, i) => {
      const st = EDGE_STYLE[e.type] ?? EDGE_STYLE.supports;
      const faint = e.type === "supports";
      return {
        id: `e${i}`,
        source: e.source,
        target: e.target,
        type: "default",
        label: st.label || undefined,
        labelStyle: { fill: st.color, fontSize: 9, fontWeight: 600 },
        labelBgStyle: { fill: "var(--bg-0)" },
        style: { stroke: st.color, strokeWidth: faint ? 1 : 1.5, opacity: faint ? 0.45 : 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, color: st.color, width: 14, height: 14 },
        animated: !faint,
      };
    });

    return { rfNodes, rfEdges };
  }, [graph, drivers, showAll, onOpenFinding]);

  if (!graph.nodes.length) {
    return (
      <div style={{ padding: "24px", textAlign: "center", fontSize: 12, color: "var(--t3)" }}>
        No argument structure yet — generate the brief first.
      </div>
    );
  }

  const usedTypes = Array.from(new Set(rfEdges.length ? graph.edges.map(e => e.type) : []))
    .filter(t => t !== "supports");

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div className="aug-label">Argument graph</div>
        {/* Edge legend — only the typed (non-supports) relationships actually present. */}
        {usedTypes.map(t => (
          <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 9.5, color: "var(--t3)" }}>
            <span style={{ width: 12, height: 0, borderTop: `2px solid ${EDGE_STYLE[t].color}` }} />
            {EDGE_STYLE[t].label || t}
          </span>
        ))}
        {hiddenCount > 0 && (
          <button
            onClick={() => setShowAll(v => !v)}
            style={{
              marginLeft: "auto", fontSize: 10.5, padding: "3px 9px", borderRadius: "var(--r2)",
              background: "var(--bg-2)", border: "1px solid var(--b1)", color: "var(--t3)", cursor: "pointer",
            }}
          >
            {showAll ? "Show key drivers" : `Show all (${graph.nodes.length - 1} findings)`}
          </button>
        )}
      </div>
      <div style={{ height: 460, borderRadius: "var(--r3)", border: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden" }}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.3}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          edgesFocusable={false}
        >
          <Background color="var(--b1)" gap={22} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}

export default ArgumentGraph;
