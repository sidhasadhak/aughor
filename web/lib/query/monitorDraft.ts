"use client";

/**
 * SE-4 I — the handoff behind "Schedule" in the query workbench.
 *
 * The workbench and MonitorsPanel live in different tabs of the shell and are separate
 * dynamic chunks; neither is an ancestor of the other. So the SQL travels through a
 * one-shot store rather than a prop.
 *
 * sessionStorage, not a module variable: the destination is a dynamically imported chunk
 * that may not have loaded yet when the draft is written, and a module variable would
 * also be lost to the fast-refresh remount that happens constantly in development. Per
 * TAB (sessionStorage, not local), because a draft is about what THIS window is doing.
 *
 * One-shot by construction — `takeMonitorDraft` clears as it reads. A draft that
 * survived would repopulate the monitor form every time the user visited the tab,
 * long after they abandoned the idea.
 */

const KEY = "aughor.monitorDraft.v1";

export interface MonitorDraft {
  connId: string;
  sql: string;
}

export function putMonitorDraft(draft: MonitorDraft): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(draft));
  } catch {
    // Private mode, or a full quota. The user lands on the monitors tab with an empty
    // form instead of a prefilled one — degraded, not broken.
  }
}

export function takeMonitorDraft(connId: string): MonitorDraft | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const d = JSON.parse(raw) as MonitorDraft;
    // A draft belongs to the connection it was captured on. Applying it to another
    // would prefill a monitor with SQL against tables that connection may not have.
    if (!d?.sql || (connId && d.connId && d.connId !== connId)) return null;
    sessionStorage.removeItem(KEY);
    return d;
  } catch {
    return null;
  }
}
