/**
 * The turn view-model and the parts→turn projection — CA-1.
 *
 * This is the reducer's heir. `investigationStream.ts` accumulated a `ChatTurn`
 * by dispatching 107 actions off a closed SSE switch; every organ on the chat
 * surface (ChatMessage and its registry, the gates, the trace) speaks that turn
 * shape, and the shape itself was never the problem — the closed switch and the
 * hand-rolled lifecycle were. So the shape stays, and the ACCUMULATION becomes a
 * pure function over an AI-SDK `UIMessage`'s parts: same fields, same semantics,
 * derived instead of dispatched. Persisted form == streamed form == projected
 * form; there is nothing left to restore.
 *
 * ── Where each field now comes from ─────────────────────────────────────────
 *
 *   • typed `data-*` parts — one projector per declared part name, in
 *     `PART_PROJECTORS`. The record is deliberately enumerable: the coverage
 *     test walks the declared vocabulary and fails on any name that neither
 *     projects nor has an explicit fallback. That is the open-model discipline
 *     the reducer could not offer.
 *   • text parts — the adapter stamps each block's channel
 *     (`providerMetadata.aughor.channel`), so streaming prose lands in
 *     `headlineStream` / `narrativeStream` / `reportStream` exactly as the
 *     `*_delta` actions used to write it. Settled values arrive as data parts
 *     (`data-headline`, `data-narrative`, `data-answer`) and win, clearing the
 *     streams — the reducer's replace semantics, reproduced.
 *   • lifecycle — the SDK owns it. `status` is derived: an `error` part is
 *     terminal, a streaming message is loading, everything else is done.
 *
 * Pure on purpose: no I/O, no hooks, no module state. Given the same message it
 * returns the same turn, which is what makes thread restore equal to
 * `setMessages` and nothing else.
 */

import type { UIMessage } from "ai";

import type { PlaybookRef, FindingDossier } from "@/lib/api";
import type {
  AnswerReport,
  ExplorationReport,
  Hypothesis,
  InvestigationPhase,
  OverviewReport,
  SubQuestion,
  SubQuestionAnswer,
} from "@/lib/types";

import type { AughorUIDataTypes } from "./aughorUIDataTypes";
import { synthesizeResumedUserMessage } from "./uiMessageAdapter";

// Re-export so surfaces can keep saying `InvPhase` without naming the types module.
export type { InvestigationPhase as InvPhase };

/** A message whose data parts are Aughor's declared vocabulary. */
export type AughorUIMessage = UIMessage<unknown, AughorUIDataTypes>;

// ── The turn shape (moved verbatim from the retired reducer) ──────────────────

export interface ContextJoin { from: string; to: string; kind: string }
export interface ContextManifest {
  tables: string[];
  table_count: number;
  estimated_tokens: number;
  joins: ContextJoin[];
}

// Editable plan gate (P3): the sub-question plan surfaced for review before the fan-out.
export interface PlanSubQuestion {
  id: string;
  question: string;
  purpose: string;
  expected_output: string;
  depends_on?: string[];
}
export interface PlanPending {
  investigationId: string | null;
  subQuestions: PlanSubQuestion[];
  chainLength: number;
  estimatedTokens: number;
}

// P4 clarify gate: a material metric-reading ambiguity awaiting the user's choice.
export interface ClarifyPending {
  investigationId: string | null;
  subject: string;
  metricLabel: string;
  question: string;
  options: string[];
  previews: string[];
}

/** A4 — one visible guard intervention: a silent rewrite made narratable. */
export interface GuardReceipt {
  guard: string;
  action: string;
  detail: string;
  before?: string;
  after?: string;
}

/** FL-2 — one narrated failover-chain hop. `event` is "fallback" (a link took
 *  over from the primary) or "link_failed" (that link died too; the chain moved
 *  on). Backends are raw ids ("gemini"); labels resolve via BACKEND_LABEL. */
