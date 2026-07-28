"use client";
/**
 * The knowledge graph as an actual GRAPH — force-directed, interactive, and wired into
 * the product rather than decorative.
 *
 * P1 — `d3-force` (the one new dependency, MIT, ~10KB) computes positions; React Flow keeps
 * rendering, so nodes stay clickable React components in the app's design system. The
 * simulation is seeded from a deterministic radial layout clustered by domain, so the settle
 * is short and a returning reader's spatial memory mostly survives; anchor forces keep each
 * domain's tables near their bearing instead of drifting into soup. Dragging pins a node
 * (the classic fx/fy pattern); the sim reheats around it.
 *
 * P2 — selection drives real actions through the workspace's own `onInvestigate` seam (the
 * same one the Ontology panel and Briefing already use): a selected table becomes "Ask about
 * this table", several become "Ask across these tables", a finding becomes a re-examination
 * prompt, a metric or term becomes its own question. The graph is a launcher for the Ask
 * surface, not a picture beside it.
 *
 * P3 — findings carry `generated_at`, so when the findings layer is on, a time slider
 * replays knowledge accumulating (the Bostock temporal force-directed pattern): sim node
 * identities are preserved across cutoff changes, so existing nodes keep their positions and
 * only the newly-arrived findings fly in.
 *
 * Findings (100) and terms (255) stay behind counted toggles — the default ~30-node view
 * must never become the hairball the C4 card surface exists to avoid.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  applyNodeChanges,
  type Edge as RFEdge,
  type Node as RFNode,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum,
} from "d3-force";
import type { CGEdge, CGNode, ConnectionGraph } from "@/lib/api";

const KIND_COLOR: Record<string, { bg: string; border: string }> = {
  domain:        { bg: "rgba(100,116,139,0.18)", border: "#64748b" },
  table:         { bg: "rgba(37,99,235,0.16)",   border: "#3b82f6" },
  metric:        { bg: "rgba(124,58,237,0.16)",  border: "#8b5cf6" },
  brief:         { bg: "rgba(22,163,74,0.16)",   border: "#22c55e" },
  finding:       { bg: "rgba(234,88,12,0.14)",   border: "#f97316" },
  glossary_term: { bg: "rgba(8,145,178,0.14)",   border: "#06b6d4" },
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

interface SimNode extends SimulationNodeDatum {
  id: string;
  /** Radial seed the anchor forces pull toward — the domain clustering. */
  ax: number;
  ay: number;
  kind: string;
  label: string;
}

interface Props {
  graph: ConnectionGraph;
  onOpenTable?: (tableId: string) => void;
  /** The workspace's Ask seam — a question here lands on the full Ask surface. */
  onAsk?: (question: string) => void;
}

/** Deterministic radial seed, grouped by domain (see the module docstring). */
function seedLayout(all: CGNode[], edges: CGEdge[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const domains = all.filter((n) => n.kind === "domain").sort((a, b) => a.label.localeCompare(b.label));
  const tables = all.filter((n) => n.kind === "table");
  const domainAngle = new Map<string, number>();
  domains.forEach((d, i) => domainAngle.set(d.label, (TWO_PI * i) / Math.max(1, domains.length)));
  domains.forEach((d) => {
    const a = domainAngle.get(d.label)!;
    pos.set(d.id, { x: 220 * Math.cos(a), y: 220 * Math.sin(a) });
  });

  const angleOfTable = new Map<string, number>();
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
      pos.set(t.id, { x: 480 * Math.cos(a), y: 480 * Math.sin(a) });
    });
  }

  const derivedTargets = (id: string) =>
    edges.filter((e) => e.kind === "derived_from" && e.from_id === id).map((e) => e.to_id);
  all.filter((n) => n.kind === "metric" || n.kind === "brief").forEach((n, i) => {
    const targets = derivedTargets(n.id).map((t) => angleOfTable.get(t)).filter((a): a is number => a !== undefined);
    const a = targets.length ? targets.reduce((s, v) => s + v, 0) / targets.length : -Math.PI / 2 + i * 0.5;
    pos.set(n.id, { x: 700 * Math.cos(a), y: 700 * Math.sin(a) });
  });

  const groundOf = new Map<string, string>();
  edges.filter((e) => e.kind === "grounded_in").forEach((e) => {
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
    return { x: r * Math.cos(a), y: r * Math.sin(a) };
  };
  all.filter((n) => n.kind === "finding").forEach((n, i) => pos.set(n.id, fan(groundOf.get(n.id), 900, i)));
  all.filter((n) => n.kind === "glossary_term").forEach((n, i) =>
    pos.set(n.id, fan(tableByBare.get(bare((n.data.table as string) || "")), 1180, i)));
  return pos;
}

