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

import { Button } from "@/components/ui/button";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type ChartCustom } from "@/components/Chart";
import { formatMetricValue, formatVariance } from "@/lib/format";
import { graduateCard, getCockpitLayout, saveCockpitLayout, type CardRunResult, type DashboardCard } from "@/lib/api";
import { toast } from "@/components/ui/toast";
import {
  GRID, boxToCell, cellPos, cellSize, packTopLeft, bottomRow,
  type Box, type Cell, type Cells,
} from "@/components/brief/gridLayout";

export type CardState = { card: DashboardCard; run?: CardRunResult; failed?: boolean };

type Kind = "kpi" | "chart" | "table" | "note";

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

function cardKind(cs: CardState): Kind {
  const { card, run, failed } = cs;
  if (failed || run?.error) return "kpi";
  const trend = run && !run.error ? seriesTrend(run.columns, run.rows) : null;
  const val = run?.refresh?.last_value ?? null;
  if (trend || val != null) return "kpi";
  const isTabular = !!run && (run.columns?.length ?? 0) > 0 && (run.rows?.length ?? 0) > 0;
  if (isTabular) return card.kind === "table" ? "table" : "chart";
  return "note";
}

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

function BigValue({ v }: { v: number | null | undefined }) {
  return (
    <span className="aug-fs-display" style={{ fontWeight: 600, color: "var(--t1)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const }}>
      {formatMetricValue(v)}
    </span>
  );
}

function PinnedCardNode({ data, selected }: NodeProps<Node<PinnedNodeData>>) {
  const { cs, kind } = data;
  const { card, run, failed } = cs;
  const errored = failed || !!run?.error;
  const val = run?.refresh?.last_value ?? null;
  const prev = run?.refresh?.prev_value ?? null;
  const delta = val != null && prev != null ? val - prev : null;
  const hist = run?.refresh?.history ?? [];
  const caveats = run?.caveats ?? [];
  const trend = useMemo(() => (run && !run.error ? seriesTrend(run.columns, run.rows) : null), [run]);
  const render = (card.render || {}) as { chartType?: string; chartConfig?: Record<string, unknown>; custom?: ChartCustom };
  const isTabular = !errored && !trend && val == null && !!run && !run.error
    && (run.columns?.length ?? 0) > 0 && (run.rows?.length ?? 0) > 0;

  // Measure the body so the chart / sparkline fill the (resizeable) box.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setDims({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  const sparkW = dims.w > 20 ? dims.w - 2 : 198;
  const sparkH = Math.max(24, Math.min(dims.h > 0 ? dims.h - 40 : 30, 120));

  // Watch → alert.
  const t0 = card.thresholds as { warning?: number | null; critical?: number | null; direction?: string } | undefined;
  const [alerting, setAlerting] = useState(!!(t0 && (t0.warning != null || t0.critical != null)));
  const [alertOpen, setAlertOpen] = useState(false);
  const [alertVal, setAlertVal] = useState("");
  const [alertDir, setAlertDir] = useState<"below" | "above">((t0?.direction as "below" | "above") || "below");
  const [alertBusy, setAlertBusy] = useState(false);
  const canAlert = val != null && !errored;
  const saveAlert = async () => {
    const n = Number(alertVal);
    if (!alertVal || Number.isNaN(n)) return;
    setAlertBusy(true);
    try {
      await graduateCard(card.id, { warning_threshold: n, threshold_direction: alertDir });
      setAlerting(true); setAlertOpen(false);
      toast.success("Alert set", { description: `You'll be notified when this metric goes ${alertDir} ${n}.` });
    } catch {
      toast.error("Couldn't set alert", { description: "The card's query didn't pass the trust guards, so no monitor was scheduled." });
    }
    finally { setAlertBusy(false); }
  };

  return (
    <div style={{
      width: "100%", height: "100%", boxSizing: "border-box", display: "flex", flexDirection: "column",
      background: "var(--bg-2)",
      border: `1px solid ${selected ? "var(--vio4)" : "var(--b1)"}`,
      borderRadius: "var(--r3)", overflow: "hidden",
    }}>
      <NodeResizer isVisible={selected} minWidth={MIN_CELLS[kind].w * GRID} minHeight={MIN_CELLS[kind].h * GRID} {...RESIZER} />

      {/* Title bar — the drag handle. The title wraps FULLY (no ellipsis) so it's always readable. */}
      <div className="pinned-drag aug-fs-sm" title={card.title}
        style={{
          fontWeight: 500, color: "var(--t1)", lineHeight: 1.35, padding: "9px 12px 7px", cursor: "grab",
          flex: "0 0 auto", overflowWrap: "anywhere",
          borderBottom: "1px solid color-mix(in srgb, var(--b1) 60%, transparent)",
        }}>
        {card.title}
      </div>

      {/* Body — fills; chart/table grow with the box. */}
      <div ref={bodyRef} className="nodrag nowheel" style={{ flex: 1, minHeight: 0, overflow: "hidden", padding: "8px 12px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
        {errored ? (
          <div style={{ fontSize: 12, color: "var(--amb4)" }}>Could not refresh</div>
        ) : trend ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <BigValue v={trend.values[trend.values.length - 1]} />
              {trend.lastDelta != null && (
                <span style={{ fontSize: 12, color: trend.lastDelta >= 0 ? "var(--grn4)" : "var(--red4)" }}>
                  {formatVariance(trend.lastDelta)} {trend.periodLabel}
                </span>
              )}
            </div>
            <Sparkline values={trend.values} width={sparkW} height={sparkH} color="var(--blue4)" />
          </>
        ) : val != null ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <BigValue v={val} />
              {delta != null && delta !== 0 && (
                <span style={{ fontSize: 12, color: delta > 0 ? "var(--grn4)" : "var(--red4)" }}>
                  {delta > 0 ? "+" : "-"}{formatMetricValue(Math.abs(delta))}
                </span>
              )}
            </div>
            {hist.length >= 2
              ? <Sparkline values={hist} width={sparkW} height={sparkH} color="var(--blue4)" />
              : <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>trend builds as it refreshes</div>}
          </>
        ) : isTabular && run ? (
          <ResultChartCard
            columns={run.columns}
            rows={run.rows as unknown[][]}
            chartType={render.chartType ?? null}
            chartConfig={render.chartConfig ?? null}
            custom={render.custom ?? null}
            fillHeight={dims.h > 60 ? dims.h - 6 : null}
          />
        ) : (
          <div style={{ fontSize: 13, color: "var(--t3)" }}>{run ? `${run.row_count} rows` : "…"}</div>
        )}
      </div>

      {/* Footer — actions (never a drag target). */}
      <div className="nodrag" style={{ flex: "0 0 auto", padding: "5px 10px 7px", display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid color-mix(in srgb, var(--b1) 60%, transparent)" }}>
        {caveats.length > 0 && (
          <div title={caveats.join("; ")} className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
            {caveats.length} guard caveat{caveats.length > 1 ? "s" : ""}
          </div>
        )}
        {canAlert && alerting && (
          <div title="This card is now a scheduled monitor" className="aug-fs-xs" style={{ color: "var(--amb4)", display: "flex", alignItems: "center", gap: 4 }}>
            <span>⏰</span> Alerting when {alertDir} threshold
          </div>
        )}
        {canAlert && !alerting && alertOpen && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <select value={alertDir} onChange={e => setAlertDir(e.target.value as "below" | "above")}
              style={{ fontSize: 11, background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r1)", color: "var(--t2)", padding: "2px 4px" }}>
              <option value="below">below</option>
              <option value="above">above</option>
            </select>
            <input type="number" value={alertVal} onChange={e => setAlertVal(e.target.value)} placeholder="threshold"
              onKeyDown={e => { if (e.key === "Enter") saveAlert(); }}
              style={{ fontSize: 11, width: 74, background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r1)", color: "var(--t1)", padding: "2px 4px", outline: "none" }} />
            <Button variant="ghost" size="xs" onClick={saveAlert} disabled={!alertVal || alertBusy}
              style={{ fontSize: 11, color: "var(--amb4)", padding: "2px 6px" }}>{alertBusy ? "…" : "Save"}</Button>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
          {/* Evidence capsule — the receipt/derivation behind a finding-derived card. */}
          {data.onEvidence && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => data.onEvidence!(card.provenance.insight_id)}
              title="See the evidence behind this finding"
              style={{ fontSize: 11, color: "var(--vio4)", padding: "2px 8px", border: "1px solid color-mix(in srgb, var(--vio4) 35%, var(--b1))", borderRadius: "var(--r-pill)" }}>Evidence</Button>
          )}
          {data.onOpenSource && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => data.onOpenSource!(card.provenance.insight_id)}
              style={{ fontSize: 11, color: "var(--blue4)", padding: "2px 6px" }}>Source</Button>
          )}
          {canAlert && !alerting && (
            <Button variant="ghost" size="xs" onClick={() => setAlertOpen(o => !o)}
              title="Alert me when this KPI crosses a threshold (schedules a monitor)"
              style={{ fontSize: 11, color: "var(--amb4)", padding: "2px 6px" }}>
              {alertOpen ? "Cancel" : "Set alert"}
            </Button>
          )}
          <Button variant="ghost" size="xs" onClick={() => data.onRefresh(card.id)}
            style={{ fontSize: 11, color: "var(--t3)", padding: "2px 6px", marginLeft: "auto" }}>Refresh</Button>
          <Button variant="ghost" size="xs" onClick={() => data.onRemove(card.id)}
            style={{ fontSize: 11, color: "var(--t4)", padding: "2px 6px" }}>Remove</Button>
        </div>
      </div>
    </div>
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
