"use client";
import React from "react";
import type { CGWarrant, CGWarrantClass, GraphAudit } from "@/lib/api";
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
        <span style={{ fontSize: 11, color: "var(--t3)" }}>
          {Math.round(audit.edge_grounded_share * 100)}% of {total} connections are measured or human-confirmed
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

// The bar fills mirror the chip hues (StatusChip owns the pill classes; a raw bar needs
// the colour directly).
const BAR: Record<CGWarrantClass, string> = {
  measured: "var(--grn1)",
  human: "var(--vio1)",
  declared: "var(--blue1)",
  derived: "var(--amb1)",
  inferred: "var(--bg-4)",
};
