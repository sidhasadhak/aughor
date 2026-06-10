"use client";

/**
 * OntologyCanvas — interactive business-process graph.
 *
 * Entity nodes on a dark canvas connected by animated flowing edges that
 * convey relationship direction and confidence.  Click a node to open the
 * detail drawer; hover to highlight the local neighbourhood.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { verbLabel } from "@/lib/format";
import { useWheelZoom } from "@/lib/useWheelZoom";
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

// Compact node geometry — the "light" card used on the org board where many
// clusters are tiled and the heavy detail card would overwhelm the view.
const NODE_W_C   = 168;
const NODE_H_C   = 48;
const LAYER_GAP_C = 90;
const NODE_GAP_C  = 22;

// A cluster is drawn radially (open, roughly circular) when it is small and
// shallow — a star of a few entities reads better as a ring than as columns.
// Larger / deeper clusters keep the left-to-right columnar process layout.
function preferRadial(graph: OntologyGraph): boolean {
  const n = Object.keys(graph.entities).length;
  return n > 1 && n <= 6;
}

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

function nodeHeight(e: OntologyEntity, compact = false): number {
  if (compact) return NODE_H_C;
  const header    = 80;
  const lifecycle = e.has_lifecycle && e.lifecycle_states.length ? 52 : 0;
  const footer    = 32;
  return header + lifecycle + footer;
}

interface LayoutResult {
  nodes: NodeLayout[];
  canvasW: number;
  canvasH: number;
  colLabels: { x: number; label: string }[];
}

// ── Radial layout — open, roughly circular arrangement for small clusters ───────
//
// The highest-degree entity sits at the centre; the rest fan out evenly on a
// ring around it.  Reads as an open star on the dotted background rather than a
// rigid column stack — better for the simple 2–6 entity schemas.
function computeRadialLayout(graph: OntologyGraph, compact: boolean): LayoutResult {
  const NW = compact ? NODE_W_C : NODE_W;
  const entities = Object.values(graph.entities);
  const rels     = Object.values(graph.relationships);

  // degree per entity to pick the hub
  const deg: Record<string, number> = {};
  for (const e of entities) deg[e.id] = 0;
  for (const r of rels) { if (r.from_entity in deg) deg[r.from_entity]++; if (r.to_entity in deg) deg[r.to_entity]++; }
  const sorted = [...entities].sort((a, b) => (deg[b.id] - deg[a.id]) || a.display_name.localeCompare(b.display_name));

  const hub = sorted[0];
  const ring = sorted.slice(1);
  const NH = (e: OntologyEntity) => nodeHeight(e, compact);

  // Ring radius scales with the ring count so cards don't crowd.
  const radius = Math.max(150, ring.length * (compact ? 34 : 52) + 90);
  const cx = radius + NW / 2 + PAD;
  const cy = radius + NH(hub) / 2 + PAD;

  const nodes: NodeLayout[] = [];
  // hub centred
  nodes.push({ entity: hub, x: cx - NW / 2, y: cy - NH(hub) / 2, h: NH(hub), col: 0 });
  ring.forEach((e, i) => {
    const ang = (-Math.PI / 2) + (i * 2 * Math.PI) / ring.length;
    const x = cx + Math.cos(ang) * radius - NW / 2;
    const y = cy + Math.sin(ang) * radius - NH(e) / 2;
    nodes.push({ entity: e, x, y, h: NH(e), col: 1 });
  });

  const canvasW = cx + radius + NW / 2 + PAD;
  const canvasH = cy + radius + NH(hub) / 2 + PAD;
  return { nodes, canvasW, canvasH, colLabels: [] };
}

function computeLayout(graph: OntologyGraph, opts: { compact?: boolean; radial?: boolean } = {}): LayoutResult {
  const compact = !!opts.compact;
  const useRadial = opts.radial ?? (compact && preferRadial(graph));
  if (useRadial && Object.keys(graph.entities).length > 1) {
    return computeRadialLayout(graph, compact);
  }
  const NW       = compact ? NODE_W_C : NODE_W;
  const LAYERGAP = compact ? LAYER_GAP_C : LAYER_GAP;
  const GAPY     = compact ? NODE_GAP_C : NODE_GAP_Y;
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
  cols.forEach((c, i) => { colX[c] = PAD + i * (NW + LAYERGAP); });

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

  // ── Crossing reduction (barycenter / median heuristic) ─────────────────────
  // Columns are fixed by topological depth; WITHIN each column we order nodes to
  // minimise edge crossings rather than alphabetically.  Each node drifts toward
  // the average height of its neighbours, so edges run flat instead of tangling
  // across the whole cluster.  A handful of sweeps converge — this is the classic
  // Sugiyama layer-ordering step (what graphviz/dagre do).
  const undirAdj: Record<string, string[]> = {};
  for (const e of entities) undirAdj[e.id] = [];
  for (const r of rels) {
    if (r.from_entity in undirAdj && r.to_entity in undirAdj && r.from_entity !== r.to_entity) {
      undirAdj[r.from_entity].push(r.to_entity);
      undirAdj[r.to_entity].push(r.from_entity);
    }
  }
  const degree: Record<string, number> = {};
  for (const e of entities) degree[e.id] = undirAdj[e.id].length;

  // order[col] = entity ids, top→bottom.  Seed high-degree first (a stable start
  // that floats the busiest hubs toward the centre after centering).
  const order: Record<number, string[]> = {};
  for (const c of cols) {
    order[c] = byCol[c].map(e => e.id).sort(
      (a, b) =>
        (degree[b] - degree[a]) ||
        graph.entities[a].display_name.localeCompare(graph.entities[b].display_name),
    );
  }

  for (let sweep = 0; sweep < 6; sweep++) {
    // normalised vertical position (0..1) of every node under the current order
    const pos: Record<string, number> = {};
    for (const c of cols) {
      const L = Math.max(1, order[c].length);
      order[c].forEach((id, i) => { pos[id] = (i + 0.5) / L; });
    }
    const prevIdx: Record<string, number> = {};
    for (const c of cols) order[c].forEach((id, i) => { prevIdx[id] = i; });
    for (const c of cols) {
      const bary: Record<string, number> = {};
      for (const id of order[c]) {
        const ns = undirAdj[id];
        bary[id] = ns.length
          ? ns.reduce((s, n) => s + (pos[n] ?? 0.5), 0) / ns.length
          : (prevIdx[id] + 0.5) / Math.max(1, order[c].length); // keep isolated nodes put
      }
      order[c] = [...order[c]].sort((a, b) => (bary[a] - bary[b]) || (prevIdx[a] - prevIdx[b]));
    }
  }

  // ── Vertical centering — align columns around a shared midline so related
  // nodes sit at similar heights (flatter edges, far fewer crossings).
  const colContentH: Record<number, number> = {};
  for (const c of cols) {
    let h = 0;
    for (const id of order[c]) h += nodeHeight(graph.entities[id], compact) + GAPY;
    colContentH[c] = Math.max(0, h - GAPY);
  }
  const tallest = cols.length ? Math.max(...cols.map(c => colContentH[c])) : 0;
  const topPad = PAD + 28;   // room for the column header

  // Place nodes
  const nodes: NodeLayout[] = [];
  for (const col of cols) {
    let y = topPad + (tallest - colContentH[col]) / 2;
    for (const id of order[col]) {
      const e = graph.entities[id];
      const h = nodeHeight(e, compact);
      nodes.push({ entity: e, x: colX[col], y, h, col });
      y += h + GAPY;
    }
  }

  const canvasW = cols.length
    ? colX[cols[cols.length - 1]] + NW + PAD
    : PAD * 2 + NW;

  const canvasH = Math.max(compact ? 160 : 480, topPad + tallest + PAD);

  return { nodes, canvasW, canvasH, colLabels };
}

// ── Entity node card ──────────────────────────────────────────────────────────

// Dot colour per entity type — used by the compact card.
const TYPE_DOT: Record<string, string> = {
  reference_data:  "bg-emerald-400",
  event:           "bg-violet-400",
  standalone:      "bg-zinc-500",
  business_object: "bg-sky-400",
};

function EntityNode({
  layout,
  pos,
  width,
  compact = false,
  draggable = false,
  scale = 1,
  isSelected,
  isNeighbour,
  isDimmed,
  actionCount,
  metricCount,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onInvestigate,
  onDragDelta,
  onDragCommit,
}: {
  layout: NodeLayout;
  pos: { x: number; y: number };
  width: number;
  compact?: boolean;
  draggable?: boolean;
  scale?: number;
  isSelected: boolean;
  isNeighbour: boolean;
  isDimmed: boolean;
  actionCount: number;
  metricCount: number;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onInvestigate?: (q: string) => void;
  onDragDelta?: (dx: number, dy: number) => void;
  onDragCommit?: () => void;
}) {
  const { entity } = layout;
  const { x, y } = pos;
  // Avatar letter — first char of display name, uppercased
  const avatar = entity.display_name.charAt(0).toUpperCase();

  // ── Drag handling (pointer) — deltas are reported in board px (screen ÷ scale)
  const drag = useRef<{ active: boolean; lastX: number; lastY: number; moved: boolean }>(
    { active: false, lastX: 0, lastY: 0, moved: false },
  );
  const onPointerDown = (e: React.PointerEvent) => {
    if (!draggable) return;
    if ((e.target as HTMLElement).closest("button")) return; // let buttons work
    e.stopPropagation();
    try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch {}
    drag.current = { active: true, lastX: e.clientX, lastY: e.clientY, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current.active) return;
    const dx = (e.clientX - drag.current.lastX) / scale;
    const dy = (e.clientY - drag.current.lastY) / scale;
    if (Math.abs(e.clientX - drag.current.lastX) + Math.abs(e.clientY - drag.current.lastY) > 2) drag.current.moved = true;
    drag.current.lastX = e.clientX;
    drag.current.lastY = e.clientY;
    onDragDelta?.(dx, dy);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag.current.active) return;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
    const moved = drag.current.moved;
    drag.current.active = false;
    if (moved) { onDragCommit?.(); } else { onClick(); }
  };

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

  // ── Compact "light" card — a single pill: type dot + name + degree badge.
  if (compact) {
    return (
      <div
        className={cn(
          "absolute rounded-lg border select-none transition-colors duration-150 flex items-center gap-2 px-2.5",
          draggable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
          isSelected
            ? "border-violet-400/60 bg-[#1b2030] ring-1 ring-violet-500/20"
            : isNeighbour
            ? "border-violet-600/35 bg-zinc-900/90"
            : "border-zinc-700/45 bg-zinc-900/70 hover:border-zinc-600/70 hover:bg-zinc-900",
          isDimmed && "opacity-20",
        )}
        style={{ left: x, top: y, width, height: NODE_H_C }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onClick={() => { if (!draggable) onClick(); }}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
        <span className={cn("w-2 h-2 rounded-full shrink-0", TYPE_DOT[entity.entity_type ?? "business_object"] ?? "bg-sky-400")} />
        <span className={cn("text-[12px] font-medium leading-tight truncate flex-1", isSelected ? "text-violet-100" : "text-zinc-200")}>
          {entity.display_name}
        </span>
        {(actionCount > 0 || metricCount > 0) && (
          <span className="text-[10px] text-zinc-500 font-mono shrink-0">
            {actionCount + metricCount}
          </span>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "absolute rounded-md border cursor-pointer select-none transition-all duration-200",
        isNeighbour && !isSelected ? "border-violet-600/35 bg-zinc-900/90" : typeTheme.border,
        isDimmed && "opacity-20 pointer-events-none",
        draggable && "cursor-grab active:cursor-grabbing",
      )}
      style={{ left: x, top: y, width }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={() => { if (!draggable) onClick(); }}
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
              <span className="text-[11px] text-zinc-500 font-mono truncate">
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
          <p className="text-[8px] text-zinc-500 uppercase tracking-widest mb-1.5 font-semibold">
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
                      ? "text-zinc-500 border-zinc-700/60 bg-zinc-800/40"
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
  showLabels = true,
  compact = false,
  hasFocus = false,
}: {
  edges: EdgeData[];
  dimmedEdges: Set<string>;
  canvasW: number;
  canvasH: number;
  hoveredEdgeId: string | null;
  onHoverEdge: (id: string | null) => void;
  onClickEdge?: (rel: OntologyRelationship) => void;
  showLabels?: boolean;
  /** Compact (org overview) — edges rest as calm static threads, lighting up on focus. */
  compact?: boolean;
  /** True when some entity is hovered/selected (so non-related edges should recede). */
  hasFocus?: boolean;
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
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="var(--blue4)" opacity="0.65" />
        </marker>
        <marker id="arr-ver" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="var(--grn4)" opacity="0.8" />
        </marker>
        <marker id="arr-hi" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="var(--vio4)" />
        </marker>
      </defs>

      {edges.map(({ rel, x1, y1, x2, y2 }) => {
        const verified = rel.join_confidence === "verified";
        const isDimmed = dimmedEdges.has(rel.id);
        const isHovered = hoveredEdgeId === rel.id;
        // "Active" = directly tied to the focused entity (so it should pop).
        const isActive = hasFocus && !isDimmed;
        // In compact overview, edges stay calm + static unless involved with focus.
        const lit = isHovered || isActive;
        const animate = !compact || lit;

        const goRight = x2 >= x1;
        const dx = Math.max(80, Math.abs(x2 - x1) * 0.46);
        const cpx1 = x1 + (goRight ? dx : -dx);
        const cpx2 = x2 - (goRight ? dx : -dx);
        const d = `M${x1},${y1} C${cpx1},${y1} ${cpx2},${y2} ${x2},${y2}`;

        // midpoint for labels
        const mx = cubicBezier(x1, cpx1, cpx2, x2, 0.5);
        const my = cubicBezier(y1, y1, y2, y2, 0.5);

        const baseColor   = verified ? "var(--grn4)" : "var(--blue4)";
        const hoverColor  = "var(--vio4)";
        const stroke      = isHovered ? hoverColor : baseColor;
        const markerEnd   = isHovered ? "url(#arr-hi)" : verified ? "url(#arr-ver)" : "url(#arr-inf)";
        const opacity     = isDimmed
          ? (compact ? 0.05 : 0.08)
          : lit
            ? 1
            : compact ? 0.32 : 0.65;

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

            {/* Base line — in calm compact resting state this is the *only* line
                drawn (static thread), so give it enough presence to read. */}
            <path
              d={d}
              fill="none"
              stroke={stroke}
              strokeWidth={verified ? 1.5 : 1}
              opacity={compact && !lit ? 0.9 : verified ? 0.4 : 0.25}
              markerEnd={markerEnd}
            />

            {/* Animated flow overlay — suppressed in compact resting state to keep
                the org overview from shimmering as a hairball. */}
            {animate && (verified ? (
              /* Verified — tiny dot shimmer on a solid line */
              <path
                d={d}
                fill="none"
                stroke={isHovered ? hoverColor : "var(--grn4)"}
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
                stroke={isHovered ? hoverColor : "var(--blue4)"}
                strokeWidth={1.5}
                strokeDasharray="5 7"
                style={{
                  animation: `edge-flow ${rel.join_confidence === "exact" ? "1.6s" : "1.2s"} linear infinite`,
                }}
              />
            ))}

            {/* Verb label — shown in expanded view (or on hover in compact, to
                keep the multi-schema org overview from drowning in pills) */}
            {(showLabels || isHovered || isActive) && (() => {
              const verbText = verbLabel(rel.verb);
              const verbW = Math.max(40, verbText.length * 5.4 + 16);
              return (
                <g transform={`translate(${mx},${my})`}>
                  <rect
                    x={-verbW / 2} y={-9} width={verbW} height={18} rx={5}
                    fill={isHovered ? "var(--vio1)" : "var(--bg-1)"}
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
                  fill="var(--blue1)" stroke={hoverColor} strokeWidth={0.6} opacity={0.85}
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
          <path d="M1,1.5 L7,4 L1,6.5 Z" fill="var(--amb4)" opacity="0.9" />
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
              stroke="var(--amb4)"
              strokeWidth={1.5}
              strokeDasharray="6 4"
              markerEnd="url(#arr-causal)"
            />
            {weightLabel && (
              <g transform={`translate(${mx},${my - 14})`}>
                <rect x={-12} y={-7} width={24} height={14} rx={3} fill="var(--amb1)" stroke="var(--amb4)" strokeWidth={0.7} opacity={0.9} />
                <text textAnchor="middle" dominantBaseline="central" fontSize={8} fontFamily="monospace" fill="var(--amb4)">{weightLabel}</text>
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
    <div className="flex items-center gap-4 bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/50 rounded-lg px-4 py-2.5 pointer-events-none flex-wrap">
      {/* Entity types */}
      <span className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Objects</span>
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
      <span className="text-zinc-500 text-[11px]">|</span>
      {/* Relationships */}
      <span className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold">Links</span>
      <div className="flex items-center gap-1.5">
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="var(--blue4)" strokeWidth="1.5"
            strokeDasharray="5 7" style={{ animation: "edge-flow 1.2s linear infinite" }} />
        </svg>
        <span className="text-[11px] text-zinc-500">inferred</span>
      </div>
      <div className="flex items-center gap-1.5">
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="var(--grn4)" strokeWidth="1.5"
            strokeDasharray="3 30" style={{ animation: "edge-flow-verified 2.2s linear infinite" }} />
        </svg>
        <span className="text-[11px] text-zinc-500">verified</span>
      </div>
      <div className="flex items-center gap-1.5" style={{ opacity: showCausal ? 1 : 0.3 }}>
        <svg width="28" height="8" className="shrink-0">
          <line x1="0" y1="4" x2="28" y2="4" stroke="var(--amb4)" strokeWidth="1.5" strokeDasharray="6 4" />
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
  Standalone: "text-zinc-500",
};

function ColLabels({ labels }: { labels: { x: number; label: string }[] }) {
  return (
    <>
      {labels.map(({ x, label }) => (
        <div
          key={x}
          className={cn(
            "absolute text-[11px] uppercase tracking-widest font-semibold pointer-events-none",
            COL_LABEL_STYLE[label] ?? "text-zinc-500",
          )}
          style={{ left: x, top: 20 }}
        >
          {label}
        </div>
      ))}
    </>
  );
}

// ── Entity cluster ──────────────────────────────────────────────────────────────
//
// The nodes-and-edges graph laid out in a LOCAL coordinate frame (0..w, 0..h),
// with its own hover / neighbour-dimming state.  Reused by both the single-
// connection canvas and the org board, where many clusters are tiled inside
// connection / schema bounding boxes.

/** Cheap size probe for packing clusters into boxes before render. */
export function measureCluster(graph: OntologyGraph, opts: { compact?: boolean } = {}): { w: number; h: number } {
  const { canvasW, canvasH } = computeLayout(graph, opts);
  return { w: canvasW, h: canvasH };
}

// ── Persisted drag offsets ──────────────────────────────────────────────────────
// Keyed per-cluster (connection+schema) so a node nudged on the board stays put
// across reloads.  Stored as { entityId: {dx,dy} } deltas off the computed layout.
type Offsets = Record<string, { dx: number; dy: number }>;

// Drag offsets are DELTAS off the computed layout.  When the layout engine itself
// changes (e.g. alphabetical → barycenter), old deltas point at the wrong base and
// scramble the graph — so we version-stamp them and drop any from an older engine.
const LAYOUT_VERSION = 2;
const posStoreKey = (key: string) => `ont-pos:${key}`;

function loadOffsets(key?: string): Offsets {
  if (!key || typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(posStoreKey(key));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    // Current format: { v, o }.  Anything else (or an older version) is stale.
    if (parsed && typeof parsed === "object" && "v" in parsed) {
      return parsed.v === LAYOUT_VERSION ? (parsed.o ?? {}) : {};
    }
    return {};   // legacy bare-map format predates the barycenter layout — discard
  } catch { return {}; }
}
function saveOffsets(key: string | undefined, o: Offsets) {
  if (!key || typeof window === "undefined") return;
  try { window.localStorage.setItem(posStoreKey(key), JSON.stringify({ v: LAYOUT_VERSION, o })); } catch {}
}
function clearOffsets(key?: string) {
  if (!key || typeof window === "undefined") return;
  try { window.localStorage.removeItem(posStoreKey(key)); } catch {}
}

export function EntityCluster({
  graph,
  selectedEntityId,
  onSelectEntity,
  onInvestigate,
  onClickEdge,
  causalEdges = [],
  showCausal = false,
  showColLabels = true,
  compact = false,
  storageKey,
  scale = 1,
}: {
  graph: OntologyGraph;
  selectedEntityId: string | null;
  onSelectEntity: (id: string | null) => void;
  onInvestigate?: (q: string) => void;
  onClickEdge?: (rel: OntologyRelationship) => void;
  causalEdges?: CausalEdge[];
  showCausal?: boolean;
  showColLabels?: boolean;
  compact?: boolean;
  /** When set, node drags are enabled and persisted under this key. */
  storageKey?: string;
  /** Board zoom — drag deltas are divided by it so movement tracks the cursor. */
  scale?: number;
}) {
  const NW = compact ? NODE_W_C : NODE_W;
  const draggable = !!storageKey;

  const [hoveredEntityId, setHoveredEntityId] = useState<string | null>(null);
  const [hoveredEdgeId,   setHoveredEdgeId]   = useState<string | null>(null);
  // Ref is the source of truth (updated synchronously during a drag); state
  // mirrors it to trigger re-render.  This keeps persistence correct regardless
  // of React's batching between pointermove and pointerup.
  const offsetsRef = useRef<Offsets>(loadOffsets(storageKey));
  const [offsets, setOffsets] = useState<Offsets>(offsetsRef.current);
  useEffect(() => {
    const o = loadOffsets(storageKey);
    offsetsRef.current = o;
    setOffsets(o);
  }, [storageKey]);

  const { nodes, colLabels, canvasW, canvasH } = useMemo(
    () => computeLayout(graph, { compact }),
    [graph, compact],
  );

  // Apply persisted/live drag offsets to layout positions.
  const posOf = (id: string, x: number, y: number) => {
    const o = offsets[id];
    return { x: x + (o?.dx ?? 0), y: y + (o?.dy ?? 0) };
  };
  const nodeMap = useMemo(() => {
    const m: Record<string, { x: number; y: number; h: number }> = {};
    for (const n of nodes) { const p = posOf(n.entity.id, n.x, n.y); m[n.entity.id] = { x: p.x, y: p.y, h: n.h }; }
    return m;
  }, [nodes, offsets]);

  const relsByEntity = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const r of Object.values(graph.relationships)) {
      (m[r.from_entity] ??= []).push(r.id);
      (m[r.to_entity]   ??= []).push(r.id);
    }
    return m;
  }, [graph]);

  const focusId = hoveredEntityId ?? selectedEntityId;

  const neighbourIds = useMemo(() => {
    if (!focusId) return new Set<string>();
    const s = new Set([focusId]);
    for (const rid of relsByEntity[focusId] ?? []) {
      const r = graph.relationships[rid];
      if (r) { s.add(r.from_entity); s.add(r.to_entity); }
    }
    return s;
  }, [focusId, relsByEntity, graph.relationships]);

  const dimmedEdges = useMemo(() => {
    if (!focusId) return new Set<string>();
    const active = new Set(relsByEntity[focusId] ?? []);
    return new Set(Object.keys(graph.relationships).filter(id => !active.has(id)));
  }, [focusId, relsByEntity, graph.relationships]);

  const edges: EdgeData[] = useMemo(() => {
    return Object.values(graph.relationships).flatMap(rel => {
      const src = nodeMap[rel.from_entity];
      const dst = nodeMap[rel.to_entity];
      if (!src || !dst) return [];
      const srcMidY = src.y + src.h / 2;
      const dstMidY = dst.y + dst.h / 2;
      let x1: number, x2: number;
      if (src.x + NW <= dst.x) { x1 = src.x + NW; x2 = dst.x; }
      else if (dst.x + NW <= src.x) { x1 = src.x; x2 = dst.x + NW; }
      else { x1 = src.x + NW * 0.75; x2 = dst.x + NW * 0.25; }
      return [{ rel, x1, y1: srcMidY, x2, y2: dstMidY }];
    });
  }, [graph.relationships, nodeMap, NW]);

  const onDragDelta = (id: string, dx: number, dy: number) => {
    const cur = offsetsRef.current[id] ?? { dx: 0, dy: 0 };
    offsetsRef.current = { ...offsetsRef.current, [id]: { dx: cur.dx + dx, dy: cur.dy + dy } };
    setOffsets(offsetsRef.current);
  };
  const onDragCommit = () => { saveOffsets(storageKey, offsetsRef.current); };

  return (
    <div className="relative" style={{ width: canvasW, height: canvasH }}>
      {showColLabels && !compact && <ColLabels labels={colLabels} />}

      <FlowEdges
        edges={edges}
        dimmedEdges={dimmedEdges}
        canvasW={canvasW}
        canvasH={canvasH}
        hoveredEdgeId={hoveredEdgeId}
        onHoverEdge={setHoveredEdgeId}
        onClickEdge={onClickEdge}
        showLabels={!compact}
        compact={compact}
        hasFocus={focusId !== null}
      />

      {showCausal && (
        <CausalEdges causalEdges={causalEdges} nodeMap={nodeMap} canvasW={canvasW} canvasH={canvasH} />
      )}

      {nodes.map(nl => {
        const actionCount = Object.values(graph.actions).filter(a => a.entity === nl.entity.id).length;
        const metricCount = Object.values(graph.metrics).filter(m => m.entity === nl.entity.id).length;
        const isDimmed = focusId !== null && !neighbourIds.has(nl.entity.id);
        const isNeighbour = focusId !== null && neighbourIds.has(nl.entity.id) && nl.entity.id !== selectedEntityId;
        return (
          <EntityNode
            key={nl.entity.id}
            layout={nl}
            pos={posOf(nl.entity.id, nl.x, nl.y)}
            width={NW}
            compact={compact}
            draggable={draggable}
            scale={scale}
            isSelected={selectedEntityId === nl.entity.id}
            isNeighbour={isNeighbour}
            isDimmed={isDimmed}
            actionCount={actionCount}
            metricCount={metricCount}
            onClick={() => onSelectEntity(nl.entity.id === selectedEntityId ? null : nl.entity.id)}
            onMouseEnter={() => setHoveredEntityId(nl.entity.id)}
            onMouseLeave={() => setHoveredEntityId(null)}
            onInvestigate={onInvestigate}
            onDragDelta={(dx, dy) => onDragDelta(nl.entity.id, dx, dy)}
            onDragCommit={onDragCommit}
          />
        );
      })}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

const INITIAL_ZOOM = 1.0;
// Breathing room on EVERY side of the content so the plane can be panned up/left
// as well as down/right (the content used to be pinned to 0,0 — unreachable above
// or left of origin).  Translating the content inward by PAN_PAD makes negative-
// looking space scrollable.
const PAN_PAD = 1200;

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
  const [zoom,        setZoom]        = useState(INITIAL_ZOOM);
  const [causalEdges, setCausalEdges] = useState<CausalEdge[]>([]);
  const [showCausal,  setShowCausal]  = useState(true);
  // Bumping this remounts the cluster with fresh (computed) positions.
  const [layoutNonce, setLayoutNonce] = useState(0);

  // Scroll viewport — trackpad pinch + ⌘/Ctrl-wheel zoom-to-cursor.
  const scrollRef = useRef<HTMLDivElement>(null);
  useWheelZoom(scrollRef, zoom, setZoom, { min: 0.2, max: 2.0 });

  useEffect(() => {
    if (!connId) return;
    getCausalGraph(connId).then(setCausalEdges).catch(() => {});
  }, [connId]);

  const { w: rawW, h: rawH } = useMemo(() => measureCluster(graph), [graph]);
  // The pannable plane wraps the content with PAN_PAD on every side.
  const planeW = rawW + PAN_PAD * 2;
  const planeH = rawH + PAN_PAD * 2;

  // Center the view on the content on first paint (and when the graph changes),
  // leaving equal room to pan in every direction.
  const centeredKey = useRef<string>("");
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || rawW === 0) return;
    const key = `${connId ?? ""}:${graph.schema_name ?? ""}:${rawW}x${rawH}`;
    if (centeredKey.current === key) return;
    centeredKey.current = key;
    // Put the content's top-left a little inside the viewport.
    el.scrollLeft = PAN_PAD * zoom - 40;
    el.scrollTop  = PAN_PAD * zoom - 40;
  }, [connId, graph.schema_name, rawW, rawH, zoom]);

  // "Tidy" — discard saved drag positions for this cluster and re-run the
  // auto-layout (then re-center).  Lets you snap back to the clean arrangement.
  const tidyLayout = () => {
    clearOffsets(connId ? `${connId}:${graph.schema_name}` : undefined);
    centeredKey.current = "";
    setLayoutNonce(n => n + 1);
  };

  return (
    <div className="w-full h-full relative" style={{ background: "var(--bg-1)" }}>

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
              : "text-zinc-500 border-zinc-700/50 hover:text-zinc-400",
          )}
        >
          <svg width="14" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="10" y2="4" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
            <path d="M8,1.5 L13,4 L8,6.5 Z" fill="currentColor" />
          </svg>
          causal
        </button>

        <div className="w-px h-3 bg-zinc-700 mx-0.5" />

        {/* Tidy — reset dragged positions back to the computed auto-layout */}
        <button
          onClick={tidyLayout}
          title="Tidy — reset to auto-layout"
          className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md border text-zinc-400 border-zinc-700/50 hover:text-violet-300 hover:border-violet-500/30 transition"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="shrink-0">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M3 3v5h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          tidy
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
      <div ref={scrollRef} className="w-full h-full overflow-auto">
        {/* Spacer sized to the scaled, padded plane — determines scroll range on
            every side (incl. above & left of the content). */}
        <div
          style={{
            width: planeW * zoom,
            height: planeH * zoom,
            position: "relative",
            minWidth: "100%",
            backgroundImage: "radial-gradient(circle, var(--b2) 1.2px, transparent 1.2px)",
            backgroundSize: `${24 * zoom}px ${24 * zoom}px`,
          }}
        >
          {/* Actual canvas, translated into the padded plane then scaled from its
              own top-left.  The translate scales with zoom so zoom-to-cursor (in
              useWheelZoom, which works in absolute scroll coords) stays exact. */}
          <div
            className="relative"
            style={{
              width: rawW,
              height: rawH,
              transform: `translate(${PAN_PAD * zoom}px, ${PAN_PAD * zoom}px) scale(${zoom})`,
              transformOrigin: "top left",
              position: "absolute",
              top: 0,
              left: 0,
            }}
          >
            <EntityCluster
              key={layoutNonce}
              graph={graph}
              selectedEntityId={selectedEntityId}
              onSelectEntity={onSelectEntity}
              onInvestigate={onInvestigate}
              onClickEdge={onClickEdge}
              causalEdges={causalEdges}
              showCausal={showCausal}
              scale={zoom}
              storageKey={connId ? `${connId}:${graph.schema_name}` : undefined}
            />
          </div>
        </div>
      </div>

      {/* Legend — pinned top-left, outside scroll/zoom area */}
      <div className="absolute top-3 left-3 z-20 pointer-events-none">
        <CanvasLegend showCausal={showCausal} />
      </div>
    </div>
  );
}
