/**
 * The Record's client (the 2027 study §G) — claims, inquiries, decisions, scenarios, missions,
 * corrections, the authority table, the attention budget and the ledger API's read side.
 *
 * These doors return the ledger's own entries as plain objects, so the generated client carries
 * no shape for them; the types here are read off `aughor/record/*.py` and the routers that serve
 * them. A refusal's reason is the server's sentence — `RecordError.message` carries `detail`
 * through, so a screen can say why something was refused instead of "request failed".
 */
import { getApiBase } from "./config";

export class RecordError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, init);
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? "");
    } catch {
      detail = "";
    }
    throw new RecordError(res.status, detail || `The request failed (${res.status})`);
  }
  return res.json();
}

function send<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  return read<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ── claims ───────────────────────────────────────────────────────────────────────────────

export type ClaimKind =
  | "observation" | "finding" | "reading" | "definition" | "hypothesis" | "prediction" | "said" | "cause";

export interface ClaimWarrant {
  kind: "run" | "document" | "attestation" | "claim";
  ref: string;
  detail: string;
  reproducible: boolean | null;
  why_not: string;
}

export interface ClaimConfidence {
  reference_class: string;
  hit_rate: number | null;
  n: number;
  scope: string;
  note: string;
}

export interface Claim {
  id: string;
  key: string;
  version: number;
  kind: ClaimKind;
  about: { kind: string; key: string };
  statement: {
    text: string; metric: string; value: number | null; unit: string;
    range_start: string; range_end: string; object_set: string;
  };
  tier: string;
  status: "Final" | "Provisional" | "To date";
  as_of: string;
  valid_from: string;
  valid_until: string;
  warrants: ClaimWarrant[];
  falsifier: string;
  next_check: string;
  owner: string;
  author: string;
  author_kind: "person" | "agent" | "system";
  definition_version: string;
  state: string;
  extra: Record<string, unknown>;
  recorded_at: string;
  supersedes: string;
  superseded_by: string;
  confidence: ClaimConfidence | null;
  /** Why no confidence is counted for this claim's class yet — present when `confidence` is null. */
  confidence_note?: string;
  /** Present on the single-claim read: the decisions that cite this claim. */
  relied_on_by?: string[];
  /** Present on the single-claim read: every gate decision on a message that cited the answer
   *  behind this claim — and, when there is nothing to read, why. */
  told?: ToldRow[];
  told_note?: string;
}

/** One message that left (or was held) citing an answer. */
export interface ToldRow {
  at: string; state: string; kind: string; target: string; addressed_to: string; by: string;
  verdict: string; departure_id: string;
}

/** What marking a claim wrong set in motion, beside the claim's new version. */
export interface MarkedWrong extends Claim {
  superseded: string;
  woke_inquiries: string[];
  reopened_decisions: string[];
}

export interface ClaimFilter {
  kind?: string; about_kind?: string; about_key?: string; connection_id?: string;
  state?: string; as_of?: string; limit?: number;
}

export const listClaims = (f: ClaimFilter = {}) => read<Claim[]>(`/record/claims${qs({ ...f })}`);
export const getClaim = (id: string) => read<Claim>(`/record/claims/${encodeURIComponent(id)}`);
export const getClaimVersions = (id: string) => read<Claim[]>(`/record/claims/${encodeURIComponent(id)}/versions`);
export const markClaimWrong = (id: string, body: { corrected?: string; why?: string; by?: string }) =>
  send<MarkedWrong>(`/record/claims/${encodeURIComponent(id)}/wrong`, body);

// ── inquiries ────────────────────────────────────────────────────────────────────────────

export type RunVerdictKind =
  | "answered" | "contradicted" | "no_data" | "no_definition" | "withheld" | "out_of_budget" | "tool_failed";

export interface RunNote { run: string; verdict: string; why: string; at: string }

export interface Inquiry {
  id: string;
  key: string;
  version: number;
  question: string;
  subject: string;
  connection_id: string;
  opened_by: string;
  hypotheses: string[];
  runs: RunNote[];
  claims: string[];
  open: { what: string; settled_by: string }[];
  decisions: string[];
  state: "open" | "waiting" | "closed";
  waiting_for: string;
  closed_as: string;
  next_check: string;
  woke: Record<string, unknown>[];
  refused: Record<string, unknown>[];
  lessons: { believed: string; turned_out: string }[];
  opened_at: string;
  extra: Record<string, unknown>;
  recorded_at: string;
  /** The version that replaced this one — "" on the current version. */
  superseded_by: string;
}

