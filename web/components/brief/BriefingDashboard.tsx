"use client";

/**
 * BriefingDashboard — the Briefing tab's actionable chart layer (#3).
 *
 * The tab already selects the top cross-domain findings (headline + signals) and
 * writes a prose synthesis over them. Each finding carries its own `.sql` — the
 * exact query behind the claim. This turns those claims into a glanceable
 * dashboard WITHOUT a backend change: it runs each finding's SQL through the same
 * authority the Query Builder uses (`runDirectQuery` → /query/run, matcache-backed)
 * and renders the result with the already-deployed chart stack.
 *
 * Classification reuses the shipped inference (no new rules):
 *   • single-series time trend / single scalar → a KPI tile (value + Sparkline + Δ)
 *   • categorical / multi-series / distribution → a chart figure (InvestigationChart)
 *   • anything not chartable / errored / empty   → dropped (never a broken chart)
 *
 * Fail-safe by design: one finding's bad query can never break the dashboard —
 * each runs independently and only the renderable ones surface.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { runDirectQuery, type ExplorationInsight } from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import {
  classifyColumns,
  inferChartType,
  isShareColumn,
} from "@/components/charts/chartTypeInference";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import {
  formatMetricValue,
  formatPercent,
  formatVariance,
  cleanLabel,
} from "@/lib/format";

// One top finding to render (matches the panel's SynthesisSignal shape).
export interface DashboardFinding {
  insight: ExplorationInsight;
  domain: string;
}

type RunResult =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ok"; columns: string[]; rows: string[][] };

// Cap how many finding queries we fire — headline + signals is already ≤ 7.
const MAX_FINDINGS = 8;
// Row cap per finding query. Plenty for a trend or a top-N breakdown.
const ROW_LIMIT = 200;

// ── Result → display classification (reuses the deployed inference) ─────────────

interface Kpi {
  id: string;
  label: string;
  value: string;
  values: number[];        // sparkline series (empty for a pure scalar)
  delta: string | null;    // signed period-over-period, e.g. "+12.5%"
  period: string;          // MoM / WoW / YoY …
  up: boolean;
  finding: string;
  insight: ExplorationInsight;
  domain: string;
}

interface Figure {
  id: string;
  columns: string[];
  rows: string[][];
  finding: string;
  insight: ExplorationInsight;
  domain: string;
}

/** A KPI is a single metric over time (no breakdown dimension) or a single scalar
 *  row — the shapes that read as ONE headline number rather than a comparison. */
function asKpi(f: DashboardFinding, columns: string[], rows: string[][]): Kpi | null {
  if (!columns.length || !rows.length) return null;
  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows as unknown[][]);
  if (!numericIdxs.length) return null;

  const isTrend  = dateIdxs.length >= 1 && catIdxs.length === 0;
  const isScalar = rows.length === 1 && dateIdxs.length === 0;
  if (!isTrend && !isScalar) return null;

  // Prefer a non-share numeric for the headline value (a rate is the Δ story, not the level).
  const numIdx = numericIdxs.find(i => !isShareColumn(columns[i], rows as unknown[][], i)) ?? numericIdxs[0];
  const share  = isShareColumn(columns[numIdx], rows as unknown[][], numIdx);

  const trend = isTrend ? seriesTrend(columns, rows as (string | number | null)[][]) : null;
  const lastNum = trend
    ? trend.values[trend.values.length - 1]
    : Number(rows[0][numIdx]);
  if (lastNum === undefined || isNaN(lastNum)) return null;

  const value = share ? formatPercent(lastNum) : formatMetricValue(lastNum);
  const delta = trend && trend.lastDelta != null ? formatVariance(trend.lastDelta) : null;

  return {
    id: f.insight.id,
    label: cleanLabel(columns[numIdx]),
    value,
    values: trend?.values ?? [],
    delta,
    period: trend?.periodLabel ?? "",
    up: (trend?.lastDelta ?? 0) >= 0,
    finding: f.insight.finding,
    insight: f.insight,
    domain: f.domain,
  };
}

// ── KPI tile ────────────────────────────────────────────────────────────────────

function KpiTile({ kpi, onInvestigate }: { kpi: Kpi; onInvestigate: (q: string) => void }) {
  return (
    <button
      onClick={() => onInvestigate(kpi.finding)}
      title={kpi.finding}
      style={{
        display: "flex", flexDirection: "column", gap: 5, alignItems: "flex-start",
        textAlign: "left", padding: "9px 11px", borderRadius: "var(--r2)",
        background: "var(--bg-2)", border: "1px solid var(--b1)", cursor: "pointer",
        minWidth: 0, transition: "border-color .1s",
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; }}
    >
      <span style={{
        fontSize: 10, color: "var(--t4)", textTransform: "uppercase",
        letterSpacing: ".05em", fontWeight: 600, whiteSpace: "nowrap",
        overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%",
      }}>{kpi.label}</span>
      <span style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{ fontSize: 20, color: "var(--t1)", fontWeight: 600, fontFamily: "var(--font-mono)", lineHeight: 1 }}>
          {kpi.value}
        </span>
        {kpi.delta && (
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: kpi.up ? "var(--grn4)" : "var(--red4)" }}>
            {kpi.delta}
          </span>
        )}
      </span>
      <span style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 18 }}>
        {kpi.values.length >= 2 && <Sparkline values={kpi.values} />}
        {kpi.period && <span style={{ fontSize: 10, color: "var(--t4)" }}>{kpi.period}</span>}
      </span>
    </button>
  );
}

// ── Figure card ───────────────────────────────────────────────────────────────

