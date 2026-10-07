"use client";

/**
 * Home's desk — the sections of ROADMAP §3.55 (`docs/HOME_STUDY_2026-10-06.md`) below the ask box.
 * Every other page reports to a person; this one prepares for them and trades with them. Each
 * section is picked by code (`lib/home.ts`) from records the install already keeps — no model is
 * called to fill it — and each says when it has nothing, rather than showing a copy of another page.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import { ActorField, useActor } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getAnalysisSummary } from "@/lib/api";
import {
  ANSWERS, bookSaid, dismissFinding, domainFindings, pickLead, pickQuestion, pickWorthALook, readYou,
  recheckFinding, standingQuestions, weekAhead,
  type Analysis, type Finding, type YourRecord,
} from "@/lib/home";
import { declareDecision, listClaims, listDecisions, type Claim, type Decision } from "@/lib/record";

const LAST_SEEN_KEY = "aughor_home_last_seen";

const card: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "16px 18px",
};
const label: CSSProperties = { fontSize: 12, color: "var(--t3)", marginBottom: 6 };
const body: CSSProperties = { fontSize: 14, color: "var(--t1)", lineHeight: 1.55 };
const note: CSSProperties = {
  fontSize: 12, color: "var(--t3)", lineHeight: 1.5, marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--b1)",
};

const shortDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};
const today = () => new Date().toISOString().slice(0, 10);

export function HomeDesk({ connectionId, analyses, onOpenAnalysis, onDraft }: {
  connectionId: string;
  /** The install's recent analyses, newest first — the same list the shell already reads. */
  analyses: Analysis[];
  onOpenAnalysis: (id: string, kind?: string) => void;
  /** Put a question in the ask box for the person to edit and send — never sends it. */
  onDraft: (question: string) => void;
}) {
  const actor = useActor();
  // The previous visit, read before this one is written: "since your last visit" means that one.
  const [since] = useState<string | null>(() => {
    try { return window.localStorage.getItem(LAST_SEEN_KEY); } catch { return null; }
  });
  useEffect(() => {
    try { window.localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString()); } catch { /* storage refused */ }
  }, []);

  const [said, setSaid] = useState<Claim[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [predictions, setPredictions] = useState<Claim[]>([]);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [you, setYou] = useState<YourRecord | null>(null);

  const reloadRecord = useCallback(() => {
    if (!connectionId) return;
    listClaims({ kind: "said", connection_id: connectionId, limit: 500 }).then(setSaid).catch(() => setSaid([]));
    listDecisions({ connection_id: connectionId, limit: 200 }).then(setDecisions).catch(() => setDecisions([]));
    listClaims({ kind: "prediction", connection_id: connectionId, limit: 500 }).then(setPredictions).catch(() => setPredictions([]));
  }, [connectionId]);
  useEffect(() => { reloadRecord(); }, [reloadRecord]);
  useEffect(() => {
    if (!connectionId) { setFindings([]); return; }
    domainFindings(connectionId).then(setFindings).catch(() => setFindings([]));
  }, [connectionId]);
  useEffect(() => { readYou().then(setYou).catch(() => setYou(null)); }, [said.length]);

  // A question answered during this visit stays on screen with its confirmation; it leaves on the next.
  const [answeredNow, setAnsweredNow] = useState<ReadonlySet<string>>(new Set());
  const answered = useMemo(() => new Set(said.map(c => String(c.extra?.about_ref ?? ""))
    .filter(id => id && !answeredNow.has(id))), [said, answeredNow]);
  const decided = useMemo(() => {
    const text = JSON.stringify(decisions);
    return new Set((findings ?? []).filter(f => text.includes(f.id)).map(f => f.id));
  }, [decisions, findings]);

  if (!connectionId) {
    return <div style={{ ...card, color: "var(--t3)", fontSize: 13 }}>Choose a connection to see what is on your desk.</div>;
  }

  const lead = pickLead(analyses, since, connectionId);
  const question = pickQuestion(analyses, connectionId, answered);
  const standing = standingQuestions(analyses, connectionId);
  const due = weekAhead(decisions, predictions, today());

  return (
    <div data-testid="home-desk" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: "var(--t2)" }}>
        {since ? `Since your last visit on ${shortDate(since)}` : "Your first visit in this browser"}
      </div>

      <LeadCard lead={lead} onOpen={onOpenAnalysis} onDraft={onDraft} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        <QuestionCard key={question?.about.id ?? "none"} question={question} connectionId={connectionId}
          actor={actor} onBooked={id => { setAnsweredNow(prev => new Set([...prev, id])); reloadRecord(); }} />
        <LookCard findings={findings} acted={new Set([...answered, ...decided])} connectionId={connectionId}
          onDecided={reloadRecord} />
      </div>

      <section aria-label="Your standing questions">
        <div style={{ ...label, fontSize: 13, color: "var(--t1)" }}>
          Your standing questions <span style={{ color: "var(--t3)" }}>· asked three or more times, with the latest answer</span>
        </div>
        {standing.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--t3)" }}>No question has been asked here three times yet.</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            {standing.map(s => (
              <Button key={s.latest.id} variant="ghost" onClick={() => onOpenAnalysis(s.latest.id, s.latest.kind)}
                style={{ ...card, height: "auto", display: "flex", flexDirection: "column", alignItems: "flex-start",
                  gap: 4, textAlign: "left", whiteSpace: "normal", padding: "12px 14px" }}>
                <span style={{ fontSize: 12, color: "var(--t2)", lineHeight: 1.4 }}>{s.question}</span>
                <span style={{ fontSize: 13, color: "var(--t1)", lineHeight: 1.45 }}>{s.latest.headline}</span>
                <span style={{ fontSize: 11, color: "var(--t3)" }}>
                  {`asked ${s.count} times since ${shortDate(s.first_at)} · last on ${shortDate(s.latest.started_at)}`}
                </span>
              </Button>
            ))}
          </div>
        )}
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        <section aria-label="The week ahead" style={card}>
          <div style={label}>The week ahead</div>
          {due.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--t3)" }}>
              Nothing on the record lands in the next seven days — no decision is due for review and no forecast settles.
            </div>
          ) : due.map(d => (
            <div key={`${d.on}:${d.what}`} style={{ display: "flex", gap: 12, fontSize: 13, padding: "6px 0", borderTop: "1px solid var(--b1)" }}>
              <span style={{ width: 64, flex: "none", color: "var(--t1)" }}>{shortDate(d.on)}</span>
              <span style={{ color: "var(--t2)" }}>{d.what}</span>
            </div>
          ))}
        </section>
        <YouCard you={you} />
      </div>
    </div>
  );
}

