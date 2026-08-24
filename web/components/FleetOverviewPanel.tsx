"use client";

/**
 * Agent Ops · Overview — the operating picture.
 *
 * An operations view answers three questions IN ORDER, and this panel is that order top to
 * bottom: **what's wrong** (the status rail and the needs-you strip), **what's running**
 * (the KPI tiles and the activity chart), **what it cost** (the cost tile and the fleet
 * table). The previous Overview opened with tokens/hour and never answered the first
 * question at all.
 *
 * Four rules it exists to keep:
 *
 * **Every number is a door.** Click any tile and the drawer says what is counted, what it
 * is out of, how much of the population could have carried the fact, and opens the list
 * whose count equals it. A tile that shows 24 and opens a list of 31 teaches the reader the
 * page is decorative; the parity is a backend test.
 *
 * **One window.** The tiles, the chart, the row sparks and the jobs list all read the range
 * held by the workspace. This surface used to draw client-side minute buckets over an hour
 * beside server-side hourly buckets over a day, in the same table.
 *
 * **Runners are not agents.** The automation engine's evaluation tick was 1,291 of 1,316
 * jobs in twenty-four hours (measured 2026-08-17) and sat in the agent table as "Unassigned
 * kinds", setting the shape of every metric on the page. It has its own muted lane now,
 * never summed into the agent totals, with a toggle for anyone who wants it back.
 *
 * **Unknown is never zero.** Unmetered runs, unpriced calls, orphaned restarts and an agent
 * that is not metered at all each say so in their own words rather than rendering a 0 or a
 * dash that reads as "nothing happened".
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { ActivityChart, colorFor } from "@/components/agentops/ActivityChart";
import { ProvenanceDrawer, type Provenance } from "@/components/agentops/ProvenanceDrawer";
import { rangeLabel, rangeParams, type RangeKey, type TimeRange } from "@/components/agentops/useTimeRange";
import { Sparkline } from "@/components/brief/Sparkline";
import { StatTile } from "@/components/brief/StatTile";
import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import {
  acceptProposal, cancelJob, getFleetOverview, getJobs, getNeedsHuman, getObsTimeseries,
  patchAgent, patchUserAgent, rejectProposal,
  type FleetJob, type FleetOverview, type FleetRow, type FleetRunnerRow,
  type NeedsHumanRow, type TimeSeriesResponse,
} from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { subscribeKernelEvents } from "@/lib/events";
import { compactNumber, formatCount, pct, relTime } from "@/lib/format";

type Density = "calm" | "noc";
type JobFilter = "active" | "all" | "succeeded" | "failed";

const JOB_STATE_HUE: Record<string, "positive" | "negative" | "caution" | "info" | "muted"> = {
  RUNNING: "info", PENDING: "muted", PAUSED: "caution",
  SUCCEEDED: "positive", FAILED: "negative", CANCELLED: "caution",
  // Interrupted is not an error — the process died holding the job, and nobody observed a
  // failure. Caution, like Cancelled, rather than the negative hue.
  INTERRUPTED: "caution",
};

const JOB_FILTERS: { id: JobFilter; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "all", label: "All" },
  { id: "succeeded", label: "Succeeded" },
  { id: "failed", label: "Failed / Stopped" },
];

const SOURCE_LABEL: Record<NeedsHumanRow["source"], string> = {
  kinetic_inbox: "proposal", paused_run: "paused run", automation_approval: "automation",
  agent_alert: "alert", automation_broken: "broken automation",
};
const SOURCE_HUE: Record<NeedsHumanRow["source"], "accent" | "negative" | "caution"> = {
  kinetic_inbox: "accent", paused_run: "negative", automation_approval: "caution",
  agent_alert: "negative", automation_broken: "negative",
};

/** A live age, counted up from the moment the item started waiting. */
function waitedFor(ms: number | null, tick: number): string {
  if (ms == null) return "—";
  const s = Math.floor((ms + tick) / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${s}s`;
}

export function FleetOverviewPanel({ onOpenAgent, onOpenAttention, onOpenInvestigation, range,
  onBrush, onClearBrush }: {
  onOpenAgent?: (id: string, kind: "charter" | "persona") => void;
  onOpenAttention?: () => void;
  onOpenInvestigation?: (id: string) => void;
  range: TimeRange;
  onBrush: (since: string, until: string) => void;
  onClearBrush: () => void;
}) {
  const [data, setData] = useState<FleetOverview | null>(null);
  const [jobs, setJobs] = useState<FleetJob[]>([]);
  const [chart, setChart] = useState<TimeSeriesResponse | null>(null);
  const [attention, setAttention] = useState<NeedsHumanRow[]>([]);
  const [density, setDensity] = useState<Density>("calm");
  const [jobFilter, setJobFilter] = useState<JobFilter>("active");
  const [showRunners, setShowRunners] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [prov, setProv] = useState<Provenance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const params = useMemo(() => rangeParams(range), [range]);

  const load = useCallback(() => {
    getFleetOverview({ ...params, include_runners: showRunners })
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
    getJobs({ limit: 200 }).then(setJobs).catch(() => {});
    // `source: "jobs"` — this chart is headed "Runs by agent" and must plot the same runs
    // the Runs tile counts. Grouping model CALLS by charter draws an honest chart of a
    // different quantity, and on any history predating the attribution column every bar
    // reads "(unattributed)".
    getObsTimeseries({ source: "jobs", ...params })
      .then(setChart).catch(() => setChart(null));
    getNeedsHuman(100).then(d => setAttention(d.rows)).catch(() => {});
  }, [params, showRunners]);

  useEffect(() => {
    load();
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["job.state"] });
    const iv = setInterval(load, 15_000);   // slow fallback if the stream is down
    return () => { unsub(); clearInterval(iv); };
  }, [load]);

  // The waiting timers count up on their own — an age frozen at fetch time reads as a
  // stale page, and "how long has this been waiting" is the whole point of the strip.
  useEffect(() => {
    const iv = setInterval(() => setTick(t => t + 1000), 1000);
    return () => clearInterval(iv);
  }, []);

  const liveByKind = useMemo(() => {
    const m: Record<string, number> = {};
    for (const j of jobs) {
      if (["RUNNING", "PENDING", "PAUSED"].includes(j.state)) m[j.kind] = (m[j.kind] || 0) + 1;
    }
    return m;
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    if (jobFilter === "all") return jobs;
    if (jobFilter === "active") return jobs.filter(j => ["RUNNING", "PENDING", "PAUSED"].includes(j.state));
    if (jobFilter === "succeeded") return jobs.filter(j => j.state === "SUCCEEDED");
    // INTERRUPTED belongs here so a restart-killed job is still findable — it is terminal,
    // and without it those rows would appear under no filter but "All".
    return jobs.filter(j => ["FAILED", "CANCELLED", "INTERRUPTED"].includes(j.state));
  }, [jobs, jobFilter]);

  const togglePause = async (row: FleetRow) => {
    setBusy(row.id);
    try {
      if (row.kind === "charter") await patchAgent(row.id, { enabled: !row.enabled });
      else await patchUserAgent(row.id, { enabled: !row.enabled });
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally { setBusy(null); }
  };

  const resolveInbox = async (row: NeedsHumanRow, action: "accept" | "reject") => {
    setBusy(row.id);
    try {
      if (action === "accept") await acceptProposal(row.id, "agent-ops");
      else await rejectProposal(row.id, "agent-ops");
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally { setBusy(null); }
  };

  if (error && !data) {
    return <div className="aug-fs-sm" style={{ padding: 24, color: "var(--red4)" }}>{error}</div>;
  }
  if (!data) {
    return <div className="aug-fs-sm" style={{ padding: 24, color: "var(--t2)" }}>Loading overview…</div>;
  }

  const { tiles } = data;
  const noc = density === "noc";
  const charters = data.rows.filter(r => r.kind === "charter");
  const personas = data.rows.filter(r => r.kind === "persona");
  const runners = data.runners ?? [];
  const order = (chart?.series ?? []).map(s => s.key);
  const label = rangeLabel(range);
  const windowText = `${label}${range.since ? " (brushed)" : ""}`;

  // Which buckets the current brush covers, for the chart's highlight overlay.
  const selection: [number, number] | null = (() => {
    if (!range.since || !range.until || !chart) return null;
    const s = chart.edges.findIndex(e => Date.parse(e) >= Date.parse(range.since!));
    return s < 0 ? null : [Math.max(0, s), chart.edges.length - 1];
  })();

  const openProv = (p: Provenance) => setProv(p);

  return (
    <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column",
                  minHeight: 0, background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex",
                    flexDirection: "column", gap: 14, minHeight: 0 }}>

        {/* ── 1 · what's running, at a glance ─────────────────────────────────── */}
        <section aria-label="Agents right now">
          <SectionHead title="Agents · right now"
            sub={`${charters.filter(r => r.kind === "charter" && r.enabled).length} active · ${runners.length} background runner${runners.length === 1 ? "" : "s"}`} />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[...charters, ...personas].map(row => {
              const live = row.kind === "charter"
                ? row.job_kinds.reduce((n, k) => n + (liveByKind[k] || 0), 0) : 0;
              const state = !row.enabled ? "paused" : live > 0 ? "running" : "idle";
              return (
                <Button key={row.id} variant="ghost" size="sm"
                  onClick={() => { setExpanded(row.id); document.getElementById(`ao-row-${row.id}`)?.scrollIntoView({ block: "center" }); }}
                  title={`${row.name} — ${state}`}
                  style={{
                    display: "flex", alignItems: "center", gap: 7, height: "auto",
                    padding: "5px 10px 5px 8px", border: "1px solid var(--b2)",
                    borderRadius: "var(--r-pill)", background: "var(--bg-2)",
                    color: "var(--t1)", fontSize: 12,
                  }}>
                  <span aria-hidden style={{
                    width: 8, height: 8, borderRadius: "50%",
                    background: state === "running" ? "var(--grn4)"
                      : state === "paused" ? "var(--amb4)" : "var(--t4)",
                  }} />
                  {row.name}
                  <span className="aug-fs-xs" style={{ color: "var(--t2)", fontFamily: "var(--font-mono)" }}>
                    {state === "running" ? `${live} live` : state}
                  </span>
                </Button>
              );
            })}
          </div>
        </section>

        {/* ── 2 · what needs a human, oldest first ────────────────────────────── */}
        <section aria-label="Needs you">
          <SectionHead title="Needs you"
            action={attention.length > 0 && onOpenAttention
              ? { label: `${attention.length} waiting · open Attention →`, onClick: onOpenAttention }
              : undefined} />
          {attention.length === 0 ? (
            <Card>
              <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
                Nothing needs a human. All three sources are empty right now.
              </span>
            </Card>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
              {attention.slice(0, 3).map(row => (
                <div key={`${row.source}:${row.id}`} className="aug-anim-fade" style={{
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderLeft: `3px solid ${row.source === "paused_run" ? "var(--red4)" : "var(--amb4)"}`,
                  borderRadius: "var(--r3)", padding: "10px 12px",
                  display: "flex", flexDirection: "column", gap: 6,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                    <StatusChip hue={SOURCE_HUE[row.source]} strength="soft">
                      {SOURCE_LABEL[row.source]}
                    </StatusChip>
                    <span className="aug-fs-sm" style={{
                      fontFamily: "var(--font-mono)",
                      color: row.source === "paused_run" ? "var(--red4)" : "var(--amb4)",
                    }} title={row.since_basis === "started_at"
                      ? "since start — the pause event aged out of the journal" : undefined}>
                      {waitedFor(row.waiting_ms, tick)}
                      {row.since_basis === "started_at" && " *"}
                    </span>
        </div>
                  <div className="aug-text-ui" style={{ fontWeight: 600 }}>{row.title}</div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {row.source === "kinetic_inbox" ? (
                      <>
                        <Button size="xs" variant="ghost" disabled={busy === row.id}
                          onClick={() => resolveInbox(row, "accept")}>Accept</Button>
                        <Button size="xs" variant="ghost" disabled={busy === row.id}
                          onClick={() => resolveInbox(row, "reject")}>Reject</Button>
                      </>
                    ) : (
                      <Button size="xs" variant="ghost"
                        onClick={() => {
                          const inv = row.resolve?.investigation_id;
                          if (inv && onOpenInvestigation) onOpenInvestigation(inv);
                          else onOpenAttention?.();
                        }}>
                        {row.source === "paused_run" ? "Open & resume" : "Open automation"}
                      </Button>
                    )}
        </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── 3 · the figures, each a door ────────────────────────────────────── */}
        <section aria-label="Key figures">
          <SectionHead title={`${windowText} · ${showRunners ? "including background runners" : "agents only"}`}
            sub="click a tile to see where its number comes from" />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <StatTile label="Runs" value={formatCount(tiles.runs_started)}
              accent="var(--chart-1)" expandable onClick={() => openProv({
                eyebrow: "Where this number comes from", title: "Runs",
                value: formatCount(tiles.runs_started), window: windowText,
                definition: "Jobs created in the window whose kind belongs to an agent charter. "
                  + "Automation ticks and eval experiments are runners and are excluded unless toggled in.",
                denominator: `${formatCount(tiles.runs_started)} agent runs · ${formatCount(tiles.runner_runs)} runner runs excluded`,
                coverage: tiles.truncated
                  ? "capped — this window holds more jobs than one read returns, so the "
                    + "figure is a floor"
                  : "100% — every job carries a kind",
                open: { label: "Open the jobs list", hint: "the runs whose count equals this figure",
                        onOpen: () => { setJobFilter("all"); setProv(null); } },
                note: tiles.runner_runs > 0
                  ? `The ${formatCount(tiles.runner_runs)} runner runs are the automation engine's evaluation tick — one job per minute, no model calls. Counted apart so this figure means agent work.`
                  : undefined,
              })}
              caption={tiles.truncated
                ? `a floor — the window holds more jobs than one read returns`
                : tiles.runner_runs > 0
                  ? `+${formatCount(tiles.runner_runs)} background runs excluded`
                  : "no background runs in window"}
              title="Agent runs started in the window" />

            <StatTile label="Failures" value={formatCount(tiles.failed_runs)}
              accent="var(--chart-5)" expandable onClick={() => openProv({
                eyebrow: "Where this number comes from", title: "Failures",
                value: formatCount(tiles.failed_runs), window: windowText,
                definition: "Runs that ended FAILED for a reason the agent produced. A process "
                  + "restart that orphaned a run is infrastructure, and is counted apart.",
                denominator: tiles.error_rate == null ? "no finished runs in window"
                  : `${pct(tiles.error_rate)} of finished runs`,
                coverage: "100% — state is always recorded",
                facts: [["Orphaned restarts", formatCount(tiles.orphaned_runs)]],
                open: { label: "Open failed and stopped jobs", hint: "FAILED · CANCELLED · INTERRUPTED",
                        onOpen: () => { setJobFilter("failed"); setProv(null); } },
              })}
              caption={tiles.orphaned_runs > 0
                ? `+${tiles.orphaned_runs} orphaned restarts — infrastructure, counted apart`
                : (tiles.error_rate == null ? "no finished runs yet" : `${pct(tiles.error_rate)} of finished runs`)}
              title="Agent-produced failures" />

            <StatTile label="p50 / p95"
              value={tiles.p50_duration_ms == null ? "—"
                : `${fmtMs(tiles.p50_duration_ms)} / ${fmtMs(tiles.p95_duration_ms ?? 0)}`}
              accent="var(--chart-4)" expandable onClick={() => openProv({
                eyebrow: "Where this number comes from", title: "Run duration",
                value: tiles.p50_duration_ms == null ? "—"
                  : `${fmtMs(tiles.p50_duration_ms)} / ${fmtMs(tiles.p95_duration_ms ?? 0)}`,
                window: windowText,
                definition: "Percentiles of finished_at − started_at over agent runs. p50 is what "
                  + "a typical run takes; p95 is what a slow one takes.",
                denominator: `${formatCount(tiles.runs_started)} runs started in window`,
                note: "p50 has been computed by this endpoint since it shipped and was never "
                  + "rendered — a median tells you what is normal, which a p95 alone cannot.",
              })}
              caption="typical / slow" title="Median and 95th-percentile run duration" />

            <StatTile label="Tokens" value={compactNumber(tiles.tokens.total)}
              accent="var(--chart-3)" expandable onClick={() => openProv({
                eyebrow: "Where this number comes from", title: "Tokens",
                value: compactNumber(tiles.tokens.total), window: windowText,
                definition: "Sum of metrics.total_tokens over finished agent runs. A run whose "
                  + "backend reported no usage is UNMETERED — unknown spend, never zero.",
                denominator: `${formatCount(tiles.tokens.metered_runs)} metered runs`,
                coverage: tiles.tokens.metered_runs + tiles.tokens.unmetered_runs > 0
                  ? pct(tiles.tokens.metered_runs / (tiles.tokens.metered_runs + tiles.tokens.unmetered_runs))
                  : "no finished runs",
                facts: [["Unmetered runs", formatCount(tiles.tokens.unmetered_runs)]],
              })}
              caption={tiles.tokens.unmetered_runs > 0
                ? `${formatCount(tiles.tokens.unmetered_runs)} unmetered — unknown, not zero`
                : "all finished runs metered"}
              title="Tokens spent by agent runs" />

            <StatTile label="Cost"
              value={tiles.cost?.usd == null ? "—" : `$${tiles.cost.usd.toFixed(2)}`}
              accent="var(--chart-2)" expandable onClick={() => openProv({
                eyebrow: "Where this number comes from", title: "Cost",
                value: tiles.cost?.usd == null ? "—" : `$${tiles.cost.usd.toFixed(2)}`,
                window: windowText,
                definition: "Model calls in the window priced from the provider's own published "
                  + "catalogue — never a hardcoded rate. A model the catalogue does not price "
                  + "contributes nothing and is counted as unpriced.",
                denominator: `${formatCount(tiles.cost?.calls ?? 0)} model calls`,
                coverage: tiles.cost?.calls
                  ? pct(1 - (tiles.cost.unpriced_calls ?? 0) / tiles.cost.calls) + " priced"
                  : "no calls in window",
                note: tiles.cost && !tiles.cost.is_complete
                  ? "Incomplete: some calls ran on models nothing publishes a price for. The "
                    + "figure is a floor, not a total."
                  : undefined,
              })}
              caption={tiles.cost?.unpriced_calls
                ? `${formatCount(tiles.cost.unpriced_calls)} calls unpriced — a floor, not a total`
                : "every call priced"}
              title="Model spend in the window" />
          </div>
        </section>

        {/* ── 4 · activity on the shared axis ─────────────────────────────────── */}
        <section aria-label="Activity" style={{
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          borderRadius: "var(--r3)", padding: "12px 12px 8px",
        }}>
          <SectionHead title="Runs by agent" sub="hover a bar · click to filter · drag to brush" />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {(chart?.series ?? []).map(s => {
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
                  {s.label}
                </Button>
              );
            })}
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6,
                            marginLeft: "auto", color: "var(--t2)", fontSize: 12, cursor: "pointer" }}>
              <input type="checkbox" checked={showRunners}
                onChange={e => setShowRunners(e.target.checked)} />
              include background runners
            </label>
      </div>
          {chart ? (
            <div style={{ marginTop: 8 }}>
              <ActivityChart window={chart.window} edges={chart.edges}
                series={chart.series} runners={[]} showRunners={false}
                hidden={hidden} order={order} selection={selection}
                onBrush={onBrush} onPickBucket={onBrush} />
              <div style={{ display: "flex", justifyContent: "space-between",
                            marginTop: 4, color: "var(--t2)" }}>
                <span className="aug-fs-xs">
                  {label} · {chart.window.buckets} bins · y = runs
                </span>
                {range.since && (
                  <Button variant="ghost" size="xs" onClick={onClearBrush}
                    style={{ color: "var(--blue4)" }}>brushed — clear</Button>
                )}
              </div>
            </div>
          ) : (
            <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "10px 0 4px" }}>
              No agent runs in this window.
            </p>
          )}
        </section>

        {/* ── 5 · the fleet, in two lanes ─────────────────────────────────────── */}
        <section aria-label="All agents">
          <SectionHead title="All agents"
            sub="built-in and custom agents in one grammar · runners below, never summed in"
            action={{ label: noc ? "Calm" : "NOC", onClick: () => setDensity(noc ? "calm" : "noc") }} />
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
                        borderRadius: "var(--r3)", overflow: "hidden" }}>
        <table className="aug-dt" style={{ width: "100%" }}>
          <thead>
            <tr>
                  <th style={{ width: 22 }} />
              <th>Agent</th>
              <th>Status</th>
              <th>Live</th>
                  <th>Activity</th>
              <th>Runs</th>
                  <th>Failures</th>
              {noc && <th>Tokens</th>}
              {noc && <th>Queries</th>}
              {noc && <th>Unmetered</th>}
              <th>Last run</th>
                  <th />
            </tr>
          </thead>
          <tbody>
                <LaneHead cols={noc ? 12 : 9} title="Agents"
                  note={`${charters.length} built-in · ${personas.length} custom`} />
                {[...charters, ...personas].map(row => (
                  <AgentRow key={row.id} row={row} noc={noc} order={order}
                    live={row.kind === "charter"
                      ? row.job_kinds.reduce((n, k) => n + (liveByKind[k] || 0), 0) : 0}
                    expanded={expanded === row.id}
                    onToggle={() => setExpanded(expanded === row.id ? null : row.id)}
                    onPause={() => togglePause(row)} busy={busy === row.id}
                    onOpen={onOpenAgent} />
            ))}
                {runners.length > 0 && (
                  <>
                    <LaneHead cols={noc ? 12 : 9} title="Background runners"
                      note="counted separately — never in the agents' totals" />
                    {runners.map(r => <RunnerRow key={r.id} row={r} noc={noc} />)}
                  </>
                  )}
          </tbody>
        </table>
      </div>
        </section>

        {/* ── 6 · jobs ────────────────────────────────────────────────────────── */}
        <section aria-label="Jobs">
          <SectionHead title="Jobs" sub="the runs behind the figures above" />
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
        {JOB_FILTERS.map(f => (
              <Button key={f.id} variant="ghost" size="xs"
                onClick={() => setJobFilter(f.id)}
                aria-pressed={jobFilter === f.id}
                style={{
                  background: jobFilter === f.id ? "var(--bg-4)" : "transparent",
                  color: jobFilter === f.id ? "var(--t1)" : "var(--t2)",
                }}>{f.label}</Button>
        ))}
          </div>
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
                        borderRadius: "var(--r3)", overflow: "hidden" }}>
            {filteredJobs.length === 0 ? (
              <p className="aug-fs-sm" style={{ color: "var(--t2)", padding: "12px 14px", margin: 0 }}>
                {jobFilter === "active" ? "Nothing running right now." : "No jobs match this filter."}
              </p>
        ) : (
          <table className="aug-dt" style={{ width: "100%" }}>
            <thead>
                  <tr><th>Job</th><th>Agent</th><th>State</th><th>Started</th><th>Duration</th><th /></tr>
            </thead>
            <tbody>
                  {filteredJobs.slice(0, 60).map(j => (
                  <tr key={j.id}>
                      <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis",
                                   whiteSpace: "nowrap" }} title={j.title || j.kind}>
                        {j.title || j.kind}
                    </td>
                      <td className="aug-fs-sm" style={{ color: "var(--t2)" }}>
                        {j.agent?.agent || j.kind}
                    </td>
                    <td>
                        <StatusChip hue={JOB_STATE_HUE[j.state] ?? "muted"} strength="soft">
                          {j.state.toLowerCase()}
                        </StatusChip>
                    </td>
                      <td className="aug-fs-sm" style={{ color: "var(--t2)" }}>{relTime(j.created_at)}</td>
                      <td style={{ fontVariantNumeric: "tabular-nums" }}>
                        {j.duration_ms ? fmtMs(j.duration_ms) : "—"}
                      </td>
                    <td>
                        {["RUNNING", "PENDING", "PAUSED"].includes(j.state) && (
                        <Button variant="ghost" size="xs"
                            onClick={() => cancelJob(j.id).then(load).catch(() => {})}>Kill</Button>
                      )}
                    </td>
                  </tr>
                  ))}
            </tbody>
          </table>
        )}
          </div>
        </section>
      </div>

      <ProvenanceDrawer open={prov !== null} data={prov} onClose={() => setProv(null)} />
    </div>
  );
}

