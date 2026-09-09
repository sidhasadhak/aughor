"use client";

/**
 * ERDiagram — the schema's entity-relationship view.
 *
 * Rendering is React Flow, the same engine as the automation graph, the trace
 * view and the agent map; layout is dagre. What used to live here was a
 * hand-written layering pass plus a hand-written measure-and-draw loop for the
 * connector lines — roughly two hundred lines re-implementing pan, zoom, drag
 * and edge routing that the canvas already had.
 *
 * Two things survived that rewrite because no library knows them:
 *
 *   1. The semantic bucketing (dimension / bridge / fact / isolated). That is
 *      warehouse knowledge read off join direction, and it is the reason the
 *      diagram reads left-to-right the way an analyst expects.
 *   2. Column-level anchoring. An edge lands on the exact field it joins on,
 *      not on the side of the card, which is what makes a wide schema legible.
 *
 * Both are preserved here — (1) as dagre rank hints, (2) as one pair of React
 * Flow handles per column row.
 */

import { createContext, memo, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useNodesState,
  type Edge as RFEdge,
  type Node as RFNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";

import { Icon } from "@/components/ui/icon";
import { formatCount } from "@/lib/format";
import type { RichSchema, SchemaColumn, SchemaJoin, SchemaTable } from "@/lib/api";

// ── Card geometry ─────────────────────────────────────────────────────────────
// dagre is told the height each card will occupy, so these have to match what
// TableNode actually renders. Change one, change the other.
const CARD_W    = 264;
const LABEL_H   = 18;   // the "Table" caption above the card
const LABEL_GAP = 4;    // the gap-1 between caption and card
const HEADER_H  = 54;
const ROW_H     = 26;
const FOOTER_H  = 32;   // "Show N more"

const LAYER_GAP = 130;
const CARD_GAP  = 40;

/** Height past which a role's column wraps into adjacent sub-columns. */
const MAX_LANE_H = 1500;

// ── Semantics ─────────────────────────────────────────────────────────────────

/** Columns that are a primary key: literally named `id`, or referenced by a join. */
function buildPkSet(tables: SchemaTable[], joins: SchemaJoin[]): Set<string> {
  const pks = new Set<string>();
  for (const t of tables)
    for (const c of t.columns)
      if (c.name.toLowerCase() === "id") pks.add(`${t.name}.${c.name}`);
  for (const j of joins) pks.add(`${j.t2}.${j.c2}`);
  return pks;
}

/** PKs → FKs → the rest, so key columns are always in the collapsed slice. */
function sortCols(table: SchemaTable, pkSet: Set<string>): SchemaColumn[] {
  return [...table.columns].sort((a, b) => {
    const rank = (c: SchemaColumn) =>
      pkSet.has(`${table.name}.${c.name}`) ? 0 : c.is_fk ? 1 : 2;
    return rank(a) !== rank(b) ? rank(a) - rank(b) : a.name.localeCompare(b.name);
  });
}

/**
 * Columns visible while collapsed. Every join endpoint is included even when it
 * is neither an inferred PK nor flagged `is_fk` — an edge whose handle is not
 * rendered is an edge React Flow silently drops.
 */
function buildKeySet(tables: SchemaTable[], joins: SchemaJoin[], pkSet: Set<string>): Set<string> {
  const keys = new Set<string>(pkSet);
  for (const t of tables)
    for (const c of t.columns)
      if (c.is_fk) keys.add(`${t.name}.${c.name}`);
  for (const j of joins) {
    keys.add(`${j.t1}.${j.c1}`);
    keys.add(`${j.t2}.${j.c2}`);
  }
  return keys;
}

/**
 * The role each table plays, read off join direction:
 *   0 dimension — only referenced, never references
 *   1 bridge    — both
 *   2 fact      — references others, never referenced
 *   3 isolated  — no joins at all
 */
function semanticLayers(tables: SchemaTable[], joins: SchemaJoin[]): Record<string, number> {
  const out: Record<string, number> = {};
  const inn: Record<string, number> = {};
  for (const t of tables) { out[t.name] = 0; inn[t.name] = 0; }
  for (const j of joins) {
    if (j.t1 in out) out[j.t1] += 1;
    if (j.t2 in inn) inn[j.t2] += 1;
  }
  const layer: Record<string, number> = {};
  for (const t of tables) {
    const o = out[t.name], i = inn[t.name];
    layer[t.name] = (o === 0 && i === 0) ? 3 : o === 0 ? 0 : i === 0 ? 2 : 1;
  }
  return layer;
}

function cardHeight(table: SchemaTable, keySet: Set<string>, expanded: boolean): number {
  const visible = expanded
    ? table.columns.length
    : table.columns.filter(c => keySet.has(`${table.name}.${c.name}`)).length;
  const hasMore = table.columns.length > visible;
  return LABEL_H + LABEL_GAP + HEADER_H + visible * ROW_H + (hasMore ? FOOTER_H : 0);
}

// ── Layout ────────────────────────────────────────────────────────────────────

/**
 * Layout: dagre decides the vertical order, the semantic role decides the column.
 *
 * dagre is very good at the hard part — ordering nodes within a rank so edges
 * cross as little as possible — and has no opinion worth having about which
 * column a dimension table belongs in. Left alone it drags a pure dimension into
 * the middle of the diagram whenever that shortens its outgoing edges.
 *
 * Constraining dagre's own ranker instead was measurably worse. `minlen` is a
 * lower bound, so it can push a node right but never pull one left; bounding
 * both sides needs an invisible anchor per role, and because dagre rejects
 * `minlen: 0` those anchors have to sit two ranks apart — which inserts an empty
 * gutter column between every pair of lanes. Measured on LuxExperience (14
 * tables, 14 joins) against this function:
 *
 *     anchor-constrained   6 columns   2624×1783   16445px of edge
 *     plain dagre          5 columns   1840×1098    8675px   (7/41 roles wrong)
 *     this                 4 columns   1446×1056    7288px   (0/41 roles wrong)
 *
 * So dagre runs unconstrained, and only its vertical ordering is kept: tables
 * are then stacked into their own role's column in that order. One role is
 * always exactly one column, which the anchor version could not promise — a
 * within-role join draws as a sideways edge rather than splitting the lane.
 */
function layout(
  tables: SchemaTable[],
  joins: SchemaJoin[],
  keySet: Set<string>,
  expanded: Set<string>,
): { pos: Record<string, { x: number; y: number }>; laneOf: Record<string, number> } {
  const layerOf = semanticLayers(tables, joins);

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", ranksep: LAYER_GAP, nodesep: CARD_GAP, ranker: "network-simplex" });
  g.setDefaultEdgeLabel(() => ({}));

  const heights: Record<string, number> = {};
  for (const t of tables) {
    heights[t.name] = cardHeight(t, keySet, expanded.has(t.name));
    g.setNode(t.name, { width: CARD_W, height: heights[t.name] });
  }
  // PK side → FK side, so dimensions rank left and facts right.
  for (const j of joins)
    if (j.t1 !== j.t2) g.setEdge(j.t2, j.t1, { minlen: 1, weight: 1 });

  dagre.layout(g);

  const lanes = [...new Set(tables.map(t => layerOf[t.name]))].sort((a, b) => a - b);
  const byLane: Record<number, SchemaTable[]> = {};
  for (const t of tables) (byLane[layerOf[t.name]] ??= []).push(t);
  for (const lane of lanes)
    byLane[lane].sort((a, b) => g.node(a.name).y - g.node(b.name).y);

  // A role with many tables would otherwise be one very tall column — a
  // warehouse with 17 dimensions produced a 1446×3257 strip. Wrap an oversized
  // lane across adjacent sub-columns instead: the role still reads as one band,
  // and the diagram stays closer to the shape of a screen.
  const stackHeight = (ts: SchemaTable[]) =>
    ts.reduce((sum, t) => sum + heights[t.name] + CARD_GAP, -CARD_GAP);

  const columns: SchemaTable[][] = [];
  const laneOfColumn: number[] = [];
  for (const lane of lanes) {
    const cards = byLane[lane];
    const total = stackHeight(cards);
    const parts = Math.max(1, Math.ceil(total / MAX_LANE_H));
    const target = total / parts;
    let current: SchemaTable[] = [];
    let done = 0;
    for (const t of cards) {
      // Keep dagre's order; break to a new sub-column once one is full enough,
      // leaving the remainder to the last so it is never starved.
      if (current.length && done < parts - 1 && stackHeight(current) >= target) {
        columns.push(current); laneOfColumn.push(lane); current = []; done += 1;
      }
      current.push(t);
    }
    columns.push(current); laneOfColumn.push(lane);
  }

  const tallest = Math.max(...columns.map(stackHeight));
  const pos: Record<string, { x: number; y: number }> = {};
  const laneOf: Record<string, number> = {};
  columns.forEach((cards, i) => {
    // Centre each column against the tallest, so a column holding one table
    // sits beside the middle of one holding six rather than pinned to the top.
    let y = (tallest - stackHeight(cards)) / 2;
    for (const t of cards) {
      pos[t.name] = { x: i * (CARD_W + LAYER_GAP), y };
      laneOf[t.name] = laneOfColumn[i];
      y += heights[t.name] + CARD_GAP;
    }
  });
  return { pos, laneOf };
}

// ── Node ──────────────────────────────────────────────────────────────────────

/**
 * The expand callback reaches TableNode through context rather than through
 * `data`. A handler in `data` is a new function identity on every render, which
 * defeats the `memo` below and re-renders every card on any state change.
 */
const ExpandContext = createContext<(table: string) => void>(() => {});

interface TableNodeData extends Record<string, unknown> {
  table: SchemaTable;
  keys: string[];
  pks: string[];
  expanded: boolean;
}

const TableNode = memo(function TableNode({ data }: { data: TableNodeData }) {
  const onExpand = useContext(ExpandContext);
  const { table, expanded } = data;

  const pkSet  = useMemo(() => new Set(data.pks), [data.pks]);
  const keySet = useMemo(() => new Set(data.keys), [data.keys]);

  const sorted = useMemo(() => sortCols(table, pkSet), [table, pkSet]);
  const visible = expanded ? sorted : sorted.filter(c => keySet.has(`${table.name}.${c.name}`));
  const hiddenCount = sorted.length - visible.length;

  return (
    <div className="flex flex-col gap-1" style={{ width: CARD_W }}>
      <span
        className="aug-fs-xs text-zinc-500 px-0.5"
        style={{ height: LABEL_H, lineHeight: `${LABEL_H}px` }}
      >
        Table
      </span>

      <div className="rounded-[var(--r3)] border border-zinc-600 overflow-hidden shadow-lg shadow-black/40">
        {/* Header */}
        <div
          className="flex items-center gap-2.5 px-3 bg-zinc-900 border-b border-zinc-700/80"
          style={{ height: HEADER_H }}
        >
          <div className="w-7 h-7 rounded bg-indigo-950/80 border border-indigo-800/50 flex items-center justify-center text-indigo-300 shrink-0">
            <Icon name="table" size={16} label="Table" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="aug-fs-sm font-semibold font-mono text-zinc-100 truncate leading-snug">
              {table.name}
            </div>
            {table.row_count && (
              <div className="aug-fs-xs font-mono text-zinc-500 leading-none mt-px">
                {formatCount(Number(table.row_count))} rows
              </div>
            )}
          </div>
        </div>

        {/* Column rows — each one carries its own pair of anchors, which is what
            lets an edge land on the field it actually joins on. */}
        <div className="bg-zinc-800 divide-y divide-zinc-700/40">
          {visible.map(col => {
            const isPk = pkSet.has(`${table.name}.${col.name}`);
            const type = col.type.replace(/\(.*\)/, "").trim();
            return (
              <div
                key={col.name}
                className="relative flex items-center gap-2 px-3 hover:bg-zinc-700/30 transition-colors"
                style={{ height: ROW_H }}
              >
                <Handle
                  type="target"
                  id={`${col.name}__t`}
                  position={Position.Left}
                  isConnectable={false}
                  style={{ opacity: 0 }}
                />
                <Handle
                  type="source"
                  id={`${col.name}__s`}
                  position={Position.Right}
                  isConnectable={false}
                  style={{ opacity: 0 }}
                />
                {/* Right-hand target, used only by a join between two tables in
                    the same lane — it lets the edge bulge into the gutter
                    instead of cutting back across its own column. */}
                <Handle
                  type="target"
                  id={`${col.name}__rt`}
                  position={Position.Right}
                  isConnectable={false}
                  style={{ opacity: 0 }}
                />
                <div className="w-7 flex items-center justify-center shrink-0">
                  {isPk ? (
                    <span className="aug-fs-xs font-bold text-amber-400 border border-amber-400/50 rounded px-[3px] py-px leading-tight">
                      PK
                    </span>
                  ) : col.is_fk ? (
                    <span className="aug-fs-xs font-bold text-violet-400 border border-violet-400/50 rounded px-[3px] py-px leading-tight">
                      FK
                    </span>
                  ) : null}
                </div>
                <span className="flex-1 aug-fs-xs font-mono text-zinc-300 truncate min-w-0">
                  {col.name}
                </span>
                <span className="aug-fs-xs font-mono text-zinc-500 shrink-0 pl-2">
                  {type}
                </span>
              </div>
            );
          })}
        </div>

        {(hiddenCount > 0 || expanded) && (
          <button
            onClick={() => onExpand(table.name)}
            className="w-full bg-zinc-800 aug-fs-xs text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/50 transition-colors border-t border-zinc-700/50 text-center"
            style={{ height: FOOTER_H, lineHeight: `${FOOTER_H}px` }}
          >
            {expanded
              ? "Show less"
              : `Show ${hiddenCount} more column${hiddenCount !== 1 ? "s" : ""}`}
          </button>
        )}
      </div>
    </div>
  );
});

const NODE_TYPES = { erTable: TableNode };

// ── Diagram ───────────────────────────────────────────────────────────────────

export function ERDiagram({ schema }: { schema: RichSchema }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [nodes, setNodes, onNodesChange] = useNodesState<RFNode<TableNodeData>>([]);

  const onExpand = useCallback((name: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }, []);

  const pkSet  = useMemo(() => buildPkSet(schema.tables, schema.joins), [schema]);
  const keySet = useMemo(() => buildKeySet(schema.tables, schema.joins, pkSet), [schema, pkSet]);

  // Positions are recomputed whenever the schema or an expansion changes; drag
  // is handled by onNodesChange and deliberately survives until the next relayout.
  const { pos: positions, laneOf } = useMemo(
    () => layout(schema.tables, schema.joins, keySet, expanded),
    [schema, keySet, expanded],
  );

  useEffect(() => {
    const pks  = [...pkSet];
    const keys = [...keySet];
    setNodes(schema.tables.map(t => ({
      id: t.name,
      type: "erTable",
      position: positions[t.name] ?? { x: 0, y: 0 },
      data: { table: t, keys, pks, expanded: expanded.has(t.name) },
      draggable: true,
    })) as RFNode<TableNodeData>[]);
  }, [schema, positions, expanded, pkSet, keySet, setNodes]);

  const edges = useMemo<RFEdge[]>(() => schema.joins.map((j, i) => {
    // Both ends in one lane (two bridges that join each other, say): enter from
    // the right so the edge bulges into the gutter rather than crossing back
    // over its own column.
    const sameLane = laneOf[j.t1] !== undefined && laneOf[j.t1] === laneOf[j.t2];
    return {
      id: `${j.t2}.${j.c2}→${j.t1}.${j.c1}#${i}`,
      source: j.t2,
      sourceHandle: `${j.c2}__s`,
      target: j.t1,
      targetHandle: sameLane ? `${j.c1}__rt` : `${j.c1}__t`,
      type: "smoothstep",
      pathOptions: { borderRadius: 8 },
      style: {
        stroke: j.match === "exact" ? "var(--blue4)" : "var(--t3)",
        strokeWidth: 1.4,
        strokeDasharray: j.match === "exact" ? undefined : "4 3",
      },
    };
  }), [schema, laneOf]);

  if (!schema.tables.length) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="aug-fs-xs text-zinc-500">No tables found.</span>
      </div>
    );
  }

  return (
    <ExpandContext.Provider value={onExpand}>
      <div className="w-full h-full">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.15}
          maxZoom={1.8}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#3f3f3d" gap={20} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </ExpandContext.Provider>
  );
}