export interface InquiryDetail extends Inquiry {
  /** Each hypothesis as it stands now — the latest version, once. */
  hypothesis_claims: Claim[];
  /** What it established, as it stands now; `restated_since` when that is not how it was cited. */
  established_claims: (Claim & { cited_as: string; restated_since: boolean })[];
  run_verdicts: { run: string; verdict: string; why: string; at?: string }[];
}

export type VerdictTallies = Record<RunVerdictKind, number>;

export const listInquiries = (f: { connection_id?: string; state?: string; due?: boolean; limit?: number } = {}) =>
  read<Inquiry[]>(`/record/inquiries${qs({ ...f })}`);
export const getInquiry = (id: string) => read<InquiryDetail>(`/record/inquiries/${encodeURIComponent(id)}`);
export const getRunVerdicts = (connectionId?: string) =>
  read<VerdictTallies>(`/record/inquiries/verdicts${qs({ connection_id: connectionId })}`);
export const proposeInquiryRun = (id: string) =>
  send<InquiryDetail>(`/record/inquiries/${encodeURIComponent(id)}/propose`);
export const closeInquiry = (id: string, closedAs: string, lessons: { believed: string; turned_out: string }[]) =>
  send<InquiryDetail>(`/record/inquiries/${encodeURIComponent(id)}/close`, { closed_as: closedAs, lessons });

/** What the Record already holds as refuted that a new hypothesis resembles — said beside it. */
export interface ResemblesRefuted { hypothesis: string; refuted_by: string; refuted_on: string; overlap: number; evidence: string }

export const addInquiryHypothesis = (id: string, text: string, by?: string) =>
  send<InquiryDetail & { resembles_refuted: ResemblesRefuted | null }>(
    `/record/inquiries/${encodeURIComponent(id)}/hypothesis`, { text, by });
export const handInquiry = (id: string, owner: string, by?: string) =>
  send<InquiryDetail>(`/record/inquiries/${encodeURIComponent(id)}/owner`, { owner, by });
export const setInquiryNextCheck = (id: string, on: string, waitingFor = "", by?: string) =>
  send<InquiryDetail>(`/record/inquiries/${encodeURIComponent(id)}/next-check`, { on, waiting_for: waitingFor, by });

// ── decisions, outcomes, scenarios ───────────────────────────────────────────────────────

export interface DecisionOption {
  id: string; description: string; predictions: string[]; cost: string; reversibility: string; actor: string;
}

export interface Decision {
  id: string;
  key: string;
  version: number;
  question: string;
  owner: string;
  approvers: string[];
  options: DecisionOption[];
  chosen: string;
  dissent: { who: string; why: string }[];
  relied_on: string[];
  objective: string;
  decided_at: string;
  decided_by: string;
  review_on: string;
  expectation_claim: string;
  actions: string[];
  outcome: string;
  reopened_by: string;
  source: { kind: string; ref: string; detail: string };
  connection_id: string;
  extra: Record<string, unknown>;
  recorded_at: string;
  /** The version that replaced this one — "" on the current version. */
  superseded_by: string;
}

export type OutcomeVerdict = "as_expected" | "better" | "worse" | "cannot_tell";

export interface Outcome {
  id: string;
  of: string;
  measured_on: string;
  actual: number | null;
  baseline: number | null;
  effect: { value: number | null; low: number | null; high: number | null; method: string };
  verdict: OutcomeVerdict;
  why: string;
  against_expectation: string;
  writes_back: string[];
  measured_by: string;
  recorded_at: string;
}

export interface DecisionDetail extends Decision {
  relied_on_claims: Claim[];
  expectation: Claim | null;
  outcome_record: Outcome | null;
  /** What replaced the claim it stood on, while the decision is reopened and unanswered. */
  reopened_by_claim: Claim | null;
}

export interface ExpectationIn {
  metric: string; direction?: string; low?: number | null; mid?: number | null; high?: number | null;
  unit?: string; coverage?: number; settles_on?: string; text?: string;
}

export interface DeclareDecisionBody {
  question: string;
  chosen: string;
  options?: string[];
  owner?: string;
  dissent?: { who: string; why: string }[];
  relied_on?: string[];
  objective?: string;
  connection_id?: string;
  /** When it was decided, for a decision taken before today. */
  decided_at?: string;
  decided_by?: string;
  review_on?: string;
  expectation?: ExpectationIn | null;
  note?: string;
}

