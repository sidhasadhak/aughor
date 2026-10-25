"use client";

/**
 * Decisions — "what are we choosing, and what did we choose?" (the 2027 study §V, screens 5
 * and 6).
 *
 * The decision is the organisation's: the question and who is answerable, the options side by
 * side, what it relied on as recorded at that moment, the dissent kept, the expectation booked
 * when it was taken and the date it is reviewed on — and, after that date, what became of it
 * against the expectation and against the baseline.
 *
 * A scenario has no page of its own. It lives inside the decision it was projected for: its
 * assumptions with whose they are, each prediction with the method that produced it and what
 * that method must say, the limits in words, and what each will be scored against.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatCount, formatTableNumber, pct } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import { requestTab } from "@/lib/navigate";
import {
  amendDecision, bookOutcome, bookScenario, confirmMeetingCandidate, declareDecision, declareDecisionKind, decisionStands,
  getCalibration, getDecision, getPastCases, getThread, listDecisionKinds, listDecisions, listMeetingCandidates, listScenarios,
  plainWho, proposeMeetingCandidates, refuseMeetingCandidate, verdictWords, whoLabel, type MeetingCandidate,
  type CalibrationRow, type Claim, type Decision, type DecisionDetail, type DecisionKind, type OutcomeVerdict, type Scenario,
  type ThreadLink, type ThreadStep,
  type ScenarioBody,
} from "@/lib/record";
import {
  Absent, ActorField, BackHeader, ClaimLine, Fact, Gate, ListCard, ListRow, Page, Section, day, dayDistance, daysUntil,
  useActor, useLoad,
  type Actor, type ListColumn,
} from "@/components/record/kit";
import {
  CARD, Chip, Dot, Figure, Figures, NUM, NeedsRow, NeedsYou, Page as ClarityPage,
} from "@/components/clarity/kit";
import { chosenWords, countBy, dateWords, distanceWords, shortLabel, whenWords } from "@/components/record/words";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Segmented } from "@/components/ui/segmented";
import { Callout } from "@/components/ui/callout";

type Filter = "all" | "due" | "waiting" | "reviewed";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "due", label: "Review due" },
  { id: "waiting", label: "Awaiting its date" },
  { id: "reviewed", label: "Reviewed" },
];

/** Where a decision stands against its review date. */
export function reviewState(d: Pick<Decision, "outcome" | "review_on">): "reviewed" | "due" | "waiting" {
  if (d.outcome) return "reviewed";
  const n = daysUntil(d.review_on);
  return n !== null && n <= 0 ? "due" : "waiting";
}

const REVIEW_HUE: Record<string, ChipHue> = { reviewed: "muted", due: "caution", waiting: "info" };
const REVIEW_WORDS: Record<string, string> = { reviewed: "reviewed", due: "review due", waiting: "awaiting its date" };
const VERDICT_HUE: Record<string, ChipHue> = { as_expected: "positive", better: "positive", worse: "negative", missed: "caution", cannot_tell: "muted" };

const SOURCE_WORDS: Record<string, string> = {
  declared: "declared in a sentence",
  recommendation: "by accepting a recommendation",
  approval: "by approving an action",
  reply: "by a reply",
};

export function DecisionsPanel({ connections, selectedConn, openId, onOpen, onOpenClaim }: {
  connections: Connection[];
  selectedConn: string;
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenClaim: (id: string) => void;
}) {
  if (openId) {
    return <DecisionReader id={openId} connections={connections} onBack={() => onOpen(null)} onMoved={onOpen} onOpenClaim={onOpenClaim} />;
  }
  return <DecisionLedger connections={connections} selectedConn={selectedConn} onOpen={onOpen} />;
}

function DecisionLedger({ connections, selectedConn, onOpen }: {
  connections: Connection[]; selectedConn: string; onOpen: (id: string) => void;
}) {
  const [declaring, setDeclaring] = useState(false);
  const load = useLoad(() => listDecisions({ limit: 300 }), []);
  // The form appears only when a person asks for it (CLARITY: read first, edit behind a button).
  const form = declaring && (
    <section aria-label="Record a decision" style={CARD}>
      <DeclareForm connectionId={selectedConn} onCancel={() => setDeclaring(false)}
        onBooked={d => { setDeclaring(false); load.reload(); onOpen(d.id); }} />
    </section>
  );
  return (
    <ClarityPage testId="decisions-page">
      <Gate load={load} what="decisions">
        {all => <DecisionOverview all={all} connections={connections} onOpen={onOpen} form={form}
          declaring={declaring} onDeclare={() => setDeclaring(v => !v)} />}
      </Gate>
      <KindsSection />
      <MeetingSection connectionId={selectedConn} onOpen={onOpen} />
    </ClarityPage>
  );
}

/** The words a kind's key reads as — `decision_kind:a_price_change` → "a price change". */
export function kindWords(key: string | undefined): string {
  return (key ?? "").replace(/^decision_kind:/, "").replace(/_/g, " ");
}

/** The kinds of decision the organisation declared (the decision-framework study §3.1): who approves one, whether it
 *  must say what it expects, when it is reviewed, the metrics it usually moves. People declare them; a model never does.
 *  A decision of a kind keeps its kind's rules, and past decisions of the same kind are the next one's base rate. */
