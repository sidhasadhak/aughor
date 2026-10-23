"use client";

/**
 * Keeping a question on a dashboard (PENDING 54; design-mockups/dashboard-questions.html, screen 2, approved
 * 2026-10-23): its words, how often the agent asks it — Weekly by default — and what each answer costs on this install,
 * said before anything is kept. Nothing is asked here: the first answer comes on the rhythm, or is the Data Canvas
 * answer it is kept from. Used by a dashboard's "+ Question" and the Data Canvas's "Keep on a dashboard".
 */
import { useEffect, useState } from "react";

import { costWords } from "@/components/dashboards/QuestionPiece";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Textarea } from "@/components/ui/textarea";
import { keepQuestion, readQuestionCost, type QuestionRhythm, type RunCostEstimate } from "@/lib/api";

export const MAX_QUESTION = 500;

const RHYTHMS: { value: QuestionRhythm; label: string }[] = [
  { value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" }, { value: "ask", label: "Only when I ask" },
];
/** What each rhythm reads, in words — the period is written into the question by code, each time. */
export const RHYTHM_PERIOD: Record<QuestionRhythm, string> = {
  daily: "Every day at 09:00 UTC, for the newest settled day against the day before.",
  weekly: "Mondays at 09:00 UTC, for the last complete week against the week before.",
  monthly: "The 1st of each month at 09:00 UTC, for the last complete month against the month before.",
  ask: "Only when you ask — nothing runs on its own.",
};

export function QuestionComposer({ connectionId, schema, question = "", firstRun, from, busy = false, onKept, onClose }: {
  connectionId: string;
  schema?: string;
  /** The words it starts with — a Data Canvas answer's question, when it is kept from one. */
  question?: string;
  /** The Data Canvas answer it is kept from: its first answer. */
  firstRun?: string;
  /** Where it comes from, said above the words. */
  from?: string;
  busy?: boolean;
  onKept: (automationId: string, first: string, rhythm: QuestionRhythm) => void;
  onClose: () => void;
}) {
  const [words, setWords] = useState(question);
  const [rhythm, setRhythm] = useState<QuestionRhythm>("weekly");
  const [cost, setCost] = useState<RunCostEstimate | null>(null);
  const [keeping, setKeeping] = useState(false);
  const [refused, setRefused] = useState("");
  useEffect(() => {
    let alive = true;
    readQuestionCost(connectionId).then(c => { if (alive) setCost(c); }).catch(() => { if (alive) setCost(null); });
    return () => { alive = false; };
  }, [connectionId]);

  const keep = async () => {
    setKeeping(true); setRefused("");
    try {
      const out = await keepQuestion(connectionId, { question: words.trim(), rhythm, schema_name: schema || undefined,
        first_run: firstRun || undefined });
      onKept(out.automation_id, out.first, out.rhythm);
    } catch (e) {
      setRefused((e as Error).message);
    } finally { setKeeping(false); }
  };

  return (
    <div data-testid="question-composer" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: 14, marginBottom: 16,
      display: "flex", flexDirection: "column", gap: 10 }}>
      {from && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{from}</div>}
      <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
        A question the agent answers the way the Data Canvas does — figures, summary, why — kept here with every answer it gives.
        Opening the dashboard never asks it.
      </div>
      <Textarea aria-label="The question" placeholder="How did sales change week over week, and why?" value={words} maxLength={MAX_QUESTION}
        autoFocus disabled={busy || keeping} onChange={e => setWords(e.target.value)} style={{ minHeight: 64 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>Answer it</span>
        <Segmented label="How often the agent answers it" value={rhythm} onChange={setRhythm} options={RHYTHMS} disabled={busy || keeping} />
        <span className="aug-fs-xs" data-testid="question-period" style={{ color: "var(--t2)" }}>{RHYTHM_PERIOD[rhythm]}</span>
      </div>
      <div className="aug-fs-xs" data-testid="question-composer-cost" style={{ padding: "8px 10px", borderRadius: "var(--r2)",
        background: "var(--bg-3)", color: "var(--t2)" }}>
        {costWords(cost, rhythm)}{firstRun ? ". The answer it is kept from is its first." : "."}
      </div>
      {refused && <div className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{refused}</div>}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button size="sm" data-testid="question-keep" disabled={busy || keeping || !words.trim()} onClick={() => void keep()}>
          {keeping ? "Keeping…" : "Keep the question"}</Button>
        <Button size="sm" variant="ghost" disabled={keeping} onClick={onClose}>Cancel</Button>
        <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>
          {words.length} / {MAX_QUESTION}</span>
      </div>
    </div>
  );
}