export interface OutcomeBody {
  measured_on: string; actual?: number | null; baseline?: number | null; verdict: OutcomeVerdict;
  why?: string; against_expectation?: string;
  /** The measured effect against the baseline — what a later decision of this kind is projected from. */
  effect_value?: number | null;
  /** The person booking it, when no sign-in names them. */
  measured_by?: string;
}

export interface Projection {
  method: string; tier: string; value: number | null; low: number | null; high: number | null;
  coverage: number | null; unit: string; must_say: string[]; backtest: Record<string, unknown>;
  inputs: Record<string, unknown>; claim: string; note: string;
}

export interface Scenario {
  id: string;
  for_kind: string;
  for_id: string;
  question: string;
  assumptions: { variable: string; value: number | null; source: string; by: string; text: string; claim: string }[];
  predictions: string[];
  limits: string[];
  methods: string[];
  tier: string;
  connection_id: string;
  recorded_at: string;
}

/** A past decision that asked the same question, with its measured effect. */
export interface PastCase {
  outcome: string; decision: string; effect: number; verdict: string; measured_on: string; method: string;
  question: string; matched_on: string;
}

export interface ScenarioBody {
  method: "identity" | "declared" | "history" | "intervention";
  metric: string;
  settles_on?: string;
  direction?: string;
  unit?: string;
  formula?: string;
  inputs?: Record<string, number>;
  varied?: string[];
  assumption?: { variable: string; value: number | null; by?: string; text?: string; unit?: string; low?: number | null; high?: number | null };
  limits?: string[];
  question?: string;
  /** The person projecting, when no sign-in names them. */
  by?: string;
}

export interface CalibrationRow {
  method: string; metric: string; author: string; n: number; inside: number; above: number; below: number;
  cannot_tell: number; coverage_observed: number | null; coverage_stated: number | null; signed_error: number | null;
}

export const listDecisions = (f: { connection_id?: string; due?: boolean; limit?: number } = {}) =>
  read<Decision[]>(`/record/decisions${qs({ ...f })}`);
export const getDecision = (id: string) => read<DecisionDetail>(`/record/decisions/${encodeURIComponent(id)}`);
export const declareDecision = (body: DeclareDecisionBody) => send<DecisionDetail>("/record/decisions", body);
export const bookOutcome = (id: string, body: OutcomeBody) =>
  send<{ outcome_id: string; decision: Decision | null }>(`/record/decisions/${encodeURIComponent(id)}/outcome`, body);
export const listScenarios = (decisionId: string) =>
  read<{ scenarios: Scenario[]; predictions: (Claim & { booked_as: string })[] }>(
    `/record/decisions/${encodeURIComponent(decisionId)}/scenarios`);
export const amendDecision = (id: string, body: { option?: string; dissent?: { who: string; why: string }; by?: string }) =>
  send<DecisionDetail>(`/record/decisions/${encodeURIComponent(id)}/amend`, body);
export const decisionStands = (id: string, why: string, by?: string) =>
  send<DecisionDetail>(`/record/decisions/${encodeURIComponent(id)}/stands`, { why, by });
export const getPastCases = (decisionId: string, metric: string) =>
  read<{ cases: PastCase[]; needed: number; measurable: boolean | null }>(
    `/record/decisions/${encodeURIComponent(decisionId)}/cases${qs({ metric })}`);
export const bookScenario = (decisionId: string, body: ScenarioBody) =>
  send<{ scenario: Scenario; projection: Projection; prediction: Claim | null }>(
    `/record/decisions/${encodeURIComponent(decisionId)}/scenario`, body);
export const getCalibration = (connectionId?: string) =>
  read<CalibrationRow[]>(`/record/calibration${qs({ connection_id: connectionId })}`);

// ── corrections ──────────────────────────────────────────────────────────────────────────

export type CorrectionKind =
  | "restatement" | "refuted_hypothesis" | "missed_move" | "prediction_outside_interval" | "decision_worse_than_expected";

export interface CorrectionEntry {
  kind: CorrectionKind;
  at: string;
  connection_id: string;
  ref: string;
  believed: string;
  replaced_by: string;
  why: string;
  believed_as_of?: string;
  replaced_as_of?: string;
  decision?: string;
  inquiry?: string;
  run?: string;
  metric?: string;
  method?: string;
}

