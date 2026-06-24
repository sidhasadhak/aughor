"use client";

import { useState } from "react";
import type { Hypothesis } from "@/lib/types";

interface Props {
  investigationId: string;
  hypotheses: Hypothesis[];
  onSubmit: (feedback: string) => void;
  /** When true, renders as a post-completion validation panel rather than a HITL gate */
  postCompletion?: boolean;
}

const VERDICT_COLOR: Record<string, string> = {
  confirmed: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  refuted: "text-red-400 border-red-500/30 bg-red-500/10",
  inconclusive: "text-amber-400 border-amber-500/30 bg-amber-500/10",
  untested: "text-zinc-500 border-zinc-600 bg-zinc-800/50",
};

export function FeedbackPrompt({ investigationId, hypotheses, onSubmit, postCompletion = false }: Props) {
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = () => {
    setSubmitting(true);
    onSubmit(feedback.trim());
  };

  const handleSkip = () => {
    setSubmitting(true);
    onSubmit("");
  };

  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start gap-3">
        <span className="text-amber-400 text-base mt-0.5">⏸</span>
        <div>
          <p className="text-sm font-medium text-amber-300">
            {postCompletion ? "Validate these findings" : "Review before final report"}
          </p>
          <p className="text-xs text-zinc-500 mt-0.5">
            {postCompletion
              ? "Were these hypotheses correct? Add context to improve future investigations."
              : "The agent has tested all hypotheses. Add context or redirect before it synthesises the report."}
          </p>
        </div>
      </div>

      {/* Hypothesis verdicts */}
      <div className="space-y-2">
        {hypotheses.map((h, i) => (
          <div
            key={h.id}
            className={`rounded-lg border px-3 py-2 flex items-start gap-3 ${VERDICT_COLOR[h.verdict] ?? VERDICT_COLOR.untested}`}
          >
            <span className="text-xs font-mono shrink-0 mt-0.5">H{i + 1}</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs leading-snug text-zinc-300 truncate">{h.description}</p>
              {h.key_finding && (
                <p className="text-xs mt-0.5 opacity-70 leading-snug">{h.key_finding}</p>
              )}
            </div>
            <span className="text-xs font-medium shrink-0 capitalize">{h.verdict}</span>
          </div>
        ))}
      </div>

      {/* Feedback input */}
      <div className="space-y-2">
        <label className="text-xs text-zinc-500">
          Optional: add context, correct an interpretation, or redirect the report focus
        </label>
        <textarea
          className="w-full rounded-lg bg-zinc-800 border border-zinc-600 text-sm text-zinc-100 placeholder:text-zinc-400 p-3 resize-none focus:outline-none focus:ring-1 focus:ring-amber-500 transition"
          rows={3}
          placeholder="e.g. Focus on APAC segment, the EU numbers are expected due to the Nov promotion. Ignore H3."
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          disabled={submitting}
          onKeyDown={e => {
            if (e.key === "Enter" && e.metaKey) { e.preventDefault(); handleSubmit(); }
          }}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="flex-1 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium py-2 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {submitting ? (postCompletion ? "Submitting…" : "Generating report…") : (postCompletion ? "Submit feedback" : "Generate report →")}
        </button>
        <button
          onClick={handleSkip}
          disabled={submitting}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition disabled:opacity-50"
        >
          Skip
        </button>
      </div>
    </div>
  );
}
