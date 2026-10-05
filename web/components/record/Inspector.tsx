"use client";

/**
 * The inspector — a cited record read beside the page that cites it (the 2027 study §U and §V;
 * decided on a mock-up, 2026-10-05).
 *
 * A decision cites claims, a claim names the decisions that stood on it, an inquiry cites both.
 * Following one of those used to mean leaving the page; here it opens in a drawer on the right
 * and the page stays where it is. The drawer only reads: anything that writes — marking a claim
 * wrong, booking an outcome — is on the record's own page, one click away under "Open full page".
 * Esc or the close button puts it away. A citation inside the drawer opens in the drawer.
 *
 * It is offered on Now and the Record's pages and nowhere else, and it changes no link that
 * existed before those pages did.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { Connection } from "@/lib/api";
import { countNoun, formatTableNumber } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import {
  getClaim, getDecision, getInquiry, getMission, verdictWords, whoLabel,
  type Claim, type DecisionDetail, type InquiryDetail, type MissionDetail,
} from "@/lib/record";
import {
  Absent, Counted, Gate, StatusMark, TierMark, day, dayDistance, useLoad,
} from "@/components/record/kit";
import { reviewState } from "@/components/decisions/DecisionsPanel";
import { inquiryState } from "@/components/inquiries/InquiriesPanel";
import { objectiveLine } from "@/components/missions/MissionsPanel";
import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

export type InspectLayer = "claims" | "decisions" | "inquiries" | "missions";
export interface InspectTarget { layer: InspectLayer; id: string }
export type Inspect = (layer: InspectLayer, id: string) => void;

const KIND_WORD: Record<InspectLayer, string> = {
  claims: "Claim", decisions: "Decision", inquiries: "Inquiry", missions: "Mission",
};

/**
 * Gives a page its drawer. `children` gets the function that opens a record in it; the drawer
 * belongs to the page it was opened from, so when `pageKey` changes it is gone.
 */
export function InspectorHost({ connections, pageKey, onOpenFull, top = 0, children }: {
  connections: Connection[];
  pageKey: string;
  /** How far down the drawer starts — under a workspace's tabs, so they stay in reach. */
  top?: number;
  /** "Open full page": leave for the record's own page. */
  onOpenFull: Inspect;
  children: (inspect: Inspect) => React.ReactNode;
}) {
  const [open, setOpen] = useState<{ target: InspectTarget; on: string } | null>(null);
  const target = open && open.on === pageKey ? open.target : null;
  const inspect = useCallback<Inspect>((layer, id) => setOpen({ target: { layer, id }, on: pageKey }), [pageKey]);
  const close = useCallback(() => setOpen(null), []);

  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, close]);

  return (
    <div style={{ position: "relative", flex: 1, display: "flex", minHeight: 0, minWidth: 0 }}>
      {children(inspect)}
      {target && (
        <Inspector target={target} connections={connections} top={top} onClose={close} onInspect={inspect}
          onOpenFull={(layer, id) => { close(); onOpenFull(layer, id); }} />
      )}
    </div>
  );
}

