"use client";

/**
 * PinnedCardsCanvas — the standing cockpit layer as a CANVAS (briefing-cockpit follow-up).
 *
 * The user's pinned KPI / chart / table cards become React-Flow nodes the reader arranges by
 * priority (drag by the title bar) and resizes at will (NodeResizer), with a MINIMUM size per viz
 * type so a KPI never gets forced as large as a table. Charts + tables FILL their node (measured
 * body height → ResultChartCard `fillHeight`), so a stretched card's chart grows with it. Layout
 * (position + size per card) persists per-connection in localStorage — the same connection scope
 * every other briefing element uses.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, ReactFlowProvider, Background, NodeResizer,
  useNodesState, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Button } from "@/components/ui/button";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type ChartCustom } from "@/components/Chart";
import { formatMetricValue, formatVariance } from "@/lib/format";
import { graduateCard, getCockpitLayout, saveCockpitLayout, type CardRunResult, type DashboardCard } from "@/lib/api";

export type CardState = { card: DashboardCard; run?: CardRunResult; failed?: boolean };

type Kind = "kpi" | "chart" | "table" | "note";

// Per-type sizing — a consistent floor + a sensible starting box, so each viz reads well.
const MIN_SIZE: Record<Kind, { w: number; h: number }> = {
  kpi: { w: 180, h: 108 }, chart: { w: 280, h: 200 }, table: { w: 320, h: 180 }, note: { w: 170, h: 88 },
};
const DEFAULT_SIZE: Record<Kind, { w: number; h: number }> = {
  kpi: { w: 244, h: 150 }, chart: { w: 372, h: 288 }, table: { w: 432, h: 264 }, note: { w: 244, h: 116 },
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

type Box = { x: number; y: number; w: number; h: number };
type Layout = Record<string, Box>;

type Handlers = { onRemove: (id: string) => void; onRefresh: (id: string) => void; onOpenSource?: (iid: string) => void; onEvidence?: (iid: string) => void };

/** Reconcile the card list into RF nodes: KEEP each surviving node's geometry + selection (only its
 *  data refreshes); a card lacking a live node takes its SAVED box, or is shelf-packed BELOW whatever
 *  is already placed (so an added card never lands on top of an existing one). */
