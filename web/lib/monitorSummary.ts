/**
 * Monitors, read the way CLARITY.md says a screen reads: what each monitor watches in a few words, whether it has
 * ever been proven to fire, how many checks a day the set costs, and its alerts with repeats folded into a count.
 * Pure functions over what `GET /monitors`, `GET /alerts` and `GET /monitors/{id}/proof` already return.
 */
import type { MonitorAlert, MonitorDef, MonitorProof } from "@/lib/api";
import { compactNumber, formatCount, MONTHS_SHORT, normalizeNumberPrecision } from "@/lib/format";

/** Where a monitor's proof stands, from the server's own record (`aughor/monitors/drill.py::proof`):
 *  proven — a drill fired and delivered; delivered — a real alert went out; checked — a drill fired, nothing sent;
 *  undelivered — a drill fired and delivery failed; silent — a drill did not fire; never — no drill, no delivery. */
export type ProofState = "proven" | "delivered" | "checked" | "undelivered" | "silent" | "never" | "unknown";

export function proofState(p: MonitorProof | null | undefined): ProofState {
  if (!p) return "unknown";
  const d = p.last_drill;
  if (d && d.fired && d.delivered === true) return "proven";
  if (p.last_real_delivery) return "delivered";
  if (d && d.fired && d.delivered === false) return "undelivered";
  if (d && d.fired) return "checked";
  if (d) return "silent";
  return "never";
}

/** Proof states that say the rule has been seen to fire, at least in a drill. */
export const FIRES: ReadonlySet<ProofState> = new Set(["proven", "delivered", "checked"]);

/** The proof as a chip's few words; the server's sentence stays on hover. */
export function proofWords(p: MonitorProof | null | undefined): string {
  const s = proofState(p);
  const when = (iso: string | undefined | null) => (iso ? ` ${dayMonth(iso)}` : "");
  switch (s) {
    case "proven": return `proven${when(p?.last_drill?.at)}`;
    case "delivered": return `alert delivered${when(String(p?.last_real_delivery?.fired_at ?? ""))}`;
    case "checked": return `rule checked${when(p?.last_drill?.at)} · not delivered`;
    case "undelivered": return "delivery failed";
    case "silent": return "rule did not fire";
    case "never": return "never proven";
    default: return "proof unread";
  }
}

