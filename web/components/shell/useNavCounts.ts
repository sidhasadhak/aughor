"use client";

/**
 * The counts behind the rail's badges, from reads that change nothing:
 *
 *   unackedAlerts   unacknowledged monitor alerts (GET /alerts) — each one waits on a human
 *   decisionsDue    decisions whose review date has come with no outcome booked (GET /record/decisions?due)
 *   inquiriesDue    waiting inquiries whose check date has come (GET /record/inquiries?due)
 *   departuresOwed  sends held for a person's mark or answer (GET /departures/summary)
 *
 * One rule (the 2027 study §U, rule 4): a badge counts only what waits on a person. A count that
 * is only a count — runs in flight — is not a badge; the topbar's activity strip already says it.
 *
 * Agent Ops' needs-human count is deliberately absent. Its route (GET …/needs-human) runs the
 * expiry and parked-run sweeps on every call, so polling it from the shell would run those sweeps
 * from every screen; the Now page reads it while that page is open.
 *
 * Refresh rides the shared kernel event stream (monitor.alert, inquiry.*, outcome.*, claim.*),
 * throttled, with a slow fallback interval — acknowledging an alert or marking a send emits no
 * event, so the interval catches it.
 */
import { useEffect, useRef, useState } from "react";

import { getAllAlerts, getDepartureSummary } from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { listDecisions, listInquiries } from "@/lib/record";

export interface NavCounts {
  unackedAlerts: number;
  decisionsDue: number;
  inquiriesDue: number;
  departuresOwed: number;
}

const NONE: NavCounts = { unackedAlerts: 0, decisionsDue: 0, inquiriesDue: 0, departuresOwed: 0 };

/** What waits on a person across the product — Now's badge. */
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
    const unsub = subscribeKernelEvents(throttled, { kinds: ["monitor.alert", "inquiry.", "outcome.", "claim."] });
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
