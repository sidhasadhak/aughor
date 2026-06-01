"use client";

/**
 * OntologyCanvas — interactive business-process graph.
 *
 * Entity nodes on a dark canvas connected by animated flowing edges that
 * convey relationship direction and confidence.  Click a node to open the
 * detail drawer; hover to highlight the local neighbourhood.
 */

import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type {
  OntologyGraph,
  OntologyEntity,
  OntologyRelationship,
  OntologyAction,
  OntologyMetric,
  CausalEdge,
} from "@/lib/api";
import { getCausalGraph } from "@/lib/api";

// ── Layout constants ──────────────────────────────────────────────────────────

const NODE_W     = 256;
const LAYER_GAP  = 130;
const NODE_GAP_Y = 32;
const PAD        = 60;

// ── Layout engine — topological depth sort ────────────────────────────────────
//
// Left-to-right = business process start-to-finish:
//   FOUNDATION (depth 0) — master entities with no outgoing dependencies
//   OBJECTS    (depth 1…n-1) — entities that reference foundation objects
//   EVENTS     (depth n)  — leaf entities that reference objects but are
//                            referenced by nothing else
//   STANDALONE            — entities with no relationships at all
//
// Depth is computed as the longest path from each entity to any base entity
// via its outgoing reference edges (from_entity → to_entity means "references").

interface NodeLayout {
  entity: OntologyEntity;
  x: number;
  y: number;
  h: number;
  col: number;   // topological column index
}

function nodeHeight(e: OntologyEntity): number {
  const header    = 80;
  const lifecycle = e.has_lifecycle && e.lifecycle_states.length ? 52 : 0;
  const footer    = 32;
  return header + lifecycle + footer;
}