export interface ChainState {
  event: string;
  from: string;
  to: string;
  model: string;
  detail: string;
}

/**
 * VA-2 — one delegated hop: work a NAMED agent did inside this turn.
 *
 * A delegate's frames reach the stream carrying `delegate` provenance, and without
 * this they would land on the turn itself: `sql` is last-write-wins, so a delegate's
 * query would quietly become "the query behind this answer" — a question the
 * supervisor never asked, attributed to the supervisor. So a delegated frame is
 * projected into the HOP instead of the turn.
 *
 * `work` is a full `ChatTurn` on purpose. The hop's sql / rows / receipts are produced
 * by the SAME `PART_PROJECTORS` the turn's are, so they mean the same thing by
 * construction; projecting them a second way here would be the second authority this
 * module exists to avoid.
 */
export interface DelegatedHop {
  agentId: string;
  agentName: string;
  /** The agent that delegated THIS hop — "" when the conversation itself did. */
  parentAgentId: string;
  /** Root-to-here agent ids. The same value the runtime refuses cycles on. */
  agentPath: string;
  depth: number;
  /** Frame names this hop produced, in arrival order. */
  frames: string[];
  /** What the delegate actually did, projected exactly as a turn is. */
  work: ChatTurn;
}

/** CI-6a — one converse tool step: the model chose a tool, and this is the record. */
export interface ConverseStep {
  index: number;
  tool: string;
  ok: boolean;
  detail: string;
  resultChars: number;
}

/** The one recovery a user can perform (Wave R4). A closed set on purpose. */
export type ErrorRecovery = "retry" | "switch_model" | "fix_config" | "";

export type ErrorDetail = {
  reason: string;          // stable code (rate_limited, bad_key, truncated, …)
  retryable: boolean;      // re-sending the SAME request could plausibly succeed
  recovery: ErrorRecovery; // the one action worth offering
  hint: string;            // that action, in a sentence
};

/** Read the typed fields off an `error` payload, or null when the backend predates
 *  them. Null rather than a guessed default: "this backend does not classify errors"
 *  and "this error is unclassifiable" must not render the same. */
export function toErrorDetail(p: Record<string, unknown>): ErrorDetail | null {
  const reason = typeof p.reason === "string" ? p.reason : "";
  if (!reason) return null;
  const recovery = typeof p.recovery === "string" ? p.recovery : "";
  return {
    reason,
    retryable: p.retryable === true,
    recovery: (["retry", "switch_model", "fix_config"].includes(recovery) ? recovery : "") as ErrorRecovery,
    hint: typeof p.hint === "string" ? p.hint : "",
  };
}

export interface ChatTurn {
  id: string;
  question: string;
  mode: "ask" | "investigate";
  status: "loading" | "done" | "error";
  guardReceipts: GuardReceipt[];
  /** VA-2 — delegated hops, in first-seen order. Empty for an undelegated turn. */
  delegations: DelegatedHop[];
  converseSteps: ConverseStep[];
  scanItems: string[];
  scanProgress: { done: number; total: number } | null;
  /** FL-2 — the failover chain's last narrated hop; null while the primary holds. */
  chainState: ChainState | null;

  // Ask mode
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  headline: string | null;
  headlineStream: string | null;
  chartType: string | null;
  chartConfig?: Record<string, unknown> | null;

  route: {
    depth: "quick" | "deep" | "overview";
    mode: string;
    tier: string;
    why: string;
    ambiguous: boolean;
    forced: string | null;
    downgradedFrom: string | null;
  } | null;

  agent: {
    agentId: string;
    name: string;
    connectionId: string;
    docCount: number;
  } | null;

  clarify: {
    question: string;
    options: string[];
    previews: string[];
    source: string;
    reason: string;
  } | null;

  escalate: {
    signal: string;
    reason: string;
  } | null;

