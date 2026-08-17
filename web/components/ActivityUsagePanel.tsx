"use client";

/**
 * Agents · Activity — the USAGE zoom: what the platform actually spent, and on what.
 *
 * Three folds already existed, were tested, and had ZERO frontend consumers — `/obs/model-usage`,
 * `/obs/prompt-weight` and the roles/fallback rollup on `/activity`. Their own docstrings name the
 * gap they were built to close ("the fold has existed since #288 with no caller anywhere: no route,
 * no UI"); the route landed and the gap simply reopened one layer up. This is the layer.
 *
 * Every number here is WINDOWED, and the window ships with it. That is not decoration: read live on
 * 2026-08-14 the fallback rate said 42.8% because the row window reached back into 2026-08-10, a
 * single bad day holding 429 of the log's 499 lifetime fallbacks — the days on either side were 0%.
 * A rate whose window is invisible gets read as "right now".
 *
 * The other rule this surface owes its data: coverage is part of the measurement. Calls whose
 * backend reported no usage are shown, never folded away — a model that does not report tokens must
 * not read as free — and the call-site table says what fraction of calls carried attribution at all
 * rather than presenting a top-N built from 3% of the traffic.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import { getApiBase } from "@/lib/config";
import { fmtMs } from "@/lib/cost";
import { compactNumber, formatCount, pct } from "@/lib/format";

type RoleFold = Record<string, { calls: number; tokens: number }>;
type Window = { scanned_rows: number; from: string | null; to: string | null };
type Fallback = { fell_back: number; of_attributed: number; rate: number | null };

type ModelRow = {
  provider: string; model: string; calls: number; failures: number;
  prompt_tokens: number; completion_tokens: number; total_tokens: number;
  calls_without_usage: number; retried_calls: number; mean_ms: number; failure_rate: number;
};

type SiteRow = {
  caller: string; calls: number; prompt_tokens: number; completion_tokens: number;
  calls_without_usage: number; roles: Record<string, number>;
};

const UNATTRIBUTED = "(unattributed)";

/** ONE scan for all three folds. They are shown under a single window label, so they have to be
 *  folded over a single window — otherwise the role table's token total and the model table's are
 *  drawn from different populations and invite exactly the comparison they cannot support. */
