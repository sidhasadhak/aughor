"use client";

/**
 * BriefingDashboard — the Briefing tab's actionable layer (#3).
 *
 * Charts EXPLAIN the industry's key metrics; text cards carry the new findings.
 *
 * The BusinessProfile already knows the vertical's north-star metrics in priority
 * order, and each carries a `chart_sql` — a small SERIES (a daily/weekly trend, or
 * a top-N breakdown) that explains that metric. This runs the TOP THREE of those
 * through the same authority the Query Builder uses (`runDirectQuery` → /query/run,
 * matcache-backed) and draws them with the deployed chart stack, titled by metric
 * (AOV over time, Top return reasons, Gross-margin trend…). The explorer's findings
 * — the new, non-obvious signals — render below as compact text cards.
 *
 * Fail-safe by design: a metric whose chart_sql errors or returns a non-series is
 * silently skipped (never a broken chart); each query runs independently.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getBusinessProfile, runDirectQuery, type ExplorationInsight, type NorthStarMetric } from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import { inferChartType } from "@/components/charts/chartTypeInference";

// One top finding to render (matches the panel's SynthesisSignal shape).
export interface DashboardFinding {
  insight: ExplorationInsight;
  domain: string;
}

type RunResult =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ok"; columns: string[]; rows: string[][] };

// How many findings to surface as text cards (headline + signals is already ≤ 7).
const MAX_FINDINGS = 8;
// Render at most THREE metric-explainer charts — the top-priority metrics that draw.
const MAX_CHARTS = 3;
// Row cap per chart query. Plenty for a trend or a top-N breakdown.
const ROW_LIMIT = 200;

/** True when NO numeric column carries a non-zero, non-null value across the series —
 *  a flat all-zero / all-null chart (e.g. CAC that computes to 0 every month). Mirrors
 *  the backend chart_sql audit so a degenerate metric never draws ("no zero on cards"). */
function isDegenerateSeries(rows: string[][]): boolean {
  const width = rows[0]?.length ?? 0;
  for (let c = 0; c < width; c++) {
    let isNumericCol = true;
    let hasLive = false;
    for (const row of rows) {
      const cell = row[c];
      if (cell == null || cell === "" || cell === "NULL") continue;
      const n = Number(cell);
      if (Number.isNaN(n)) { isNumericCol = false; break; }   // a label/date column, not the measure
      if (n !== 0) hasLive = true;
    }
    if (isNumericCol && hasLive) return false;                // found a real measure → not degenerate
  }
  return true;
}

interface MetricFigure {
  id: string;        // metric name (stable)
  name: string;      // chart title
  columns: string[];
  rows: string[][];
}

// ── Metric-explainer chart card ─────────────────────────────────────────────────

function ChartCard({ figure }: { figure: MetricFigure }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)", minWidth: 0,
    }}>
      {/* Compact briefing chart — 25% shorter than the default render, titled by the
          metric it explains (e.g. "Average Order Value"). */}
      <InvestigationChart
        columns={figure.columns}
        rows={figure.rows}
        heightScale={0.75}
        title={figure.name}
      />
    </div>
  );
}

// ── Finding (prose) card ─────────────────────────────────────────────────────────

function FindingCard({
  finding, domain, onInvestigate, actions,
}: {
  finding: string;
  domain: string;
  onInvestigate: (q: string) => void;
  actions?: ReactNode;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)", minWidth: 0,
    }}>
      <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 600 }}>
        {domain}
      </div>
      <button
        onClick={() => onInvestigate(finding)}
        title="Investigate this finding"
        style={{
          textAlign: "left", background: "transparent", border: "none", padding: 0,
          fontSize: 11.5, lineHeight: 1.5, color: "var(--t1)", cursor: "pointer",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "var(--blue4)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "var(--t1)"; }}
      >
        {finding}
      </button>
      {actions && <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: "auto" }}>{actions}</div>}
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
  /** Reuse the panel's FindingActions so each finding stays actionable (monitor/share/evidence). */
  renderActions?: (insight: ExplorationInsight, domain: string) => ReactNode;
}) {
  // ── Metric-explainer charts: run the top-priority metrics' chart_sql ────────────
  const [metricFigs, setMetricFigs] = useState<MetricFigure[]>([]);
  const [chartsPending, setChartsPending] = useState(false);

  useEffect(() => {
    if (!connectionId) { setMetricFigs([]); return; }
    let alive = true;
    setChartsPending(true);
    (async () => {
      try {
        const p = await getBusinessProfile(connectionId);
        if (!alive) return;
        const metrics: NorthStarMetric[] = (p.available && p.profile?.north_star_metrics) || [];
        // Profile order IS priority order — walk it and keep the first MAX_CHARTS that
        // actually draw as a chart (a real series, not a table/scalar).
        const withSql = metrics.filter(m => m.chart_sql?.trim());
        const figs: MetricFigure[] = [];
        for (const m of withSql) {
          if (figs.length >= MAX_CHARTS) break;
          try {
            const r = await runDirectQuery(connectionId, m.chart_sql!, ROW_LIMIT, { useCache: true });
            if (!alive) return;
            if (r.error || !r.rows || r.rows.length < 2) continue;
            if (isDegenerateSeries(r.rows)) continue;            // flat all-zero/all-null → no card ("no zero on cards")
            const inf = inferChartType(r.columns, r.rows as unknown[][]);
            if (!inf || inf.type === "table") continue;          // not chartable → skip
            figs.push({ id: m.name, name: m.name, columns: r.columns, rows: r.rows });
          } catch { /* fail-safe: skip this metric */ }
        }
        if (alive) setMetricFigs(figs);
      } finally {
        if (alive) setChartsPending(false);
      }
    })();
    return () => { alive = false; };
  }, [connectionId]);

  // ── Finding text cards: dedup, rank by impact (novelty + confidence) ────────────
  const findingCards = useMemo(() => {
    const seen = new Set<string>();
    const out: DashboardFinding[] = [];
    for (const f of findings) {
      const id = f.insight?.id;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(f);
    }
    out.sort((a, b) =>
      ((b.insight.novelty ?? 0) + (b.insight.confidence ?? 0)) -
      ((a.insight.novelty ?? 0) + (a.insight.confidence ?? 0)));
    return out.slice(0, MAX_FINDINGS);
  }, [findings]);

  const hasCharts = metricFigs.length > 0;
  const hasFindings = findingCards.length > 0;
  if (!hasCharts && !hasFindings && !chartsPending) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
      <div className="aug-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span>Dashboard</span>
        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>
          Live
        </span>
        {chartsPending && (
          <span style={{ fontSize: 10, color: "var(--t4)", display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 9, height: 9, border: "1.5px solid var(--b2)", borderTop: "1.5px solid var(--blue4)", borderRadius: "50%", animation: "aug-spin var(--dur-breath) linear infinite" }} />
            charting key metrics…
          </span>
        )}
      </div>

      {/* Key-metric explainer charts — the top-priority metrics drawn as trends/breakdowns. */}
      {hasCharts && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
          {metricFigs.map(f => <ChartCard key={f.id} figure={f} />)}
        </div>
      )}

      {/* New findings — the non-obvious signals, as compact text cards ranked by impact. */}
      {hasFindings && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
          {findingCards.map(f => (
            <FindingCard key={f.insight.id} finding={f.insight.finding} domain={f.domain}
              onInvestigate={onInvestigate} actions={renderActions?.(f.insight, f.domain)} />
          ))}
        </div>
      )}
    </div>
  );
}
