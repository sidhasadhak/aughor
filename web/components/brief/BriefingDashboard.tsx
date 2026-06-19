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
import { getBusinessProfile, runDirectQuery, insightKey, type ExplorationInsight, type NorthStarMetric } from "@/lib/api";
import { InvestigationChart } from "@/components/InvestigationChart";
import { inferChartType } from "@/components/charts/chartTypeInference";
import { InlineInvestigationThread } from "@/components/brief/InlineInvestigationThread";

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

// ── Time-window lens (capability D) ───────────────────────────────────────────
// Re-scope the trend charts to a trailing window. Applied CLIENT-SIDE against each
// series' OWN latest date (data is often historical, so "last 90 days" means relative
// to the data, not today) — robust and instant, no fragile SQL rewriting. Charts
// without a date dimension are left untouched.
interface LensWindow { label: string; days: number | null; }
const LENS_WINDOWS: LensWindow[] = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
  { label: "All", days: null },
];
const _DATE_RE = /^\d{4}-\d{2}(-\d{2})?/;

/** Index of the first column whose values parse as ISO-ish dates, else -1. */
function dateColumnIndex(rows: string[][]): number {
  const width = rows[0]?.length ?? 0;
  for (let c = 0; c < width; c++) {
    let hits = 0, seen = 0;
    for (const row of rows) {
      const v = row[c];
      if (v == null || v === "" || v === "NULL") continue;
      seen++;
      if (_DATE_RE.test(String(v))) hits++;
    }
    if (seen > 0 && hits === seen) return c;
  }
  return -1;
}

/** Keep only the trailing `days` of a trend, measured from the series' latest date.
 *  Returns the figure unchanged when there's no date column or no window. */
function applyWindow(fig: MetricFigure, days: number | null): MetricFigure {
  if (days == null) return fig;
  const di = dateColumnIndex(fig.rows);
  if (di < 0) return fig;                         // not a time series → lens doesn't apply
  let maxMs = -Infinity;
  for (const row of fig.rows) {
    const t = Date.parse(String(row[di]));
    if (!Number.isNaN(t)) maxMs = Math.max(maxMs, t);
  }
  if (maxMs === -Infinity) return fig;
  const cutoff = maxMs - days * 86400_000;
  const rows = fig.rows.filter(row => {
    const t = Date.parse(String(row[di]));
    return Number.isNaN(t) || t >= cutoff;
  });
  return rows.length >= 2 ? { ...fig, rows } : fig;   // keep original if the window is too sparse to draw
}

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
  sql: string;       // the chart_sql that drew it — re-runnable for drill-downs
}

/** A seed for the inline investigation thread (shared by finding cards + chart drills). */
interface ThreadSeed {
  key: string;
  question: string;
  seedSql: string | null;
  seedContext: string;
}

/** The first non-numeric column is the category/x dimension (date or label). */
function pickDimension(columns: string[], rows: string[][]): string | null {
  for (let c = 0; c < columns.length; c++) {
    let numeric = true;
    for (const row of rows) {
      const v = row[c];
      if (v == null || v === "" || v === "NULL") continue;
      if (Number.isNaN(Number(v))) { numeric = false; break; }
    }
    if (!numeric) return columns[c];
  }
  return null;
}

/** Wrap a chart query to keep only the clicked dimension value — filter an existing
 *  result without re-deriving it. String values are quoted (single-quotes escaped). */
function filteredChartSql(chartSql: string, dim: string, value: unknown): string {
  const raw = String(value);
  const lit = Number.isNaN(Number(raw)) || raw.trim() === "" ? `'${raw.replace(/'/g, "''")}'` : raw;
  return `SELECT * FROM (${chartSql.replace(/;\s*$/, "")}) AS _drill WHERE "${dim}" = ${lit}`;
}

// ── Metric-explainer chart card ─────────────────────────────────────────────────

