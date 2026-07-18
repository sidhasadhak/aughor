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
 * The cards are a small DASHBOARD: each shows a brief title, EXPANDS on click to reveal a short
 * summary (the full finding + why it matters + an Investigate action), and is freely DRAGGABLE and
 * RESIZEABLE (React Flow NodeResizer) — so the reader arranges the argument to fill the space.
 * Layout is hand-rolled and deterministic (longest-path-to-verdict layering) as a sensible START;
 * drags and resizes persist. Progressive disclosure starts at the verdict + top drivers so it
 * never opens as a hairball.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, ReactFlowProvider, Background, Controls, Handle, Position, MarkerType, NodeResizer,
  useNodesState, useEdgesState, useUpdateNodeInternals, useReactFlow,
  type Node, type Edge, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ChevronDown, ChevronUp } from "lucide-react";

import {
  fetchCardRelations,
  type ArgumentGraph as ArgumentGraphData, type ArgumentGraphNode,
  type ArgumentGraphEdge, type ArgumentEdgeType,
} from "@/lib/api";

// How many drivers the collapsed view shows before "Show all" (verdict + top-N by impact).
const COLLAPSED_DRIVERS = 4;
const ROW_GAP = 168;
const COL_GAP = 264;

// Initial card widths per node kind (px). Auto height; both persist once the user resizes.
const W_VERDICT = 268, W_FINDING = 236, W_CARD = 212;

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
  relates_to:    { color: "var(--vio4)",  label: "pinned card" },
  related:       { color: "var(--t4)",    label: "related" },
};

const COMPOSITION_TONE: Record<string, string> = {
  chain: "var(--blue4)", tension: "var(--amb4)", confound: "var(--red4)",
  concentration: "var(--vio4)", share: "var(--grn4)",
};

// Human phrasing for the composition type, shown in a card's expanded summary.
const COMPOSITION_PHRASE: Record<string, string> = {
  chain: "Chained — this drives a downstream finding.",
  tension: "In tension with another finding (a trade-off).",
  confound: "May confound the headline read.",
  concentration: "A concentration / roll-up of finer parts.",
  share: "Shares an entity or join key with another finding.",
};

/** A short, brief title for the collapsed card — the full finding rides in the expand. */
function shortLabel(s: string, n = 82): string {
  const t = (s || "").replace(/\s+/g, " ").trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, n);
  const sp = cut.lastIndexOf(" ");
  return (sp > n * 0.6 ? cut.slice(0, sp) : cut).trimEnd() + "…";
}

// ── Custom nodes ─────────────────────────────────────────────────────────────

// React Flow v12 requires node data to satisfy Record<string, unknown>; the imported
// ArgumentGraphNode is an interface (no implicit index signature), so intersect one in.
type FindingNodeData = ArgumentGraphNode & {
  expanded?: boolean; onToggle?: () => void; onOpen?: () => void;
} & Record<string, unknown>;

// Subtle NodeResizer chrome shared by every card (visible only while a node is selected).
const RESIZER = {
  color: "var(--blue4)",
  handleStyle: { width: 7, height: 7, borderRadius: 2, background: "var(--bg-2)", border: "1.5px solid var(--blue4)" },
  lineStyle: { borderColor: "color-mix(in srgb, var(--blue4) 45%, transparent)" },
};

function VerdictNode({ data, selected }: NodeProps<Node<{ title: string }>>) {
  return (
    <div style={{
      width: "100%", height: "100%", boxSizing: "border-box",
      padding: "10px 14px", borderRadius: "var(--r3)",
      background: "color-mix(in srgb, var(--blue4) 12%, var(--bg-2))",
      border: "1px solid color-mix(in srgb, var(--blue4) 40%, var(--b1))",
      boxShadow: "0 0 0 1px color-mix(in srgb, var(--blue4) 20%, transparent)",
      overflow: "hidden",
    }}>
      <NodeResizer isVisible={selected} minWidth={190} minHeight={54} {...RESIZER} />
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--blue4)", marginBottom: 3 }}>
        Verdict
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.35, color: "var(--t1)" }}>{data.title}</div>
      {/* Verdict is the sink: evidence connects into its bottom. */}
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

