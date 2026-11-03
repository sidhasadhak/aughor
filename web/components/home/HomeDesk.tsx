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
import { NEEDS_EDGE } from "@/components/clarity/kit";
import { LeadChart } from "@/components/home/LeadChart";
import { getMetrics, readMetricTrend, type Metric } from "@/lib/api";
import { readableFigures } from "@/lib/format";
import {
  ANSWERS, ASKED, bookSaid, byDay, dayMonth, dayWords, daysBehind, dismissFinding, domainFindings, leadDetail, metricWords,
  pickLead, pickQuestion, pickWorthALook, rangeText, readYou, recheckFinding, standingQuestions, weekAhead,
  type Analysis, type Due, type Finding, type LeadDetail, type YourRecord, leadReading, plainDays, type TrendPoint,
} from "@/lib/home";
import { declareDecision, listClaims, listDecisions, type Claim, type Decision, type ExpectationIn } from "@/lib/record";

const LAST_SEEN_KEY = "aughor_home_last_seen";

const card: CSSProperties = {
  background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px", minWidth: 0,
};
const muted: CSSProperties = { color: "var(--t3)" };
const oneLine: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };

const today = () => new Date().toISOString().slice(0, 10);

/** How much of the lead's metric the line shows, a day at a time. */
const TREND_DAYS = 60;

