"use client";

/**
 * A Question on a dashboard (PENDING 54; design-mockups/dashboard-questions.html, approved 2026-10-23): a question the
 * agent answers on its rhythm, shown as the Data Canvas shows an answer — its headline, figures, summary, why, what it
 * could not see, its confidence and the period it read — with every earlier answer beside it.
 *
 * Opening it NEVER asks: it reads the answers kept (`GET /dashboards/questions/{id}`). Asking costs a full agent run, so
 * the cost is said beside every answer and "Ask again now" asks once more before it spends.
 */
import { useState, type CSSProperties } from "react";

import { Chip, Label, MUTED, NUM, ROW } from "@/components/clarity/kit";
import { Gate, useLoad } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { askQuestionNow, readQuestion, type DashboardQuestion, type QuestionAnswer, type RunCostEstimate } from "@/lib/api";
import { utcDayWords } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { requestTab } from "@/lib/navigate";

const SERIF = "var(--font-serif)";
const RULE = "1px solid var(--b1)";
/** How many earlier answers show before "Show all". */
const SHOWN = 4;
const RUNS_A_MONTH: Record<string, string> = {
  daily: "about 30 runs a month", weekly: "about 4 runs a month", monthly: "1 run a month", ask: "a run each time it is asked",
};

const whenWords = utcDayWords;

/** What an answer costs here, from this install's own metered runs — never a guess; an unpriced model is said so. */
export function costWords(cost: RunCostEstimate | null | undefined, rhythm: string): string {
  const each = cost?.n && cost.minutes != null ? `about ${Math.max(1, Math.round(cost.minutes))} min on this install`
    : "not yet metered on this install";
  const usd = cost?.usd_floor != null ? `, at least $${cost.usd_floor.toFixed(2)}` : cost?.unpriced_calls ? ", its model unpriced" : "";
  const month = RUNS_A_MONTH[rhythm];
  return `Each answer is a full agent run — ${each}${usd}${month ? ` · ${month}` : ""}`;
}

function verdictChip(verdict: string, status: string) {
  if (status === "running") return <Chip tone="violet">asking now</Chip>;
  if (verdict === "contradicted") return <Chip tone="down" title="A later reading of the same period disagreed with it">contradicted</Chip>;
  if (verdict === "answered") return <Chip tone="up">answered</Chip>;
  if (status && status !== "complete") return <Chip tone="amber" title={`The run ended ${status.replace(/_/g, " ")}`}>no answer</Chip>;
  return null;
}

function Why({ why }: { why: QuestionAnswer["why"] }) {
  if (why.drivers.length) {
    const most = Math.max(...why.drivers.map(d => Math.abs(d.share ?? 0)), 1);
    return (
      <div data-testid="question-why-drivers" style={{ display: "grid", gridTemplateColumns: "minmax(140px, auto) minmax(0, 1fr) auto",
        gap: "6px 12px", alignItems: "center", maxWidth: 640 }}>
        {withUniqueKeys(why.drivers, d => d.cause).map(([k, d]) => (
          <span key={k} style={{ display: "contents" }}>
            <span className="aug-fs-sm">{d.cause}</span>
            <span aria-hidden style={{ height: 10, borderRadius: 5, background: "var(--bg-3)", overflow: "hidden" }}>
              <i style={{ display: "block", height: "100%", width: `${(Math.abs(d.share ?? 0) / most) * 100}%`, borderRadius: 5,
                background: "var(--chart-1)" }} />
            </span>
            <span className="aug-fs-sm" style={{ ...NUM, textAlign: "right" }}>{d.amount}</span>
          </span>
        ))}
      </div>
    );
  }
  if (!why.lines.length) return <p className="aug-fs-sm" style={{ ...MUTED, margin: 0 }}>This answer broke nothing down.</p>;
  return (
    <ul data-testid="question-why-lines" className="aug-fs-sm" style={{ margin: 0, paddingLeft: 18, color: "var(--t2)", lineHeight: 1.6, maxWidth: "78ch" }}>
      {withUniqueKeys(why.lines, l => l).map(([k, l]) => <li key={k}>{l}</li>)}
    </ul>
  );
}

const SEC: CSSProperties = { margin: "14px 0 6px" };

function Answer({ a }: { a: QuestionAnswer }) {
  return (
    <div data-testid="question-answer">
      <h3 className="aug-fs-h1" style={{ fontFamily: SERIF, lineHeight: 1.25, fontWeight: 600, margin: "10px 0 4px", maxWidth: "52ch" }}>{a.headline}</h3>
      <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 12 }} data-testid="question-dated">
        {`Answered ${whenWords(a.answered_at, true)}`}{a.period ? `, for ${a.period}` : ""}{a.against ? ` against ${a.against}` : ""}.
      </div>
      {a.figures.length > 0 && (
        <div data-testid="question-figures" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10, marginBottom: 14 }}>
          {withUniqueKeys(a.figures, f => f.label).map(([k, f]) => (
            <div key={k} style={{ border: RULE, borderRadius: "var(--r2)", padding: "8px 10px", minWidth: 0 }}>
              <div className="aug-fs-xs" style={MUTED}>{f.label}</div>
              <div className="aug-fs-h1" style={{ fontWeight: 600, margin: "2px 0", ...NUM }}>{f.value}</div>
              {f.note && <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>{f.note}</div>}
            </div>
          ))}
        </div>
      )}
      {a.summary && <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t2)", lineHeight: 1.6, maxWidth: "78ch" }}>{a.summary}</p>}
      <div style={SEC}><Label>Why</Label></div>
      <Why why={a.why} />
      {a.gaps && (
        <>
          <div style={SEC}><Label tone="amber">What it couldn&apos;t see</Label></div>
          <div className="aug-fs-sm" data-testid="question-gaps" style={{ borderLeft: "2px solid var(--amb4)", padding: "2px 0 2px 10px",
            color: "var(--t2)", maxWidth: "78ch" }}>{a.gaps}</div>
        </>
      )}
    </div>
  );
}

