"use client";

/**
 * Now — "what needs me, this week?" (the 2027 study §V, screen 2).
 *
 * It is bounded and it ends: the few things that used one of the week's slots, each saying why
 * it won; what is addressed to a person; what was restated since they were last here; what
 * competed and lost, with why; and the Briefing in one line. A first run gets one sentence and
 * the way to Home, where a first run starts. There is no tile here and nothing to arrange.
 *
 * Every row is a ledger entry read back — the departure gate's triage ranked it (code), and the
 * hold is as much a row as the send.
 */
import { useEffect, useMemo, useState } from "react";

import { getDepartures, getNeedsHuman, type Connection, type Departure, type NeedsHuman } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { owes, summaryLine, whenText } from "@/lib/departures";
import { countNoun } from "@/lib/format";
import { connectionLabel, destinationLabel, needsYouTitle } from "@/lib/names";
import {
  getAttentionBudget, getAttentionHeld, getCorrections, listDecisions, listInquiries, listMissions,
  setAttentionSlots, whoLabel,
  type AttentionBudget, type CorrectionEntry, type Decision, type HeldItem, type Inquiry, type Mission,
} from "@/lib/record";
import { Absent, Gate, Page, Section, day, dayDistance, useLoad } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const LAST_SEEN_KEY = "aughor_now_last_seen";

interface OrgBriefing {
  briefings: { connection_id: string; connection_name: string; note?: string;
    briefing: null | { as_of?: string; version?: number; headline?: string; theme?: string; lede?: string } }[];
  with_briefing: number;
  connections: number;
}

interface Week {
  weekStart: string;
  sent: Departure[];
  budgets: AttentionBudget[];
  held: HeldItem[];
}

async function readWeek(): Promise<Week> {
  const [rows, heldView] = await Promise.all([getDepartures({ limit: 200 }), getAttentionHeld()]);
  const weekStart = heldView.week_start;
  const sent = (rows ?? []).filter(d => d.state === "departed" && d.ts.slice(0, 10) >= weekStart);
  const places = [...new Set([...sent.map(d => d.target), ...heldView.held.map(h => h.target)].filter(Boolean))];
  const budgets = await Promise.all(places.map(p => getAttentionBudget(p)));
  return { weekStart, sent, budgets, held: heldView.held };
}

interface Waiting {
  decisions: Decision[];
  inquiries: Inquiry[];
  departures: Departure[];
  needs: NeedsHuman;
}

async function readWaiting(): Promise<Waiting> {
  const [decisions, inquiries, owed, needs] = await Promise.all([
    listDecisions({ due: true }), listInquiries({ due: true }), getDepartures({ awaiting: true, limit: 50 }), getNeedsHuman(50),
  ]);
  return { decisions, inquiries, departures: (owed ?? []).filter(d => owes(d) !== null), needs };
}

async function readOrgBriefing(): Promise<OrgBriefing> {
  const res = await fetch(`${getApiBase()}/briefing/organisation`);
  if (!res.ok) throw new Error(`The Briefing could not be read (${res.status})`);
  return res.json();
}

export interface NowDoors {
  onOpenDecision: (id: string) => void;
  onOpenInquiry: (id: string) => void;
  onOpenDepartures: (departureId?: string) => void;
  onOpenAttention: () => void;
  onOpenBriefing: (connectionId?: string) => void;
  onOpenCorrections: () => void;
  onOpenMissions: () => void;
  /** Home — where a first run connects data and asks its first question. */
  onOpenHome: () => void;
}

