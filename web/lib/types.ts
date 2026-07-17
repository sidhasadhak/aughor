export type Verdict = "confirmed" | "refuted" | "inconclusive" | "untested";

export interface Hypothesis {
  id: string;
  description: string;
  confidence: number;
  verdict: Verdict;
  key_finding: string;
}

export interface StatResult {
  type: "anomaly" | "trend" | "comparison" | "distribution";
  interpretation: string;
  is_significant: boolean;
  sigma: number | null;
  p_value: number | null;
}

export interface QuerySummary {
  sql: string;
  row_count: number;
  error: string | null;
  stats: StatResult[];
}

export interface Finding {
  claim: string;
  evidence: string;
  confidence: number;
  hypothesis_id: string | null;
}

export interface DataQualityNote {
  table: string;
  column: string | null;
  issue: string;
  impact: string;
  recommended_fix: string;
}

export interface Report {
  headline: string;
  verdict: string;
  key_findings: Finding[];
  what_is_not_the_cause: string[];
  data_quality_notes: DataQualityNote[];
  risks: string[];
  recommended_actions: string[];
}

export interface QueryCitation {
  hypothesis_id: string;
  sql: string;
  row_count: number;
  error: string | null;
  columns?: string[];
  rows?: unknown[][];
  stats?: StatResult[];
}

export interface EvidenceScore {
  hypothesis_id: string;
  confidence: number;
  verdict: Verdict;
  key_finding: string;
  should_continue: boolean;
}

// ── Explore mode types ───────────────────────────────────────────────────────

export type SubQuestionPurpose = "landscape" | "relationship" | "threshold" | "drill_down" | "confounder" | "synthesis";

export interface SubQuestion {
  id: string;
  question: string;
  depends_on: string[];
  purpose: SubQuestionPurpose;
  expected_output: string;
  done: boolean;
  answer: string | null;
  refinement: string | null;
}

export interface SubQuestionAnswer {
  subq_id: string;
  question: string;
  purpose: SubQuestionPurpose;
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  error: string | null;
  answer: string;
  insight: string;
  refinement: string | null;
}

export interface VerificationCheck {
  name: string;
  label: string;
  status: "ran" | "not_run" | "n/a";
  detail?: string | null;
}

export interface VerificationManifest {
  checks: VerificationCheck[];
  coverage: number;
  earned_confidence: number;   // 0-1, computed (not asserted)
  confidence_band: "high" | "medium" | "low";
  data_trust: number;          // 0-1
  signals: string[];           // why the score is what it is
}

export interface ExplorationReport {
  headline: string;
  conclusion: string;
  narrative: string;
  recommended_actions: string[];
  data_quality_notes: DataQualityNote[];
  verification?: VerificationManifest | null;   // Bet 0 — which guards ran + earned trust
}

// ── Overview mode types ──────────────────────────────────────────────────────
// "Show me interesting facts about this schema" — a deterministic, notability-ranked
// TOUR of diverse fact TYPES across the whole dataset (the Genie-style default
// first-look). Mirrors aughor/overview/build.py exactly: OverviewReport → OverviewFact[].

export type OverviewLens =
  | "scale" | "concentration" | "outlier" | "distribution"
  | "composition" | "coverage" | "relationship";

export interface OverviewFact {
  lens: OverviewLens;
  headline: string;
  stat: string;               // pre-rendered primary number ("95.3%" / "51.2×" / "273.9K")
  stat_label: string;
  why: string;                // one-sentence "why it's notable"
  notability: number;         // 0..1
  table: string;              // may be schema-qualified ("main.tickets")
  measure: string | null;
  dimension: string | null;
  sql: string;                // exact probe SQL ("" for pure-profile facts like scale)
  columns: string[];          // e.g. ["group", "value"]  (may be [])
  rows: unknown[][];          // small (<=12), e.g. [["economy", 3571], …]  (may be [])
  chart_type: "bar" | "line" | "none";
  chart_config: Record<string, unknown> | null;   // {type,x_field,y_field,title}
}

export interface OverviewReport {
  facts: OverviewFact[];
  summary: string;            // "8 notable facts across 12 of 17 tables — …"
  tables_seen: number;
  tables_total: number;
  generated_at: string;
}

// ── ADA types ────────────────────────────────────────────────────────────────

export interface PhaseKeyNumber {
  label: string;
  value: string;
  delta?: string;
  context?: string;
}

export interface InvestigationFinding {
  finding_id: string;
  title: string;
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  error?: string;
  interpretation: string;
  key_numbers: PhaseKeyNumber[];
  chart_type: string;
  stat_note?: string;
  is_significant: boolean;
  trust_caveat?: string;
  /** Authoritative per-column display unit from the backend ({"metric_total": "percent"}). */
  column_units?: Record<string, string>;
  /** Chart-grammar exhibit spec (flag chart.exhibit_grammar) — semantic color / ref lines /
   *  point labels. Absent → legacy rendering. */
  exhibit?: import("@/components/charts/exhibit").ExhibitSpec;
}

export interface InvestigationPhase {
  phase_id: string;
  phase_name: string;
  phase_icon: string;
  status: "complete" | "partial" | "running" | "skipped" | "error";
  summary: string;
  findings: InvestigationFinding[];
  skipped_reason?: string;
}

