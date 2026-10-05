"use client";

/**
 * The counts behind the rail's badges, from reads that change nothing:
 *
 *   unackedAlerts   unacknowledged monitor alerts (GET /alerts) — amber: each one waits on a human
 *   runningRuns     agent runs in flight (GET /investigations, status "running") — neutral: a count
 *   decisionsDue    decisions whose review date has come with no outcome booked (GET /record/decisions?due)
 *   inquiriesDue    waiting inquiries whose check date has come (GET /record/inquiries?due)
 *   departuresOwed  sends held for a person's mark or answer (GET /departures/summary)
 *
 * The last three are what the Now page lists under "Waiting on you"; their sum is its badge, amber
 * like the alerts: each one waits on a human.
 *
 * Agent Ops' needs-human count is deliberately absent. Its route (GET …/needs-human) runs the
 * expiry and parked-run sweeps on every call, so polling it from the shell would run those sweeps
 * from every screen; it stays on the Agent Ops workspace, which already polls it while open.
 *
 * Refresh rides the shared kernel event stream (monitor.alert, investigation.*), throttled, with
 * a slow fallback interval — acknowledging an alert emits no event, so the interval catches it.
 */
import { useEffect, useRef, useState } from "react";

import { getAllAlerts, getDepartureSummary } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { subscribeKernelEvents } from "@/lib/events";
import { listDecisions, listInquiries } from "@/lib/record";

export interface NavCounts {
  unackedAlerts: number;
  runningRuns: number;
  decisionsDue: number;
  inquiriesDue: number;
  departuresOwed: number;
}

const NONE: NavCounts = { unackedAlerts: 0, runningRuns: 0, decisionsDue: 0, inquiriesDue: 0, departuresOwed: 0 };

/** What the Now page holds for a person — its badge. */
export function waitingOnAPerson(c: NavCounts): number {
  return c.decisionsDue + c.inquiriesDue + c.departuresOwed;
}

export function useNavCounts(workspaceId?: string): NavCounts {
  const [counts, setCounts] = useState<NavCounts>(NONE);
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
      listDecisions({ due: true })
        .then(rows => { if (alive) setCounts(c => ({ ...c, decisionsDue: rows.length })); })
        .catch(() => {});
      listInquiries({ due: true })
        .then(rows => { if (alive) setCounts(c => ({ ...c, inquiriesDue: rows.length })); })
        .catch(() => {});
      getDepartureSummary()
        .then(sum => { if (alive) setCounts(c => ({ ...c, departuresOwed: sum?.awaiting ?? 0 })); })
        .catch(() => {});
    };
    load();
    const throttled = () => {
      if (pending.current) return;
      pending.current = setTimeout(() => { pending.current = null; load(); }, 5_000);
    };
    const unsub = subscribeKernelEvents(throttled, { kinds: ["monitor.alert", "investigation.", "inquiry.", "outcome."] });
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
