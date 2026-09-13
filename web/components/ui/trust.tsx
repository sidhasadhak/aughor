"use client";

/**
 * The trust system as primitives (INSTRUMENT.md §7) — Aughor's signature: readable at 11px,
 * never shouting, and instantly told apart from ordinary chrome. One drawing of each, so a
 * guard verdict or a receipt looks the same on every surface that shows one.
 *
 *   <GuardChip>     passed ✓ · warned ◈ · refused ✕ — a 1px border and no fill
 *   <ReceiptChain>  query → guard → guard → figure; a broken link stays in the chain, in red
 *   <Confidence>    the computed figure beside a 3px rule — ≥0.86 green, ≥0.5 amber, else red
 *   <Cite>          a checkable figure (dashed underline) and where it is checked (superscript)
 *   <CiteRef>       that superscript alone — a claim's pointer into the margin apparatus
 *   <WhyFigure>     a figure whose dashed underline opens "why this number"
 *   <WhyCard>       that popover's body: claim, matched cell, snapshot, rows read, cost, doors
 */
import React from "react";

import { Button } from "@/components/ui/button";

export type GuardVerdict = "passed" | "warned" | "refused";

const MARK: Record<GuardVerdict, string> = { passed: "✓", warned: "◈", refused: "✕" };

/** A guard verdict. Three outcomes only — anything else is not a guard. */
export function GuardChip({ verdict, children, title, className = "" }: {
  verdict: GuardVerdict;
  children: React.ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span className={`aug-guard aug-guard-${verdict} ${className}`} title={title}>
      <span aria-hidden>{MARK[verdict]}</span>
      {children}
      <span className="sr-only">{` — ${verdict}`}</span>
    </span>
  );
}

export type ReceiptLink =
  | { kind: "query"; label: string; title?: string; onOpen?: () => void }
  | { kind: "guard"; label: string; verdict: GuardVerdict; title?: string }
  | { kind: "figure"; label: string; title?: string };

function linkClass(l: ReceiptLink): string {
  if (l.kind === "query") return "aug-receipt-query";
  if (l.kind === "guard") {
    return l.verdict === "passed" ? "aug-receipt-passed" : l.verdict === "warned" ? "aug-receipt-warned" : "aug-receipt-broken";
  }
  return "";
}

/** The shape of Aughor's whole claim, drawn identically wherever it appears. */
export function ReceiptChain({ links, className = "" }: { links: ReceiptLink[]; className?: string }) {
  return (
    <span className={`aug-receipt-chain ${className}`} role="list" aria-label="Receipt chain">
      {links.map((l, i) => {
        const text = l.kind === "guard" ? `${l.label} ${MARK[l.verdict]}` : l.label;
        const cls = `aug-receipt-link ${linkClass(l)}`;
        return (
          <span key={`${l.kind}:${l.label}:${i}`} role="listitem" style={{ display: "inline-flex", alignItems: "center" }}>
            {l.kind === "query" && l.onOpen
              ? <Button variant="ghost" size="xs" className={`${cls} font-normal`} title={l.title} onClick={l.onOpen}>{text}</Button>
              : <span className={cls} title={l.title}>{text}</span>}
            {i < links.length - 1 && <span aria-hidden className="aug-receipt-arrow">→</span>}
          </span>
        );
      })}
    </span>
  );
}

/** The tier a confidence falls in, shared so a surface that needs only the colour agrees with
 *  the bar. Below 0.5 Aughor does not lead with the figure. */
export function confidenceTier(value: number): "high" | "mid" | "low" {
  return value >= 0.86 ? "high" : value >= 0.5 ? "mid" : "low";
}