/** The Ask question a selection turns into — one selected thing, one honest question. */
function questionFor(selected: CGNode[]): string {
  if (selected.length === 1) {
    const n = selected[0];
    if (n.kind === "table") return `Give me an overview of the ${n.label} table: what it contains, its data quality, and the most important patterns in it.`;
    if (n.kind === "metric") return `Explain the metric "${n.label}": how it is computed here, and show its current value.`;
    if (n.kind === "glossary_term") return `What does "${n.label}" mean in this data, and where is it used?`;
    if (n.kind === "finding") {
      const q = (n.data.question as string) || "";
      const text = n.label.length > 140 ? `${n.label.slice(0, 140)}…` : n.label;
      return q
        ? `Re-examine this earlier finding and tell me whether it still holds: "${text}" (it answered: ${q})`
        : `Re-examine this earlier finding and tell me whether it still holds: "${text}"`;
    }
    if (n.kind === "domain") return `Give me an overview of the ${n.label} domain: its tables, how they relate, and what stands out.`;
  }
  const tables = selected.filter((n) => n.kind === "table").map((n) => n.label);
  if (tables.length === selected.length && tables.length > 1)
    return `Analyze how these tables relate and what joins them safely: ${tables.join(", ")}.`;
  return `Analyze the relationship between: ${selected.map((n) => n.label).join(", ")}.`;
}

