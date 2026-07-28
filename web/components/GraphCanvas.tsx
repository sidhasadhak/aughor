"use client";
/**
 * The knowledge graph as an actual GRAPH — nodes and edges on a pannable canvas.
 *
 * Until now the Graph tab rendered cards: domains → tables → detail. That surface is the
 * anti-hairball drill-down (Wave C4) and it stays — but nothing LOOKED like a graph, which
 * undersells that the thing on disk genuinely is one. This view renders it with
 * `@xyflow/react`, which had been sitting in package.json with zero consumers.
 *
 * Two decisions carried over from the C4 design rather than re-litigated:
 *
 * - **Progressive disclosure, not a hairball.** The default canvas shows domains, tables,
 *   metrics and briefs (~30 nodes). Findings (100) and glossary terms (255) are one toggle
 *   away, counted on the toggle so the reader knows what they are asking for. Rendering all
 *   ~380 nodes at once is exactly the "massive noisy diary" view C4 exists to avoid.
 * - **Deterministic layout, no physics.** Nodes cluster radially around their domain's
 *   angle: domains inner ring, tables around their domain, metrics/briefs outside the
 *   tables they derive from, findings/terms fanned around the table they ground in. A force
 *   simulation would add runtime cost and — worse — put nodes somewhere DIFFERENT on every
 *   visit; a stable layout lets a returning reader keep their spatial memory of their own
 *   data.
 */
import React, { useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CGEdge, CGNode, ConnectionGraph } from "@/lib/api";

// One hue per node kind — matched to the app's dark surface, readable in both themes.
const KIND_COLOR: Record<string, { bg: string; border: string; text: string }> = {
  domain:        { bg: "rgba(100,116,139,0.18)", border: "#64748b", text: "var(--t1, #e2e8f0)" },
  table:         { bg: "rgba(37,99,235,0.16)",   border: "#3b82f6", text: "var(--t1, #e2e8f0)" },
  metric:        { bg: "rgba(124,58,237,0.16)",  border: "#8b5cf6", text: "var(--t1, #e2e8f0)" },
  brief:         { bg: "rgba(22,163,74,0.16)",   border: "#22c55e", text: "var(--t1, #e2e8f0)" },
  finding:       { bg: "rgba(234,88,12,0.14)",   border: "#f97316", text: "var(--t1, #e2e8f0)" },
  glossary_term: { bg: "rgba(8,145,178,0.14)",   border: "#06b6d4", text: "var(--t1, #e2e8f0)" },
};

const EDGE_COLOR: Record<string, string> = {
  joins_on: "#3b82f6",
  derived_from: "#8b5cf6",
  grounded_in: "#f97316",
  defines: "#06b6d4",
  resolves: "#64748b",
};

const TWO_PI = Math.PI * 2;

