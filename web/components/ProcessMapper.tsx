"use client";

import { useEffect, useState } from "react";
import { getProcessMap, type ProcessMap, type ProcessNode, type ProcessEdge } from "@/lib/api";
import { compactNumber } from "@/lib/format";

// ── Layout constants ──────────────────────────────────────────────────────────

const NODE_W    = 140;
const NODE_H    = 64;
const COL_GAP   = 80;
const ROW_GAP   = 20;
const PAD       = 32;

// ── Health colour by conversion rate ─────────────────────────────────────────

function edgeHealth(rate: number): { stroke: string; label: string } {
  if (rate >= 0.8) return { stroke: "#22c55e", label: "text-emerald-400" };
  if (rate >= 0.5) return { stroke: "#f59e0b", label: "text-amber-400"   };
  return              { stroke: "#ef4444", label: "text-red-400"         };
}

function nodeRing(state: string, edges: ProcessEdge[], isTerminal: boolean): string {
  if (isTerminal) return "border-zinc-600";
  // Check lowest outbound rate
  const out = edges.filter(e => e.from_state === state);
  if (out.length === 0) return "border-zinc-600";
  const minRate = Math.min(...out.map(e => e.rate));
  if (minRate < 0.5) return "border-red-500/60";
  if (minRate < 0.8) return "border-amber-500/60";
  return "border-emerald-500/40";
}

function fmt(n: number): string {
  return compactNumber(n, 1);
}

// ── Layout engine ─────────────────────────────────────────────────────────────
// Place nodes in columns: non-terminal states left-to-right by ontology order,
// terminal states in the rightmost column.

interface LayoutNode extends ProcessNode {
  x: number;
  y: number;
  col: number;
}

function layout(nodes: ProcessNode[], edges: ProcessEdge[]): { laid: LayoutNode[]; svgW: number; svgH: number } {
  const nonTerminal = nodes.filter(n => !n.is_terminal);
  const terminal    = nodes.filter(n => n.is_terminal);

  const cols: ProcessNode[][] = [];
  nonTerminal.forEach((n, i) => cols.push([n]));
  if (terminal.length > 0) cols.push(terminal);

  const svgW = PAD * 2 + cols.length * NODE_W + (cols.length - 1) * COL_GAP;
  const maxRows = Math.max(...cols.map(c => c.length));
  const svgH = PAD * 2 + maxRows * NODE_H + (maxRows - 1) * ROW_GAP;

  const laid: LayoutNode[] = [];
  cols.forEach((col, ci) => {
    const colX = PAD + ci * (NODE_W + COL_GAP);
    const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP;
    const startY = (svgH - colH) / 2;
    col.forEach((n, ri) => {
      laid.push({ ...n, x: colX, y: startY + ri * (NODE_H + ROW_GAP), col: ci });
    });
  });

  return { laid, svgW: Math.max(svgW, 300), svgH: Math.max(svgH, NODE_H + PAD * 2) };
}

// ── Edge path — cubic bezier between node right-centre and node left-centre ──

function edgePath(from: LayoutNode, to: LayoutNode): string {
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_H / 2;
  const cx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface Tooltip { x: number; y: number; content: string }

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  connId: string;
  entityId: string;
  onInvestigate?: (question: string) => void;
}