export function dayMonth(iso: string): string {
  // A bare day ("2026-09-30") is that day wherever the reader is, not UTC midnight shifted into their zone.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return isNaN(d.getTime()) ? iso : `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

/** How many times a day a schedule runs, for the crons the form writes and their plain variants; null for one it
 *  cannot read without guessing. */
export function checksPerDay(cron: string): number | null {
  const f = (cron || "").trim().split(/\s+/);
  if (f.length !== 5) return null;
  const [min, hour, dom, mon, dow] = f;
  if (dom !== "*" || mon !== "*") return null;
  const days = dow === "*" ? 1 : /^\d$/.test(dow) ? 1 / 7 : /^(\d)-(\d)$/.test(dow)
    ? (Number(dow.split("-")[1]) - Number(dow.split("-")[0]) + 1) / 7 : null;
  if (days == null) return null;
  let perDay: number | null = null;
  if (/^\*\/(\d+)$/.test(min) && hour === "*") perDay = 1440 / Number(min.slice(2));
  else if (min === "*" && hour === "*") perDay = 1440;
  else if (/^\d+$/.test(min) && hour === "*") perDay = 24;
  else if (/^\d+$/.test(min) && /^\*\/(\d+)$/.test(hour)) perDay = 24 / Number(hour.slice(2));
  else if (/^\d+$/.test(min) && /^\d+$/.test(hour)) perDay = 1;
  else if (/^\d+$/.test(min) && /^\d+(,\d+)+$/.test(hour)) perDay = hour.split(",").length;
  return perDay == null ? null : perDay * days;
}

const SCHEDULE_WORD: Record<string, string> = {
  "0 * * * *": "hourly", "0 */6 * * *": "every 6 hours", "0 9 * * *": "daily", "0 9 * * 1": "weekly",
};
export function scheduleWords(cron: string): string {
  return SCHEDULE_WORD[cron] ?? cron;
}

/** "3 hourly · 1 daily" — the set's schedules, most common first; a schedule the form does not name keeps its cron. */
export function scheduleMix(monitors: Pick<MonitorDef, "check_cron">[]): string {
  const m = new Map<string, number>();
  for (const x of monitors) {
    const w = SCHEDULE_WORD[x.check_cron] ?? `on ${x.check_cron}`;
    m.set(w, (m.get(w) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([w, n]) => `${n} ${w}`).join(" · ");
}

/** 86 → "86", 200000 → "200K", 0.125 → "0.13". */
export function short(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return compactNumber(v, Math.abs(v) < 1000 && !Number.isInteger(v) ? 2 : 1).replace(/\.0(?=[KMB]?$)/, "");
}
const num = short;

/** What a monitor watches for, in a few words: "below 86", "2.5σ over 30 days", "orders within 24 h". */
export function ruleWords(m: Pick<MonitorDef, "alert_on" | "warning_threshold" | "critical_threshold" | "threshold_direction"
  | "sigma_threshold" | "history_days" | "dimension_column" | "freshness_table" | "freshness_sla_hours">): string {
  switch (m.alert_on) {
    case "threshold_cross": {
      const parts = [m.warning_threshold != null ? `${m.threshold_direction} ${num(m.warning_threshold)}` : "",
        m.critical_threshold != null ? `critical ${m.threshold_direction} ${num(m.critical_threshold)}` : ""].filter(Boolean);
      return `Threshold · ${parts.join(", ") || "no threshold set"}`;
    }
    case "anomaly": return `Anomaly · ${m.sigma_threshold}σ over ${m.history_days} days`;
    case "trend_reversal": return `Trend reversal · ${m.history_days} days`;
    case "segment_drift": return `Drift${m.dimension_column ? ` by ${m.dimension_column}` : ""}`;
    case "data_freshness": return `Freshness · ${m.freshness_table || "a table"} within ${m.freshness_sla_hours} h`;
    case "any_change": return "Any change";
    default: return String(m.alert_on);
  }
}

const CHANNEL_WORD: Record<string, string> = { in_app: "in-app", slack: "Slack", email: "email" };
export const channelWords = (c: string) => CHANNEL_WORD[c] ?? c;

/** An alert's message with its numbers as a person reads them: "2.026e+04 above … 2e+04" → "20,260 above … 20,000". */
export const alertText = (message: string) => normalizeNumberPrecision(message);

/** The alerts whose monitor no longer exists: history, said apart. A workspace's Monitors page counted four alerts of
 *  two monitors removed weeks before as its own (the Olist study, 2026-10-22: "Open alerts 0 · 5 acknowledged · last 24
 *  Aug" beside one monitor that had never fired). `live` is the monitors read with the alerts. */
export function fromRemovedMonitors<T extends Pick<MonitorAlert, "monitor_id">>(alerts: T[],
  live: ReadonlyArray<Pick<MonitorDef, "id">>): T[] {
  const ids = new Set(live.map(m => m.id));
  return alerts.filter(a => !ids.has(a.monitor_id));
}

/** How many of `alerts` came from monitors since removed, in the Notifications page's words for its removed triggers:
 *  "all from 2 monitors since removed", "3 from 1 monitor since removed", or "" when none did. */
export function removedWords(alerts: Pick<MonitorAlert, "monitor_id">[], live: ReadonlyArray<Pick<MonitorDef, "id">>): string {
  const gone = fromRemovedMonitors(alerts, live);
  if (!gone.length) return "";
  const n = new Set(gone.map(a => a.monitor_id)).size;
  const monitors = `${formatCount(n)} ${n === 1 ? "monitor" : "monitors"} since removed`;
  return gone.length === alerts.length ? `all from ${monitors}` : `${formatCount(gone.length)} from ${monitors}`;
}

/** Alerts that say the same thing, said once: one group per monitor, severity, message and caveat. */
export interface AlertGroup {
  key: string;
  latest: MonitorAlert;
  count: number;
  first: string;
  last: string;
  /** The ids not yet acknowledged. */
  open: string[];
}

export function foldAlerts(alerts: MonitorAlert[]): AlertGroup[] {
  const m = new Map<string, AlertGroup>();
  for (const a of alerts) {
    const key = `${a.monitor_id}|${a.severity}|${a.message}|${a.caveat ?? ""}`;
    const g = m.get(key);
    if (!g) {
      m.set(key, { key, latest: a, count: 1, first: a.triggered_at, last: a.triggered_at, open: a.acknowledged ? [] : [a.id] });
      continue;
    }
    g.count++;
    if (!a.acknowledged) g.open.push(a.id);
    if (a.triggered_at > g.last) { g.last = a.triggered_at; g.latest = a; }
    if (a.triggered_at < g.first) g.first = a.triggered_at;
  }
  return [...m.values()].sort((a, b) => (b.open.length ? 1 : 0) - (a.open.length ? 1 : 0) || b.last.localeCompare(a.last));
}

/** Alerts per week, oldest first, the last `weeks` weeks ending with the week holding `now` (weeks start Monday). */
export function alertsByWeek(alerts: Pick<MonitorAlert, "triggered_at" | "severity">[], now: Date, weeks = 12):
  { start: Date; n: number; bySeverity: Record<string, number> }[] {
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const out = Array.from({ length: weeks }, (_, i) => {
    const start = new Date(monday);
    start.setDate(start.getDate() - (weeks - 1 - i) * 7);
    return { start, n: 0, bySeverity: {} as Record<string, number> };
  });
  for (const a of alerts) {
    const t = new Date(a.triggered_at).getTime();
    if (isNaN(t)) continue;
    for (let i = out.length - 1; i >= 0; i--) {
      const end = i === out.length - 1 ? Infinity : out[i + 1].start.getTime();
      if (t >= out[i].start.getTime() && t < end) {
        out[i].n++;
        out[i].bySeverity[a.severity] = (out[i].bySeverity[a.severity] ?? 0) + 1;
        break;
      }
    }
  }
  return out;
}