function FigureCard({
  figure, onInvestigate, actions,
}: {
  figure: Figure;
  onInvestigate: (q: string) => void;
  actions?: ReactNode;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)", minWidth: 0,
    }}>
      <button
        onClick={() => onInvestigate(figure.finding)}
        title="Investigate this finding"
        style={{
          textAlign: "left", background: "transparent", border: "none", padding: 0,
          fontSize: 11, lineHeight: 1.45, color: "var(--t2)", cursor: "pointer",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "var(--t1)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "var(--t2)"; }}
      >
        {figure.finding}
      </button>
      <div style={{ minWidth: 0 }}>
        {/* Compact briefing chart — 25% shorter than the default render. */}
        <InvestigationChart columns={figure.columns} rows={figure.rows} heightScale={0.75} />
      </div>
      {actions && <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{actions}</div>}
    </div>
  );
}

// ── Dashboard ───────────────────────────────────────────────────────────────────

export function BriefingDashboard({
  findings,
  connectionId,
  onInvestigate,
  renderActions,
}: {
  findings: DashboardFinding[];
  connectionId: string;
  onInvestigate: (q: string) => void;
  /** Reuse the panel's FindingActions so each figure stays actionable (monitor/share/evidence). */
  renderActions?: (insight: ExplorationInsight, domain: string) => ReactNode;
}) {
  // Dedup by insight id (headline can repeat a signal), keep only findings with SQL.
  const runnable = useMemo(() => {
    const seen = new Set<string>();
    const out: DashboardFinding[] = [];
    for (const f of findings) {
      const id = f.insight?.id;
      if (!id || seen.has(id) || !f.insight.sql?.trim()) continue;
      seen.add(id);
      out.push(f);
      if (out.length >= MAX_FINDINGS) break;
    }
    return out;
  }, [findings]);

  const [results, setResults] = useState<Record<string, RunResult>>({});
  // The effect re-fires only when this key changes (connection or the finding set) — the
  // parent rebuilds the `findings` array every render, so we key on a stable string, not
  // its identity. Each run owns an `alive` flag so the latest run's results always win
  // (and a superseded run's late responses are discarded).
  const runKey = `${connectionId}|${runnable.map(f => f.insight.id).join(",")}`;

  useEffect(() => {
    if (!connectionId || !runnable.length) { setResults({}); return; }

    let alive = true;
    setResults(Object.fromEntries(runnable.map(f => [f.insight.id, { status: "loading" } as RunResult])));

    runnable.forEach(async (f) => {
      try {
        const r = await runDirectQuery(connectionId, f.insight.sql, ROW_LIMIT, { useCache: true });
        if (!alive) return;
        setResults(prev => ({
          ...prev,
          [f.insight.id]: r.error
            ? { status: "error" }
            : { status: "ok", columns: r.columns, rows: r.rows },
        }));
      } catch {
        if (alive) setResults(prev => ({ ...prev, [f.insight.id]: { status: "error" } }));
      }
    });

    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);

  // Renderable results → ONE impact-ranked list that MIXES chart figures and
  // non-chart KPI tiles (no more "all KPIs then all charts" segregation). Impact =
  // novelty + confidence (the explorer's own signals): a surprising, well-evidenced
  // finding floats up whether it draws as a chart or a number.
  type DashCard =
    | { kind: "kpi"; id: string; impact: number; kpi: Kpi }
    | { kind: "figure"; id: string; impact: number; figure: Figure };
  const cards = useMemo<DashCard[]>(() => {
    const out: DashCard[] = [];
    for (const f of runnable) {
      const r = results[f.insight.id];
      if (!r || r.status !== "ok" || r.rows.length < 1) continue;
      const impact = (f.insight.novelty ?? 0) + (f.insight.confidence ?? 0);
      const kpi = asKpi(f, r.columns, r.rows);
      if (kpi) { out.push({ kind: "kpi", id: kpi.id, impact, kpi }); continue; }
      // Not a KPI — a chart only if the engine can actually draw it.
      if (r.rows.length < 2) continue;
      const inferred = inferChartType(r.columns, r.rows as unknown[][]);
      if (!inferred || inferred.type === "table") continue;
      out.push({
        kind: "figure", id: f.insight.id, impact,
        figure: {
          id: f.insight.id, columns: r.columns, rows: r.rows,
          finding: f.insight.finding, insight: f.insight, domain: f.domain,
        },
      });
    }
    return out.sort((a, b) => b.impact - a.impact);   // rank by impact, mixed
  }, [runnable, results]);

  const anyLoading = runnable.some(f => results[f.insight.id]?.status === "loading");
  const hasContent = cards.length > 0;

  // Nothing to draw and nothing pending → render nothing (the prose/cards still show).
  if (!runnable.length || (!hasContent && !anyLoading)) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
      <div className="aug-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span>Dashboard</span>
        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>
          Live
        </span>
        {anyLoading && (
          <span style={{ fontSize: 10, color: "var(--t4)", display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 9, height: 9, border: "1.5px solid var(--b2)", borderTop: "1.5px solid var(--blue4)", borderRadius: "50%", animation: "aug-spin var(--dur-breath) linear infinite" }} />
            rendering charts…
          </span>
        )}
      </div>

      {/* One impact-ranked grid — chart cards and non-chart KPI cards interleaved,
          not segregated. alignItems:start lets short KPI cards sit beside tall charts. */}
      {cards.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
          {cards.map(c => c.kind === "kpi"
            ? <KpiTile key={c.id} kpi={c.kpi} onInvestigate={onInvestigate} />
            : <FigureCard
                key={c.id}
                figure={c.figure}
                onInvestigate={onInvestigate}
                actions={renderActions?.(c.figure.insight, c.figure.domain)}
              />
          )}
        </div>
      )}
    </div>
  );
}
