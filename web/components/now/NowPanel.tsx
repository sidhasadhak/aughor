"use client";

/**
 * Now — "what needs me, this week?" (the 2027 study §V, screen 2), laid out to CLARITY (`aughor-v2/CLARITY.md`).
 *
 * Four figures (sent this week, waiting on you, held, corrected), then what waits on a person in amber with its
 * buttons on the row, then the week's slots as bars beside what lost one, then what was sent — the same send to
 * the same place folded into one row with its count — and what was corrected beside the Briefing. It is bounded
 * and it ends; a first run gets one line and the way to Home.
 *
 * Every row is a ledger entry read back — the departure gate's triage ranked it (code), and the hold is as much a
 * row as the send. Nothing is dropped to make it short: a fold says its count, the rest is behind Details, and a
 * read that failed says so where its rows would be.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { getDepartures, getJobs, getNeedsHuman, type Connection, type Departure, type JobRow, type NeedsHuman } from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { approverName } from "@/lib/auth";
import { getApiBase } from "@/lib/config";
import { owes, sourceName, summaryLine, whenText } from "@/lib/departures";
import { countNoun, endedDay, formatCount, normalizeNumberPrecision, relTime } from "@/lib/format";
import { dayWords } from "@/lib/home";
import { connectionLabel, destinationLabel, needsYouTitle } from "@/lib/names";
import {
  WAITING_CHANGED_EVENT, getAttentionBudget, getAttentionHeld, getCorrections, getSetAside, listDecisions,
  listInquiries, listMissions, restoreItem, setAttentionSlots, setItemAside, whoLabel,
  type AttentionBudget, type CorrectionEntry, type Corrections, type Decision, type HeldItem, type Inquiry,
  type Mission, type SetAside, type SetAsideKind,
} from "@/lib/record";
import { ActorField, Gate, day, dayDistance, useActor, useLoad, type Actor, type Load } from "@/components/record/kit";
import { ProposalCardById } from "@/components/ProposalCard";
import { InspectorHost, type Inspect, type InspectLayer } from "@/components/record/Inspector";
import {
  Bar, CARD, Card, Chip, Page, Empty, Figure, Figures, MUTED, NUM, NeedsYou, ONE_LINE, ROW, RULE,
} from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";

const LAST_SEEN_KEY = "aughor_now_last_seen";
const DEPARTURES_READ = 200;

/** One connection's row of the organisation's Briefing. The API puts a kept Briefing's fields on the row itself
 *  (`as_of`, `headline_theme`, `lede`) and `briefing: null` on a connection with none; an older shape nested them
 *  under `briefing`. Both are read — reading only the nested one said "no Briefing kept" over two kept ones. */
interface OrgBriefingRow {
  connection_id: string;
  connection_name: string;
  note?: string;
  briefing?: null | { as_of?: string; headline?: string; theme?: string; lede?: string };
  as_of?: string;
  headline_theme?: string;
  lede?: string;
  /** What the kept edition covers, and — for data that ENDED — the day it ended (2026-10-23). */
  covers?: string;
  data_ended?: boolean;
  data_through?: string | null;
}
interface OrgBriefing { briefings: OrgBriefingRow[]; with_briefing: number; connections: number }

export function keptBriefing(r: OrgBriefingRow): { as_of: string; headline: string; lede: string } | null {
  if (r.briefing === null) return null;
  const as_of = r.briefing?.as_of ?? r.as_of ?? "";
  const headline = r.briefing?.headline ?? r.briefing?.theme ?? r.headline_theme ?? "";
  const lede = r.briefing?.lede ?? r.lede ?? "";
  return as_of || headline || lede ? { as_of, headline, lede } : null;
}

interface Week {
  weekStart: string;
  sent: Departure[];
  budgets: AttentionBudget[];
  held: HeldItem[];
  /** The ledger read filled its page and its oldest row is still this week: more may have left. */
  capped: boolean;
  /** This API serves no departures ledger at all — said, never read as "nothing left". */
  noLedger: boolean;
}

async function readWeek(): Promise<Week> {
  const [rows, heldView] = await Promise.all([getDepartures({ limit: DEPARTURES_READ }), getAttentionHeld()]);
  const weekStart = heldView.week_start;
  const all = rows ?? [];
  const sent = all.filter(d => d.state === "departed" && d.ts.slice(0, 10) >= weekStart);
  const places = [...new Set([...sent.map(d => d.target), ...heldView.held.map(h => h.target)].filter(Boolean))];
  const budgets = await Promise.all(places.map(p => getAttentionBudget(p)));
  const capped = all.length >= DEPARTURES_READ && (all[all.length - 1]?.ts ?? "").slice(0, 10) >= weekStart;
  return { weekStart, sent, budgets, held: heldView.held, capped, noLedger: rows === null };
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
  /** A record's own page — where the inspector's "Open full page" goes. */
  onOpenRecord: (layer: InspectLayer, id: string) => void;
  /** Home — where a first run connects data and asks its first question. */
  onOpenHome: () => void;
  /** Agent Ops' Overview — every run, with its trace, cost and Stop. */
  onOpenAgentOps?: () => void;
}

