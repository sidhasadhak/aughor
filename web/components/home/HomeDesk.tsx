"use client";

/**
 * Home's desk — the sections of ROADMAP §3.55 (`docs/HOME_STUDY_2026-10-06.md`) below the ask box.
 * Every other page reports to a person; this one prepares for them and trades with them. Each
 * section is picked by code (`lib/home.ts`) from records the install already keeps — no model is
 * called to fill it — and each says when it has nothing, rather than showing a copy of another page.
 *
 * Laid out as the approved mockup lays it out (design-mockups/home.html, 2026-10-10; the law is
 * `aughor-v2/CLARITY.md`): the lead figure and what needs the person side by side, then the standing
 * questions, then the week ahead beside what is between them and Aughor. Figures first, facts as chips,
 * one muted line for an empty section, and no paragraph under any title — 1,076 words on theLook became
 * about 250.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { ExpectRow, NOT_ACT } from "@/components/decisions/DecideDoor";
import { ActorField, useActor } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { getMetrics, getSystemFlags, type Metric } from "@/lib/api";
import {
  ANSWERS, ASKED, bookSaid, byDay, dayMonth, dayWords, daysBehind, dismissFinding, domainFindings, leadDetail, metricWords,
  pickLead, pickQuestion, pickWorthALook, rangeText, readYou, recheckFinding, standingQuestions, weekAhead,
  type Analysis, type Due, type Finding, type LeadDetail, type YourRecord,
} from "@/lib/home";
import { declareDecision, listClaims, listDecisions, type Claim, type Decision, type ExpectationIn } from "@/lib/record";

const LAST_SEEN_KEY = "aughor_home_last_seen";

const card: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px", minWidth: 0,
};
const muted: CSSProperties = { color: "var(--t3)" };
const oneLine: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };

const today = () => new Date().toISOString().slice(0, 10);

/** A section's small uppercase label, with what it says at its right end. */
function Label({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: "var(--t3)",
      textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}
      {right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
    </div>
  );
}

type Tone = "plain" | "up" | "down" | "amber";
const TONE: Record<Tone, CSSProperties> = {
  plain: { background: "var(--bg-3)", color: "var(--t2)", border: "1px solid var(--b1)" },
  up: { background: "var(--grn1)", color: "var(--grn4)", border: "1px solid transparent" },
  down: { background: "var(--red1)", color: "var(--red4)", border: "1px solid transparent" },
  amber: { background: "var(--amb1)", color: "var(--amb4)", border: "1px solid transparent" },
};

/** A fact as a chip: what a figure's change, its range or its age is, said in a few words. */
function Chip({ tone = "plain", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span className="aug-fs-xs" title={title} style={{ ...TONE[tone], display: "inline-flex", alignItems: "center", gap: 5,
      padding: "2px 8px", borderRadius: "var(--r-pill)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
      {children}
    </span>
  );
}

const row: CSSProperties = { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" };

export function HomeDesk({ connectionId, analyses, onOpenAnalysis, onDraft }: {
  connectionId: string;
  /** The install's recent analyses, newest first — the same list the shell already reads. */
  analyses: Analysis[];
  onOpenAnalysis: (id: string, kind?: string) => void;
  /** Put a question in the ask box for the person to edit and send — never sends it. */
  onDraft: (question: string) => void;
}) {
  const actor = useActor();
  // PENDING 57, D-1: with the decision loop on, a decision taken here cites its finding and may say what is expected.
  const [loop, setLoop] = useState(false);
  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => { if (alive) setLoop(!!f["record.decision_loop"]?.value); }).catch(() => { if (alive) setLoop(false); });
    return () => { alive = false; };
  }, []);
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
    return <div className="aug-fs-sm" style={{ ...card, ...muted }}>Choose a connection to see what is on your desk.</div>;
  }

  const lead = pickLead(analyses, since, connectionId);
  const question = pickQuestion(analyses, connectionId, answered);
  const standing = standingQuestions(analyses, connectionId);
  const due = weekAhead(decisions, predictions, today());

  return (
    <div data-testid="home-desk" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="aug-fs-sm" style={{ ...muted, marginTop: -6 }}>
        {since ? `Since your last visit · ${dayWords(since)}` : "Your first visit in this browser"}
      </div>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "stretch" }}>
        <div style={{ flex: "1.55 1 420px", minWidth: 0, display: "flex" }}>
          <LeadCard lead={lead} onOpen={onOpenAnalysis} onDraft={onDraft} />
        </div>
        <div style={{ flex: "1 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 14 }}>
          <QuestionCard key={question?.about.id ?? "none"} question={question} connectionId={connectionId}
            actor={actor} onBooked={id => { setAnsweredNow(prev => new Set([...prev, id])); reloadRecord(); }} />
          <LookCard findings={findings} acted={new Set([...answered, ...decided])} connectionId={connectionId} loop={loop}
            onDecided={reloadRecord} />
        </div>
      </div>

      <section aria-label="Your standing questions" data-testid="home-standing" style={card}>
        <Label right={standing.length ? <span className="aug-fs-xs" style={muted}>asked 3+ times · latest answer</span> : null}>
          Your standing questions
        </Label>
        {standing.length === 0 ? (
          <div className="aug-fs-sm" style={muted}>No question asked three times yet.</div>
        ) : standing.map((s, i) => (
          <Button key={s.latest.id} variant="ghost" title={s.question} onClick={() => onOpenAnalysis(s.latest.id, s.latest.kind)}
            style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.1fr) 40px", alignItems: "center", gap: 14,
              width: "100%", height: "auto", padding: "9px 2px", borderRadius: 0, textAlign: "left", whiteSpace: "normal",
              borderTop: i ? "1px solid var(--b1)" : undefined }}>
            <span className="aug-fs-sm" style={{ ...oneLine, color: "var(--t2)" }}>{s.question}</span>
            <span className="aug-fs-sm" title={s.latest.headline ?? ""} style={{ ...oneLine, color: "var(--t1)", fontWeight: 600, textAlign: "right" }}>
              {s.latest.headline}
            </span>
            <span className="aug-fs-xs" style={{ ...muted, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{s.count}×</span>
          </Button>
        ))}
      </section>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "1.55 1 420px", minWidth: 0 }}><WeekCard due={due} /></div>
        <div style={{ flex: "1 1 300px", minWidth: 0 }}><YouCard you={you} /></div>
      </div>
    </div>
  );
}