function ChartCard({
  figure, connectionId, onPull,
}: {
  figure: MetricFigure;
  connectionId: string;
  /** Open an inline investigation seeded with the clicked slice (capability B). */
  onPull: (seed: ThreadSeed) => void;
}) {
  // The clicked datum (a bar/point) → a small drill menu; null = nothing selected.
  const [sel, setSel] = useState<{ dim: string; value: unknown } | null>(null);
  // When the user filters the chart to one value, render that filtered series instead.
  const [filtered, setFiltered] = useState<MetricFigure | null>(null);
  const fig = filtered ?? figure;

  const onSelect = (datum: Record<string, unknown>) => {
    const dim = pickDimension(figure.columns, figure.rows);
    if (!dim) return;
    const value = datum[dim];
    if (value == null) return;
    setSel({ dim, value });
  };

  async function applyFilter() {
    if (!sel) return;
    try {
      const sql = filteredChartSql(figure.sql, sel.dim, sel.value);
      const r = await runDirectQuery(connectionId, sql, ROW_LIMIT, { useCache: true });
      if (!r.error && r.rows?.length) {
        setFiltered({ ...figure, name: `${figure.name} · ${sel.value}`, columns: r.columns, rows: r.rows, sql });
      }
    } catch { /* fail-safe: leave the chart as-is */ }
    setSel(null);
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)", border: "1px solid var(--b1)", minWidth: 0,
    }}>
      {/* Compact briefing chart — 25% shorter than the default render, titled by the
          metric it explains (e.g. "Average Order Value"). Click a bar/point to drill. */}
      <InvestigationChart
        columns={fig.columns}
        rows={fig.rows}
        heightScale={0.75}
        title={fig.name}
        onSelect={onSelect}
      />

      {filtered && (
        <button
          onClick={() => setFiltered(null)}
          style={{ alignSelf: "flex-start", fontSize: 10, color: "var(--t3)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          ↩ Clear filter
        </button>
      )}

      {sel && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
          fontSize: 11, color: "var(--t2)", borderTop: "1px solid var(--b1)", paddingTop: 7,
        }}>
          <span><strong>{String(sel.value)}</strong></span>
          <button
            onClick={() => {
              onPull({
                key: `chart:${figure.id}:${String(sel.value)}`,
                question: `Why is ${sel.dim} = ${String(sel.value)} the outlier for ${figure.name}?`,
                seedSql: filteredChartSql(figure.sql, sel.dim, sel.value),
                seedContext: `SEED: investigating the ${figure.name} chart, focused on ${sel.dim} = ${String(sel.value)}.`,
              });
              setSel(null);
            }}
            style={_drillBtn(true)}
          >
            Why is it the outlier?
          </button>
          <button onClick={applyFilter} style={_drillBtn(false)}>Filter chart</button>
          <button onClick={() => setSel(null)} style={{ ..._drillBtn(false), color: "var(--t4)" }}>✕</button>
        </div>
      )}
    </div>
  );
}

function _drillBtn(primary: boolean): React.CSSProperties {
  return {
    fontSize: 11, cursor: "pointer", borderRadius: "var(--r2)", padding: "3px 9px",
    fontWeight: primary ? 600 : 400,
    color: primary ? "var(--bg-0)" : "var(--blue5)",
    background: primary ? "var(--blue5)" : "var(--bg-sel)",
    border: `1px solid ${primary ? "var(--blue5)" : "var(--b1)"}`,
  };
}

// ── Finding (prose) card ─────────────────────────────────────────────────────────