/** A figure whose read is in flight or failed says that, in its own line — never a 0. */
function readState<T>(load: Load<T>, what: string): ReactNode | null {
  if (load.error) return <Chip tone="amber" title={load.error}>{what} could not be read</Chip>;
  if (load.data === null) return "reading…";
  return null;
}

export function NowPanel({ connections, contextReady, doors }: {
  connections: Connection[];
  /** False while the shell is still finding the workspace and its connections. */
  contextReady: boolean;
  doors: NowDoors;
}) {
  const week = useLoad(readWeek, []);
  const waiting = useLoad(readWaiting, []);
  const aside = useLoad(getSetAside, []);
  const corrections = useLoad(() => getCorrections({ limit: 60 }), []);
  const briefing = useLoad(readOrgBriefing, []);
  // What is running now, from the kernel's jobs — the record Agent Ops lists — on this workspace's connections
  // (the Olist study, Gaps 9 and 34: Now said "Nothing waits on you" through a live exploration of the workspace's
  // own data, and only the header's "1 live" knew).
  const running = useLoad(() => getJobs({ state: "active" }), []);
  useEffect(() => subscribeKernelEvents(() => running.reload(), { kinds: ["job.state"] }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []);
  const here = useMemo(() => new Set(connections.map(c => c.id)), [connections]);
  const runningHere: JobRow[] = (Array.isArray(running.data) ? running.data : []).filter(j => !!j.conn_id && here.has(j.conn_id));
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
  // A first visit reads the last seven days; the floor is fixed as the page arrives.
  const [weekAgo] = useState(() => new Date(Date.now() - 7 * 86_400_000).toISOString());
  const floor = since ?? weekAgo;

  const firstRun = contextReady && connections.filter(c => !c.builtin).length === 0
    && week.data !== null && week.data.sent.length === 0 && week.data.held.length === 0
    && waiting.data !== null && waiting.data.decisions.length + waiting.data.inquiries.length === 0;

  const restated = useMemo(() => (corrections.data ? splitCorrections(corrections.data, floor) : null),
    [corrections.data, floor]);

  if (firstRun) return <FirstRun doors={doors} />;

  const used = week.data?.budgets.reduce((n, b) => n + b.used, 0) ?? 0;
  const slots = week.data?.budgets.reduce((n, b) => n + b.slots, 0) ?? 0;
  const waitingCount = waiting.data ? waitingTotals(waiting.data, aside.data?.active ?? []) : null;
  const sinceWords = since ? `since your last visit, ${dayWords(since)}` : "in the last seven days";

  return (
    <InspectorHost connections={connections} pageKey="now" onOpenFull={doors.onOpenRecord}>
      {inspect => (
        <Page testId="now">
          <Figures testId="now-figures">
            <Figure testId="now-fig-sent" label="Sent this week" value={week.data ? formatCount(week.data.sent.length) : "—"}
              title={week.data ? `Everything that left the platform since ${dayWords(week.data.weekStart)}` : undefined}
              sub={readState(week, "the ledger") ?? (week.data!.noLedger
                ? <Chip tone="amber">this API serves no departures ledger</Chip>
                : <>
                    <span style={NUM}>{slots ? `${used} of ${slots} slots used` : "no place has slots yet"}</span>
                    {week.data!.capped && <Chip tone="amber" title={`The newest ${DEPARTURES_READ} departures are all this week's — more may have left`}>a floor</Chip>}
                  </>)} />
            <Figure testId="now-fig-waiting" label="Waiting on you"
              value={waitingCount ? formatCount(waitingCount.shown) : "—"}
              tone={waitingCount && waitingCount.shown > 0 ? "amber" : undefined}
              sub={readState(waiting, "what waits") ?? ([waitingCount!.shown ? waitingCount!.kinds : "nothing is due",
                waitingCount!.aside ? `${waitingCount!.aside} set aside` : ""].filter(Boolean).join(" · "))} />
            <Figure testId="now-fig-held" label="Held this week"
              title="What competed for a place's slot and lost — listed below with its score when there is any, never dropped silently"
              value={week.data ? formatCount(week.data.held.length) : "—"}
              sub={readState(week, "the holds") ?? (week.data!.held.length ? "lost a slot to something stronger" : "nothing lost a slot")} />
            <Figure testId="now-fig-corrected" label="Corrected" value={restated ? formatCount(restated.shown.length) : "—"}
              title="Restated, refuted, missed or outside its band — what you were told that changed"
              sub={readState(corrections, "the corrections") ?? sinceWords} />
          </Figures>

          <NeedsYou testId="now-needs" waiting={(waitingCount?.shown ?? 0) > 0 || !!waiting.error} right={waitingCount && waitingCount.shown > 0 ? `${countNoun(waitingCount.shown, "item")} · oldest first` : undefined}>
            <Gate load={waiting} what="what waits on a person">
              {w => <WaitingList waiting={w} aside={aside.data?.active ?? []} returned={aside.data?.returned ?? []}
                connections={connections} doors={doors} inspect={inspect} onResolved={waiting.reload}
                onAsideChanged={() => { aside.reload(); window.dispatchEvent(new Event(WAITING_CHANGED_EVENT)); }} />}
            </Gate>
          </NeedsYou>

          {runningHere.length > 0 && (
            <Card label="Running now" testId="now-running" right={countNoun(runningHere.length, "run")}>
              {runningHere.map((j, i) => (
                <div key={j.id} data-testid="now-running-row" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto",
                  gap: 12, alignItems: "center", padding: "7px 0", ...(i ? RULE : {}) }}>
                  <div style={{ minWidth: 0 }}>
                    <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>{j.title || j.kind}</div>
                    <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t2)" }}>
                      {j.agent?.agent || j.kind} · {connectionLabel(j.conn_id ?? "", connections)}
                      {j.started_at || j.created_at ? ` · started ${relTime(j.started_at || j.created_at || "")} ago` : ""}
                    </div>
                  </div>
                  {doors.onOpenAgentOps && (
                    <Button size="xs" variant="secondary" onClick={() => doors.onOpenAgentOps?.()}>Open in Agent Ops</Button>
                  )}
                </div>
              ))}
            </Card>
          )}

          {/* The picture — the week's slots, place by place — beside the Briefing in a line each. */}
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div style={{ flex: "1.4 1 420px", minWidth: 0 }}>
              <Card label="Slots this week" testId="now-slots"
                right={week.data ? `since ${dayWords(week.data.weekStart)}` : undefined}>
                <Gate load={week} what="this week's slots">
                  {w => <Slots week={w} onChanged={week.reload} />}
                </Gate>
              </Card>
            </div>
            <div style={{ flex: "1 1 300px", minWidth: 0 }}>
              <Card label="The Briefing" testId="now-briefing">
                <Gate load={briefing} what="the Briefing">
                  {b => <BriefingLines fold={b} doors={doors} />}
                </Gate>
              </Card>
            </div>
          </div>

          <Card label="Sent this week" testId="now-sent"
            right={<>
              {week.data && week.data.sent.length > 0 && <span>newest first</span>}
              <Button variant="link" size="xs" onClick={() => doors.onOpenDepartures()}>Every departure</Button>
            </>}>
            <Gate load={week} what="this week's sends">
              {w => <Sent week={w} missions={missions.data ?? []} connections={connections} doors={doors} />}
            </Gate>
          </Card>

          {/* What was held earns a card only when something was: with none, its figure above already says so. */}
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div style={{ flex: "1.4 1 420px", minWidth: 0 }}>
              <Card label="Since you were here" testId="now-restated"
                right={<Button variant="link" size="xs" onClick={doors.onOpenCorrections}>All corrections</Button>}>
                <Gate load={corrections} what="what was restated">
                  {c => <Restated split={restated ?? splitCorrections(c, floor)} labels={c.labels} inspect={inspect} />}
                </Gate>
              </Card>
            </div>
            {(week.error || (week.data?.held.length ?? 0) > 0) && (
              <div style={{ flex: "1 1 300px", minWidth: 0 }}>
                <Card label="Held this week" testId="now-held">
                  <Gate load={week} what="what was held">
                    {w => <Held held={w.held} doors={doors} />}
                  </Gate>
                </Card>
              </div>
            )}
          </div>
        </Page>
      )}
    </InspectorHost>
  );
}