function LeadCard({ lead, onOpen, onDraft }: {
  lead: ReturnType<typeof pickLead>;
  onOpen: (id: string, kind?: string) => void;
  onDraft: (q: string) => void;
}) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const runId = lead?.run.id ?? "";
  useEffect(() => {
    setDetail(null);
    if (!runId) return;
    leadDetail(runId).then(setDetail).catch(() => setDetail(null));
  }, [runId]);
  if (!lead) {
    return (
      <section aria-label="The one thing to know" style={{ ...card, flex: 1 }}>
        <Label>One thing to know</Label>
        <div className="aug-fs-sm" style={muted}>No daily run has reported a move here yet.</div>
      </section>
    );
  }
  const headline = String(lead.run.headline);
  const fig = detail?.figure ?? null;
  const behind = fig?.day ? daysBehind(fig.day, today()) : 0;
  const up = fig?.change ? !fig.change.trim().startsWith("-") : true;
  const pct = fig?.pct != null ? `${fig.pct >= 0 ? "+" : ""}${(fig.pct * 100).toFixed(1)}%` : "";
  const low = detail?.confidence && detail.confidence.toUpperCase() !== "HIGH";
  return (
    <section aria-label="The one thing to know" data-testid="home-lead" style={{ ...card, flex: 1 }}>
      <Label right={behind > 0 ? <Chip>{behind === 1 ? "1 day behind today" : `${behind} days behind today`}</Chip> : null}>
        {lead.stale ? "One thing to know · nothing new since your last visit" : "One thing to know"}
      </Label>
      {fig ? (
        <>
          <div className="aug-fs-sm" style={{ color: "var(--t2)" }} title={headline}>{fig.metric} · {dayWords(fig.day)}</div>
          <div className="aug-fs-display" data-testid="home-lead-value"
            style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums", margin: "2px 0 8px" }}>{fig.value}</div>
          <div style={row}>
            {fig.change && (
              <Chip tone={up ? "up" : "down"}><Icon name={up ? "trendup" : "trenddown"} size={12} />{fig.change}{pct ? ` · ${pct}` : ""}</Chip>
            )}
            {fig.verdict && <Chip tone={fig.unusual ? "amber" : "plain"}>{fig.verdict}</Chip>}
            {low && <Chip title={detail?.why || undefined}>{`${detail?.confidence.toLowerCase()} confidence`}</Chip>}
          </div>
        </>
      ) : (
        <div className="aug-fs-h2" style={{ color: "var(--t1)", fontWeight: 500, lineHeight: 1.45 }}>{headline}</div>
      )}
      <div className="aug-fs-xs" style={{ ...muted, margin: "10px 0 12px" }}>Looked into on {dayWords(lead.run.started_at)}</div>
      <div style={row}>
        <Button size="sm" variant="secondary" onClick={() => onOpen(lead.run.id, lead.run.kind)}>Read the analysis</Button>
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
        <Label>Needs you · a question</Label>
        <div className="aug-fs-sm" style={muted}>Nothing to ask you today.</div>
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
      <Label>Needs you · a question</Label>
      <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>{ASKED}</div>
      <div className="aug-fs-sm" title={question.subject}
        style={{ ...muted, margin: "2px 0 10px", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {question.subject}
      </div>
      {kept ? (
        <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>{`Kept as said by you · ${kept}`}</div>
      ) : (
        <div style={row}>
          {ANSWERS.map(a => <Button key={a} size="xs" variant="outline" onClick={() => answer(a)}>{a}</Button>)}
          <span style={{ marginLeft: "auto" }}><ActorField actor={actor} id="home-actor" /></span>
        </div>
      )}
      {error && <div className="aug-fs-xs" style={{ color: "var(--red4)", marginTop: 8 }}>{error}</div>}
    </section>
  );
}

function LookCard({ findings, acted, connectionId, onDecided, loop = false }: {
  findings: Finding[] | null;
  acted: ReadonlySet<string>;
  connectionId: string;
  onDecided: () => void;
  /** The decision loop (PENDING 57): the decision cites its finding, offers not acting, and may expect something. */
  loop?: boolean;
}) {
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<"" | "decide" | "dismiss">("");
  const [text, setText] = useState("");
  const [said, setSaidLine] = useState("");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [expect, setExpect] = useState({ metric: "", direction: "up", dimension: "", part: "" });
  useEffect(() => {
    if (!loop || mode !== "decide") return;
    let alive = true;
    // approved, and knowing its dates — the only metrics a review can measure for the weeks after the decision
    getMetrics(connectionId).then(ms => { if (alive) setMetrics(ms.filter(x => x.status === "approved" && x.time_kind && x.time_column)); })
      .catch(() => { if (alive) setMetrics([]); });
    return () => { alive = false; };
  }, [loop, mode, connectionId]);
  const finding = findings ? pickWorthALook(findings, acted, skip) : null;
  if (findings === null) return <section aria-label="Worth another look" style={card}><Label>Needs you · a finding to act on</Label></section>;
  if (!finding) {
    return (
      <section aria-label="Worth another look" style={card}>
        <Label>Needs you · a finding to act on</Label>
        <div className="aug-fs-sm" style={muted}>{said || "Every finding here has been acted on."}</div>
      </section>
    );
  }
  const next = (line: string) => {
    setSaidLine(line); setMode(""); setText(""); setSkip(s => new Set([...s, finding.id]));
    setExpect({ metric: "", direction: "up", dimension: "", part: "" });
  };
  const decide = async () => {
    try {
      const expectation: ExpectationIn | null = loop && expect.metric ? {
        metric: expect.metric, direction: expect.direction,
        ...(expect.dimension && expect.part.trim() ? { segment_dimension: expect.dimension, segment_value: expect.part.trim() } : {}),
      } : null;
      const d = await declareDecision(loop ? {
        question: finding.text, chosen: text.trim(), options: [text.trim(), NOT_ACT], connection_id: connectionId,
        note: `Decided from Home on finding ${finding.id}`, finding_id: finding.id, ...(expectation ? { expectation } : {}),
      } : {
        question: finding.text, chosen: text.trim(), connection_id: connectionId,
        note: `Decided from Home on finding ${finding.id}`,
      });
      onDecided();
      next(`Booked as a decision · review ${dayWords(d.review_on)}`
        + (loop && !expectation ? " · nothing expected, so it cannot be scored" : ""));
    } catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  const dismiss = async () => {
    try {
      await dismissFinding(connectionId, finding.id, text.trim());
      next(loop ? "Set aside · booked as a decision not to act · it can be restored" : "Set aside · it can be restored");
    }
    catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  const recheck = async () => {
    try {
      const r = await recheckFinding(connectionId, finding.id);
      setSaidLine(r.status === "confirmed" ? "Checked again · the numbers still hold"
        : r.status === "drifted" ? "Checked again · a number moved — open the finding to see which"
        : `Checked again · ${r.status ?? "done"}`);
    } catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <section aria-label="Worth another look" data-testid="home-look" style={card}>
      <Label right={<span className="aug-fs-xs" style={muted}>{dayWords(finding.generated_at)}</span>}>Needs you · a finding to act on</Label>
      <div className="aug-fs-chrome" title={finding.text} style={{ color: "var(--t1)", fontWeight: 500, marginBottom: 10,
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{finding.text}</div>
      {mode === "" ? (
        <div style={row}>
          <Button size="xs" variant="secondary" onClick={() => setMode("decide")}>Decide</Button>
          <Button size="xs" variant="ghost" onClick={recheck}>Check again</Button>
          <Button size="xs" variant="ghost" onClick={() => setMode("dismiss")}>Not worth it</Button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 6 }}>
          <Input value={text} onChange={e => setText(e.target.value)} style={{ flex: 1 }}
            placeholder={mode === "decide" ? "What was decided?" : "Why is it not worth it?"} />
          <Button size="sm" disabled={!text.trim()} onClick={mode === "decide" ? decide : dismiss}>
            {mode === "decide" ? "Book it" : "Set aside"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setMode(""); setText(""); }}>Cancel</Button>
        </div>
      )}
      {loop && mode === "decide" && <ExpectRow metrics={metrics} value={expect} onChange={setExpect} />}
      {said && <div className="aug-fs-xs" style={{ ...muted, marginTop: 8 }}>{said}</div>}
    </section>
  );
}

/** The forecasts and reviews that land in the next seven days, a day at a time: the first day's ranges written out,
 *  the later days' metrics as chips. */
function WeekCard({ due }: { due: Due[] }) {
  const days = byDay(due);
  const span = (ds: Due[]) => {
    const f = ds[0];
    if (!f?.from || ds.some(d => d.from !== f.from || d.to !== f.to)) return "";
    if (f.from === f.to) return `for ${dayMonth(f.from)}`;
    return f.from.slice(0, 7) === (f.to ?? "").slice(0, 7)
      ? `for ${Number(f.from.slice(8, 10))}–${dayMonth(f.to ?? "")}` : `for ${dayMonth(f.from)} – ${dayMonth(f.to ?? "")}`;
  };
  return (
    <section aria-label="The week ahead" data-testid="home-week" style={card}>
      <Label><Icon name="date" size={13} /> The week ahead</Label>
      {days.length === 0 ? (
        <div className="aug-fs-sm" style={muted}>Nothing lands in the next seven days.</div>
      ) : days.map((d, i) => (
        <div key={d.on} style={{ display: "grid", gridTemplateColumns: "96px minmax(0, 1fr) auto", gap: 12, padding: "8px 0",
          borderTop: i ? "1px solid var(--b1)" : undefined }}>
          <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>
            {dayWords(d.on)}
            <div className="aug-fs-xs" style={muted}>
              {[d.forecasts.length ? `${d.forecasts.length} forecast${d.forecasts.length === 1 ? "" : "s"}` : "",
                d.reviews.length ? `${d.reviews.length} review${d.reviews.length === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ")}
            </div>
          </div>
          <div style={{ minWidth: 0 }}>
            {d.reviews.map(r => (
              <div key={r.what} className="aug-fs-sm" style={{ ...oneLine, color: "var(--t2)" }} title={r.what}>{r.what}</div>
            ))}
            {i === 0 ? (
              <div className="aug-fs-sm" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "3px 16px" }}>
                {d.forecasts.slice(0, 4).map(f => (
                  <div key={f.what} style={{ display: "contents" }}>
                    <span style={oneLine}>{metricWords(f.metric)}</span>
                    <span style={{ color: "var(--t2)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{rangeText(f.low, f.high, f.unit)}</span>
                  </div>
                ))}
                {d.forecasts.length > 4 && <span className="aug-fs-xs" style={muted}>+{d.forecasts.length - 4} more</span>}
              </div>
            ) : (
              <div style={row}>
                {d.forecasts.slice(0, 5).map(f => <Chip key={f.what}>{metricWords(f.metric)}</Chip>)}
                {d.forecasts.length > 5 && <Chip>+{d.forecasts.length - 5}</Chip>}
              </div>
            )}
          </div>
          <span className="aug-fs-xs" style={muted}>{span(d.forecasts)}</span>
        </div>
      ))}
    </section>
  );
}

function YouCard({ you }: { you: YourRecord | null }) {
  const told = you?.by_kind?.said ?? 0;
  const forecasts = you?.by_kind?.prediction ?? 0;
  const scored = you?.predictions?.scored ?? 0;
  const inside = you?.predictions?.inside ?? 0;
  const stat = (k: string, v: string) => (
    <div>
      <div className="aug-fs-h1" style={{ color: "var(--t1)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{v}</div>
      <div className="aug-fs-xs" style={muted}>{k}</div>
    </div>
  );
  return (
    <section aria-label="Between you and Aughor" data-testid="home-you" style={card}>
      <Label>Between you and Aughor</Label>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
        {stat("you told it", String(told))}
        {stat("your forecasts", String(forecasts))}
        {stat("landed in range", scored ? `${inside} of ${scored}` : "—")}
      </div>
    </section>
  );
}