export interface Corrections {
  counts: Record<CorrectionKind, number>;
  labels: Record<CorrectionKind, string>;
  entries: CorrectionEntry[];
  note: string;
}

export const getCorrections = (f: { connection_id?: string; kind?: string; limit?: number } = {}) =>
  read<Corrections>(`/record/corrections${qs({ ...f })}`);

// ── missions ─────────────────────────────────────────────────────────────────────────────

/** The measurable definition a metric is read by — resolved from the approved metric when absent. */
type MetricSpec = Record<string, unknown> | null;

export interface MissionObjective {
  metric: string; direction: string; target: number | null; unit: string; by_when: string; text: string;
  spec?: MetricSpec;
}
export interface MissionConstraint {
  metric: string; kind: string; limit: number | null; bound: "at_least" | "at_most"; unit: string; text: string;
  spec?: MetricSpec;
}
export interface MissionBudget {
  interruptions_per_week: number; spend_per_month: number | null; spend_unit: string;
  authority_ceiling: Record<string, number>;
}
export interface MissionWatch { kind: string; ref: string; label: string }

export interface Mission {
  id: string;
  key: string;
  version: number;
  name: string;
  objective: MissionObjective;
  constraints: MissionConstraint[];
  scope: { domain: string; segment: string; connections: string[] };
  owner: string;
  budget: MissionBudget;
  watches: MissionWatch[];
  review: { cadence: string; next_report_on: string; last_report: string; reports: string[] };
  state: "proposed" | "active" | "paused" | "met" | "retired";
  written_by: string;
  opened_at: string;
  history: Record<string, unknown>[];
  recorded_at: string;
  /** The version that replaced this one — "" on the current version. */
  superseded_by: string;
  interruptions_this_week: number;
  /** Whether the loop reads it: active and owned. */
  runs: boolean;
  runs_note?: string;
}

export interface MissionDetail extends Mission {
  requested_version: number;
  reports: { id: string; period: { from: string; to: string } | null; headline: string | null; verdict: string | null }[];
}

export interface MissionReport {
  mission: string;
  name: string;
  owner: string;
  state: string;
  period: { from: string; to: string; days: number; cadence: string };
  headline: string;
  objective: MissionObjective & {
    measurable: boolean; note?: string; verdict: string; why: string;
    actual?: number | null; baseline?: number | null; low?: number | null; high?: number | null;
  };
  constraints: { metric: string; kind: string; limit: number | null; bound: string; held: boolean | null; note: string; actual: number | null; window: string }[];
  watches: (MissionWatch & { state: string })[];
  opened: { inquiries: number; by_state: Record<string, number>; ids: string[] };
  decided: { id?: string; question?: string; chosen?: string; verdict?: string; outcome?: string; review_on?: string }[];
  cost: {
    interruptions: number; interruptions_budgeted: number; held: number;
    actions_by_level: Record<string, number>; demotions: unknown[];
    spend: { amount: number | null; unit: string; tokens: number; llm_calls: number; runs: number; unpriced_calls: number; budget: number | null; budget_unit: string; against_budget: string; note: string };
  };
  autonomy: { acted: unknown[]; l5_actions: string[]; note: string };
  lessons: (string | { believed?: string; turned_out?: string })[];
  composed_at: string;
  composed_by: string;
}

export interface MissionBody {
  name: string;
  objective: { metric: string; direction?: string; target?: number | null; unit?: string; by_when?: string; text?: string; spec?: MetricSpec };
  constraints?: { metric: string; kind?: string; limit?: number | null; bound?: string; unit?: string; text?: string; spec?: MetricSpec }[];
  domain?: string;
  segment?: string;
  connections?: string[];
  owner?: string;
  budget?: { interruptions_per_week?: number; spend_per_month?: number | null; spend_unit?: string; authority_ceiling?: Record<string, number> };
  cadence?: string;
  state?: string;
  key?: string;
  watches?: MissionWatch[];
  /** The person writing it, when no sign-in names them. */
  written_by?: string;
}

/** A body a pack ships for a person to write a mission from — it never becomes one on its own. */
export interface MissionTemplate {
  pack: string;
  id: string;
  name: string;
  description: string;
  cadence: string;
  body: Partial<MissionBody>;
  note: string;
}

