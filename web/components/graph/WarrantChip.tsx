"use client";
import React from "react";
import type { CGStanding, CGWarrant, CGWarrantClass, GraphAudit, NodeTrust } from "@/lib/api";
import { StatusChip, ChipHue } from "@/components/brief/StatusChip";

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
 * The honesty scorecard — the warrant mix of the whole graph, plus the two freshness
 * axes.
 *
 * All five classes are always shown, including the empty ones. A scorecard that hid its
 * weak classes would read as "nothing weak here", which is the failure mode this wave
 * exists to refuse — the same reason the drift line is shown next to the staleness chip
 * rather than instead of it.
 */
export function GraphAuditBar({ audit }: { audit: GraphAudit | null }) {
  if (!audit || audit.totals.edges === 0) return null;
  const total = audit.totals.edges;
  const classes = audit.order;

  return (
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "12px 16px", marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>How we know this graph</span>
        {/* Joins, not all edges: `grounded_in` links (a finding to the table it came
            from) can never be measured and are ~95% of a real graph, so an all-edge
            share read 3% on a connection whose every join WAS measured. Named for its
            denominator so nobody has to guess it. */}
        <span style={{ fontSize: 11, color: "var(--t3)" }}>
          {audit.totals.joins > 0
            ? `${Math.round(audit.joins_measured_share * 100)}% of ${audit.totals.joins} joins are measured against your data`
            : `${total} connections, no joins yet`}
        </span>
      </div>

      <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", background: "var(--bg-3)", marginBottom: 10 }}>
        {classes.map((c) => {
          const n = audit.edges[c] || 0;
          if (!n) return null;
          return (
            <div
              key={c}
              title={`${n} ${audit.labels[c].toLowerCase()} · ${audit.meanings[c]}`}
              style={{ width: `${(n / total) * 100}%`, background: BAR[c] }}
            />
          );
        })}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {classes.map((c) => (
          <StatusChip key={c} hue={HUE[c]} strength="soft" title={audit.meanings[c]}>
            {audit.labels[c]} · {audit.edges[c] || 0}
          </StatusChip>
        ))}
      </div>

      {audit.drift?.drifted && (
        <div style={{ fontSize: 11, color: "var(--amb1)", marginTop: 10 }}>
          ⚠ {audit.drift.reason || "The graph is missing what the platform has since learned — rebuild it."}
        </div>
      )}
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