function LeadCard({ lead, onOpen, onDraft }: {
  lead: ReturnType<typeof pickLead>;
  onOpen: (id: string, kind?: string) => void;
  onDraft: (q: string) => void;
}) {
  const [summary, setSummary] = useState("");
  const runId = lead?.run.id ?? "";
  useEffect(() => {
    setSummary("");
    if (!runId) return;
    getAnalysisSummary(runId).then(s => setSummary(s.summary)).catch(() => setSummary(""));
  }, [runId]);
  if (!lead) {
    return (
      <section aria-label="The one thing to know" style={card}>
        <div style={label}>The one thing to know</div>
        <div style={{ fontSize: 13, color: "var(--t3)" }}>
          No daily run has reported a move here. A scheduled analysis is what prepares this before you arrive.
        </div>
      </section>
    );
  }
  const headline = String(lead.run.headline);
  return (
    <section aria-label="The one thing to know" data-testid="home-lead" style={{ ...card, borderColor: "var(--b2)" }}>
      <div style={label}>
        {lead.stale
          ? "The one thing to know · nothing new since your last visit, so the latest notable move"
          : "The one thing to know · the largest move the daily run reported since your last visit"}
      </div>
      <div style={{ fontSize: 18, fontWeight: 500, color: "var(--t1)", lineHeight: 1.45 }}>{headline}</div>
      {summary && <div style={{ ...body, marginTop: 6 }}>{`Already looked into on ${shortDate(lead.run.started_at)}: ${summary}`}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button size="sm" variant="outline" onClick={() => onOpen(lead.run.id, lead.run.kind)}>Read the analysis</Button>
        <Button size="sm" variant="ghost" onClick={() => onDraft(`Why did this happen? ${headline}`)}>Ask a follow-up</Button>
      </div>
    </section>
  );
}

function QuestionCard({ question, connectionId, actor, onBooked }: {
  question: ReturnType<typeof pickQuestion>;
  connectionId: string;
  actor: ReturnType<typeof useActor>;
  onBooked: (aboutId: string) => void;
}) {
  const [kept, setKept] = useState("");
  const [error, setError] = useState("");
  if (!question) {
    return (
      <section aria-label="A question for you" style={card}>
        <div style={label}>A question for you</div>
        <div style={{ fontSize: 13, color: "var(--t3)" }}>
          Nothing to ask you today: no analysis credits a cause you have not already spoken to.
        </div>
      </section>
    );
  }
  const answer = async (text: string) => {
    setError("");
    try {
      await bookSaid({ connection_id: connectionId, text, about: question.about.id, asked: question.text });
      setKept(text);
      onBooked(question.about.id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <section aria-label="A question for you" data-testid="home-question" style={card}>
      <div style={label}>A question for you</div>
      <div style={body}>{question.text}</div>
      <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
        {ANSWERS.map(a => <Button key={a} size="sm" variant="outline" onClick={() => answer(a)}>{a}</Button>)}
      </div>
      <div style={{ marginTop: 10 }}><ActorField actor={actor} id="home-actor" /></div>
      <div style={{ ...note, color: error ? "var(--red4)" : "var(--t3)" }}>
        {error || (kept
          ? `Kept as said by you on ${shortDate(new Date().toISOString())}: ${kept}.`
          : "Blocks nothing. Your answer is kept as said by you, dated, on the record.")}
      </div>
    </section>
  );
}

function LookCard({ findings, acted, connectionId, onDecided }: {
  findings: Finding[] | null;
  acted: ReadonlySet<string>;
  connectionId: string;
  onDecided: () => void;
}) {
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<"" | "decide" | "dismiss">("");
  const [text, setText] = useState("");
  const [said, setSaidLine] = useState("");
  const finding = findings ? pickWorthALook(findings, acted, skip) : null;
  if (findings === null) return <section aria-label="Worth another look" style={card}><div style={label}>Worth another look</div></section>;
  if (!finding) {
    return (
      <section aria-label="Worth another look" style={card}>
        <div style={label}>Worth another look</div>
        <div style={{ fontSize: 13, color: "var(--t3)" }}>Every finding here has been acted on, or there are none yet.</div>
        {said && <div style={note}>{said}</div>}
      </section>
    );
  }
  const next = (line: string) => { setSaidLine(line); setMode(""); setText(""); setSkip(s => new Set([...s, finding.id])); };
  const decide = async () => {
    try {
      const d = await declareDecision({ question: finding.text, chosen: text.trim(), connection_id: connectionId,
        note: `Decided from Home on finding ${finding.id}` });
      onDecided();
      next(`Booked as a decision; its review is set for ${shortDate(d.review_on)}.`);
    } catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  const dismiss = async () => {
    try { await dismissFinding(connectionId, finding.id, text.trim()); next("Set aside with your reason; it can be restored."); }
    catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  const recheck = async () => {
    try {
      const r = await recheckFinding(connectionId, finding.id);
      setSaidLine(r.status === "confirmed" ? "Re-ran its own SQL: the numbers still hold."
        : r.status === "drifted" ? "Re-ran its own SQL: a number moved — open the finding to see which."
        : `Re-ran its own SQL: ${r.status ?? "done"}.`);
    } catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <section aria-label="Worth another look" data-testid="home-look" style={card}>
      <div style={label}>{`Worth another look · from ${shortDate(finding.generated_at)}, nothing decided`}</div>
      <div style={body}>{finding.text}</div>
      {mode === "" ? (
        <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
          <Button size="sm" variant="outline" onClick={() => setMode("decide")}>Decide something</Button>
          <Button size="sm" variant="outline" onClick={recheck}>Check it again</Button>
          <Button size="sm" variant="outline" onClick={() => setMode("dismiss")}>Not worth it</Button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
          <Input value={text} onChange={e => setText(e.target.value)} style={{ flex: 1 }}
            placeholder={mode === "decide" ? "What was decided?" : "Why is it not worth it?"} />
          <Button size="sm" disabled={!text.trim()} onClick={mode === "decide" ? decide : dismiss}>
            {mode === "decide" ? "Book it" : "Set aside"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setMode(""); setText(""); }}>Cancel</Button>
        </div>
      )}
      <div style={note}>{said || "One finding at a time, from what was concluded and never acted on."}</div>
    </section>
  );
}

function YouCard({ you }: { you: YourRecord | null }) {
  const told = you?.by_kind?.said ?? 0;
  const forecasts = you?.by_kind?.prediction ?? 0;
  const scored = you?.predictions?.scored ?? 0;
  const inside = you?.predictions?.inside ?? 0;
  const cell = (k: string, v: string) => (
    <div><div style={{ fontSize: 12, color: "var(--t3)" }}>{k}</div><div style={{ fontSize: 22, fontWeight: 500, color: "var(--t1)" }}>{v}</div></div>
  );
  return (
    <section aria-label="Between you and Aughor" data-testid="home-you" style={card}>
      <div style={label}>Between you and Aughor</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
        {cell("You told it", String(told))}
        {cell("Your forecasts", String(forecasts))}
        {cell("Landed in your range", scored ? `${inside} of ${scored}` : "—")}
      </div>
      <div style={note}>{told || forecasts ? "Counted from the record — what became of what you said." : "Answer today's question and this starts counting."}</div>
    </section>
  );
}
