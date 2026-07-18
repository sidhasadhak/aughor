"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { type ChartCustom } from "@/components/Chart";
import { formatMetricValue, formatVariance } from "@/lib/format";
import {
  deleteDashboardCard,
  graduateCard,
  listDashboardCards,
  runDashboardCard,
  type CardRunResult,
  type DashboardCard,
} from "@/lib/api";

type CardState = { card: DashboardCard; run?: CardRunResult; failed?: boolean };

/** The standing "cockpit" layer of the Briefing: the user's own pinned KPI/chart cards.
 *  Each is re-run through the guard battery so its number stays honest, and shows a trend —
 *  either the finding's own time-series or the value's cross-cycle history (S1). Renders
 *  nothing until at least one card exists. */
export function PinnedCards({ connectionId, refreshKey, onOpenSource }: {
  connectionId: string;
  refreshKey?: number;
  onOpenSource?: (insightId: string) => void;
}) {
  const [cards, setCards] = useState<CardState[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!connectionId) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listDashboardCards({ scope: "connection", scopeRef: connectionId });
        const withRuns = await Promise.all(
          list.map(async (card): Promise<CardState> => {
            try { return { card, run: await runDashboardCard(card.id) }; }
            catch { return { card, failed: true }; }
          }),
        );
        if (!cancelled) setCards(withRuns);
      } catch {
        if (!cancelled) setCards([]);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, [connectionId, refreshKey]);

  const remove = useCallback(async (id: string) => {
    await deleteDashboardCard(id).catch(() => {});
    setCards(cs => cs.filter(c => c.card.id !== id));
  }, []);

  const refreshOne = useCallback(async (id: string) => {
    try {
      const run = await runDashboardCard(id);
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, run, failed: false } : c)));
    } catch {
      setCards(cs => cs.map(c => (c.card.id === id ? { ...c, failed: true } : c)));
    }
  }, []);

  if (!ready || cards.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div className="aug-label" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
        Your pinned cards
        <span style={{
          fontSize: 9, fontWeight: 600, letterSpacing: ".05em", textTransform: "uppercase" as const,
          padding: "2px 6px", borderRadius: "var(--r1)", color: "var(--grn4)",
          background: "var(--grn1)", border: "1px solid var(--grn2)",
        }}>Guarded</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 12 }}>
        {cards.map(({ card, run, failed }) => (
          <PinnedCard
            key={card.id} card={card} run={run} failed={failed}
            onRemove={() => remove(card.id)}
            onRefresh={() => refreshOne(card.id)}
            onOpenSource={onOpenSource && card.provenance.insight_id
              ? () => onOpenSource(card.provenance.insight_id) : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function BigValue({ v }: { v: number | null | undefined }) {
  return (
    <span style={{ fontSize: 23, fontWeight: 600, color: "var(--t1)", fontVariantNumeric: "tabular-nums" as const }}>
      {formatMetricValue(v)}
    </span>
  );
}

function PinnedCard({ card, run, failed, onRemove, onRefresh, onOpenSource }: {
  card: DashboardCard;
  run?: CardRunResult;
  failed?: boolean;
  onRemove: () => void;
  onRefresh: () => void;
  onOpenSource?: () => void;
}) {
  const errored = failed || !!run?.error;
  const val = run?.refresh?.last_value ?? null;
  const prev = run?.refresh?.prev_value ?? null;
  const delta = val != null && prev != null ? val - prev : null;
  const hist = run?.refresh?.history ?? [];
  const caveats = run?.caveats ?? [];

  // A time series inside the finding's own result (e.g. "GMV by month") → intra-metric trend.
  const trend = useMemo(
    () => (run && !run.error ? seriesTrend(run.columns, run.rows) : null),
    [run],
  );

  // A multi-column / categorical result (e.g. "Customers by region") is neither a scalar nor a
  // trend → render it as its own chart/table (ResultChartCard) with the card's stored render spec,
  // instead of a bare "N rows". Such cards get more room (span two grid columns).
  const render = (card.render || {}) as { chartType?: string; chartConfig?: Record<string, unknown>; custom?: ChartCustom };
  const isTabular = !errored && !trend && val == null && !!run && !run.error
    && (run.columns?.length ?? 0) > 0 && (run.rows?.length ?? 0) > 0;

  // Watch → alert (Slice 4): graduate a scalar KPI card to a scheduled threshold Monitor.
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
    } catch { /* best-effort; leave the form open on failure */ }
    finally { setAlertBusy(false); }
  };

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: "13px 15px", display: "flex", flexDirection: "column" as const, gap: 7, minHeight: 132,
      gridColumn: isTabular ? "span 2" : undefined,
    }}>
      <div style={{ fontSize: 11.5, color: "var(--t2)", lineHeight: 1.4 }}>{card.title}</div>

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
          <Sparkline values={trend.values} width={198} height={30} color="var(--blue4)" />
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
            ? <Sparkline values={hist} width={198} height={30} color="var(--blue4)" />
            : <div style={{ fontSize: 10, color: "var(--t4)" }}>trend builds as it refreshes</div>}
        </>
      ) : isTabular && run ? (
        <ResultChartCard
          columns={run.columns}
          rows={run.rows as unknown[][]}
          chartType={render.chartType ?? null}
          chartConfig={render.chartConfig ?? null}
          custom={render.custom ?? null}
          heightScale={0.62}
        />
      ) : (
        <div style={{ fontSize: 13, color: "var(--t3)" }}>{run ? `${run.row_count} rows` : "…"}</div>
      )}

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

      <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: "auto" }}>
        {onOpenSource && (
          <Button variant="ghost" size="xs" onClick={onOpenSource}
            style={{ fontSize: 11, color: "var(--blue4)", padding: "2px 6px" }}>
            Source
          </Button>
        )}
        {canAlert && !alerting && (
          <Button variant="ghost" size="xs" onClick={() => setAlertOpen(o => !o)}
            title="Alert me when this KPI crosses a threshold (schedules a monitor)"
            style={{ fontSize: 11, color: "var(--amb4)", padding: "2px 6px" }}>
            {alertOpen ? "Cancel" : "Set alert"}
          </Button>
        )}
        <Button variant="ghost" size="xs" onClick={onRefresh}
          style={{ fontSize: 11, color: "var(--t3)", padding: "2px 6px", marginLeft: "auto" }}>
          Refresh
        </Button>
        <Button variant="ghost" size="xs" onClick={onRemove}
          style={{ fontSize: 11, color: "var(--t4)", padding: "2px 6px" }}>
          Remove
        </Button>
      </div>
    </div>
  );
}