export function GraphCanvas({ graph, onOpenTable, onAsk }: Props) {
  const [showFindings, setShowFindings] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [rfNodes, setRfNodes] = useState<RFNode[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  // P3 — the findings-time cutoff (an index into the sorted timestamp list; null = all).
  const [timeIdx, setTimeIdx] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());

  const all = useMemo(() => Object.values(graph.nodes) as CGNode[], [graph]);
  const allEdges = useMemo(() => Object.values(graph.edges) as CGEdge[], [graph]);
  const byId = useMemo(() => new Map(all.map((n) => [n.id, n])), [all]);
  const seeds = useMemo(() => seedLayout(all, allEdges), [all, allEdges]);

  // The findings timeline — distinct timestamps, sorted. Blank stamps sort first (always shown).
  const timeline = useMemo(() => {
    const ts = [...new Set(all.filter((n) => n.kind === "finding")
      .map((n) => String(n.data.generated_at || "")))].sort();
    return ts;
  }, [all]);

  const cutoff = timeIdx !== null && timeline.length ? timeline[Math.min(timeIdx, timeline.length - 1)] : null;

  const visibleIds = useMemo(() => {
    const ids: string[] = [];
    for (const n of all) {
      if (n.kind === "finding") {
        if (!showFindings) continue;
        if (cutoff !== null && String(n.data.generated_at || "") > cutoff) continue;
      }
      if (n.kind === "glossary_term" && !showTerms) continue;
      ids.push(n.id);
    }
    return ids;
  }, [all, showFindings, showTerms, cutoff]);

  // ── the simulation: one instance, node identity preserved across visibility changes ──
  useEffect(() => {
    const prev = simNodesRef.current;
    const nodes: SimNode[] = visibleIds.map((id) => {
      const existing = prev.get(id);
      if (existing) return existing;                       // keeps x/y/vx/vy — the temporal pattern
      const s = seeds.get(id) ?? { x: 0, y: 0 };
      const n = byId.get(id)!;
      return { id, x: s.x, y: s.y, ax: s.x, ay: s.y, kind: n.kind, label: n.label };
    });
    simNodesRef.current = new Map(nodes.map((n) => [n.id, n]));
    const idset = new Set(visibleIds);
    const links = allEdges
      .filter((e) => idset.has(e.from_id) && idset.has(e.to_id))
      .map((e) => ({ source: e.from_id, target: e.to_id, kind: e.kind }));

    const sim = simRef.current ?? forceSimulation<SimNode>();
    simRef.current = sim;
    sim.nodes(nodes)
      .force("link", forceLink<SimNode, { source: string; target: string; kind: string }>(links)
        .id((d) => d.id)
        .distance((l) => (l.kind === "joins_on" ? 230 : l.kind === "derived_from" ? 180 : 130))
        .strength(0.25))
      .force("charge", forceManyBody<SimNode>()
        .strength((d) => (d.kind === "finding" || d.kind === "glossary_term" ? -60 : -320)))
      .force("collide", forceCollide<SimNode>().radius((d) => Math.min(d.label.length, 30) * 3.4 + 16))
      // Anchors keep the domain clustering readable instead of letting charge win.
      .force("ax", forceX<SimNode>((d) => d.ax).strength((d) =>
        d.kind === "domain" ? 0.35 : d.kind === "table" ? 0.12 : 0.04))
      .force("ay", forceY<SimNode>((d) => d.ay).strength((d) =>
        d.kind === "domain" ? 0.35 : d.kind === "table" ? 0.12 : 0.04));

    const sel = new Set(selectedIds);
    const onTick = () => {
      setRfNodes(sim.nodes().map((sn) => {
        const n = byId.get(sn.id)!;
        const c = KIND_COLOR[n.kind] ?? KIND_COLOR.domain;
        const big = n.kind === "domain";
        return {
          id: sn.id,
          position: { x: sn.x ?? 0, y: sn.y ?? 0 },
          data: { label: n.label.length > 30 ? `${n.label.slice(0, 30)}…` : n.label },
          selected: sel.has(sn.id),
          style: {
            background: c.bg, border: `1.5px solid ${c.border}`, color: "var(--t1, #e2e8f0)",
            borderRadius: big ? 22 : 8, fontSize: big ? 13 : 11,
            padding: big ? "10px 16px" : "5px 9px", width: "auto",
          },
        };
      }));
    };
    sim.on("tick", onTick);
    sim.alpha(0.9).alphaDecay(0.035).restart();
    onTick();
    return () => { sim.on("tick", null); sim.stop(); };
    // selectedIds is applied inside onNodesChange; re-running the sim for a selection
    // change would reheat the layout every click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleIds, allEdges, byId, seeds]);

  // P3 — replay: advance the cutoff through the timeline.
  useEffect(() => {
    if (!playing) return;
    if (timeIdx === null) { setTimeIdx(0); return; }
    if (timeIdx >= timeline.length - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setTimeIdx((i) => (i === null ? 0 : i + 1)), 350);
    return () => clearTimeout(t);
  }, [playing, timeIdx, timeline.length]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setRfNodes((ns) => applyNodeChanges(changes, ns));
    const selDelta = changes.filter((c) => c.type === "select") as { id: string; selected: boolean }[];
    if (selDelta.length) {
      setSelectedIds((ids) => {
        const s = new Set(ids);
        selDelta.forEach((c) => (c.selected ? s.add(c.id) : s.delete(c.id)));
        return [...s];
      });
    }
  }, []);

  // Drag pins (fx/fy) and reheats — the classic d3 drag contract.
  const onNodeDrag = useCallback((_: unknown, node: RFNode) => {
    const sn = simNodesRef.current.get(node.id);
    if (sn) { sn.fx = node.position.x; sn.fy = node.position.y; }
    simRef.current?.alphaTarget(0.25).restart();
  }, []);
  const onNodeDragStop = useCallback((_: unknown, node: RFNode) => {
    const sn = simNodesRef.current.get(node.id);
    if (sn) { sn.fx = node.position.x; sn.fy = node.position.y; }   // stays pinned
    simRef.current?.alphaTarget(0);
  }, []);

  const rfEdges: RFEdge[] = useMemo(() => {
    const idset = new Set(visibleIds);
    return allEdges
      .filter((e) => idset.has(e.from_id) && idset.has(e.to_id))
      .map((e) => {
        const measured = e.provenance?.measured;
        return {
          id: e.id, source: e.from_id, target: e.to_id,
          label: e.kind === "joins_on" && typeof measured === "number" ? `${Math.round(measured * 100)}%` : undefined,
          style: { stroke: EDGE_COLOR[e.kind] ?? "#475569", strokeWidth: e.kind === "joins_on" ? 1.6 : 1, opacity: 0.6 },
          labelStyle: { fill: "var(--t2, #94a3b8)", fontSize: 9 },
          labelBgStyle: { fill: "transparent" },
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: EDGE_COLOR[e.kind] ?? "#475569" },
        };
      });
  }, [allEdges, visibleIds]);

  const selected = selectedIds.map((id) => byId.get(id)).filter((n): n is CGNode => !!n);
  const counts = graph.counts || {};

  const chip = (active: boolean, onClick: () => void, label: string) => (
    <button onClick={onClick}
      style={{
        fontSize: 11, padding: "3px 10px", borderRadius: 999, cursor: "pointer",
        border: `1px solid ${active ? "var(--t3, #64748b)" : "var(--bg-3, #1e293b)"}`,
        background: active ? "var(--bg-3, #1e293b)" : "transparent",
        color: active ? "var(--t1, #e2e8f0)" : "var(--t3, #94a3b8)",
      }}>{label}</button>
  );

  const action = (label: string, onClick: () => void, primary = false) => (
    <button onClick={onClick}
      style={{
        fontSize: 11, padding: "4px 12px", borderRadius: 6, cursor: "pointer",
        border: `1px solid ${primary ? "#3b82f6" : "var(--bg-3, #1e293b)"}`,
        background: primary ? "rgba(37,99,235,0.18)" : "var(--bg-2, #0f172a)",
        color: "var(--t1, #e2e8f0)", fontWeight: primary ? 600 : 400,
      }}>{label}</button>
  );

  const cutoffLabel = cutoff ? cutoff.slice(0, 10) : "all time";

  return (
    <div style={{ height: "100%", minHeight: 560, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {chip(showFindings, () => { setShowFindings((v) => !v); setTimeIdx(null); setPlaying(false); },
          showFindings ? "Findings shown" : `Show ${counts.finding || 0} findings`)}
        {chip(showTerms, () => setShowTerms((v) => !v),
          showTerms ? "Terms shown" : `Show ${counts.glossary_term || 0} terms`)}
        {showFindings && timeline.length > 1 && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <button onClick={() => setPlaying((p) => !p)} title="Replay how knowledge accumulated"
              style={{ fontSize: 12, cursor: "pointer", background: "none", color: "var(--t1, #e2e8f0)",
                       border: "1px solid var(--bg-3, #1e293b)", borderRadius: 6, padding: "2px 8px" }}>
              {playing ? "❚❚" : "▶"}
            </button>
            <input type="range" min={0} max={timeline.length - 1}
              value={timeIdx ?? timeline.length - 1}
              onChange={(e) => { setPlaying(false); setTimeIdx(Number(e.target.value)); }}
              style={{ width: 160 }} aria-label="Findings up to date" />
            <span style={{ fontSize: 11, color: "var(--t3, #94a3b8)", minWidth: 80 }}>
              {timeIdx === null ? "all findings" : `up to ${cutoffLabel}`}
            </span>
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--t3, #94a3b8)", marginLeft: "auto" }}>
          drag pins a node · click selects · shift-click multi-selects
        </span>
      </div>

      {selected.length > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
                      padding: "6px 10px", borderRadius: 8, border: "1px solid var(--bg-3, #1e293b)",
                      background: "var(--bg-2, rgba(15,23,42,0.6))" }}>
          <span style={{ fontSize: 11, color: "var(--t2, #94a3b8)" }}>
            {selected.length === 1
              ? `${selected[0].kind.replace("_", " ")}: ${selected[0].label.slice(0, 60)}`
              : `${selected.length} selected`}
          </span>
          {onAsk && action(
            selected.length === 1 && selected[0].kind === "table" ? "Ask about this table"
              : selected.length === 1 && selected[0].kind === "finding" ? "Re-examine this finding"
              : selected.length === 1 ? `Ask about ${selected[0].kind.replace("_", " ")}`
              : "Ask about these together",
            () => onAsk(questionFor(selected)), true)}
          {selected.length === 1 && selected[0].kind === "table" && onOpenTable &&
            action("Open detail", () => onOpenTable(selected[0].id))}
          {selected.length === 1 && selected[0].provenance &&
            <span style={{ fontSize: 10, color: "var(--t4, #64748b)" }}>
              source: {selected[0].provenance.source}
            </span>}
        </div>
      )}

      <div style={{ flex: 1, borderRadius: 10, overflow: "hidden", border: "1px solid var(--bg-3, #1e293b)" }}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={onNodesChange}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          onNodeDoubleClick={(_, n) => { if (String(n.id).startsWith("table:")) onOpenTable?.(String(n.id)); }}
          fitView
          minZoom={0.08}
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          selectionOnDrag={false}
          colorMode="dark"
        >
          <Background gap={28} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
