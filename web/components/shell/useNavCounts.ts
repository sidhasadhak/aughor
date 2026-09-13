"use client";

/**
 * The counts behind the rail's badges, from reads that change nothing:
 *
 *   unackedAlerts   unacknowledged monitor alerts (GET /alerts) — amber: each one waits on a human
 *   runningRuns     agent runs in flight (GET /investigations, status "running") — neutral: a count
 *
 * Agent Ops' needs-human count is deliberately absent. Its route (GET …/needs-human) runs the
 * expiry and parked-run sweeps on every call, so polling it from the shell would run those sweeps
 * from every screen; it stays on the Agent Ops workspace, which already polls it while open.
 *
 * Refresh rides the shared kernel event stream (monitor.alert, investigation.*), throttled, with
 * a slow fallback interval — acknowledging an alert emits no event, so the interval catches it.
 */
import { useEffect, useRef, useState } from "react";

import { getAllAlerts } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { subscribeKernelEvents } from "@/lib/events";

export interface NavCounts {
  unackedAlerts: number;
  runningRuns: number;
}

export function useNavCounts(workspaceId?: string): NavCounts {
  const [counts, setCounts] = useState<NavCounts>({ unackedAlerts: 0, runningRuns: 0 });
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      getAllAlerts(undefined, 100, workspaceId || undefined)
        .then(alerts => { if (alive) setCounts(c => ({ ...c, unackedAlerts: alerts.filter(a => !a.acknowledged).length })); })
        .catch(() => {});
      fetch(`${getApiBase()}/investigations${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`)
        .then(r => (r.ok ? r.json() : []))
        .then((rows: unknown) => {
          if (!alive) return;
          const running = Array.isArray(rows)
            ? rows.filter(r => (r as { status?: string }).status === "running").length
            : 0;
          setCounts(c => ({ ...c, runningRuns: running }));
        })
        .catch(() => {});
    };
    load();
    const throttled = () => {
      if (pending.current) return;
      pending.current = setTimeout(() => { pending.current = null; load(); }, 5_000);
    };
    const unsub = subscribeKernelEvents(throttled, { kinds: ["monitor.alert", "investigation."] });
    const iv = setInterval(load, 60_000);
    return () => {
      alive = false;
      unsub();
      clearInterval(iv);
      if (pending.current) clearTimeout(pending.current);
      pending.current = null;
    };
  }, [workspaceId]);

  return counts;
}
