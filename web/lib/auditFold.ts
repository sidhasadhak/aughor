/**
 * Security & Audit's query checks, read the way CLARITY.md says a screen reads them: a thing said once, its
 * repeats folded into a count, and the platform's own reads named as noise rather than counted as alarm.
 *
 * Measured on theLook (2026-10-11): of the latest 200 checks, 196 were the Briefer's period comparisons — 98 of
 * them "suspicious" flags written BEFORE each statement ran (0 rows, 0 ms; the `UNION ALL` of a this-period/
 * last-period read scores as possible injection), then the same 98 statements logged again as they ran. Listed
 * a row each, the page was 200 rows of the platform talking to itself.
 */
import { callerLabel } from "@/lib/names";

export interface AuditRecord {
  id: string;
  ts: string;
  connection_id: string;
  hypothesis_id: string;
  sql_digest: string;
  sql_full: string;
  /** safe · suspicious · blocked — and `pii_blocked`, a result withheld for holding sensitive values. */
  verdict: string;
  row_count: number;
  duration_ms: number;
  pii_redacted: number;
  error: string | null;
}

/** What happened to one statement, in the reader's words. A flag is a note written before the statement ran; the
 *  statement itself is logged again when it runs. */
export type Outcome = "blocked" | "withheld" | "flagged" | "failed" | "passed";

export function outcomeOf(r: Pick<AuditRecord, "verdict" | "error">): Outcome {
  if (r.verdict === "blocked") return "blocked";
  if (r.verdict === "pii_blocked") return "withheld";
  if (r.verdict === "suspicious") return "flagged";
  if (r.error) return "failed";
  return "passed";
}

export const OUTCOME_WORD: Record<Outcome, string> = {
  blocked: "Blocked", withheld: "Withheld", flagged: "Flagged", failed: "Failed", passed: "Passed",
};

/** Callers that are the platform's own background work — its scheduled agents and checks. Nobody asked for these
 *  reads, so a flag on one is the platform talking to itself, not somebody probing the data. */
const PLATFORM_KEYS = new Set(["profile-calibrate", "cb2_review"]);

export function isPlatformCaller(hypothesisId: string): boolean {
  const k = (hypothesisId || "").trim();
  return /^__.+__$/.test(k) || PLATFORM_KEYS.has(k);
}

/** Who ran a statement, as the audit trail names it: the agent that issued it and what it was doing. */
export function callerName(hypothesisId: string): { agent: string; detail?: string } {
  const h = (hypothesisId || "").trim();
  switch (h) {
    case "__explorer__":          return { agent: "Scout", detail: "exploration" };
    case "__monitor__":           return { agent: "Watcher", detail: "monitor" };
    case "__monitor_window__":    return { agent: "Watcher", detail: "window probe" };
    case "__revalidate__":        return { agent: "Curator", detail: "revalidation" };
    case "__fix_save__":          return { agent: "Curator", detail: "fix save" };
    case "__fed_driver__":        return { agent: "Analyst", detail: "federation" };
    case "__remote_join__":       return { agent: "Analyst", detail: "remote join" };
    case "query_builder":         return { agent: "You", detail: "Query Builder" };
    case "query_workbench":       return { agent: "You", detail: "SQL Editor" };
    case "cross_source_join":     return { agent: "You", detail: "cross-source" };
    case "federated_planner":     return { agent: "Analyst", detail: "federation" };
    case "semantic_operator":     return { agent: "You", detail: "semantic op" };
    case "profile-calibrate":     return { agent: "Curator", detail: "profile" };
    case "__brief_metric_move__": return { agent: "Briefer", detail: "metric move check" };
    case "__brief_period__":      return { agent: "Briefer", detail: "period comparison" };
    case "__trust_coltypes__":    return { agent: "Trust check", detail: "column types" };
    case "__automation_probe__":  return { agent: "Automations", detail: "probe" };
    case "cb2_review":            return { agent: "Curator", detail: "measurement" };
  }
  if (h.startsWith("card:")) return { agent: "You", detail: "a pinned card" };
  // A deep analysis's hypotheses and sub-questions (h1, inv2, subq_3, …) are the Analyst's.
  if (/^(h|inv|subq|hypothesis)[\d_]/i.test(h) || h.startsWith("intake") || h.startsWith("clarify")) {
    return { agent: "Analyst", detail: h };
  }
  return callerLabel(h);
}

export function callerText(hypothesisId: string): string {
  const { agent, detail } = callerName(hypothesisId);
  return detail ? `${agent} · ${detail}` : agent;
}