  // Investigate mode
  statusText: string | null;
  phases: InvestigationPhase[];
  deepReport: AnswerReport | null;
  report: Record<string, unknown> | null;
  queryMode: string | null;

  // Explore mode
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  exploreReport: ExplorationReport | null;

  // Dossier (Tier-0 trace)
  dossierReport: FindingDossier | null;
  dossierInsightId: string | null;

  // Overview (interesting-facts tour)
  overviewReport?: OverviewReport | null;

  // Real-time investigation progress
  queriesExecuted: { sql: string; row_count: number; error: string | null }[];
  latestScore: Record<string, unknown> | null;
  hypotheses: Hypothesis[];
  investigationId: string | null;
  receiptId: string | null;
  publicReceiptId: string | null;

  // Shared
  tablesUsed: string[];
  contextManifest: ContextManifest | null;
  planPending: PlanPending | null;
  clarifyPending: ClarifyPending | null;
  followups: string[];
  analysis: { intent: string; steps: string[] } | null;
  error: string | null;
  errorDetail: ErrorDetail | null;

  // Timing — wall clock for the whole turn. The SDK message carries no clock, so
  // the surface that watched the turn stream passes what it measured; a restored
  // turn is inert (0 / null), exactly as the old restore left it.
  startedAt: number;
  elapsedMs: number | null;

  // Cache metadata
  fromCache: boolean;
  cachedQuestion: string | null;

  inspectWarning: { issues: string[]; suggestedFix: string } | null;
  playbookRefs: PlaybookRef[];

  narrative: {
    narrative: string;
    anomalies: string[];
    trend: string;
    confidence: string;
  } | null;

  narrativeStream: string | null;
  reportStream: string | null;

  clarifyingQuestions: string[];
  clarifyingContext: string;
}

export const EMPTY_TURN: Omit<ChatTurn, "id" | "question" | "mode"> = {
  status: "loading",
  route: null,
  agent: null,
  clarify: null,
  escalate: null,
  guardReceipts: [],
  delegations: [],
  converseSteps: [],
  scanItems: [], scanProgress: null,
  chainState: null,
  sql: null, columns: [], rows: [], headline: null, headlineStream: null, chartType: null,
  statusText: null, phases: [], deepReport: null, report: null, queryMode: null,
  subQuestions: [], subqAnswers: [], exploreReport: null,
  dossierReport: null, dossierInsightId: null,
  overviewReport: null,
  queriesExecuted: [], latestScore: null,
  hypotheses: [], investigationId: null, receiptId: null, publicReceiptId: null,
  tablesUsed: [], contextManifest: null, planPending: null, clarifyPending: null, followups: [], analysis: null, error: null, errorDetail: null,
  startedAt: 0, elapsedMs: null,
  fromCache: false, cachedQuestion: null,
  inspectWarning: null,
  playbookRefs: [],
  narrative: null,
  narrativeStream: null,
  reportStream: null,
  clarifyingQuestions: [],
  clarifyingContext: '',
};

// The one shared sentence for interrupted work (unified plan Layer 0.4) — mirrors
// aughor/kernel/jobs.py UNCERTAIN_RESULT. Interrupted ≠ failed: "failed" claims a
// fact nobody observed, so every surface that gives up on learning the truth says
// this instead of coining its own wording.
export const UNCERTAIN_RESULT = "its result is uncertain and was not replayed";

// Tiny session ID generator — no external deps
export function newSessionId() {
  return Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
}

// ── The projection ────────────────────────────────────────────────────────────

type Payload = Record<string, unknown>;

/**
 * One projector per declared data-part name. Each body is the corresponding
 * reducer case, ported: same field, same defaulting, same replace-vs-append
 * decision. Mutating the draft is safe because `projectTurn` builds a fresh
 * object per call — the function stays pure from the outside.
 */