function Inspector({ target, connections, top, onClose, onInspect, onOpenFull }: {
  target: InspectTarget; connections: Connection[]; top: number; onClose: () => void; onInspect: Inspect; onOpenFull: Inspect;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  // The drawer takes the keyboard as it opens, and again when what it shows changes.
  useEffect(() => { closeRef.current?.focus(); }, [target.layer, target.id]);
  return (
    <aside className="aug-beside" role="complementary" aria-label={`${KIND_WORD[target.layer]}, opened beside the page`}
      data-testid="inspector" style={{ top }}>
      <div className="aug-beside-head">
        <span className="aug-label">{KIND_WORD[target.layer]}</span>
        <span style={{ flex: 1 }} />
        <Button ref={closeRef} size="xs" variant="ghost" onClick={onClose} aria-label="Close" title="Close (Esc)">
          <Icon name="close" size={14} />
        </Button>
      </div>
      <div className="aug-beside-body">
        {target.layer === "claims" && <ClaimView id={target.id} connections={connections} onInspect={onInspect} />}
        {target.layer === "decisions" && <DecisionView id={target.id} onInspect={onInspect} />}
        {target.layer === "inquiries" && <InquiryView id={target.id} onInspect={onInspect} />}
        {target.layer === "missions" && <MissionView id={target.id} />}
      </div>
      <div className="aug-beside-foot">
        <Button size="xs" variant="outline" style={{ width: "100%" }} onClick={() => onOpenFull(target.layer, target.id)}>
          Open full page
        </Button>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Esc closes it. To change anything, open the full page.</span>
      </div>
    </aside>
  );
}

// ── the pieces ───────────────────────────────────────────────────────────────────────────

function Part({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="aug-beside-part">
      <div className="aug-label">{label}</div>
      {children}
    </div>
  );
}

/** A cited record as a box of its own; with `onOpen`, the whole box opens it in the drawer. */
function Box({ children, foot, onOpen, chosen }: {
  children: React.ReactNode; foot?: React.ReactNode; onOpen?: () => void; chosen?: boolean;
}) {
  const body = (
    <>
      <span className="aug-fs-ui" style={{ color: "var(--t1)" }}>{children}</span>
      {foot && <span className="aug-item-foot aug-fs-sm">{foot}</span>}
    </>
  );
  return onOpen
    ? <Button variant="ghost" className="aug-beside-box aug-beside-link" onClick={onOpen}>{body}</Button>
    : <div className="aug-beside-box" data-chosen={chosen || undefined}>{body}</div>;
}

function Title({ children, marks }: { children: React.ReactNode; marks?: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <p className="aug-beside-title">{children}</p>
      {marks && <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>{marks}</div>}
    </div>
  );
}

const WARRANT_WORDS: Record<string, string> = {
  run: "a run measured it", document: "a document states it", attestation: "a person attested it", claim: "it rests on another claim",
};

function ClaimView({ id, connections, onInspect }: { id: string; connections: Connection[]; onInspect: Inspect }) {
  const load = useLoad(() => getClaim(id), [id]);
  return (
    <Gate load={load} what="the claim">
      {(c: Claim) => (
        <>
          <Title marks={<><StatusMark status={c.status} /><TierMark tier={c.tier} /><Counted claim={c} brief /></>}>
            {c.statement.text}
          </Title>
          {c.superseded_by && (
            <Box onOpen={() => onInspect("claims", c.superseded_by)} foot={<span>open the version that replaced it</span>}>
              This version was replaced.
            </Box>
          )}
          <Part label="Why it is held">
            {c.warrants.length === 0
              ? <Absent>{c.tier === "said" ? "It was said, and nothing measured it." : "No warrant is recorded on this version."}</Absent>
              : c.warrants.map(w => (
                <Box key={`${w.kind}:${w.ref}`} onOpen={w.kind === "claim" ? () => onInspect("claims", w.ref) : undefined}
                  foot={<>{w.detail && <span>{WARRANT_WORDS[w.kind] ?? w.kind}</span>}{w.kind === "attestation" && w.ref && <span>by {whoLabel(w.ref)}</span>}</>}>
                  {w.detail || WARRANT_WORDS[w.kind] || w.kind}
                </Box>
              ))}
          </Part>
          <Part label="Who relies on it">
            {(c.relied_on_by?.length ?? 0) === 0 ? <Absent>No decision cites this claim.</Absent>
              : c.relied_on_by!.map((d, i) => (
                <Box key={d} onOpen={() => onInspect("decisions", d)}>
                  {c.relied_on_by!.length === 1 ? "One decision stood on it" : `Decision ${i + 1} of ${c.relied_on_by!.length}`}
                </Box>
              ))}
          </Part>
          <Part label="Who else was told">
            {(c.told?.length ?? 0) === 0
              ? <Absent>{c.told_note ? c.told_note.charAt(0).toUpperCase() + c.told_note.slice(1) + "." : "Nothing is on record."}</Absent>
              : <Box>{countNoun(c.told!.length, "message")} cited the answer behind it</Box>}
          </Part>
          <Part label="About it">
            <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0, lineHeight: 1.6 }}>
              A {c.kind}{c.state ? `, ${c.state}` : ""}, on {c.about.kind === "connection" ? connectionLabel(c.about.key, connections) : `${c.about.kind} ${c.about.key}`}.
              {" "}As of {day(c.as_of) || "an undated day"}; version {c.version}{c.supersedes ? ", which replaced an earlier one" : ""}.
              {" "}By {whoLabel(c.author_kind === "agent" ? `agent:${c.author}` : c.author)}.
            </p>
          </Part>
        </>
      )}
    </Gate>
  );
}

