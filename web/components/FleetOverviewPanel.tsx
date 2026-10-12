"use client";

/**
 * Agent Ops · Overview — the operating picture, laid out to CLARITY (`aughor-v2/CLARITY.md`): four figures (runs,
 * failed, running now, model spend), then what needs a person in amber with its buttons on the row, then runs by
 * agent as a chart, then the agents and their runs as lists.
 *
 * Four rules it keeps, each from an earlier defect:
 *
 * **Every number is a door.** A figure opens "where this number comes from" — what is counted, out of what, how
 * much of the population could carry it — and the list whose count equals it.
 *
 * **One range.** The figures, the chart, the agents' sparks and the runs list read the range the workspace holds;
 * a brush on the chart narrows the same range.
 *
 * **Background runs are not agents.** The automation engine's per-minute check outnumbers agent work by about a
 * thousand to one; it is counted apart, never summed into the agents, with a switch for anyone who wants it in.
 *
 * **Unknown is never zero.** Unpriced calls, runs that reported no usage, runs a restart cut off and a built-in
 * agent with no runs of its own each say so as a chip, never as a 0 or a dash.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ActivityChart, colorFor } from "@/components/agentops/ActivityChart";
import { ProvenanceDrawer, type Provenance } from "@/components/agentops/ProvenanceDrawer";
import { RANGE_LABELS, rangeParams, type TimeRange } from "@/components/agentops/useTimeRange";
import { Sparkline } from "@/components/brief/Sparkline";
import {
  CARD, Card, Chip, Dot, Empty, Figure, Figures, MUTED, NUM, NeedsYou, ONE_LINE, ROW, RULE,
} from "@/components/clarity/parts";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { Loading, ReadFailed } from "@/components/ui/states";
import {
  BUILT_IN_AGENT_KIND, acceptProposal, cancelJob, getFleetOverview, getJobs, getNeedsHuman, getObsTimeseries,
  patchAgent, patchUserAgent, rejectProposal,
  type FleetJob, type FleetOverview, type FleetRow, type FleetRunnerRow, type NeedsHumanRow, type TimeSeriesResponse,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { compactNumber, countNoun, formatCost, formatCount, pct, relTime } from "@/lib/format";
import { needsYouTitle } from "@/lib/names";
import { runDisplayTitle } from "@/lib/runTitle";
import { useVisiblePoll } from "@/lib/useVisiblePoll";

type RunFilter = "active" | "failed" | "succeeded" | "all";

const RUN_FILTERS: { value: RunFilter; label: string; title: string }[] = [
  { value: "active", label: "Running", title: "In flight now, of any age" },
  { value: "failed", label: "Failed or stopped", title: "Failed, cancelled, or cut off by a restart, in this range" },
  { value: "succeeded", label: "Succeeded", title: "Succeeded in this range" },
  { value: "all", label: "All", title: "Every agent run in this range" },
];

const ACTIVE = ["RUNNING", "PENDING", "PAUSED"];
/** A restart-killed run is terminal; without INTERRUPTED here it would show under no filter but "All". */
const STOPPED = ["FAILED", "CANCELLED", "INTERRUPTED"];

/** The needs-a-person source a proposed action arrives from — the API's own name for it. */
const PROPOSAL_SOURCE = "kinetic_inbox";
const SOURCE_LABEL: Record<NeedsHumanRow["source"], string> = {
  [PROPOSAL_SOURCE]: "proposal", paused_run: "paused run", automation_approval: "automation",
  agent_alert: "alert", automation_broken: "broken automation",
};