const PART_PROJECTORS: Record<string, (t: ChatTurn, d: Payload) => void> = {
  route: (t, d) => {
    t.route = {
      depth: (d.depth as "quick" | "deep" | "overview") ?? "quick",
      mode: (d.mode as string) ?? "",
      tier: (d.tier as string) ?? "",
      why: (d.why as string) ?? "",
      ambiguous: Boolean(d.ambiguous),
      forced: (d.forced as string) ?? null,
      downgradedFrom: (d.downgraded_from as string) ?? null,
    };
    // The router decided the depth — set the turn's effective mode so the
    // existing renderers (quick vs investigate) work unchanged.
    t.mode = t.route.depth === "deep" ? "investigate" : "ask";
  },
  agent: (t, d) => {
    t.agent = {
      agentId: (d.agent_id as string) ?? "",
      name: (d.name as string) ?? "",
      connectionId: (d.connection_id as string) ?? "",
      docCount: Number(d.doc_count ?? 0),
    };
  },
  clarify: (t, d) => {
    t.clarify = {
      question: (d.question as string) ?? "",
      options: (d.options as string[]) ?? [],
      previews: (d.previews as string[]) ?? [],
      source: (d.source as string) ?? "",
      reason: (d.reason as string) ?? "",
    };
  },
  escalate: (t, d) => {
    t.escalate = { signal: (d.signal as string) ?? "", reason: (d.reason as string) ?? "" };
  },
  sql: (t, d) => { t.sql = (d.sql as string) ?? null; },
  guard_receipt: (t, d) => {
    t.guardReceipts = [...t.guardReceipts, {
      guard: (d.guard as string) ?? "",
      action: (d.action as string) ?? "",
      detail: (d.detail as string) ?? "",
      before: d.before as string | undefined,
      after: d.after as string | undefined,
    }];
  },
  chain_state: (t, d) => {
    t.chainState = {
      event: (d.event as string) ?? "",
      from: (d.from as string) ?? "",
      to: (d.to as string) ?? "",
      model: (d.model as string) ?? "",
      detail: (d.detail as string) ?? "",
    };
  },
  converse_step: (t, d) => {
    t.converseSteps = [...t.converseSteps, {
      index: (d.index as number) ?? 0,
      tool: (d.tool as string) ?? "",
      ok: d.ok !== false,
      detail: (d.detail as string) ?? "",
      resultChars: (d.result_chars as number) ?? 0,
    }];
  },
  columns: (t, d) => { t.columns = (d.columns as string[]) ?? []; },
  rows: (t, d) => { t.rows = (d.rows as unknown[][]) ?? []; },
  headline: (t, d) => { t.headline = (d.headline as string) ?? null; t.headlineStream = null; },
  answer: (t, d) => { t.headline = ((d.text ?? d.answer) as string) ?? null; t.headlineStream = null; },
  narrative: (t, d) => {
    t.narrative = {
      narrative: (d.narrative as string) ?? (d.insight as string) ?? "",
      anomalies: (d.anomalies as string[]) ?? [],
      trend: (d.trend as string) ?? "stable",
      confidence: (d.confidence as string) ?? "medium",
    };
    t.narrativeStream = null;
  },
  receipt_id: (t, d) => { t.publicReceiptId = (d.receipt_id as string) ?? null; },
  chart_type: (t, d) => { t.chartType = (d.chart_type as string) ?? null; },
  chart_config: (t, d) => { t.chartConfig = (d.chart_config as Record<string, unknown>) ?? null; },
  tables_used: (t, d) => { t.tablesUsed = (d.tables as string[]) ?? []; },
  context_assembled: (t, d) => { t.contextManifest = d as unknown as ContextManifest; },
  plan_pending: (t, d) => {
    t.planPending = {
      investigationId: (d.investigation_id as string) ?? null,
      subQuestions: (d.sub_questions as PlanSubQuestion[]) ?? [],
      chainLength: (d.chain_length as number) ?? 0,
      estimatedTokens: (d.estimated_tokens as number) ?? 0,
    };
  },
  clarify_pending: (t, d) => {
    t.clarifyPending = {
      investigationId: (d.investigation_id as string) ?? null,
      subject: (d.subject as string) ?? "",
      metricLabel: (d.metric_label as string) ?? "",
      question: (d.question as string) ?? "",
      options: (d.options as string[]) ?? [],
      previews: (d.previews as string[]) ?? [],
    };
  },
  followups: (t, d) => { t.followups = (d.questions as string[]) ?? []; },
  analysis: (t, d) => {
    t.analysis = { intent: (d.intent as string) ?? "", steps: (d.steps as string[]) ?? [] };
  },
  mode: (t, d) => { t.queryMode = (d.query_mode as string) ?? null; },
  status: (t, d) => {
    // Defensive: declared in the vocabulary though the native stream spells its
    // progress via phase frames — a payload that names its text still lands.
    const text = String(d.text ?? d.status ?? d.message ?? "");
    if (text) t.statusText = text;
  },
  phase_complete: (t, d) => {
    const phase = d.phase as InvestigationPhase;
    t.phases = [...t.phases, phase];
    t.statusText = `Analyzing ${phase?.phase_id}…`;
  },
  phase_progress: (t, d) => {
    const done = d.done as number, total = d.total as number;
    const current = (d.current as string) || "";
    t.statusText = current
      ? `Scanning ${current} · ${done}/${total}…`
      : `Scanning dimensions · ${done}/${total}…`;
    t.scanProgress = { done, total };
    if (current && !t.scanItems.includes(current)) t.scanItems = [...t.scanItems, current];
  },
  hypotheses: (t, d) => { t.hypotheses = (d.hypotheses as Hypothesis[]) ?? []; },
  score: (t, d) => {
    const score = (d.score as Record<string, unknown>) ?? {};
    t.latestScore = score;
    t.hypotheses = (score.hypotheses as Hypothesis[] | undefined) ?? t.hypotheses;
  },
  queries_executed: (t, d) => {
    const queries = (d.queries as { sql: string; row_count: number; error: string | null }[]) ?? [];
    const fail = queries.filter(q => q.error).length;
    t.queriesExecuted = [...t.queriesExecuted, ...queries];
    t.statusText = `Ran ${queries.length} quer${queries.length === 1 ? "y" : "ies"}${fail ? ` (${fail} failed)` : ""}…`;
  },
  inspect_warning: (t, d) => {
    t.inspectWarning = {
      issues: (d.issues as string[]) ?? [],
      suggestedFix: (d.suggested_fix as string) ?? "",
    };
  },
  playbook_refs: (t, d) => { t.playbookRefs = (d.items as PlaybookRef[]) ?? []; },
  clarifying_questions: (t, d) => {
    t.clarifyingQuestions = (d.questions as string[]) ?? [];
    t.clarifyingContext = (d.context_note as string) ?? "";
  },
  // WIRE NAMES — FROZEN: `ada_report` / `d.ada_report` are the backend's spelling
  // (deprecated alias for `answer_report`, kept one release — REC-U9).
  answer_report: (t, d) => projectDeepReport(t, d),
  ada_report: (t, d) => projectDeepReport(t, d),
  dossier_report: (t, d) => {
    t.dossierReport = d.dossier as FindingDossier;
    t.dossierInsightId = (d.insight_id as string) ?? null;
    t.queryMode = "dossier";
    t.statusText = null;
  },
  overview_report: (t, d) => {
    // Leave `mode` untouched (route set it to "ask" for an overview depth) so the
    // turn renders via the dedicated overview branch, not the investigate registry.
    t.overviewReport = d.overview_report as OverviewReport;
    t.queryMode = "overview";
    t.statusText = null;
  },
  report: (t, d) => {
    const qMode = (d.query_mode as string) ?? "investigate";
    projectCacheMeta(t, d);
    t.report = d.report as Record<string, unknown>;
    t.queryMode = qMode;
    t.statusText = null;
    t.investigationId = (d.investigation_id as string) ?? t.investigationId;
    // For direct-routed agentic queries, surface the first query's SQL + results
    // so the turn renders like Quick mode (chart/table + SQL).
    if (qMode === "direct" && Array.isArray(d.query_history) && (d.query_history as unknown[]).length > 0) {
      const q = (d.query_history as { sql: string; columns: string[]; rows: unknown[][] }[])[0];
      if (q.sql) t.sql = q.sql;
      if (q.columns?.length) t.columns = q.columns;
      if (q.rows?.length) t.rows = q.rows;
    }
  },
  explore_report: (t, d) => {
    projectCacheMeta(t, d);
    t.exploreReport = d.explore_report as ExplorationReport;
    t.subQuestions = (d.sub_questions ?? []) as SubQuestion[];
    t.subqAnswers = (d.subq_answers ?? []) as SubQuestionAnswer[];
    t.queryMode = "explore";
    t.statusText = null;
    t.investigationId = (d.investigation_id as string) ?? t.investigationId;
  },
  // The AG-UI composite figure — declared in the vocabulary (the seam's render_answer
  // tool re-frames into per-field frames today, but the composite is legal wire).
  figure: (t, d) => {
    if (typeof d.sql === "string") t.sql = d.sql;
    if (Array.isArray(d.columns)) t.columns = d.columns as string[];
    if (Array.isArray(d.rows)) t.rows = d.rows as unknown[][];
    if (typeof d.chart_type === "string") t.chartType = d.chart_type;
    if (d.chart_config) t.chartConfig = d.chart_config as Record<string, unknown>;
    if (Array.isArray(d.tables_used)) t.tablesUsed = d.tables_used as string[];
  },
  error: (t, d) => {
    t.status = "error";
    t.error = String(d.message ?? "stream error");
    t.errorDetail = toErrorDetail(d);
  },
  done: (t, d) => {
    if (d.has_receipt) t.receiptId = (d.inv_id as string) ?? t.receiptId;
  },
};