export function NowPanel({ connections, contextReady, doors }: {
  connections: Connection[];
  /** False while the shell is still finding the workspace and its connections. */
  contextReady: boolean;
  doors: NowDoors;
}) {
  const week = useLoad(readWeek, []);
  const waiting = useLoad(readWaiting, []);
  const corrections = useLoad(() => getCorrections({ limit: 60 }), []);
  const briefing = useLoad(readOrgBriefing, []);
  const missions = useLoad(() => listMissions({ state: "active" }), []);

  // "Since you were here" is this reader's own convenience: the last visit is kept in this
  // browser, read once as the page arrives and moved forward only as they leave it.
  const [since] = useState<string | null>(() => {
    try { return localStorage.getItem(LAST_SEEN_KEY); } catch { return null; }
  });
  useEffect(() => {
    const arrived = new Date().toISOString();
    return () => { try { localStorage.setItem(LAST_SEEN_KEY, arrived); } catch { /* a private window keeps no visit */ } };
  }, []);

  const firstRun = contextReady && connections.filter(c => !c.builtin).length === 0
    && week.data !== null && week.data.sent.length === 0 && week.data.held.length === 0
    && waiting.data !== null && waiting.data.decisions.length + waiting.data.inquiries.length === 0;

  if (firstRun) return <FirstRun doors={doors} />;

  return (
    <Page>
      <Section label="This week's slots" meta={week.data ? slotsMeta(week.data) : undefined}>
        <Gate load={week} what="this week's sends">
          {w => <Slots week={w} missions={missions.data ?? []} connections={connections} doors={doors} onChanged={week.reload} />}
        </Gate>
      </Section>

      <Section label="Waiting on you" meta={waiting.data ? waitingMeta(waiting.data) : undefined}>
        <Gate load={waiting} what="what waits on a person">
          {w => <WaitingList waiting={w} connections={connections} doors={doors} />}
        </Gate>
      </Section>

      <Section label="Since you were here" meta={since ? `last visit ${whenText(since)}` : "your first visit in this browser — the last seven days"}
        action={<Button variant="ghost" size="xs" onClick={doors.onOpenCorrections}>All corrections</Button>}>
        <Gate load={corrections} what="what was restated">
          {c => <Restated entries={c.entries} since={since} labels={c.labels} />}
        </Gate>
      </Section>

      <Section label="Held this week" meta={week.data ? countNoun(week.data.held.length, "item") : undefined}
        action={<Button variant="ghost" size="xs" onClick={() => doors.onOpenDepartures()}>Every departure</Button>}>
        <Gate load={week} what="what was held">
          {w => <Held held={w.held} doors={doors} />}
        </Gate>
      </Section>

      <Section label="The Briefing">
        <Gate load={briefing} what="the Briefing">
          {b => <BriefingLine fold={b} doors={doors} />}
        </Gate>
      </Section>
    </Page>
  );
}

function slotsMeta(w: Week): string {
  if (w.budgets.length === 0) return "nothing was sent to a place this week";
  const used = w.budgets.reduce((n, b) => n + b.used, 0);
  const slots = w.budgets.reduce((n, b) => n + b.slots, 0);
  return `${used} of ${slots} used across ${countNoun(w.budgets.length, "place")}`;
}

function waitingMeta(w: Waiting): string {
  const n = w.decisions.length + w.inquiries.length + w.departures.length + w.needs.rows.length;
  return n === 0 ? "nothing" : countNoun(n, "thing");
}

/** The number a person is waited on for — the Now badge reads the same reads. */
export function waitingCount(w: Waiting): number {
  return w.decisions.length + w.inquiries.length + w.departures.length + w.needs.rows.length;
}

// ── 1 · the week's slots ─────────────────────────────────────────────────────────────────

function Slots({ week, missions, connections, doors, onChanged }: {
  week: Week; missions: Mission[]; connections: Connection[]; doors: NowDoors; onChanged: () => void;
}) {
  if (week.budgets.length === 0) {
    return (
      <Absent>
        Nothing left the platform for a channel or a person since {week.weekStart}. A send that passes the
        departure gate uses one of its place&apos;s slots and is listed here with why it won.
      </Absent>
    );
  }
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {week.budgets.map(b => (
        <Place key={b.addressee} budget={b} sent={week.sent.filter(d => d.target === b.addressee)}
          missions={missions} connections={connections} doors={doors} onChanged={onChanged} />
      ))}
    </div>
  );
}

function Place({ budget, sent, missions, connections, doors, onChanged }: {
  budget: AttentionBudget; sent: Departure[]; missions: Mission[]; connections: Connection[];
  doors: NowDoors; onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [slots, setSlots] = useState(String(budget.slots));
  const [error, setError] = useState("");
  const save = async () => {
    const n = Number(slots);
    if (!Number.isInteger(n) || n < 0) { setError("Slots are a whole number, 0 or more."); return; }
    try {
      await setAttentionSlots(budget.addressee, n);
      setEditing(false);
      setError("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <span className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{destinationLabel(budget.addressee).label}</span>
        <span className="aug-fs-ui aug-num" style={{ color: budget.left === 0 ? "var(--amb4)" : "var(--t2)" }}>
          {budget.used} of {budget.slots} slots used
        </span>
        {budget.held_count > 0 && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{countNoun(budget.held_count, "item")} held</span>
        )}
        <span style={{ flex: 1 }} />
        {editing ? (
          <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <Input aria-label={`Slots a week for ${budget.addressee}`} value={slots} inputMode="numeric"
              onChange={e => setSlots(e.target.value)} style={{ width: 64 }} />
            <Button size="xs" onClick={() => void save()}>Save</Button>
            <Button size="xs" variant="ghost" onClick={() => { setEditing(false); setError(""); }}>Cancel</Button>
          </span>
        ) : (
          <Button size="xs" variant="ghost" onClick={() => setEditing(true)}
            title="How many sends a week this place takes; 0 holds everything unattended">Set slots</Button>
        )}
      </div>
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "4px 0 0" }}>{error}</p>}
      {sent.length === 0 ? (
        <Absent>No send used a slot here this week.</Absent>
      ) : sent.map(d => <SentItem key={d.id} d={d} missions={missions} connections={connections} doors={doors} />)}
    </div>
  );
}