export const listMissions = (f: { connection_id?: string; state?: string; owner?: string } = {}) =>
  read<Mission[]>(`/record/missions${qs({ ...f })}`);
export const getMission = (id: string) => read<MissionDetail>(`/record/missions/${encodeURIComponent(id)}`);
export const writeMission = (body: MissionBody) => send<Mission>("/record/missions", body);
export const setMissionState = (id: string, state: string, why = "") =>
  send<Mission>(`/record/missions/${encodeURIComponent(id)}/state`, { state, why });
export const getMissionReport = (id: string, compose = false) =>
  read<{ booked: boolean; report: MissionReport | null; note?: string }>(
    `/record/missions/${encodeURIComponent(id)}/report${qs({ compose })}`);
export const getPastMissionReport = (id: string, reportId: string) =>
  read<{ booked: boolean; report: MissionReport | null; note?: string }>(
    `/record/missions/${encodeURIComponent(id)}/reports/${encodeURIComponent(reportId)}`);
/** Report now: composed and booked, and — unless `deliver` is false — sent to the owner through the gate. */
export const reportMissionNow = (id: string, deliver: boolean) =>
  send<{ report_id: string; report: MissionReport; delivery: { door?: string; status?: string; note?: string }; mission: Mission }>(
    `/record/missions/${encodeURIComponent(id)}/report?deliver=${deliver ? "true" : "false"}`);
export const getMissionTemplates = (connectionId?: string) =>
  read<{ templates: MissionTemplate[]; packs: string[]; note: string }>(
    `/record/missions/templates${qs({ connection_id: connectionId })}`);

// ── set aside: "not now" on what waits on a person ───────────────────────────────────────

export type SetAsideKind = "decision" | "inquiry" | "departure" | "approval";

/** One item a person took off the Now list until a day — and, once it is back, why. */
export interface SetAside {
  item_kind: SetAsideKind;
  /** The item's stable name: a decision's or an inquiry's key, a departure's or a proposal's id. */
  ref: string;
  until: string;
  why: string;
  by: string;
  at: string;
  title: string;
  status: "active" | "returned";
  /** Why it is on the list again: its day came, or the record behind it changed. */
  back_because: string;
}

export const getSetAside = () => read<{ today: string; active: SetAside[]; returned: SetAside[] }>("/record/set-aside");
export const setItemAside = (body: { kind: SetAsideKind; ref: string; until: string; why: string; title?: string; by?: string }) =>
  send<SetAside>("/record/set-aside", body);
export const restoreItem = (kind: SetAsideKind, ref: string, by?: string) =>
  send<SetAside>("/record/set-aside/restore", { kind, ref, by });

/** Told to the rail when what waits on a person changed on this page, so its badge re-reads now. */
export const WAITING_CHANGED_EVENT = "aughor:waiting-changed";

// ── the attention budget (triage at the departure gate) ──────────────────────────────────

export interface HeldItem {
  departure_id: string; at: string; kind: string; target: string; addressed_to: string;
  by: string; text: string; why: string; triage: string;
}

export interface AttentionBudget {
  addressee: string; week_start: string; slots: number; used: number; left: number;
  held: HeldItem[]; held_count: number; note: string;
}

export interface TriageTerm { term: string; label: string; weight: number; read_today: string }

export const getAttentionBudget = (addressee: string) =>
  read<AttentionBudget>(`/attention/budget${qs({ addressee })}`);
export const getAttentionHeld = (addressee?: string) =>
  read<{ week_start: string; held: HeldItem[] }>(`/attention/held${qs({ addressee })}`);
export const getTriageTerms = () => read<{ terms: TriageTerm[]; held_state: string }>("/attention/terms");
export const setAttentionSlots = (addressee: string, slots: number) =>
  send<AttentionBudget>("/attention/slots", { addressee, slots });

// ── the authority table (the action centre) ──────────────────────────────────────────────

/** What the ladder is computed from — a record, not an opinion. */
export interface ActionRecordCounts {
  executions: number; verified: number; failed_verifications: number; unverified: number;
  approved_by_person: number; under_grant: number; undone: number; last_run: string;
}

/** One declared action on one connection: the level it may run at, and why. */
export interface AuthorityLevel {
  action_id: string;
  scope: string;
  level: number;
  label: string;
  /** What the record earned, before any ceiling. */
  earned: number;
  ceiling: number;
  why: string;
  notes: string[];
  record: ActionRecordCounts;
  /** The receipt that granted L4, the entry that took it, the L5 receipt — ids, "" when none. */
  graduation: string;
  demotion: string;
  l5: string;
  /** The ceiling a person set on this action here, outside any mission — null when none stands. */
  person_ceiling: { level: number; by: string; why: string; at: string } | null;
}