/** A section's small uppercase label, with what it says at its right end. */
function Label({ children, right, amber }: { children: ReactNode; right?: ReactNode; amber?: boolean }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: amber ? "var(--amb4)" : "var(--t3)",
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
        <div style={{ flex: "2 1 560px", minWidth: 0, display: "flex" }}>
          <LeadCard lead={lead} connectionId={connectionId} onOpen={onOpenAnalysis} onDraft={onDraft} />
        </div>
        <div style={{ flex: "1 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 14 }}>
          {question && (
            <QuestionCard key={question.about.id} question={question} connectionId={connectionId}
              actor={actor} onBooked={id => { setAnsweredNow(prev => new Set([...prev, id])); reloadRecord(); }} />
          )}
          <LookCard findings={findings} acted={new Set([...answered, ...decided])} connectionId={connectionId}
            onDecided={reloadRecord} noQuestion={!question} />
          <WeekCard due={due} />
          <YouCard you={you} />
        </div>
      </div>

      <section aria-label="Your standing questions" data-testid="home-standing" style={card}>
        <Label right={standing.length ? <span className="aug-fs-xs" style={muted}>asked 3+ times · latest answer</span> : null}>
          Your standing questions
        </Label>
        {standing.length === 0 ? (
          <div className="aug-fs-sm" style={muted}>No question asked three times yet.</div>
        ) : standing.map((s, i) => (
          <Button key={s.latest.id} variant="plain" title={s.question} onClick={() => onOpenAnalysis(s.latest.id, s.latest.kind)}
            style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 32px", alignItems: "center", gap: 14,
              width: "100%", height: "auto", padding: "8px 2px", borderRadius: 0, textAlign: "left", whiteSpace: "normal",
              borderTop: i ? "1px solid var(--b1)" : undefined }}>
            <span style={{ minWidth: 0 }}>
              <span className="aug-fs-chrome" title={s.latest.headline ?? ""} style={{ ...oneLine, display: "block", color: "var(--t1)", fontWeight: 500 }}>
                {readableFigures(s.latest.headline)}
              </span>
              <span className="aug-fs-xs" style={{ ...oneLine, ...muted, display: "block" }}>{s.question}</span>
            </span>
            <span className="aug-fs-xs" style={{ ...muted, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{s.count}×</span>
          </Button>
        ))}
      </section>
    </div>
  );
}

function LeadCard({ lead, connectionId, onOpen, onDraft }: {
  lead: ReturnType<typeof pickLead>;
  connectionId: string;
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
  // The metric the analysis reported, as the warehouse reads it now: one statement, no model call.
  const label = detail?.figure?.metric ?? "";
  const [trend, setTrend] = useState<{ points: TrendPoint[]; why: string } | null>(null);
  useEffect(() => {
    setTrend(null);
    if (!label || !connectionId) return;
    let alive = true;
    const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
    getMetrics(connectionId)
      .then(ms => ms.find(m => m.status === "approved" && (m.label === label || m.name === label)))
      .then(m => (m ? readMetricTrend(connectionId, m.name, { preset: "custom", start: yesterday, end: yesterday }, undefined, undefined, TREND_DAYS) : null))
      .then(t => {
        if (!alive) return;
        // the trend words a figure bare and keeps its currency in `unit`
        const symbol = t && /^(\$|€|£|¥|₹|R\$)$/.test(t.unit ?? "") ? t.unit : "";
        setTrend(t ? {
          points: t.series.flatMap(p => (p.value == null ? [] : [{ day: p.start, value: p.value, text: `${symbol}${p.value_text ?? ""}`, settling: !!p.settling }])),
          why: t.why ?? "",
        } : { points: [], why: "" });
      })
      .catch(e => { if (alive) setTrend({ points: [], why: e instanceof Error ? e.message : String(e) }); });
    return () => { alive = false; };
  }, [label, connectionId]);
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
  // What the day reads now wins over what the analysis reported; a difference is said, never smoothed over.
  const reading = fig && trend ? leadReading(fig, trend.points) : null;
  const looked = dayWords(lead.run.started_at);
  const verdict = fig?.verdict ? fig.verdict.charAt(0).toUpperCase() + fig.verdict.slice(1) : "";
  return (
    <section aria-label="The one thing to know" data-testid="home-lead" style={{ ...card, flex: 1, display: "flex", flexDirection: "column" }}>
      <Label right={behind > 0 || low ? (
        <span style={row}>
          {low && <Chip title={detail?.why || undefined}>{`${detail?.confidence.toLowerCase()} confidence`}</Chip>}
          {behind > 0 && <Chip>{behind === 1 ? "1 day behind today" : `${behind} days behind today`}</Chip>}
        </span>
      ) : null}>
        {lead.stale ? "One thing to know · nothing new since your last visit" : "One thing to know"}
      </Label>
      {fig ? (
        <>
          <div className="aug-fs-chrome" style={{ color: "var(--t2)" }} title={headline}>{fig.metric} · {dayWords(fig.day)}</div>
          <div className="aug-fs-lead" data-testid="home-lead-value"
            style={{ color: "var(--t1)", fontWeight: 500, fontVariantNumeric: "tabular-nums", margin: "2px 0 6px" }}>{reading?.value ?? fig.value}</div>
          <div style={row}>
            {reading ? (
              reading.change && <span className="aug-fs-chrome" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{reading.change}</span>
            ) : fig.change && (
              <Chip tone={up ? "up" : "down"}><Icon name={up ? "trendup" : "trenddown"} size={12} />{plainDays(fig.change)}{pct ? ` · ${pct}` : ""}</Chip>
            )}
            {reading?.reported && (
              <Chip tone="amber" title={`The analysis of ${looked} reported ${fig.value}. The warehouse reads this day differently now.`}>
                {`reported ${reading.reported} on ${dayMonth(lead.run.started_at)} · restated ${(reading.restated! * 100).toFixed(0).replace("-", "−")}%`}
              </Chip>
            )}
          </div>
          {trend && trend.points.length > 1 ? (
            <LeadChart points={trend.points} day={fig.day}
              reported={reading?.reported ? { value: Number(fig.value.replace(/[^0-9.-]/g, "")), text: reading.reported, on: dayMonth(lead.run.started_at) } : null} />
          ) : trend?.why ? (
            <div className="aug-fs-xs" style={{ ...muted, marginTop: 10 }}>The line behind this figure could not be read · {trend.why}</div>
          ) : !trend ? (
            <div aria-hidden style={{ height: 272, marginTop: 12 }} />
          ) : null}
        </>
      ) : (
        <div className="aug-fs-h2" style={{ color: "var(--t1)", fontWeight: 500, lineHeight: 1.45 }}>{headline}</div>
      )}
      <div style={{ ...row, marginTop: "auto", paddingTop: 12 }}>
        <Button size="sm" variant="secondary" onClick={() => onOpen(lead.run.id, lead.run.kind)}>Read the analysis</Button>
        <Button size="sm" variant="ghost" onClick={() => onDraft(`Why did this happen? ${headline}`)}>Ask a follow-up</Button>
        <span className="aug-fs-xs" style={{ ...muted, flex: "1 1 240px", textAlign: "right" }}>
          Looked into on {looked}{verdict ? ` · ${verdict}` : ""}
        </span>
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
  if (!question) return null;
  const answer = async (text: string) => {
    setError("");
    try {
      await bookSaid({ connection_id: connectionId, text, about: question.about.id, asked: question.text });
      setKept(text);
      onBooked(question.about.id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <section aria-label="A question for you" data-testid="home-question" style={{ ...card, boxShadow: NEEDS_EDGE }}>
      <Label amber>Needs you · a question</Label>
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

/** PENDING 57, D-1: a decision taken here cites its finding, offers not acting, and may say what is expected. */
function LookCard({ findings, acted, connectionId, onDecided, noQuestion }: {
  findings: Finding[] | null;
  acted: ReadonlySet<string>;
  connectionId: string;
  onDecided: () => void;
  /** Nothing to ask: said once, in the foot of this card, rather than as a card of its own. */
  noQuestion: boolean;
}) {
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<"" | "decide" | "dismiss">("");
  const [text, setText] = useState("");
  const [said, setSaidLine] = useState("");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [expect, setExpect] = useState({ metric: "", direction: "up", dimension: "", part: "" });
  useEffect(() => {
    if (mode !== "decide") return;
    let alive = true;
    // approved, and knowing its dates — the only metrics a review can measure for the weeks after the decision
    getMetrics(connectionId).then(ms => { if (alive) setMetrics(ms.filter(x => x.status === "approved" && x.time_kind && x.time_column)); })
      .catch(() => { if (alive) setMetrics([]); });
    return () => { alive = false; };
  }, [mode, connectionId]);
  const finding = findings ? pickWorthALook(findings, acted, skip) : null;
  if (findings === null) return <section aria-label="Worth another look" style={card}><Label>Needs you · a finding to act on</Label></section>;
  if (!finding) {
    return (
      <section aria-label="Worth another look" style={card}>
        <Label>Needs you · a finding to act on</Label>
        <div className="aug-fs-sm" style={muted}>{said || "Every finding here has been acted on."}</div>
        {noQuestion && <div className="aug-fs-sm" style={{ ...muted, marginTop: 8 }}>Nothing to ask you today.</div>}
      </section>
    );
  }
  const next = (line: string) => {
    setSaidLine(line); setMode(""); setText(""); setSkip(s => new Set([...s, finding.id]));
    setExpect({ metric: "", direction: "up", dimension: "", part: "" });
  };
  const decide = async () => {
    try {
      const expectation: ExpectationIn | null = expect.metric ? {
        metric: expect.metric, direction: expect.direction,
        ...(expect.dimension && expect.part.trim() ? { segment_dimension: expect.dimension, segment_value: expect.part.trim() } : {}),
      } : null;
      const d = await declareDecision({
        question: finding.text, chosen: text.trim(), options: [text.trim(), NOT_ACT], connection_id: connectionId,
        note: `Decided from Home on finding ${finding.id}`, finding_id: finding.id, ...(expectation ? { expectation } : {}),
      });
      onDecided();
      next(`Booked as a decision · review ${dayWords(d.review_on)}`
        + (!expectation ? " · nothing expected, so it cannot be scored" : ""));
    } catch (e) { setSaidLine(e instanceof Error ? e.message : String(e)); }
  };
  const dismiss = async () => {
    try {
      await dismissFinding(connectionId, finding.id, text.trim());
      next("Set aside · booked as a decision not to act · it can be restored");
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
    <section aria-label="Worth another look" data-testid="home-look" style={{ ...card, flex: 1, display: "flex", flexDirection: "column", boxShadow: NEEDS_EDGE }}>
      <Label amber right={<span className="aug-fs-xs" style={muted}>{dayWords(finding.generated_at)}</span>}>Needs you · a finding to act on</Label>
      <div className="aug-fs-chrome" title={finding.text} style={{ color: "var(--t1)", fontWeight: 500, marginBottom: 10,
        display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{readableFigures(finding.text)}</div>
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
      {mode === "decide" && <ExpectRow metrics={metrics} value={expect} onChange={setExpect} />}
      {said && <div className="aug-fs-xs" style={{ ...muted, marginTop: 8 }}>{said}</div>}
      {noQuestion && <div className="aug-fs-sm" style={{ ...muted, marginTop: "auto", paddingTop: 12 }}>Nothing to ask you today.</div>}
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
      <Label right={days.length ? <span className="aug-fs-xs" style={muted}>{dayWords(days[0].on)}{span(days[0].forecasts) ? ` · ${span(days[0].forecasts)}` : ""}</span> : null}>The week ahead</Label>
      {days.length === 0 ? (
        <div className="aug-fs-sm" style={muted}>Nothing lands in the next seven days.</div>
      ) : days.map((d, i) => (
        <div key={d.on} style={{ padding: i ? "8px 0 0" : 0, borderTop: i ? "1px solid var(--b1)" : undefined, marginTop: i ? 8 : 0 }}>
          {i > 0 && <div className="aug-fs-sm" style={{ color: "var(--t1)", marginBottom: 4 }}>{dayWords(d.on)}</div>}
          {d.reviews.map(r => (
            <div key={r.what} className="aug-fs-sm" style={{ ...oneLine, color: "var(--t2)" }} title={r.what}>{r.what}</div>
          ))}
          {i === 0 ? (
            <div className="aug-fs-sm" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "3px 16px" }}>
              {d.forecasts.slice(0, 4).map(f => (
                <div key={f.what} style={{ display: "contents" }}>
                  <span style={{ ...oneLine, color: "var(--t2)" }}>{metricWords(f.metric)}</span>
                  <span style={{ color: "var(--t1)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{rangeText(f.low, f.high, f.unit)}</span>
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
      <div className="aug-fs-h1" style={{ color: "var(--t1)", fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{v}</div>
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