function projectDeepReport(t: ChatTurn, d: Payload) {
  projectCacheMeta(t, d);
  t.deepReport = (d.answer_report ?? d.ada_report) as AnswerReport;
  t.reportStream = null;
  t.queryMode = (d.query_mode as string) ?? "investigate";
  t.statusText = null;
  t.investigationId = (d.investigation_id as string) ?? t.investigationId;
}

function projectCacheMeta(t: ChatTurn, d: Payload) {
  if (d.from_cache) {
    t.fromCache = true;
    t.cachedQuestion = (d.cached_question as string) ?? null;
  }
}

/** Every part name the projection consumes — one half of the coverage contract. */
export const PROJECTED_PARTS: ReadonlySet<string> = new Set(Object.keys(PART_PROJECTORS));

/** Part names deliberately NOT projected: they render as a labelled fallback in
 *  `PartsMessage` instead (the escape hatch is a rendering decision, not state). */
export const FALLBACK_PARTS: ReadonlySet<string> = new Set(["unknown_frame"]);

export interface ProjectTurnOptions {
  /** Stable id for the turn (React key + scroll anchor) — the USER message's id,
   *  which exists from the send; the assistant message may not exist yet. */
  id?: string;
  /** The mode the client asked with — the reducer's ASK action carried it. A
   *  `route` part overrides it, exactly as the ROUTE action did. */
  initialMode?: "ask" | "investigate";
  /** True while this turn's assistant message is still streaming in. */
  streaming?: boolean;
  /** A transport-level failure for THIS turn (the SDK surfaces it as chat.error,
   *  never as a part) — renders as the turn's error tail. */
  transportError?: string | null;
  /** Wall-clock measured by the surface that watched the turn stream. */
  timing?: { startedAt: number; elapsedMs: number | null };
}

