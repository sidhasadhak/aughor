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
}

export interface EvidenceScore {
  hypothesis_id: string;
  confidence: number;
  verdict: Verdict;
  key_finding: string;
  should_continue: boolean;
}

// SSE event shapes
export type InvestigationEvent =
  | { type: "start"; question: string; investigation_id?: string }
  | { type: "mode"; query_mode: "direct" | "investigate" }
  | { type: "hypotheses"; hypotheses: Hypothesis[] }
  | { type: "queries_executed"; iteration: number; hypothesis_idx: number; queries: QuerySummary[]; corrections: { fix_explanation: string; data_quality_issue: string | null }[]; stats: StatResult[] }
  | { type: "score"; iteration: number; score: { hypothesis_id: string; confidence: number; verdict: Verdict; key_finding: string }; hypotheses: Hypothesis[] }
  | { type: "report"; report: Report; hypotheses: Hypothesis[]; query_count: number; query_history: QueryCitation[]; investigation_id: string; from_cache?: boolean; cached_question?: string; cache_score?: number; query_mode?: "direct" | "investigate" | null }
  | { type: "paused"; investigation_id: string; hypotheses: Hypothesis[]; scores: EvidenceScore[] }
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
  queryMode: "direct" | "investigate" | null;
}
