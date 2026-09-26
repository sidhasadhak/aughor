"use client";

/**
 * IndustryKpiStrip — the per-industry "Key Metrics" scorecard at the top of the
 * Briefing. Each card is a ThoughtSpot-style answer card: the live value, a
 * period-over-period DELTA whose COLOUR reflects whether the move is good or bad for
 * the business (a rising CAC is red even though it's "up"), a matching sparkline, and
 * a one-line trend caption.
 *
 * Click a card → it EXPANDS into a rich chart of that metric's trend (master-detail),
 * so the KPIs themselves are the entry point to the deeper view — replacing the old
 * standalone metric-chart grid.
 *
 * Split into a pure presentational `KpiStripView` + `buildKpi` (value/delta/favorability
 * logic) and the data-fetching `IndustryKpiStrip` container — so the card layout +
 * expand interaction can be exercised in /chart-lab without a backend.
 *
 * Fail-safe: a metric whose value_sql errors / returns no scalar / is out of its stated
 * range is silently dropped — never a wrong number. The delta + sparkline + caption +
 * expand appear only when chart_sql yields a real series; otherwise the card degrades to
 * label + value.
 */
import { useEffect, useState } from "react";
import NumberFlow from "@number-flow/react";
import { getBusinessProfile, runDirectQuery, currencySymbol, type BriefingRangeBlock, type StatedRange } from "@/lib/api";
import { RangeMeasureTile, rangeTop } from "@/components/brief/BriefRange";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { GroundedNumber } from "@/components/brief/GroundedNumber";
import { seriesTrend } from "@/components/brief/Sparkline";
import { StatTile } from "@/components/brief/StatTile";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { useVizConfigs } from "@/lib/useVizConfigs";
import { effectiveCurrencySymbol } from "@/lib/orgSettings";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { betterIsHigher } from "@/lib/favorability";
import { deltaInfo, formatMetric, periodWord, type KpiFlow } from "@/components/brief/metricFormat";

export type { KpiFlow } from "@/components/brief/metricFormat";

interface Trend {
  values: number[];
  deltaText: string;          // "+3.1pts" / "-0.6%" / "+0.4×"
  sign: number;               // -1 | 0 | 1
  favorable: boolean | null;  // good move? (direction-aware); null when flat
  caption: string;            // "climbing" / "easing" / "holding steady" …
}
export interface Kpi {
  name: string; display: string; sql: string; raw: number; color: string;
  trend: Trend | null;
  /** Exact odometer mapping for `display`; absent → render the plain string. */
  flow?: KpiFlow;
  /** Full chart_sql result, kept so a click can expand the card into a rich chart. */
  chart?: { columns: string[]; rows: unknown[][] } | null;
}

// Categorical accent palette for the left border + sparkline (visual variety, like the
// reference). The DELTA badge carries the semantic good/bad colour separately.
export const KPI_ACCENTS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-6)", "var(--chart-5)"];

const trendCaption = (sign: number, favorable: boolean | null) =>
  sign === 0 ? "holding steady" : sign > 0 ? (favorable ? "climbing" : "rising") : (favorable ? "easing" : "slipping");

/** Build a card model from a raw value (+ optional time series + full chart result).
 *  Returns null when the value is broken/degenerate. Shared by the live container and
 *  the /chart-lab harness. */
export function buildKpi(args: {
  name: string; raw: number; unit: string; accent: string;
  /** How `unit` reads, as the API shipped it (`stated_range`) — absent reads as open, never a guessed bound. */
  range?: StatedRange;
  sym?: string; sql?: string; series?: number[];
  chart?: { columns: string[]; rows: unknown[][] } | null;
}): Kpi | null {
  const { name, raw, unit, range, accent, sym = "$", sql = "", series, chart = null } = args;
  const f = formatMetric(raw, unit, sym, name, range);
  if (!f.ok) return null;
  let trend: Trend | null = null;
  if (series && series.length >= 2) {
    const d = deltaInfo(series, unit, name, range);
    if (d) {
      const fav = d.sign === 0 ? null : betterIsHigher(name) ? d.sign > 0 : d.sign < 0;
      trend = { values: series, deltaText: d.text, sign: d.sign, favorable: fav, caption: trendCaption(d.sign, fav) };
    }
  }
  return { name, display: f.display, sql, raw, color: accent, trend, flow: f.flow, chart };
}

/** The big KPI figure. The receipt affordance (GroundedNumber: click → the SQL + cell
 *  behind the number) stays the in-flow element with its text made transparent — layout,
 *  dashed underline, click target and tooltip are byte-identical to the static version and
 *  the card never shifts while digits roll. The NumberFlow odometer paints exactly over it
 *  (aria-hidden + pointer-events:none, top offset cancels its 0.25em mask padding). First
 *  paint mounts at 0 and rolls to the live value; NumberFlow disables the animation for
 *  prefers-reduced-motion users by default (respectMotionPreference), so they see the
 *  final value immediately. */
