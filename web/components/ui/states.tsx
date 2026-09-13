"use client";

/**
 * The universal states beyond empty and loading (INSTRUMENT.md §6): an error, a partial answer,
 * and the refusal. Every list, panel and answer needs its states designed, never improvised, and
 * each of these names its next action.
 *
 *   <ErrorState>    what failed · what it means · what to do, carrying the run id and the exact
 *                   object so it pastes into a ticket. Retry is never the only door offered.
 *   <PartialState>  a real answer with a named hole — the hole stated in the same breath as the
 *                   figure, and unattributed magnitude drawn as a hatched bar labelled unknown:
 *                   never assigned, never dropped. "This figure is a floor, not a total."
 *   <Refusal>       confident, specific, and offering the nearest answerable question. "Answer
 *                   anyway, unguarded" may exist; it is never the primary door.
 */
import React from "react";

import { Button } from "@/components/ui/button";

export interface StateDoor {
  label: string;
  onClick: () => void;
  /** The one door that resolves the state, drawn in the state's hue. At most one per state. */
  primary?: boolean;
  title?: string;
}

function Doors({ doors }: { doors?: StateDoor[] }) {
  if (!doors?.length) return null;
  return (
    <div className="aug-state-actions">
      {doors.map(d => (
        <Button key={d.label} variant="ghost" size="xs" title={d.title} onClick={d.onClick}
          className={`aug-state-action${d.primary ? " aug-state-action-primary" : ""}`}>
          {d.label}
        </Button>
      ))}
    </div>
  );
}

function Head({ kind, meta }: { kind: string; meta?: React.ReactNode }) {
  return (
    <div className="aug-state-head">
      <span className="aug-state-kind">{kind}</span>
      {meta != null && <span className="aug-state-meta">{meta}</span>}
    </div>
  );
}

export function ErrorState({ kind = "Failed", meta, what, means, doors, runId, object, className = "", style }: {
  /** The short kind label — "Query failed", "Connection refused". Drawn in mono capitals. */
  kind?: string;
  /** Where it failed, in mono at the right: "bigquery · 403". */
  meta?: React.ReactNode;
  /** Sentence one: what failed, naming the exact object. */
  what: React.ReactNode;
  /** Sentence two: what that means for the answer or the screen. */
  means?: React.ReactNode;
  /** Sentence three is the doors — what to do. Never Retry alone. */
  doors?: StateDoor[];
  /** The run and the object, printed so the error pastes into a ticket without a screenshot. */
  runId?: string;
  object?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const ticket = [runId, object].filter(Boolean).join(" · ");
  return (
    <div role="alert" className={`aug-error ${className}`} style={style}>
      <Head kind={kind} meta={meta} />
      <div className="aug-state-what">{what}</div>
      {means != null && <div className="aug-state-detail">{means}</div>}
      <Doors doors={doors} />
      {ticket && (
        <div className="aug-state-ticket">ref <span className="aug-state-ticket-id">{ticket}</span></div>
      )}
    </div>
  );
}

export interface PartialBar {
  label: string;
  /** Share of the whole, 0–1; the bar's width is this share of `scale` pixels. */
  share: number;
  /** The figure printed at the right. Ignored for the unknown bar, which says "unknown". */
  value?: React.ReactNode;
  /** The part nobody could attribute: hatched, and labelled unknown. */
  unknown?: boolean;
  /** Series hue for an attributed driver; defaults to the de-emphasis grey. */
  color?: string;
}

export function PartialState({ kind = "Partial", meta, claim, detail, bars, doors, scale = 160, className = "", style }: {
  /** "Partial · 3 of 4 drivers". */
  kind?: string;
  /** Usually the computed confidence, in mono at the right. */
  meta?: React.ReactNode;
  /** The answer, with its figures. */
  claim: React.ReactNode;
  /** The hole, named: what could not be computed and what the figure therefore is. */
  detail?: React.ReactNode;
  bars?: PartialBar[];
  doors?: StateDoor[];
  scale?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={className} style={{ display: "flex", flexDirection: "column", gap: 10, ...style }}>
      <div className="aug-partial">
        <Head kind={kind} meta={meta} />
        <div className="aug-state-claim">{claim}</div>
        {detail != null && <div className="aug-state-detail">{detail}</div>}
        <Doors doors={doors} />
      </div>
      {bars?.length ? (
        <div className="aug-partial-bars">
          {bars.map(b => (
            <div key={b.label} className={`aug-partial-bar${b.unknown ? " aug-partial-bar-unknown" : ""}`}>
              <span className="aug-partial-bar-label" title={b.label}>{b.label}</span>
              <span
                className={`aug-partial-bar-fill${b.unknown ? " aug-hatch" : ""}`}
                style={{
                  width: Math.max(2, Math.round(Math.min(1, Math.max(0, b.share)) * scale)),
                  ...(b.color && !b.unknown ? { background: b.color } : null),
                }}
              />
              <span className="aug-partial-bar-value">{b.unknown ? "unknown" : b.value}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Refusal({ kind = "Refused", meta, claim, detail, doors, className = "", style }: {
  /** "Refused · premise failed". */
  kind?: string;
  /** The receipt id, in mono at the right. */
  meta?: React.ReactNode;
  /** The refusal itself, confident and specific: "I will not tell you why X fell, because it did not." */
  claim: React.ReactNode;
  /** The evidence that makes the refusal right. */
  detail?: React.ReactNode;
  /** The nearest answerable question first. An "unguarded" door is never drawn as the primary. */
  doors?: StateDoor[];
  className?: string;
  style?: React.CSSProperties;
}) {
  const safe = doors?.map(d => (/unguarded/i.test(d.label) ? { ...d, primary: false } : d));
  return (
    <div className={`aug-refusal ${className}`} style={style}>
      <Head kind={kind} meta={meta} />
      <div className="aug-state-claim">{claim}</div>
      {detail != null && <div className="aug-state-detail">{detail}</div>}
      <Doors doors={safe} />
    </div>
  );
}
