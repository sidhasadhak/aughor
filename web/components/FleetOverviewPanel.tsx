"use client";

/**
 * CR3 — the fleet overview: KPI tiles over the jobs table + ONE fleet table
 * unifying charters and personas WITH THE KIND LABELLED (charter ≠ persona —
 * the collision was dodged twice in Wave H and stays dodged here).
 *
 * Honesty rules rendered, not just documented:
 * - charter spend (job metering) and persona spend (session log) are shown
 *   under their own labels; a persona whose spend isn't recorded says so and
 *   names the flag — never a confident 0.
 * - `unmetered runs` are counted beside tokens (a NULL metrics blob is not
 *   zero spend), and orphaned restarts are separated from agent errors.
 * - concurrency renders what the kernel has: one global cap + exempt kinds.
 * - dollar cost deliberately absent — it lives on /usage with its own RBAC
 *   and its own `cost_is_complete` caveat.
 *
 * Calm is the default density; NOC adds the spend columns.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Sparkline } from "@/components/brief/Sparkline";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  cancelJob, getFleetOverview, getJobs, patchAgent, patchUserAgent,
  type FleetJob, type FleetOverview, type FleetRow,
} from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { subscribeKernelEvents } from "@/lib/events";
import { compactNumber, formatCount, pct, relTime } from "@/lib/format";

type Density = "calm" | "noc";

export function FleetOverviewPanel({ onOpenAgent }: { onOpenAgent?: (id: string) => void }) {
  const [data, setData] = useState<FleetOverview | null>(null);
  const [activeJobs, setActiveJobs] = useState<FleetJob[]>([]);
  const [density, setDensity] = useState<Density>("calm");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    getFleetOverview().then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
    getJobs({ state: "active", limit: 50 }).then(setActiveJobs).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["job.state"] });
    const iv = setInterval(load, 15_000); // slow fallback if the stream is down
    return () => { unsub(); clearInterval(iv); };
  }, [load]);

  const togglePause = async (row: FleetRow) => {
    setBusy(row.id);
    try {
      if (row.kind === "charter") await patchAgent(row.id, { enabled: !row.enabled });
      else await patchUserAgent(row.id, { enabled: !row.enabled });
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  if (error && !data) {
    return <div style={{ padding: 24, color: "var(--red4)", fontSize: 12 }}>{error}</div>;
  }
  if (!data) {
    return <div style={{ padding: 24, color: "var(--t3)", fontSize: 12 }}>Loading fleet…</div>;
  }

  const { tiles } = data;
  const noc = density === "noc";
  const charters = data.rows.filter(r => r.kind === "charter");
  const personas = data.rows.filter(r => r.kind === "persona");

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      {/* ── KPI tiles ── */}
      <MiniStatRow>
        <MiniStat value={tiles.active_jobs} label="Active jobs"
          tone={tiles.active_jobs > 0 ? "var(--blue4)" : "var(--t1)"} />
        <MiniStat value={tiles.runs_per_min} label={`Runs/min · last ${tiles.window_minutes}m`} />
        <MiniStat value={tiles.p95_duration_ms != null ? fmtMs(tiles.p95_duration_ms) : "—"}
          label="p95 duration (window)" />
        <MiniStat
          value={tiles.error_rate != null ? pct(tiles.error_rate) : "—"}
          label={`Error rate · ${tiles.failed_runs} failed, ${tiles.orphaned_runs} orphaned restarts (excluded)`}
          tone={tiles.error_rate ? "var(--red4)" : "var(--t1)"} />
        <MiniStat
          value={tiles.tokens.per_hour != null ? compactNumber(tiles.tokens.per_hour) : "—"}
          label={`Tokens/hr · ${tiles.tokens.metered_runs} metered, ${tiles.tokens.unmetered_runs} unmetered`} />
        <MiniStat value={tiles.concurrency.max_concurrent_jobs}
          label={`Concurrency cap (global) · exempt: ${tiles.concurrency.unbounded_kinds.join(", ") || "none"}`} />
      </MiniStatRow>

      {/* ── density toggle ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span className="aug-label" style={{ color: "var(--t3)" }}>The fleet</span>
        <span style={{ flex: 1 }} />
        {!data.session_log_recording && (
          <span style={{ fontSize: 11, color: "var(--amb4)" }}>
            session log not recording — persona spend is frozen at its last rows
          </span>
        )}
        <Button variant={density === "calm" ? "secondary" : "ghost"} size="xs"
          onClick={() => setDensity("calm")}>Calm</Button>
        <Button variant={noc ? "secondary" : "ghost"} size="xs"
          onClick={() => setDensity("noc")}>NOC</Button>
      </div>

      {/* ── the one fleet table ── */}
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
        borderRadius: "var(--r3)", overflow: "hidden", marginBottom: 20 }}>
        <table className="aug-dt" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Activity 24h</th>
              <th>Runs</th>
              <th>Errors</th>
              {noc && <th>Tokens</th>}
              {noc && <th>Queries</th>}
              {noc && <th>Unmetered</th>}
              <th>Last run</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {charters.map(row => row.kind === "charter" && (
              <tr key={row.id}>
                <td style={{ fontWeight: 500 }}>{row.name}
                  <span style={{ color: "var(--t4)", fontSize: 11, marginLeft: 6 }}>{row.role}</span>
                </td>
                <td><StatusChip hue="info" strength="soft">charter</StatusChip></td>
                <td>
                  <StatusChip hue={row.enabled ? "positive" : "caution"} strength="soft">
                    {row.enabled ? "active" : "paused"}
                  </StatusChip>
                </td>
                <td>{row.spark.some(v => v > 0)
                  ? <Sparkline values={row.spark} width={84} height={16} />
                  : <span style={{ color: "var(--t4)", fontSize: 11 }}>quiet</span>}
                </td>
                <td style={{ fontVariantNumeric: "tabular-nums" }}>{formatCount(row.runs)}</td>
                <td style={{ fontVariantNumeric: "tabular-nums" }}>
                  {row.failed > 0
                    ? <span style={{ color: "var(--red4)" }}>{row.failed}</span>
                    : <span style={{ color: "var(--t4)" }}>0</span>}
                  {row.orphaned > 0 && (
                    <span style={{ color: "var(--t4)", fontSize: 11 }}
                      title="server-restart orphans — infrastructure, not agent errors">
                      {" "}+{row.orphaned} orphaned
                    </span>
                  )}
                </td>
                {noc && <td style={{ fontVariantNumeric: "tabular-nums" }}>{compactNumber(row.tokens)}</td>}
                {noc && <td style={{ fontVariantNumeric: "tabular-nums" }}>{formatCount(row.queries)}</td>}
                {noc && <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t4)" }}
                  title="finished runs that recorded no metrics — unknown spend, not zero">
                  {row.unmetered_runs}</td>}
                <td style={{ color: "var(--t3)" }}>{relTime(row.last_run_at)}</td>
                <td>
                  <Button variant="ghost" size="xs" disabled={busy === row.id}
                    onClick={() => togglePause(row)}>
                    {row.enabled ? "Pause" : "Resume"}
                  </Button>
                </td>
              </tr>
            ))}
            {personas.map(row => row.kind === "persona" && (
              <tr key={row.id}>
                <td style={{ fontWeight: 500 }}>{row.name}
                  {row.last_eval && (
                    <span style={{ color: "var(--t4)", fontSize: 11, marginLeft: 6 }}>
                      goldens {row.last_eval.passed}/{row.last_eval.total}
                    </span>
                  )}
                </td>
                <td><StatusChip hue="accent" strength="soft">persona</StatusChip></td>
                <td>
                  <StatusChip hue={row.enabled ? "positive" : "caution"} strength="soft">
                    {row.enabled ? "active" : "paused"}
                  </StatusChip>
                </td>
                <td colSpan={2}>
                  {row.spend.measured
                    ? <span style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                        {formatCount(row.spend.calls)} model calls
                      </span>
                    : <span style={{ fontSize: 11, color: "var(--t3)" }}>
                        spend not recorded — enable <code style={{ fontSize: 10 }}>{row.spend.enable_flag}</code>
                      </span>}
                </td>
                <td>
                  {row.spend.measured && row.spend.failure_rate != null && row.spend.failure_rate > 0
                    ? <span style={{ color: "var(--red4)", fontVariantNumeric: "tabular-nums" }}>
                        {pct(row.spend.failure_rate)}
                      </span>
                    : <span style={{ color: "var(--t4)" }}>—</span>}
                </td>
                {noc && <td style={{ fontVariantNumeric: "tabular-nums" }}>
                  {row.spend.measured ? compactNumber(row.spend.total_tokens) : "—"}</td>}
                {noc && <td style={{ color: "var(--t4)" }}>—</td>}
                {noc && <td style={{ color: "var(--t4)" }}>—</td>}
                <td style={{ color: "var(--t3)" }}>—</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Button variant="ghost" size="xs" disabled={busy === row.id}
                    onClick={() => togglePause(row)}>
                    {row.enabled ? "Pause" : "Resume"}
                  </Button>
                  {onOpenAgent && (
                    <Button variant="ghost" size="xs" onClick={() => onOpenAgent(row.id)}>Open</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── active jobs (the kill control) ── */}
      <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 8 }}>
        Active jobs
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
        borderRadius: "var(--r3)", overflow: "hidden" }}>
        {activeJobs.length === 0 ? (
          <div style={{ padding: 16, fontSize: 12, color: "var(--t3)" }}>
            Nothing running right now.
          </div>
        ) : (
          <table className="aug-dt" style={{ width: "100%" }}>
            <thead>
              <tr><th>Agent</th><th>Kind</th><th>State</th><th>Started</th><th></th></tr>
            </thead>
            <tbody>
              {activeJobs.map(j => (
                <tr key={j.id}>
                  <td>{j.agent?.agent || j.kind}</td>
                  <td style={{ color: "var(--t3)" }}>{j.kind}</td>
                  <td><StatusChip hue="info" strength="soft">{j.state.toLowerCase()}</StatusChip></td>
                  <td style={{ color: "var(--t3)" }}>{relTime(j.started_at || j.created_at)}</td>
                  <td>
                    <Button variant="ghost" size="xs"
                      onClick={() => cancelJob(j.id).then(load)}>Kill</Button>
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