const REVIEW_WORDS: Record<string, string> = { reviewed: "reviewed", due: "review due", waiting: "awaiting its date" };

function DecisionView({ id, onInspect }: { id: string; onInspect: Inspect }) {
  const load = useLoad(() => getDecision(id), [id]);
  return (
    <Gate load={load} what="the decision">
      {(d: DecisionDetail) => {
        const state = reviewState(d);
        const others = d.options.filter(o => o.id !== d.chosen && o.description !== d.chosen);
        return (
          <>
            <Title marks={<>
              <StatusChip hue={state === "due" ? "caution" : state === "reviewed" ? "muted" : "info"}>{REVIEW_WORDS[state]}</StatusChip>
              {d.reopened_by && <StatusChip hue="caution">reopened</StatusChip>}
            </>}>{d.question}</Title>
            {d.superseded_by && (
              <Box onOpen={() => onInspect("decisions", d.superseded_by)} foot={<span>open it as it stands now</span>}>
                This is an earlier version of the decision.
              </Box>
            )}
            <Part label="What was chosen">
              <Box chosen foot={<span>decided {day(d.decided_at)} by {whoLabel(d.decided_by)}</span>}>{d.chosen}</Box>
              {others.map(o => <Box key={o.id} foot={<span>not taken</span>}>{o.description}</Box>)}
            </Part>
            <Part label="What it relied on">
              {d.relied_on_claims.length === 0 ? <Absent>No claim was cited when it was booked.</Absent>
                : d.relied_on_claims.map(c => (
                  <Box key={c.id} onOpen={() => onInspect("claims", c.superseded_by || c.id)}
                    foot={c.superseded_by ? <span style={{ color: "var(--amb4)" }}>restated since — opens what replaced it</span> : undefined}>
                    {c.statement.text}
                  </Box>
                ))}
            </Part>
            <Part label="What was expected">
              {d.expectation ? <Box foot={<span>settles {day(String(d.expectation.extra.settles_on ?? d.review_on))}</span>}>{d.expectation.statement.text}</Box>
                : <Absent>No expectation was booked with it.</Absent>}
            </Part>
            <Part label="What became of it">
              {d.outcome_record
                ? <Box foot={<>
                    {d.outcome_record.actual != null && <span>actual {formatTableNumber(d.outcome_record.actual)}</span>}
                    <span>measured {day(d.outcome_record.measured_on)}</span>
                  </>}>{verdictWords(d.outcome_record.verdict)}{d.outcome_record.why ? `: ${d.outcome_record.why}` : ""}</Box>
                : <Absent>Not reviewed yet. Its review date is {d.review_on ? `${day(d.review_on)} (${dayDistance(d.review_on)})` : "not set"}.</Absent>}
            </Part>
            {d.dissent.length > 0 && (
              <Part label="Dissent">
                {d.dissent.map(x => <Box key={`${x.who}:${x.why}`} foot={<span>{whoLabel(x.who)}</span>}>{x.why}</Box>)}
              </Part>
            )}
          </>
        );
      }}
    </Gate>
  );
}

