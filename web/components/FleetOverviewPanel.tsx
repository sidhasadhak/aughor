"use client";

/**
 * Agentic Ops · Fleet — the operating picture: pulse, KPI tiles, ONE
 * kind-labelled fleet table, and THE jobs table (absorbing the old standalone
 * Fleet screen — one jobs surface, one kill control, not two).
 *
 * Honesty rules rendered, not just documented:
 * - the pulse buckets by MINUTE over the last hour (our runs are minutes-long
 *   investigations; per-second theater would be noise wearing a chart).
 * - charter spend (job metering) and persona spend (session log) are shown
 *   under their own labels; a persona whose spend isn't recorded says so and
 *   names the flag — never a confident 0.
 * - `unmetered runs` are counted beside tokens (a NULL metrics blob is not
 *   zero spend), and orphaned restarts are separated from agent errors.
 * - concurrency renders what the kernel actually has: one global cap plus an
 *   exemption set — not per-agent knobs.
 * - dollar cost deliberately absent — it lives on /usage with its own RBAC
 *   and its own `cost_is_complete` caveat.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Sparkline } from "@/components/brief/Sparkline";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  cancelJob, getFleetOverview, getJobs, patchAgent, patchUserAgent,
  type FleetJob, type FleetOverview, type FleetRow,
} from "@/lib/api";
import { evalChip } from "@/lib/agentEval";
import { costSummary, fmtMs } from "@/lib/cost";
import { subscribeKernelEvents } from "@/lib/events";
import { compactNumber, formatCount, pct, relTime } from "@/lib/format";

type Density = "calm" | "noc";
type JobFilter = "active" | "all" | "succeeded" | "failed";

const JOB_STATE_HUE: Record<string, "positive" | "negative" | "caution" | "info" | "muted"> = {
  RUNNING: "info", PENDING: "muted", PAUSED: "caution",
  SUCCEEDED: "positive", FAILED: "negative", CANCELLED: "caution",
};

const JOB_FILTERS: { id: JobFilter; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "all", label: "All" },
  { id: "succeeded", label: "Succeeded" },
  { id: "failed", label: "Failed / Cancelled" },
];

export function FleetOverviewPanel({ onOpenAgent }: {
  onOpenAgent?: (id: string, kind: "charter" | "persona") => void;
}) {
  const [data, setData] = useState<FleetOverview | null>(null);
  const [jobs, setJobs] = useState<FleetJob[]>([]);
  const [density, setDensity] = useState<Density>("calm");
  const [jobFilter, setJobFilter] = useState<JobFilter>("active");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    getFleetOverview().then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
    getJobs({ limit: 200 }).then(setJobs).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["job.state"] });
    const iv = setInterval(load, 15_000); // slow fallback if the stream is down
    return () => { unsub(); clearInterval(iv); };
  }, [load]);

  // ── the pulse: runs started per MINUTE over the last hour, from the same
  //    jobs the table shows (no second source to disagree with) ──
  const pulse = useMemo(() => {
    const buckets = new Array<number>(60).fill(0);
    const now = Date.now();
    for (const j of jobs) {
      const t = j.created_at ? Date.parse(j.created_at) : NaN;
      if (Number.isNaN(t)) continue;
      const minAgo = Math.floor((now - t) / 60_000);
      if (minAgo >= 0 && minAgo < 60) buckets[59 - minAgo] += 1;
    }
    return buckets;
  }, [jobs]);

  // Per-charter live counts: active jobs joined on the charter's job kinds.
  const liveByKind = useMemo(() => {
    const m: Record<string, number> = {};
    for (const j of jobs) {
      if (j.state === "RUNNING" || j.state === "PENDING" || j.state === "PAUSED") {
        m[j.kind] = (m[j.kind] || 0) + 1;
      }
    }
    return m;
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    if (jobFilter === "all") return jobs;
    if (jobFilter === "active") return jobs.filter(j => ["RUNNING", "PENDING", "PAUSED"].includes(j.state));
    if (jobFilter === "succeeded") return jobs.filter(j => j.state === "SUCCEEDED");
    return jobs.filter(j => j.state === "FAILED" || j.state === "CANCELLED");
  }, [jobs, jobFilter]);

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
      {/* ── fleet pulse ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 18, padding: "14px 18px",
        background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
        marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1,
            fontVariantNumeric: "tabular-nums" }}>{tiles.runs_per_min}</div>
          <div style={{ fontSize: 10.5, color: "var(--t3)", marginTop: 4 }}>
            runs/min · last {tiles.window_minutes}m
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {pulse.some(v => v > 0)
            ? <Sparkline values={pulse} width={520} height={34} />
            : <span style={{ fontSize: 11, color: "var(--t4)" }}>
                quiet hour — runs appear here as minute buckets when agents work
              </span>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 13, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
            {tiles.p95_duration_ms != null ? fmtMs(tiles.p95_duration_ms) : "—"}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--t3)" }}>p95 duration</div>
        </div>
      </div>

      {/* ── KPI tiles ── */}
      <MiniStatRow>
        <MiniStat value={tiles.active_jobs} label="Active jobs"
          tone={tiles.active_jobs > 0 ? "var(--blue4)" : "var(--t1)"} />
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
              <th>Live</th>
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
                <td style={{ fontVariantNumeric: "tabular-nums" }}>
                  {(() => {
                    const live = row.job_kinds.reduce((n, k) => n + (liveByKind[k] || 0), 0);
                    return live > 0
                      ? <span style={{ color: "var(--blue4)", fontWeight: 600 }}>{live}</span>
                      : <span style={{ color: "var(--t4)" }}>0</span>;
                  })()}
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
                <td style={{ whiteSpace: "nowrap" }}>
                  <Button variant="ghost" size="xs" disabled={busy === row.id}
                    onClick={() => togglePause(row)}>
                    {row.enabled ? "Pause" : "Resume"}
                  </Button>
                  {onOpenAgent && (
                    <Button variant="ghost" size="xs"
                      onClick={() => onOpenAgent(row.id, "charter")}>Open</Button>
                  )}
                </td>
              </tr>
            ))}
            {personas.map(row => row.kind === "persona" && (
              <tr key={row.id}>
                <td style={{ fontWeight: 500 }}>{row.name}
                  {(() => {
                    const chip = evalChip(row.last_eval, row.eval_basis);
                    return chip && (
                      <span title={chip.detail} style={{ marginLeft: 6 }}>
                        <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
                      </span>
                    );
                  })()}
                </td>
                <td><StatusChip hue="accent" strength="soft">persona</StatusChip></td>
                <td>
                  <StatusChip hue={row.enabled ? "positive" : "caution"} strength="soft">
                    {row.enabled ? "active" : "paused"}
                  </StatusChip>
                </td>
                <td style={{ color: "var(--t4)" }}>—</td>
                <td>
                  {row.spend.measured
                    ? <span style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                        {formatCount(row.spend.calls)} model calls
                      </span>
                    : <span style={{ fontSize: 11, color: "var(--t3)" }}>
                        spend not recorded — enable <code style={{ fontSize: 10 }}>{row.spend.enable_flag}</code>
                      </span>}
                </td>
                <td style={{ color: "var(--t4)" }}>—</td>
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
                    <Button variant="ghost" size="xs"
                      onClick={() => onOpenAgent(row.id, "persona")}>Open</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── THE jobs table (the kill control lives here, once) ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span className="aug-label" style={{ color: "var(--t3)" }}>Jobs</span>
        <span style={{ flex: 1 }} />
        {JOB_FILTERS.map(f => (
          <Button key={f.id} variant={jobFilter === f.id ? "secondary" : "ghost"} size="xs"
            onClick={() => setJobFilter(f.id)}>{f.label}</Button>
        ))}
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
        borderRadius: "var(--r3)", overflow: "hidden" }}>
        {filteredJobs.length === 0 ? (
          <div style={{ padding: 16, fontSize: 12, color: "var(--t3)" }}>
            {jobFilter === "active"
              ? "Nothing running right now."
              : "No jobs match this filter."}
          </div>
        ) : (
          <table className="aug-dt" style={{ width: "100%" }}>
            <thead>
              <tr><th>Agent</th><th>Task</th><th>State</th><th>Cost</th><th>When</th><th></th></tr>
            </thead>
            <tbody>
              {filteredJobs.slice(0, 60).map(j => {
                const isActive = ["RUNNING", "PENDING", "PAUSED"].includes(j.state);
                const cost = costSummary(j.cost);
                return (
                  <tr key={j.id}>
                    <td>
                      <div style={{ fontSize: 12, fontWeight: 500 }}>{j.agent?.agent || j.kind}</div>
                      <div style={{ fontSize: 10, color: "var(--t3)" }}>{j.kind}</div>
                    </td>
                    <td style={{ maxWidth: 360 }}>
                      <div style={{ fontSize: 12, color: "var(--t2)", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.title}</div>
                      {j.error && (
                        <div style={{ fontSize: 10, color: "var(--red4)", overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.error}</div>
                      )}
                    </td>
                    <td><StatusChip hue={JOB_STATE_HUE[j.state] ?? "muted"} strength="soft">
                      {j.state.toLowerCase()}</StatusChip></td>
                    <td style={{ fontSize: 11, color: cost ? "var(--t2)" : "var(--t4)" }}>{cost || "—"}</td>
                    <td style={{ fontSize: 11, color: "var(--t3)", whiteSpace: "nowrap" }}>
                      {relTime(j.started_at || j.created_at)}
                      {j.duration_ms != null ? ` · ${fmtMs(j.duration_ms)}` : ""}
                    </td>
                    <td>
                      {isActive && (
                        <Button variant="ghost" size="xs"
                          onClick={() => cancelJob(j.id).then(load)}>Kill</Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
