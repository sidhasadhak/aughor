"use client";

import { useEffect, useRef, useState } from "react";
import AtlasSendIcon from "@atlaskit/icon/core/send";
import CommentIcon   from "@atlaskit/icon/core/comment";
import AiSparkleIcon from "@atlaskit/icon/core/ai-sparkle";
import { Separator } from "@/components/ui/separator";
import { ReportView } from "@/components/ReportView";
import { InvestigationReportView } from "@/components/InvestigationReport";
import { ExplorationReportView } from "@/components/ExplorationReport";
import type { Hypothesis, QueryCitation, Report, ADAReport, ExplorationReport, SubQuestion, SubQuestionAnswer } from "@/lib/types";
import { API_BASE } from "@/lib/config";
import { localizeCurrency } from "@/lib/orgSettings";
import { getEvidenceClaims, submitClaimFeedback, type EvidenceClaim } from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";

interface FullInvestigation {
  id: string;
  question: string;
  connection_id: string;
  started_at: string;
  completed_at: string | null;
  hypotheses: Hypothesis[] | null;
  report: Report | null;
  query_history: QueryCitation[] | null;
}

interface Props {
  invId: string | null;
  onContinue?: (question: string, mode: "ask" | "investigate") => void;
}

export function HistoryDetailPanel({ invId, onContinue }: Props) {
  const [inv, setInv] = useState<FullInvestigation | null>(null);
  const [loading, setLoading] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [mode, setMode] = useState<"ask" | "investigate">("investigate");
  const [activeTab, setActiveTab] = useState<"report" | "evidence">("report");
  const [evidence, setEvidence] = useState<EvidenceClaim[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [feedbackPending, setFeedbackPending] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!invId) { setInv(null); setEvidence([]); setActiveTab("report"); return; }
    setLoading(true);
    fetch(`${API_BASE}/investigations/${invId}`)
      .then(r => r.json())
      .then(setInv)
      .catch(() => setInv(null))
      .finally(() => setLoading(false));
  }, [invId]);

  // Fetch evidence claims when Evidence tab is first opened
  useEffect(() => {
    if (activeTab !== "evidence" || !invId) return;
    setEvidenceLoading(true);
    getEvidenceClaims(invId)
      .then(setEvidence)
      .catch(() => setEvidence([]))
      .finally(() => setEvidenceLoading(false));
  }, [activeTab, invId]);

  const handleFeedback = async (
    claimId: string,
    feedback: "validated" | "disputed" | "needs_context",
  ) => {
    if (!invId) return;
    setFeedbackPending(claimId);
    try {
      const updated = await submitClaimFeedback(invId, claimId, feedback);
      setEvidence(prev => prev.map(c => c.id === claimId ? updated : c));
    } catch {
      // noop — feedback is best-effort
    } finally {
      setFeedbackPending(null);
    }
  };

  if (!invId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
        <p className="text-2xl font-semibold text-zinc-500">Select an investigation</p>
        <p className="text-sm text-zinc-500 max-w-xs">
          Click any item on the left to view its full results.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex gap-1">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (!inv) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-zinc-500">
        Failed to load investigation.
      </div>
    );
  }

  const hypotheses = inv.hypotheses ?? [];
  const queryHistory = inv.query_history ?? [];

  // Detect report type via stored marker or field-sniffing
  const reportRaw = inv.report as (Record<string, unknown> & { _report_type?: string }) | null;
  const reportType: "investigate" | "explore" | "direct" | "legacy" = (() => {
    if (!reportRaw) return "legacy";
    if (reportRaw._report_type === "investigate" || reportRaw.executive_summary !== undefined) return "investigate";
    if (reportRaw._report_type === "explore" || reportRaw.narrative !== undefined) return "explore";
    if (hypotheses.length === 1 && (hypotheses[0] as Hypothesis & { id?: string })?.id === "direct") return "direct";
    return "legacy";
  })();

  const handleContinue = () => {
    const q = followUp.trim();
    if (!q || !onContinue) return;
    onContinue(q, mode);
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }}>

      {/* ── Tab bar: Report / Evidence ── */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--b1)", flexShrink: 0 }}>
        {(["report", "evidence"] as const).map(t => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            style={{
              padding: "8px 16px", fontSize: 12, fontWeight: 500, cursor: "pointer",
              background: "none", border: "none", borderBottom: `2px solid ${activeTab === t ? "var(--blue3)" : "transparent"}`,
              marginBottom: -1,
              color: activeTab === t ? "var(--t1)" : "var(--t3)",
              transition: "all .1s",
            }}
          >
            {t === "report" ? "Report" : `Evidence${evidence.length > 0 ? ` (${evidence.length})` : ""}`}
          </button>
        ))}
      </div>

      {/* ── Evidence panel ── */}
      {activeTab === "evidence" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
          {evidenceLoading && (
            <div style={{ display: "flex", justifyContent: "center", padding: "32px 0" }}>
              <div style={{ display: "flex", gap: 4 }}>
                {[0, 1, 2].map(i => (
                  <span key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--b3)", display: "inline-block", animation: "aug-blink 1.4s ease-in-out infinite", animationDelay: `${i * 150}ms` }} />
                ))}
              </div>
            </div>
          )}

          {!evidenceLoading && evidence.length === 0 && (
            <div style={{ padding: "40px 0", textAlign: "center" }}>
              <p style={{ fontSize: 13, color: "var(--t3)", marginBottom: 6 }}>No evidence claims yet.</p>
              <p style={{ fontSize: 11, color: "var(--t4)", lineHeight: 1.5 }}>
                Claims are extracted automatically when an ADA investigation completes.
              </p>
            </div>
          )}

          {!evidenceLoading && evidence.map(claim => (
            <EvidenceClaimCard
              key={claim.id}
              claim={claim}
              feedbackPending={feedbackPending === claim.id}
              onFeedback={handleFeedback}
            />
          ))}
        </div>
      )}

      {/* ── Report panel ── */}
      {activeTab === "report" && (
    <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
      {/* Scrollable report */}
      <div style={{ position: "absolute", inset: 0, overflowY: "auto" }}>
        <div style={{ width: "90%", margin: "0 auto", padding: "32px 0", display: "flex", flexDirection: "column", gap: 28 }}>
          {/* Question */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <p className="text-xs uppercase tracking-wide" style={{ color: "var(--t3)" }}>Question</p>
                {(reportType === "investigate" || reportType === "explore") && (
                <span style={{ fontSize: 11, color: "var(--vio5)", border: "1px solid var(--vio2)", background: "var(--vio1)", borderRadius: "var(--r1)", padding: "1px 8px", fontWeight: 500 }}>Agentic</span>
              )}
              {reportType === "direct" && (
                <span style={{ fontSize: 11, color: "var(--blue5)", border: "1px solid var(--blue2)", background: "var(--blue1)", borderRadius: "var(--r1)", padding: "1px 8px", fontWeight: 500 }}>Quick</span>
              )}
              {invId && reportRaw && (
                <div style={{ marginLeft: "auto" }}>
                  <ExportButton invId={invId} />
                </div>
              )}
            </div>
            <p style={{ fontSize: 15, fontWeight: 500, color: "var(--t1)", lineHeight: 1.5 }}>{localizeCurrency(inv.question)}</p>
            <p style={{ marginTop: 4, fontSize: 11, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>{inv.connection_id}</p>
          </div>

          {/* Report */}
          {reportRaw && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Separator className="bg-zinc-800" />

              {reportType === "investigate" && (
                <InvestigationReportView report={reportRaw as unknown as ADAReport} />
              )}

              {reportType === "explore" && (
                <ExplorationReportView
                  report={reportRaw as unknown as ExplorationReport}
                  subQuestions={(reportRaw.sub_questions ?? []) as SubQuestion[]}
                  subqAnswers={(reportRaw.subq_answers ?? []) as SubQuestionAnswer[]}
                  queryCount={queryHistory.length}
                />
              )}

              {(reportType === "direct" || reportType === "legacy") && (
                <>
                  <p className="text-xs uppercase tracking-wide" style={{ color: "var(--t3)" }}>
                    {reportType === "direct" ? "Query Report" : "Investigation Report"}
                  </p>
                  <ReportView
                    report={inv.report as Report}
                    queryCount={queryHistory.length}
                    queryHistory={queryHistory}
                    queryMode={reportType === "direct" ? "direct" : "investigate"}
                    hypotheses={hypotheses}
                    invId={inv.id}
                  />
                </>
              )}
            </div>
          )}

          {!reportRaw && (
            <div style={{ border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: "16px", fontSize: 13, color: "var(--t3)" }}>
              This investigation did not complete — no report available.
            </div>
          )}

          {/* Spacer so last content clears the floating input + investigative chain circle */}
          {onContinue && <div style={{ height: 240 }} />}
        </div>
      </div>

      {/* Gradient fade */}
      {onContinue && (
        <div style={{
          position: "absolute", bottom: 0, left: 0, right: 0,
          height: 260, pointerEvents: "none", zIndex: 1,
          background: "linear-gradient(to bottom, transparent 0%, #0d0e11 60%)",
        }} />
      )}

      {/* Follow-up input — floating */}
      {onContinue && (
        <div style={{
          position: "absolute", bottom: 20, left: 0, right: 0,
          zIndex: 2, pointerEvents: "none",
        }}>
          <div className="w-[90%] mx-auto space-y-2" style={{ pointerEvents: "all" }}>
            {/* InputBox replica */}
            <div
              className="rounded-md flex flex-col overflow-hidden"
              style={{
                background: "var(--bg-0)",
                border: "1px solid rgba(255,255,255,0.09)",
                boxShadow: "0 6px 20px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.04) inset",
              }}
            >
              <textarea
                ref={inputRef}
                rows={2}
                value={followUp}
                onChange={e => setFollowUp(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleContinue(); }
                }}
                placeholder="Ask anything about your data…"
                className="w-full bg-transparent text-[12px] text-zinc-100 placeholder:text-zinc-500 px-4 pt-3 pb-2 resize-none focus:outline-none"
              />
              <div className="flex items-center justify-between px-3 pb-2.5">
                {/* Mode toggle */}
                <div style={{ display: "flex", alignItems: "center", gap: 2, padding: "2px", background: "var(--bg-0)", borderRadius: "var(--r2)", border: "1px solid var(--b1)" }}>
                  <button
                    onClick={() => setMode("ask")}
                    style={{
                      display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
                      borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
                      cursor: "pointer", border: "none", transition: "all .12s",
                      background: mode === "ask" ? "var(--bg-3)" : "transparent",
                      color: mode === "ask" ? "var(--t1)" : "var(--t3)",
                      boxShadow: mode === "ask" ? "0 1px 3px rgba(0,0,0,.3)" : "none",
                    }}
                  >
                    <CommentIcon label="Quick" size="small" />
                    Quick
                  </button>
                  <button
                    onClick={() => setMode("investigate")}
                    style={{
                      display: "flex", alignItems: "center", gap: 5, padding: "3px 10px",
                      borderRadius: "var(--r1)", fontSize: 11, fontWeight: 500, fontFamily: "var(--font-ui)",
                      cursor: "pointer", border: mode === "investigate" ? "1px solid var(--vio2)" : "1px solid transparent",
                      transition: "all .12s",
                      background: mode === "investigate" ? "var(--vio1)" : "transparent",
                      color: mode === "investigate" ? "var(--vio5)" : "var(--t3)",
                      boxShadow: mode === "investigate" ? "0 1px 3px rgba(0,0,0,.3)" : "none",
                    }}
                  >
                    <AiSparkleIcon label="Agentic" size="small" />
                    Agentic
                  </button>
                </div>
                {/* Send */}
                <button
                  onClick={handleContinue}
                  disabled={!followUp.trim()}
                  title="Send"
                  className="w-7 h-7 rounded-lg text-zinc-500 flex items-center justify-center hover:text-zinc-100 disabled:opacity-25 disabled:cursor-not-allowed transition"
                >
                  <AtlasSendIcon label="Send" size="small" />
                </button>
              </div>
            </div>
            <p className="text-[12px] text-center" style={{ color: "var(--t4)" }}>Always review the accuracy of responses.</p>
          </div>
        </div>
      )}
    </div>
      )}
    </div>
  );

}

