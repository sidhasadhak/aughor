"use client";

/**
 * Inquiries — "why is this happening?" (the 2027 study §V, screen 4).
 *
 * An inquiry is a record that outlives its runs: the question, what is established, each
 * hypothesis with the evidence that decided it — the refuted ones kept, because they are
 * memory — what is still open and what would settle it, and the lessons written at its close.
 * A reader knows where it stands without opening a transcript.
 */
import { useMemo, useState } from "react";

import type { Connection } from "@/lib/api";
import { compactNumber, countNoun, formatCount, formatTableNumber } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import {
  addInquiryHypothesis, closeInquiry, getInquiry, handInquiry, listInquiries, proposeInquiryRun,
  setInquiryNextCheck, verdictWords, whoLabel,
  type Claim, type Inquiry, type InquiryDetail,
} from "@/lib/record";
import {
  Absent, ActorField, BackHeader, ClaimLine, Fact, Gate, ListCard, ListRow, MarkWrong, Page, Section, day, dayDistance,
  markedWords, useActor, useLoad,
  type ListColumn,
} from "@/components/record/kit";
import {
  countBy, dateWords, daysFrom, inquiryLabel, inquiryStateShort, whenWords,
} from "@/components/record/words";
import {
  Chip, Dot, Figure, Figures, NUM, NeedsRow, NeedsYou, Page as ClarityPage,
} from "@/components/clarity/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Callout } from "@/components/ui/callout";

type StateFilter = "all" | "open" | "waiting" | "closed";

const FILTERS: { id: StateFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "open", label: "Open" },
  { id: "waiting", label: "Waiting" },
  { id: "closed", label: "Closed" },
];

/** open · waiting for … · closed as … — the state in the words the record keeps. */
export function inquiryState(q: Pick<Inquiry, "state" | "waiting_for" | "closed_as">): string {
  if (q.state === "waiting") return q.waiting_for ? `waiting for ${q.waiting_for}` : "waiting";
  if (q.state === "closed") return q.closed_as ? `closed as ${q.closed_as}` : "closed";
  return "open";
}

const STATE_HUE: Record<string, ChipHue> = { open: "info", waiting: "caution", closed: "muted" };

const HYPOTHESIS_HUE: Record<string, ChipHue> = {
  supported: "positive", refuted: "negative", open: "info", abandoned: "muted",
};

export function InquiriesPanel({ connections, openId, onOpen, onOpenRun, onOpenDecision, onOpenClaim, onAsk }: {
  connections: Connection[];
  /** The inquiry the URL names — the Reader; absent, the Ledger. */
  openId: string | null;
  onOpen: (id: string | null) => void;
  onOpenRun: (runId: string) => void;
  onOpenDecision: (id: string) => void;
  onOpenClaim: (id: string) => void;
  onAsk: () => void;
}) {
  if (openId) {
    return <InquiryReader id={openId} connections={connections} onBack={() => onOpen(null)} onMoved={onOpen}
      onOpenRun={onOpenRun} onOpenDecision={onOpenDecision} onOpenClaim={onOpenClaim} />;
  }
  return <InquiryLedger connections={connections} onOpen={onOpen} onAsk={onAsk} />;
}

function InquiryLedger({ connections, onOpen, onAsk }: {
  connections: Connection[]; onOpen: (id: string) => void; onAsk: () => void;
}) {
  const load = useLoad(() => listInquiries({ limit: 300 }), []);
  return (
    <ClarityPage testId="inquiries-page">
      <Gate load={load} what="inquiries">
        {all => <InquiryOverview all={all} connections={connections} onOpen={onOpen} onAsk={onAsk} />}
      </Gate>
    </ClarityPage>
  );
}

const STATE_DOT: Record<string, "blue" | "grey" | "green"> = { open: "blue", waiting: "grey", closed: "grey" };
const UNSTATED = /^unstated\b/;

/** Figures → Needs you → the list: what is open, what waits and on what, what is due for a person, and every inquiry
 *  as one row — its label, how much is still open, one muted line. */