const TERM_WORDS: Record<string, string> = {
  mission: "its bearing on a mission", size: "its size against normal", waiting: "the cost of waiting", novelty: "its novelty",
};

/** The gate's triage line (`mission 1.00 · size 0.00 · … → score 0.65`) as what it was ranked on,
 *  strongest term first. A line that does not parse is shown as the gate wrote it. */
export function triageWords(triage: string): string {
  const score = /score\s+([\d.]+)/.exec(triage)?.[1];
  const terms = [...triage.matchAll(/(mission|size|waiting|novelty)\s+([\d.]+)/g)]
    .map(m => [m[1], Number(m[2])] as const).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (terms.length === 0) return triage;
  return `ranked on ${terms.map(([t]) => TERM_WORDS[t]).join(", ")}${score ? ` — score ${score}` : ""}`;
}

/** The mission a departure bore on, by name — the gate writes the ids it charged on the row. */
function bearingText(d: Departure, missions: Mission[]): string {
  const noted = d.checks.mission ?? "";
  if (!noted) return "bears on no mission";
  const named = missions.filter(m => noted.includes(m.id) || noted.includes(m.key) || noted.includes(m.name));
  return named.length ? `bears on ${named.map(m => m.name).join(", ")}` : noted;
}

function SentItem({ d, missions, connections, doors }: {
  d: Departure; missions: Mission[]; connections: Connection[]; doors: NowDoors;
}) {
  return (
    <div className="aug-item">
      <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.text_preview}</div>
      <div className="aug-item-foot aug-fs-sm">
        <span>{bearingText(d, missions)}</span>
        {d.checks.triage && <span title={`Why it won a slot — ${d.checks.triage}`}>{triageWords(d.checks.triage)}</span>}
        <span>{summaryLine(d)}</span>
        {d.conn_id && <span>{connectionLabel(d.conn_id, connections)}</span>}
        <span>{whenText(d.ts)}</span>
        <span style={{ flex: 1 }} />
        {/* Its row in Departures: every check it passed, and the analysis behind it when there is one. */}
        <Button size="xs" variant="outline" onClick={() => doors.onOpenDepartures(d.id)}>Open its receipt</Button>
      </div>
    </div>
  );
}

// ── 2 · waiting on a person ──────────────────────────────────────────────────────────────

