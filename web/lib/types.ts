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

export interface ExplorationReport {
  headline: string;
  conclusion: string;
  narrative: string;
  recommended_actions: string[];
  data_quality_notes: DataQualityNote[];
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

export interface ADARecommendation {
  action: string;
  expected_impact: string;
  owner: string;
  timeline: string;
}

export interface ADAReport {
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
  recommendations: ADARecommendation[];
  data_gaps: string[];
}

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
  | { type: "ada_report"; ada_report: ADAReport; investigation_id: string; query_mode: "investigate" }
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
  adaReport: ADAReport | null;
}
