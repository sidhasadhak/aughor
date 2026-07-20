"use client";

/**
 * PinnedCardsCanvas — the standing cockpit layer as a CANVAS (briefing-cockpit follow-up).
 *
 * The user's pinned KPI / chart / table cards become React-Flow nodes the reader arranges by
 * priority (drag by the title bar) and resizes at will (NodeResizer), with a MINIMUM size per viz
 * type so a KPI never gets forced as large as a table. Charts + tables FILL their node (measured
 * body height → ResultChartCard `fillHeight`), so a stretched card's chart grows with it.
 *
 * The board is a SNAP-TO-GRID cockpit that never overlaps: drag and resize both snap to a uniform
 * `GRID` lattice (React-Flow's `snapToGrid`/`snapGrid`, which its resizer reads too), and the layout
 * is kept TOP-LEFT PACKED — cards gravitate up AND left, filling any hole a neighbour left behind
 * (see ./gridLayout). While you move or resize one card it is pinned under the cursor and every OTHER
 * card repacks around it; on release the board repacks whole, so priority order settles with no gap.
 * Layout (order + size per card) persists per-connection, account-keyed, on the server — the same
 * connection scope every other briefing element uses.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, ReactFlowProvider, Background, NodeResizer, applyNodeChanges,
  useNodesState, type Node, type NodeProps, type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getCockpitLayout, saveCockpitLayout } from "@/lib/api";
import { PinnedCardBody, cardKind, type CardState, type Kind } from "@/components/brief/PinnedCardBody";
import {
  GRID, boxToCell, cellPos, cellSize, packTopLeft, bottomRow,
  type Box, type Cell, type Cells,
} from "@/components/brief/gridLayout";

// Re-export so existing importers (PinnedCards) keep getting CardState from here.
export type { CardState };

// CardState / Kind / cardKind / the card body now live in PinnedCardBody (imported above).

// Per-type sizing IN GRID CELLS — a consistent floor + a sensible starting box, so each viz reads
// well and a KPI never gets forced as large as a table. (× GRID for pixels.)
const MIN_CELLS: Record<Kind, { w: number; h: number }> = {
  kpi: { w: 9, h: 6 }, chart: { w: 14, h: 10 }, table: { w: 16, h: 9 }, note: { w: 9, h: 5 },
};
const DEFAULT_CELLS: Record<Kind, { w: number; h: number }> = {
  kpi: { w: 12, h: 8 }, chart: { w: 19, h: 15 }, table: { w: 22, h: 14 }, note: { w: 12, h: 6 },
};

const RESIZER = {
  color: "var(--vio4)",
  handleStyle: { width: 7, height: 7, borderRadius: 2, background: "var(--bg-2)", border: "1.5px solid var(--vio4)" },
  lineStyle: { borderColor: "color-mix(in srgb, var(--vio4) 45%, transparent)" },
};

// ── Layout persistence — server-side, account-keyed (per connection + user) ─────

type Layout = Record<string, Box>;

type Handlers = { onRemove: (id: string) => void; onRefresh: (id: string) => void; onOpenSource?: (iid: string) => void; onEvidence?: (iid: string) => void };

// ── Node ⇄ grid-cell bridge ─────────────────────────────────────────────────────

const nodeKind = (n: Node): Kind => ((n.data as { kind?: Kind })?.kind) ?? "chart";

/** A node's live pixel box (explicit size wins over the measured fallback). */
function nodeBox(n: Node): Box {
  return {
    x: n.position.x, y: n.position.y,
    w: (n.width ?? n.measured?.width ?? 0) as number,
    h: (n.height ?? n.measured?.height ?? 0) as number,
  };
}

/** A node snapped to its grid cell, honouring its type's minimum size and the column count. */
function cellFromNode(n: Node, cols: number): Cell {
  const k = nodeKind(n);
  return boxToCell(nodeBox(n), MIN_CELLS[k].w, MIN_CELLS[k].h, cols);
}

function cellsFromNodes(nodes: Node[], cols: number): Cells {
  const out: Cells = {};
  for (const n of nodes) out[n.id] = cellFromNode(n, cols);
  return out;
}