function bare(t: string): string {
  return String(t).split(".").pop()!.trim().replace(/"/g, "").toLowerCase();
}

interface Props {
  graph: ConnectionGraph;
  onOpenTable?: (tableId: string) => void;
}

export function GraphCanvas({ graph, onOpenTable }: Props) {
  const [showFindings, setShowFindings] = useState(false);
  const [showTerms, setShowTerms] = useState(false);

  const { nodes, edges, hiddenCounts } = useMemo(() => {
    const all = Object.values(graph.nodes) as CGNode[];
    const allEdges = Object.values(graph.edges) as CGEdge[];
    const byId = new Map(all.map((n) => [n.id, n]));

    const domains = all.filter((n) => n.kind === "domain")
      .sort((a, b) => a.label.localeCompare(b.label));
    const tables = all.filter((n) => n.kind === "table");
    const cx = 0, cy = 0;

    // Angle per domain, then tables inherit their domain's bearing.
    const domainAngle = new Map<string, number>();
    domains.forEach((d, i) => domainAngle.set(d.label, (TWO_PI * i) / Math.max(1, domains.length)));
    const angleOfTable = new Map<string, number>();
    const pos = new Map<string, { x: number; y: number }>();

    domains.forEach((d) => {
      const a = domainAngle.get(d.label)!;
      pos.set(d.id, { x: cx + 220 * Math.cos(a), y: cy + 220 * Math.sin(a) });
    });

    const grouped = new Map<string, CGNode[]>();
    tables.forEach((t) => {
      const dom = (t.data.domain as string) || "Ungrouped";
      (grouped.get(dom) ?? grouped.set(dom, []).get(dom)!).push(t);
    });
    for (const [dom, members] of grouped) {
      const base = domainAngle.get(dom) ?? -Math.PI / 2;
      const arc = Math.min(TWO_PI / Math.max(1, grouped.size), Math.PI / 2.2) * 0.9;
      members.sort((a, b) => a.label.localeCompare(b.label)).forEach((t, i) => {
        const a = base + (members.length === 1 ? 0 : arc * (i / (members.length - 1) - 0.5));
        angleOfTable.set(t.id, a);
        pos.set(t.id, { x: cx + 480 * Math.cos(a), y: cy + 480 * Math.sin(a) });
      });
    }

    // Metrics + briefs sit outside the tables they derive from.
    const derivedTargets = (id: string) =>
      allEdges.filter((e) => e.kind === "derived_from" && e.from_id === id).map((e) => e.to_id);
    all.filter((n) => n.kind === "metric" || n.kind === "brief").forEach((n, i) => {
      const targets = derivedTargets(n.id).map((t) => angleOfTable.get(t)).filter((a): a is number => a !== undefined);
      const a = targets.length
        ? targets.reduce((s, v) => s + v, 0) / targets.length
        : -Math.PI / 2 + i * 0.5;
      pos.set(n.id, { x: cx + 700 * Math.cos(a), y: cy + 700 * Math.sin(a) });
    });

    // Findings fan around the table they ground in; terms around the table they define.
    const groundOf = new Map<string, string>();
    allEdges.filter((e) => e.kind === "grounded_in").forEach((e) => {
      if (!groundOf.has(e.from_id)) groundOf.set(e.from_id, e.to_id);
    });
    const tableByBare = new Map(tables.map((t) => [bare(t.label), t.id]));

    const fanned = new Map<string, number>();
    const fan = (anchorId: string | undefined, ring: number, fallbackIdx: number) => {
      const a0 = (anchorId && angleOfTable.get(anchorId)) ?? (TWO_PI * fallbackIdx) / 40;
      const k = `${anchorId ?? "?"}:${ring}`;
      const n = fanned.get(k) ?? 0;
      fanned.set(k, n + 1);
      const a = a0 + ((n % 11) - 5) * 0.075 + Math.floor(n / 11) * 0.03;
      const r = ring + Math.floor(n / 11) * 110;
      return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
    };

    const findings = showFindings ? all.filter((n) => n.kind === "finding") : [];
    findings.forEach((n, i) => pos.set(n.id, fan(groundOf.get(n.id), 900, i)));
    const terms = showTerms ? all.filter((n) => n.kind === "glossary_term") : [];
    terms.forEach((n, i) => pos.set(n.id, fan(tableByBare.get(bare((n.data.table as string) || "")), 1180, i)));

    // Deterministic collision pass. Two metrics deriving from the same table, or two
    // tables on adjacent domain arcs, otherwise stack pixel-perfectly ("Revenue" under
    // "AOV" on the first live render). The cell is RECTANGULAR and sized to the node
    // BOX, not a point — the first version used a 46px square grid and the labels,
    // 80–140px wide, still overlapped from neighbouring cells. Colliders spiral in
    // small angle+radius steps rather than pushing along one bearing, which had kept
    // same-angle stacks stacked; sorted ids keep the outcome stable across visits.
    const CELL_X = 170;
    const CELL_Y = 46;
    const taken = new Set<string>();
    const cellOf = (p: { x: number; y: number }) =>
      `${Math.round(p.x / CELL_X)}:${Math.round(p.y / CELL_Y)}`;
    [...pos.keys()].sort().forEach((id) => {
      const orig = pos.get(id)!;
      let a = Math.atan2(orig.y - cy, orig.x - cx);
      if (!Number.isFinite(a)) a = 0;
      const r0 = Math.hypot(orig.x - cx, orig.y - cy);
      let p = orig;
      let step = 0;
      while (taken.has(cellOf(p)) && step < 60) {
        step += 1;
        const na = a + (step % 2 === 0 ? 1 : -1) * 0.11 * Math.ceil(step / 2);
        const nr = r0 + CELL_Y * Math.floor(step / 4);
        p = { x: cx + nr * Math.cos(na), y: cy + nr * Math.sin(na) };
      }
      taken.add(cellOf(p));
      pos.set(id, p);
    });

    const visible = new Set([...pos.keys()]);
    const rfNodes: RFNode[] = [...visible].map((id) => {
      const n = byId.get(id)!;
      const c = KIND_COLOR[n.kind] ?? KIND_COLOR.domain;
      const big = n.kind === "domain";
      return {
        id,
        position: pos.get(id)!,
        data: { label: n.label.length > 30 ? `${n.label.slice(0, 30)}…` : n.label },
        style: {
          background: c.bg, border: `1.5px solid ${c.border}`, color: c.text,
          borderRadius: big ? 22 : 8, fontSize: big ? 13 : 11,
          padding: big ? "10px 16px" : "5px 9px", width: "auto",
        },
      };
    });

    const rfEdges: RFEdge[] = allEdges
      .filter((e) => visible.has(e.from_id) && visible.has(e.to_id))
      .map((e) => {
        const measured = e.provenance?.measured;
        return {
          id: e.id, source: e.from_id, target: e.to_id,
          label: e.kind === "joins_on" && typeof measured === "number"
            ? `${Math.round(measured * 100)}%` : undefined,
          style: { stroke: EDGE_COLOR[e.kind] ?? "#475569", strokeWidth: e.kind === "joins_on" ? 1.6 : 1, opacity: 0.65 },
          labelStyle: { fill: "var(--t2, #94a3b8)", fontSize: 9 },
          labelBgStyle: { fill: "transparent" },
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: EDGE_COLOR[e.kind] ?? "#475569" },
        };
      });

    const counts = graph.counts || {};
    return {
      nodes: rfNodes,
      edges: rfEdges,
      hiddenCounts: {
        finding: showFindings ? 0 : counts.finding || 0,
        glossary_term: showTerms ? 0 : counts.glossary_term || 0,
      },
    };
  }, [graph, showFindings, showTerms]);

  const chip = (active: boolean, onClick: () => void, label: string) => (
    <button
      onClick={onClick}
      style={{
        fontSize: 11, padding: "3px 10px", borderRadius: 999, cursor: "pointer",
        border: `1px solid ${active ? "var(--t3, #64748b)" : "var(--bg-3, #1e293b)"}`,
        background: active ? "var(--bg-3, #1e293b)" : "transparent",
        color: active ? "var(--t1, #e2e8f0)" : "var(--t3, #94a3b8)",
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ height: "100%", minHeight: 520, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {chip(showFindings, () => setShowFindings((v) => !v),
          showFindings ? "Findings shown" : `Show ${hiddenCounts.finding} findings`)}
        {chip(showTerms, () => setShowTerms((v) => !v),
          showTerms ? "Terms shown" : `Show ${hiddenCounts.glossary_term} terms`)}
        <span style={{ fontSize: 11, color: "var(--t3, #94a3b8)" }}>
          Click a table to open its detail page. Join edges carry the measured value-domain overlap.
        </span>
      </div>
      <div style={{ flex: 1, borderRadius: 10, overflow: "hidden", border: "1px solid var(--bg-3, #1e293b)" }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          minZoom={0.08}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, n) => {
            if (String(n.id).startsWith("table:")) onOpenTable?.(String(n.id));
          }}
          colorMode="dark"
        >
          <Background gap={28} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
