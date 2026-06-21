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
import { getBusinessProfile, runDirectQuery, currencySymbol } from "@/lib/api";
import { GroundedNumber } from "@/components/brief/GroundedNumber";
import { Sparkline, seriesTrend } from "@/components/brief/Sparkline";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import { effectiveCurrencySymbol } from "@/lib/orgSettings";
import { useOrgSettings } from "@/lib/useOrgSettings";
import { betterIsHigher } from "@/lib/favorability";

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
  /** Full chart_sql result, kept so a click can expand the card into a rich chart. */
  chart?: { columns: string[]; rows: unknown[][] } | null;
}

// Categorical accent palette for the left border + sparkline (visual variety, like the
// reference). The DELTA badge carries the semantic good/bad colour separately.
export const KPI_ACCENTS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-6)", "var(--chart-5)"];

const isMultiplier = (name: string, unit: string) =>
  /\b(x|×|multiple|multiplier|roas|times)\b/i.test(unit) || /\broas\b|return on ad/i.test(name);

/** Format a raw scalar by its declared unit/range; gate out broken values. The business's
 *  currency symbol is used for money metrics — a €-company never shows '$'. */
function formatMetric(v: number, unit: string, sym: string, name: string): { display: string; ok: boolean } {
  const u = (unit || "").toLowerCase();
  let display: string;
  if (isMultiplier(name, u)) {
    if (v <= 0 || v > 1000) return { display: "", ok: false };
    display = `${v.toFixed(2)}×`;
  } else if (/ratio|0-1|0\.\.1/.test(u) && !/0-100|0\.\.100/.test(u)) {
    if (v < -0.001 || v > 1.05) return { display: "", ok: false };   // broken bounded rate (>1)
    if (v >= 0.9995) return { display: "", ok: false };              // rounds to 100% — degenerate
    display = `${(v * 100).toFixed(1)}%`;
  } else if (/percent|0-100|0\.\.100|%/.test(u)) {
    if (v < -0.5 || v > 105) return { display: "", ok: false };
    if (v >= 99.95) return { display: "", ok: false };
    display = `${v.toFixed(1)}%`;
  } else if (/day/.test(u)) {
    display = `${v.toFixed(1)}d`;
  } else {
    const a = Math.abs(v);
    const s = a >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
            : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
            : a >= 1e3 ? `${(v / 1e3).toFixed(1)}K`
            : Number.isInteger(v) ? String(v) : v.toFixed(2);
    const pre = /usd|eur|gbp|jpy|cny|inr|[$€£¥₹]|revenue|spend|cost|gmv|sales|value|price/.test(u) ? sym : "";
    display = pre + s;
  }
  if (Math.abs(parseFloat(display.replace(/[^0-9.eE-]/g, "")) || 0) === 0) return { display: "", ok: false };
  return { display, ok: true };
}

/** Period-over-period delta in the metric's own terms: pts for rates, × for multipliers,
 *  relative % for everything else. null when there aren't two points. */
function deltaInfo(values: number[], unit: string, name: string): { text: string; sign: number } | null {
  if (values.length < 2) return null;
  const prev = values[values.length - 2], last = values[values.length - 1];
  const diff = last - prev;
  const sign = Math.abs(diff) < 1e-12 ? 0 : diff > 0 ? 1 : -1;
  const u = (unit || "").toLowerCase();
  let text: string;
  if (isMultiplier(name, u)) {
    text = `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}×`;
  } else if (/ratio|0-1|0\.\.1/.test(u) && !/0-100/.test(u)) {
    const pts = diff * 100;
    text = `${pts >= 0 ? "+" : ""}${pts.toFixed(1)}pts`;
  } else if (/percent|0-100|%/.test(u)) {
    text = `${diff >= 0 ? "+" : ""}${diff.toFixed(1)}pts`;
  } else {
    const rel = prev !== 0 ? (diff / Math.abs(prev)) * 100 : 0;
    text = `${rel >= 0 ? "+" : ""}${rel.toFixed(1)}%`;
  }
  return { text, sign };
}

const trendCaption = (sign: number, favorable: boolean | null) =>
  sign === 0 ? "holding steady" : sign > 0 ? (favorable ? "climbing" : "rising") : (favorable ? "easing" : "slipping");

const periodWord = (label: string) =>
  ({ DoD: "yesterday", WoW: "last week", MoM: "last month", QoQ: "last quarter", YoY: "last year", HoH: "prior hour" } as Record<string, string>)[label] ?? "prior period";

/** Build a card model from a raw value (+ optional time series + full chart result).
 *  Returns null when the value is broken/degenerate. Shared by the live container and
 *  the /chart-lab harness. */
export function buildKpi(args: {
  name: string; raw: number; unit: string; accent: string;
  sym?: string; sql?: string; series?: number[];
  chart?: { columns: string[]; rows: unknown[][] } | null;
}): Kpi | null {
  const { name, raw, unit, accent, sym = "$", sql = "", series, chart = null } = args;
  const f = formatMetric(raw, unit, sym, name);
  if (!f.ok) return null;
  let trend: Trend | null = null;
  if (series && series.length >= 2) {
    const d = deltaInfo(series, unit, name);
    if (d) {
      const fav = d.sign === 0 ? null : betterIsHigher(name) ? d.sign > 0 : d.sign < 0;
      trend = { values: series, deltaText: d.text, sign: d.sign, favorable: fav, caption: trendCaption(d.sign, fav) };
    }
  }
  return { name, display: f.display, sql, raw, color: accent, trend, chart };
}