/** Read a text part's channel stamp; unstamped text reads as narrative prose. */
function textChannel(part: { providerMetadata?: Record<string, unknown> }): string {
  const aughor = part.providerMetadata?.["aughor"] as { channel?: string } | undefined;
  return aughor?.channel ?? "narrative";
}

export interface ProjectedThreadTurn {
  turn: ChatTurn;
  userMsg: AughorUIMessage;
  assistantMsg?: AughorUIMessage;
}

/**
 * Project a whole conversation: each user message opens a turn, the assistant
 * message that follows is its body. The LAST turn carries the live lifecycle —
 * the SDK's streaming state and any transport-level error, neither of which is
 * a part. Pure, like `projectTurn`; every chat surface derives its turns here
 * so the pairing rule cannot fork.
 */
export function projectThread(
  messages: AughorUIMessage[],
  opts: {
    /** True while the SDK is mid-stream (status submitted | streaming). */
    streaming?: boolean;
    /** The SDK's transport error, if its status is `error`. */
    transportError?: string | null;
    /** Wall-clock per turn, keyed by user-message id (measured by the surface). */
    timingFor?: (userMessageId: string) => { startedAt: number; elapsedMs: number | null } | undefined;
  } = {},
): ProjectedThreadTurn[] {
  const pairs: { userMsg: AughorUIMessage; assistantMsg?: AughorUIMessage }[] = [];
  let pendingUser: AughorUIMessage | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      if (pendingUser) pairs.push({ userMsg: pendingUser });
      pendingUser = m;
    } else if (m.role === "assistant") {
      if (pendingUser) {
        pairs.push({ userMsg: pendingUser, assistantMsg: m });
        pendingUser = null;
      } else {
        // FL-1b — an assistant message with no user partner is a RESUMED run:
        // the tab reloaded mid-stream and the thread restarted empty. Dropping
        // it rendered a live run as a blank page; instead, the seam synthesizes
        // the user side from the question it stashed off the wire's `start`
        // frame, so the turn renders whole.
        pairs.push({
          userMsg: synthesizeResumedUserMessage(m) as AughorUIMessage,
          assistantMsg: m,
        });
      }
    }
  }
  if (pendingUser) pairs.push({ userMsg: pendingUser });

  return pairs.map(({ userMsg, assistantMsg }, i) => {
    const last = i === pairs.length - 1;
    const question = userMsg.parts
      .filter((p): p is { type: "text"; text: string } => p.type === "text")
      .map((p) => p.text)
      .join("")
      .trim();
    return {
      userMsg,
      assistantMsg,
      turn: projectTurn(question, assistantMsg, {
        id: userMsg.id,
        initialMode: (userMsg.metadata as { mode?: "ask" | "investigate" } | undefined)?.mode ?? "ask",
        streaming: last ? opts.streaming : false,
        transportError: last ? opts.transportError : null,
        timing: opts.timingFor?.(userMsg.id),
      }),
    };
  });
}