function FindingCard({
  finding, domain, onPull, active, actions,
}: {
  finding: string;
  domain: string;
  /** Open an inline investigation seeded with this finding (capability A). */
  onPull: () => void;
  /** Highlight when this card's thread is the one currently open. */
  active?: boolean;
  actions?: ReactNode;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)",
      border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 600 }}>
        {domain}
      </div>
      <button
        onClick={onPull}
        title="Pull the thread — investigate this finding in place"
        style={{
          textAlign: "left", background: "transparent", border: "none", padding: 0,
          fontSize: 11.5, lineHeight: 1.5, color: active ? "var(--blue4)" : "var(--t1)", cursor: "pointer",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "var(--blue4)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = active ? "var(--blue4)" : "var(--t1)"; }}
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
  schema,
  canvasId,
  onInvestigate,
  renderActions,
}: {
  findings: DashboardFinding[];
  connectionId: string;
  /** Shared schema scope from the workspace header — the metric charts re-fetch the
   *  matching profile when it changes. Undefined = all schemas / connection default. */
  schema?: string;
  /** Canvas scope (when the brief is canvas-bound) — threaded into inline investigations. */
  canvasId?: string;
  /** Escape hatch — open the seeded question in the full Ask surface. */
  onInvestigate: (q: string) => void;
  /** Reuse the panel's FindingActions so each finding stays actionable (monitor/share/evidence). */
  renderActions?: (insight: ExplorationInsight, domain: string) => ReactNode;
}) {
  // Capabilities A + B — one inline investigation thread, seeded either from a clicked
  // finding ("pull the thread") or a clicked chart slice ("why is this the outlier?").
  // Rendered full-width below the grid so the 2-col layout isn't disrupted.
  const [thread, setThread] = useState<ThreadSeed | null>(null);
  // ── Metric-explainer charts: run the top-priority metrics' chart_sql ────────────
  const [metricFigs, setMetricFigs] = useState<MetricFigure[]>([]);
  const [chartsPending, setChartsPending] = useState(false);
  // Capability D — steer the lens: a trailing time window over the trend charts.
  const [windowDays, setWindowDays] = useState<number | null>(null);

  useEffect(() => {
    if (!connectionId) { setMetricFigs([]); return; }
    let alive = true;
    setChartsPending(true);
    (async () => {
      try {
        const p = await getBusinessProfile(connectionId, schema);
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
            figs.push({ id: m.name, name: m.name, columns: r.columns, rows: r.rows, sql: m.chart_sql! });
          } catch { /* fail-safe: skip this metric */ }
        }
        if (alive) setMetricFigs(figs);
      } finally {
        if (alive) setChartsPending(false);
      }
    })();
    return () => { alive = false; };
  }, [connectionId, schema]);

  // ── Finding text cards: dedup, rank by impact (novelty + confidence) ────────────
  const findingCards = useMemo(() => {
    const seen = new Set<string>();
    const out: DashboardFinding[] = [];
    for (const f of findings) {
      const id = f.insight?.id;
      // Dedup by composite identity (source_schema::id) — bare ids collide across schemas in
      // the "All schemas" aggregate, so a plain id-set would silently drop a real finding.
      const key = f.insight ? insightKey(f.insight) : "";
      if (!id || seen.has(key)) continue;
      seen.add(key);
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

  // Apply the time-window lens; only offer the control when at least one chart is a
  // trend (has a date dimension) — a window over a categorical breakdown is meaningless.
  const anyTimeSeries = metricFigs.some(f => dateColumnIndex(f.rows) >= 0);
  const windowedFigs = metricFigs.map(f => applyWindow(f, windowDays));

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
        {/* Capability D — time-window lens over the trend charts. */}
        {anyTimeSeries && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, marginLeft: "auto" }} title="Re-scope the trend charts to a trailing window">
            <span style={{ fontSize: 9, color: "var(--t4)", textTransform: "none", letterSpacing: 0, fontWeight: 400, marginRight: 2 }}>Window</span>
            {LENS_WINDOWS.map(win => {
              const on = windowDays === win.days;
              return (
                <button
                  key={win.label}
                  onClick={() => setWindowDays(win.days)}
                  style={{
                    fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: "var(--r1)", cursor: "pointer",
                    color: on ? "var(--bg-0)" : "var(--t3)",
                    background: on ? "var(--blue5)" : "var(--bg-2)",
                    border: `1px solid ${on ? "var(--blue5)" : "var(--b1)"}`,
                  }}
                >{win.label}</button>
              );
            })}
          </span>
        )}
      </div>

      {/* Key-metric explainer charts — the top-priority metrics drawn as trends/breakdowns.
          Click a bar/point to drill: investigate the slice, or filter the chart to it. */}
      {hasCharts && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
          {windowedFigs.map(f => (
            <ChartCard key={f.id} figure={f} connectionId={connectionId} onPull={setThread} />
          ))}
        </div>
      )}

      {/* New findings — the non-obvious signals, as compact text cards ranked by impact.
          Clicking a finding pulls the thread: an ADA investigation streams in place
          below the grid, seeded with that finding's exact query. */}
      {hasFindings && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
          {findingCards.map(f => {
            const key = `finding:${insightKey(f.insight)}`;
            return (
              <FindingCard key={insightKey(f.insight)} finding={f.insight.finding} domain={f.domain}
                active={thread?.key === key}
                onPull={() => setThread(prev => prev?.key === key ? null : {
                  key,
                  question: `Why is this happening? ${f.insight.finding}`,
                  seedSql: f.insight.sql || null,
                  seedContext: `SEED FINDING (the briefing claim being investigated): ${f.insight.finding}`,
                })}
                actions={renderActions?.(f.insight, f.domain)} />
            );
          })}
        </div>
      )}

      {/* Inline investigation thread — seeded from the clicked finding or chart slice.
          Keyed by seed so picking a different one remounts a fresh stream. */}
      {thread && (
        <InlineInvestigationThread
          key={thread.key}
          question={thread.question}
          opts={{
            connectionId,
            schema: schema ?? null,
            canvasId: canvasId ?? null,
            seedSql: thread.seedSql,
            seedContext: thread.seedContext,
          }}
          onClose={() => setThread(null)}
          onOpenInAsk={onInvestigate}
        />
      )}
    </div>
  );
}
