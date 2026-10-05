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
import { compactNumber, countNoun, formatTableNumber } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import {
  closeInquiry, getClaim, getInquiry, listInquiries, proposeInquiryRun, verdictWords, whoLabel,
  type Claim, type Inquiry, type InquiryDetail,
} from "@/lib/record";
import {
  Absent, BackHeader, ClaimLine, Fact, Gate, Ledger, Page, Section, day, dayDistance, useLoad,
  type LedgerColumn,
} from "@/components/record/kit";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
  const [filter, setFilter] = useState<StateFilter>("all");
  const load = useLoad(() => listInquiries({ limit: 300 }), []);
  const rows = useMemo(
    () => (load.data ?? []).filter(q => filter === "all" || q.state === filter),
    [load.data, filter]);
  const many = new Set((load.data ?? []).map(q => q.connection_id)).size > 1;
  const columns: LedgerColumn<Inquiry>[] = [
    { head: "Question", cell: q => q.question },
    { head: "State", cell: q => <StatusChip hue={STATE_HUE[q.state] ?? "muted"}>{inquiryState(q)}</StatusChip>, width: 190 },
    { head: "Opened by", cell: q => whoLabel(q.opened_by), width: 150 },
    { head: "Hypotheses", cell: q => q.hypotheses.length, num: true, width: 96 },
    { head: "Still open", cell: q => q.open.length, num: true, width: 90 },
    { head: "Next check", cell: q => (q.next_check ? `${day(q.next_check)} · ${dayDistance(q.next_check)}` : "—"), width: 170 },
    { head: "Runs", cell: q => q.runs.length, num: true, width: 60 },
    ...(many ? [{ head: "Connection", cell: (q: Inquiry) => connectionLabel(q.connection_id, connections), width: 150 }] : []),
  ];
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--bg-0)" }}>
      <div className="aug-toolbar">
        <div role="group" aria-label="Filter inquiries by state" className="aug-segmented">
          {FILTERS.map(f => (
            <Button key={f.id} variant="ghost" size="xs" aria-pressed={filter === f.id}
              className={`aug-seg-item${filter === f.id ? " active" : ""}`} onClick={() => setFilter(f.id)}>
              {f.label}
            </Button>
          ))}
        </div>
        {load.data && (
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
            {countNoun(rows.length, "inquiry", "inquiries")} · every connection
          </span>
        )}
        <span style={{ flex: 1 }} />
        <Button size="xs" onClick={onAsk} title="A deep analysis opens an inquiry, or wakes the one already open on its subject">
          Ask why
        </Button>
      </div>
      <Page wide>
        <Gate load={load} what="inquiries">
          {() => (
            <Ledger name="inquiries" columns={columns} rows={rows} rowKey={q => q.id} onOpen={q => onOpen(q.id)}
              empty={filter === "all"
                ? "No inquiry has been opened yet. A deep analysis opens one, and so does an alert that fires; a second question on the same subject wakes the one already open instead of starting another."
                : `No inquiry is ${filter} right now.`} />
          )}
        </Gate>
      </Page>
    </div>
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
        {detail => <InquiryBody q={detail} connections={connections} onMoved={onMoved}
          onOpenRun={onOpenRun} onOpenDecision={onOpenDecision} onOpenClaim={onOpenClaim} />}
      </Gate>
    </div>
  );
}

function InquiryBody({ q, connections, onMoved, onOpenRun, onOpenDecision, onOpenClaim }: {
  q: InquiryDetail; connections: Connection[]; onMoved: (id: string) => void;
  onOpenRun: (runId: string) => void; onOpenDecision: (id: string) => void; onOpenClaim: (id: string) => void;
}) {
  const established = useLoad<Claim[]>(
    () => Promise.all(q.claims.map(cid => getClaim(cid).catch(() => null))).then(cs => cs.filter((c): c is Claim => c !== null)),
    [q.id, q.claims.join(",")]);
  const supported = q.hypothesis_claims.filter(h => h.state === "supported");
  const proposed = (q.extra.proposed_run as ProposedRun | undefined) ?? null;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const act = async (fn: () => Promise<InquiryDetail>) => {
    setBusy(true);
    setError("");
    try { onMoved((await fn()).id); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };

  const rail = (
    <>
      <div className="aug-rail-head"><span className="aug-label">This inquiry</span></div>
      <Fact label="Opened by">{whoLabel(q.opened_by)}</Fact>
      <Fact label="Opened">{day(q.opened_at)}</Fact>
      <Fact label="Connection">{connectionLabel(q.connection_id, connections)}</Fact>
      <Fact label="State">{inquiryState(q)}</Fact>
      <Fact label="Next check">{q.next_check ? `${day(q.next_check)} · ${dayDistance(q.next_check)}` : "none set"}</Fact>
      <Fact label="Runs">{q.runs.length}</Fact>
      {q.woke.length > 0 && <Fact label="Woken">{countNoun(q.woke.length, "time")} without being asked</Fact>}
    </>
  );

  return (
    <Page rail={rail}>
      {error && <p className="aug-fs-sm" role="alert" style={{ color: "var(--red4)", margin: "0 0 12px" }}>{error}</p>}
      {q.superseded_by && (
        <div className="aug-callout aug-callout-amber" style={{ marginBottom: 16 }}>
          <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>This is an earlier version of the inquiry. </span>
          <Button size="xs" variant="link" onClick={() => onMoved(q.superseded_by)}>Open it as it stands now</Button>
        </div>
      )}

      <Section label="What is established" meta={countNoun(supported.length + (established.data?.length ?? 0), "statement")}>
        {supported.length === 0 && q.claims.length === 0 ? (
          <Absent>Nothing is established yet. A hypothesis a run supports, and a finding a run measures, are listed here with how often statements of their kind have held.</Absent>
        ) : (
          <>
            {supported.map(h => <ClaimLine key={h.id} claim={h} onOpen={onOpenClaim} />)}
            <Gate load={established} what="the established claims">
              {cs => <>{cs.map(c => <ClaimLine key={c.id} claim={c} onOpen={onOpenClaim} />)}</>}
            </Gate>
          </>
        )}
      </Section>

      <Section label="Hypotheses" meta={q.hypothesis_claims.length ? hypothesisMeta(q.hypothesis_claims) : undefined}>
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
                ? <span>{h.state === "refuted" ? "tested false: " : h.state === "supported" ? "held: " : ""}{h.extra.evidence}</span>
                : <span>{h.state === "abandoned" ? "not tested by any run" : "no run has decided it"}</span>}
              <span>proposed by {whoLabel(h.author_kind === "agent" ? `agent:${h.author}` : h.author)}</span>
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
    <div className="aug-callout aug-callout-blue" style={{ marginTop: 10 }}>
      <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>The next run: a deep analysis of this question.</div>
      <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 4, lineHeight: 1.55 }}>
        <div>What it would cost: {measured}</div>
        <div>What it could change: {changes.length ? changes.join(" · ") : "nothing that is recorded as open"}.</div>
        {run.rule && <div style={{ color: "var(--t3)" }}>{run.rule.charAt(0).toUpperCase() + run.rule.slice(1)}.</div>}
      </div>
    </div>
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
      <div role="group" aria-label="Closed as" className="aug-segmented" style={{ justifySelf: "start" }}>
        {CLOSE_AS.map(c => (
          <Button key={c} variant="ghost" size="xs" aria-pressed={closedAs === c}
            className={`aug-seg-item${closedAs === c ? " active" : ""}`} onClick={() => setClosedAs(c)}>{c}</Button>
        ))}
      </div>
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