function reconcileNodes(prev: Node[], cards: CardState[], handlers: Handlers, saved: Layout, maxWidth = 1180): Node[] {
  const byId = new Map(prev.map(n => [n.id, n]));
  const MAXW = Math.max(360, maxWidth), GAP = 14;
  let baseY = 0;
  for (const cs of cards) {
    const p = byId.get(cs.card.id);
    if (p) { baseY = Math.max(baseY, p.position.y + ((p.height ?? p.measured?.height ?? 150) as number)); continue; }
    const s = saved[cs.card.id];
    if (s) baseY = Math.max(baseY, s.y + s.h);
  }
  let x = 0, y = baseY ? baseY + GAP : 0, rowH = 0;
  return cards.map(cs => {
    const kind = cardKind(cs);
    const data = { cs, kind, ...handlers };
    const p = byId.get(cs.card.id);
    if (p) return { ...p, data, dragHandle: ".pinned-drag" };
    const s = saved[cs.card.id];
    const def = DEFAULT_SIZE[kind];
    let position: { x: number; y: number }, width: number, height: number;
    if (s) {
      position = { x: s.x, y: s.y }; width = s.w; height = s.h;
    } else {
      if (x + def.w > MAXW) { x = 0; y += rowH + GAP; rowH = 0; }
      position = { x, y }; width = def.w; height = def.h;
      x += def.w + GAP; rowH = Math.max(rowH, def.h);
    }
    return { id: cs.card.id, type: "pinned", position, width, height, dragHandle: ".pinned-drag", data } as Node;
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
    <span style={{ fontSize: 23, fontWeight: 600, color: "var(--t1)", fontVariantNumeric: "tabular-nums" as const }}>
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
    } catch { /* best-effort */ }
    finally { setAlertBusy(false); }
  };

  return (
    <div style={{
      width: "100%", height: "100%", boxSizing: "border-box", display: "flex", flexDirection: "column",
      background: "var(--bg-2)", border: `1px solid ${selected ? "var(--vio4)" : "var(--b1)"}`,
      borderRadius: "var(--r3)", overflow: "hidden",
    }}>
      <NodeResizer isVisible={selected} minWidth={MIN_SIZE[kind].w} minHeight={MIN_SIZE[kind].h} {...RESIZER} />

      {/* Title bar — the drag handle. The title wraps FULLY (no ellipsis) so it's always readable. */}
      <div className="pinned-drag" title={card.title}
        style={{
          fontSize: 11.5, fontWeight: 500, color: "var(--t1)", lineHeight: 1.35, padding: "9px 12px 7px", cursor: "grab",
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
              : <div style={{ fontSize: 10, color: "var(--t4)" }}>trend builds as it refreshes</div>}
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
          <div title={caveats.join("; ")} style={{ fontSize: 10, color: "var(--amb4)" }}>
            {caveats.length} guard caveat{caveats.length > 1 ? "s" : ""}
          </div>
        )}
        {canAlert && alerting && (
          <div title="This card is now a scheduled monitor" style={{ fontSize: 10, color: "var(--amb4)", display: "flex", alignItems: "center", gap: 4 }}>
            <span>⏰</span> Alerting when {alertDir} threshold
          </div>
        )}
        {canAlert && !alerting && alertOpen && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <select value={alertDir} onChange={e => setAlertDir(e.target.value as "below" | "above")}
              style={{ fontSize: 10, background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r1)", color: "var(--t2)", padding: "2px 4px" }}>
              <option value="below">below</option>
              <option value="above">above</option>
            </select>
            <input type="number" value={alertVal} onChange={e => setAlertVal(e.target.value)} placeholder="threshold"
              onKeyDown={e => { if (e.key === "Enter") saveAlert(); }}
              style={{ fontSize: 10, width: 74, background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r1)", color: "var(--t1)", padding: "2px 4px", outline: "none" }} />
            <Button variant="ghost" size="xs" onClick={saveAlert} disabled={!alertVal || alertBusy}
              style={{ fontSize: 10, color: "var(--amb4)", padding: "2px 6px" }}>{alertBusy ? "…" : "Save"}</Button>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
          {data.onOpenSource && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => data.onOpenSource!(card.provenance.insight_id)}
              style={{ fontSize: 11, color: "var(--blue4)", padding: "2px 6px" }}>Source</Button>
          )}
          {/* Evidence capsule — the receipt/derivation behind a finding-derived card. */}
          {data.onEvidence && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => data.onEvidence!(card.provenance.insight_id)}
              title="See the evidence behind this finding"
              style={{ fontSize: 10.5, color: "var(--vio4)", padding: "2px 8px", border: "1px solid color-mix(in srgb, var(--vio4) 35%, var(--b1))", borderRadius: "var(--r-pill)" }}>Evidence</Button>
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

// ── Canvas ───────────────────────────────────────────────────────────────────

function PinnedCardsInner({ connectionId, cards, onRemove, onRefresh, onOpenSource, onEvidence }: {
  connectionId: string;
  cards: CardState[];
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}) {
  const handlers = useMemo(() => ({ onRemove, onRefresh, onOpenSource, onEvidence }), [onRemove, onRefresh, onOpenSource, onEvidence]);

  // The board is BOUNDED (not an infinite canvas): its width tracks the container, and it grows only
  // VERTICALLY as cards are added — measure the width so packing wraps at the real edge.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [wrapW, setWrapW] = useState(1180);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWrapW(el.clientWidth));
    ro.observe(el);
    setWrapW(el.clientWidth);
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

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);

  // Reconcile card data changes into RF state ONCE the layout has loaded — positioning new cards
  // from the saved layout (read in an effect, not during render). Surviving nodes keep their geometry.
  useEffect(() => {
    if (loaded == null) return;
    setRfNodes(prev => reconcileNodes(prev, cards, handlers, savedRef.current, wrapW));
  }, [cards, handlers, loaded, wrapW, setRfNodes]);

  // Persist the layout (position + size per card) to the server shortly after any drag / resize.
  useEffect(() => {
    if (loaded == null || !rfNodes.length) return;
    const t = setTimeout(() => {
      const l: Layout = {};
      rfNodes.forEach(n => {
        const w = (n.width ?? n.measured?.width) as number | undefined;
        const h = (n.height ?? n.measured?.height) as number | undefined;
        if (w && h) l[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y), w: Math.round(w), h: Math.round(h) };
      });
      savedRef.current = l;
      saveCockpitLayout(connectionId, l);
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
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
        minZoom={1}
        maxZoom={1}
        panOnDrag={false}
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
        <Background color="var(--b1)" gap={22} />
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
}) {
  return (
    <ReactFlowProvider>
      <PinnedCardsInner {...props} />
    </ReactFlowProvider>
  );
}