export interface AuthorityRow extends AuthorityLevel {
  /** What L4 would still need, one reason a line. */
  graduation_check: string[];
  reversibility: string;
  verification_declared: boolean;
  undo_declared: boolean;
}

export interface AuthorityTable {
  connection_id: string;
  levels: Record<string, string>;
  graduation_n: number;
  l5_n: number;
  actions: AuthorityRow[];
  note: string;
}

export interface AuthorityRecord extends AuthorityLevel {
  graduation_check: { can_graduate: boolean; reasons: string[] };
  executions: ActionExecution[];
}

export interface ActionExecution {
  id?: string;
  entry?: string;
  at?: string;
  actor?: string;
  under?: string;
  status?: string;
  params?: Record<string, unknown>;
  verification?: { status: string; why?: string; sql?: string };
  undo?: { action_id?: string; window_hours?: number; open?: boolean; until?: string; why?: string; fired?: string } | null;
  [k: string]: unknown;
}

export const getAuthorityTable = (connectionId: string) =>
  read<AuthorityTable>(`/authority${qs({ connection_id: connectionId })}`);
export const getAuthorityRecord = (actionId: string, connectionId: string) =>
  read<AuthorityRecord>(`/authority/${encodeURIComponent(actionId)}/record${qs({ connection_id: connectionId })}`);
export const demoteAction = (actionId: string, connectionId: string, why: string, drill = false, by?: string) =>
  send<Record<string, unknown>>(`/authority/${encodeURIComponent(actionId)}/demote`, { connection_id: connectionId, why, drill, by });
/** Cap an action on a connection at a level, or — with `null` — lift the cap. It only ever lowers. */
export const setActionCeiling = (actionId: string, connectionId: string, level: number | null, why = "", by?: string) =>
  send<Record<string, unknown>>(`/authority/${encodeURIComponent(actionId)}/ceiling`, { connection_id: connectionId, level, why, by });
/** Sign a standing grant for an action at L4: one target value, an expiry, a cap on uses. */
export const signStandingGrant = (actionId: string, connectionId: string, body: { target_value: string; expires_days: number; max_uses: number; by?: string }) =>
  send<{ grant: Record<string, unknown> }>(`/authority/${encodeURIComponent(actionId)}/widen`, { connection_id: connectionId, ...body });
export const graduateAction = (actionId: string, connectionId: string) =>
  send<Record<string, unknown>>(`/authority/${encodeURIComponent(actionId)}/graduate`, { connection_id: connectionId });
export const undoExecution = (actionId: string, entryId: string, connectionId: string) =>
  send<Record<string, unknown>>(
    `/authority/${encodeURIComponent(actionId)}/executions/${encodeURIComponent(entryId)}/undo`,
    { connection_id: connectionId });
export const getGatewayWrites = () =>
  read<{ writes: Record<string, unknown>[]; count: number; note: string }>("/authority/writes");

// ── the ledger API's read side (the developer screen) ────────────────────────────────────

export interface ContractDuty { duty: string; books: string[]; proposes: string[]; today: string; why: string }
export interface AgentContract {
  version: string;
  duties: ContractDuty[];
  [k: string]: unknown;
}
export interface EventKind {
  kind: string; what: string; payload: string[]; emitted_by: string; category: string; subscribable: boolean;
}
export interface ServicePrincipal {
  name: string; duties?: string[]; clearance?: string; created_at?: string; created_by?: string;
  revoked_at?: string; [k: string]: unknown;
}
export interface PrincipalRecord { principal: string; [k: string]: unknown }

export const getContract = () => read<AgentContract>("/ledger/v1/contract");
export const getEventCatalogue = () => read<{ kinds: EventKind[]; [k: string]: unknown }>("/ledger/v1/events/catalogue");
export const getServicePrincipals = () => read<{ principals: ServicePrincipal[] }>("/ledger/v1/principals/service");
export const getPrincipalRecord = (principal: string) =>
  read<PrincipalRecord>(`/ledger/v1/principals/${encodeURIComponent(principal)}/record`);
