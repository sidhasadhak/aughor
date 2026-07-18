"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { formatMetricValue, formatVariance } from "@/lib/format";
import {
  deleteDashboardCard,
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

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: "13px 15px", display: "flex", flexDirection: "column" as const, gap: 7, minHeight: 132,
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
      ) : (
        <div style={{ fontSize: 13, color: "var(--t3)" }}>{run ? `${run.row_count} rows` : "…"}</div>
      )}

      {caveats.length > 0 && (
        <div title={caveats.join("; ")} style={{ fontSize: 10, color: "var(--amb4)" }}>
          {caveats.length} guard caveat{caveats.length > 1 ? "s" : ""}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: "auto" }}>
        {onOpenSource && (
          <Button variant="ghost" size="xs" onClick={onOpenSource}
            style={{ fontSize: 11, color: "var(--blue4)", padding: "2px 6px" }}>
            Source
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
