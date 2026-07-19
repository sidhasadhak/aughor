"use client";

/**
 * StatTile — the canonical KPI stat-tile spec.
 *
 * ONE tile shape for a metric-at-a-glance: a section-label caption, a big mono figure,
 * an optional period-delta badge whose COLOUR is favorability-aware (a rising CAC is red
 * even though it's "up"), an optional trend sparkline, and an optional one-word caption.
 * Optionally expandable (a ⤢ affordance + an open accent border) for a master-detail drill.
 *
 * It owns only the tile CHROME — the value is a slot (`value`), so a caller can pass a
 * plain string, a <GroundedNumber> receipt, or the KPI odometer without this component
 * knowing which. That keeps the tuned bits (NumberFlow overlay, favorability logic) with
 * their owners while every KPI tile in the product renders through one spec.
 *
 * Pure/presentational (no data fetching, no interaction state) so it renders in /chart-lab.
 */
import type { ReactNode } from "react";
import { Sparkline } from "@/components/brief/Sparkline";

export interface StatDelta {
  /** Preformatted delta in the metric's own units ("+3.1pts" / "-0.6%" / "+0.4×"). */
  text:      string;
  /** -1 | 0 | 1 — a flat (0) delta hides the badge. */
  sign:      number;
  /** Good move for the business? direction-aware; null when flat/unknown → neutral colour. */
  favorable: boolean | null;
}

export interface StatTileProps {
  label:      string;
  value:      ReactNode;
  /** Categorical accent for the sparkline + the open-state border (not the delta colour). */
  accent?:    string;
  delta?:     StatDelta | null;
  sparkline?: number[] | null;
  caption?:   string;
  /** Master-detail: show the ⤢ affordance + pointer; the caller renders the detail. */
  expandable?: boolean;
  open?:       boolean;
  onClick?:    () => void;
  title?:      string;
  /** Flex basis / floor so a KPI is never forced as wide as a chart card. */
  flexBasis?: number;
  minWidth?:  number;
}

export function StatTile({
  label, value, accent = "var(--b1)", delta, sparkline, caption,
  expandable = false, open = false, onClick, title, flexBasis = 160, minWidth = 150,
}: StatTileProps) {
  const fav = delta?.favorable;
  const deltaColor = fav == null ? "var(--t3)" : fav ? "var(--grn4)" : "var(--red4)";
  const deltaBg    = fav == null ? "var(--bg-3)" : fav ? "var(--grn1)" : "var(--red1)";
  const border = `1px solid ${open ? accent : "var(--b1)"}`;
  return (
    <div
      onClick={onClick}
      title={title}
      style={{
        position: "relative", flex: `1 1 ${flexBasis}px`, minWidth, padding: "11px 13px",
        borderRadius: "var(--r2)", background: open ? "var(--bg-3)" : "var(--bg-2)",
        // Explicit per-side borders (not the `border` shorthand) so React never warns about
        // mixing shorthand + longhand across rerenders.
        borderTop: border, borderRight: border, borderBottom: border, borderLeft: border,
        display: "flex", flexDirection: "column", gap: 7,
        cursor: expandable ? "pointer" : "default",
        transition: "background var(--dur-fast), border-color var(--dur-fast)",
      }}
    >
      <div className="aug-label" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingRight: 14 }} title={label}>
        {label}
      </div>
      {expandable && (
        <span aria-hidden style={{ position: "absolute", top: 9, right: 10, fontSize: 11, lineHeight: 1, color: open ? accent : "var(--t4)" }}>
          {open ? "×" : "⤢"}
        </span>
      )}
      <div className="aug-fs-display" style={{ color: "var(--t1)", fontWeight: 700, fontFamily: "var(--font-mono)", lineHeight: 1 }}>
        {value}
      </div>
      {delta && delta.sign !== 0 && (
        <span style={{
          alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: 3,
          fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)",
          color: deltaColor, background: deltaBg, padding: "1px 6px", borderRadius: "var(--r1)",
        }}>
          {delta.sign > 0 ? "↑" : "↓"} {delta.text}
        </span>
      )}
      {sparkline && sparkline.length >= 2 && (
        <Sparkline values={sparkline} color={accent} width={130} height={26} showDot={false} />
      )}
      {caption && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>{caption}</div>}
    </div>
  );
}