/**
 * Project one turn from its question and its assistant `UIMessage`.
 *
 * Pure: same inputs, same turn. `message` may be undefined (the send is in
 * flight and no assistant message exists yet) — that projects as a loading turn,
 * which is what it is.
 */
/**
 * The `delegate` stamp a sub-agent's frames carry, or null for the turn's own work.
 *
 * Read defensively: this crosses the wire, and a half-formed stamp that produced a hop
 * with no name would render an anonymous agent — worse than not rendering the hop,
 * because it looks like the product does not know who ran the query. No id, no hop.
 */
function delegationOf(d: Payload): Omit<DelegatedHop, "frames" | "work"> | null {
  const raw = d?.delegate as Record<string, unknown> | undefined;
  const agentId = typeof raw?.sub_agent_id === "string" ? raw.sub_agent_id : "";
  if (!agentId) return null;
  const path = typeof raw?.agent_path === "string" && raw.agent_path ? raw.agent_path : agentId;
  return {
    agentId,
    agentName: (typeof raw?.sub_agent_name === "string" && raw.sub_agent_name) || agentId,
    parentAgentId: typeof raw?.parent_agent_id === "string" ? raw.parent_agent_id : "",
    agentPath: path,
    depth: Number(raw?.depth ?? path.split("/").length) || 1,
  };
}