function computeLayout(graph: OntologyGraph): {
  nodes: NodeLayout[];
  canvasW: number;
  canvasH: number;
  colLabels: { x: number; label: string }[];
} {
  const entities = Object.values(graph.entities);
  const rels     = Object.values(graph.relationships);

  // deps[id] = entities that id directly references (outgoing from id)
  const deps: Record<string, string[]> = {};
  for (const e of entities) deps[e.id] = [];
  for (const r of rels) {
    if (r.from_entity in deps) deps[r.from_entity].push(r.to_entity);
  }

  // Topological depth via memoised DFS:
  //   depth(e) = 0           if e has no outgoing refs  (base / foundation)
  //   depth(e) = max(depth(dep) + 1)  for each dep e references
  // Cycles are broken by treating the back-edge target as depth-0.
  const depthCache: Record<string, number> = {};
  const computing  = new Set<string>();

  function topoDepth(id: string): number {
    if (computing.has(id))      return 0;  // cycle — treat as base
    if (id in depthCache)       return depthCache[id];
    computing.add(id);
    let d = 0;
    for (const dep of (deps[id] ?? [])) {
      d = Math.max(d, topoDepth(dep) + 1);
    }
    computing.delete(id);
    depthCache[id] = d;
    return d;
  }

  for (const e of entities) topoDepth(e.id);

  // Entities that participate in at least one relationship
  const hasRels = new Set<string>();
  for (const r of rels) { hasRels.add(r.from_entity); hasRels.add(r.to_entity); }

  // Connected depths for figuring out the column count
  const connectedDepths = entities.filter(e => hasRels.has(e.id)).map(e => depthCache[e.id]);
  const maxConnectedDepth = connectedDepths.length ? Math.max(...connectedDepths) : 0;

  // Assign column: connected entities by depth, isolated entities at end
  const ISOLATED_COL = maxConnectedDepth + 1;
  const colOf: Record<string, number> = {};
  for (const e of entities) {
    colOf[e.id] = hasRels.has(e.id) ? depthCache[e.id] : ISOLATED_COL;
  }

  // Group by column and sort alphabetically within each column
  const byCol: Record<number, OntologyEntity[]> = {};
  for (const e of entities) (byCol[colOf[e.id]] ??= []).push(e);
  for (const arr of Object.values(byCol))
    arr.sort((a, b) => a.display_name.localeCompare(b.display_name));

  const cols = Object.keys(byCol).map(Number).sort((a, b) => a - b);
  const colX: Record<number, number> = {};
  cols.forEach((c, i) => { colX[c] = PAD + i * (NODE_W + LAYER_GAP); });

  // Semantic column labels — prefer majority entity_type in column, fall back to position
  const connectedCols = cols.filter(c => c !== ISOLATED_COL || !byCol[c]?.every(e => !hasRels.has(e.id)));
  const nConnected    = connectedCols.length;

  function majorityType(col: number): string {
    const bucket = byCol[col] ?? [];
    const counts: Record<string, number> = {};
    for (const e of bucket) counts[e.entity_type ?? "business_object"] = (counts[e.entity_type ?? "business_object"] ?? 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "business_object";
  }

  const TYPE_LABEL: Record<string, string> = {
    reference_data:  "Foundation",
    business_object: "Objects",
    event:           "Events",
    standalone:      "Standalone",
  };

  function colLabel(col: number, colIndex: number): string {
    const isIsolated = col === ISOLATED_COL && byCol[col]?.every(e => !hasRels.has(e.id));
    if (isIsolated) return "Standalone";
    const majority = majorityType(col);
    // If entity_type gives a clear signal, use it; otherwise fall back to position
    if (majority !== "business_object") return TYPE_LABEL[majority] ?? "Objects";
    if (colIndex === 0) return "Foundation";
    if (colIndex === nConnected - 1 && nConnected > 1) return "Events";
    return "Objects";
  }

  const colLabels = cols.map((c, i) => ({ x: colX[c], label: colLabel(c, i) }));

  // Place nodes
  const nodes: NodeLayout[] = [];
  for (const col of cols) {
    let y = PAD + 28;   // leave room for column header
    for (const e of byCol[col]) {
      const h = nodeHeight(e);
      nodes.push({ entity: e, x: colX[col], y, h, col });
      y += h + NODE_GAP_Y;
    }
  }

  const canvasW = cols.length
    ? colX[cols[cols.length - 1]] + NODE_W + PAD
    : PAD * 2 + NODE_W;

  const canvasH = Math.max(
    480,
    ...cols.map(c => {
      let h = PAD + 28;
      for (const e of (byCol[c] ?? [])) h += nodeHeight(e) + NODE_GAP_Y;
      return h + PAD - NODE_GAP_Y;
    }),
  );

  return { nodes, canvasW, canvasH, colLabels };
}

// ── Entity node card ──────────────────────────────────────────────────────────

function EntityNode({
  layout,
  isSelected,
  isNeighbour,
  isDimmed,
  actionCount,
  metricCount,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onInvestigate,
}: {
  layout: NodeLayout;
  isSelected: boolean;
  isNeighbour: boolean;
  isDimmed: boolean;
  actionCount: number;
  metricCount: number;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onInvestigate?: (q: string) => void;
}) {
  const { entity, x, y } = layout;
  // Avatar letter — first char of display name, uppercased
  const avatar = entity.display_name.charAt(0).toUpperCase();

  // Entity-type colour palette
  const typeTheme = isSelected
    ? { ring: "bg-violet-600/30 text-violet-200 ring-1 ring-violet-500/30", border: "border-violet-400/60 bg-[#1a1f2e] shadow-xl shadow-violet-500/10 ring-1 ring-violet-500/15" }
    : entity.entity_type === "reference_data"
    ? { ring: "bg-emerald-700/20 text-emerald-300 ring-1 ring-emerald-600/25", border: "border-zinc-700/50 bg-zinc-900/80 hover:border-emerald-600/40 hover:bg-zinc-900" }
    : entity.entity_type === "event"
    ? { ring: "bg-violet-700/20 text-violet-300 ring-1 ring-violet-600/25", border: "border-zinc-700/50 bg-zinc-900/80 hover:border-violet-600/40 hover:bg-zinc-900" }
    : entity.entity_type === "standalone"
    ? { ring: "bg-zinc-700/40 text-zinc-500 ring-1 ring-zinc-700/30", border: "border-zinc-700/40 bg-zinc-900/60 hover:border-zinc-600/60" }
    : { ring: "bg-sky-700/20 text-sky-300 ring-1 ring-sky-600/25", border: "border-zinc-700/50 bg-zinc-900/80 hover:border-sky-600/40 hover:bg-zinc-900" }; // business_object

  return (
    <div
      className={cn(
        "absolute rounded-md border cursor-pointer select-none transition-all duration-200",
        isNeighbour && !isSelected ? "border-violet-600/35 bg-zinc-900/90" : typeTheme.border,
        isDimmed && "opacity-20 pointer-events-none",
      )}
      style={{ left: x, top: y, width: NODE_W }}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* Header — avatar + name */}
      <div className="px-3.5 pt-3.5 pb-3 border-b border-zinc-700/40">
        <div className="flex items-center gap-3">
          {/* Avatar */}
          <div className={cn("w-10 h-10 rounded-md flex items-center justify-center shrink-0 font-bold text-[15px]", typeTheme.ring)}>
            {avatar}
          </div>

          <div className="min-w-0 flex-1">
            <p
              className={cn(
                "text-[16px] font-semibold leading-tight truncate",
                isSelected ? "text-violet-100" : "text-zinc-100",
              )}
            >
              {entity.display_name}
            </p>
            {entity.grain_verified ? (
              <span className="text-[11px] text-emerald-400/60">verified grain</span>
            ) : (
              <span className="text-[11px] text-zinc-700 font-mono truncate">
                {entity.source_tables[0]}
              </span>
            )}
          </div>
        </div>

        {entity.description && (
          <p className="text-[11px] text-zinc-500 mt-2 leading-relaxed line-clamp-2">
            {entity.description}
          </p>
        )}
      </div>

      {/* Lifecycle states */}
      {entity.has_lifecycle && entity.lifecycle_states.length > 0 && (
        <div className="px-3.5 py-2 border-b border-zinc-700/40">
          <p className="text-[8px] text-zinc-600 uppercase tracking-widest mb-1.5 font-semibold">
            {entity.lifecycle_column ?? "status"}
          </p>
          <div className="flex flex-wrap gap-1">
            {entity.lifecycle_states.map(s => {
              const isTerminal = entity.terminal_states.includes(s);
              return (
                <span
                  key={s}
                  className={cn(
                    "text-[11px] font-mono rounded-md px-1.5 py-0.5 border",
                    isTerminal
                      ? "text-zinc-600 border-zinc-700/60 bg-zinc-800/40"
                      : "text-sky-300 border-sky-500/20 bg-sky-500/8",
                  )}
                >
                  {s}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer — counts + investigate */}
      <div className="px-3.5 py-2 flex items-center gap-2">
        {actionCount > 0 && (
          <span className="text-[11px] text-amber-400/50">
            {actionCount} action{actionCount !== 1 ? "s" : ""}
          </span>
        )}
        {metricCount > 0 && (
          <span className="text-[11px] text-emerald-400/50">
            {metricCount} metric{metricCount !== 1 ? "s" : ""}
          </span>
        )}
        {onInvestigate && (
          <button
            className="ml-auto text-[11px] text-violet-400/60 hover:text-violet-300 border border-violet-500/15 hover:border-violet-400/35 rounded-md px-1.5 py-0.5 transition"
            onClick={(e) => {
              e.stopPropagation();
              const q = entity.active_filter
                ? `Investigate ${entity.display_name}: what is driving recent changes? Focus on active records (${entity.active_filter}).`
                : `Investigate ${entity.display_name}: what is driving recent changes in this entity?`;
              onInvestigate(q);
            }}
          >
            Investigate →
          </button>
        )}
      </div>
    </div>
  );
}

// ── Flowing edge SVG ──────────────────────────────────────────────────────────

interface EdgeData {
  rel: OntologyRelationship;
  x1: number; y1: number;
  x2: number; y2: number;
}

/** Evaluate a cubic bezier at t ∈ [0,1]. */
function cubicBezier(
  p0: number, p1: number, p2: number, p3: number, t: number,
): number {
  const u = 1 - t;
  return u*u*u*p0 + 3*u*u*t*p1 + 3*u*t*t*p2 + t*t*t*p3;
}

function FlowEdges({
  edges,
  dimmedEdges,
  canvasW,
  canvasH,
  hoveredEdgeId,
  onHoverEdge,
  onClickEdge,
}: {
  edges: EdgeData[];
  dimmedEdges: Set<string>;
  canvasW: number;
  canvasH: number;
  hoveredEdgeId: string | null;
  onHoverEdge: (id: string | null) => void;
  onClickEdge?: (rel: OntologyRelationship) => void;
}) {
  return (
    <svg
      className="absolute inset-0 overflow-visible"
      width={canvasW}
      height={canvasH}
      style={{ zIndex: 0, pointerEvents: "none" }}
    >
      <defs>
        {/* Arrow markers — inferred / exact / verified */}
        <marker id="arr-inf" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="#4e9dcc" opacity="0.65" />
        </marker>
        <marker id="arr-ver" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="#34d399" opacity="0.8" />
        </marker>
        <marker id="arr-hi" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="#a78bfa" />
        </marker>
      </defs>

      {edges.map(({ rel, x1, y1, x2, y2 }) => {
        const verified = rel.join_confidence === "verified";
        const isDimmed = dimmedEdges.has(rel.id);
        const isHovered = hoveredEdgeId === rel.id;

        const goRight = x2 >= x1;
        const dx = Math.max(80, Math.abs(x2 - x1) * 0.46);
        const cpx1 = x1 + (goRight ? dx : -dx);
        const cpx2 = x2 - (goRight ? dx : -dx);
        const d = `M${x1},${y1} C${cpx1},${y1} ${cpx2},${y2} ${x2},${y2}`;

        // midpoint for labels
        const mx = cubicBezier(x1, cpx1, cpx2, x2, 0.5);
        const my = cubicBezier(y1, y1, y2, y2, 0.5);

        const baseColor   = verified ? "#34d399" : "#4e9dcc";
        const hoverColor  = "#a78bfa";
        const stroke      = isHovered ? hoverColor : baseColor;
        const markerEnd   = isHovered ? "url(#arr-hi)" : verified ? "url(#arr-ver)" : "url(#arr-inf)";
        const opacity     = isDimmed ? 0.08 : isHovered ? 1 : 0.65;

        return (
          <g
            key={rel.id}
            opacity={opacity}
            style={{ pointerEvents: "auto", cursor: onClickEdge ? "pointer" : "default" }}
            onMouseEnter={() => onHoverEdge(rel.id)}
            onMouseLeave={() => onHoverEdge(null)}
            onClick={() => onClickEdge?.(rel)}
          >
            {/* Wide invisible hit area */}
            <path d={d} fill="none" stroke="transparent" strokeWidth={14} />

            {/* Glow on hover */}
            {isHovered && (
              <path
                d={d}
                fill="none"
                stroke={hoverColor}
                strokeWidth={8}
                opacity={0.12}
              />
            )}

            {/* Base line (solid for verified, barely-there for inferred) */}
            <path
              d={d}
              fill="none"
              stroke={stroke}
              strokeWidth={verified ? 1.5 : 1}
              opacity={verified ? 0.4 : 0.25}
              markerEnd={markerEnd}
            />

            {/* Animated flow overlay */}
            {verified ? (
              /* Verified — tiny dot shimmer on a solid line */
              <path
                d={d}
                fill="none"
                stroke={isHovered ? hoverColor : "#34d399"}
                strokeWidth={2}
                strokeDasharray="3 30"
                style={{
                  animation: "edge-flow-verified 2.2s linear infinite",
                }}
              />
            ) : (
              /* Inferred / exact — flowing dashes */
              <path
                d={d}
                fill="none"
                stroke={isHovered ? hoverColor : "#4e9dcc"}
                strokeWidth={1.5}
                strokeDasharray="5 7"
                style={{
                  animation: `edge-flow ${rel.join_confidence === "exact" ? "1.6s" : "1.2s"} linear infinite`,
                }}
              />
            )}

            {/* Verb label — always visible (primary edge label) */}
            {(() => {
              const verbText = rel.verb.toLowerCase().replace(/_/g, " ");
              const verbW = Math.max(40, verbText.length * 5.4 + 16);
              return (
                <g transform={`translate(${mx},${my})`}>
                  <rect
                    x={-verbW / 2} y={-9} width={verbW} height={18} rx={5}
                    fill={isHovered ? "#1e1b2e" : "#13181f"}
                    stroke={isHovered ? hoverColor : baseColor}
                    strokeWidth={isHovered ? 1 : 0.7}
                    opacity={0.97}
                  />
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={9}
                    fontFamily="system-ui, sans-serif"
                    fill={isHovered ? hoverColor : baseColor}
                    fontStyle="italic"
                  >
                    {verbText}
                  </text>
                </g>
              );
            })()}

            {/* Cardinality badge — hover only (secondary info) */}
            {isHovered && (
              <g transform={`translate(${mx},${my + 20})`}>
                <rect
                  x={-14} y={-7} width={28} height={14} rx={3}
                  fill="#1a2030" stroke={hoverColor} strokeWidth={0.6} opacity={0.85}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={8}
                  fontFamily="monospace"
                  fill={hoverColor}
                  opacity={0.75}
                >
                  {rel.cardinality}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Causal edges overlay ──────────────────────────────────────────────────────
// Rendered on top of structural edges; dashed orange arrows between entities.

function CausalEdges({
  causalEdges,
  nodeMap,
  canvasW,
  canvasH,
}: {
  causalEdges: CausalEdge[];
  nodeMap: Record<string, { x: number; y: number; h: number }>;
  canvasW: number;
  canvasH: number;
}) {
  const positioned = useMemo(() => {
    return causalEdges.flatMap(e => {
      if (!e.from_entity || !e.to_entity) return [];
      const src = nodeMap[e.from_entity];
      const dst = nodeMap[e.to_entity];
      if (!src || !dst) return [];
      const y1 = src.y + src.h / 2 + 8;   // slight vertical offset from structural edges
      const y2 = dst.y + dst.h / 2 + 8;
      let x1: number, x2: number;
      if (src.x + NODE_W <= dst.x) {
        x1 = src.x + NODE_W; x2 = dst.x;
      } else if (dst.x + NODE_W <= src.x) {
        x1 = src.x; x2 = dst.x + NODE_W;
      } else {
        x1 = src.x + NODE_W * 0.75;
        x2 = dst.x + NODE_W * 0.25;
      }
      return [{ edge: e, x1, y1, x2, y2 }];
    });
  }, [causalEdges, nodeMap]);

  if (positioned.length === 0) return null;

  return (
    <svg
      className="absolute inset-0 overflow-visible"
      width={canvasW}
      height={canvasH}
      style={{ zIndex: 1, pointerEvents: "none" }}
    >
      <defs>
        <marker id="arr-causal" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="#f97316" opacity="0.9" />
        </marker>
      </defs>
      {positioned.map(({ edge, x1, y1, x2, y2 }) => {
        const goRight = x2 >= x1;
        const dx = Math.max(80, Math.abs(x2 - x1) * 0.46);
        const cpx1 = x1 + (goRight ? dx : -dx);
        const cpx2 = x2 - (goRight ? dx : -dx);
        const d = `M${x1},${y1} C${cpx1},${y1} ${cpx2},${y2} ${x2},${y2}`;
        const mx = cubicBezier(x1, cpx1, cpx2, x2, 0.5);
        const my = cubicBezier(y1, y1, y2, y2, 0.5);
        const weightLabel = edge.weight > 1 ? `×${edge.weight}` : "";
        return (
          <g key={edge.id} opacity={0.75}>
            <path
              d={d}
              fill="none"
              stroke="#f97316"
              strokeWidth={1.5}
              strokeDasharray="6 4"
              markerEnd="url(#arr-causal)"
            />
            {weightLabel && (
              <g transform={`translate(${mx},${my - 14})`}>
                <rect x={-12} y={-7} width={24} height={14} rx={3} fill="#1a1008" stroke="#f97316" strokeWidth={0.7} opacity={0.9} />
                <text textAnchor="middle" dominantBaseline="central" fontSize={8} fontFamily="monospace" fill="#fb923c">{weightLabel}</text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────

function CanvasLegend({ showCausal }: { showCausal: boolean }) {
  return (
    <div className="absolute top-4 left-4 flex items-center gap-4 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-4 py-2.5 pointer-events-none flex-wrap">
      {/* Entity types */}
      <span className="text-[11px] text-zinc-600 uppercase tracking-wider font-semibold">Objects</span>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-3 rounded-md bg-emerald-700/25 border border-emerald-600/30" />
        <span className="text-[11px] text-zinc-500">reference data</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-3 rounded-md bg-sky-700/25 border border-sky-600/30" />
        <span className="text-[11px] text-zinc-500">business object</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-3 rounded-md bg-violet-700/25 border border-violet-600/30" />
        <span className="text-[11px] text-zinc-500">event</span>
      </div>
      {/* Divider */}
      <span className="text-zinc-700 text-[11px]">|</span>
      {/* Relationships */}
      <span className="text-[11px] text-zinc-600 uppercase tracking-wider font-semibold">Links</span>
      <div className="flex items-center gap-1.5">
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="#4e9dcc" strokeWidth="1.5"
            strokeDasharray="5 7" style={{ animation: "edge-flow 1.2s linear infinite" }} />
        </svg>
        <span className="text-[11px] text-zinc-500">inferred</span>
      </div>
      <div className="flex items-center gap-1.5">
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="#34d399" strokeWidth="1.5"
            strokeDasharray="3 30" style={{ animation: "edge-flow-verified 2.2s linear infinite" }} />
        </svg>
        <span className="text-[11px] text-zinc-500">verified</span>
      </div>
      <div className="flex items-center gap-1.5" style={{ opacity: showCausal ? 1 : 0.3 }}>
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="#f97316" strokeWidth="1.5" strokeDasharray="6 4" />
        </svg>
        <span className="text-[11px] text-zinc-500">causal</span>
      </div>
    </div>
  );
}

// ── Column labels ─────────────────────────────────────────────────────────────

// Colour mapping per semantic column type
const COL_LABEL_STYLE: Record<string, string> = {
  Foundation: "text-emerald-600/70",
  Objects:    "text-sky-600/60",
  Events:     "text-violet-600/60",
  Standalone: "text-zinc-700",
};

function ColLabels({ labels }: { labels: { x: number; label: string }[] }) {
  return (
    <>
      {labels.map(({ x, label }) => (
        <div
          key={x}
          className={cn(
            "absolute text-[11px] uppercase tracking-widest font-semibold pointer-events-none",
            COL_LABEL_STYLE[label] ?? "text-zinc-700",
          )}
          style={{ left: x, top: 20 }}
        >
          {label}
        </div>
      ))}
    </>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

const INITIAL_ZOOM   = 1.0;
const CANVAS_OVERFLOW = 600;   // extra dotted space beyond content on each side

export function OntologyCanvas({
  graph,
  connId,
  selectedEntityId,
  onSelectEntity,
  onInvestigate,
  onClickEdge,
}: {
  graph: OntologyGraph;
  connId?: string;
  selectedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
  onInvestigate?: (q: string) => void;
  onClickEdge?: (rel: OntologyRelationship) => void;
}) {
  const [hoveredEntityId, setHoveredEntityId] = useState<string | null>(null);
  const [hoveredEdgeId,   setHoveredEdgeId]   = useState<string | null>(null);
  const [zoom,            setZoom]             = useState(INITIAL_ZOOM);
  const [causalEdges,     setCausalEdges]      = useState<CausalEdge[]>([]);
  const [showCausal,      setShowCausal]       = useState(true);

  useEffect(() => {
    if (!connId) return;
    getCausalGraph(connId).then(setCausalEdges).catch(() => {});
  }, [connId]);

  const { nodes, colLabels, canvasW: rawW, canvasH: rawH } = useMemo(() => computeLayout(graph), [graph]);
  // Extend canvas with overflow so the dotted background continues well past content
  // (gives plenty of room when zooming out or panning)
  const canvasW = rawW + CANVAS_OVERFLOW;
  const canvasH = rawH + CANVAS_OVERFLOW;
  const nodeMap = useMemo(
    () => Object.fromEntries(nodes.map(n => [n.entity.id, n])),
    [nodes],
  );

  // Which entity relationships belong to
  const relsByEntity = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const r of Object.values(graph.relationships)) {
      (m[r.from_entity] ??= []).push(r.id);
      (m[r.to_entity]   ??= []).push(r.id);
    }
    return m;
  }, [graph]);

  const focusId = hoveredEntityId ?? selectedEntityId;

  // Neighbour set for the focused entity
  const neighbourIds = useMemo(() => {
    if (!focusId) return new Set<string>();
    const s = new Set([focusId]);
    for (const rid of relsByEntity[focusId] ?? []) {
      const r = graph.relationships[rid];
      if (r) { s.add(r.from_entity); s.add(r.to_entity); }
    }
    return s;
  }, [focusId, relsByEntity, graph.relationships]);

  // Dimmed edges = edges not touching the focused entity
  const dimmedEdges = useMemo(() => {
    if (!focusId) return new Set<string>();
    const active = new Set(relsByEntity[focusId] ?? []);
    return new Set(
      Object.keys(graph.relationships).filter(id => !active.has(id)),
    );
  }, [focusId, relsByEntity, graph.relationships]);

  // Build positioned edges
  const edges: EdgeData[] = useMemo(() => {
    return Object.values(graph.relationships).flatMap(rel => {
      const src = nodeMap[rel.from_entity];
      const dst = nodeMap[rel.to_entity];
      if (!src || !dst) return [];

      const srcMidY = src.y + src.h / 2;
      const dstMidY = dst.y + dst.h / 2;

      let x1: number, x2: number;
      if (src.x + NODE_W <= dst.x) {
        x1 = src.x + NODE_W; x2 = dst.x;
      } else if (dst.x + NODE_W <= src.x) {
        x1 = src.x; x2 = dst.x + NODE_W;
      } else {
        // Same column — self-loop offset
        x1 = src.x + NODE_W * 0.75;
        x2 = dst.x + NODE_W * 0.25;
      }

      return [{ rel, x1, y1: srcMidY, x2, y2: dstMidY }];
    });
  }, [graph.relationships, nodeMap]);

  return (
    <div className="w-full h-full relative" style={{ background: "#11171D" }}>

      {/* Zoom controls + causal toggle — pinned top-right, outside scroll area */}
      <div className="absolute top-3 right-3 z-20 flex items-center gap-1 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-2.5 py-1.5 pointer-events-auto select-none">
        {/* Causal arrows toggle */}
        <button
          onClick={() => setShowCausal(v => !v)}
          title={showCausal ? "Hide causal arrows" : "Show causal arrows"}
          className={cn(
            "flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md border transition",
            showCausal
              ? "text-orange-400 border-orange-500/30 bg-orange-500/10 hover:bg-orange-500/15"
              : "text-zinc-600 border-zinc-700/50 hover:text-zinc-400",
          )}
        >
          <svg width="14" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="10" y2="4" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
            <path d="M8,1.5 L13,4 L8,6.5 Z" fill="currentColor" />
          </svg>
          causal
        </button>

        <div className="w-px h-3 bg-zinc-700 mx-0.5" />

        <button
          onClick={() => setZoom(z => Math.max(0.2, +((z - 0.1).toFixed(2))))}
          className="w-5 h-5 flex items-center justify-center text-zinc-400 hover:text-zinc-200 text-base font-mono transition"
        >−</button>
        <span className="text-[11px] font-mono text-zinc-400 w-8 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom(z => Math.min(2.0, +((z + 0.1).toFixed(2))))}
          className="w-5 h-5 flex items-center justify-center text-zinc-400 hover:text-zinc-200 text-base font-mono transition"
        >+</button>
        <div className="w-px h-3 bg-zinc-700 mx-0.5" />
        <button
          onClick={() => setZoom(INITIAL_ZOOM)}
          className="text-[11px] text-zinc-500 hover:text-zinc-300 transition px-1"
        >100%</button>
      </div>

      {/* Scrollable canvas area */}
      <div className="w-full h-full overflow-auto">
        {/* Spacer sized to scaled canvas dimensions — determines scroll range */}
        <div style={{ width: canvasW * zoom, height: canvasH * zoom, position: "relative", minWidth: "100%" }}>
          {/* Actual canvas, scaled from top-left */}
          <div
            className="relative"
            style={{
              width: canvasW,
              height: canvasH,
              transform: `scale(${zoom})`,
              transformOrigin: "top left",
              position: "absolute",
              top: 0,
              left: 0,
              backgroundImage: "radial-gradient(circle, #2a3140 1.2px, transparent 1.2px)",
              backgroundSize: "24px 24px",
            }}
          >
            <ColLabels labels={colLabels} />

            <FlowEdges
              edges={edges}
              dimmedEdges={dimmedEdges}
              canvasW={canvasW}
              canvasH={canvasH}
              hoveredEdgeId={hoveredEdgeId}
              onHoverEdge={setHoveredEdgeId}
              onClickEdge={onClickEdge}
            />

            {showCausal && (
              <CausalEdges
                causalEdges={causalEdges}
                nodeMap={nodeMap}
                canvasW={canvasW}
                canvasH={canvasH}
              />
            )}

            {nodes.map(nl => {
              const actionCount = Object.values(graph.actions).filter(
                a => a.entity === nl.entity.id,
              ).length;
              const metricCount = Object.values(graph.metrics).filter(
                m => m.entity === nl.entity.id,
              ).length;
              const isDimmed = focusId !== null && !neighbourIds.has(nl.entity.id);
              const isNeighbour =
                focusId !== null &&
                neighbourIds.has(nl.entity.id) &&
                nl.entity.id !== selectedEntityId;

              return (
                <EntityNode
                  key={nl.entity.id}
                  layout={nl}
                  isSelected={selectedEntityId === nl.entity.id}
                  isNeighbour={isNeighbour}
                  isDimmed={isDimmed}
                  actionCount={actionCount}
                  metricCount={metricCount}
                  onClick={() =>
                    onSelectEntity(
                      nl.entity.id === selectedEntityId ? null : nl.entity.id,
                    )
                  }
                  onMouseEnter={() => setHoveredEntityId(nl.entity.id)}
                  onMouseLeave={() => setHoveredEntityId(null)}
                  onInvestigate={onInvestigate}
                />
              );
            })}

            <CanvasLegend showCausal={showCausal} />
          </div>
        </div>
      </div>
    </div>
  );
}