export function ProcessMapper({ connId, entityId, onInvestigate }: Props) {
  const [map, setMap] = useState<ProcessMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);

  useEffect(() => {
    setLoading(true);
    setMap(null);
    getProcessMap(connId, entityId)
      .then(setMap)
      .catch(() => setMap(null))
      .finally(() => setLoading(false));
  }, [connId, entityId]);

  if (loading) {
    return (
      <div className="py-8 text-center text-xs text-zinc-500 font-mono animate-pulse">
        Loading process map…
      </div>
    );
  }

  if (!map || map.nodes.length === 0) {
    return (
      <div className="py-6 text-center text-xs text-zinc-500">
        No lifecycle data available for this entity.
      </div>
    );
  }

  const { laid, svgW, svgH } = layout(map.nodes, map.edges);
  const nodeByState = Object.fromEntries(laid.map(n => [n.state, n]));

  // Only draw edges that connect nodes we've laid out
  const visibleEdges = map.edges.filter(
    e => nodeByState[e.from_state] && nodeByState[e.to_state]
  );

  // Edge stroke width scaled by count relative to max
  const maxEdgeCount = Math.max(...visibleEdges.map(e => e.count), 1);

  function showNodeTooltip(n: LayoutNode) {
    const cx = n.x + NODE_W / 2;
    const cy = n.y;
    const out = map!.edges.filter(e => e.from_state === n.state);
    const lines = [`${n.state}: ${fmt(n.count)} records`];
    if (n.is_terminal) lines.push("terminal state");
    out.forEach(e => lines.push(`→ ${e.to_state}: ${fmt(e.count)} (${(e.rate * 100).toFixed(0)}%)`));
    setTooltip({ x: cx, y: cy - 8, content: lines.join("\n") });
  }

  function showEdgeTooltip(e: ProcessEdge, mx: number, my: number) {
    setTooltip({
      x: mx, y: my - 8,
      content: `${e.from_state} → ${e.to_state}\n${fmt(e.count)} transitions · ${(e.rate * 100).toFixed(0)}% conversion`,
    });
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-zinc-300">
            Process Map
            <span className="ml-2 text-zinc-500 font-mono font-normal">
              {map.lifecycle_column}
            </span>
          </p>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {fmt(map.total_records)} total records
            {!map.has_transitions && " · showing state distribution only"}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-zinc-500">
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-emerald-500" /> ≥80%</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-500" /> ≥50%</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-red-500" /> &lt;50%</span>
        </div>
      </div>

      {/* SVG canvas */}
      <div className="overflow-x-auto rounded-md border border-zinc-700 bg-zinc-900">
        <svg
          width={svgW}
          height={svgH}
          className="block"
          onMouseLeave={() => setTooltip(null)}
        >
          {/* Edges — drawn behind nodes */}
          {visibleEdges.map((e, i) => {
            const fromN = nodeByState[e.from_state];
            const toN   = nodeByState[e.to_state];
            const { stroke } = edgeHealth(e.rate);
            const strokeW = 1.5 + (e.count / maxEdgeCount) * 4;
            const midX = (fromN.x + NODE_W + toN.x) / 2;
            const midY = (fromN.y + toN.y + NODE_H) / 2;
            return (
              <g key={i}>
                <path
                  d={edgePath(fromN, toN)}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={strokeW}
                  strokeOpacity={0.6}
                  className="cursor-pointer"
                  onMouseEnter={ev => showEdgeTooltip(e, midX, midY)}
                />
                {/* Rate label on edge midpoint */}
                <text
                  x={midX}
                  y={midY - 4}
                  textAnchor="middle"
                  fontSize={10}
                  fill={stroke}
                  fillOpacity={0.85}
                  className="pointer-events-none select-none font-mono"
                >
                  {(e.rate * 100).toFixed(0)}%
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {laid.map(n => {
            const ring = nodeRing(n.state, map.edges, n.is_terminal);
            const pct = map.total_records > 0 ? (n.count / map.total_records) * 100 : 0;
            return (
              <g
                key={n.state}
                className="cursor-pointer"
                onMouseEnter={() => showNodeTooltip(n)}
                onClick={() => onInvestigate?.(`Investigate the ${n.state} state for ${map.display_name}`)}
              >
                {/* Node box */}
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={8}
                  ry={8}
                  fill="var(--bg-1)"
                  stroke={
                    ring.includes("red")     ? "#ef4444" :
                    ring.includes("amber")   ? "#f59e0b" :
                    ring.includes("emerald") ? "#22c55e" :
                    "var(--b2)"
                  }
                  strokeWidth={1.5}
                  strokeOpacity={0.7}
                />
                {/* State label */}
                <text
                  x={n.x + NODE_W / 2}
                  y={n.y + 22}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill="var(--t1)"
                  className="pointer-events-none select-none"
                >
                  {n.state.length > 14 ? n.state.slice(0, 13) + "…" : n.state}
                </text>
                {/* Count */}
                <text
                  x={n.x + NODE_W / 2}
                  y={n.y + 38}
                  textAnchor="middle"
                  fontSize={10}
                  fill="var(--t3)"
                  className="pointer-events-none select-none font-mono"
                >
                  {fmt(n.count)} · {pct.toFixed(0)}%
                </text>
                {/* Terminal badge */}
                {n.is_terminal && (
                  <text
                    x={n.x + NODE_W / 2}
                    y={n.y + 54}
                    textAnchor="middle"
                    fontSize={9}
                    fill="var(--t4)"
                    className="pointer-events-none select-none uppercase tracking-widest"
                  >
                    terminal
                  </text>
                )}
              </g>
            );
          })}

          {/* SVG tooltip */}
          {tooltip && (() => {
            const lines = tooltip.content.split("\n");
            const maxLen = Math.max(...lines.map(l => l.length));
            const tw = maxLen * 6.5 + 20;
            const th = lines.length * 14 + 12;
            const tx = Math.min(Math.max(tooltip.x - tw / 2, 4), svgW - tw - 4);
            const ty = Math.max(tooltip.y - th - 6, 4);
            return (
              <g pointerEvents="none">
                <rect x={tx} y={ty} width={tw} height={th} rx={6} fill="var(--bg-1)" stroke="var(--b2)" strokeWidth={1} />
                {lines.map((l, i) => (
                  <text key={i} x={tx + 10} y={ty + 14 + i * 14} fontSize={10} fill="var(--t1)" fontFamily="monospace">
                    {l}
                  </text>
                ))}
              </g>
            );
          })()}
        </svg>
      </div>

      {/* No-transition notice */}
      {!map.has_transitions && map.nodes.length > 0 && (
        <p className="text-[11px] text-zinc-500 text-center">
          Transition arrows require multiple rows per record tracking state changes over time.
        </p>
      )}
    </div>
  );
}
