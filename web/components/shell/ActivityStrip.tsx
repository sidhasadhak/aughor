"use client";

/**
 * The topbar's LIVE activity strip (INSTRUMENT.md §6) — the only always-on motion in the app,
 * so the warehouse is visibly thinking from every screen.
 *
 * Ticks: the query the Agent Ops "Runs by agent" chart draws (`/obs/timeseries`, source `jobs`,
 * the last 24 hours in hourly buckets), so the strip is that chart in miniature. A tick's height
 * is the bucket's agent runs; its hue is the series colour of the agent that ran most in it —
 * the colour `colorFor` gives that agent on Agent Ops — and older ticks fade.
 *
 * Status: agent jobs in flight right now, with the automation engine's Worker jobs excluded as
 * the chart excludes them, and "exploring" while the explorer runs on the selected connection.
 * No coverage figure: no endpoint serves the explorer's frontier, and a number the platform
 * cannot compute is not printed.
 *
 * Refresh rides the shared kernel event stream (job and exploration events), throttled because
 * `job.state` fires on every automation tick, with a slow fallback interval for a dropped
 * stream. If the series cannot be read the strip is not drawn: no ticks is honest, invented
 * ticks are not.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { colorFor } from "@/components/agentops/ActivityChart";
import { getExplorationStatus, getJobs, getObsTimeseries, type TimeSeriesResponse } from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { countNoun, formatCount } from "@/lib/format";

/** The charter no job kind claims (aughor/kernel/agents.py) — background work, not an agent. */
const RUNNER_AGENT = "Worker";
const IDLE_PHASES = new Set(["", "pending", "complete", "failed"]);

export function ActivityStrip({ connectionId, onOpen }: {
  connectionId?: string;
  /** The strip's door: the Agent Ops overview, where these runs are drawn at full size. */
  onOpen?: () => void;
}) {
  const [chart, setChart] = useState<TimeSeriesResponse | null>(null);
  const [live, setLive] = useState<number | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    getObsTimeseries({ source: "jobs", range: "24h" }).then(setChart).catch(() => setChart(null));
    getJobs({ state: "active", limit: 200 })
      .then(jobs => setLive(jobs.filter(j => j.agent?.agent !== RUNNER_AGENT).length))
      .catch(() => setLive(null));
    if (connectionId) {
      getExplorationStatus(connectionId)
        .then(s => setPhase(!s.paused && !IDLE_PHASES.has(String(s.phase ?? "")) ? String(s.phase) : null))
        .catch(() => setPhase(null));
    } else {
      setPhase(null);
    }
  }, [connectionId]);

  useEffect(() => {
    load();
    const throttled = () => {
      if (pending.current) return;
      pending.current = setTimeout(() => { pending.current = null; load(); }, 10_000);
    };
    const unsub = subscribeKernelEvents(throttled, { kinds: ["job.state", "exploration."] });
    const iv = setInterval(load, 60_000);
    return () => {
      unsub();
      clearInterval(iv);
      if (pending.current) clearTimeout(pending.current);
      pending.current = null;
    };
  }, [load]);

  const ticks = useMemo(() => {
    if (!chart?.measured || !chart.series?.length) return null;
    const order = chart.series.map(s => s.key);
    const buckets = chart.series[0].values.length;
    if (!buckets) return null;
    const hours = (chart.window?.bucket_seconds ?? 3600) / 3600;
    const raw = Array.from({ length: buckets }, (_, i) => {
      let total = 0, topKey = "", topVal = 0;
      for (const s of chart.series) {
        const v = s.values[i] ?? 0;
        total += v;
        if (v > topVal) { topVal = v; topKey = s.key; }
      }
      const top = chart.series.find(s => s.key === topKey);
      return { total, topKey, topLabel: top?.label ?? "", ago: Math.round((buckets - 1 - i) * hours) };
    });
    const max = Math.max(1, ...raw.map(t => t.total));
    return raw.map((t, i) => ({
      ...t,
      height: t.total > 0 ? 3 + Math.round((t.total / max) * 13) : 2,
      color: t.total > 0 ? colorFor(t.topKey, order) : "var(--b2)",
      opacity: 0.3 + 0.7 * (i / Math.max(1, buckets - 1)),
    }));
  }, [chart]);

  if (!ticks) return null;
  const running = (live ?? 0) > 0 || phase != null;
  const status = [phase ? "exploring" : null, live != null ? `${formatCount(live)} live` : null]
    .filter(Boolean).join(" · ") || "idle";

  const door = onOpen ? {
    role: "link" as const,
    tabIndex: 0,
    onClick: onOpen,
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter") onOpen(); },
    style: { cursor: "pointer" },
  } : {};

  return (
    <div className="aug-activity-strip" title="Agent runs, last 24 hours — open Agent Ops" {...door}>
      <span className="aug-activity-label">LIVE</span>
      <div className="aug-activity-ticks" role="img" aria-label={`Agent runs per hour over the last ${ticks.length} hours`}>
        {ticks.map((t, i) => (
          <span
            key={i}
            className="aug-activity-tick"
            title={`${t.ago === 0 ? "This hour" : `${t.ago}h ago`} · ${countNoun(t.total, "agent run")}${t.topLabel && t.total > 0 ? ` · mostly ${t.topLabel}` : ""}`}
            style={{ height: t.height, background: t.color, opacity: t.opacity }}
          />
        ))}
      </div>
      <span className="aug-activity-status" title={phase ? `Explorer phase: ${phase}` : undefined}>{status}</span>
      <span aria-hidden className={`aug-dot ${running ? "aug-dot-live" : "aug-dot-idle"}`} style={{ width: 6, height: 6 }} />
    </div>
  );
}