function FindingNode({ id, data, selected }: NodeProps<Node<FindingNodeData>>) {
  const tone = data.composition_type ? (COMPOSITION_TONE[data.composition_type] ?? "var(--b2)") : null;
  const expanded = !!data.expanded;
  const upd = useUpdateNodeInternals();
  // Handles sit at top/bottom; re-measure after an expand so edges stay pinned to the card.
  useEffect(() => { upd(id); }, [expanded, id, upd]);

  return (
    <div
      onClick={data.onToggle}
      title={expanded ? "Collapse" : "Expand — read the finding and why it matters"}
      style={{
        width: "100%", height: "100%", boxSizing: "border-box",
        padding: "8px 11px", borderRadius: "var(--r3)",
        background: "var(--bg-2)",
        border: `1px solid ${data.cited ? "var(--blue4)" : "var(--b1)"}`,
        borderLeft: tone ? `3px solid ${tone}` : undefined,
        cursor: "pointer", opacity: data.plausibility ? 0.72 : 1,
        display: "flex", flexDirection: "column", gap: 4, overflow: "hidden",
      }}
    >
      <NodeResizer isVisible={selected} minWidth={170} minHeight={52} {...RESIZER} />
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--t4)" }}>
          {data.domain || "—"}
        </span>
        {data.composition_type && (
          <span style={{ fontSize: 8.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: tone ?? "var(--t3)" }}>
            {data.composition_type}
          </span>
        )}
        {data.cited && <span title="Cited by the verdict" style={{ fontSize: 9, color: "var(--blue4)" }}>◆</span>}
        {/* Expand affordance — always visible so the card reads as expandable at a glance. */}
        <span style={{ marginLeft: "auto", color: "var(--t4)", display: "inline-flex" }}>
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </div>

      {/* Title — brief when collapsed (clamped), full when expanded. */}
      <div style={{
        fontSize: 11, lineHeight: 1.4, color: "var(--t1)",
        ...(expanded ? {} : { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as const, overflow: "hidden" }),
      }}>
        {expanded ? data.title : shortLabel(data.title)}
      </div>

      {/* Summary — the "know more" layer, revealed on expand. */}
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 2, paddingTop: 6, borderTop: "1px solid var(--b1)" }}>
          {data.angle && (
            <div style={{ fontSize: 10, color: "var(--t3)" }}>
              <span style={{ color: "var(--t4)" }}>Angle · </span>{data.angle}
            </div>
          )}
          {/* Impact strength bar (impact is a 0–1 ranking score). */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".04em" }}>Impact</span>
            <span style={{ flex: 1, height: 4, borderRadius: "var(--r-pill)", background: "var(--bg-4)", overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", width: `${Math.min(100, Math.max(6, data.impact * 100))}%`, background: tone ?? "var(--blue4)" }} />
            </span>
          </div>
          {data.composition_type && COMPOSITION_PHRASE[data.composition_type] && (
            <div style={{ fontSize: 10, color: tone ?? "var(--t3)" }}>{COMPOSITION_PHRASE[data.composition_type]}</div>
          )}
          {data.plausibility && (
            <div style={{ fontSize: 10, color: "var(--amb4)" }}>⚠ Trust gate: {data.plausibility}</div>
          )}
          {data.has_sql && data.onOpen && (
            <button
              onClick={(e) => { e.stopPropagation(); data.onOpen!(); }}
              style={{
                alignSelf: "flex-start", marginTop: 1, fontSize: 10.5, fontWeight: 600,
                color: "var(--blue4)", background: "transparent", border: "none", padding: 0, cursor: "pointer",
              }}
            >
              Investigate this finding →
            </button>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Top} style={{ opacity: 0 }} />
    </div>
  );
}

// A user-pinned cockpit card, visually distinct from AI findings (violet, "PINNED" chip) so a
// human artefact never reads as a machine finding. It relates UP to the finding(s) it explains.
function CardNode({ data, selected }: NodeProps<Node<{ title: string }>>) {
  return (
    <div style={{
      width: "100%", height: "100%", boxSizing: "border-box",
      padding: "8px 11px", borderRadius: "var(--r3)",
      background: "color-mix(in srgb, var(--vio4) 10%, var(--bg-2))",
      border: "1px dashed color-mix(in srgb, var(--vio4) 45%, var(--b1))",
      overflow: "hidden",
    }}>
      <NodeResizer isVisible={selected} minWidth={150} minHeight={48} {...RESIZER} />
      <Handle type="source" position={Position.Top} style={{ opacity: 0 }} />
      <div style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--vio4)", marginBottom: 3 }}>
        ◆ Pinned card
      </div>
      <div style={{ fontSize: 10.5, lineHeight: 1.4, color: "var(--t2)",
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {data.title}
      </div>
    </div>
  );
}

const nodeTypes = { verdict: VerdictNode, finding: FindingNode, card: CardNode };

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

function ArgumentGraphInner({ graph, connectionId, schema, onOpenFinding }: {
  graph: ArgumentGraphData;
  connectionId: string;
  schema?: string;
  /** Investigate the finding behind a node (reuses the briefing's pull-the-thread handler). */
  onOpenFinding: (insightId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpand = useCallback((nid: string) => {
    setExpanded(prev => {
      const n = new Set(prev);
      if (n.has(nid)) n.delete(nid); else n.add(nid);
      return n;
    });
  }, []);

  // Live card↔finding relations (Slice 4) — fetched, not cached with the brief, so a card pinned
  // this session wires into the graph immediately. Best-effort: a failure just omits card nodes.
  const [cardRel, setCardRel] = useState<{ nodes: ArgumentGraphNode[]; edges: ArgumentGraphEdge[] }>({ nodes: [], edges: [] });

  useEffect(() => {
    const findingIds = graph.nodes.filter(n => n.kind === "finding").map(n => n.id);
    if (!connectionId || !findingIds.length) { setCardRel({ nodes: [], edges: [] }); return; }
    let cancelled = false;
    fetchCardRelations(connectionId, { schema, findingIds })
      .then(r => { if (!cancelled) setCardRel(r); })
      .catch(() => { if (!cancelled) setCardRel({ nodes: [], edges: [] }); });
    return () => { cancelled = true; };
  }, [connectionId, schema, graph.nodes]);

  // The brief's finding graph + the live card relations, as one node/edge set.
  const allNodes = useMemo(() => [...graph.nodes, ...cardRel.nodes], [graph.nodes, cardRel.nodes]);
  const allEdges = useMemo(() => [...graph.edges, ...cardRel.edges], [graph.edges, cardRel.edges]);

  const drivers = useMemo(
    () => allNodes.filter(n => n.kind === "finding" && n.is_driver).sort((a, b) => b.impact - a.impact),
    [allNodes],
  );
  const hiddenCount = Math.max(0, allNodes.length - 1 - Math.min(drivers.length, COLLAPSED_DRIVERS));

  // Desired node/edge set from the graph data — the deterministic START layout (positions), the
  // fresh per-node handlers, and the visible edge set. Reconciled into RF state below so user
  // drags/resizes/selection persist across data changes.
  const { desiredNodes, desiredEdges, usedTypes } = useMemo(() => {
    const verdict = allNodes.find(n => n.kind === "verdict");
    const visible = new Set<string>();
    if (showAll) {
      allNodes.forEach(n => visible.add(n.id));
    } else {
      if (verdict) visible.add(verdict.id);
      drivers.slice(0, COLLAPSED_DRIVERS).forEach(n => visible.add(n.id));
    }
    const vNodes = allNodes.filter(n => visible.has(n.id));
    const vEdges = allEdges.filter(e => visible.has(e.source) && visible.has(e.target));

    // `related` is a lateral sibling link (driver↔driver) — exclude it from the hierarchy so it
    // can't push a driver into a lower row; every other edge type points evidence→claim.
    const rows = layoutRows(vNodes, vEdges.filter(e => e.type !== "related"));
    const byRow = new Map<number, ArgumentGraphNode[]>();
    vNodes.forEach(n => { const r = rows.get(n.id) ?? 1; const a = byRow.get(r) ?? []; a.push(n); byRow.set(r, a); });

    const pos = new Map<string, { x: number; y: number }>();
    [...byRow.entries()].forEach(([r, ns]) => {
      ns.sort((a, b) => b.impact - a.impact);
      const width = (ns.length - 1) * COL_GAP;
      ns.forEach((n, i) => pos.set(n.id, { x: i * COL_GAP - width / 2, y: r * ROW_GAP }));
    });

    const desiredNodes: Node[] = vNodes.map(n => ({
      id: n.id,
      type: n.kind === "verdict" ? "verdict" : n.kind === "card" ? "card" : "finding",
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      width: n.kind === "verdict" ? W_VERDICT : n.kind === "card" ? W_CARD : W_FINDING,
      data: (n.kind === "verdict" || n.kind === "card")
        ? { title: n.title }
        : { ...n, expanded: expanded.has(n.id), onToggle: () => toggleExpand(n.id), onOpen: n.has_sql ? () => onOpenFinding(n.id) : undefined },
      draggable: true,
    }));

    const desiredEdges: Edge[] = vEdges.map((e, i) => {
      const st = EDGE_STYLE[e.type] ?? EDGE_STYLE.supports;
      const faint = e.type === "supports";
      const lateral = e.type === "related";         // structural sibling link — quiet, symmetric
      const dashed = e.type === "relates_to" || lateral;   // human/structural ties read as dashed
      return {
        id: `e${i}`,
        source: e.source,
        target: e.target,
        type: "default",
        label: (e.label || st.label) || undefined,   // a `related` edge shows its shared join key
        labelStyle: { fill: st.color, fontSize: 9, fontWeight: 600 },
        labelBgStyle: { fill: "var(--bg-0)" },
        style: {
          stroke: st.color, strokeWidth: (faint || lateral) ? 1 : 1.5,
          opacity: (faint || lateral) ? 0.4 : 0.9,
          strokeDasharray: dashed ? "5 4" : undefined,
        },
        // `related` is symmetric — no arrowhead; everything else points evidence→claim.
        markerEnd: lateral ? undefined : { type: MarkerType.ArrowClosed, color: st.color, width: 14, height: 14 },
        animated: !faint && !dashed,
      };
    });

    const usedTypes = [...new Set(vEdges.map(e => e.type))].filter(t => t !== "supports");
    return { desiredNodes, desiredEdges, usedTypes };
  }, [allNodes, allEdges, drivers, showAll, expanded, toggleExpand, onOpenFinding]);

  // RF-owned state so drags + NodeResizer changes persist. SEEDED with the initial layout so
  // React Flow's built-in `fitView` frames real (measured) nodes on init — not an empty graph.
  // The reconcile effect below then keeps it in sync, KEEPING each surviving node's user
  // position / size / selection (only data + type refresh).
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>(desiredNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>(desiredEdges);

  useEffect(() => {
    setRfNodes(prev => {
      const byId = new Map(prev.map(n => [n.id, n]));
      return desiredNodes.map(d => {
        const p = byId.get(d.id);
        return p
          ? { ...d, position: p.position, width: p.width, height: p.height, selected: p.selected }
          : d;
      });
    });
  }, [desiredNodes, setRfNodes]);

  useEffect(() => { setRfEdges(desiredEdges); }, [desiredEdges, setRfEdges]);

  // The initial frame comes from <ReactFlow fitView> over the SEEDED nodes. When the visible set
  // changes (Show all ⇄ key drivers, or relations arriving) we re-fit so the new cards are packed
  // into view — skipping the first mount so we don't clobber the built-in init fit.
  const { fitView } = useReactFlow();
  const visibleCount = rfNodes.length;
  const didMount = useRef(false);
  useEffect(() => {
    if (!didMount.current) { didMount.current = true; return; }
    const t = setTimeout(() => fitView({ padding: 0.16, duration: 240 }), 90);
    return () => clearTimeout(t);
  }, [visibleCount, showAll, fitView]);

  if (!graph.nodes.length) {
    return (
      <div style={{ padding: "24px", textAlign: "center", fontSize: 12, color: "var(--t3)" }}>
        No argument structure yet — generate the brief first.
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <div className="aug-label">Argument graph</div>
        <span style={{ fontSize: 9.5, color: "var(--t4)" }}>click a card to expand · drag to arrange · select to resize</span>
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
      <div style={{ height: 540, borderRadius: "var(--r3)", border: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden" }}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.3}
          maxZoom={1.5}
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

// useReactFlow (for fitView) must run inside a provider; <ReactFlow> only provides it to its
// own children, so wrap the whole surface in one.
export function ArgumentGraph(props: {
  graph: ArgumentGraphData;
  connectionId: string;
  schema?: string;
  onOpenFinding: (insightId: string) => void;
}) {
  return (
    <ReactFlowProvider>
      <ArgumentGraphInner {...props} />
    </ReactFlowProvider>
  );
}

export default ArgumentGraph;