function WaitingList({ waiting, connections, doors }: { waiting: Waiting; connections: Connection[]; doors: NowDoors }) {
  const none = waitingCount(waiting) === 0;
  if (none) {
    return <Absent>Nothing is addressed to a person: no review date has come, no inquiry is due, no send is waiting on an answer and no approval is open.</Absent>;
  }
  return (
    <div>
      {waiting.decisions.map(d => (
        <div className="aug-item" key={`decision:${d.id}`}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
            What became of &ldquo;{d.chosen}&rdquo;?
          </div>
          <div className="aug-item-foot aug-fs-sm">
            <span>review date {day(d.review_on)} · {dayDistance(d.review_on)}</span>
            <span>decided by {whoLabel(d.decided_by)}</span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" onClick={() => doors.onOpenDecision(d.id)}>Open the decision</Button>
          </div>
        </div>
      ))}
      {waiting.inquiries.map(q => (
        <div className="aug-item" key={`inquiry:${q.id}`}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{q.question}</div>
          <div className="aug-item-foot aug-fs-sm">
            <span>its check date has come ({day(q.next_check)}){q.waiting_for ? ` — it was waiting for ${q.waiting_for}` : ""}</span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" onClick={() => doors.onOpenInquiry(q.id)}>Open the inquiry</Button>
          </div>
        </div>
      ))}
      {waiting.departures.map(d => (
        <div className="aug-item" key={`departure:${d.id}`}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{summaryLine(d)}</div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{owes(d) === "answer" ? "an owner's answer is needed" : "its declarer marks it right or wrong"}</span>
            <span>{destinationLabel(d.target).label}</span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" onClick={() => doors.onOpenDepartures(d.id)}>
              {owes(d) === "answer" ? "Answer" : "Mark it"}
            </Button>
          </div>
        </div>
      ))}
      {waiting.needs.rows.map(r => {
        const t = needsYouTitle(r.title);
        return (
          <div className="aug-item" key={`needs:${r.source}:${r.id}`}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{t.display}</div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{NEEDS_WORDS[r.source] ?? "an action waits for approval"}</span>
              {r.connection_id && <span>{connectionLabel(r.connection_id, connections)}</span>}
              {r.since && <span>since {whenText(r.since)}</span>}
              <span style={{ flex: 1 }} />
              <Button size="xs" variant="outline" onClick={doors.onOpenAttention}>Resolve</Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Why a row waits, by its source. The one source not named here is the inbox of proposed actions. */
const NEEDS_WORDS: Record<string, string> = {
  paused_run: "a run is paused for a person",
  automation_approval: "an automation waits for approval",
  agent_alert: "an agent raised an alert",
  automation_broken: "an automation is failing",
};

// ── 3 · since you were here ──────────────────────────────────────────────────────────────

function Restated({ entries, since, labels }: {
  entries: CorrectionEntry[]; since: string | null; labels: Record<string, string>;
}) {
  // A first visit reads the last seven days; the floor is fixed as the section arrives.
  const [weekAgo] = useState(() => new Date(Date.now() - 7 * 86_400_000).toISOString());
  const shown = useMemo(() => {
    const floor = since ?? weekAgo;
    return entries.filter(e => e.at >= floor && e.believed !== e.replaced_by).slice(0, 8);
  }, [entries, since, weekAgo]);
  if (shown.length === 0) {
    return <Absent>Nothing you were told has been restated, refuted or missed since then.</Absent>;
  }
  return (
    <div>
      {shown.map(e => (
        <div className="aug-item" key={`${e.kind}:${e.ref}:${e.at}`}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{e.replaced_by}</div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{labels[e.kind] ?? e.kind}</span>
            <span>was: {e.believed}</span>
            <span>{whenText(e.at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── 4 · the held list ────────────────────────────────────────────────────────────────────

function Held({ held, doors }: { held: HeldItem[]; doors: NowDoors }) {
  if (held.length === 0) {
    return <Absent>Nothing competed for a slot and lost this week. When a place&apos;s slots are used, what is held is listed here with its score — never dropped silently.</Absent>;
  }
  return (
    <div>
      {held.map(h => (
        <div className="aug-item" key={h.departure_id}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{h.text}</div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{h.why}</span>
            <span title={`What it was held on — ${h.triage}`}>{triageWords(h.triage)}</span>
            <span>from {h.by || "an automation"}</span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="ghost" onClick={() => doors.onOpenDepartures(h.departure_id)}>Open</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── 5 · the Briefing, one line ───────────────────────────────────────────────────────────

function BriefingLine({ fold, doors }: { fold: OrgBriefing; doors: NowDoors }) {
  const kept = fold.briefings.filter(b => b.briefing);
  if (kept.length === 0) {
    return (
      <div className="aug-item">
        <Absent>No Briefing has been kept for any of the {countNoun(fold.connections, "connection")} yet — one is kept the first time a Briefing is built.</Absent>
        <div className="aug-item-foot"><Button size="xs" variant="outline" onClick={() => doors.onOpenBriefing()}>Open the Briefing</Button></div>
      </div>
    );
  }
  return (
    <div>
      {kept.map(b => (
        <div className="aug-item" key={b.connection_id}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{b.briefing!.lede || b.briefing!.headline || b.briefing!.theme}</div>
          <div className="aug-item-foot aug-fs-sm">
            <span>{b.connection_name}</span>
            {b.briefing!.as_of && <span>as of {day(b.briefing!.as_of)}</span>}
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="outline" onClick={() => doors.onOpenBriefing(b.connection_id)}>Read the Briefing</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── a first run ──────────────────────────────────────────────────────────────────────────

/** Nothing has been sent, held or asked yet. Home is where a first run starts; this page only says
 *  what it will hold once there is something to hold. */
function FirstRun({ doors }: { doors: NowDoors }) {
  return (
    <Page>
      <p className="aug-fs-h1 aug-lede">
        This page will hold the few things that need you each week, and say what it kept from you.
      </p>
      <div className="aug-item" style={{ marginTop: 16 }}>
        <div className="aug-fs-ui" style={{ color: "var(--t2)" }}>
          Nothing has been sent, held or asked yet. It fills once data is connected and a mission is written —
          what leaves the platform is then ranked by what bears on that mission.
        </div>
        <div className="aug-item-foot">
          <Button size="sm" onClick={doors.onOpenHome}>Start from Home</Button>
          <Button size="sm" variant="outline" onClick={doors.onOpenMissions}>Write a mission</Button>
        </div>
      </div>
    </Page>
  );
}
