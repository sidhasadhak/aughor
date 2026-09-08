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
 * dagre, constrained so a table stays in its own role's lane.
 *
 * Left to itself dagre's network simplex shortens edges, which drags a pure
 * dimension into the middle of the diagram whenever that makes its outgoing
 * edges shorter. Measured on theLook: `users` (a dimension) landed in column 1
 * and `events` (a fact) a column early.
 *
 * A `minlen` lower bound alone does not fix that — it can push a node right,
 * never pull one left, so a node already past its minimum is unaffected. The
 * fix is to bound both sides: one invisible anchor per role, chained, with each
 * table pinned between its own anchor and the next. dagre rejects `minlen: 0`,
 * so the anchors sit two ranks apart and each table is pinned one past its own.
 *
 * Note this does not guarantee one column per role: two bridge tables that join
 * each other cannot share a rank, because dagre will not route an edge inside
 * one. That lane splits, which is honest — it shows the dependency.
 */
function layout(
  tables: SchemaTable[],
  joins: SchemaJoin[],
  keySet: Set<string>,
  expanded: Set<string>,
): Record<string, { x: number; y: number }> {
  const layerOf = semanticLayers(tables, joins);
  const maxLayer = Math.max(0, ...Object.values(layerOf));

  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: "LR",
    ranksep: LAYER_GAP,
    nodesep: CARD_GAP,
    marginx: 48,
    marginy: 48,
    ranker: "network-simplex",
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const t of tables)
    g.setNode(t.name, { width: CARD_W, height: cardHeight(t, keySet, expanded.has(t.name)) });

  // PK side → FK side, so dimensions rank left and facts right.
  for (const j of joins)
    if (j.t1 !== j.t2) g.setEdge(j.t2, j.t1, { minlen: 1, weight: 1 });

  for (let i = 0; i <= maxLayer + 1; i += 1)
    g.setNode(`__lane${i}`, { width: 0, height: 0 });
  for (let i = 0; i < maxLayer + 1; i += 1)
    g.setEdge(`__lane${i}`, `__lane${i + 1}`, { minlen: 2, weight: 1 });
  for (const t of tables) {
    const l = layerOf[t.name];
    g.setEdge(`__lane${l}`, t.name, { minlen: 1, weight: 1000 });       // not before its lane
    g.setEdge(t.name, `__lane${l + 1}`, { minlen: 1, weight: 1000 });   // not after it
  }

  dagre.layout(g);

  const pos: Record<string, { x: number; y: number }> = {};
  for (const t of tables) {
    const n = g.node(t.name);
    // dagre centres a node; React Flow positions by top-left.
    pos[t.name] = { x: n.x - n.width / 2, y: n.y - n.height / 2 };
  }
  return pos;
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
  const positions = useMemo(
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

  const edges = useMemo<RFEdge[]>(() => schema.joins.map((j, i) => ({
    id: `${j.t2}.${j.c2}→${j.t1}.${j.c1}#${i}`,
    source: j.t2,
    sourceHandle: `${j.c2}__s`,
    target: j.t1,
    targetHandle: `${j.c1}__t`,
    type: "smoothstep",
    style: {
      stroke: j.match === "exact" ? "var(--blue4)" : "var(--t3)",
      strokeWidth: 1.4,
      strokeDasharray: j.match === "exact" ? undefined : "4 3",
    },
  })), [schema]);

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