/** Write a packed layout back onto nodes: `keepId` (the card under the cursor) is left untouched so it
 *  tracks the pointer; every other node moves/snaps to its packed cell, and identical geometry is
 *  returned by reference so untouched cards don't re-render. */
function applyCells(nodes: Node[], packed: Cells, keepId: string | null): Node[] {
  return nodes.map(n => {
    if (n.id === keepId) return n;
    const c = packed[n.id];
    if (!c) return n;
    const { x, y } = cellPos(c), { w, h } = cellSize(c);
    if (n.position.x === x && n.position.y === y && n.width === w && n.height === h) return n;
    return { ...n, position: { x, y }, width: w, height: h };
  });
}

/**
 * Reconcile the card list into RF nodes. A card the reader has DELIBERATELY placed (a saved box)
 * keeps that cell; every other card is auto-placed fresh — shelf-packed left-to-right at the current
 * column count, below any saved cards. Auto-placement is deterministic in (card order, cols), so a
 * data refresh recomputes the identical layout (no jitter) while a width change re-spreads cleanly —
 * and a card auto-placed during a transient 0-width mount simply re-flows correctly next pass rather
 * than getting a bad geometry frozen in. The board is then packed top-left into a gap-free layout.
 */
function reconcileNodes(prev: Node[], cards: CardState[], handlers: Handlers, saved: Layout, cols: number): Node[] {
  const byId = new Map(prev.map(n => [n.id, n]));
  const meta = new Map<string, { data: PinnedNodeData; prev?: Node }>();

  // User-arranged cells anchor the board; new/auto cards shelf below them.
  const savedCells: Cells = {};
  for (const cs of cards) {
    if (saved[cs.card.id]) {
      const k = cardKind(cs);
      savedCells[cs.card.id] = boxToCell(saved[cs.card.id], MIN_CELLS[k].w, MIN_CELLS[k].h, cols);
    }
  }

  const cells: Cells = { ...savedCells };
  let shelfX = 0, shelfY = bottomRow(savedCells), rowH = 0;
  for (const cs of cards) {
    const kind = cardKind(cs);
    meta.set(cs.card.id, { data: { cs, kind, ...handlers } as PinnedNodeData, prev: byId.get(cs.card.id) });
    if (savedCells[cs.card.id]) continue; // deliberately placed — leave it
    const def = DEFAULT_CELLS[kind];
    const gw = Math.min(def.w, cols);
    if (shelfX + gw > cols) { shelfX = 0; shelfY += rowH; rowH = 0; }
    cells[cs.card.id] = { gx: Math.min(shelfX, Math.max(0, cols - gw)), gy: shelfY, gw, gh: def.h };
    shelfX += gw; rowH = Math.max(rowH, def.h);
  }

  const packed = packTopLeft(cells, [], cols);
  return cards.map(cs => {
    const { data, prev: p } = meta.get(cs.card.id)!;
    const c = packed[cs.card.id];
    const { x, y } = cellPos(c), { w, h } = cellSize(c);
    const base = p ?? ({ id: cs.card.id, type: "pinned" } as Partial<Node>);
    return { ...base, position: { x, y }, width: w, height: h, dragHandle: ".pinned-drag", data } as Node;
  });
}

// ── The card node ──────────────────────────────────────────────────────────────

type PinnedNodeData = {
  cs: CardState; kind: Kind;
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
} & Record<string, unknown>;

/** Canvas node = the RF wrapper (resize handles + selection ring) around the shared card body. */
function PinnedCardNode({ data, selected }: NodeProps<Node<PinnedNodeData>>) {
  const { cs, kind } = data;
  return (
    <>
      <NodeResizer isVisible={selected} minWidth={MIN_CELLS[kind].w * GRID} minHeight={MIN_CELLS[kind].h * GRID} {...RESIZER} />
      <PinnedCardBody
        cs={cs} selected={selected} dragHandleClass="pinned-drag"
        onRemove={data.onRemove} onRefresh={data.onRefresh}
        onOpenSource={data.onOpenSource} onEvidence={data.onEvidence}
      />
    </>
  );
}

const nodeTypes = { pinned: PinnedCardNode };