// ── small parts ──────────────────────────────────────────────────────────────────

function SectionHead({ title, sub, action }: {
  title: string; sub?: string; action?: { label: string; onClick: () => void };
}) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between",
                  gap: 12, marginBottom: 8 }}>
      <h4 className="aug-label" style={{ color: "var(--t2)", margin: 0 }}>{title}</h4>
      {sub && <span className="aug-fs-sm" style={{ color: "var(--t2)", marginRight: "auto" }}>{sub}</span>}
      {action && (
        <Button variant="ghost" size="xs" onClick={action.onClick}
          style={{ color: "var(--blue4)" }}>{action.label}</Button>
      )}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r3)", padding: "10px 12px" }}>{children}</div>
  );
}

function LaneHead({ title, note, cols }: { title: string; note: string; cols: number }) {
  return (
    <tr style={{ background: "var(--bg-1)" }}>
      <td colSpan={cols} style={{ padding: "8px 8px 4px" }}>
        <span className="aug-label" style={{ color: "var(--t2)" }}>{title}</span>
        <span className="aug-fs-sm" style={{ color: "var(--t2)", marginLeft: 10 }}>{note}</span>
      </td>
    </tr>
  );
}

/** One agent — charter or custom — in the SAME columns. What differs is the source line,
 *  which is stated rather than left to be inferred from a row half full of dashes. */