function InquiryView({ id, onInspect }: { id: string; onInspect: Inspect }) {
  const load = useLoad(() => getInquiry(id), [id]);
  return (
    <Gate load={load} what="the inquiry">
      {(q: InquiryDetail) => {
        const owner = typeof q.extra.owner === "string" ? q.extra.owner : "";
        return (
          <>
            <Title marks={<StatusChip hue={q.state === "open" ? "info" : q.state === "waiting" ? "caution" : "muted"}>{inquiryState(q)}</StatusChip>}>
              {q.question}
            </Title>
            {q.superseded_by && (
              <Box onOpen={() => onInspect("inquiries", q.superseded_by)} foot={<span>open it as it stands now</span>}>
                This is an earlier version of the inquiry.
              </Box>
            )}
            <Part label="What is established">
              {q.established_claims.length === 0 ? <Absent>Nothing is established yet.</Absent>
                : q.established_claims.map(c => (
                  <Box key={c.id} onOpen={() => onInspect("claims", c.id)}
                    foot={c.restated_since ? <span style={{ color: "var(--amb4)" }}>restated since</span> : undefined}>
                    {c.statement.text}
                  </Box>
                ))}
            </Part>
            <Part label="Hypotheses">
              {q.hypothesis_claims.length === 0 ? <Absent>None is recorded.</Absent>
                : q.hypothesis_claims.map(h => (
                  <Box key={h.id} onOpen={() => onInspect("claims", h.id)} foot={<span>{h.state || "open"}</span>}>{h.statement.text}</Box>
                ))}
            </Part>
            <Part label="Still open">
              {q.open.length === 0 ? <Absent>Nothing is left open.</Absent>
                : q.open.map(o => <Box key={o.what} foot={<span>would settle it: {o.settled_by || "not stated"}</span>}>{o.what}</Box>)}
            </Part>
            <Part label="About it">
              <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0, lineHeight: 1.6 }}>
                Opened {day(q.opened_at)} by {whoLabel(q.opened_by)}. {owner ? `Owned by ${whoLabel(owner)}.` : "Nobody is named as its owner."}
                {" "}{q.next_check ? `Next checked ${day(q.next_check)} (${dayDistance(q.next_check)}).` : "No check date is set."}
                {" "}{countNoun(q.runs.length, "run")}.
              </p>
            </Part>
          </>
        );
      }}
    </Gate>
  );
}

function MissionView({ id }: { id: string }) {
  const load = useLoad(() => getMission(id), [id]);
  return (
    <Gate load={load} what="the mission">
      {(m: MissionDetail) => (
        <>
          <Title marks={<StatusChip hue={m.state === "active" ? "positive" : m.state === "paused" ? "caution" : "muted"}>{m.state}</StatusChip>}>
            {m.name}
          </Title>
          <Part label="What it is trying to achieve"><Box>{objectiveLine(m.objective)}</Box></Part>
          <Part label="Without damaging">
            {m.constraints.length === 0 ? <Absent>No constraint was written.</Absent>
              : m.constraints.map(c => (
                <Box key={c.metric}>{c.metric} {c.bound === "at_most" ? "at most" : "at least"} {c.limit != null ? formatTableNumber(c.limit) : "its limit"}</Box>
              ))}
          </Part>
          <Part label="Its last report">
            {m.reports.length === 0 ? <Absent>None is booked yet.</Absent>
              : <Box foot={m.reports[0].period ? <span>{day(m.reports[0].period.from)} to {day(m.reports[0].period.to)}</span> : undefined}>{m.reports[0].headline}</Box>}
          </Part>
          <Part label="About it">
            <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0, lineHeight: 1.6 }}>
              {m.owner ? `Owned by ${whoLabel(m.owner)}.` : "It has no owner, so it does not run."}
              {" "}It may interrupt {m.budget.interruptions_per_week} times a week and reports {m.review.cadence}
              {m.review.next_report_on ? `, next on ${day(m.review.next_report_on)}` : ""}.
            </p>
          </Part>
        </>
      )}
    </Gate>
  );
}