function InquiryOverview({ all, connections, onOpen, onAsk }: {
  all: Inquiry[]; connections: Connection[]; onOpen: (id: string) => void; onAsk: () => void;
}) {
  const [filter, setFilter] = useState<StateFilter>("all");
  const rows = useMemo(() => all.filter(q => filter === "all" || q.state === filter), [all, filter]);
  const of = (s: Inquiry["state"]) => all.filter(q => q.state === s);
  const open = of("open"), waiting = of("waiting"), closed = of("closed");
  const noRun = open.filter(q => q.runs.length === 0);
  const reasons = [...new Set(waiting.map(q => q.waiting_for).filter(Boolean))];
  const items = all.filter(q => q.state !== "closed").flatMap(q => q.open);
  const withItems = all.filter(q => q.state !== "closed" && q.open.length > 0).length;
  const unstated = items.length > 0 && items.every(o => !o.settled_by || UNSTATED.test(o.settled_by));
  const due = waiting.filter(q => q.next_check && (daysFrom(q.next_check) ?? 1) <= 0);
  const next = waiting.map(q => q.next_check).filter(d => d && (daysFrom(d) ?? 0) > 0).sort()[0] ?? "";
  const conns = [...new Set(all.map(q => q.connection_id).filter(Boolean))];
  const many = conns.length > 1;
  const scope = many ? `${conns.length} connections` : conns[0] ? connectionLabel(conns[0], connections) : "";
  const ownerOf = (q: Inquiry) => (typeof q.extra.owner === "string" ? q.extra.owner : "");

  const columns: ListColumn<Inquiry>[] = [
    { head: "Question", value: q => q.question },
    { head: "State", value: q => inquiryState(q) },
    { head: "Opened by", value: q => whoLabel(q.opened_by) },
    { head: "Opened", value: q => day(q.opened_at) },
    { head: "Owner", value: q => (ownerOf(q) ? whoLabel(ownerOf(q)) : "") },
    { head: "Hypotheses", value: q => q.hypotheses.length },
    { head: "Still open", value: q => q.open.length },
    { head: "Next check", value: q => day(q.next_check) },
    { head: "Runs", value: q => q.runs.length },
    { head: "Connection", value: q => connectionLabel(q.connection_id, connections) },
  ];

  return (
    <>
      <Figures testId="inquiry-figures">
        <Figure label="Open" value={formatCount(open.length)} testId="fig-inq-open"
          sub={open.length === 0 ? "none open" : noRun.length ? `${noRun.length} with no run yet` : "each has a run"} />
        <Figure label="Waiting" value={formatCount(waiting.length)} testId="fig-inq-waiting"
          title={reasons.length ? `Waiting for: ${reasons.join(" · ")}` : undefined}
          sub={waiting.length === 0 ? "none waiting"
            : reasons.length === 1 ? `for ${reasons[0]}` : `on ${reasons.length} different things`} />
        <Figure label="Closed" value={formatCount(closed.length)} testId="fig-inq-closed"
          sub={closed.length === 0 ? "none closed yet"
            : countBy(closed, q => q.closed_as || "closed").map(([k, n]) => `${n} ${k}`).join(" · ")} />
        <Figure label="Still open" value={formatCount(items.length)} testId="fig-inq-items"
          sub={items.length === 0 ? "nothing left open" : <>
            <span>{`across ${countNoun(withItems, "inquiry", "inquiries")}`}</span>
            {unstated && <Chip title="Each report named the gap without what would close it">none says what settles it</Chip>}
          </>} />
      </Figures>

      <NeedsYou testId="inquiry-needs" empty={next ? `Nothing needs you · the next check is ${whenWords(next)}` : "Nothing needs you"}>
        {[
          ...due.map(q => (
            <NeedsRow key={`due-${q.id}`} testId="needs-inq-due"
              title={`${inquiryLabel(q.question).text} · its check was due ${dateWords(q.next_check)}`}
              detail={q.waiting_for ? `waiting for ${q.waiting_for}` : undefined}
              actions={<Button size="xs" variant="secondary" onClick={() => onOpen(q.id)}>Open</Button>} />
          )),
          ...noRun.map(q => {
            const cost = (q.extra.proposed_run as ProposedRun | undefined)?.cost;
            return (
              <NeedsRow key={`norun-${q.id}`} testId="needs-inq-norun"
                title={inquiryLabel(q.question).text}
                detail={`open, with no run yet${cost?.tokens != null ? ` · a deep analysis would take about ${compactNumber(cost.tokens)} tokens here` : ""}`}
                actions={<Button size="xs" variant="secondary" onClick={() => onOpen(q.id)}>Open</Button>} />
            );
          }),
        ]}
      </NeedsYou>

      <ListCard<Inquiry> label="Inquiries" name="inquiries" testId="inquiry-list" rows={rows} rowKey={q => q.id}
        columns={columns}
        tools={<>
          <span className="aug-fs-xs" style={NUM}>
            {filter === "all" ? formatCount(all.length) : `${formatCount(rows.length)} of ${formatCount(all.length)}`}{scope ? ` · ${scope}` : ""}
          </span>
          <Segmented label="Filter inquiries by state" value={filter} onChange={setFilter}
            options={FILTERS.map(f => ({ value: f.id, label: f.label }))} />
          <Button size="xs" onClick={onAsk} title="A deep analysis opens an inquiry, or wakes the one already open on its subject">
            Ask why
          </Button>
        </>}
        empty={filter === "all"
          ? "No inquiry has been opened yet. A deep analysis opens one, and so does an alert that fires."
          : `No inquiry is ${filter} right now.`}
        renderRow={(q, first) => {
          const label = inquiryLabel(q.question);
          const owner = ownerOf(q);
          const latest = q.runs[q.runs.length - 1];
          // The reason every waiting inquiry shares is said once, in the figure above; a row names only its own.
          const meta = [
            q.state === "waiting" && reasons.length === 1 ? "waiting" : inquiryStateShort(q),
            q.runs.length ? countNoun(q.runs.length, "run") : "no run yet",
            q.next_check ? `next check ${dateWords(q.next_check)}` : "",
            owner ? `owned by ${whoLabel(owner)}` : "",
            q.opened_by && q.opened_by !== "person" ? `opened by ${whoLabel(q.opened_by)}` : "",
            many ? connectionLabel(q.connection_id, connections) : "",
            label.scheduled && latest?.why ? `latest: ${latest.why}` : "",
          ].filter(Boolean).join(" · ");
          return (
            <ListRow first={first} testId="inquiry-row" title={label.text} full={label.full} onOpen={() => onOpen(q.id)}
              mark={<Dot hue={q.state === "closed" && q.closed_as === "answered" ? "green" : STATE_DOT[q.state] ?? "grey"} title={inquiryState(q)} />}
              chips={q.hypotheses.length > 0 && <Chip>{countNoun(q.hypotheses.length, "hypothesis", "hypotheses")}</Chip>}
              figure={q.open.length > 0 ? `${formatCount(q.open.length)} still open` : undefined}
              figureTitle={q.open.length ? q.open.map(o => `· ${o.what}`).join("\n") : undefined}
              meta={meta} metaTitle={inquiryState(q)} />
          );
        }} />
    </>
  );
}