export interface WaterfallEntry {
  cause: string;
  amount_label: string;
  pct_of_total: number;
  controllable: boolean;
  structural: boolean;
}

export interface AnswerRecommendation {
  action: string;
  expected_impact: string;
  owner: string;
  timeline: string;
}

/** @deprecated Use {@link AnswerRecommendation}. Kept one release for the `ADA`→answer rename (REC-U9). */
export type ADARecommendation = AnswerRecommendation;

export interface AnswerReport {
  headline: string;
  executive_summary: string;
  metric: string;
  observation_period: string;
  comparison_basis: string;
  total_change_label: string;
  phases: InvestigationPhase[];
  attribution_waterfall: WaterfallEntry[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
  confidence_justification: string;
  recommendations: AnswerRecommendation[];
  data_gaps: string[];
  // Phase-2 structural trust artifacts (Orchestrator) — optional; older reports omit them.
  contradiction_report?: {
    severity: string; count: number;
    items: { kind: string; detail: string; phases: string[]; severity: string }[];
  } | null;
  orchestration_plan?: {
    question_kind: string; planned_ids: string[];
    steps: { phase_id: string; phase_name: string; icon: string; disposition: string; reason: string }[];
  } | null;
  plan_reconciliation?: { planned: string[]; actual: string[]; skipped: string[]; unplanned: string[] } | null;
  // T4-1 — plain-language receipt of how the metric was computed (formula + interpretation).
  metric_definition?: string | null;
}

/** @deprecated Use {@link AnswerReport}. Kept one release for the `ADA`→answer rename (REC-U9). */
export type ADAReport = AnswerReport;

// SSE event shapes
export type InvestigationEvent =
  | { type: "start"; question: string; investigation_id?: string }
  | { type: "mode"; query_mode: "direct" | "investigate" | "explore"; route_reasoning?: string; route_confidence?: number }
  | { type: "hypotheses"; hypotheses: Hypothesis[] }
  | { type: "queries_executed"; iteration: number; hypothesis_idx: number; subq_id?: string; queries: QuerySummary[]; corrections: { fix_explanation: string; data_quality_issue: string | null }[]; stats: StatResult[] }
  | { type: "score"; iteration: number; score: { hypothesis_id: string; confidence: number; verdict: Verdict; key_finding: string }; hypotheses: Hypothesis[] }
  | { type: "report"; report: Report; hypotheses: Hypothesis[]; query_count: number; query_history: QueryCitation[]; investigation_id: string; from_cache?: boolean; cached_question?: string; cache_score?: number; query_mode?: "direct" | "investigate" | null }
  | { type: "explore_plan"; sub_questions: SubQuestion[] }
  | { type: "subq_answer"; subq_id: string; question: string; purpose: SubQuestionPurpose; answer: string; insight: string; refinement: string | null; sql: string; columns: string[]; rows: unknown[][]; row_count: number; error: string | null }
  | { type: "explore_report"; explore_report: ExplorationReport; sub_questions: SubQuestion[]; subq_answers: SubQuestionAnswer[]; query_count: number; investigation_id: string; query_mode: "explore" }
  | { type: "paused"; investigation_id: string; hypotheses: Hypothesis[]; scores: EvidenceScore[] }
  | { type: "phase_complete"; phase: InvestigationPhase; all_phases: InvestigationPhase[] }
  | { type: "phase_progress"; phase_id: string; done: number; total: number; current?: string }
  | { type: "clarify_pending"; investigation_id: string; subject: string; metric_label: string; question: string; options: string[]; previews: string[] }
  | { type: "answer_report"; answer_report: AnswerReport; investigation_id: string; query_mode: "investigate"; mode?: "investigate" }
  /** @deprecated wire alias for `answer_report`, kept one release (REC-U9). */
  | { type: "ada_report"; ada_report: AnswerReport; investigation_id: string; query_mode: "investigate" }
  | { type: "error"; message: string }
  | { type: "done" };

export interface InvestigationSummary {
  id: string;
  question: string;
  connection_id: string;
  started_at: string;
  completed_at: string | null;
  status: "running" | "complete" | "timed_out" | "failed";
  hypothesis_count: number;
  query_count: number;
  headline: string | null;
  kind: "investigation" | "chat";
}

export interface InvestigationState {
  status: "idle" | "running" | "paused" | "done" | "error";
  question: string;
  investigationId: string | null;
  hypotheses: Hypothesis[];
  queriesExecuted: number;
  currentIteration: number;
  log: string[];
  report: Report | null;
  queryHistory: QueryCitation[];
  error: string | null;
  statsPerHypothesis: Record<number, StatResult[]>;
  fromCache: boolean;
  cachedQuestion: string | null;
  humanFeedback: string | null;
  queryMode: "direct" | "investigate" | "explore" | null;
  routeReasoning: string | null;
  routeConfidence: number | null;
  // Explore mode
  subQuestions: SubQuestion[];
  subqAnswers: SubQuestionAnswer[];
  exploreReport: ExplorationReport | null;
  // ADA investigate mode
  investigationPhases: InvestigationPhase[];
  adaReport: AnswerReport | null;
}