function KindsSection() {
  const load = useLoad(() => listDecisionKinds(), []);
  const [open, setOpen] = useState(false);
  return (
    <Section label="Kinds of decision" meta={load.data ? countNoun(load.data.kinds.filter(k => k.state === "active").length, "kind") : undefined}
      action={<Button size="xs" variant="secondary" onClick={() => setOpen(v => !v)}>{open ? "Close" : "Declare a kind"}</Button>}>
      {open && <KindForm onDeclared={() => { setOpen(false); load.reload(); }} />}
      <Gate load={load} what="the kinds of decision">
        {r => r.kinds.length === 0 ? (
          <Absent>None declared. A kind says who approves a decision of it, whether it must say what it expects, and when it is
            reviewed — and past decisions of the same kind become what the next one is projected from.</Absent>
        ) : (
          <div data-testid="decision-kinds">
            {r.kinds.map(k => (
              <div className="aug-item" key={k.key}>
                <div className="aug-fs-ui" style={{ color: k.state === "active" ? "var(--t1)" : "var(--t3)" }}>
                  {k.name}{k.state === "retired" ? " · retired" : ""}
                </div>
                <div className="aug-item-foot aug-fs-sm">
                  <span>{k.metrics.length ? `moves ${k.metrics.join(", ")}` : "names no metric"}</span>
                  <span>{`reviewed after ${k.review_days} days`}</span>
                  {k.expectation_required && <span>must say what it expects</span>}
                  {k.approvers.length > 0 && <span>{`approved by ${k.approvers.map(a => whoLabel(a)).join(", ")}`}</span>}
                  <span>{`declared by ${whoLabel(k.declared_by)}`}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Gate>
    </Section>
  );
}

/** Decisions taken in a meeting (the decision-framework study §3.2): a person brings the notes, the model reads them
 *  once and proposes the decisions it finds, and each is confirmed — booked as the person's decision, dated the
 *  meeting's day — or refused and kept with why. Nothing is booked before a person confirms. */
function MeetingSection({ connectionId, onOpen }: { connectionId: string; onOpen: (id: string) => void }) {
  const load = useLoad(() => listMeetingCandidates({ status: "proposed" }), []);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [heldOn, setHeldOn] = useState("");
  const [notes, setNotes] = useState("");
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const read = async () => {
    setBusy(true); setSaid("");
    try {
      const out = await proposeMeetingCandidates({ connection_id: connectionId, title: title.trim(), held_on: heldOn, text: notes,
                                                   share_quotes: share });
      setSaid([`${countNoun(out.candidates.length, "decision")} proposed from “${title.trim()}”`, out.cut,
               out.dropped ? `${out.dropped} with no question left out` : ""].filter(Boolean).join(" · "));
      setOpen(false); setNotes(""); load.reload();
    } catch (e) { setSaid(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <Section label="Decisions from a meeting" meta={load.data ? countNoun(load.data.candidates.length, "to confirm", "to confirm") : undefined}
      action={<Button size="xs" variant="secondary" onClick={() => setOpen(v => !v)}>{open ? "Close" : "Bring a meeting's notes"}</Button>}>
      {open && (
        <div className="aug-form-grid" data-testid="meeting-form" style={{ marginBottom: 12 }}>
          <label className="aug-fs-sm" htmlFor="mt-t">The meeting</label>
          <Input id="mt-t" value={title} onChange={e => setTitle(e.target.value)} placeholder="Weekly trading" />
          <label className="aug-fs-sm" htmlFor="mt-d">Held on</label>
          <Input id="mt-d" type="date" value={heldOn} onChange={e => setHeldOn(e.target.value)} style={{ width: 170 }} />
          <label className="aug-fs-sm" htmlFor="mt-n">Its notes</label>
          <Textarea id="mt-n" value={notes} onChange={e => setNotes(e.target.value)} rows={8}
            placeholder="Paste the notes or the transcript — nothing is fetched from a mailbox, a calendar or a drive" />
          <span />
          <label className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Checkbox checked={share} onChange={e => setShare(e.target.checked)} aria-label="Keep the quoted lines" />
            Keep the lines each decision was read from — otherwise only a hash of the notes is kept
          </label>
          <span />
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Button size="xs" disabled={busy || !title.trim() || !heldOn || !notes.trim()} onClick={() => void read()}>Find the decisions</Button>
            <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>One model call reads the notes. It proposes; nothing is booked until you confirm.</span>
          </div>
        </div>
      )}
      {said && <div className="aug-fs-sm" style={{ color: "var(--t2)", marginBottom: 8 }}>{said}</div>}
      <Gate load={load} what="the meeting's proposals">
        {r => r.candidates.length === 0 ? (
          <Absent>Nothing waits to be confirmed. Bring a meeting&apos;s notes and the decisions in them are proposed here, each for a
            person to confirm or refuse.</Absent>
        ) : (
          <div data-testid="meeting-candidates">
            {r.candidates.map(c => <CandidateRow key={c.id} c={c} onAnswered={load.reload} onOpen={onOpen} />)}
          </div>
        )}
      </Gate>
    </Section>
  );
}

function CandidateRow({ c, onAnswered, onOpen }: { c: MeetingCandidate; onAnswered: () => void; onOpen: (id: string) => void }) {
  const [chosen, setChosen] = useState(c.chosen);
  const [error, setError] = useState("");
  const confirm = async () => {
    setError("");
    try { const out = await confirmMeetingCandidate(c.id, { chosen: chosen.trim() }); onAnswered(); onOpen(out.decision.id); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const refuse = async () => {
    setError("");
    try { await refuseMeetingCandidate(c.id, "not a decision the meeting took"); onAnswered(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="aug-item">
      <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{c.question}</div>
      <div className="aug-item-foot aug-fs-sm" style={{ alignItems: "center" }}>
        <Input aria-label="What was chosen" value={chosen} onChange={e => setChosen(e.target.value)} placeholder="the meeting did not say — name it"
          style={{ flex: "1 1 220px" }} />
        <Button size="xs" disabled={!chosen.trim()} onClick={() => void confirm()}>Confirm</Button>
        <Button size="xs" variant="ghost" onClick={() => void refuse()}>Not a decision</Button>
      </div>
      <div className="aug-item-foot aug-fs-xs" style={{ color: "var(--t3)" }}>
        <span>{`“${c.title}”, ${day(c.held_on)}`}</span>
        {c.said_by && <span>{`said by ${c.said_by}`}</span>}
        <span>{c.quote_found ? "its line is in the notes" : "its line was not found in the notes — read it before confirming"}</span>
        <span>proposed by the model</span>
      </div>
      {c.quote && <div className="aug-fs-sm" style={{ color: "var(--t2)", fontStyle: "italic" }}>{`“${c.quote}”`}</div>}
      {error && <div className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</div>}
    </div>
  );
}

function KindForm({ onDeclared }: { onDeclared: (k: DecisionKind) => void }) {
  const [name, setName] = useState("");
  const [metrics, setMetrics] = useState("");
  const [approvers, setApprovers] = useState("");
  const [days, setDays] = useState("30");
  const [required, setRequired] = useState(false);
  const [error, setError] = useState("");
  const list = (v: string) => v.split(",").map(x => x.trim()).filter(Boolean);
  const submit = async () => {
    setError("");
    try {
      onDeclared(await declareDecisionKind({
        name: name.trim(), metrics: list(metrics), approvers: list(approvers).map(a => (a.includes(":") ? a : `person:${a}`)),
        review_days: Number(days) || 30, expectation_required: required,
      }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="aug-form-grid" data-testid="kind-form" style={{ marginBottom: 12 }}>
      <label className="aug-fs-sm" htmlFor="kind-n">The kind</label>
      <Input id="kind-n" value={name} onChange={e => setName(e.target.value)} placeholder="a price change" />
      <label className="aug-fs-sm" htmlFor="kind-m">The metrics it moves</label>
      <Input id="kind-m" value={metrics} onChange={e => setMetrics(e.target.value)} placeholder="gmv, gross_margin" />
      <label className="aug-fs-sm" htmlFor="kind-a">Who approves one</label>
      <Input id="kind-a" value={approvers} onChange={e => setApprovers(e.target.value)} placeholder="ana, ben" />
      <label className="aug-fs-sm" htmlFor="kind-d">Reviewed after</label>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Input id="kind-d" value={days} onChange={e => setDays(e.target.value)} inputMode="numeric" style={{ width: 80 }} />
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>days, plus how long this connection&apos;s days take to settle</span>
      </div>
      <span />
      <label className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Checkbox checked={required} onChange={e => setRequired(e.target.checked)} aria-label="Must say what it expects" />
        A decision of this kind must say what it expects
      </label>
      <span />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button size="xs" disabled={!name.trim()} onClick={() => void submit()}>Declare it</Button>
        {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
      </div>
    </div>
  );
}

const SOURCE_SHORT: Record<string, string> = {
  declared: "declared", recommendation: "from a recommendation", approval: "from an approval", reply: "from a reply",
};
const REVIEW_DOT: Record<string, "amber" | "grey" | "green"> = { due: "amber", waiting: "grey", reviewed: "green" };

/** Figures → Needs you → the list: how many, which are due for a review or reopened (with the button that answers
 *  them), whether they can be scored at all, and every decision as one row. */
function DecisionOverview({ all, connections, onOpen, form, declaring, onDeclare }: {
  all: Decision[]; connections: Connection[]; onOpen: (id: string) => void;
  form: React.ReactNode; declaring: boolean; onDeclare: () => void;
}) {
  const me = useActor().name;
  const [filter, setFilter] = useState<Filter>("all");
  const rows = useMemo(() => all.filter(d => filter === "all" || reviewState(d) === filter), [all, filter]);
  const due = all.filter(d => reviewState(d) === "due");
  const reviewed = all.filter(d => reviewState(d) === "reviewed");
  const reopened = all.filter(d => d.reopened_by && reviewState(d) !== "due");
  const next = all.filter(d => reviewState(d) === "waiting" && d.review_on).map(d => d.review_on).sort()[0] ?? "";
  const oldestDue = due.map(d => d.review_on).sort()[0] ?? "";
  const withExpectation = all.filter(d => d.expectation_claim).length;
  const scored = all.filter(d => d.expectation_claim && d.outcome);
  const told = scored.filter(d => d.outcome_verdict && d.outcome_verdict !== "cannot_tell").length;
  const notes = [...new Set(all.filter(d => !d.expectation_claim)
    .map(d => (typeof d.extra.expectation_note === "string" ? d.extra.expectation_note.replace(/^none:\s*/, "") : ""))
    .filter(Boolean))];
  const conns = [...new Set(all.map(d => d.connection_id).filter(Boolean))];
  const many = conns.length > 1;
  const scope = many ? `${conns.length} connections` : conns[0] ? connectionLabel(conns[0], connections) : "";
  const label = (d: Decision) => shortLabel(d.question);
  // What every row would repeat is said once, in the figure: who decided, and how each was booked.
  const deciders = [...new Set(all.map(d => d.decided_by))];
  const sources = [...new Set(all.map(d => d.source.kind))];

  const columns: ListColumn<Decision>[] = [
    { head: "Question", value: d => d.question },
    { head: "Chosen", value: d => d.options.find(o => o.id === d.chosen)?.description || d.chosen },
    { head: "Decided by", value: d => whoLabel(d.decided_by) },
    { head: "Decided", value: d => day(d.decided_at) },
    { head: "Review date", value: d => day(d.review_on) },
    { head: "Review", value: d => REVIEW_WORDS[reviewState(d)] },
    { head: "Reopened", value: d => (d.reopened_by ? "reopened" : "") },
    { head: "Expectation", value: d => (d.expectation_claim ? "booked" : "none") },
    { head: "Booked", value: d => SOURCE_WORDS[d.source.kind] ?? d.source.kind },
    { head: "Connection", value: d => (d.connection_id ? connectionLabel(d.connection_id, connections) : "every connection") },
  ];

  return (
    <>
      <Figures testId="decision-figures">
        <Figure label="Decisions" value={formatCount(all.length)} testId="fig-dec-all"
          sub={all.length === 0 ? "none booked yet" : [
            ...countBy(all, d => d.source.kind).map(([k, n]) => `${n} ${SOURCE_SHORT[k] ?? k}`),
            deciders.length === 1 ? `by ${whoLabel(deciders[0], me)}` : "",
          ].filter(Boolean).join(" · ")} />
        <Figure label="Review due" value={formatCount(due.length)} tone={due.length ? "amber" : undefined} testId="fig-dec-due"
          sub={due.length ? `the oldest since ${dateWords(oldestDue)}` : next ? `the next ${whenWords(next)}` : "no review date set"} />
        <Figure label="Reviewed" value={formatCount(reviewed.length)} testId="fig-dec-reviewed"
          sub={reviewed.length ? `of ${formatCount(all.length)}` : "no outcome booked yet"} />
        <Figure label="With an expectation" value={`${formatCount(withExpectation)} of ${formatCount(all.length)}`}
          testId="fig-dec-expect"
          title={notes.length ? notes.join(" · ") : undefined}
          sub={withExpectation === all.length
            ? (scored.length ? `${formatCount(told)} of ${formatCount(scored.length)} reviewed reached a verdict`
              : "each is scored on its review date")
            : <Chip title={notes.join(" · ") || undefined}>{`${formatCount(all.length - withExpectation)} cannot be scored`}</Chip>} />
      </Figures>

      <NeedsYou testId="decision-needs" empty="Nothing needs you">
        {[
          ...due.map(d => (
            <NeedsRow key={`due-${d.id}`} testId="needs-dec-due"
              title={`${label(d)} · review due since ${dateWords(d.review_on)}`}
              detail={`${chosenWords(d)} by ${whoLabel(d.decided_by, me)} on ${dateWords(d.decided_at)}`}
              actions={<Button size="xs" variant="secondary" onClick={() => onOpen(d.id)}>Review</Button>} />
          )),
          ...reopened.map(d => (
            <NeedsRow key={`reopened-${d.id}`} testId="needs-dec-reopened"
              title={`${label(d)} · reopened`}
              detail="A claim it relied on was restated; a person has not answered yet"
              actions={<Button size="xs" variant="secondary" onClick={() => onOpen(d.id)}>Open</Button>} />
          )),
        ]}
      </NeedsYou>

      {form}

      <ListCard<Decision> label="Decisions" name="decisions" testId="decision-list" rows={rows} rowKey={d => d.id}
        columns={columns}
        tools={<>
          <span className="aug-fs-xs" style={NUM}>
            {[filter === "all" ? "" : `${formatCount(rows.length)} of ${formatCount(all.length)}`, scope].filter(Boolean).join(" · ")}
          </span>
          <Segmented label="Filter decisions by review" value={filter} onChange={setFilter}
            options={FILTERS.map(f => ({ value: f.id, label: f.label }))} />
          <Button size="xs" onClick={onDeclare} aria-expanded={declaring}
            title="A decision taken elsewhere, in one sentence, with what you expect of it">
            Record a decision
          </Button>
        </>}
        empty={filter === "all"
          ? "No decision is on the record yet. Accepting a recommendation or approving an action books one."
          : `No decision is in "${FILTERS.find(f => f.id === filter)?.label.toLowerCase()}" right now.`}
        renderRow={(d, first) => {
          const state = reviewState(d);
          const meta = [
            deciders.length > 1 ? `decided by ${whoLabel(d.decided_by, me)} · ${dateWords(d.decided_at)}` : `decided ${dateWords(d.decided_at)}`,
            sources.length > 1 ? SOURCE_SHORT[d.source.kind] ?? "" : "",
            d.dissent.length ? countNoun(d.dissent.length, "dissent") : "",
            many ? (d.connection_id ? connectionLabel(d.connection_id, connections) : "every connection") : "",
          ].filter(Boolean).join(" · ");
          return (
            <ListRow first={first} testId="decision-row" title={label(d)} full={d.question} onOpen={() => onOpen(d.id)}
              mark={<Dot hue={REVIEW_DOT[state]} title={REVIEW_WORDS[state]} />}
              chips={<>
                <Chip title={d.options.find(o => o.id === d.chosen)?.description || undefined}>{chosenWords(d)}</Chip>
                {d.reopened_by && <Chip tone="amber" title="A claim it relied on was restated; a person has not answered yet">reopened</Chip>}
              </>}
              figure={state === "reviewed" ? "reviewed" : d.review_on ? `review ${distanceWords(d.review_on)}` : "no review date"}
              figureTitle={d.review_on ? `Review date: ${whenWords(d.review_on)}` : undefined}
              meta={meta} />
          );
        }} />
    </>
  );
}

const num = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** "We decided this elsewhere" — the question, what was chosen, and the expectation booked with it. */
function DeclareForm({ connectionId, onBooked, onCancel, revises = "", initialQuestion = "" }: {
  connectionId: string; onBooked: (d: DecisionDetail) => void; onCancel: () => void;
  /** The decision this one changes — a modifying decision; its thread reads backwards to it (study §3.1). */
  revises?: string;
  initialQuestion?: string;
}) {
  const [question, setQuestion] = useState(initialQuestion);
  const [chosen, setChosen] = useState("");
  const [others, setOthers] = useState("");
  const [metric, setMetric] = useState("");
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [unit, setUnit] = useState("");
  const [reviewOn, setReviewOn] = useState("");
  const [decidedOn, setDecidedOn] = useState("");
  const [kind, setKind] = useState("");
  const kinds = useLoad(() => listDecisionKinds("active"), []);
  const declared = kinds.data?.kinds ?? [];
  const actor = useActor();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const lo = num(low), hi = num(high);
      const options = [chosen, ...others.split("\n")].map(o => o.trim()).filter(Boolean);
      const d = await declareDecision({
        question: question.trim(), chosen: chosen.trim(), options, connection_id: connectionId, review_on: reviewOn,
        decided_at: decidedOn ? `${decidedOn}T12:00:00Z` : undefined, ...(kind ? { kind } : {}),
        ...(revises ? { revises } : {}),
        expectation: metric.trim()
          ? { metric: metric.trim(), low: lo, high: hi, mid: lo !== null && hi !== null ? (lo + hi) / 2 : null, unit: unit.trim(), settles_on: reviewOn }
          : null,
      });
      onBooked(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section label={revises ? "Revise this decision" : "Record a decision"}>
      <div className="aug-form-grid">
        <label className="aug-fs-sm" htmlFor="dec-q">What was being decided</label>
        <Input id="dec-q" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Do we extend the promotion by two weeks?" />
        <label className="aug-fs-sm" htmlFor="dec-c">What was chosen</label>
        <Input id="dec-c" value={chosen} onChange={e => setChosen(e.target.value)} placeholder="Extend it to 15 September" />
        <label className="aug-fs-sm" htmlFor="dec-o">The options not taken</label>
        <Input id="dec-o" value={others} onChange={e => setOthers(e.target.value)} placeholder="End it on schedule" />
        {declared.length > 0 && (
          <>
            <label className="aug-fs-sm" htmlFor="dec-k">Kind</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <SelectField id="dec-k" aria-label="The kind of decision" value={kind} style={{ maxWidth: 260 }} onChange={e => setKind(e.target.value)}>
                <option value="">none named</option>
                {declared.map(k => <option key={k.key} value={k.key}>{k.name}</option>)}
              </SelectField>
              {(() => {
                const k = declared.find(x => x.key === kind);
                return k ? <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                  {[k.expectation_required ? "it must say what it expects" : "", `reviewed after ${k.review_days} days`,
                    k.approvers.length ? `approved by ${k.approvers.map(a => whoLabel(a)).join(", ")}` : ""].filter(Boolean).join(" · ")}
                </span> : null;
              })()}
            </div>
          </>
        )}
        <label className="aug-fs-sm" htmlFor="dec-m">Expected to move</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Input id="dec-m" value={metric} onChange={e => setMetric(e.target.value)} placeholder="new customers" style={{ flex: "2 1 160px" }} />
          <Input aria-label="Expected low" value={low} onChange={e => setLow(e.target.value)} placeholder="from" inputMode="decimal" style={{ flex: "1 1 80px" }} />
          <Input aria-label="Expected high" value={high} onChange={e => setHigh(e.target.value)} placeholder="to" inputMode="decimal" style={{ flex: "1 1 80px" }} />
          <Input aria-label="Unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="unit" style={{ flex: "1 1 70px" }} />
        </div>
        <label className="aug-fs-sm" htmlFor="dec-r">Review on</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Input id="dec-r" type="date" value={reviewOn} onChange={e => setReviewOn(e.target.value)} style={{ width: 170 }} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>left empty, the date is proposed from how long this connection&apos;s days take to settle</span>
        </div>
        <label className="aug-fs-sm" htmlFor="dec-d">Decided on</label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Input id="dec-d" type="date" value={decidedOn} max={new Date().toISOString().slice(0, 10)} onChange={e => setDecidedOn(e.target.value)} style={{ width: 170 }} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>left empty, today. A past decision, with its outcome booked, becomes a case later ones are projected from.</span>
        </div>
        <span />
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ActorField actor={actor} id="dec-actor" />
          <Button size="xs" disabled={busy || !question.trim() || !chosen.trim()} onClick={() => void submit()}>Book it</Button>
          <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
          {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
        </div>
      </div>
    </Section>
  );
}

// ── the Reader ───────────────────────────────────────────────────────────────────────────

function DecisionReader({ id, connections, onBack, onMoved, onOpenClaim }: {
  id: string; connections: Connection[]; onBack: () => void; onOpenClaim: (id: string) => void;
  /** Booking an outcome restates the decision; the page follows it to the id it now has. */
  onMoved: (id: string) => void;
}) {
  const load = useLoad(() => getDecision(id), [id]);
  const d = load.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Decisions" onBack={onBack} title={d?.question ?? "Decision"}
        chips={d && <StatusChip hue={REVIEW_HUE[reviewState(d)]}>{REVIEW_WORDS[reviewState(d)]}</StatusChip>} />
      <Gate load={load} what="the decision">
        {detail => <DecisionBody d={detail} connections={connections} reload={load.reload} onMoved={onMoved} onOpenClaim={onOpenClaim} />}
      </Gate>
    </div>
  );
}

function band(c: Claim): string {
  const lo = c.extra.low as number | null | undefined, hi = c.extra.high as number | null | undefined;
  const unit = c.statement.unit ? ` ${c.statement.unit}` : "";
  if (lo == null || hi == null) return c.statement.value != null ? `${formatTableNumber(c.statement.value)}${unit}` : "no interval stated";
  if (lo === hi) return `${formatTableNumber(lo)}${unit} exactly`;
  const cov = typeof c.extra.coverage === "number" ? ` at ${pct(c.extra.coverage as number)} coverage` : "";
  return `${formatTableNumber(lo)} to ${formatTableNumber(hi)}${unit}${cov}`;
}

function DecisionBody({ d, connections, reload, onMoved, onOpenClaim }: {
  d: DecisionDetail; connections: Connection[]; reload: () => void; onMoved: (id: string) => void;
  onOpenClaim: (id: string) => void;
}) {
  const scenarios = useLoad(() => listScenarios(d.id), [d.id, d.version]);
  const calibration = useLoad(() => getCalibration(d.connection_id || undefined), [d.connection_id]);
  const state = reviewState(d);
  const actor = useActor();
  const current = !d.superseded_by;
  const [adding, setAdding] = useState<"" | "option" | "dissent">("");
  const [option, setOption] = useState("");
  const [dissentWho, setDissentWho] = useState("");
  const [dissentWhy, setDissentWhy] = useState("");
  const [revising, setRevising] = useState(false);
  const [standsWhy, setStandsWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const write = async (fn: () => Promise<DecisionDetail>) => {
    setBusy(true);
    setError("");
    try {
      const next = await fn();
      setAdding(""); setOption(""); setDissentWho(""); setDissentWhy(""); setStandsWhy("");
      onMoved(next.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  // What was added after the decision was booked — dated and named, so it never reads as having
  // been on the table at the moment of deciding.
  const amendments = (Array.isArray(d.extra.amendments) ? d.extra.amendments : []) as { kind: string; what: string; at: string; by: string }[];
  const addedLater = (kind: string, what: string) => amendments.find(a => a.kind === kind && a.what === what);
  const reopenings = (Array.isArray(d.extra.reopened) ? d.extra.reopened : []) as
    { at: string; why?: string; settled_at?: string; settled_by?: string; settled_why?: string }[];
  const answered = reopenings.filter(r => r.settled_at);
  // Approvals given where the approver works — a ✅ on the decision card in Slack — each dated and named.
  const approvals = (Array.isArray(d.extra.approvals) ? d.extra.approvals : []) as
    { by: string; where?: string; at: string; named?: boolean }[];
  const rail = (
    <>
      <div className="aug-rail-head"><span className="aug-label">This decision</span></div>
      <Fact label="Answerable">{whoLabel(d.owner || d.decided_by)}</Fact>
      {d.approvers.length > 0 && <Fact label="Approvers">{d.approvers.map(a => whoLabel(a, actor.name)).join(", ")}</Fact>}
      {approvals.length > 0 && (
        <Fact label="Approved">{approvals.map(a => `${whoLabel(a.by, actor.name)}${a.where ? ` in ${a.where}` : ""}, ${day(a.at)}`
          + (d.approvers.length && !a.named ? " (not a named approver)" : "")).join(" · ")}</Fact>
      )}
      <Fact label="Decided">{day(d.decided_at)} by {whoLabel(d.decided_by, actor.name)}</Fact>
      <Fact label="Booked">{SOURCE_WORDS[d.source.kind] ?? d.source.kind}</Fact>
      {d.kind && <Fact label="Kind">{kindWords(d.kind)}</Fact>}
      <Fact label="Review date">{d.review_on ? `${day(d.review_on)} · ${dayDistance(d.review_on)}` : "none set"}</Fact>
      {d.objective && <Fact label="Toward">{d.objective}</Fact>}
      <Fact label="Connection">{d.connection_id ? connectionLabel(d.connection_id, connections) : "every connection"}</Fact>
    </>
  );
  return (
    <Page rail={rail}>
      {revising ? (
        <DeclareForm connectionId={d.connection_id} revises={d.id} initialQuestion={d.question}
          onCancel={() => setRevising(false)} onBooked={next => { setRevising(false); requestTab("decisions", { id: next.id }); }} />
      ) : current && (
        <div style={{ marginBottom: 12 }}>
          <Button size="xs" variant="secondary" onClick={() => setRevising(true)}>Revise this decision</Button>
        </div>
      )}
      {d.superseded_by && (
        <Callout tone="amber" style={{ marginBottom: 16 }}>
          <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>This is the decision as first booked; it has been restated since. </span>
          <Button size="xs" variant="link" onClick={() => onMoved(d.superseded_by)}>Open it as it stands now</Button>
        </Callout>
      )}
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 12px" }}>{error}</p>}
      {current && d.reopened_by && (
        <Callout tone="amber" style={{ marginBottom: 16 }}>
          <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: "0 0 4px" }}>
            Reopened: a claim this decision relied on was restated.
            {d.reopened_by_claim && <> It now reads: “{d.reopened_by_claim.statement.text}”</>}
          </p>
          <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "0 0 8px" }}>
            Nothing was undone. If the choice still holds on what replaced the claim, say why and it is no longer open; if it does not, record the new decision.
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Input aria-label="Why it still stands" value={standsWhy} onChange={e => setStandsWhy(e.target.value)}
              placeholder="Why the choice still holds" style={{ flex: "1 1 260px" }} />
            <ActorField actor={actor} id="dec-stands-actor" />
            <Button size="xs" disabled={busy || !standsWhy.trim()} onClick={() => void write(() => decisionStands(d.id, standsWhy.trim()))}>It still stands</Button>
            <Button size="xs" variant="ghost" onClick={() => onOpenClaim(d.reopened_by)}>Open the claim</Button>
          </div>
        </Callout>
      )}
      <Section label="The options" meta={countNoun(d.options.length, "option")}
        action={current && <Button size="xs" variant="outline" aria-expanded={adding === "option"} onClick={() => setAdding(a => (a === "option" ? "" : "option"))}>Add an option</Button>}>
        {adding === "option" && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
            <Input aria-label="An option that was on the table" value={option} onChange={e => setOption(e.target.value)}
              placeholder="An option that was on the table" style={{ flex: "1 1 280px" }} />
            <ActorField actor={actor} id="dec-opt-actor" />
            <Button size="xs" disabled={busy || !option.trim()} onClick={() => void write(() => amendDecision(d.id, { option: option.trim() }))}>Add it</Button>
            <Button size="xs" variant="ghost" onClick={() => setAdding("")}>Cancel</Button>
            <span className="aug-fs-sm" style={{ color: "var(--t3)", flexBasis: "100%" }}>It is marked as added today. What was chosen does not change — choosing again is a new decision.</span>
          </div>
        )}
        {d.options.length === 0 ? (
          <Absent>Only the choice was recorded: {d.chosen}. The options it was chosen over were not written down.</Absent>
        ) : (
          <div className="aug-options">
            {d.options.map(o => {
              const chosen = o.id === d.chosen || o.description === d.chosen;
              return (
                <div className="aug-option" data-chosen={chosen} key={o.id}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <span className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: chosen ? 600 : 400 }}>{o.description}</span>
                    {chosen && <StatusChip hue="info">chosen</StatusChip>}
                    {d.extra?.recommended === o.id && <StatusChip hue="muted">recommended</StatusChip>}
                  </div>
                  <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                    {[o.cost && `cost: ${o.cost}`, o.reversibility && `reversibility: ${o.reversibility}`, o.actor && `acts: ${whoLabel(o.actor)}`]
                      .filter(Boolean).join(" · ") || "no cost, reversibility or actor recorded"}
                  </div>
                  {addedLater("option", o.id) && (
                    <div className="aug-fs-sm" style={{ color: "var(--amb4)" }}>
                      added on {day(addedLater("option", o.id)!.at)} by {whoLabel(addedLater("option", o.id)!.by)}, after the decision
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Section>

      <Section label="The scenario"
        meta={scenarios.data ? countNoun(scenarios.data.predictions.filter(p => p.booked_as !== d.expectation_claim).length, "prediction") : undefined}>
        <Gate load={scenarios} what="the scenario">
          {s => <ScenarioBlock decision={d} scenarios={s.scenarios} predictions={s.predictions} actor={actor}
            calibration={calibration.data ?? []} onBooked={() => { scenarios.reload(); reload(); }} onOpenClaim={onOpenClaim} />}
        </Gate>
      </Section>

      <Section label="What it relied on" meta={countNoun(d.relied_on_claims.length, "claim")}>
        {d.relied_on_claims.length === 0 ? (
          <Absent>No claim was cited when this decision was booked.</Absent>
        ) : d.relied_on_claims.map(c => (
          <ClaimLine key={c.id} claim={c} onOpen={onOpenClaim}
            note={c.superseded_by ? "as recorded when it was decided — restated since" : undefined}
            action={c.superseded_by && <Button size="xs" variant="ghost" onClick={() => onOpenClaim(c.superseded_by)}>What replaced it</Button>} />
        ))}
        {answered.map(r => (
          <p className="aug-fs-sm" key={r.at} style={{ color: "var(--t2)", margin: "8px 0 0" }}>
            Reopened on {day(r.at)} when a claim it relied on was restated; {whoLabel(r.settled_by ?? "")} answered on {day(r.settled_at)} that it still stands: {r.settled_why}
          </p>
        ))}
      </Section>

      <Section label="Dissent" meta={d.dissent.length ? countNoun(d.dissent.length, "voice") : undefined}
        action={current && <Button size="xs" variant="outline" aria-expanded={adding === "dissent"} onClick={() => setAdding(a => (a === "dissent" ? "" : "dissent"))}>Record dissent</Button>}>
        {adding === "dissent" && (
          <div className="aug-form-grid" style={{ marginBottom: 12 }}>
            <label className="aug-fs-sm" htmlFor="dec-dis-who">Who disagreed</label>
            <Input id="dec-dis-who" value={dissentWho} onChange={e => setDissentWho(e.target.value)} placeholder="a person" />
            <label className="aug-fs-sm" htmlFor="dec-dis-why">Why</label>
            <Input id="dec-dis-why" value={dissentWhy} onChange={e => setDissentWhy(e.target.value)} placeholder="What they said against the choice" />
            <span />
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <ActorField actor={actor} id="dec-dis-actor" />
              <Button size="xs" disabled={busy || !dissentWho.trim() || !dissentWhy.trim()}
                onClick={() => void write(() => amendDecision(d.id, { dissent: { who: dissentWho.trim(), why: dissentWhy.trim() } }))}>Record it</Button>
              <Button size="xs" variant="ghost" onClick={() => setAdding("")}>Cancel</Button>
              <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Dissent is kept with the decision; it is marked as recorded today.</span>
            </div>
          </div>
        )}
        {d.dissent.length === 0 ? <Absent>No dissent was recorded.</Absent> : d.dissent.map(x => (
          <div className="aug-item" key={`${x.who}:${x.why}`}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{x.why}</div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{whoLabel(x.who)}</span>
              {addedLater("dissent", x.who) && <span>recorded on {day(addedLater("dissent", x.who)!.at)}, after the decision</span>}
            </div>
          </div>
        ))}
      </Section>

      <Section label="The expectation booked">
        {d.expectation ? (
          <div className="aug-item">
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.expectation.statement.text}</div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{d.expectation.statement.metric}: {band(d.expectation)}</span>
              <span>settles {day(String(d.expectation.extra.settles_on ?? d.review_on))}</span>
              <span>booked by {whoLabel(d.expectation.author)}</span>
            </div>
          </div>
        ) : <Absent>No expectation was booked with this decision, so its outcome can only be read against the baseline.</Absent>}
      </Section>

      <Section label="What became of it">
        {d.outcome_record ? (
          <div className="aug-item">
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <StatusChip hue={VERDICT_HUE[d.outcome_record.verdict] ?? "muted"}>{verdictWords(d.outcome_record.verdict)}</StatusChip>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{d.outcome_record.why}</span>
            </div>
            <div className="aug-item-foot aug-fs-sm">
              {d.outcome_record.actual != null && <span>actual {formatTableNumber(d.outcome_record.actual)}</span>}
              {d.outcome_record.baseline != null && <span>baseline {formatTableNumber(d.outcome_record.baseline)}</span>}
              {d.outcome_record.against_expectation && <span>against the expectation: {d.outcome_record.against_expectation}</span>}
              <span>measured {day(d.outcome_record.measured_on)} by {whoLabel(d.outcome_record.measured_by)}</span>
            </div>
          </div>
        ) : state === "due" ? (
          <OutcomeForm decisionId={d.id} actor={actor} onBooked={id => (id ? onMoved(id) : reload())} />
        ) : (
          <Absent>
            Its review date is {d.review_on ? `${day(d.review_on)} (${dayDistance(d.review_on)})` : "not set"}. On that date the outcome
            is measured on settled days, against the expectation and against the metric&apos;s own baseline.
          </Absent>
        )}
      </Section>
      <ThreadSection id={d.id} version={d.version} />
    </Page>
  );
}

// ── the thread: where it arose to what was learned (the decision-framework study §3.1, §3.3) ─────────────

/** The decision read as one thread, stage by stage — each step a line, its why in a sentence, and its receipt
 *  behind a click — with its loops, what it revises and what revised it. Composed by code from the Record. */
export function ThreadSection({ id, version }: { id: string; version: number }) {
  const load = useLoad(() => getThread(id), [id, version]);
  return (
    <Section label="From where it arose to what was learned" meta="read forwards and backwards">
      <Gate load={load} what="the thread">
        {t => (
          <div data-testid="decision-thread">
            {t.backwards.map(l => <LinkRow key={`b:${l.decision}`} l={l} />)}
            {t.stages.map(st => (
              <div key={st.stage} style={{ display: "grid", gridTemplateColumns: "150px minmax(0, 1fr)", gap: 12, padding: "8px 0",
                borderTop: "1px solid var(--b1)" }}>
                <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{st.words}</span>
                <div>{st.steps.map((s, i) => <StepRow key={`${st.stage}:${s.ref || s.kind}:${i}`} s={s} />)}</div>
              </div>
            ))}
            {t.loops.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "150px minmax(0, 1fr)", gap: 12, padding: "8px 0",
                borderTop: "1px solid var(--b1)" }}>
                <span className="aug-fs-sm" style={{ color: "var(--amb4)" }}>Loops</span>
                <div>{t.loops.map((s, i) => <StepRow key={`loop:${i}`} s={s} />)}</div>
              </div>
            )}
            {t.forwards.map(l => <LinkRow key={`f:${l.decision}`} l={l} />)}
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>Composed by {t.composed_by}.</div>
          </div>
        )}
      </Gate>
    </Section>
  );
}

function StepRow({ s }: { s: ThreadStep }) {
  const [open, setOpen] = useState(false);
  const receipt = Object.entries(s.receipt);
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="aug-fs-ui" style={{ color: "var(--t1)", display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span>{s.line}</span>
        {s.at && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{day(s.at)}</span>}
        {receipt.length > 0 && (
          <Button size="xs" variant="ghost" onClick={() => setOpen(v => !v)}>{open ? "Hide the receipt" : "Receipt"}</Button>
        )}
      </div>
      {s.why && <div className="aug-fs-sm" style={{ color: "var(--t2)", maxWidth: "78ch" }}>{plainWho(s.why)}</div>}
      {open && (
        <div className="aug-fs-xs" data-testid="thread-receipt" style={{ color: "var(--t3)", fontFamily: "var(--font-mono)", marginTop: 2 }}>
          {receipt.map(([k, v]) => <div key={k}>{`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`}</div>)}
        </div>
      )}
    </div>
  );
}

function LinkRow({ l }: { l: ThreadLink }) {
  return (
    <div className="aug-item-foot aug-fs-sm" style={{ padding: "6px 0" }}>
      <span style={{ color: "var(--t3)" }}>{l.why}:</span>
      <span style={{ color: "var(--t1)" }}>{`${l.question} → ${l.chosen}`}</span>
      <span>{day(l.decided_at)}</span>
      <Button size="xs" variant="link" onClick={() => requestTab("decisions", { id: l.decision })}>Open it →</Button>
    </div>
  );
}

// ── the scenario, inside its decision ────────────────────────────────────────────────────

const METHOD_WORDS: Record<string, string> = {
  identity: "arithmetic on stated inputs — exact",
  declared: "an assumption a named person declared",
  history: "the metric's own history",
  intervention: "past cases of the same change",
};

function licence(method: string, metric: string, rows: CalibrationRow[]): string {
  const mine = rows.filter(r => r.method === method);
  const n = mine.reduce((a, r) => a + r.n - r.cannot_tell, 0);
  if (n === 0) return "no prediction by this method has been scored here yet";
  const inside = mine.reduce((a, r) => a + r.inside, 0);
  const onMetric = mine.filter(r => r.metric === metric).reduce((a, r) => a + r.n - r.cannot_tell, 0);
  return `${inside} of ${n} scored predictions by this method fell inside their interval${onMetric ? ` (${onMetric} on this metric)` : ""}`;
}

function ScenarioBlock({ decision, scenarios, predictions, calibration, actor, onBooked, onOpenClaim }: {
  decision: DecisionDetail; scenarios: Scenario[]; predictions: (Claim & { booked_as?: string })[];
  calibration: CalibrationRow[]; actor: Actor; onBooked: () => void; onOpenClaim: (id: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const made = predictions.filter(p => p.id !== decision.expectation?.id && p.booked_as !== decision.expectation_claim);
  const assumptions = scenarios.flatMap(s => s.assumptions);
  const limits = [...new Set(scenarios.flatMap(s => s.limits))];
  return (
    <div>
      {made.length === 0 && !adding && (
        <Absent>No scenario has been projected for this decision. A projection states its method — arithmetic on stated inputs, a named person&apos;s assumption, the metric&apos;s own history, or what past decisions like this one did — and is scored when its days settle.</Absent>
      )}
      {assumptions.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div className="aug-fs-sm" style={{ color: "var(--t3)", marginBottom: 2 }}>Assumptions</div>
          {assumptions.map(a => (
            <div className="aug-item" key={`${a.variable}:${a.claim}`}>
              <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                {a.variable}{a.value != null ? ` = ${formatTableNumber(a.value)}` : ""}{a.text ? ` — ${a.text}` : ""}
              </div>
              <div className="aug-item-foot aug-fs-sm"><span>{a.source} by {whoLabel(a.by)}</span></div>
            </div>
          ))}
        </div>
      )}
      {made.map(p => {
        const method = String(p.extra.method ?? "");
        // What the method must say, in a reader's words: the claim it was booked as is the button
        // beside it, and a person is named, not shown as an id.
        const mustSay = (Array.isArray(p.extra.must_say) ? (p.extra.must_say as string[]) : [])
          .filter(m => !m.startsWith("booked as claim")).map(plainWho);
        const scored = p.state === "scored";
        return (
          <div className="aug-item" key={p.id}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{p.statement.metric}: {band(p)}</span>
              <StatusChip hue="muted" title={METHOD_WORDS[method]}>{method || "no method"}</StatusChip>
              {scored && (
                <StatusChip hue={p.extra.scored_against === "inside" ? "positive" : "negative"}>
                  scored {String(p.extra.scored_against ?? "")}: {formatTableNumber(p.extra.actual as number)}
                </StatusChip>
              )}
            </div>
            <div className="aug-item-foot aug-fs-sm">
              <span>{METHOD_WORDS[method] ?? method}</span>
              {mustSay.map(m => <span key={m}>{m}</span>)}
              <span title="How far this method can be trusted here">{licence(method, p.statement.metric, calibration)}</span>
              {!scored && <span>scored on {day(String(p.extra.settles_on ?? ""))} against the settled figure</span>}
              <span>by {whoLabel(p.author)}</span>
              <span style={{ flex: 1 }} />
              <Button size="xs" variant="ghost" onClick={() => onOpenClaim(p.id)}>Open the claim</Button>
            </div>
          </div>
        );
      })}
      {limits.length > 0 && (
        <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "10px 0 0" }}>
          <span style={{ color: "var(--t3)" }}>Limits: </span>{limits.join(" · ")}
        </p>
      )}
      <div style={{ marginTop: 10 }}>
        {adding
          ? <ProjectForm decision={decision} actor={actor} onCancel={() => setAdding(false)} onBooked={() => { setAdding(false); onBooked(); }} />
          : <Button size="xs" variant="outline" onClick={() => setAdding(true)}>Add a projection</Button>}
      </div>
    </div>
  );
}

type Method = ScenarioBody["method"];

const METHOD_LABEL: Record<Method, string> = {
  identity: "Arithmetic", declared: "My assumption", history: "Its own history", intervention: "Past decisions like it",
};

/** What the method's booking line says, before it is booked. */
const METHOD_HINT: Record<Method, string> = {
  identity: "It says which inputs it held fixed.",
  declared: "It is booked as your declared claim, under your name.",
  history: "It reads the metric's last six periods on this connection and states how often that band has held. The metric needs an approved definition.",
  intervention: "It reads the measured effect of past decisions that asked the same question, and projects nothing from fewer than the least it needs.",
};

/** One projection under one method of the ladder — refused, with the reason, when the method has nothing to read. */
function ProjectForm({ decision, actor, onBooked, onCancel }: {
  decision: DecisionDetail; actor: Actor; onBooked: () => void; onCancel: () => void;
}) {
  const [method, setMethod] = useState<Method>("identity");
  // What method 4 would read, shown before anything is booked.
  const cases = useLoad(
    () => (method === "intervention" ? getPastCases(decision.id, "") : Promise.resolve(null)), [method, decision.id]);
  const [metric, setMetric] = useState("");
  const [formula, setFormula] = useState("");
  const [inputs, setInputs] = useState("");
  const [variable, setVariable] = useState("");
  const [value, setValue] = useState("");
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [unit, setUnit] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      if (method === "identity") {
        const parsed: Record<string, number> = {};
        for (const part of inputs.split(",")) {
          const [k, v] = part.split("=").map(x => x.trim());
          if (!k) continue;
          if (num(v ?? "") === null) throw new Error(`"${part.trim()}" is not a name = number`);
          parsed[k] = Number(v);
        }
        await bookScenario(decision.id, { method, metric: metric.trim(), formula: formula.trim(), inputs: parsed, unit: unit.trim() });
      } else if (method === "declared") {
        await bookScenario(decision.id, {
          method, metric: metric.trim(), unit: unit.trim(),
          assumption: { variable: variable.trim(), value: num(value), low: num(low), high: num(high), unit: unit.trim() },
        });
      } else {
        await bookScenario(decision.id, { method, metric: metric.trim(), unit: unit.trim() });
      }
      onBooked();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="aug-form-grid">
      <label className="aug-fs-sm">Method</label>
      <Segmented label="Method" value={method} onChange={setMethod} style={{ justifySelf: "start" }}
        options={(["identity", "declared", "history", "intervention"] as const).map(m => ({ value: m, label: METHOD_LABEL[m], title: METHOD_WORDS[m] }))} />
      <label className="aug-fs-sm" htmlFor="sc-metric">What it predicts</label>
      <div style={{ display: "flex", gap: 8 }}>
        <Input id="sc-metric" value={metric} onChange={e => setMetric(e.target.value)} placeholder="credit cost" style={{ flex: 1 }} />
        <Input aria-label="Unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="unit" style={{ width: 90 }} />
      </div>
      {method === "identity" ? (
        <>
          <label className="aug-fs-sm" htmlFor="sc-formula">Formula</label>
          <Input id="sc-formula" value={formula} onChange={e => setFormula(e.target.value)} placeholder="accounts * credit" />
          <label className="aug-fs-sm" htmlFor="sc-inputs">Inputs</label>
          <Input id="sc-inputs" value={inputs} onChange={e => setInputs(e.target.value)} placeholder="accounts = 31, credit = 1290" />
        </>
      ) : method === "declared" ? (
        <>
          <label className="aug-fs-sm" htmlFor="sc-var">Assumption</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Input id="sc-var" value={variable} onChange={e => setVariable(e.target.value)} placeholder="win-back rate" style={{ flex: "2 1 160px" }} />
            <Input aria-label="Value" value={value} onChange={e => setValue(e.target.value)} placeholder="value" inputMode="decimal" style={{ flex: "1 1 80px" }} />
            <Input aria-label="Low" value={low} onChange={e => setLow(e.target.value)} placeholder="low" inputMode="decimal" style={{ flex: "1 1 70px" }} />
            <Input aria-label="High" value={high} onChange={e => setHigh(e.target.value)} placeholder="high" inputMode="decimal" style={{ flex: "1 1 70px" }} />
          </div>
        </>
      ) : method === "intervention" ? (
        <>
          <label className="aug-fs-sm">Past cases</label>
          <Gate load={cases} what="the past cases">
            {c => (c === null ? null : (
              <div>
                <p className="aug-fs-ui" style={{ color: "var(--t1)", margin: 0 }}>
                  {countNoun(c.cases.length, "past decision")} that asked this question {c.cases.length === 1 ? "has" : "have"} a measured effect;{" "}
                  {c.needed} are the least an effect is read from.
                </p>
                {c.cases.map(k => (
                  <div className="aug-item-foot aug-fs-sm" key={k.outcome} style={{ marginTop: 4 }}>
                    <span>{k.question}</span>
                    <span>effect {formatTableNumber(k.effect)}</span>
                    <span>{verdictWords(k.verdict)}</span>
                    <span>measured {day(k.measured_on)}</span>
                  </div>
                ))}
                {c.cases.length < c.needed && (
                  <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: "4px 0 0" }}>
                    A case is a decision with its outcome booked and an effect measured. One taken before today can be recorded from the Decisions list, with the day it was decided.
                  </p>
                )}
              </div>
            ))}
          </Gate>
        </>
      ) : null}
      <span />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {method === "declared" && <ActorField actor={actor} id="sc-actor" />}
        <Button size="xs" disabled={busy || !metric.trim()}
          onClick={() => void submit()}>Book the projection</Button>
        <Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{METHOD_HINT[method]}</span>
        {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", flexBasis: "100%" }}>{error}</span>}
      </div>
    </div>
  );
}

const VERDICTS: OutcomeVerdict[] = ["as_expected", "better", "worse", "missed", "cannot_tell"];

/** The review date has come: what was measured, against the expectation and the baseline. */
function OutcomeForm({ decisionId, actor, onBooked }: {
  decisionId: string; actor: Actor; onBooked: (restatedId: string | null) => void;
}) {
  const [actual, setActual] = useState("");
  const [baseline, setBaseline] = useState("");
  const [effect, setEffect] = useState("");
  const [verdict, setVerdict] = useState<OutcomeVerdict>("cannot_tell");
  const [why, setWhy] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const booked = await bookOutcome(decisionId, {
        measured_on: new Date().toISOString().slice(0, 10), actual: num(actual), baseline: num(baseline), verdict, why: why.trim(),
        // Left empty, the effect is the measured figure less its baseline when both are given.
        effect_value: num(effect) ?? (num(actual) !== null && num(baseline) !== null ? num(actual)! - num(baseline)! : null),
      });
      onBooked(booked.decision?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <Absent>Its review date has come and no outcome is booked. The platform books one itself when the metric is measurable on settled days; a person can book it here.</Absent>
      <div className="aug-form-grid" style={{ marginTop: 8 }}>
        <label className="aug-fs-sm" htmlFor="out-actual">Measured</label>
        <div style={{ display: "flex", gap: 8 }}>
          <Input id="out-actual" value={actual} onChange={e => setActual(e.target.value)} placeholder="actual" inputMode="decimal" style={{ width: 140 }} />
          <Input aria-label="Baseline" value={baseline} onChange={e => setBaseline(e.target.value)} placeholder="baseline" inputMode="decimal" style={{ width: 140 }} />
          <Input aria-label="Effect" value={effect} onChange={e => setEffect(e.target.value)} placeholder="effect" inputMode="decimal" style={{ width: 140 }}
            title="What the decision changed, against the baseline. Left empty, the measured figure less the baseline." />
        </div>
        <label className="aug-fs-sm">Verdict</label>
        <Segmented label="Verdict" value={verdict} onChange={setVerdict} style={{ justifySelf: "start" }}
          options={VERDICTS.map(v => ({ value: v, label: verdictWords(v) }))} />
        <label className="aug-fs-sm" htmlFor="out-why">Why</label>
        <Input id="out-why" value={why} onChange={e => setWhy(e.target.value)} placeholder="What the measurement showed" />
        <span />
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ActorField actor={actor} id="out-actor" />
          <Button size="xs" disabled={busy} onClick={() => void submit()}>Book the outcome</Button>
          {error && <span className="aug-fs-sm" role="alert" style={{ color: "var(--red4)" }}>{error}</span>}
        </div>
      </div>
    </div>
  );
}