export function Confidence({ value, note, title, className = "" }: {
  /** 0–1. A computed number, never a mood. */
  value: number;
  note?: React.ReactNode;
  title?: string;
  className?: string;
}) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <span className={`aug-confidence aug-confidence-${confidenceTier(v)} ${className}`} title={title}>
      <span className="aug-confidence-value">{v.toFixed(2)}</span>
      <span className="aug-confidence-bar" aria-hidden>
        <span className="aug-confidence-fill" style={{ display: "block", width: `${v * 100}%` }} />
      </span>
      {note != null && <span className="aug-confidence-note">{note}</span>}
    </span>
  );
}

function pressable(onOpen?: () => void) {
  if (!onOpen) return {};
  return {
    role: "button" as const,
    tabIndex: 0,
    onClick: onOpen,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); }
    },
  };
}

/** Where a claim is checked: the superscript that points into the margin apparatus. An amber one is
 *  a note that argues with the sentence. Pressable when `onOpen` is given; it hands back the
 *  marker's box, so the note opens beside it whether it was clicked or keyed. */
export function CiteRef({ refNo, dissent = false, title, onOpen }: {
  refNo: React.ReactNode;
  dissent?: boolean;
  title?: string;
  onOpen?: (anchor: DOMRect) => void;
}) {
  const cls = `aug-cite-ref${dissent ? " aug-cite-ref-dissent" : ""}${onOpen ? " aug-cite-ref-open" : ""}`;
  if (!onOpen) return <sup className={cls} title={title}>{refNo}</sup>;
  return (
    <sup className={cls} title={title} role="button" tabIndex={0}
      onClick={e => onOpen(e.currentTarget.getBoundingClientRect())}
      onKeyDown={e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(e.currentTarget.getBoundingClientRect()); }
      }}>
      {refNo}
    </sup>
  );
}

/** A figure inline in prose that can be checked, and the note or receipt that checks it. */
export function Cite({ children, refNo, tone = "neutral", dissent = false, title, onOpen }: {
  children: React.ReactNode;
  /** Where the figure is checked — the note or receipt number. */
  refNo?: React.ReactNode;
  /** An adverse or favourable figure wears its hue; a neutral one keeps the prose colour. */
  tone?: "adverse" | "favourable" | "neutral";
  /** The note argues with the sentence: the marker turns amber. */
  dissent?: boolean;
  title?: string;
  onOpen?: () => void;
}) {
  const color = tone === "adverse" ? "var(--red4)" : tone === "favourable" ? "var(--grn4)" : undefined;
  return (
    <>
      <span className="aug-cite" style={color ? { color } : undefined} title={title} {...pressable(onOpen)}>{children}</span>
      {refNo != null && <CiteRef refNo={refNo} dissent={dissent} />}
    </>
  );
}

/** A figure that answers "why this number". The dashed underline is the whole affordance — no
 *  icon, no button, nothing added to the layout. */
export function WhyFigure({ children, onOpen, title, className = "", style }: {
  children: React.ReactNode;
  onOpen?: () => void;
  title?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <span className={`aug-why ${className}`} title={title} style={style} {...pressable(onOpen)}>{children}</span>
  );
}

export interface WhyRow { key: string; value: React.ReactNode }
export interface WhyAction { label: string; onClick: () => void; title?: string }

/** The body of the "why this number" popover — rows in the spec's order (claim, matched cell,
 *  snapshot, rows read, cost), then the doors: open in SQL · drill · dispute. The surface is the
 *  .aug-popover; the caller positions it the way its other popovers are positioned. */
export function WhyCard({ rows, actions, className = "", style }: {
  rows: WhyRow[];
  actions?: WhyAction[];
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`aug-popover aug-why-card ${className}`} style={style}>
      {rows.map(r => (
        <div key={r.key} className="aug-why-row">
          <span className="aug-why-key">{r.key}</span>
          <span className="aug-why-value">{r.value}</span>
        </div>
      ))}
      {actions?.length ? (
        <div className="aug-why-actions">
          {actions.map(a => (
            <Button key={a.label} variant="link" size="xs" title={a.title} onClick={a.onClick}
              className="aug-why-action h-auto px-0 font-normal">
              {a.label}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