// ── EvidenceClaimCard ─────────────────────────────────────────────────────────

const FEEDBACK_STYLES = {
  validated:    { label: "Validated",     color: "var(--grn4)",  bg: "var(--grn1)",  border: "var(--grn2)" },
  disputed:     { label: "Disputed",      color: "var(--red4)",  bg: "var(--red1)",  border: "var(--red2)" },
  needs_context:{ label: "Needs context", color: "var(--amb4)",  bg: "var(--amb1)",  border: "var(--amb2)" },
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.75 ? "var(--grn3)" : value >= 0.5 ? "var(--amb3)" : "var(--red3)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: 3, background: "var(--bg-4)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2, transition: "width .3s" }} />
      </div>
      <span style={{ fontSize: 11, color: "var(--t3)", fontFamily: "var(--font-mono)", minWidth: 28 }}>{pct}%</span>
    </div>
  );
}

function EvidenceClaimCard({
  claim,
  feedbackPending,
  onFeedback,
}: {
  claim: EvidenceClaim;
  feedbackPending: boolean;
  onFeedback: (id: string, fb: "validated" | "disputed" | "needs_context") => void;
}) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const fb = claim.owner_feedback ? FEEDBACK_STYLES[claim.owner_feedback] : null;

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
      padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8,
    }}>
      {/* Claim text + feedback badge */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{
          width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginTop: 5,
          background: claim.confidence >= 0.75 ? "var(--grn3)" : claim.confidence >= 0.5 ? "var(--amb3)" : "var(--red3)",
        }} />
        <p style={{ flex: 1, fontSize: 12, color: "var(--t1)", lineHeight: 1.5 }}>
          {claim.claim_text}
        </p>
        {fb && (
          <span style={{ fontSize: 11, padding: "1px 8px", borderRadius: "var(--r1)", background: fb.bg, border: `1px solid ${fb.border}`, color: fb.color, flexShrink: 0 }}>
            {fb.label}
          </span>
        )}
      </div>

      {/* Confidence bar */}
      <ConfidenceBar value={claim.confidence} />

      {/* Meta row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {claim.hypothesis_id && (
          <span style={{ fontSize: 11, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
            phase: {claim.hypothesis_id}
          </span>
        )}
        {claim.metric_used && (
          <span style={{ fontSize: 11, padding: "1px 7px", borderRadius: "var(--r1)", background: "var(--blue1)", border: "1px solid var(--blue2)", color: "var(--blue5)" }}>
            {claim.metric_used}
          </span>
        )}
        {claim.data_freshness && (
          <span style={{ fontSize: 11, color: "var(--t4)" }}>
            data as of {new Date(claim.data_freshness).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>

      {/* SQL toggle */}
      {claim.sql_source && (
        <div>
          <button
            onClick={() => setSqlOpen(v => !v)}
            style={{ fontSize: 11, color: "var(--t3)", background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 4 }}
          >
            <span style={{ fontSize: 10, transition: "transform .15s", display: "inline-block", transform: sqlOpen ? "rotate(90deg)" : "none" }}>▶</span>
            SQL source
          </button>
          {sqlOpen && (
            <pre style={{
              marginTop: 6, fontSize: 11, fontFamily: "var(--font-code)", lineHeight: 1.6,
              background: "var(--code-bg)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
              padding: "8px 12px", overflowX: "auto", color: "var(--t2)", whiteSpace: "pre-wrap",
            }}>
              {claim.sql_source}
            </pre>
          )}
        </div>
      )}

      {/* Feedback buttons */}
      {!claim.owner_feedback && (
        <div style={{ display: "flex", gap: 6, paddingTop: 2 }}>
          {(["validated", "disputed", "needs_context"] as const).map(fb => (
            <button
              key={fb}
              onClick={() => onFeedback(claim.id, fb)}
              disabled={feedbackPending}
              style={{
                fontSize: 11, padding: "3px 10px", borderRadius: "var(--r1)", cursor: "pointer",
                background: FEEDBACK_STYLES[fb].bg, border: `1px solid ${FEEDBACK_STYLES[fb].border}`,
                color: FEEDBACK_STYLES[fb].color, transition: "opacity .1s",
                opacity: feedbackPending ? 0.4 : 1,
              }}
            >
              {FEEDBACK_STYLES[fb].label}
            </button>
          ))}
        </div>
      )}

      {/* Feedback note (if set) */}
      {claim.feedback_note && (
        <p style={{ fontSize: 11, color: "var(--t3)", fontStyle: "italic", marginTop: -2 }}>
          &ldquo;{claim.feedback_note}&rdquo;
        </p>
      )}
    </div>
  );
}