function seedHop(hops: Map<string, DelegatedHop>,
                 info: Omit<DelegatedHop, "frames" | "work">): DelegatedHop {
  const hop: DelegatedHop = {
    ...info,
    frames: [],
    // A real turn shape, so the hop's work is readable by every organ that already
    // speaks `ChatTurn` — the SQL panel, the receipt list, the table.
    work: { ...EMPTY_TURN, id: `${info.agentPath}`, question: "", mode: "ask" },
  };
  hops.set(info.agentPath, hop);
  return hop;
}

export function projectTurn(
  question: string,
  message: AughorUIMessage | undefined,
  opts: ProjectTurnOptions = {},
): ChatTurn {
  const t: ChatTurn = {
    ...EMPTY_TURN,
    id: opts.id ?? message?.id ?? "pending",
    question,
    mode: opts.initialMode ?? "ask",
    startedAt: opts.timing?.startedAt ?? 0,
    elapsedMs: opts.timing?.elapsedMs ?? null,
  };

  // The latest full text per channel. Each adapter channel grows ONE part (a
  // re-synthesis opens a fresh block), so the channel's last part IS its current
  // whole text — the replace semantics the `*_delta` frames had on the wire.
  const channelText = new Map<string, string>();

  // VA-2 — one scratch turn per delegated hop, keyed by `agent_path` (the same value
  // the runtime refuses cycles on, so the tree drawn here and the tree refused there
  // cannot disagree). Insertion order is first-seen order, which is hop order.
  const hops = new Map<string, DelegatedHop>();

  for (const part of message?.parts ?? []) {
    if (part.type === "text") {
      channelText.set(textChannel(part), part.text);
      continue;
    }
    if (!part.type.startsWith("data-")) continue; // SDK parts render as fallbacks
    const name = part.type.slice("data-".length);
    const project = PART_PROJECTORS[name];
    const data = (part as { data: unknown }).data as Payload;

    // A frame a DELEGATE produced belongs to that delegate, not to this turn. Routed
    // before the turn's projector runs rather than after: `sql` and friends replace
    // rather than accumulate, so letting one through and correcting it afterwards
    // would still have overwritten the supervisor's own value.
    const hop = delegationOf(data);
    if (hop) {
      const into = hops.get(hop.agentPath) ?? seedHop(hops, hop);
      into.frames.push(name);
      if (project) project(into.work, data);
      continue;
    }

    if (project) project(t, data);
  }

  t.delegations = [...hops.values()];

  const headlineText = channelText.get("headline") ?? "";
  const narrativeText = channelText.get("narrative") ?? "";
  const reportText = channelText.get("report") ?? "";

  if (opts.streaming) {
    // Streams render only until their settled value lands — the projectors above
    // already nulled the stream when it did.
    if (t.headline == null && headlineText) t.headlineStream = headlineText;
    if (t.narrative == null && narrativeText) t.narrativeStream = narrativeText;
    if (t.deepReport == null && reportText) t.reportStream = reportText;
  } else if (!t.headline && headlineText) {
    // Terminal safety net: a settled headline whose data part never arrived
    // (a dropped tail) still shows the words the user watched stream in.
    t.headline = headlineText;
  }

  // Lifecycle. An `error` part already set status terminally; a transport-level
  // failure ranks the same; otherwise the SDK's streaming state decides.
  if (t.status !== "error") {
    if (opts.transportError) {
      t.status = "error";
      t.error = opts.transportError;
    } else {
      t.status = opts.streaming ? "loading" : "done";
    }
  }

  return t;
}
