"use client";

/**
 * BriefingDashboard — the Briefing tab's actionable findings layer (#3).
 *
 * The explorer's findings — the new, non-obvious signals — render as compact text
 * cards ranked by impact; clicking one "pulls the thread" into an inline ADA
 * investigation seeded with that finding's exact query.
 *
 * (The industry's key-metric trends used to render here as a standalone chart grid;
 * they now live in the KPI scorecard above, where a card expands into its own chart
 * on click — see IndustryKpiStrip.)
 */

import { useMemo, useState, type ReactNode } from "react";
import { insightKey, type ExplorationInsight } from "@/lib/api";
import { InlineInvestigationThread } from "@/components/brief/InlineInvestigationThread";

// One top finding to render (matches the panel's SynthesisSignal shape).
export interface DashboardFinding {
  insight: ExplorationInsight;
  domain: string;
}

// How many findings to surface as text cards (headline + signals is already ≤ 7).
const MAX_FINDINGS = 8;

/** A seed for the inline investigation thread (pulled from a finding card). */
interface ThreadSeed {
  key: string;
  question: string;
  seedSql: string | null;
  seedContext: string;
  /** The originating finding's insight id — seeds the rich dossier. */
  insightId?: string | null;
}

// ── Finding (prose) card ─────────────────────────────────────────────────────────

function FindingCard({
  finding, domain, onPull, active, actions,
}: {
  finding: string;
  domain: string;
  /** Open an inline investigation seeded with this finding (capability A). */
  onPull: () => void;
  /** Highlight when this card's thread is the one currently open. */
  active?: boolean;
  actions?: ReactNode;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      padding: "9px 11px", borderRadius: "var(--r3)",
      background: "var(--bg-2)",
      border: `1px solid ${active ? "var(--blue4)" : "var(--b1)"}`,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 600 }}>
        {domain}
      </div>
      <button
        onClick={onPull}
        title="Pull the thread — investigate this finding in place"
        style={{
          textAlign: "left", background: "transparent", border: "none", padding: 0,
          fontSize: 11.5, lineHeight: 1.5, color: active ? "var(--blue4)" : "var(--t1)", cursor: "pointer",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "var(--blue4)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = active ? "var(--blue4)" : "var(--t1)"; }}
      >
        {finding}
      </button>
      {actions && <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: "auto" }}>{actions}</div>}
    </div>
  );
}

// ── Dashboard ───────────────────────────────────────────────────────────────────

export function BriefingDashboard({
  findings,
  connectionId,
  schema,
  canvasId,
  onInvestigate,
  renderActions,
}: {
  findings: DashboardFinding[];
  connectionId: string;
  /** Shared schema scope from the workspace header — threaded into inline investigations. */
  schema?: string;
  /** Canvas scope (when the brief is canvas-bound) — threaded into inline investigations. */
  canvasId?: string;
  /** Escape hatch — open the seeded question in the full Ask surface. */
  onInvestigate: (q: string) => void;
  /** Reuse the panel's FindingActions so each finding stays actionable (monitor/share/evidence). */
  renderActions?: (insight: ExplorationInsight, domain: string) => ReactNode;
}) {
  // Capability A — one inline investigation thread, seeded from a clicked finding
  // ("pull the thread"). Rendered full-width below the grid.
  const [thread, setThread] = useState<ThreadSeed | null>(null);

  // ── Finding text cards: dedup, drop the impossible, rank by impact ──────────────
  // Same triage authority as the brief (stamped server-side by /domains): suppress only
  // 'implausible' findings (an impossible value — e.g. inventory turnover 96,295×); keep
  // everything else, including confounds, ranked by the impact score (which carries the
  // change/north-star/risk weighting). Falls back to novelty+confidence when unannotated.
  const findingCards = useMemo(() => {
    const seen = new Set<string>();
    const out: DashboardFinding[] = [];
    for (const f of findings) {
      const id = f.insight?.id;
      // Dedup by composite identity (source_schema::id) — bare ids collide across schemas in
      // the "All schemas" aggregate, so a plain id-set would silently drop a real finding.
      const key = f.insight ? insightKey(f.insight) : "";
      if (!id || seen.has(key)) continue;
      if (f.insight.plausibility === "implausible") continue;   // drop only the impossible
      seen.add(key);
      out.push(f);
    }
    const rank = (i: ExplorationInsight) =>
      i.impact ?? ((i.novelty ?? 0) / 5 + (i.confidence ?? 0));
    out.sort((a, b) => rank(b.insight) - rank(a.insight));
    return out.slice(0, MAX_FINDINGS);
  }, [findings]);

  if (!findingCards.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
      <div className="aug-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span>Dashboard</span>
        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b1)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>
          Live
        </span>
      </div>

      {/* New findings — the non-obvious signals, as compact text cards ranked by impact.
          Clicking a finding pulls the thread: an ADA investigation streams in place
          below the grid, seeded with that finding's exact query. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 11, alignItems: "start" }}>
        {findingCards.map(f => {
          const key = `finding:${insightKey(f.insight)}`;
          return (
            <FindingCard key={insightKey(f.insight)} finding={f.insight.finding} domain={f.domain}
              active={thread?.key === key}
              onPull={() => setThread(prev => prev?.key === key ? null : {
                key,
                question: `Why is this happening? ${f.insight.finding}`,
                seedSql: f.insight.sql || null,
                seedContext: `SEED FINDING (the briefing claim being investigated): ${f.insight.finding}`,
                insightId: f.insight.id,
              })}
              actions={renderActions?.(f.insight, f.domain)} />
          );
        })}
      </div>

      {/* Inline investigation thread — seeded from the clicked finding.
          Keyed by seed so picking a different one remounts a fresh stream. */}
      {thread && (
        <InlineInvestigationThread
          key={thread.key}
          question={thread.question}
          opts={{
            connectionId,
            schema: schema ?? null,
            canvasId: canvasId ?? null,
            seedSql: thread.seedSql,
            seedContext: thread.seedContext,
            insightId: thread.insightId ?? null,
          }}
          onClose={() => setThread(null)}
          onOpenInAsk={onInvestigate}
        />
      )}
    </div>
  );
}