// ── what waits on a person ───────────────────────────────────────────────────────────────

/** One row of "Waiting on you", whatever it is about, with the name a set-aside knows it by. */
interface WaitingRow {
  kind: SetAsideKind;
  /** The stable name: a decision's or an inquiry's key outlives its versions. */
  ref: string;
  /** What the set-aside door is given: the id the page holds today. */
  id: string;
  title: string;
}

function rowsOf(w: Waiting): WaitingRow[] {
  return [
    ...w.decisions.map(d => ({ kind: "decision" as const, ref: d.key, id: d.id, title: `What became of “${d.chosen}”?` })),
    ...w.inquiries.map(q => ({ kind: "inquiry" as const, ref: q.key, id: q.id, title: q.question })),
    ...w.departures.map(d => ({ kind: "departure" as const, ref: d.id, id: d.id, title: summaryLine(d) })),
    ...w.needs.rows.map(r => ({ kind: "approval" as const, ref: `${r.source}:${r.id}`, id: `${r.source}:${r.id}`, title: needsYouTitle(r.title).display })),
  ];
}

const asideKey = (kind: string, ref: string) => `${kind}:${ref}`;

const KIND_NOUN: Record<SetAsideKind, [string, string]> = {
  decision: ["review", "reviews"], inquiry: ["inquiry", "inquiries"], departure: ["send", "sends"],
  approval: ["approval", "approvals"],
};

/** How many wait, how many were set aside, and what the waiting ones are: "1 review · 2 approvals". */
export function waitingTotals(w: Waiting, active: SetAside[]): { shown: number; aside: number; kinds: string } {
  const hidden = new Set(active.map(a => asideKey(a.item_kind, a.ref)));
  const rows = rowsOf(w);
  const waitingRows = rows.filter(r => !hidden.has(asideKey(r.kind, r.ref)));
  const counts = new Map<SetAsideKind, number>();
  for (const r of waitingRows) counts.set(r.kind, (counts.get(r.kind) ?? 0) + 1);
  const kinds = [...counts.entries()].map(([k, n]) => countNoun(n, KIND_NOUN[k][0], KIND_NOUN[k][1])).join(" · ");
  return { shown: waitingRows.length, aside: rows.length - waitingRows.length, kinds };
}