// ── the Reader ───────────────────────────────────────────────────────────────────────────

/** The run an inquiry waits for, as the Record worked it out: what it would cost here and what its result could change. */
interface ProposedRun {
  question?: string;
  rule?: string;
  cost?: {
    from?: string; tokens?: number | null; minutes?: number | null; n?: number; usd_floor?: number | null;
    ceiling?: { tokens?: number; seconds?: number };
  };
  could_change?: {
    open_items?: { what: string }[];
    open_hypotheses?: { claim: string; text: string }[];
    decisions?: unknown[];
  };
}

function InquiryReader({ id, connections, onBack, onMoved, onOpenRun, onOpenDecision, onOpenClaim }: {
  id: string; connections: Connection[]; onBack: () => void;
  /** A write books a new version of the inquiry; the page follows it to the id it now has. */
  onMoved: (id: string) => void;
  onOpenRun: (runId: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
}) {
  const load = useLoad(() => getInquiry(id), [id]);
  const q = load.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <BackHeader from="Inquiries" onBack={onBack} title={q?.question ?? "Inquiry"}
        chips={q && <StatusChip hue={STATE_HUE[q.state] ?? "muted"}>{inquiryState(q)}</StatusChip>} />
      <Gate load={load} what="the inquiry">
        {detail => <InquiryBody q={detail} connections={connections} onMoved={onMoved} onReload={load.reload}
          onOpenRun={onOpenRun} onOpenDecision={onOpenDecision} onOpenClaim={onOpenClaim} />}
      </Gate>
    </div>
  );
}