export const mintServicePrincipal = (body: Record<string, unknown>) =>
  send<Record<string, unknown>>("/ledger/v1/principals/service", body);
export const revokeServicePrincipal = (name: string, why: string) =>
  send<Record<string, unknown>>(`/ledger/v1/principals/service/${encodeURIComponent(name)}${qs({ why })}`, undefined, "DELETE");
/** A projection method registered from outside: it runs as a foreign tool and carries its backtest. */
export interface RegisteredMethod {
  name: string; kind: string; declared_by: string; tier: string; note: string; registered_at: string;
  backtest: { n: number; metric: string; mae: number | null; mape: number | null; coverage_stated: number | null;
    coverage_observed: number | null; measured_on: string[]; note: string };
  adapter: { kind: string; server_id: string; tool: string };
}

export interface MethodBody {
  name: string; kind: string; note?: string;
  backtest: { n: number; metric?: string; mae?: number | null; mape?: number | null; coverage_observed?: number | null; measured_on: string[] };
  adapter: { server_id: string; tool: string };
}

export const getMethods = () =>
  read<{ builtin: string[]; registered: RegisteredMethod[]; rule: string }>("/ledger/v1/methods");
export const registerMethod = (body: MethodBody) => send<RegisteredMethod>("/ledger/v1/methods", body);
export const withdrawMethod = (name: string) =>
  send<RegisteredMethod>(`/ledger/v1/methods/${encodeURIComponent(name)}`, undefined, "DELETE");

/** What the static gate says about a set of pack files — nothing is written by asking. */
export interface PackVerdict {
  ok: boolean; pack_id: string; errors: string[]; warnings: string[]; files: number;
  static_gate?: string; declares?: Record<string, number | boolean>;
}

export const checkPack = (files: Record<string, string>) => send<PackVerdict>("/packs/check", { files });
export const uploadPack = (files: Record<string, string>, overwrite = false) =>
  send<Record<string, unknown>>("/packs/upload", { files, overwrite });
export const getRestatements = (since: string, connectionId?: string) =>
  read<{ restatements: Record<string, unknown>[]; [k: string]: unknown }>(
    `/ledger/v1/restatements${qs({ since, connection_id: connectionId })}`);

// ── onboarding: coverage and the shopping list ───────────────────────────────────────────

export interface Onboarding {
  connection_id: string;
  hours: { hours: number | null; passed: boolean | null; note: string; gate_hours: number };
  packs: unknown[];
  shopping_list: { what?: string; unlocks?: string[]; [k: string]: unknown }[];
  shopping_note: string;
  coverage: Record<string, unknown>;
  [k: string]: unknown;
}

export const getOnboarding = (connectionId: string) =>
  read<Onboarding>(`/onboarding${qs({ connection_id: connectionId })}`);

// ── words for the ledger's own identifiers ───────────────────────────────────────────────

/** `user:ana` → `ana`; `person:ana` → `ana`; `monitor:churn-watch` → `the churn-watch monitor`;
 *  an empty author reads as nobody named, never as a blank cell. */
export function whoLabel(who: string | null | undefined): string {
  const w = (who ?? "").trim();
  if (!w) return "nobody named";
  const [kind, ...rest] = w.split(":");
  const name = rest.join(":");
  if (!name) return w === "system" ? "the platform" : w === "person" ? "a person" : w === "unidentified" ? "nobody identified" : w;
  if (kind === "user" || kind === "person") return name;
  if (kind === "monitor") return `the ${name} monitor`;
  if (kind === "agent") return `the ${name} agent`;
  if (kind === "claim") return "a restated claim";
  return `${kind} ${name}`;
}

/** A sentence the ledger wrote with a principal's id in it (`user:ana's assumption`) read with
 *  the name instead — the id is the ledger's, the name is the reader's. */
export function plainWho(text: string): string {
  return text.replace(/\b(?:user|person):([\w.-]+)/g, "$1");
}

export const VERDICT_WORDS: Record<string, string> = {
  answered: "answered",
  contradicted: "contradicted",
  no_data: "no data",
  no_definition: "no definition",
  withheld: "withheld",
  out_of_budget: "out of budget",
  tool_failed: "tool failed",
  as_expected: "as expected",
  better: "better than expected",
  worse: "worse than expected",
  cannot_tell: "cannot tell",
};

export const verdictWords = (v: string | null | undefined) => (v ? VERDICT_WORDS[v] ?? v.replace(/_/g, " ") : "");