const tomorrow = () => new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

/**
 * "Not now": the row leaves this list until a day the person picks, with why. Nothing about the
 * thing itself is written — a review set aside is still due on its own page — and it comes back
 * on that day, or sooner if the record behind it changes.
 */
function NotNow({ row, actor, onDone, onCancel }: {
  row: WaitingRow; actor: Actor; onDone: () => void; onCancel: () => void;
}) {
  const [until, setUntil] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await setItemAside({ kind: row.kind, ref: row.id, until, why: why.trim(), title: row.title });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
      <span className="aug-fs-sm" style={MUTED}>Not until</span>
      <Input type="date" aria-label="Set aside until" min={tomorrow()} value={until} onChange={e => setUntil(e.target.value)} style={{ width: 160 }} />
      <Input aria-label="Why it is set aside" value={why} onChange={e => setWhy(e.target.value)} placeholder="Why — what it waits for" style={{ flex: "1 1 240px" }} />
      <ActorField actor={actor} id={`aside-by-${row.kind}-${row.id}`} />
      <Button size="xs" disabled={busy || !until || !why.trim()} onClick={() => void submit()}
        title="It comes back on that day, or sooner if what it rests on changes. Nothing is recorded on the item itself.">
        Set aside
      </Button>
      <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
      {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", flexBasis: "100%" }}>{error}</span>}
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

/** One waiting row: what it is (the full text on hover), one muted line, and its buttons on the row. */
function WaitRow({ testId, title, onTitle, meta, buttons, below, first }: {
  testId?: string; title: string; onTitle?: () => void; meta: ReactNode; buttons: ReactNode; below?: ReactNode; first: boolean;
}) {
  return (
    <div data-testid={testId} style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <div style={{ minWidth: 0 }} title={title}>
          {onTitle ? (
            <Button variant="link" size="xs" className="aug-ledger-open" onClick={onTitle}
              style={{ ...ONE_LINE, display: "block", maxWidth: "100%", color: "var(--t1)" }}>{title}</Button>
          ) : (
            <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{title}</div>
          )}
          <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)" }}>{meta}</div>
        </div>
        <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>{buttons}</span>
      </div>
      {below}
    </div>
  );
}

function WaitingList({ waiting, aside, returned, connections, doors, inspect, onResolved, onAsideChanged }: {
  waiting: Waiting; connections: Connection[]; doors: NowDoors;
  /** Read a row's record beside this page; its own button is what leaves for the page it is dealt with on. */
  inspect: Inspect;
  /** What a person set aside and is still off the list; what was set aside and is back. */
  aside: SetAside[]; returned: SetAside[];
  /** An approval was decided here; the list re-reads. */
  onResolved: () => void;
  onAsideChanged: () => void;
}) {
  const actor = useActor();
  // The proposed action a person is deciding in place — the same card Attention shows, so what
  // either click does is read before it is clicked.
  const [deciding, setDeciding] = useState("");
  const [decided, setDecided] = useState("");
  const [deferring, setDeferring] = useState("");
  const [showAside, setShowAside] = useState(false);
  const [error, setError] = useState("");

  const hidden = new Map(aside.map(a => [asideKey(a.item_kind, a.ref), a]));
  const back = new Map(returned.map(a => [asideKey(a.item_kind, a.ref), a]));
  const rows = rowsOf(waiting);
  const rowFor = (kind: SetAsideKind, ref: string) => rows.find(r => r.kind === kind && r.ref === ref)!;
  const isHidden = (kind: SetAsideKind, ref: string) => hidden.has(asideKey(kind, ref));
  // Only what still waits can be set aside: one dealt with on its own page has left both lists.
  const asideRows = rows.filter(r => isHidden(r.kind, r.ref)).map(r => ({ row: r, a: hidden.get(asideKey(r.kind, r.ref))! }));
  const shown = rows.length - asideRows.length;
  let n = 0;
  const first = () => n++ === 0;

  /** The "Not now" button every row carries, the form it opens, and — for a row that came back — why. */
  const notNow = (kind: SetAsideKind, ref: string) => {
    const row = rowFor(kind, ref);
    const key = asideKey(kind, ref);
    const b = back.get(key);
    return {
      button: <Button size="xs" variant="ghost" aria-expanded={deferring === key} onClick={() => setDeferring(x => (x === key ? "" : key))}>Not now</Button>,
      form: deferring === key && (
        <NotNow row={row} actor={actor} onCancel={() => setDeferring("")}
          onDone={() => { setDeferring(""); setDecided("Set aside. It is listed below until its day."); onAsideChanged(); }} />
      ),
      // It was set aside and is here again: say so, and why.
      note: b && (
        <Chip tone="amber" title={`Set aside by ${whoLabel(b.by)}: ${b.why}`}>
          back {b.back_because.startsWith("its day came") ? "on its day" : `early: ${b.back_because}`}
        </Chip>
      ),
    };
  };
  const restore = async (a: SetAside) => {
    setError("");
    try { await restoreItem(a.item_kind, a.ref); onAsideChanged(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div>
      {decided && <p className="aug-fs-sm" role="status" style={{ color: "var(--t2)", margin: "0 0 8px" }}>{decided}</p>}
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 8px" }}>{error}</p>}
      {shown === 0 && (
        <Empty title="Checked: review dates that have come, inquiries due, sends waiting on an answer, and open approvals">
          {asideRows.length ? "Nothing else waits on you." : "Nothing waits on you."}
        </Empty>
      )}
      {waiting.decisions.filter(d => !isHidden("decision", d.key)).map(d => {
        const x = notNow("decision", d.key);
        return (
          <WaitRow key={`decision:${d.id}`} first={first()} title={`What became of “${d.chosen}”?`}
            onTitle={() => inspect("decisions", d.id)}
            meta={<><span>decision · review {dayWords(d.review_on)}{dayDistance(d.review_on) ? ` · ${dayDistance(d.review_on)}` : ""} · by {whoLabel(d.decided_by)}</span>{x.note}</>}
            buttons={<>{x.button}<Button size="xs" variant="secondary" onClick={() => doors.onOpenDecision(d.id)}>Open the decision</Button></>}
            below={x.form} />
        );
      })}
      {waiting.inquiries.filter(q => !isHidden("inquiry", q.key)).map(q => {
        const x = notNow("inquiry", q.key);
        return (
          <WaitRow key={`inquiry:${q.id}`} first={first()} title={q.question} onTitle={() => inspect("inquiries", q.id)}
            meta={<><span>inquiry · check date {day(q.next_check)}{q.waiting_for ? ` · was waiting for ${q.waiting_for}` : ""}</span>{x.note}</>}
            buttons={<>{x.button}<Button size="xs" variant="secondary" onClick={() => doors.onOpenInquiry(q.id)}>Open the inquiry</Button></>}
            below={x.form} />
        );
      })}
      {waiting.departures.filter(d => !isHidden("departure", d.id)).map(d => {
        const x = notNow("departure", d.id);
        const answer = owes(d) === "answer";
        return (
          <WaitRow key={`departure:${d.id}`} first={first()} title={summaryLine(d)}
            meta={<><span>{answer ? "an owner's answer is needed" : "its declarer marks it right or wrong"}{d.target ? ` · ${destinationLabel(d.target).label}` : ""}</span>{x.note}</>}
            buttons={<>{x.button}<Button size="xs" variant="secondary" onClick={() => doors.onOpenDepartures(d.id)}>{answer ? "Answer" : "Mark it"}</Button></>}
            below={x.form} />
        );
      })}
      {waiting.needs.rows.filter(r => !isHidden("approval", `${r.source}:${r.id}`)).map(r => {
        const t = needsYouTitle(r.title);
        const x = notNow("approval", `${r.source}:${r.id}`);
        const proposal = r.source === "kinetic_inbox";
        return (
          <WaitRow key={`needs:${r.source}:${r.id}`} first={first()} title={t.display}
            meta={<>
              <span>{NEEDS_WORDS[r.source] ?? "an action waits for approval"}
                {r.connection_id ? ` · ${connectionLabel(r.connection_id, connections)}` : ""}
                {r.since ? ` · since ${whenText(r.since)}` : ""}</span>
              {x.note}
            </>}
            buttons={<>
              {x.button}
              {proposal
                ? <Button size="xs" variant="secondary" aria-expanded={deciding === r.id}
                    onClick={() => setDeciding(v => (v === r.id ? "" : r.id))}>{deciding === r.id ? "Close" : "Review and decide"}</Button>
                : <Button size="xs" variant="secondary" onClick={doors.onOpenAttention}>Resolve</Button>}
            </>}
            below={<>
              {x.form}
              {deciding === r.id && (
                <div style={{ marginTop: 8 }}>
                  <ProposalCardById proposalId={r.id} actor={approverName("now")}
                    onResolved={(status, message) => { setDecided(message); if (status === "ok") { setDeciding(""); onResolved(); } }} />
                </div>
              )}
            </>} />
        );
      })}
      {asideRows.length > 0 && (
        <div data-testid="now-set-aside" style={{ paddingTop: 8, ...RULE }}>
          <div style={{ ...ROW, gap: 10 }}>
            <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
              {countNoun(asideRows.length, "item")} set aside · the next back {dayWords(asideRows.map(x => x.a.until).sort()[0])}
            </span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="ghost" aria-expanded={showAside} onClick={() => setShowAside(v => !v)}>{showAside ? "Hide" : "Show"}</Button>
          </div>
          {showAside && asideRows.map(({ row, a }) => (
            <WaitRow key={asideKey(row.kind, row.ref)} first={false} title={row.title}
              meta={<span title={a.why}>{`by ${whoLabel(a.by)} until ${dayWords(a.until)} · ${dayDistance(a.until)} · ${a.why}`}</span>}
              buttons={<Button size="xs" variant="outline" onClick={() => void restore(a)}>Restore</Button>} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── the week's slots, as bars ────────────────────────────────────────────────────────────

function Slots({ week, onChanged }: { week: Week; onChanged: () => void }) {
  if (week.budgets.length === 0) {
    return (
      <Empty title="A send that passes the departure gate uses one of its place's slots and is listed with why it won.">
        Nothing used a slot since {dayWords(week.weekStart)}.
      </Empty>
    );
  }
  return (
    <div>
      {week.budgets.map((b, i) => <Place key={b.addressee} budget={b} first={i === 0} onChanged={onChanged} />)}
    </div>
  );
}

function Place({ budget, first, onChanged }: { budget: AttentionBudget; first: boolean; onChanged: () => void }) {
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
  const full = budget.left === 0;
  return (
    <div data-testid="now-place" style={{ padding: "8px 0", ...(first ? {} : RULE) }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(90px, 160px) minmax(0, 1fr) auto auto", gap: 12, alignItems: "center" }}>
        <span className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }} title={budget.addressee}>
          {destinationLabel(budget.addressee).label}
        </span>
        <Bar value={budget.used} max={budget.slots} color={full ? "var(--amb3)" : "var(--chart-1)"} />
        <span className="aug-fs-sm" style={{ ...NUM, color: full ? "var(--amb4)" : "var(--t2)", whiteSpace: "nowrap" }}>
          {budget.used} of {budget.slots}
          {budget.held_count > 0 && <span style={MUTED}> · {budget.held_count} held</span>}
        </span>
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
    </div>
  );
}

// ── what was held ────────────────────────────────────────────────────────────────────────

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

function Held({ held, doors }: { held: HeldItem[]; doors: NowDoors }) {
  if (held.length === 0) {
    return (
      <Empty title="When a place's slots are used, what is held is listed here with its score — never dropped silently.">
        Nothing lost a slot this week.
      </Empty>
    );
  }
  return (
    <div>
      {held.map((h, i) => (
        <div key={h.departure_id} data-testid="now-held-row" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto",
          gap: 12, alignItems: "center", padding: "8px 0", ...(i ? RULE : {}) }}>
          <div style={{ minWidth: 0 }}>
            <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }} title={h.text}>{firstLine(h.text)}</div>
            <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t2)" }} title={`${h.why} — ${h.triage}`}>
              {h.why} · {triageWords(h.triage)} · from {h.by || "an automation"}
            </div>
          </div>
          <Button size="xs" variant="ghost" onClick={() => doors.onOpenDepartures(h.departure_id)}>Open</Button>
        </div>
      ))}
    </div>
  );
}

// ── what was sent, folded ────────────────────────────────────────────────────────────────

/** The first line of a send, without Markdown's heading marks: a short label; the whole text is on hover. */
function firstLine(text: string): string {
  return (text || "").split("\n").map(l => l.replace(/^#+\s*/, "").trim()).find(Boolean) ?? "";
}

/** The mission a departure bore on, by name — the gate writes the ids it charged on the row. */
function bearingText(d: Departure, missions: Mission[]): string {
  const noted = d.checks.mission ?? "";
  if (!noted) return "no mission";
  const named = missions.filter(m => noted.includes(m.id) || noted.includes(m.key) || noted.includes(m.name));
  return named.length ? `bears on ${named.map(m => m.name).join(", ")}` : noted;
}

export interface SendGroup { key: string; source: string; target: string; sends: Departure[] }

/** The same source sending to the same place, folded into one row (CLARITY: say a thing once). Newest first. */
export function foldSends(sent: Departure[]): SendGroup[] {
  const groups = new Map<string, SendGroup>();
  for (const d of [...sent].sort((a, b) => b.ts.localeCompare(a.ts))) {
    const source = sourceName(d);
    const key = `${source}\u0000${d.target}`;
    const g = groups.get(key) ?? { key, source, target: d.target, sends: [] };
    g.sends.push(d);
    groups.set(key, g);
  }
  return [...groups.values()];
}

/** A fact the rows of a fold share, said once; when they differ, say that they do. */
function shared(values: string[], differ: string): string {
  const set = [...new Set(values.filter(Boolean))];
  return set.length <= 1 ? (set[0] ?? "") : differ;
}

function Sent({ week, missions, connections, doors }: {
  week: Week; missions: Mission[]; connections: Connection[]; doors: NowDoors;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (week.noLedger) return <Empty>This API serves no departures ledger, so what left is not known here.</Empty>;
  if (week.sent.length === 0) return <Empty>Nothing left the platform since {dayWords(week.weekStart)}.</Empty>;
  const groups = foldSends(week.sent);
  return (
    <div>
      {groups.map((g, i) => {
        const latest = g.sends[0];
        const place = g.target ? destinationLabel(g.target).label : "";
        const bearing = shared(g.sends.map(d => bearingText(d, missions)), "bears on more than one mission");
        const ranked = shared(g.sends.map(d => (d.checks.triage ? triageWords(d.checks.triage) : "")), "ranked differently each time");
        const expanded = open === g.key;
        return (
          <div key={g.key} data-testid="now-send-group" style={{ padding: "8px 0", ...(i ? RULE : {}) }}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 12, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <Button variant="ghost" size="xs" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : g.key)}
                  title={expanded ? "Hide each send" : "Each send"}
                  style={{ height: "auto", padding: 0, margin: 0, gap: 6, color: "var(--t1)", fontWeight: 500, maxWidth: "100%" }}>
                  <span className="aug-fs-chrome" style={ONE_LINE}>{g.source}</span>
                  <Icon name={expanded ? "chevu" : "chevd"} size={12} />
                </Button>
                <div className="aug-fs-xs" style={{ ...ROW, gap: 6, color: "var(--t2)" }}>
                  {place ? <span>→ {place}</span>
                    : <Chip title="It left without a place recorded, so it used no place's slot">no place · used no slot</Chip>}
                  {bearing && <span>· {bearing}</span>}
                  {ranked && <span title={latest.checks.triage}>· {ranked}</span>}
                  <span>· latest {dayWords(latest.ts)} {whenText(latest.ts).slice(11)}</span>
                </div>
              </div>
              <span className="aug-fs-chrome" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>
                {g.sends.length > 1 ? `×${g.sends.length}` : ""}
              </span>
              <Button size="xs" variant="secondary" onClick={() => doors.onOpenDepartures(latest.id)}
                title="Every check it passed, and the analysis behind it">Receipt</Button>
            </div>
            {expanded && (
              <div style={{ marginTop: 6, paddingLeft: 12, borderLeft: "2px solid var(--b1)" }}>
                {g.sends.map(d => (
                  <div key={d.id} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 10, alignItems: "center",
                    padding: "4px 0" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="aug-fs-sm" style={{ ...ONE_LINE, color: "var(--t1)" }} title={d.text_preview}>
                        {firstLine(d.text_preview)}
                      </div>
                      <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t3)" }}>
                        {whenText(d.ts)}{d.conn_id ? ` · ${connectionLabel(d.conn_id, connections)}` : ""} · {summaryLine(d)}
                      </div>
                    </div>
                    <Button size="xs" variant="ghost" onClick={() => doors.onOpenDepartures(d.id)}>Open its receipt</Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {week.capped && (
        <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 6, ...RULE }}>
          The newest {DEPARTURES_READ} departures are all this week&apos;s — earlier sends this week are not read here.
        </div>
      )}
    </div>
  );
}

// ── since you were here ──────────────────────────────────────────────────────────────────

interface Split {
  /** What changed in what you were told, since the floor — newest first. */
  shown: CorrectionEntry[];
  /** Restated with the same words: re-issued, nothing said differently. Counted, not listed. */
  unchanged: number;
  /** The read held its whole page inside the floor: there may be more. */
  capped: boolean;
}

export function splitCorrections(c: Corrections, floor: string): Split {
  const recent = c.entries.filter(e => e.at >= floor);
  return {
    shown: recent.filter(e => e.believed !== e.replaced_by),
    unchanged: recent.filter(e => e.believed === e.replaced_by).length,
    capped: c.entries.length >= 60 && recent.length === c.entries.length,
  };
}

/** The metric a prediction named — `expected: Revenue $11,330 to …` reads "Revenue". */
function metricOf(e: CorrectionEntry): string {
  const m = /^expected:\s*(.+?)\s+(?:[$€£¥]|-?\d)/.exec(e.believed);
  return m?.[1] ?? e.metric ?? "";
}

function Restated({ split, labels, inspect }: {
  split: Split; labels: Record<string, string>; inspect: Inspect;
}) {
  const [details, setDetails] = useState(false);
  // What a correction is about, when it is a record the drawer can read.
  const target = (e: CorrectionEntry): [InspectLayer, string] | null =>
    e.kind === "decision_worse_than_expected" && e.decision ? ["decisions", e.decision]
      : e.kind !== "missed_move" && e.ref ? ["claims", e.ref] : null;
  const byKind = new Map<string, CorrectionEntry[]>();
  for (const e of split.shown) byKind.set(e.kind, [...(byKind.get(e.kind) ?? []), e]);

  const noise = split.unchanged > 0 && (
    <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: split.shown.length ? 6 : 2 }}
      title="Restated with the same words as before — nothing you were told changed">
      {countNoun(split.unchanged, "more was", "more were")} re-issued with the same words
    </div>
  );
  if (split.shown.length === 0) {
    return (
      <>
        <Empty>Nothing you were told has been restated, refuted or missed since then.</Empty>
        {noise}
      </>
    );
  }
  return (
    <div>
      {[...byKind.entries()].map(([kind, entries], i) => {
        const metrics = [...new Set(entries.map(metricOf).filter(Boolean))];
        return (
          <div key={kind} data-testid="now-correction-kind" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto",
            gap: 12, alignItems: "center", padding: "8px 0", ...(i ? RULE : {}) }}>
            <div style={{ minWidth: 0 }}>
              <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)" }}>{labels[kind] ?? kind}</div>
              <div className="aug-fs-xs" style={{ ...ROW, gap: 5, color: "var(--t2)", marginTop: 2 }}>
                {metrics.slice(0, 4).map(m => <Chip key={m}>{m}</Chip>)}
                {metrics.length > 4 && <Chip title={metrics.slice(4).join(", ")}>+{metrics.length - 4}</Chip>}
                <span>{metrics.length ? "· " : ""}latest {dayWords(entries[0].at)}</span>
              </div>
            </div>
            <span className="aug-fs-chrome" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>{formatCount(entries.length)}</span>
          </div>
        );
      })}
      {noise}
      {split.capped && (
        <div className="aug-fs-xs" style={MUTED}>a floor · the read held its newest 60, all since then</div>
      )}
      <div style={{ paddingTop: 6, ...RULE }}>
        <Button variant="ghost" size="xs" aria-expanded={details} onClick={() => setDetails(v => !v)}
          style={{ margin: 0, padding: 0, height: "auto", color: "var(--t2)" }}>
          Details <Icon name={details ? "chevu" : "chevd"} size={12} />
        </Button>
        {details && (
          <div style={{ marginTop: 4 }}>
            {split.shown.slice(0, 8).map(e => {
              const t = target(e);
              const what = `${metricOf(e) ? `${metricOf(e)}: ` : ""}${normalizeNumberPrecision(e.replaced_by)}`;
              return (
                <div key={`${e.kind}:${e.ref}:${e.at}`} style={{ padding: "4px 0" }}>
                  <div className="aug-fs-sm" style={{ ...ONE_LINE, color: "var(--t1)" }} title={what}>
                    {t ? <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => inspect(...t)}>{what}</Button> : what}
                  </div>
                  <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t3)" }} title={e.believed}>
                    was: {normalizeNumberPrecision(e.believed)} · {whenText(e.at)}
                  </div>
                </div>
              );
            })}
            {split.shown.length > 8 && (
              <div className="aug-fs-xs" style={MUTED}>+{split.shown.length - 8} more in All corrections</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── the Briefing, a line each ────────────────────────────────────────────────────────────

function BriefingLines({ fold, doors }: { fold: OrgBriefing; doors: NowDoors }) {
  const kept = fold.briefings.map(b => ({ b, k: keptBriefing(b) })).filter(x => x.k !== null);
  const none = fold.briefings.filter(b => keptBriefing(b) === null);
  if (kept.length === 0) {
    return (
      <div style={{ ...ROW, justifyContent: "space-between" }}>
        <Empty title="One is kept the first time a Briefing is built.">
          No Briefing kept yet for any of the {countNoun(fold.connections, "connection")}.
        </Empty>
        <Button size="xs" variant="secondary" onClick={() => doors.onOpenBriefing()}>Open the Briefing</Button>
      </div>
    );
  }
  return (
    <div>
      {kept.map(({ b, k }, i) => (
        <div key={b.connection_id} data-testid="now-briefing-row" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto",
          gap: 12, alignItems: "center", padding: "8px 0", ...(i ? RULE : {}) }}>
          <div style={{ minWidth: 0 }} title={k!.lede || k!.headline}>
            <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{k!.headline || firstLine(k!.lede)}</div>
            <div className="aug-fs-xs" style={{ ...ONE_LINE, color: "var(--t2)" }}>
              {b.connection_name}
              {/* An edition about data that ENDED names its days and where the data ended, so it is not
                  read as this week's news: "Olist · September 2018 · data ended Wed 17 Oct 2018". */}
              {b.data_ended && b.covers ? ` · ${b.covers}` : ""}
              {b.data_ended && b.data_through
                ? <span data-testid="now-data-ended"> · data ended {endedDay(b.data_through)}</span>
                : k!.as_of ? ` · as of ${dayWords(k!.as_of)}` : ""}
            </div>
          </div>
          <Button size="xs" variant="secondary" onClick={() => doors.onOpenBriefing(b.connection_id)}>Read</Button>
        </div>
      ))}
      {none.length > 0 && (
        <div className="aug-fs-xs" style={{ ...MUTED, paddingTop: 6, ...RULE }} title={none.map(b => b.connection_name).join(", ")}>
          {countNoun(none.length, "connection")} {none.length === 1 ? "has" : "have"} no Briefing kept yet
        </div>
      )}
    </div>
  );
}

// ── a first run ──────────────────────────────────────────────────────────────────────────

/** Nothing has been sent, held or asked yet. Home is where a first run starts; this page only says
 *  what it will hold once there is something to hold. */
function FirstRun({ doors }: { doors: NowDoors }) {
  return (
    <Page testId="now-first-run">
      <section aria-label="Now" style={CARD}>
        <div className="aug-fs-chrome" style={{ color: "var(--t1)", fontWeight: 500 }}>Nothing has been sent, held or asked yet.</div>
        <div className="aug-fs-sm" style={{ ...MUTED, margin: "2px 0 10px" }}
          title="What leaves the platform is then ranked by what bears on that mission.">
          It fills once data is connected and a mission is written.
        </div>
        <div style={ROW}>
          <Button size="sm" onClick={doors.onOpenHome}>Start from Home</Button>
          <Button size="sm" variant="outline" onClick={doors.onOpenMissions}>Write a mission</Button>
        </div>
      </section>
    </Page>
  );
}
