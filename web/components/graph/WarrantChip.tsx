"use client";
import React from "react";
import type { CGStanding, CGWarrant, CGWarrantClass, GraphAudit, NodeTrust } from "@/lib/api";
import { StatusChip, ChipHue } from "@/components/brief/StatusChip";
import { formatCount } from "@/lib/format";

/**
 * Wave P2 — the warrant class, rendered the SAME way everywhere an edge, a node, or a
 * cited fact is shown.
 *
 * The point is comparability. A join measured at 98% overlap and one matched only by
 * column name used to render identically (a `✓`, or a source name a reader cannot rank).
 * One vocabulary, one hue scale, one tooltip: the reader learns it once and it holds on
 * the graph map, the entity page, and the answer trace.
 *
 * The hue scale is deliberately NOT green-to-red. A weak warrant is not an error — an
 * inferred join is a real, useful hypothesis — so the weakest class is muted, not
 * alarming. Red is reserved for things that are wrong.
 */

const HUE: Record<CGWarrantClass, ChipHue> = {
  measured: "positive",
  human: "accent",
  declared: "info",
  derived: "caution",
  inferred: "muted",
};

/** Fallback meanings so a chip is never a bare word the reader must decode. The server
 *  sends these too (`/graph/audit`); this keeps the chip self-sufficient. */
const MEANING: Record<CGWarrantClass, string> = {
  measured: "A number read off your data.",
  human: "A person asserted this.",
  declared: "Your schema, dbt, or a written definition states this.",
  derived: "Computed by Aughor from SQL it ran.",
  inferred: "A name or shape match — nothing probed it.",
};

export function WarrantChip({ warrant, showDetail = false }: {
  warrant?: CGWarrant | null;
  /** Append the specific evidence ("98% of key values overlap") after the class name. */
  showDetail?: boolean;
}) {
  if (!warrant) return null;
  const meaning = MEANING[warrant.warrant] || "";
  return (
    <StatusChip
      hue={HUE[warrant.warrant] || "muted"}
      strength="soft"
      title={warrant.detail ? `${meaning} ${warrant.detail}` : meaning}
    >
      {warrant.label || warrant.warrant}
      {showDetail && warrant.detail ? ` · ${warrant.detail}` : ""}
    </StatusChip>
  );
}

/**
 * The honesty scorecard — how every link in the graph is known, as one bar and a line per
 * class, for the side panel beside the map. (The freshness axes moved to the chip above the
 * picture, which says "Rebuild owed" with its reason on hover — said once, 2026-10-13.)
 *
 * All five classes are always shown, including the empty ones. A scorecard that hid its
 * weak classes would read as "nothing weak here", which is the failure mode this wave
 * exists to refuse.
 */
export function WarrantMix({ audit }: { audit: GraphAudit }) {
  const total = audit.totals.edges;
  const classes = audit.order;
  return (
    <div data-testid="warrant-mix">
      <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg-3)", marginBottom: 8 }}>
        {classes.map((c) => {
          const n = audit.edges[c] || 0;
          if (!n || !total) return null;
          return (
            <div key={c} title={`${formatCount(n)} ${audit.labels[c].toLowerCase()} · ${audit.meanings[c]}`}
              style={{ width: `${(n / total) * 100}%`, background: BAR[c] }} />
          );
        })}
      </div>
      <div className="aug-fs-sm" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 14px" }}>
        {classes.map((c) => (
          <span key={c} title={audit.meanings[c]} style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0,
            color: audit.edges[c] ? "var(--t2)" : "var(--t3)" }}>
            <span aria-hidden style={{ width: 7, height: 7, borderRadius: "var(--r-pill)", background: BAR[c], flex: "none" }} />
            {audit.labels[c]}
            <span style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>{formatCount(audit.edges[c] || 0)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Wave P3 — a node's standing: what has been CHECKED about it, as opposed to how it is
 * known (the warrant class above).
 *
 * The two are deliberately different vocabularies shown side by side. A join can be
 * `measured` — a real probe of your data — and still `unchecked`, because no person has
 * confirmed that the answers built on it were right. Collapsing them into one score
 * would hide exactly the gap a reviewer is looking for.
 *
 * `corroborated` is styled as information, not success: several analyses relying on a
 * node is a fact about usage, not a verdict on correctness, and a green chip there would
 * launder the weaker claim into the stronger one.
 */
const STANDING_HUE: Record<CGStanding, ChipHue> = {
  confirmed: "positive",
  contested: "caution",
  disputed: "negative",
  corroborated: "info",
  unchecked: "muted",
};

const STANDING_LABEL: Record<CGStanding, string> = {
  confirmed: "Confirmed",
  contested: "Contested",
  disputed: "Disputed",
  corroborated: "Corroborated",
  unchecked: "Unchecked",
};

export function StandingChip({ trust }: { trust?: NodeTrust | null }) {
  if (!trust) return null;
  return (
    <StatusChip hue={STANDING_HUE[trust.standing] || "muted"} strength="soft"
                title={`${trust.meaning} ${trust.detail}`}>
      {STANDING_LABEL[trust.standing] || trust.standing}
    </StatusChip>
  );
}

// The bar fills mirror the chip hues (StatusChip owns the pill classes; a raw bar needs
// the colour directly).
const BAR: Record<CGWarrantClass, string> = {
  measured: "var(--grn1)",
  human: "var(--vio1)",
  declared: "var(--blue1)",
  derived: "var(--amb1)",
  inferred: "var(--bg-4)",
};
