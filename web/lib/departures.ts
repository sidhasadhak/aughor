/** HB-2 — pure shaping for the departures screen. Kept out of the component (the AgentMap
 *  rule): anything a test must catch lives in a function that needs no DOM. */
import type { ChipHue } from "@/components/brief/StatusChip";
import type {
  Departure, DepartureGuardOutcome, DepartureQuestion,
} from "@/lib/api";

/** Every guard in the order the gate runs them — the order a receipt lists them in. */
export const GUARD_ORDER = [
  "trust", "tie_out", "definition", "remeasure", "freshness", "claims",
  "disagreement", "repeat", "probation",
] as const;

export const GUARD_LABEL: Record<string, string> = {
  trust: "Trust", tie_out: "Tie-out", definition: "Definition", remeasure: "Re-measure",
  freshness: "Freshness", claims: "Claim type", disagreement: "Disagreement",
  repeat: "Repeat", probation: "Probation", held_lines: "Lines held",
};

const TEXT_FIELDS = [
  "id", "ts", "org_id", "kind", "state", "conn_id", "automation_id", "automation_name",
  "actor", "target", "addressed_to", "text_preview", "source_kind", "source_id", "origin",
  "about", "as_of", "verdict", "verdict_note", "verdict_at", "answer", "answered_by",
  "answered_at",
] as const;

function decoded(value: unknown): unknown {
  if (typeof value !== "string") return value;
  if (!value) return undefined;
  try { return JSON.parse(value); } catch { return undefined; }
}

function asRecord<T extends object>(value: unknown): T {
  const v = decoded(value);
  return (v && typeof v === "object" && !Array.isArray(v) ? v : {}) as T;
}

/** One ledger row as the screen reads it. The doors decode the JSON columns; a ledger
 *  served by an older API sends them as strings, and a missing field reads as empty. */
export function normalizeDeparture(raw: Record<string, unknown>): Departure {
  const out: Record<string, unknown> = { ...raw };
  for (const field of TEXT_FIELDS) out[field] = typeof raw[field] === "string" ? raw[field] : "";
  const reasons = decoded(raw.reasons);
  out.reasons = Array.isArray(reasons) ? reasons.map(String) : [];
  out.checks = asRecord(raw.checks);
  out.guards = asRecord(raw.guards);
  out.receipt = asRecord(raw.receipt);
  out.question = asRecord(raw.question);
  return out as unknown as Departure;
}

export type DepartureFilter = "all" | "owed" | "held" | "departed";

/** What a person still owes a departure: a mark (a probation send its declarer reviews)
 *  or an answer (the readings its owner chooses between). */
export function owes(d: Departure): "mark" | "answer" | null {
  if (d.state === "held_probation" && !d.verdict) return "mark";
  if ((d.question.readings?.length ?? 0) > 0 && !d.answer) return "answer";
  return null;
}

export function filterDepartures(rows: Departure[], filter: DepartureFilter): Departure[] {
  if (filter === "owed") return rows.filter(d => owes(d) !== null);
  if (filter === "held") return rows.filter(d => d.state !== "departed");
  if (filter === "departed") return rows.filter(d => d.state === "departed");
  return rows;
}

export function stateLabel(d: Departure): string {
  switch (d.state) {
    case "departed": return "departed";
    case "held_probation": return d.verdict ? `marked ${d.verdict}` : "awaiting its declarer";
    case "held_owner": return d.answer ? "answered" : "asking its owner";
    default: return "held";
  }
}

export function stateHue(d: Departure): ChipHue {
  if (d.state === "departed") return "positive";
  if (d.state === "held") return "negative";
  if (d.state === "held_probation") return d.verdict ? "muted" : "caution";
  return d.answer ? "muted" : "info";
}

const KIND_LABEL: Record<string, string> = {
  slack_post: "Slack post",
  notify: "Action Hub send",
  monitor_alert: "Monitor alert",
  briefing: "Scheduled briefing",
  agent_alert: "Agent alert",
  finding_share: "Shared finding",
  recommendation: "Recommendation",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? (kind || "Departure");
}

export function sourceName(d: Departure): string {
  return d.automation_name || d.source_id || kindLabel(d.kind);
}

export function whenText(ts: string): string {
  return ts ? ts.replace("T", " ").slice(0, 16) : "";
}

export interface GuardRow {
  guard: string;
  label: string;
  /** "recorded" for a row written before the gate recorded outcomes — never a guess. */
  outcome: DepartureGuardOutcome | "recorded";
  summary: string;
}

/** The guards in the gate's order, then anything else its checks recorded. */
export function guardRows(d: Departure): GuardRow[] {
  const known = GUARD_ORDER as readonly string[];
  const keys = [
    ...known.filter(g => g in d.guards || g in d.checks),
    ...Object.keys(d.checks).filter(k => !known.includes(k)),
  ];
  return keys.map(g => ({
    guard: g,
    label: GUARD_LABEL[g] ?? g,
    outcome: d.guards[g] ?? "recorded",
    summary: d.checks[g] ?? "",
  }));
}

export function outcomeColor(outcome: GuardRow["outcome"]): string {
  switch (outcome) {
    case "passed": return "var(--grn3)";
    case "held": return "var(--red3)";
    case "asked": return "var(--cyn3)";
    case "unavailable": return "var(--amb3)";
    default: return "var(--t3)";
  }
}

export function outcomeWord(outcome: GuardRow["outcome"]): string {
  return outcome === "not_applicable" ? "not applicable" : outcome;
}

/** The one line the table shows: what the owner is asked, why it was held, or what ran. */
export function summaryLine(d: Departure): string {
  if (d.state === "held_owner" && d.question.question) return d.question.question;
  if (d.reasons.length) return d.reasons[0];
  const passed = guardRows(d).filter(g => g.outcome === "passed").map(g => g.label.toLowerCase());
  return passed.length ? `checked: ${passed.join(", ")}` : "departed";
}

/** Who the departure waits on, in words. */
export function addressedText(d: Departure): string {
  const owed = owes(d);
  if (!owed) return "";
  if (d.addressed_to) return `waiting on ${d.addressed_to}`;
  return owed === "answer"
    ? "no owner is routable — anyone who can answer may"
    : "waiting on its declarer";
}

/** The readings an owner chooses between, each with its preview. */
export function readingsOf(q: DepartureQuestion): { label: string; preview: string }[] {
  return (q.readings ?? []).map((r, i) => ({ label: r.label, preview: q.previews?.[i] ?? "" }));
}

/** A departure named by a link (`?departure=<id>` — the receipt's link), or "". */
export function departureFromUrl(search: string): string {
  return new URLSearchParams(search).get("departure") ?? "";
}
