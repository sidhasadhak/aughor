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

import { Spinner } from "@radix-ui/themes";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";

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
        <Button key={d.label} variant={d.primary ? "secondary" : "outline"} size="xs" title={d.title} onClick={d.onClick}>
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

/**
 * A read in flight — named, so a person knows WHAT is coming ("Loading agents…"), announced to
 * assistive tech (`role="status"`), and drawn one way. Arc UI counted 37 hand-rolled "Loading…"
 * lines across 26 components in five font sizes and two greys, three of them in a hard-coded
 * Tailwind zinc; `listLoadingStates.test.ts` keeps new ones from being written. `inline` for a
 * header or a row, where a block would break the line.
 */
export function Loading({ what, inline = false, className = "", style }: {
  /** What is being read, as the screen names it: "agents", "the receipt". */
  what?: string;
  inline?: boolean;
  className?: string;
  style?: React.CSSProperties;
}) {
  const Tag = inline ? "span" : "div";
  return (
    <Tag role="status" aria-live="polite" className={`aug-fs-sm ${className}`.trim()}
      style={{ color: "var(--t3)", display: inline ? "inline-flex" : "flex", alignItems: "center", gap: 8, ...style }}>
      <Spinner size="1" />
      {what ? `Loading ${what}…` : "Loading…"}
    </Tag>
  );
}

/**
 * A list or tile whose fetch REJECTED — the one state this file did not name, and the one
 * that was being rendered as the empty state everywhere (Arc AO-3, measured 2026-10-03: five
 * Agent Ops surfaces said "nothing here" on a failed fetch, teaching the reader the data did
 * not exist). Small on purpose — it sits where a list would — and it always offers Retry,
 * which here IS the resolving door: nothing else can be done about a read that failed.
 */
export function ReadFailed({ what, error, onRetry, className = "", style }: {
  /** The thing that could not be read, as the screen names it: "the run chart". */
  what: string;
  /** The error's own words, when there are any. */
  error?: string | null;
  onRetry: () => void;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`aug-fs-sm ${className}`.trim()} role="alert"
      style={{ color: "var(--t2)", display: "flex", alignItems: "center", gap: 8,
        flexWrap: "wrap", ...style }}>
      <span>Could not read {what}{error ? ` — ${error}` : ""}.</span>
      <Button variant="outline" size="xs" onClick={onRetry}>Retry</Button>
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
    <Callout tone="red" role="alert" className={`aug-state ${className}`} style={style}>
      <Head kind={kind} meta={meta} />
      <div className="aug-state-what">{what}</div>
      {means != null && <div className="aug-state-detail">{means}</div>}
      <Doors doors={doors} />
      {ticket && (
        <div className="aug-state-ticket">ref <span className="aug-state-ticket-id">{ticket}</span></div>
      )}
    </Callout>
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
      <Callout tone="amber" className="aug-state">
        <Head kind={kind} meta={meta} />
        <div className="aug-state-claim">{claim}</div>
        {detail != null && <div className="aug-state-detail">{detail}</div>}
        <Doors doors={doors} />
      </Callout>
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
    <Callout tone="red" className={`aug-state ${className}`} style={style}>
      <Head kind={kind} meta={meta} />
      <div className="aug-state-claim">{claim}</div>
      {detail != null && <div className="aug-state-detail">{detail}</div>}
      <Doors doors={safe} />
    </Callout>
  );
}