function InquiryBody({ q, connections, onMoved, onReload, onOpenRun, onOpenDecision, onOpenClaim }: {
  q: InquiryDetail; connections: Connection[]; onMoved: (id: string) => void; onReload: () => void;
  onOpenRun: (runId: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
}) {
  const actor = useActor();
  const supported = q.hypothesis_claims.filter(h => h.state === "supported");
  const proposed = (q.extra.proposed_run as ProposedRun | undefined) ?? null;
  const owner = typeof q.extra.owner === "string" ? q.extra.owner : "";
  const closed = q.state === "closed";

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [said, setSaid] = useState("");
  const [adding, setAdding] = useState(false);
  const [hypothesis, setHypothesis] = useState("");
  const [handTo, setHandTo] = useState("");
  const [checkOn, setCheckOn] = useState("");
  const [waitsFor, setWaitsFor] = useState("");
  const act = async (fn: () => Promise<InquiryDetail>, then?: (d: InquiryDetail) => void) => {
    setBusy(true);
    setError("");
    setSaid("");
    try {
      const d = await fn();
      then?.(d);
      onMoved(d.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  // Marking a claim wrong writes the CLAIM; this inquiry moves only if it established that claim
  // and woke. Either way the page re-reads, following its own new version when it has one.
  const afterMarked = async (words: string) => {
    setSaid(words);
    try {
      const fresh = await getInquiry(q.id);
      if (fresh.superseded_by) onMoved(fresh.superseded_by); else onReload();
    } catch {
      onReload();
    }
  };
  const today = new Date().toISOString().slice(0, 10);

  const rail = (
    <>
      <div className="aug-rail-head"><span className="aug-label">This inquiry</span></div>
      <Fact label="Opened by">{whoLabel(q.opened_by)}</Fact>
      <Fact label="Owner">{owner ? whoLabel(owner) : "nobody named"}</Fact>
      <Fact label="Opened">{day(q.opened_at)}</Fact>
      <Fact label="Connection">{connectionLabel(q.connection_id, connections)}</Fact>
      <Fact label="State">{inquiryState(q)}</Fact>
      <Fact label="Next check">{q.next_check ? `${day(q.next_check)} · ${dayDistance(q.next_check)}` : "none set"}</Fact>
      <Fact label="Runs">{q.runs.length}</Fact>
      {q.woke.length > 0 && <Fact label="Woken">{countNoun(q.woke.length, "time")} without being asked</Fact>}
      {!closed && !q.superseded_by && (
        <>
          <div className="aug-rail-head" style={{ marginTop: 12 }}><span className="aug-label">Hand it on</span></div>
          <div style={{ display: "grid", gap: 8 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <Input aria-label="Hand to" value={handTo} onChange={e => setHandTo(e.target.value)} placeholder="a person" style={{ flex: 1, minWidth: 0 }} />
              <Button size="xs" variant="outline" disabled={busy || !handTo.trim()}
                onClick={() => void act(() => handInquiry(q.id, handTo.trim()), () => { setHandTo(""); setSaid("Handed over. Nothing was sent: the name is on the record."); })}>
                Hand over
              </Button>
            </div>
            {owner && (
              <Button size="xs" variant="link" style={{ padding: 0, justifySelf: "start" }} disabled={busy}
                onClick={() => void act(() => handInquiry(q.id, ""), () => setSaid("The owner's name was taken off."))}>
                Take {whoLabel(owner)} off
              </Button>
            )}
            <div style={{ display: "flex", gap: 6 }}>
              <Input type="date" aria-label="Next check date" min={today} value={checkOn} onChange={e => setCheckOn(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
              <Button size="xs" variant="outline" disabled={busy || !checkOn}
                onClick={() => void act(() => setInquiryNextCheck(q.id, checkOn, waitsFor.trim()), () => { setCheckOn(""); setWaitsFor(""); setSaid("It waits until that day, then wakes on its own."); })}>
                Set
              </Button>
              {q.next_check && (
                <Button size="xs" variant="ghost" disabled={busy}
                  onClick={() => void act(() => setInquiryNextCheck(q.id, "", ""), () => setSaid("The check date was cleared, so it is open again."))}>
                  Clear
                </Button>
              )}
            </div>
            <Input aria-label="What it waits for" value={waitsFor} onChange={e => setWaitsFor(e.target.value)} placeholder="what it waits for (optional)" />
            <ActorField actor={actor} id="inq-actor" />
            <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: 0 }}>
              Handing it over sends nothing. A check date makes it wait until that day; clearing one opens it again.
            </p>
          </div>
        </>
      )}
    </>
  );

  return (
    <Page rail={rail}>
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 12px" }}>{error}</p>}
      {said && !error && <p className="aug-fs-sm" role="status" style={{ color: "var(--t2)", margin: "0 0 12px" }}>{said}</p>}
      {q.superseded_by && (
        <Callout tone="amber" style={{ marginBottom: 16 }}>
          <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>This is an earlier version of the inquiry. </span>
          <Button size="xs" variant="link" onClick={() => onMoved(q.superseded_by)}>Open it as it stands now</Button>
        </Callout>
      )}

      <Section label="What is established" meta={countNoun(supported.length + q.established_claims.length, "statement")}>
        {supported.length === 0 && q.established_claims.length === 0 ? (
          <Absent>Nothing is established yet. A hypothesis a run supports, and a finding a run measures, are listed here with how often statements of their kind have held.</Absent>
        ) : (
          <>
            {supported.map(h => <ClaimLine key={h.id} claim={h} onOpen={onOpenClaim} />)}
            {q.established_claims.map(c => (
              <ClaimLine key={c.id} claim={c} onOpen={onOpenClaim}
                note={c.restated_since ? "restated since this inquiry established it" : undefined}
                action={!q.superseded_by && <MarkWrong claim={c} actor={actor} onMarked={out => void afterMarked(markedWords(out))} />} />
            ))}
          </>
        )}
      </Section>

      <Section label="Hypotheses" meta={q.hypothesis_claims.length ? hypothesisMeta(q.hypothesis_claims) : undefined}
        action={!closed && !q.superseded_by && (
          <Button size="xs" variant="outline" aria-expanded={adding} onClick={() => setAdding(v => !v)}>Add a hypothesis</Button>
        )}>
        {adding && (
          <div className="aug-form-grid" style={{ marginBottom: 12 }}>
            <label className="aug-fs-sm" htmlFor="inq-hyp">You think</label>
            <Input id="inq-hyp" value={hypothesis} onChange={e => setHypothesis(e.target.value)} placeholder="A cause, stated so a run could test it" />
            <span />
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <ActorField actor={actor} id="inq-hyp-actor" />
              <Button size="xs" disabled={busy || !hypothesis.trim()}
                onClick={() => void act(() => addInquiryHypothesis(q.id, hypothesis.trim()), d => {
                  const like = (d as InquiryDetail & { resembles_refuted?: { refuted_on?: string; evidence?: string } | null }).resembles_refuted;
                  setSaid(like
                    ? `Added. The Record already holds one like it as refuted${like.refuted_on ? ` on ${like.refuted_on}` : ""}${like.evidence ? `: ${like.evidence}` : ""}. Yours is kept beside it.`
                    : "Added under your name. It stays open until a run tests it.");
                  setHypothesis("");
                  setAdding(false);
                })}>
                Add it
              </Button>
              <Button size="xs" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
              <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>It is recorded as said, under your name, until a run tests it.</span>
            </div>
          </div>
        )}
        {q.hypothesis_claims.length === 0 ? (
          <Absent>No hypothesis is recorded on this inquiry.</Absent>
        ) : q.hypothesis_claims.map(h => (
          <div className="aug-item" key={h.id}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{h.statement.text}</span>
              <StatusChip hue={HYPOTHESIS_HUE[h.state] ?? "muted"}>{h.state || "open"}</StatusChip>
            </div>
            <div className="aug-item-foot aug-fs-sm">
              {typeof h.extra.evidence === "string" && h.extra.evidence
                ? <span>{h.state === "refuted"
                    ? (typeof h.extra.marked_wrong_by === "string" ? `marked false by ${whoLabel(h.extra.marked_wrong_by)}: ` : "tested false: ")
                    : h.state === "supported" ? "held: " : ""}{h.extra.evidence}</span>
                : <span>{h.state === "abandoned" ? "not tested by any run" : "no run has decided it"}</span>}
              <span>{h.author_kind === "person" ? "held by" : "proposed by"} {whoLabel(h.author_kind === "agent" ? `agent:${h.author}` : h.author)}</span>
              {!q.superseded_by && <><span style={{ flex: 1 }} /><MarkWrong claim={h} actor={actor} onMarked={() => void afterMarked("Recorded as refuted. It is kept, so it is not proposed again.")} /></>}
            </div>
          </div>
        ))}
        {q.refused.length > 0 && (
          <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: "8px 0 0" }}>
            {countNoun(q.refused.length, "hypothesis", "hypotheses")} proposed again after being refuted here {q.refused.length === 1 ? "was" : "were"} not re-tested.
          </p>
        )}
      </Section>

      <Section label="Still open" meta={q.open.length ? countNoun(q.open.length, "item") : undefined}>
        {q.open.length === 0 ? (
          <Absent>Nothing is left open on this inquiry.</Absent>
        ) : q.open.map(o => (
          <div className="aug-item" key={o.what}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{o.what}</div>
            <div className="aug-item-foot aug-fs-sm"><span>what would settle it: {o.settled_by || "not stated"}</span></div>
          </div>
        ))}
      </Section>

      <Section label="Decisions it fed">
        {q.decisions.length === 0 ? (
          <Absent>No decision cites this inquiry yet.</Absent>
        ) : (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {q.decisions.map(d => <Button key={d} size="xs" variant="outline" onClick={() => onOpenDecision(d)}>Open the decision</Button>)}
          </div>
        )}
      </Section>

      <Section label="Runs and cost" meta={countNoun(q.runs.length, "run")}
        action={q.state !== "closed" && (
          <Button size="xs" variant="outline" disabled={busy} onClick={() => void act(() => proposeInquiryRun(q.id))}
            title="Works out the next run and what it would cost on this install. Spends no model.">
            Propose the next run
          </Button>
        )}>
        {q.run_verdicts.map(r => (
          <div className="aug-item" key={r.run}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <StatusChip hue={r.verdict === "answered" ? "positive" : r.verdict === "contradicted" ? "caution" : "negative"}>
                {verdictWords(r.verdict)}
              </StatusChip>
              <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{r.why}</span>
            </div>
            <div className="aug-item-foot aug-fs-sm">
              {r.at && <span>{day(r.at)}</span>}
              <span style={{ flex: 1 }} />
              <Button size="xs" variant="ghost" onClick={() => onOpenRun(r.run)}>Open the run</Button>
            </div>
          </div>
        ))}
        {proposed && <ProposedRunNote run={proposed} />}
      </Section>

      <Section label="Lessons">
        {q.lessons.length > 0 ? q.lessons.map(l => (
          <div className="aug-item" key={l.believed}>
            <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>{l.turned_out}</div>
            <div className="aug-item-foot aug-fs-sm"><span>believed at the start: {l.believed}</span></div>
          </div>
        )) : q.state === "closed" ? (
          <Absent>It was closed without a lesson written.</Absent>
        ) : (
          <CloseForm busy={busy} onClose={(as, lessons) => void act(() => closeInquiry(q.id, as, lessons))} />
        )}
      </Section>
    </Page>
  );
}

function hypothesisMeta(hs: Claim[]): string {
  const by = (s: string) => hs.filter(h => (h.state || "open") === s).length;
  return [["supported", by("supported")], ["refuted", by("refuted")], ["open", by("open")], ["abandoned", by("abandoned")]]
    .filter(([, n]) => (n as number) > 0).map(([s, n]) => `${n} ${s}`).join(" · ");
}

function ProposedRunNote({ run }: { run: ProposedRun }) {
  const cost = run.cost ?? {};
  const could = run.could_change ?? {};
  const measured = cost.tokens != null
    ? `About ${compactNumber(cost.tokens)} tokens${cost.minutes != null ? ` and ${formatTableNumber(cost.minutes)} minutes` : ""}, from ${countNoun(cost.n ?? 0, "run")} of this kind here.`
    : `Not measured here yet${cost.ceiling?.tokens ? `: at most ${compactNumber(cost.ceiling.tokens)} tokens${cost.ceiling.seconds ? ` and ${Math.round(cost.ceiling.seconds / 60)} minutes` : ""}, its ceiling` : ""}.`;
  const changes = [
    could.open_items?.length ? `${countNoun(could.open_items.length, "open item")}` : "",
    could.open_hypotheses?.length ? `the open hypothesis${could.open_hypotheses.length === 1 ? "" : "es"}: ${could.open_hypotheses.map(h => h.text).join("; ")}` : "",
    could.decisions?.length ? countNoun(could.decisions.length, "decision") : "",
  ].filter(Boolean);
  return (
    <Callout tone="blue" style={{ marginTop: 10 }}>
      <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>The next run: a deep analysis of this question.</div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 4, lineHeight: 1.55 }}>
        <div>What it would cost: {measured}</div>
        <div>What it could change: {changes.length ? changes.join(" · ") : "nothing that is recorded as open"}.</div>
        {run.rule && <div style={{ color: "var(--t3)" }}>{run.rule.charAt(0).toUpperCase() + run.rule.slice(1)}.</div>}
      </div>
    </Callout>
  );
}

const CLOSE_AS = ["answered", "overtaken", "abandoned"] as const;

/** A person closes it, and says what was believed at the start that turned out wrong. */
function CloseForm({ busy, onClose }: {
  busy: boolean; onClose: (closedAs: string, lessons: { believed: string; turned_out: string }[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [closedAs, setClosedAs] = useState<string>("answered");
  const [believed, setBelieved] = useState("");
  const [turnedOut, setTurnedOut] = useState("");
  if (!open) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Absent>Lessons are written when a person closes the inquiry.</Absent>
        <Button size="xs" variant="outline" onClick={() => setOpen(true)}>Close this inquiry</Button>
      </div>
    );
  }
  const lesson = believed.trim() && turnedOut.trim() ? [{ believed: believed.trim(), turned_out: turnedOut.trim() }] : [];
  return (
    <div className="aug-form-grid">
      <label className="aug-fs-sm">Closed as</label>
      <Segmented label="Closed as" value={closedAs} onChange={setClosedAs} style={{ justifySelf: "start" }}
        options={CLOSE_AS.map(c => ({ value: c, label: c }))} />
      <label className="aug-fs-sm" htmlFor="inq-believed">Believed at the start</label>
      <Input id="inq-believed" value={believed} onChange={e => setBelieved(e.target.value)} placeholder="What was assumed when it opened" />
      <label className="aug-fs-sm" htmlFor="inq-turned">Turned out</label>
      <Input id="inq-turned" value={turnedOut} onChange={e => setTurnedOut(e.target.value)} placeholder="What the inquiry found instead" />
      <span />
      <div style={{ display: "flex", gap: 8 }}>
        <Button size="xs" disabled={busy} onClick={() => onClose(closedAs, lesson)}>Close it</Button>
        <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}