// ── Presentational view (no data fetching) — owns the expand/collapse UI state ──
export function KpiStripView({ industry, period, kpis }: { industry?: string; period?: string; kpis: Kpi[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  if (!kpis.length) return null;
  const expanded = kpis.find(k => k.name === expandedId && k.chart && k.chart.rows.length >= 2) ?? null;

  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 8 }}>
        Key Metrics
        {industry ? <span style={{ fontWeight: 400, color: "var(--t4)" }}>{` · ${industry}`}</span> : null}
        {period ? <span style={{ fontWeight: 400, color: "var(--t4)" }}>{` · vs ${periodWord(period)}`}</span> : null}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {kpis.map(k => {
          const fav = k.trend?.favorable;
          const deltaColor = fav == null ? "var(--t3)" : fav ? "var(--grn4)" : "var(--red4)";
          const deltaBg = fav == null ? "var(--bg-3)" : fav ? "var(--grn1)" : "var(--red1)";
          const canExpand = !!(k.chart && k.chart.rows.length >= 2);
          const isOpen = expanded?.name === k.name;
          return (
            <div
              key={k.name}
              onClick={canExpand ? () => setExpandedId(isOpen ? null : k.name) : undefined}
              title={canExpand ? (isOpen ? "Collapse" : "Click to expand the trend") : undefined}
              style={{
                position: "relative", flex: "1 1 160px", minWidth: 150, padding: "11px 13px",
                borderRadius: "var(--r2)", background: isOpen ? "var(--bg-3)" : "var(--bg-2)",
                // Explicit per-side borders (not the `border` shorthand) so they don't conflict
                // with borderLeft on rerender — React warns about mixing shorthand + longhand.
                borderTop: `1px solid ${isOpen ? k.color : "var(--b1)"}`,
                borderRight: `1px solid ${isOpen ? k.color : "var(--b1)"}`,
                borderBottom: `1px solid ${isOpen ? k.color : "var(--b1)"}`,
                borderLeft: `3px solid ${k.color}`,
                display: "flex", flexDirection: "column", gap: 7,
                cursor: canExpand ? "pointer" : "default",
                transition: "background var(--dur-fast), border-color var(--dur-fast)",
              }}
            >
              <div
                style={{ fontSize: 9.5, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingRight: 14 }}
                title={k.name}
              >
                {k.name}
              </div>
              {canExpand && (
                <span aria-hidden style={{ position: "absolute", top: 9, right: 10, fontSize: 11, lineHeight: 1, color: isOpen ? k.color : "var(--t4)" }}>
                  {isOpen ? "×" : "⤢"}
                </span>
              )}
              <div style={{ fontSize: 25, color: "var(--t1)", fontWeight: 700, fontFamily: "var(--font-mono)", lineHeight: 1 }}>
                <GroundedNumber
                  token={k.display}
                  resolve={async () => ({ sql: k.sql, grounded: true, matchedCell: k.raw, note: "Live value — the result of this query." })}
                />
              </div>
              {k.trend && k.trend.sign !== 0 && (
                <span style={{
                  alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: 3,
                  fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)",
                  color: deltaColor, background: deltaBg, padding: "1px 6px", borderRadius: "var(--r1)",
                }}>
                  {k.trend.sign > 0 ? "↑" : "↓"} {k.trend.deltaText}
                </span>
              )}
              {k.trend && <Sparkline values={k.trend.values} color={k.color} width={130} height={26} showDot={false} />}
              {k.trend && <div style={{ fontSize: 10.5, color: "var(--t3)" }}>{k.trend.caption}</div>}
            </div>
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
          <ResultChartCard columns={expanded.chart.columns} rows={expanded.chart.rows} title={expanded.name} />
        </div>
      )}
    </div>
  );
}

// ── Live container ──────────────────────────────────────────────────────────────
export function IndustryKpiStrip({ connectionId, schema }: { connectionId: string; schema?: string }) {
  const [industry, setIndustry] = useState("");
  const [period, setPeriod] = useState("");
  const [kpis, setKpis] = useState<Kpi[]>([]);
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
      if (!p.available || !p.profile) { setIndustry(""); setKpis([]); return; }
      setIndustry(p.profile.industry || "");
      // Override-wins: a set org/workspace currency beats the inferred profile currency,
      // and matches what the expanded charts render from the same orgSettings cache.
      const sym = effectiveCurrencySymbol() || currencySymbol(p.profile.currency_code);
      const metrics = (p.profile.north_star_metrics || []).filter(m => m.value_sql?.trim());

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
          return buildKpi({ name: m.name, raw: Number(cell), unit: m.unit_or_range, accent: KPI_ACCENTS[i % KPI_ACCENTS.length], sym, sql: m.value_sql, series, chart });
        } catch { return null; }
      }));

      if (!alive) return;
      setKpis(results.filter((k): k is Kpi => k !== null));
      setPeriod(seenPeriod);
    })();
    return () => { alive = false; };
  }, [connectionId, schema, orgV]);

  return <KpiStripView industry={industry} period={period} kpis={kpis} />;
}
