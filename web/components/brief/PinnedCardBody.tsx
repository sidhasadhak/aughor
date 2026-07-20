"use client";

/**
 * PinnedCardBody — the rendering of ONE pinned cockpit card (title · value/trend/table body ·
 * footer actions), independent of how it's laid out. Both the freeform React-Flow canvas
 * (PinnedCardsCanvas) and the responsive drag-to-reorder grid (PinnedCardsGrid) render the
 * SAME card through this component, so the two arrangement modes stay pixel-identical.
 *
 * RF-free by design: it owns the card chrome + body + footer + the alert composer, but NOT the
 * resize handles / node wrapper (the canvas adds those) or the reorder DnD (the grid adds that).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type ChartCustom } from "@/components/Chart";
import { formatMetricValue, formatVariance } from "@/lib/format";
import { graduateCard, type CardRunResult, type DashboardCard } from "@/lib/api";
import { toast } from "@/components/ui/toast";

export type CardState = { card: DashboardCard; run?: CardRunResult; failed?: boolean };

export type Kind = "kpi" | "chart" | "table" | "note";

/** Which viz a card renders as — drives both the canvas's cell sizing and the grid's row height. */
export function cardKind(cs: CardState): Kind {
  const { card, run, failed } = cs;
  if (failed || run?.error) return "kpi";
  const trend = run && !run.error ? seriesTrend(run.columns, run.rows) : null;
  const val = run?.refresh?.last_value ?? null;
  if (trend || val != null) return "kpi";
  const isTabular = !!run && (run.columns?.length ?? 0) > 0 && (run.rows?.length ?? 0) > 0;
  if (isTabular) return card.kind === "table" ? "table" : "chart";
  return "note";
}

function BigValue({ v }: { v: number | null | undefined }) {
  return (
    <span className="aug-fs-display" style={{ fontWeight: 600, color: "var(--t1)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" as const }}>
      {formatMetricValue(v)}
    </span>
  );
}

export function PinnedCardBody({ cs, selected = false, dragHandleClass, onRemove, onRefresh, onOpenSource, onEvidence }: {
  cs: CardState;
  /** Canvas selection ring; the grid leaves it false. */
  selected?: boolean;
  /** Class the layout owner uses to mark the title as its drag handle (RF's `.pinned-drag`). */
  dragHandleClass?: string;
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}) {
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

  // Measure the body so the chart / sparkline fill the (resizeable or grid-sized) box.
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
      {/* Title bar — the drag handle (canvas: RF `.pinned-drag`; grid: the whole card is draggable). */}
      <div className={`${dragHandleClass ?? ""} aug-fs-sm`} title={card.title}
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
          {onEvidence && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => onEvidence(card.provenance.insight_id)}
              title="See the evidence behind this finding"
              style={{ fontSize: 11, color: "var(--vio4)", padding: "2px 8px", border: "1px solid color-mix(in srgb, var(--vio4) 35%, var(--b1))", borderRadius: "var(--r-pill)" }}>Evidence</Button>
          )}
          {onOpenSource && card.provenance.insight_id && (
            <Button variant="ghost" size="xs" onClick={() => onOpenSource(card.provenance.insight_id)}
              title="Open the finding that explains this metric's move"
              style={{ fontSize: 11, color: "var(--blue4)", padding: "2px 6px" }}>Why →</Button>
          )}
          {canAlert && !alerting && (
            <Button variant="ghost" size="xs" onClick={() => setAlertOpen(o => !o)}
              title="Alert me when this KPI crosses a threshold (schedules a monitor)"
              style={{ fontSize: 11, color: "var(--amb4)", padding: "2px 6px" }}>
              {alertOpen ? "Cancel" : "Set alert"}
            </Button>
          )}
          <Button variant="ghost" size="xs" onClick={() => onRefresh(card.id)}
            style={{ fontSize: 11, color: "var(--t3)", padding: "2px 6px", marginLeft: "auto" }}>Refresh</Button>
          <Button variant="ghost" size="xs" onClick={() => onRemove(card.id)}
            style={{ fontSize: 11, color: "var(--t4)", padding: "2px 6px" }}>Remove</Button>
        </div>
      </div>
    </div>
  );
}