function Earlier({ q }: { q: DashboardQuestion }) {
  const [all, setAll] = useState(false);
  const rows = q.answers.filter(a => a.id !== q.latest?.id);
  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <div data-testid="question-earlier" style={{ marginTop: 14, borderTop: RULE, paddingTop: 10 }}>
      <Label>Earlier answers</Label>
      {shown.map(a => (
        <div key={a.id} style={{ padding: "6px 0", borderTop: RULE }}>
          <div className="aug-fs-xs" style={{ ...ROW, ...MUTED, gap: 6 }}>
            <span>{whenWords(a.asked_at)}</span>{verdictChip(a.verdict, a.status)}
          </div>
          <Button variant="link" size="xs" onClick={() => requestTab("chat", { run: a.id })} title="Open this answer in the Data Canvas"
            style={{ padding: 0, height: "auto", color: "var(--t2)", whiteSpace: "normal", textAlign: "left" }}>
            <span className="aug-fs-sm">{a.headline || "No headline — open it to read the run"}</span>
          </Button>
        </div>
      ))}
      {rows.length > SHOWN && (
        <Button variant="ghost" size="xs" onClick={() => setAll(v => !v)}>{all ? "Show fewer" : `Show all ${rows.length}`}</Button>
      )}
    </div>
  );
}

export function QuestionPiece({ automation, first }: { automation: string; first?: string }) {
  const load = useLoad(() => readQuestion(automation, first), [automation, first]);
  const [confirming, setConfirming] = useState(false);
  const [asked, setAsked] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const ask = async (q: DashboardQuestion) => {
    setAsking(true);
    try {
      const out = await askQuestionNow(q.automation_id);
      setAsked(out.asked ? "Asked. The answer is kept here when the run finishes — open the page again to read it."
        : `Not asked: ${out.reason || out.message || "the run was refused"}.`);
    } catch (e) {
      setAsked(`Not asked: ${(e as Error).message}`);
    } finally {
      setAsking(false);
      setConfirming(false);
    }
  };

  return (
    <div data-testid="question-piece" style={{ padding: "12px 14px" }}>
      <Gate load={load} what="the question">
        {q => (
          <>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <span aria-hidden className="aug-fs-xs" style={{ fontWeight: 600, color: "var(--vio4)", background: "var(--vio1)",
                borderRadius: 5, padding: "1px 6px", marginTop: 2 }}>Q</span>
              <span className="aug-fs-sm" data-testid="question-text" style={{ flex: 1, color: "var(--t2)", minWidth: 0 }}>{q.question}</span>
              <span style={{ ...ROW, gap: 6, justifyContent: "flex-end" }}>
                <Chip tone="violet">{q.rhythm_words}</Chip>
                {q.latest?.confidence && <Chip>{`confidence ${q.latest.confidence.toLowerCase()}`}</Chip>}
                {q.running && <Chip tone="violet">asking now</Chip>}
              </span>
            </div>
            {q.latest ? <Answer a={q.latest} /> : (
              <p className="aug-fs-sm" data-testid="question-waiting" style={{ margin: "12px 0 4px", color: "var(--t2)" }}>
                {q.next_at ? <>No answer yet. The first comes <b>{whenWords(q.next_at, true)}</b>, for the last complete period
                  against the one before.</> : "No answer yet. It is asked only when you ask."}
              </p>
            )}
            <Earlier q={q} />
            <div style={{ ...ROW, marginTop: 14, paddingTop: 10, borderTop: RULE }}>
              {q.latest && (
                <Button size="xs" variant="secondary" onClick={() => requestTab("chat", { run: q.latest!.id })}>Open in Data Canvas</Button>
              )}
              {confirming ? (
                <>
                  <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>This asks the agent now — a full run.</span>
                  <Button size="xs" variant="default" disabled={asking} data-testid="question-ask-confirm" onClick={() => void ask(q)}>
                    {asking ? "Asking…" : "Ask"}</Button>
                  <Button size="xs" variant="ghost" disabled={asking} onClick={() => setConfirming(false)}>Cancel</Button>
                </>
              ) : (
                <Button size="xs" variant="ghost" data-testid="question-ask" onClick={() => setConfirming(true)}>
                  {q.latest ? "Ask again now" : "Ask now"}</Button>
              )}
              <span className="aug-fs-xs" data-testid="question-cost" style={{ ...MUTED, marginLeft: "auto" }}>{costWords(q.cost, q.rhythm)}</span>
            </div>
            {asked && <div className="aug-fs-xs" data-testid="question-asked" style={{ marginTop: 6, color: "var(--t2)" }}>{asked}</div>}
          </>
        )}
      </Gate>
    </div>
  );
}
