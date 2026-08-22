"use client";

/**
 * Agent Ops · Activity · Usage — what the platform spent, on what, and how much of that
 * we can actually see.
 *
 * This replaces an orphaned panel, removed by this change. `ActivityUsagePanel.tsx`
 * was written, never imported by anything, and half broken: it asked `/activity`
 * for `roles`, `window` and `fallback`, which that route has never returned, so
 * its fallback card could not populate no matter what the data said. The fix was
 * not in the component — the columns did not exist. W0's Migration 10 promoted
 * `role` and `fallback` out of the JSON payload, and `/obs/usage-summary` folds them
 * over the shared window; this panel reads that.
 *
 * **Coverage is part of the measurement, not a footnote.** Three numbers here exist only to
 * stop a small figure reading as a cheap week: calls whose backend reported no usage, calls
 * on models nothing publishes a price for, and the denominator of the fallback rate. A rate
 * whose base is invisible gets read as "right now"; measured on this store on 2026-08-14
 * the fallback rate said 42.8% because the row window reached back into a single bad day.
 *
 * **Every ranked row is a door.** Clicking a model or a call site opens the events that
 * produced it — the filters W0 added to `/activity`. Before them the top-N was a dead end:
 * the columns were indexed and unreachable.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { ActivityChart, colorFor } from "@/components/agentops/ActivityChart";
import { rangeLabel, rangeParams, type TimeRange } from "@/components/agentops/useTimeRange";
import { StatTile } from "@/components/brief/StatTile";
import { Button } from "@/components/ui/button";
import {
  getObsTimeseries, getUsageSummary,
  type TimeSeriesResponse, type UsageSummary,
} from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { compactNumber, formatCount, pct } from "@/lib/format";

export function UsagePanel({ range, onBrush, onOpenEvents }: {
  range: TimeRange;
  onBrush: (since: string, until: string) => void;
  /** Drill: show the events behind one model / call site / role. */
  onOpenEvents: (filter: { model?: string; provider?: string; role?: string }) => void;
}) {
  const [data, setData] = useState<UsageSummary | null>(null);
  const [chart, setChart] = useState<TimeSeriesResponse | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => rangeParams(range), [range]);

  const load = useCallback(() => {
    getUsageSummary(params).then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
    getObsTimeseries({ group: "model", measure: "tokens", ...params })
      .then(setChart).catch(() => setChart(null));
  }, [params]);

  useEffect(() => { load(); }, [load]);

  if (error && !data) {
    return <div className="aug-fs-sm" style={{ padding: 20, color: "var(--red4)" }}>{error}</div>;
  }
  if (!data) {
    return <div className="aug-fs-sm" style={{ padding: 20, color: "var(--t2)" }}>Loading usage…</div>;
  }

  const label = rangeLabel(range);
  const order = (chart?.series ?? []).map(s => s.key);
  const fb = data.fallback;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex",
                  flexDirection: "column", gap: 14, minHeight: 0 }}>
      <Head title={`Model spend · ${label}`}
        sub={`${formatCount(data.calls)} calls scanned in this window`} />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <StatTile label="Calls" value={formatCount(data.calls)} accent="var(--chart-1)"
          caption={data.calls_without_usage > 0
            ? `${formatCount(data.calls_without_usage)} reported no usage`
            : "every call reported its usage"}
          title="LLM calls in the window" />

        <StatTile label="Tokens" value={compactNumber(data.tokens)} accent="var(--chart-3)"
          caption={data.usage_coverage == null ? "no calls in window"
            : `${pct(data.usage_coverage)} of calls reported usage`}
          title="Tokens across every model" />

        <StatTile label="Cost" value={`$${data.cost_usd.toFixed(2)}`} accent="var(--chart-2)"
          caption={data.unpriced_calls > 0
            ? `${formatCount(data.unpriced_calls)} calls unpriced — a floor, not a total`
            : "every call priced from the provider's catalogue"}
          title="Priced from each provider's published rates" />

        <StatTile label="Fallback rate"
          value={fb.rate == null ? "—" : pct(fb.rate)} accent="var(--chart-5)"
          caption={fb.of_attributed === 0
            ? "no call recorded whether it fell back"
            : `${formatCount(fb.fell_back)} of ${formatCount(fb.of_attributed)} attributed calls`}
          title="How often the primary backend refused and another provider answered" />

        <StatTile label="Models" value={formatCount(data.models.length)} accent="var(--chart-4)"
          caption={`${formatCount(data.roles.length)} distinct roles`}
          title="Distinct models used in the window" />
      </div>

      {/* ── tokens by model, on the shared axis ── */}
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
                        borderRadius: "var(--r3)", padding: "12px 12px 8px" }}>
        <Head title="Tokens by model" sub="hover a bar · click to filter · drag to brush" />
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(chart?.series ?? []).slice(0, 8).map(s => {
            const off = hidden.has(s.key);
            return (
              <Button key={s.key} variant="ghost" size="xs" aria-pressed={!off}
                onClick={() => setHidden(prev => {
                  const next = new Set(prev);
                  if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
                  return next;
                })}
                title={off ? `Show ${s.label}` : `Hide ${s.label}`}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6, height: "auto",
                  padding: "3px 8px", borderRadius: "var(--r-pill)",
                  border: "1px solid var(--b2)", background: "var(--bg-3)",
                  color: "var(--t1)", fontSize: 12, opacity: off ? 0.45 : 1,
                  textDecoration: off ? "line-through" : "none",
                }}>
                <i aria-hidden style={{ width: 9, height: 9, borderRadius: 2,
                  background: colorFor(s.key, order) }} />
                {s.label || "(unattributed)"}
              </Button>
            );
          })}
        </div>
        {chart && chart.series.length > 0 ? (
          <div style={{ marginTop: 8 }}>
            <ActivityChart window={chart.window} edges={chart.edges} series={chart.series}
              runners={[]} showRunners={false} hidden={hidden} order={order}
              selection={null} onBrush={onBrush} onPickBucket={onBrush} />
            <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: "4px 0 0" }}>
              {label} · {chart.window.buckets} bins · y = tokens
              {chart.coverage != null && ` · ${pct(chart.coverage)} of scanned calls named a model`}
            </p>
          </div>
        ) : (
          <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "10px 0 4px" }}>
            No model calls in this window.
          </p>
        )}
      </section>

      {/* ── the ranked lists, each a door ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14 }}>
        <Ranked title="Top models" note="click a row to see its calls"
          empty="No model calls in this window."
          rows={data.models.map(m => ({
            key: `${m.provider}/${m.model}`,
            label: m.model || "(unknown)",
            sub: `${m.provider || "—"} · ${formatCount(m.calls)} calls · ${fmtMs(m.mean_ms)} mean`
              + (m.failures ? ` · ${pct(m.failure_rate)} failed` : "")
              + (m.calls_without_usage ? ` · ${m.calls_without_usage} without usage` : ""),
            value: compactNumber(m.total_tokens),
            color: colorFor(m.model, order),
            onOpen: () => onOpenEvents({ model: m.model, provider: m.provider }),
          }))} />

        <Ranked title="Top call sites" note="which templates the budget goes to"
          empty="No attributed call sites in this window."
          rows={data.sites.map(s => ({
            key: s.caller,
            label: s.caller,
            sub: `${formatCount(s.calls)} calls`
              + (s.calls_without_usage ? ` · ${s.calls_without_usage} without usage` : ""),
            value: compactNumber(s.prompt_tokens),
            color: "var(--t3)",
            onOpen: undefined,
          }))} />

        <Ranked title="By role" note="what the calls were FOR"
          empty="No call recorded a role. Migration 10 promoted this out of the payload — rows written before it stay unattributed."
          rows={data.roles.map(r => ({
            key: r.role,
            label: r.role,
            sub: `${formatCount(r.calls)} calls`,
            value: compactNumber(r.total_tokens),
            color: "var(--t3)",
            onOpen: r.role === "(unattributed)" ? undefined
              : () => onOpenEvents({ role: r.role }),
          }))} />
      </div>
    </div>
  );
}

function Head({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
      <h4 className="aug-label" style={{ color: "var(--t2)", margin: 0 }}>{title}</h4>
      {sub && <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{sub}</span>}
    </div>
  );
}

function Ranked({ title, note, rows, empty }: {
  title: string; note: string; empty: string;
  rows: Array<{ key: string; label: string; sub: string; value: string; color: string;
                onOpen?: () => void }>;
}) {
  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
                      borderRadius: "var(--r3)", padding: "12px 12px 6px" }}>
      <Head title={title} sub={note} />
      {rows.length === 0 ? (
        <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "0 0 8px" }}>{empty}</p>
      ) : (
        <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((r, i) => (
            <li key={r.key} style={{ borderTop: i ? "1px solid var(--b1)" : undefined }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0" }}>
                <span className="aug-fs-xs" style={{ color: "var(--t2)", width: 14,
                  fontFamily: "var(--font-mono)", textAlign: "right" }}>{i + 1}</span>
                <i aria-hidden style={{ width: 9, height: 9, borderRadius: 2, flex: "0 0 auto",
                  background: r.color }} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="aug-fs-sm" style={{ color: "var(--t1)", overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</div>
                  <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>{r.sub}</div>
                </div>
                <span className="aug-fs-sm" style={{ color: "var(--t1)",
                  fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                  {r.value}
                </span>
                {r.onOpen && (
                  <Button variant="ghost" size="xs" onClick={r.onOpen}
                    style={{ color: "var(--blue4)" }}>Explore ›</Button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