function KpiValue({ kpi }: { kpi: Kpi }) {
  const flow = kpi.flow;
  const [shown, setShown] = useState(0);
  useEffect(() => { if (flow) setShown(flow.value); }, [flow?.value]);
  const receipt = (
    <GroundedNumber
      token={kpi.display}
      resolve={async () => ({ sql: kpi.sql, grounded: true, matchedCell: kpi.raw, note: "Live value — the result of this query." })}
    />
  );
  if (!flow) return receipt;   // no exact odometer mapping → the plain string, exactly as before
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <span style={{ color: "transparent" }}>{receipt}</span>
      <span aria-hidden style={{ position: "absolute", left: 0, top: "-0.25em", pointerEvents: "none", fontVariantNumeric: "tabular-nums" }}>
        <NumberFlow value={shown} locales="en-US" format={flow.format} prefix={flow.prefix} suffix={flow.suffix} />
      </span>
    </span>
  );
}

// ── Presentational view (no data fetching) — owns the expand/collapse UI state ──
export function KpiStripView({ industry, period, kpis, scopeKey, note }: {
  industry?: string; period?: string; kpis: Kpi[];
  /** Scope for persisting a KPI chart's display config (keyed `kpi:<name>` within it). */
  scopeKey?: string;
  /** BR-9 — what these figures cover when the page is scoped to a range they are NOT measured
   *  for ("all history, not 17–23 August"). Replaces the "vs <period>" word: the number's own
   *  header says what it is, in the same type. */
  note?: string;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { configFor, save } = useVizConfigs(scopeKey ?? "");
  if (!kpis.length) return null;
  const expanded = kpis.find(k => k.name === expandedId && k.chart && k.chart.rows.length >= 2) ?? null;

  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 8 }}>
        Key Metrics
        {industry ? <span style={{ fontWeight: 400, color: "var(--t3)" }}>{` · ${industry}`}</span> : null}
        {note
          ? <span data-testid="kpi-strip-note" style={{ fontWeight: 400, color: "var(--amb4)" }}>{` · ${note}`}</span>
          : period ? <span style={{ fontWeight: 400, color: "var(--t3)" }}>{` · vs ${periodWord(period)}`}</span> : null}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {kpis.map(k => {
          const canExpand = !!(k.chart && k.chart.rows.length >= 2);
          const isOpen = expanded?.name === k.name;
          // Every KPI tile renders through the one canonical StatTile spec; the tuned odometer
          // (KpiValue) rides in as the value slot so this refactor keeps it byte-for-byte.
          return (
            <StatTile
              key={k.name}
              label={k.name}
              accent={k.color}
              value={<KpiValue kpi={k} />}
              delta={k.trend ? { text: k.trend.deltaText, sign: k.trend.sign, favorable: k.trend.favorable } : null}
              sparkline={k.trend?.values ?? null}
              caption={k.trend?.caption}
              expandable={canExpand}
              open={isOpen}
              onClick={canExpand ? () => setExpandedId(isOpen ? null : k.name) : undefined}
              title={canExpand ? (isOpen ? "Collapse" : "Click to expand the trend") : undefined}
            />
          );
        })}
      </div>

      {/* Master-detail: the clicked KPI expands into a rich chart of its trend. */}
      {expanded?.chart && (
        <div
          className="aug-anim-up"
          style={{
            marginTop: 10, padding: "12px 14px", borderRadius: "var(--r3)", background: "var(--bg-2)",
            borderTop: "1px solid var(--b1)", borderRight: "1px solid var(--b1)", borderBottom: "1px solid var(--b1)",
            borderLeft: `3px solid ${expanded.color}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>{expanded.name}</span>
            <button
              onClick={() => setExpandedId(null)}
              title="Close"
              style={{ background: "transparent", border: "none", color: "var(--t3)", fontSize: 15, lineHeight: 1, cursor: "pointer", padding: 2 }}
            >
              ×
            </button>
          </div>
          <ResultChartCard columns={expanded.chart.columns} rows={expanded.chart.rows} title={expanded.name}
            config={configFor(`kpi:${expanded.name}`)}
            onConfigChange={scopeKey ? c => save(`kpi:${expanded.name}`, c) : undefined} />
        </div>
      )}
    </div>
  );
}

/** Direction B (§6.6): when a connection has no north-star metrics, the Key-Metrics slot
 *  holds a quiet dashed CTA instead of vanishing — the standing scorecard row never silently
 *  disappears. Quiet by design so it doesn't compete with real content. */
function DefineKpiCta() {
  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 8 }}>Key Metrics</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, border: "1px dashed var(--b2)", borderRadius: "var(--r2)", padding: "12px 16px", fontSize: 13, color: "var(--t3)" }}>
        <span aria-hidden style={{ width: 6, height: 6, borderRadius: "var(--r-pill)", background: "var(--b3)", flex: "none" }} />
        <span><b style={{ color: "var(--t2)", fontWeight: 500 }}>No north-star metrics defined</b> — define KPIs to add a standing scorecard row.</span>
        <Button variant="ghost" size="xs"
          onClick={() => toast.info("Define north-star metrics", { description: "Set north-star KPIs in the connection's business profile to populate this scorecard row." })}
          style={{ marginLeft: "auto", fontSize: 11 }}>Define KPIs</Button>
      </div>
    </div>
  );
}

// ── Live container ──────────────────────────────────────────────────────────────
export function IndustryKpiStrip({ connectionId, schema, scopeKey, rangeBlock, note }: {
  connectionId: string; schema?: string;
  /** Passed straight through to the view so KPI chart edits persist per scope. */
  scopeKey?: string;
  /** BR-9 — the range Briefing on screen, when there is one: the row then leads with the
   *  APPROVED metrics measured for the range (those the hero does not already show), each
   *  with its status; the standing north stars follow under `note`. */
  rangeBlock?: BriefingRangeBlock | null;
  /** BR-9 — "all history, not <range>" while a range is selected; "" on the standing view. */
  note?: string;
}) {
  const [industry, setIndustry] = useState("");
  const [period, setPeriod] = useState("");
  const [kpis, setKpis] = useState<Kpi[]>([]);
  const [noMetrics, setNoMetrics] = useState(false);   // profile settled, zero metrics defined
  // The currency symbol is baked into each KPI inside the effect below, so re-run the
  // effect when org settings change (else the strip keeps the old currency until reload).
  const orgV = useOrgSettings();

  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    let seenPeriod = "";
    (async () => {
      const p = await getBusinessProfile(connectionId, schema);
      if (!alive) return;
      if (!p.available || !p.profile) { setIndustry(""); setKpis([]); setNoMetrics(true); return; }
      setIndustry(p.profile.industry || "");
      // Override-wins: a set org/workspace currency beats the inferred profile currency,
      // and matches what the expanded charts render from the same orgSettings cache.
      const sym = effectiveCurrencySymbol() || currencySymbol(p.profile.currency_code);
      const metrics = (p.profile.north_star_metrics || []).filter(m => m.value_sql?.trim());
      setNoMetrics(metrics.length === 0);

      const results = await Promise.all(metrics.map(async (m, i): Promise<Kpi | null> => {
        try {
          const r = await runDirectQuery(connectionId, m.value_sql, 2, { useCache: true });
          if (r.error || !r.rows || r.rows.length !== 1) return null;   // need exactly one scalar row
          const cell = r.rows[0].find(c => c != null && c !== "" && !isNaN(Number(c)));
          if (cell == null) return null;

          let series: number[] | undefined;
          let chart: { columns: string[]; rows: unknown[][] } | null = null;
          if (m.chart_sql?.trim()) {
            try {
              const cr = await runDirectQuery(connectionId, m.chart_sql, 500, { useCache: true });
              if (!cr.error && cr.columns && cr.rows && cr.rows.length >= 2) {
                chart = { columns: cr.columns, rows: cr.rows as unknown[][] };
                const st = seriesTrend(cr.columns, cr.rows as (string | number | null)[][]);
                if (st && st.values.length >= 2) { series = st.values; if (!seenPeriod) seenPeriod = st.periodLabel; }
              }
            } catch { /* no trend → card degrades to label + value */ }
          }
          return buildKpi({ name: m.name, raw: Number(cell), unit: m.unit_or_range, range: m.stated_range, accent: KPI_ACCENTS[i % KPI_ACCENTS.length], sym, sql: m.value_sql, series, chart });
        } catch { return null; }
      }));

      if (!alive) return;
      setKpis(results.filter((k): k is Kpi => k !== null));
      setPeriod(seenPeriod);
    })();
    return () => { alive = false; };
  }, [connectionId, schema, orgV]);

  // The range's own row: every approved metric measured for it that the hero is not already
  // showing. Nothing is formatted here — the server's text is the figure.
  const inHero = new Set(rangeBlock ? rangeTop(rangeBlock).map(m => m.metric) : []);
  const rest = rangeBlock ? rangeBlock.measured.filter(m => !inHero.has(m.metric)) : [];
  const measuredRow = rangeBlock && rest.length > 0 ? (
    <div data-testid="kpi-strip-measured" style={{ marginBottom: 14 }}>
      <div className="aug-label" style={{ marginBottom: 8 }}>
        Key Metrics<span style={{ fontWeight: 400, color: "var(--t3)" }}>{` · measured for ${rangeBlock.covers}`}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(4, rest.length)}, minmax(0, 1fr))`, gap: 12 }}>
        {rest.map(m => <RangeMeasureTile key={m.metric} m={m} />)}
      </div>
    </div>
  ) : null;
  if (kpis.length > 0) {
    return (
      <div>
        {measuredRow}
        <KpiStripView industry={industry} period={period} kpis={kpis} scopeKey={scopeKey} note={note} />
      </div>
    );
  }
  if (measuredRow) return measuredRow;
  return noMetrics ? <DefineKpiCta /> : null;
}