// The cockpit is a fixed, non-pannable panel: CONTROL the viewport at the origin so nothing (auto-pan
// on drag, a transient narrow-width clamp) can ever shift the board. Node dragging is unaffected — it
// moves node positions, not the viewport. Stable identities so React-Flow doesn't churn.
const FIXED_VIEWPORT = { x: 0, y: 0, zoom: 1 } as const;
const keepViewport = () => {};

// ── Canvas ───────────────────────────────────────────────────────────────────

function PinnedCardsInner({ connectionId, cards, onRemove, onRefresh, onOpenSource, onEvidence, registerTidy }: {
  connectionId: string;
  cards: CardState[];
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
  registerTidy?: (fn: (() => void) | null) => void;
}) {
  const handlers = useMemo(() => ({ onRemove, onRefresh, onOpenSource, onEvidence }), [onRemove, onRefresh, onOpenSource, onEvidence]);

  // The board is BOUNDED (not an infinite canvas): its width tracks the container, and it grows only
  // VERTICALLY as cards are added — measure the width so packing wraps at the real edge.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [wrapW, setWrapW] = useState(0);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Ignore transient 0-width mounts — placing cards against a collapsed width would pile them all
    // into column 0. Keep the last good width until a real one arrives.
    const measure = () => { const w = el.clientWidth; if (w > 0) setWrapW(w); };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);

  // Cockpit layout — loaded from the SERVER (account-keyed, so any device sees the same arrangement),
  // applied once ready. `savedRef` mirrors the latest saved layout so new cards pack relative to it.
  const savedRef = useRef<Layout>({});
  const [loaded, setLoaded] = useState<Layout | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoaded(null);
    getCockpitLayout(connectionId).then(l => {
      if (cancelled) return;
      savedRef.current = (l as Layout) || {};
      setLoaded(savedRef.current);
    });
    return () => { cancelled = true; };
  }, [connectionId]);

  const [rfNodes, setRfNodes] = useNodesState<Node>([]);

  // Column count of the snap grid tracks the (bounded) board width. `colsRef` mirrors it for the
  // change handler, which runs outside React's render and must read the latest value.
  const cols = Math.max(4, Math.floor(wrapW / GRID));
  const colsRef = useRef(cols);
  useEffect(() => { colsRef.current = cols; }, [cols]);

  // Reconcile card data changes into RF state once the layout has loaded AND the board has a real
  // width (so auto-placement spreads across the true column count, never a collapsed one).
  useEffect(() => {
    if (loaded == null || wrapW <= 0) return;
    setRfNodes(prev => reconcileNodes(prev, cards, handlers, savedRef.current, cols));
  }, [cards, handlers, loaded, wrapW, cols, setRfNodes]);

  // ── Snap-to-grid + no-overlap ──────────────────────────────────────────────────
  // Drag and resize snap to the grid natively (React-Flow's `snapToGrid`/`snapGrid`, honoured by its
  // resizer too). Packing is ours: while a card is under the cursor we PIN it and repack every other
  // card top-left around it, and on release we repack the whole board so nothing overlaps or gaps.
  const opRef = useRef<{ id: string; base: Cells } | null>(null);
  // Only a USER drag/resize marks the layout dirty — automatic (re)placement from a data refresh or a
  // width change must never persist, or a transient narrow mount width would bake a bad arrangement in.
  const dirtyRef = useRef(false);

  const endOp = useCallback(() => {
    if (!opRef.current) return;
    opRef.current = null;
    setRfNodes(cur => applyCells(cur, packTopLeft(cellsFromNodes(cur, colsRef.current), [], colsRef.current), null));
  }, [setRfNodes]);

  // Tidy up: re-pack EVERY card top-left into a dense, gap-free grid (in current reading order) and
  // persist — a one-click reset of the arrangement. Same as an op's final settle, but reader-invoked
  // (from the header button, wired up via registerTidy) and it marks the layout dirty so it saves.
  const tidyUp = useCallback(() => {
    dirtyRef.current = true;
    setRfNodes(cur => applyCells(cur, packTopLeft(cellsFromNodes(cur, colsRef.current), [], colsRef.current), null));
  }, [setRfNodes]);
  useEffect(() => {
    registerTidy?.(tidyUp);
    return () => registerTidy?.(null);
  }, [registerTidy, tidyUp]);

  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    // A drag ends with a `position` change (dragging:false); a resize with a `dimensions` change
    // (resizing:false). Either closes the active op → a final gravity settle.
    const ending = changes.some(ch =>
      ((ch.type === "position" && ch.dragging === false) || (ch.type === "dimensions" && ch.resizing === false))
      && opRef.current?.id === ch.id);
    // Any deliberate drag/resize marks the layout dirty so it persists (the reader arranged it;
    // honour that on reload).
    if (changes.some(ch => (ch.type === "position" && "dragging" in ch) || (ch.type === "dimensions" && "resizing" in ch))) {
      dirtyRef.current = true;
    }

    setRfNodes(cur => {
      // The card under the cursor is the one mid-drag (dragging) or mid-resize (resizing).
      let activeId: string | null = null;
      for (const ch of changes) {
        if ((ch.type === "position" && ch.dragging) || (ch.type === "dimensions" && ch.resizing)) activeId = ch.id;
      }
      // Opening an op snapshots the board so live reflow computes against a stable base (no thrash).
      if (activeId && opRef.current?.id !== activeId) {
        opRef.current = { id: activeId, base: cellsFromNodes(cur, colsRef.current) };
      }
      const next = applyNodeChanges(changes, cur) as Node[];
      const op = opRef.current;
      if (op) {
        const active = next.find(n => n.id === op.id);
        if (active) {
          const target: Cells = { ...op.base, [op.id]: cellFromNode(active, colsRef.current) };
          return applyCells(next, packTopLeft(target, [op.id], colsRef.current), op.id);
        }
      }
      return next;
    });

    if (ending) endOp();
  }, [setRfNodes, endOp]);

  // Persist the whole layout (position + size per card) to the server shortly after a USER drag /
  // resize — gated on `dirtyRef` so automatic (re)placement never persists. Every save REPLACES the
  // stored layout with the current board, so stale card ids can't pile up.
  useEffect(() => {
    if (loaded == null || !rfNodes.length || !dirtyRef.current) return;
    const t = setTimeout(() => {
      const l: Layout = {};
      rfNodes.forEach(n => {
        const w = (n.width ?? n.measured?.width) as number | undefined;
        const h = (n.height ?? n.measured?.height) as number | undefined;
        if (w && h) l[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y), w: Math.round(w), h: Math.round(h) };
      });
      savedRef.current = l;
      saveCockpitLayout(connectionId, l);
      dirtyRef.current = false;
    }, 500);
    return () => clearTimeout(t);
  }, [rfNodes, connectionId, loaded]);

  // Height = the content bounds, so the board is fully visible and grows DOWN as cards are added
  // (no pan needed). Clamp so an empty/one-card board still reads as a panel.
  const contentH = useMemo(() => {
    let maxB = 0;
    rfNodes.forEach(n => { maxB = Math.max(maxB, n.position.y + ((n.height ?? n.measured?.height ?? 200) as number)); });
    return Math.max(220, Math.round(maxB) + 22);
  }, [rfNodes]);

  return (
    <div ref={wrapRef} style={{ height: contentH, borderRadius: "var(--r3)", border: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden", transition: "height var(--dur-fast, .15s)" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={[]}
        onNodesChange={handleNodesChange}
        nodeTypes={nodeTypes}
        snapToGrid
        snapGrid={[GRID, GRID]}
        viewport={FIXED_VIEWPORT}
        onViewportChange={keepViewport}
        minZoom={1}
        maxZoom={1}
        panOnDrag={false}
        autoPanOnNodeDrag={false}
        panOnScroll={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        nodeExtent={[[0, 0], [wrapW, Infinity]]}
        translateExtent={[[0, 0], [wrapW, Infinity]]}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
      >
        <Background color="var(--b1)" gap={GRID} />
      </ReactFlow>
    </div>
  );
}

export function PinnedCardsCanvas(props: {
  connectionId: string;
  cards: CardState[];
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
  registerTidy?: (fn: (() => void) | null) => void;
}) {
  return (
    <ReactFlowProvider>
      <PinnedCardsInner {...props} />
    </ReactFlowProvider>
  );
}
