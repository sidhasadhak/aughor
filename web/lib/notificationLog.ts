/**
 * The Notifications screen's delivery log, read the way a person reads it (`aughor-v2/CLARITY.md` §2: say a thing
 * once, fold repeats into a count, name noise as noise).
 *
 * The API returns the latest sends one row each. Fifty failures from one trigger are one fact said fifty times, so
 * they fold to one row per trigger and outcome with a count; a trigger that no longer exists is history, not a call to
 * act, and its rows say so. An error is cut to a few words for the row, and a webhook's path — where a Slack hook keeps
 * its secret — never reaches the screen, short or long.
 */

export type DeliveryStatus = "ok" | "failed" | "timeout" | "skipped";

/** One send, as `GET /actions/logs` returns it. */
export interface DeliveryLog {
  id: string;
  trigger_id: string;
  trigger_name: string;
  rec_index?: number;
  recommendation: string;
  status: DeliveryStatus;
  http_status: number | null;
  error: string | null;
  fired_at: string;
  /** The wire's other fields — among them what sent it (`SOURCE_FIELD`). */
  [field: string]: unknown;
}

/** The wire field that says what sent a message: `automation:<id>`, `monitor:<id>`, a run id, or "". It keeps its
 *  frozen name on the wire; the screen says what it means instead. */
export const SOURCE_FIELD = "investigation_id";

const SOURCES: [prefix: string, words: string][] = [
  ["automation:", "an automation"],
  ["monitor:", "a monitor"],
  ["brief:", "the Briefing"],
  ["mission:", "a mission"],
  ["agent_alert:", "an agent alert"],
];

/** What sent this message, in a reader's words. */
export function sourceWords(log: DeliveryLog): string {
  const ref = String(log[SOURCE_FIELD] ?? "");
  if (!ref) return "an action";
  if (ref === "test_inv") return "a test fire";
  for (const [prefix, words] of SOURCES) if (ref.startsWith(prefix)) return words;
  return "a recommendation acted on";
}

/** An error with every URL's path cut: a Slack webhook carries its secret in the path, and a connection error quotes
 *  it back (`… with url: /services/…`). The host stays — it is what tells a person where the send went. */
export function redactError(error: string): string {
  return error
    .replace(/\b(https?:\/\/[^/\s'"]+)\/[^\s'")]*/g, "$1/…")
    .replace(/(with url: )\S+/g, "$1…");
}

/** The error in a few words for a row; the whole (redacted) error is behind Details. */
export function shortError(log: Pick<DeliveryLog, "error" | "status" | "http_status">): string {
  const e = (log.error ?? "").trim();
  if (!e) {
    if (log.http_status) return `HTTP ${log.http_status}`;
    return log.status === "timeout" ? "no answer in time" : "";
  }
  if (/trigger is disabled/i.test(e)) return "the trigger was off";
  const at = e.match(/host='([^']+)', port=(\d+)/);
  if (at && /NewConnectionError|Connection refused|Max retries/i.test(e)) return `could not connect to ${at[1]}:${at[2]}`;
  if (/timed?\s?out/i.test(e)) return "no answer in time";
  if (/SSRF|not an allowed/i.test(e)) return "refused: not an allowed address";
  if (log.http_status) return `HTTP ${log.http_status}`;
  const clean = redactError(e);
  return clean.length > 80 ? `${clean.slice(0, 79)}…` : clean;
}

/** The words a row uses for an outcome. */
export const OUTCOME_WORD: Record<DeliveryStatus, string> = {
  ok: "sent", failed: "failed", timeout: "timed out", skipped: "skipped",
};

/** Sends folded to one row per trigger and outcome. */
export interface DeliveryGroup {
  key: string;
  triggerId: string;
  triggerName: string;
  outcome: DeliveryStatus;
  count: number;
  first: string;
  last: string;
  latest: DeliveryLog;
  /** What sent them, each said once ("an automation", "a monitor"). */
  sources: string[];
  /** What they carried, each said once, newest first. */
  messages: string[];
  /** The trigger they went through no longer exists. */
  removed: boolean;
}

/** Fold the latest sends: one group per (trigger, outcome), newest group first. `liveIds` are the triggers that exist
 *  now; a group whose trigger is not among them is history. */
export function foldDeliveries(logs: DeliveryLog[], liveIds: ReadonlySet<string>): DeliveryGroup[] {
  const groups = new Map<string, DeliveryGroup>();
  for (const log of [...logs].sort((a, b) => (a.fired_at || "").localeCompare(b.fired_at || ""))) {
    const key = `${log.trigger_id}:${log.status}`;
    const g = groups.get(key);
    const source = sourceWords(log);
    const message = (log.recommendation ?? "").trim();
    if (!g) {
      groups.set(key, {
        key, triggerId: log.trigger_id, triggerName: log.trigger_name || "a trigger with no name", outcome: log.status,
        count: 1, first: log.fired_at, last: log.fired_at, latest: log, sources: [source], messages: message ? [message] : [],
        removed: !liveIds.has(log.trigger_id),
      });
      continue;
    }
    g.count += 1;
    g.last = log.fired_at;
    g.latest = log;
    if (log.trigger_name) g.triggerName = log.trigger_name;
    if (!g.sources.includes(source)) g.sources.push(source);
    if (message) g.messages = [message, ...g.messages.filter(m => m !== message)];
  }
  return [...groups.values()].sort((a, b) => (b.last || "").localeCompare(a.last || ""));
}

/** The newest send through each trigger. */
export function latestByTrigger(logs: DeliveryLog[]): Map<string, DeliveryLog> {
  const out = new Map<string, DeliveryLog>();
  for (const log of logs) {
    const seen = out.get(log.trigger_id);
    if (!seen || (log.fired_at || "") >= (seen.fired_at || "")) out.set(log.trigger_id, log);
  }
  return out;
}

/** How many of a trigger's newest sends failed in a row (a timeout counts: nothing is known to have landed). */
export function failingStreak(logs: DeliveryLog[], triggerId: string): number {
  const mine = logs.filter(l => l.trigger_id === triggerId)
    .sort((a, b) => (b.fired_at || "").localeCompare(a.fired_at || ""));
  let n = 0;
  for (const l of mine) {
    if (l.status === "failed" || l.status === "timeout") n += 1;
    else break;
  }
  return n;
}

/** Where a trigger sends, without its secret: the API returns the URL masked to `scheme://host/••••••`, and this keeps
 *  only the host. */
export function hostOf(maskedUrl: string): string {
  const rest = (maskedUrl || "").split("://")[1] ?? "";
  return rest.split("/")[0] ?? "";
}