/** How a run's state reads as a mark, and its colour. */
const STATE_MARK: Record<string, { word: string; color: string }> = {
  RUNNING: { word: "running", color: "var(--blue4)" }, PENDING: { word: "waiting to start", color: "var(--t3)" },
  PAUSED: { word: "paused", color: "var(--amb4)" }, SUCCEEDED: { word: "succeeded", color: "var(--grn4)" },
  FAILED: { word: "failed", color: "var(--red4)" }, CANCELLED: { word: "cancelled", color: "var(--amb4)" },
  // Not an error: the process died holding the run, and nobody observed a failure.
  INTERRUPTED: { word: "cut off by a restart", color: "var(--amb4)" },
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

/** A run's length as a person reads it: "820 ms", "3.2 s", "10 min", "1 h 5 min". */
export function duration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h${min % 60 ? ` ${min % 60} min` : ""}`;
}

/** "per hour", "per 6 hours", "per day" — what one bar of the chart holds. */
function perBucket(seconds: number): string {
  if (seconds % 86_400 === 0) return seconds === 86_400 ? "per day" : `per ${seconds / 86_400} days`;
  if (seconds % 3600 === 0) return seconds === 3600 ? "per hour" : `per ${seconds / 3600} hours`;
  if (seconds % 60 === 0) return seconds === 60 ? "per minute" : `per ${seconds / 60} minutes`;
  return `per ${seconds} s`;
}

/** Runs that are the same work ending the same way, folded into one row with a count (CLARITY: say a thing once). */
export interface RunGroup { key: string; title: string; agent: string; state: string; runs: FleetJob[] }

export function foldRuns(runs: FleetJob[]): RunGroup[] {
  const groups = new Map<string, RunGroup>();
  for (const j of runs) {
    const title = runDisplayTitle(j.title || j.kind).title;
    const agent = j.agent?.agent || j.kind;
    const key = `${agent}\u0000${title}\u0000${j.state}`;
    const g = groups.get(key) ?? { key, title, agent, state: j.state, runs: [] };
    g.runs.push(j);
    groups.set(key, g);
  }
  return [...groups.values()];
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
  const [active, setActive] = useState<FleetJob[]>([]);
  const [chart, setChart] = useState<TimeSeriesResponse | null>(null);
  const [attention, setAttention] = useState<NeedsHumanRow[]>([]);
  const [runFilter, setRunFilter] = useState<RunFilter>("active");
  const [showRunners, setShowRunners] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [prov, setProv] = useState<Provenance | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A pause, an accept or a reject the server refused — said on the page, never swallowed.
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const runsRef = useRef<HTMLElement | null>(null);

  const params = useMemo(() => rangeParams(range), [range]);

  // A chart, a list or "needs you" whose read REJECTED says so with a Retry; each used to fall through to its
  // empty state, which is the one thing a failed read must never say.
  const [chartError, setChartError] = useState<string | null>(null);
  const [activeError, setActiveError] = useState<string | null>(null);
  const [attentionError, setAttentionError] = useState<string | null>(null);
  const load = useCallback(() => {
    getFleetOverview({ ...params, include_runners: showRunners })
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(String(e?.message || e)));
    // In flight now, of ANY age and any kind: the newest page of runs is almost all background checks, so
    // reading it and filtering here missed an agent run that had been going longer than a few minutes.
    getJobs({ state: "active", limit: 200 })
      .then(j => { setActive(j); setActiveError(null); })
      .catch(e => setActiveError(String(e?.message || e)));
    // `source: "jobs"` — the chart plots the same runs the Runs figure counts.
    getObsTimeseries({ source: "jobs", ...params })
      .then(c => { setChart(c); setChartError(null); })
      .catch(e => { setChart(null); setChartError(String(e?.message || e)); });
    getNeedsHuman(100)
      .then(d => { setAttention(d.rows); setAttentionError(null); })
      .catch(e => setAttentionError(String(e?.message || e)));
  }, [params, showRunners]);

  // Only while this layer is on screen; shown again, it refreshes at once.
  const visible = useVisiblePoll(load, 15_000);   // slow fallback if the stream is down
  const visibleRef = useRef(visible);
  useEffect(() => { visibleRef.current = visible; }, [visible]);
  useEffect(() => {
    load();
    const unsub = subscribeKernelEvents(() => { if (visibleRef.current) load(); }, { kinds: ["job.state"] });
    return () => { unsub(); };
  }, [load]);

  // The waiting timers count up on their own — an age frozen at fetch time reads as a stale page.
  useVisiblePoll(useCallback(() => setTick(t => t + 1000), []), 1000);

  // The kinds of work each built-in agent owns: the runs list reads THOSE, in the range, one kind at a time —
  // a single read of the newest runs is all background checks and would hold none of the runs the figures count.
  const agentKinds = useMemo(() => [...new Set((data?.rows ?? [])
    .flatMap(r => (r.kind === BUILT_IN_AGENT_KIND ? r.job_kinds : [])))].sort(), [data]);
  const runnerKinds = useMemo(() => [...new Set((data?.runners ?? []).flatMap(r => r.job_kinds))].sort(), [data]);
  const [ranged, setRanged] = useState<{ runs: FleetJob[]; capped: string[] } | null>(null);
  const [rangedError, setRangedError] = useState<string | null>(null);
  const kindsKey = [...agentKinds, ...(showRunners ? runnerKinds : [])].join(",");
  const loadRanged = useCallback(() => {
    if (runFilter === "active" || !kindsKey) return;
    const kinds = kindsKey.split(",");
    Promise.all(kinds.map(kind => getJobs({ kind, ...params, limit: 200 }).then(rows => ({ kind, rows }))))
      .then(parts => {
        const runs = parts.flatMap(p => p.rows).sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
        setRanged({ runs, capped: parts.filter(p => p.rows.length >= 200).map(p => p.kind) });
        setRangedError(null);
      })
      .catch(e => setRangedError(String(e?.message || e)));
  }, [runFilter, kindsKey, params]);
  useEffect(() => { loadRanged(); }, [loadRanged]);
  // Read only while a range's runs are on screen, and more slowly than the figures: one read per kind of work.
  useVisiblePoll(loadRanged, 30_000);

  const liveByKind = useMemo(() => {
    const m: Record<string, number> = {};
    for (const j of active) if (ACTIVE.includes(j.state)) m[j.kind] = (m[j.kind] || 0) + 1;
    return m;
  }, [active]);

  const togglePause = async (row: FleetRow) => {
    setBusy(row.id);
    setActionError(null);
    try {
      if (row.kind === BUILT_IN_AGENT_KIND) await patchAgent(row.id, { enabled: !row.enabled });
      else await patchUserAgent(row.id, { enabled: !row.enabled });
      load();
    } catch (e) {
      setActionError(String((e as Error)?.message || e));
    } finally { setBusy(null); }
  };

  const resolveProposal = async (row: NeedsHumanRow, action: "accept" | "reject") => {
    setBusy(row.id);
    setActionError(null);
    try {
      if (action === "accept") await acceptProposal(row.id, "agent-ops");
      else await rejectProposal(row.id, "agent-ops");
      load();
    } catch (e) {
      setActionError(String((e as Error)?.message || e));
    } finally { setBusy(null); }
  };

  if (error && !data) {
    return <ReadFailed what="the overview" error={error} onRetry={load} style={{ padding: 24 }} />;
  }
  if (!data) {
    return <Loading what="the overview" style={{ padding: 24 }} />;
  }

  const { tiles } = data;
  const builtIn = data.rows.filter(r => r.kind === BUILT_IN_AGENT_KIND);
  const custom = data.rows.filter(r => r.kind !== BUILT_IN_AGENT_KIND);
  const runners = data.runners ?? [];
  const order = (chart?.series ?? []).map(s => s.key);
  const rangeWords = range.since ? "the brushed range" : RANGE_LABELS[range.key].toLowerCase();
  const liveOf = (row: FleetRow) => (row.kind === BUILT_IN_AGENT_KIND
    ? row.job_kinds.reduce((n, k) => n + (liveByKind[k] || 0), 0) : 0);
  const runningNow = builtIn.reduce((n, r) => n + liveOf(r), 0);
  const on = data.rows.filter(r => r.enabled).length;
  const paused = data.rows.length - on;
  const calls = tiles.cost?.calls ?? 0;
  const unpriced = tiles.cost?.unpriced_calls ?? 0;
  const pricedShare = calls ? 1 - unpriced / calls : null;
  const unmetered = tiles.tokens.unmetered_runs;

  // Which buckets the current brush covers, for the chart's highlight overlay.
  const selection: [number, number] | null = (() => {
    if (!range.since || !range.until || !chart) return null;
    const s = chart.edges.findIndex(e => Date.parse(e) >= Date.parse(range.since!));
    return s < 0 ? null : [Math.max(0, s), chart.edges.length - 1];
  })();

  const openRuns = (filter: RunFilter) => {
    setRunFilter(filter);
    setProv(null);
    runsRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  };

  return (
    <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", minHeight: 0,
      background: "var(--bg-0)" }}>
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        <div data-testid="ao-overview" style={{ display: "flex", flexDirection: "column", gap: 14,
          padding: "16px 22px 28px", maxWidth: 1180 }}>

          {/* ── the figures, each a door ──────────────────────────────────────────── */}
          <Figures testId="ao-figures">
            <Figure testId="ao-fig-runs" label={showRunners ? "Runs · with background" : "Runs"}
              value={formatCount(tiles.runs_started)}
              title={`Agent runs started in ${rangeWords} — open for where this number comes from`}
              sub={<>
                {tiles.truncated && <Chip tone="amber" title="This range holds more runs than one read returns">a floor</Chip>}
                <span>{tiles.p50_duration_ms == null ? "none finished yet"
                  : `typical ${duration(tiles.p50_duration_ms)} · slow ${duration(tiles.p95_duration_ms)}`}</span>
              </>}
              onOpen={() => setProv({
                eyebrow: "Where this number comes from", title: "Runs", value: formatCount(tiles.runs_started),
                window: rangeWords,
                definition: "Runs started in this range by the kinds of work the built-in agents own. The automation "
                  + "engine's per-minute check is background work: it is counted apart unless it is switched in.",
                denominator: `${formatCount(tiles.runs_started)} agent runs · ${formatCount(tiles.runner_runs)} background runs counted apart`,
                coverage: tiles.truncated ? "a floor — this range holds more runs than one read returns"
                  : "every run carries its kind",
                facts: [["Typical run", duration(tiles.p50_duration_ms)], ["Slow run (95th percentile)", duration(tiles.p95_duration_ms)]],
                open: { label: "Open these runs", hint: "every agent run in this range, in the list below",
                        onOpen: () => openRuns("all") },
              })} />

            <Figure testId="ao-fig-failed" label="Failed" value={formatCount(tiles.failed_runs)}
              tone={tiles.failed_runs > 0 ? "red" : undefined}
              title="Runs that failed for a reason the agent produced — open for where this number comes from"
              sub={<>
                <span>{tiles.error_rate == null ? "nothing finished yet" : `${pct(tiles.error_rate)} of finished runs`}</span>
                {tiles.orphaned_runs > 0 && (
                  <Chip tone="amber" title="A server restart cut these runs off — infrastructure, counted apart">
                    +{formatCount(tiles.orphaned_runs)} cut off by a restart
                  </Chip>
                )}
              </>}
              onOpen={() => setProv({
                eyebrow: "Where this number comes from", title: "Failed", value: formatCount(tiles.failed_runs),
                window: rangeWords,
                definition: "Runs that ended failed for a reason the agent produced. A run a server restart cut off "
                  + "is infrastructure, and is counted apart.",
                denominator: tiles.error_rate == null ? "no finished runs in this range" : `${pct(tiles.error_rate)} of finished runs`,
                coverage: "every run records how it ended",
                facts: [["Cut off by a restart", formatCount(tiles.orphaned_runs)]],
                open: { label: "Open failed and stopped runs", hint: "failed · cancelled · cut off by a restart",
                        onOpen: () => openRuns("failed") },
              })} />

            <Figure testId="ao-fig-live" label="Running now" value={formatCount(runningNow)}
              title="Agent runs in flight now, of any age — open for where this number comes from"
              sub={<span>{`${on} of ${countNoun(data.rows.length, "agent")} on`}{paused ? ` · ${paused} paused` : ""}</span>}
              onOpen={() => setProv({
                eyebrow: "Where this number comes from", title: "Running now", value: formatCount(runningNow),
                definition: "Runs of a built-in agent's kinds that are running, waiting to start or paused right now — "
                  + "of any age: a run started yesterday and still going counts.",
                denominator: `${formatCount(tiles.active_jobs)} runs in flight of every kind, background checks included`,
                facts: [["Agents on", `${on} of ${data.rows.length}`], ["Paused", formatCount(paused)]],
                open: { label: "Open what is running", hint: "with a Kill on each", onOpen: () => openRuns("active") },
              })} />

            <Figure testId="ao-fig-spend" label={tiles.cost && !tiles.cost.is_complete ? "Model spend · at least" : "Model spend"}
              value={formatCost(tiles.cost?.usd, tiles.cost?.calls, tiles.cost?.unpriced_calls)}
              title="What the model calls in this range cost — open for where this number comes from"
              sub={<>
                {unpriced > 0 && (
                  <Chip tone="amber" testId="ao-unpriced"
                    title={`${formatCount(unpriced)} of ${formatCount(calls)} calls ran on models nothing publishes a price for — a floor, not a total`}>
                    {pct(pricedShare)} of calls priced
                  </Chip>
                )}
                <span>{compactNumber(tiles.tokens.total)} tokens</span>
                {unmetered > 0 && (
                  <Chip tone="amber" title="Finished runs that reported no usage — unknown, not zero">
                    {formatCount(unmetered)} unmetered
                  </Chip>
                )}
              </>}
              onOpen={() => setProv({
                eyebrow: "Where this number comes from", title: "Model spend",
                value: formatCost(tiles.cost?.usd, tiles.cost?.calls, tiles.cost?.unpriced_calls), window: rangeWords,
                definition: "Model calls in this range, priced from each provider's published price list — never a "
                  + "rate written into the code. A model nothing publishes a price for adds nothing and is counted as unpriced.",
                denominator: `${formatCount(calls)} model calls`,
                coverage: calls ? `${pct(pricedShare)} priced` : "no calls in this range",
                facts: [
                  ["Tokens", `${compactNumber(tiles.tokens.total)} from ${countNoun(tiles.tokens.metered_runs, "run")} that reported usage`],
                  ["Runs that reported no usage", `${formatCount(unmetered)} — unknown, not zero`],
                ],
                note: tiles.cost && !tiles.cost.is_complete
                  ? "A floor, not a total: some calls ran on models nothing publishes a price for." : undefined,
              })} />
          </Figures>

          {error && <ReadFailed what="the overview again — the figures below are from the last read" error={error} onRetry={load} />}
          {actionError && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>Not done — {actionError}</div>}

          {/* ── what needs a person, oldest first ─────────────────────────────────── */}
          <NeedsYou testId="ao-needs" waiting={attention.length > 0 || attentionError !== null} right={attention.length > 0 && (
            <>
              <span style={NUM}>{countNoun(attention.length, "item")} waiting</span>
              {onOpenAttention && <Button variant="link" size="xs" onClick={onOpenAttention}>Open Attention</Button>}
            </>
          )}>
            {attentionError ? (
              <ReadFailed what="what needs a person" error={attentionError} onRetry={load} />
            ) : attention.length === 0 ? (
              <Empty title="Proposals, paused runs, automation approvals, agent alerts and broken automations — every source was read">
                Nothing waits on a person.
              </Empty>
            ) : (
              <div>
                {attention.slice(0, 3).map((row, i) => {
                  const t = needsYouTitle(row.title);
                  const decides = row.source === PROPOSAL_SOURCE
                    || (row.source === "automation_approval" && !!row.resolve?.proposal_id);
                  return (
                    <div key={`${row.source}:${row.id}`} style={{ display: "grid", alignItems: "center", gap: 12,
                      gridTemplateColumns: "minmax(0, 1fr) auto auto", padding: "8px 0", ...(i ? RULE : {}) }}>
                      <div style={{ minWidth: 0 }} title={row.title}>
                        <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>
                          {t.subject ?? t.body}
                        </div>
                        <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t2)" }}>
                          {SOURCE_LABEL[row.source]}{t.subject && t.body ? ` · ${t.body}` : ""}
                        </div>
                      </div>
                      <span className="aug-fs-sm" style={{ ...NUM, color: row.source === "paused_run" ? "var(--red4)" : "var(--amb4)" }}
                        title={row.since_basis === "started_at"
                          ? "waiting since the run started — the pause itself aged out of the journal" : "waiting for"}>
                        {waitedFor(row.waiting_ms, tick)}{row.since_basis === "started_at" && " *"}
                      </span>
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        {decides ? (
                          <>
                            <Button size="xs" variant="secondary" disabled={busy === row.id}
                              onClick={() => resolveProposal(row, "accept")}>Accept</Button>
                            <Button size="xs" variant="ghost" disabled={busy === row.id}
                              onClick={() => resolveProposal(row, "reject")}>Reject</Button>
                          </>
                        ) : (
                          <Button size="xs" variant="secondary"
                            onClick={() => {
                              const run = row.resolve?.investigation_id;
                              if (run && onOpenInvestigation) onOpenInvestigation(run);
                              else onOpenAttention?.();
                            }}>
                            {row.source === "paused_run" ? "Open & resume" : "Open automation"}
                          </Button>
                        )}
                      </span>
                    </div>
                  );
                })}
                {attention.length > 3 && (
                  <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 6, ...RULE }}>
                    +{attention.length - 3} more in Attention
                  </div>
                )}
              </div>
            )}
          </NeedsYou>

          {/* ── the picture: runs by agent on the shared axis ──────────────────────── */}
          <Card label="Runs by agent" testId="ao-chart"
            right={chart ? `${rangeWords} · ${perBucket(chart.window.bucket_seconds)}` : rangeWords}>
            <div style={{ ...ROW, marginBottom: 6 }}>
              {/* A legend only when there are two series or more; each swatch also hides its series. */}
              {(chart?.series.length ?? 0) > 1 && chart!.series.map(s => {
                const off = hidden.has(s.key);
                return (
                  <Button key={s.key} variant="ghost" size="xs" aria-pressed={!off}
                    title={off ? `Show ${s.label}` : `Hide ${s.label}`}
                    onClick={() => setHidden(prev => {
                      const next = new Set(prev);
                      if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
                      return next;
                    })}
                    style={{ height: "auto", padding: "1px 6px", margin: 0, color: "var(--t2)", opacity: off ? 0.45 : 1,
                      textDecoration: off ? "line-through" : "none" }}>
                    <i aria-hidden style={{ width: 8, height: 8, borderRadius: 2, background: colorFor(s.key, order) }} />
                    {s.label}
                  </Button>
                );
              })}
              <label className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: "auto",
                color: "var(--t2)", cursor: "pointer" }}
                title="The automation engine's per-minute check — background work, not an agent's. Counted apart unless switched in.">
                <Checkbox checked={showRunners} onChange={e => setShowRunners(e.target.checked)} />
                <span style={NUM}>include {formatCount(tiles.runner_runs)} background runs</span>
              </label>
            </div>
            {chartError ? (
              <ReadFailed what="the run chart" error={chartError} onRetry={load} />
            ) : chart === null ? (
              <Loading what="the run chart" />
            ) : chart.series.every(s => !s.total) ? (
              <Empty>No agent runs in this range.</Empty>
            ) : (
              <ActivityChart window={chart.window} edges={chart.edges}
                series={chart.series} runners={[]} showRunners={false}
                hidden={hidden} order={order} selection={selection}
                onBrush={onBrush} onPickBucket={onBrush} />
            )}
            {range.since && (
              <div style={{ ...ROW, justifyContent: "flex-end", marginTop: 4 }}>
                <Button variant="link" size="xs" onClick={onClearBrush}>Clear the brushed range</Button>
              </div>
            )}
          </Card>

          {/* ── the agents, built-in and custom in one list; background work below, never summed in ─────── */}
          <Card label="Agents" testId="ao-agents"
            right={`${builtIn.length} built-in · ${custom.length} custom`}>
            {[...builtIn, ...custom].map((row, i) => (
              <AgentRow key={row.id} row={row} first={i === 0} live={liveOf(row)} order={order}
                expanded={expanded === row.id}
                onToggle={() => setExpanded(expanded === row.id ? null : row.id)}
                onPause={() => togglePause(row)} busy={busy === row.id} onOpen={onOpenAgent} />
            ))}
            {runners.map(r => <RunnerRow key={r.id} row={r} />)}
          </Card>

          {/* ── the runs behind the figures ───────────────────────────────────────── */}
          <section ref={runsRef} aria-label="Runs" data-testid="ao-runs" style={CARD}>
            <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
              color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
              Runs
              <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>
                <Segmented label="Which runs" value={runFilter} onChange={setRunFilter}
                  options={RUN_FILTERS.map(f => ({ value: f.value, label: f.label, title: f.title }))} />
              </span>
            </div>
            {runFilter === "active" ? (
              <ActiveRuns runs={active} error={activeError} onRetry={load} onKill={id => cancelJob(id).then(load).catch(() => {})} />
            ) : (
              <RangedRuns filter={runFilter} ranged={ranged} error={rangedError} onRetry={loadRanged}
                rangeWords={rangeWords} />
            )}
          </section>
        </div>
      </div>

      <ProvenanceDrawer open={prov !== null} data={prov} onClose={() => setProv(null)} />
    </div>
  );
}

// ── the agents list ─────────────────────────────────────────────────────────────────────

/** One agent — built-in or custom — as one row: name and state, one muted line, its spark, its runs and its two
 *  buttons. The rest (tokens, queries, where its spend is measured, its kinds of work) is behind the name. */
function AgentRow({ row, first, live, expanded, onToggle, onPause, busy, onOpen, order }: {
  row: FleetRow; first: boolean; live: number; expanded: boolean;
  onToggle: () => void; onPause: () => void; busy: boolean;
  onOpen?: (id: string, kind: "charter" | "persona") => void;
  order: string[];
}) {
  const isBuiltIn = row.kind === BUILT_IN_AGENT_KIND;
  const role = row.kind === BUILT_IN_AGENT_KIND ? row.role : "custom agent";
  const kinds = row.kind === BUILT_IN_AGENT_KIND ? row.job_kinds : null;
  const runs = row.runs ?? 0;
  const failed = row.failed ?? 0;
  const orphaned = isBuiltIn ? row.orphaned ?? 0 : 0;
  const spark = row.spark ?? [];
  const tokens = row.tokens ?? 0;
  const unmetered = row.unmetered_runs ?? 0;
  const noKinds = kinds !== null && kinds.length === 0;
  const source = isBuiltIn ? "the run records" : "the session log";
  // Colour follows the entity: an agent with a series in the chart wears that series' colour; one with none wears
  // the de-emphasis grey rather than whatever slot comes next (that was amber — the colour that means "needs you").
  const hue = order.includes(row.id) ? colorFor(row.id, order) : "var(--chart-deemph)";

  return (
    <div id={`ao-row-${row.id}`} data-testid="ao-agent-row" style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", alignItems: "center", gap: 12,
        gridTemplateColumns: "minmax(0, 1fr) 96px 84px 56px auto" }}>
        <div style={{ minWidth: 0 }}>
          <Button variant="ghost" size="xs" aria-expanded={expanded} onClick={onToggle}
            title={expanded ? "Hide the details" : "Details"}
            style={{ height: "auto", padding: 0, margin: 0, gap: 7, color: "var(--t1)", fontWeight: 600, maxWidth: "100%" }}>
            <span aria-hidden style={{ width: 9, height: 9, borderRadius: 2, flex: "0 0 auto",
              background: hue }} />
            <span className="aug-fs-chrome" style={ONE_LINE}>{row.name}</span>
            <Icon name={expanded ? "chevu" : "chevd"} size={12} />
          </Button>
          <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)", marginTop: 2 }}>
            {!row.enabled ? <Chip tone="amber">paused</Chip>
              : live > 0 ? <Chip tone="accent"><Dot color="var(--blue4)" />{live} running</Chip> : null}
            <span style={ONE_LINE}>{role}</span>
            {tokens > 0 && <span style={NUM}>· {compactNumber(tokens)} tokens</span>}
            {failed > 0 && <span style={{ ...NUM, color: "var(--red4)" }}>· {formatCount(failed)} failed</span>}
            {orphaned > 0 && <Chip tone="amber" title="A server restart cut these off — infrastructure, not the agent">+{orphaned} cut off</Chip>}
            {unmetered > 0 && <Chip tone="amber" title="Finished runs that reported no usage — unknown, not zero">{unmetered} unmetered</Chip>}
            {noKinds && <Chip title="This agent owns no kind of run, so it never shows runs here">not counted as runs</Chip>}
          </div>
        </div>
        <span>{spark.some(v => v > 0) && <Sparkline values={spark} width={92} height={16} color={hue} />}</span>
        <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right", color: runs ? "var(--t1)" : "var(--t3)" }}>
          {noKinds ? "—" : <><b style={{ fontWeight: 600 }}>{formatCount(runs)}</b> {runs === 1 ? "run" : "runs"}</>}
        </span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, textAlign: "right" }}
          title={row.last_run_at ? `last run ${row.last_run_at.replace("T", " ").slice(0, 16)}` : "no run yet"}>
          {row.last_run_at ? `${relTime(row.last_run_at)} ago` : "—"}
        </span>
        <span style={{ display: "inline-flex", gap: 4, justifyContent: "flex-end" }}>
          <Button variant="ghost" size="xs" disabled={busy} onClick={onPause}>{row.enabled ? "Pause" : "Resume"}</Button>
          {onOpen && <Button variant="ghost" size="xs" onClick={() => onOpen(row.id, isBuiltIn ? "charter" : row.kind)}>Open</Button>}
        </span>
      </div>
      {expanded && (
        <div className="aug-fs-xs" style={{ ...ROW, gap: 6, marginTop: 8, paddingLeft: 16, color: "var(--t2)" }}>
          <Chip>{countNoun(runs, "run")} · {formatCount(failed)} failed{orphaned ? ` · ${orphaned} cut off` : ""}</Chip>
          <Chip>{compactNumber(tokens)} tokens</Chip>
          <Chip>{countNoun(row.queries ?? 0, "query", "queries")}</Chip>
          <Chip tone={unmetered ? "amber" : "plain"}>
            {unmetered ? `${unmetered} reported no usage — unknown, not zero` : "every finished run reported its usage"}
          </Chip>
          {row.avg_duration_ms != null && <Chip>about {duration(row.avg_duration_ms)} a run</Chip>}
          <Chip>spend measured from {source}</Chip>
          {kinds !== null && (
            <Chip title="The kinds of run this agent owns">
              {kinds.length ? kinds.join(", ") : "owns no kind of run"}
            </Chip>
          )}
        </div>
      )}
    </div>
  );
}

/** Background work: shown so its volume is visible, shaped so it can never read as an agent. */
function RunnerRow({ row }: { row: FleetRunnerRow }) {
  return (
    <div data-testid="ao-runner-row" style={{ display: "grid", alignItems: "center", gap: 12, padding: "8px 0",
      gridTemplateColumns: "minmax(0, 1fr) 96px 84px 56px auto", opacity: 0.8, ...RULE }} title={row.role}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span aria-hidden style={{ width: 9, height: 9, borderRadius: 2, flex: "0 0 auto",
            background: "repeating-linear-gradient(135deg, var(--t3) 0 2px, transparent 2px 4px)" }} />
          <span className="aug-fs-chrome" style={{ color: "var(--t2)", fontWeight: 600 }}>{row.name}</span>
        </div>
        <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 2 }}>background · never in the agents&apos; totals</div>
      </div>
      <span>{row.spark.some(v => v > 0) && <Sparkline values={row.spark} width={92} height={16} color="var(--t3)" showDot={false} />}</span>
      <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right", color: "var(--t2)", whiteSpace: "nowrap" }}>
        {compactNumber(row.runs)} <span className="aug-fs-xs">checks</span>
      </span>
      <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, textAlign: "right" }}>
        {row.last_run_at ? `${relTime(row.last_run_at)} ago` : "—"}
      </span>
      <span className="aug-fs-xs" style={{ ...NUM, textAlign: "right", color: row.failed ? "var(--red4)" : "var(--t3)" }}>
        {row.failed ? `${formatCount(row.failed)} failed` : ""}
      </span>
    </div>
  );
}

// ── the runs list ───────────────────────────────────────────────────────────────────────

function StateMark({ state }: { state: string }) {
  const m = STATE_MARK[state] ?? { word: state.toLowerCase(), color: "var(--t3)" };
  return (
    <span className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center", gap: 5, color: m.color }}>
      <Dot color={m.color} />{m.word}
    </span>
  );
}

/** What is in flight, one row each — every one can be killed. */
function ActiveRuns({ runs, error, onRetry, onKill }: {
  runs: FleetJob[]; error: string | null; onRetry: () => void; onKill: (id: string) => void;
}) {
  if (error !== null) return <ReadFailed what="what is running" error={error} onRetry={onRetry} />;
  const live = runs.filter(j => ACTIVE.includes(j.state));
  if (live.length === 0) return <Empty>Nothing running right now.</Empty>;
  return (
    <div>
      {live.slice(0, 60).map((j, i) => (
        <div key={j.id} style={{ display: "grid", alignItems: "center", gap: 12, padding: "7px 0",
          gridTemplateColumns: "minmax(0, 1fr) auto auto", ...(i ? RULE : {}) }}>
          <div style={{ minWidth: 0 }}>
            <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }} title={j.title || j.kind}>
              {runDisplayTitle(j.title || j.kind).title}
            </div>
            <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)" }}>
              <StateMark state={j.state} /><span>· {j.agent?.agent || j.kind} · started {relTime(j.created_at)} ago</span>
            </div>
          </div>
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{j.duration_ms ? duration(j.duration_ms) : ""}</span>
          <Button variant="ghost" size="xs" onClick={() => onKill(j.id)}>Kill</Button>
        </div>
      ))}
      {live.length > 60 && <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 6, ...RULE }}>+{live.length - 60} more running</div>}
    </div>
  );
}

/** The range's runs, the same work ending the same way folded into one row with its count. */
function RangedRuns({ filter, ranged, error, onRetry, rangeWords }: {
  filter: Exclude<RunFilter, "active">; ranged: { runs: FleetJob[]; capped: string[] } | null;
  error: string | null; onRetry: () => void; rangeWords: string;
}) {
  if (error !== null) return <ReadFailed what="the runs" error={error} onRetry={onRetry} />;
  if (ranged === null) return <Loading what="the runs" />;
  const runs = ranged.runs.filter(j => (filter === "all" ? true
    : filter === "succeeded" ? j.state === "SUCCEEDED" : STOPPED.includes(j.state)));
  const groups = foldRuns(runs);
  return (
    <div data-testid="ao-runs-list">
      {ranged.capped.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <Chip tone="amber" title={`More than 200 runs of ${ranged.capped.join(", ")} in ${rangeWords}: the newest 200 of each are listed`}>
            a floor · the newest 200 of {ranged.capped.join(", ")}
          </Chip>
        </div>
      )}
      {groups.length === 0 ? (
        <Empty>{filter === "failed" ? `No failed or stopped runs in ${rangeWords}.`
          : filter === "succeeded" ? `No succeeded runs in ${rangeWords}.` : `No agent runs in ${rangeWords}.`}</Empty>
      ) : groups.slice(0, 40).map((g, i) => {
        const latest = g.runs[0];
        const timed = g.runs.map(j => j.duration_ms).filter((ms): ms is number => ms != null).sort((a, b) => a - b);
        const typical = timed.length ? timed[Math.floor(timed.length / 2)] : null;
        const errors = [...new Set(g.runs.map(j => j.error).filter(Boolean))];
        return (
          <div key={g.key} data-testid="ao-run-group" style={{ display: "grid", alignItems: "center", gap: 12, padding: "7px 0",
            gridTemplateColumns: "minmax(0, 1fr) auto", ...(i ? RULE : {}) }}>
            <div style={{ minWidth: 0 }} title={errors.length ? errors.join("\n") : g.title}>
              <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>{g.title}</div>
              <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)" }}>
                <StateMark state={g.state} />
                <span>· {g.agent} · latest {relTime(latest.created_at)} ago{typical != null ? ` · typical ${duration(typical)}` : ""}</span>
              </div>
            </div>
            <span className="aug-fs-chrome" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>
              {g.runs.length > 1 ? `×${formatCount(g.runs.length)}` : ""}
            </span>
          </div>
        );
      })}
      {groups.length > 40 && (
        <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 6, ...RULE }}>+{groups.length - 40} more kinds of run</div>
      )}
    </div>
  );
}