/** Repeats folded: one group per caller and outcome. */
export interface CheckGroup {
  key: string;
  name: string;
  outcome: Outcome;
  /** Every statement in it came from the platform's own background work. */
  own: boolean;
  rows: AuditRecord[];
  latest: string;
  earliest: string;
  /** The newest error's words, for a blocked or failed group. */
  reason: string | null;
}

/** Most needing a person first: refused, withheld, a flag on a person's or an agent's statement, a failure, the
 *  platform's own flags, then what simply passed. */
function rank(g: Pick<CheckGroup, "outcome" | "own">): number {
  switch (g.outcome) {
    case "blocked": return 0;
    case "withheld": return 1;
    case "flagged": return g.own ? 4 : 2;
    case "failed": return 3;
    default: return 5;
  }
}

export function foldChecks(records: AuditRecord[]): CheckGroup[] {
  const groups = new Map<string, CheckGroup>();
  for (const r of records) {
    const outcome = outcomeOf(r);
    const name = callerText(r.hypothesis_id);
    const own = isPlatformCaller(r.hypothesis_id);
    const key = `${outcome}|${own ? "own" : "asked"}|${name}`;
    const g = groups.get(key);
    if (!g) {
      groups.set(key, { key, name, outcome, own, rows: [r], latest: r.ts, earliest: r.ts, reason: r.error ?? null });
      continue;
    }
    g.rows.push(r);
    if (r.ts > g.latest) { g.latest = r.ts; if (r.error) g.reason = r.error; }
    if (r.ts < g.earliest) g.earliest = r.ts;
    if (!g.reason && r.error) g.reason = r.error;
  }
  return [...groups.values()].sort((a, b) => rank(a) - rank(b) || b.rows.length - a.rows.length || a.name.localeCompare(b.name));
}

/** Who ran the statements in a window, most first: past six callers the rest fold into "Other" (CLARITY §5). */
export interface CallerCount {
  name: string;
  total: number;
  flagged: number;
  /** Of those flags, how many the platform raised on its own reads. */
  flaggedOwn: number;
  blocked: number;
  failed: number;
  withheld: number;
}

export function byCaller(records: AuditRecord[], top = 6): CallerCount[] {
  const m = new Map<string, CallerCount>();
  for (const r of records) {
    const name = callerText(r.hypothesis_id);
    const c = m.get(name) ?? { name, total: 0, flagged: 0, flaggedOwn: 0, blocked: 0, failed: 0, withheld: 0 };
    c.total++;
    const o = outcomeOf(r);
    if (o === "flagged") { c.flagged++; if (isPlatformCaller(r.hypothesis_id)) c.flaggedOwn++; }
    else if (o === "blocked") c.blocked++;
    else if (o === "failed") c.failed++;
    else if (o === "withheld") c.withheld++;
    m.set(name, c);
  }
  const all = [...m.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
  if (all.length <= top) return all;
  const rest = all.slice(top - 1).reduce<CallerCount>((o, c) => ({
    name: "Other", total: o.total + c.total, flagged: o.flagged + c.flagged, flaggedOwn: o.flaggedOwn + c.flaggedOwn,
    blocked: o.blocked + c.blocked, failed: o.failed + c.failed, withheld: o.withheld + c.withheld,
  }), { name: "Other", total: 0, flagged: 0, flaggedOwn: 0, blocked: 0, failed: 0, withheld: 0 });
  return [...all.slice(0, top - 1), rest];
}

/** The flags in a window, split into the platform's own reads (noise) and everyone else's (worth a look). */
export function flagSplit(records: AuditRecord[]): { flagged: number; own: number; asked: AuditRecord[] } {
  const flagged = records.filter(r => outcomeOf(r) === "flagged");
  const asked = flagged.filter(r => !isPlatformCaller(r.hypothesis_id));
  return { flagged: flagged.length, own: flagged.length - asked.length, asked };
}

/** Statements blocked within the last `days` days of `now`. */
export function blockedSince(records: AuditRecord[], now: number, days = 7): AuditRecord[] {
  const floor = now - days * 86_400_000;
  return records.filter(r => outcomeOf(r) === "blocked" && Date.parse(r.ts) >= floor);
}

/** "3 from You · Query Builder, 1 from Analyst" — who a set of statements came from, most first. */
export function fromWhom(records: AuditRecord[], top = 3): string {
  const m = new Map<string, number>();
  for (const r of records) m.set(callerText(r.hypothesis_id), (m.get(callerText(r.hypothesis_id)) ?? 0) + 1);
  const parts = [...m.entries()].sort((a, b) => b[1] - a[1]).map(([n, c]) => `${n} ${c}`);
  return parts.length > top ? [...parts.slice(0, top), `+${parts.length - top} more`].join(" · ") : parts.join(" · ");
}