function AgentRow({ row, noc, live, expanded, onToggle, onPause, busy, onOpen, order }: {
  row: FleetRow; noc: boolean; live: number; expanded: boolean;
  onToggle: () => void; onPause: () => void; busy: boolean;
  onOpen?: (id: string, kind: "charter" | "persona") => void;
  order: string[];
}) {
  const isCharter = row.kind === "charter";
  const runs = row.runs ?? 0;
  const failed = row.failed ?? 0;
  const orphaned = isCharter ? row.orphaned ?? 0 : 0;
  const spark = row.spark ?? [];
  const tokens = row.tokens ?? 0;
  const source = isCharter ? "job metering" : "session log";

  return (
    <>
      <tr id={`ao-row-${row.id}`} onClick={onToggle} aria-expanded={expanded}
        style={{ cursor: "pointer", background: expanded ? "var(--bg-sel)" : undefined }}>
        <td aria-hidden style={{ color: "var(--t3)", fontSize: 12 }}>{expanded ? "▾" : "▸"}</td>
        <td>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span aria-hidden style={{ width: 10, height: 10, borderRadius: 2, flex: "0 0 auto",
              background: colorFor(row.id, order) }} />
            <div>
              <div style={{ fontWeight: 600 }}>{row.name}</div>
              <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                {isCharter ? row.role : `custom agent · from the ${source}`}
              </div>
            </div>
          </div>
        </td>
        <td>
          <StatusChip hue={row.enabled ? (live > 0 ? "positive" : "muted") : "caution"} strength="soft">
            {row.enabled ? (live > 0 ? "running" : "idle") : "paused"}
          </StatusChip>
        </td>
        <td style={{ fontVariantNumeric: "tabular-nums" }}>
          {live > 0 ? <span style={{ color: "var(--blue4)", fontWeight: 600 }}>{live}</span>
            : <span style={{ color: "var(--t2)" }}>0</span>}
        </td>
        <td>
          {spark.some(v => v > 0)
            ? <Sparkline values={spark} width={92} height={16} color={colorFor(row.id, order)} />
            : <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                {isCharter && row.job_kinds.length === 0 ? "not metered as jobs" : "quiet"}
              </span>}
        </td>
        <td style={{ fontVariantNumeric: "tabular-nums" }}>{formatCount(runs)}</td>
        <td style={{ fontVariantNumeric: "tabular-nums" }}>
          {failed > 0 ? <span style={{ color: "var(--red4)" }}>{failed}</span>
            : <span style={{ color: "var(--t2)" }}>0</span>}
          {orphaned > 0 && (
            <span className="aug-fs-xs" style={{ color: "var(--t2)" }}
              title="server-restart orphans — infrastructure, not agent errors">
              {" "}+{orphaned} orphaned
            </span>
          )}
        </td>
        {noc && <td style={{ fontVariantNumeric: "tabular-nums" }}>{compactNumber(tokens)}</td>}
        {noc && <td style={{ fontVariantNumeric: "tabular-nums" }}>{formatCount(row.queries ?? 0)}</td>}
        {noc && <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t2)" }}
          title="finished runs that recorded no metrics — unknown spend, not zero">
          {row.unmetered_runs ?? 0}</td>}
        <td className="aug-fs-sm" style={{ color: "var(--t2)" }}>{relTime(row.last_run_at)}</td>
        <td style={{ whiteSpace: "nowrap" }} onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="xs" disabled={busy} onClick={onPause}>
            {row.enabled ? "Pause" : "Resume"}
          </Button>
          {onOpen && (
            <Button variant="ghost" size="xs"
              onClick={() => onOpen(row.id, isCharter ? "charter" : "persona")}>Explore ›</Button>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={noc ? 12 : 9} style={{ background: "var(--bg-1)", padding: "12px 12px 14px 34px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 18 }}>
              <div>
                <h5 className="aug-label" style={{ color: "var(--t2)", margin: "0 0 6px" }}>In this window</h5>
                <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t1)" }}>
                  {formatCount(runs)} run{runs === 1 ? "" : "s"} · {failed} failed
                  {orphaned > 0 && ` · ${orphaned} orphaned`}
                </p>
                <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t2)" }}>
                  Spend measured from the {source}.
                </p>
              </div>
              <div>
                <h5 className="aug-label" style={{ color: "var(--t2)", margin: "0 0 6px" }}>Tokens</h5>
                <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t1)",
                                                  fontFamily: "var(--font-mono)" }}>
                  {compactNumber(tokens)}
                </p>
                <p className="aug-fs-xs" style={{ margin: "4px 0 0", color: "var(--t2)" }}>
                  {(row.unmetered_runs ?? 0) > 0
                    ? `${row.unmetered_runs} finished run(s) recorded no metrics — unknown, not zero.`
                    : "every finished run reported its usage."}
                </p>
              </div>
              {isCharter && (
                <div>
                  <h5 className="aug-label" style={{ color: "var(--t2)", margin: "0 0 6px" }}>Job kinds</h5>
                  <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t1)" }}>
                    {row.job_kinds.length ? row.job_kinds.join(", ")
                      : "none — this charter owns no job kind, so it can never show runs here."}
                  </p>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** A runner: shown so its volume is visible, shaped so it can never read as an agent. */
function RunnerRow({ row, noc }: { row: FleetRunnerRow; noc: boolean }) {
  return (
    <tr style={{ opacity: 0.75 }}>
      <td />
      <td>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span aria-hidden style={{
            width: 10, height: 10, borderRadius: 2, flex: "0 0 auto",
            background: "repeating-linear-gradient(135deg, var(--t3) 0 2px, transparent 2px 4px)",
          }} />
          <div>
            <div style={{ fontWeight: 600, color: "var(--t2)" }}>{row.name}</div>
            <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>{row.role}</div>
          </div>
        </div>
      </td>
      <td><StatusChip hue="muted" strength="soft">runner</StatusChip></td>
      <td style={{ color: "var(--t2)" }}>—</td>
      <td>
        {row.spark.some(v => v > 0)
          ? <Sparkline values={row.spark} width={92} height={16} color="var(--t3)" showDot={false} />
          : <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>quiet</span>}
      </td>
      <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t2)" }}>
        {formatCount(row.runs)} <span className="aug-fs-xs">ticks</span>
      </td>
      <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t2)" }}>{row.failed}</td>
      {noc && <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t2)" }}>
        {compactNumber(row.tokens)}</td>}
      {noc && <td style={{ fontVariantNumeric: "tabular-nums", color: "var(--t2)" }}>
        {formatCount(row.queries)}</td>}
      {noc && <td style={{ color: "var(--t2)" }}>{row.unmetered_runs}</td>}
      <td className="aug-fs-sm" style={{ color: "var(--t2)" }}>{relTime(row.last_run_at)}</td>
      <td />
    </tr>
  );
}