const SCAN = 5000;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, { headers: { "Content-Type": "application/json" } });
  if (!res.ok) throw new Error((await res.text().catch(() => res.statusText)) || `HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

const card: React.CSSProperties = {
  border: "1px solid var(--b0)", borderRadius: "var(--r3)", padding: "12px 14px", marginBottom: 12,
};
const head: React.CSSProperties = { fontSize: 12, fontWeight: 600, marginBottom: 8 };
const sub: React.CSSProperties = { fontSize: 11, color: "var(--t3)", fontWeight: 400 };
const num: React.CSSProperties = { fontVariantNumeric: "tabular-nums", textAlign: "right" };
const th: React.CSSProperties = { ...sub, textAlign: "left", padding: "0 8px 4px 0", fontWeight: 400 };
const td: React.CSSProperties = { fontSize: 12, padding: "3px 8px 3px 0", borderTop: "1px solid var(--b0)" };

/** A share bar — the one place a proportion is worth drawing rather than printing. */
function Share({ value }: { value: number }) {
  return (
    <span style={{ display: "inline-block", width: 54, height: 4, borderRadius: "var(--r1)",
      background: "var(--bg-3)", overflow: "hidden", verticalAlign: "middle" }}>
      <span style={{ display: "block", width: `${Math.max(1, Math.round(value * 100))}%`, height: "100%",
        background: "var(--blue3)" }} />
    </span>
  );
}

export function ActivityUsagePanel() {
  const [roles, setRoles] = useState<RoleFold>({});
  const [win, setWin] = useState<Window | null>(null);
  const [fallback, setFallback] = useState<Fallback | null>(null);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [scanned, setScanned] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setErr(null);
    Promise.all([
      getJson<{ roles: RoleFold; window: Window; fallback: Fallback }>(`/activity?limit=1&scan=${SCAN}`),
      getJson<{ models: ModelRow[] }>(`/obs/model-usage?scan=${SCAN}`),
      getJson<{ sites: SiteRow[]; scanned_calls: number }>(`/obs/prompt-weight?scan=${SCAN}`),
    ]).then(([act, mu, pw]) => {
      setRoles(act.roles || {});
      setWin(act.window || null);
      setFallback(act.fallback || null);
      setModels(mu.models || []);
      setSites(pw.sites || []);
      setScanned(pw.scanned_calls ?? null);
    }).catch(e => setErr(String(e?.message || e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const roleTokens = Object.values(roles).reduce((a, r) => a + r.tokens, 0);
  const roleCalls = Object.values(roles).reduce((a, r) => a + r.calls, 0);
  const modelTokens = models.reduce((a, m) => a + m.total_tokens, 0);
  const noUsage = models.reduce((a, m) => a + m.calls_without_usage, 0);
  const attributed = sites.filter(s => s.caller !== UNATTRIBUTED);
  const attributedCalls = attributed.reduce((a, s) => a + s.calls, 0);

  return (
    <div style={{ padding: "12px 20px", overflowY: "auto", height: "100%" }}>
      {err && <div style={{ ...card, color: "var(--destructive)", fontSize: 12 }}>{err}</div>}

      {/* ── the window every number below is folded over ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <StatusChip hue="muted" strength="soft">
          {win ? `${formatCount(win.scanned_rows)} rows` : "—"}
        </StatusChip>
        <span style={sub}>
          {win?.from ? `${win.from.slice(0, 16).replace("T", " ")} → ${(win.to || "").slice(0, 16).replace("T", " ")}` : "no window"}
          {" · a row window, not a time span — a quiet week and a busy hour look the same width"}
        </span>
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="xs" onClick={load} disabled={loading}>
          {loading ? "loading…" : "refresh"}
        </Button>
      </div>

      {/* ── 1. what the budget went to ── */}
      <div style={card}>
        <div style={head}>Spend by role <span style={sub}>· what the calls were FOR</span></div>
        {roleCalls === 0 ? <div style={sub}>No attributed calls in this window.</div> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>role</th><th style={{ ...th, ...num }}>calls</th>
              <th style={{ ...th, ...num }}>tokens</th><th style={{ ...th, ...num }}>share</th><th style={th} />
            </tr></thead>
            <tbody>
              {Object.entries(roles).sort((a, b) => b[1].tokens - a[1].tokens).map(([role, r]) => {
                const share = roleTokens > 0 ? r.tokens / roleTokens : 0;
                return (
                  <tr key={role}>
                    <td style={td}>{role}</td>
                    <td style={{ ...td, ...num }}>{formatCount(r.calls)}</td>
                    <td style={{ ...td, ...num }}>{compactNumber(r.tokens)}</td>
                    <td style={{ ...td, ...num }}>{pct(share)}</td>
                    <td style={td}><Share value={share} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── 2. the chain's health ── */}
      <div style={card}>
        <div style={head}>Provider fallback <span style={sub}>· the primary refused and a backup answered</span></div>
        {!fallback || fallback.of_attributed === 0 ? (
          <div style={sub}>Nothing in this window could have fallen back.</div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12 }}>
            <StatusChip hue={(fallback.rate ?? 0) > 0.2 ? "caution" : "positive"} strength="soft">
              {/* null, never 0% — a share of zero eligible calls is undefined */}
              {fallback.rate == null ? "—" : pct(fallback.rate)}
            </StatusChip>
            <span style={sub}>
              {formatCount(fallback.fell_back)} of {formatCount(fallback.of_attributed)} eligible calls.
              Denominator counts only calls that could have fallen back — never the whole window.
            </span>
          </div>
        )}
      </div>

      {/* ── 3. which model, and is it failing ── */}
      <div style={card}>
        <div style={head}>
          Models <span style={sub}>· calls, tokens, latency, failure rate</span>
        </div>
        {models.length === 0 ? <div style={sub}>No model calls in this window.</div> : (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>
                <th style={th}>provider · model</th>
                <th style={{ ...th, ...num }}>calls</th>
                <th style={{ ...th, ...num }}>tokens</th>
                <th style={{ ...th, ...num }}>share</th>
                <th style={{ ...th, ...num }}>mean</th>
                <th style={{ ...th, ...num }}>failures</th>
                <th style={{ ...th, ...num }}>no usage</th>
              </tr></thead>
              <tbody>
                {models.map(m => (
                  <tr key={`${m.provider}/${m.model}`}>
                    <td style={td}>
                      <span style={{ color: "var(--t3)" }}>{m.provider}</span> · {m.model}
                    </td>
                    <td style={{ ...td, ...num }}>{formatCount(m.calls)}</td>
                    <td style={{ ...td, ...num }}>{compactNumber(m.total_tokens)}</td>
                    <td style={{ ...td, ...num }}>{pct(modelTokens > 0 ? m.total_tokens / modelTokens : 0)}</td>
                    <td style={{ ...td, ...num }}>{fmtMs(m.mean_ms)}</td>
                    <td style={{ ...td, ...num, color: m.failure_rate > 0.02 ? "var(--red4)" : undefined }}>
                      {m.failures > 0 ? `${formatCount(m.failures)} · ${pct(m.failure_rate)}` : "—"}
                    </td>
                    {/* Never hidden: a backend that reports no usage must not read as free. */}
                    <td style={{ ...td, ...num, color: "var(--t3)" }}>
                      {m.calls_without_usage > 0 ? formatCount(m.calls_without_usage) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {noUsage > 0 && (
              <div style={{ ...sub, marginTop: 6 }}>
                {formatCount(noUsage)} call{noUsage === 1 ? "" : "s"} reported no token usage — their
                tokens are missing from every total above, not counted as zero.
              </div>
            )}
          </>
        )}
      </div>

      {/* ── 4. which template eats the prompt budget ── */}
      <div style={card}>
        <div style={head}>
          Call sites <span style={sub}>· where the prompt tokens go (PE-1)</span>
        </div>
        {/* The coverage IS the measurement: attribution began 2026-08-14, so history predates it
            entirely. Presenting a top-N over 3% of traffic without saying so would be a chart
            that looks like an answer. */}
        {scanned != null && (
          <div style={{ ...sub, marginBottom: 8 }}>
            {attributedCalls === 0
              ? `None of the ${formatCount(scanned)} scanned calls carry call-site attribution yet — it is stamped going forward, so this fills in as traffic runs.`
              : `${formatCount(attributedCalls)} of ${formatCount(scanned)} scanned calls carry attribution (${pct(attributedCalls / scanned)}). The rest predate it.`}
          </div>
        )}
        {attributed.length === 0 ? null : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>call site</th>
              <th style={{ ...th, ...num }}>calls</th>
              <th style={{ ...th, ...num }}>prompt tokens</th>
              <th style={th}>roles</th>
            </tr></thead>
            <tbody>
              {attributed.map(s => (
                <tr key={s.caller}>
                  <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{s.caller}</td>
                  <td style={{ ...td, ...num }}>{formatCount(s.calls)}</td>
                  <td style={{ ...td, ...num }}>{compactNumber(s.prompt_tokens)}</td>
                  <td style={{ ...td, color: "var(--t3)" }}>
                    {Object.entries(s.roles).map(([r, n]) => `${r}·${n}`).join("  ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default ActivityUsagePanel;
