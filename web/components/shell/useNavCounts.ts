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
 * like the alerts: each one waits on a human. What a person set aside on that page until a later
 * day (GET /record/set-aside) is left out of each, as it is left off the page's list.
 *
 * Agent Ops' needs-human count is deliberately absent. Its route (GET …/needs-human) runs the
 * expiry and parked-run sweeps on every call, so polling it from the shell would run those sweeps
 * from every screen; it stays on the Agent Ops workspace, which already polls it while open.
 *
 * Refresh rides the shared kernel event stream (monitor.alert, investigation.*), throttled, with
 * a slow fallback interval — acknowledging an alert emits no event, so the interval catches it.
 */
import { useEffect, useRef, useState } from "react";

import { getAllAlerts, getDepartureSummary, getDepartures } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { owes } from "@/lib/departures";
import { subscribeKernelEvents } from "@/lib/events";
import { WAITING_CHANGED_EVENT, getSetAside, listDecisions, listInquiries } from "@/lib/record";

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
      // What a person set aside is off the count as it is off the list. An older API has no such
      // read, and then nothing is set aside.
      const aside = getSetAside()
        .then(a => new Set(a.active.map(x => `${x.item_kind}:${x.ref}`)))
        .catch(() => new Set<string>());
      Promise.all([listDecisions({ due: true }), aside])
        .then(([rows, off]) => { if (alive) setCounts(c => ({ ...c, decisionsDue: rows.filter(d => !off.has(`decision:${d.key}`)).length })); })
        .catch(() => {});
      Promise.all([listInquiries({ due: true }), aside])
        .then(([rows, off]) => { if (alive) setCounts(c => ({ ...c, inquiriesDue: rows.filter(q => !off.has(`inquiry:${q.key}`)).length })); })
        .catch(() => {});
      aside.then(async off => {
        // The summary is one cheap count; the rows are read only when one of them is set aside.
        if (![...off].some(k => k.startsWith("departure:"))) return (await getDepartureSummary())?.awaiting ?? 0;
        const rows = (await getDepartures({ awaiting: true, limit: 200 })) ?? [];
        return rows.filter(d => owes(d) !== null && !off.has(`departure:${d.id}`)).length;
      })
        .then(n => { if (alive) setCounts(c => ({ ...c, departuresOwed: n })); })
        .catch(() => {});
    };
    load();
    window.addEventListener(WAITING_CHANGED_EVENT, load);
    const throttled = () => {
      if (pending.current) return;
      pending.current = setTimeout(() => { pending.current = null; load(); }, 5_000);
    };
    const unsub = subscribeKernelEvents(throttled, { kinds: ["monitor.alert", "investigation.", "inquiry.", "outcome."] });
    const iv = setInterval(load, 60_000);
    return () => {
      alive = false;
      window.removeEventListener(WAITING_CHANGED_EVENT, load);
      unsub();
      clearInterval(iv);
      if (pending.current) clearTimeout(pending.current);
      pending.current = null;
    };
  }, [workspaceId]);

  return counts;
}
