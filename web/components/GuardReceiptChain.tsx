"use client";
/**
 * B2 — A4's guard receipts rendered as Chain-of-Thought steps.
 *
 * Each receipt is one intervention a guard made on this turn: a de-fanned join,
 * a preflight repair, a re-grounded headline, a chart override, a caveat. The
 * backend already did the right thing silently; this surface is what turns
 * "restriction" into visible direction — the user watches the platform steer.
 *
 * Renders nothing for a turn with no receipts (most turns): no chrome, no cost.
 */
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import type { GuardReceipt } from "@/lib/chatTurn";

/** Human labels per guard id — the backend names the mechanism; the surface
 *  names what the reader gains. Unknown guards fall back to their raw id, so a
 *  new backend guard is visible before this map learns its nice name. */
const GUARD_LABEL: Record<string, string> = {
  fanout_defan: "Join over-count prevented",
  preflight_repair: "SQL repaired before execution",
  sql_lint: "Query quality issues fixed",
  headline_grounding: "Headline re-grounded in the returned rows",
  narration_inversion: "Universal claim qualified",
  measure_grain: "Wrong-grain total flagged",
  id_arithmetic: "Untrustworthy magnitude flagged",
  e1_trust_checks: "Trust checks added a caution",
  concentration_pareto: "Chart switched to Pareto for a concentration question",
  fanout_replan: "Queries re-planned around a join fan-out",
};

/** Compact verb for the action — reads as the step's sub-line with the detail. */
const ACTION_VERB: Record<string, string> = {
  rewrote_sql: "rewrote the SQL",
  repaired_sql: "repaired the SQL",
  rewrote_headline: "rewrote the headline",
  caveated_headline: "added a caution to the headline",
  overrode_chart: "overrode the chart choice",
  replanned_queries: "sent the plan back for correction",
  hinted: "returned a repair hint to the model",
  caveated: "carried a caveat instead of asserting",
};

function truncate(s: string, n = 90): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function GuardReceiptChain({
  receipts,
  streaming = false,
}: {
  receipts: GuardReceipt[];
  streaming?: boolean;
}) {
  if (!receipts.length) return null;
  return (
    <ChainOfThought defaultOpen={false} className="my-1">
      <ChainOfThoughtHeader streaming={streaming}>
        {receipts.length === 1
          ? "1 guard intervened"
          : `${receipts.length} guards intervened`}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {receipts.map((r, i) => (
          <ChainOfThoughtStep
            key={`${r.guard}-${i}`}
            label={GUARD_LABEL[r.guard] ?? r.guard}
            description={
              r.detail
                ? `${ACTION_VERB[r.action] ?? r.action}: ${r.detail}`
                : ACTION_VERB[r.action] ?? r.action
            }
            status="complete"
          >
            {(r.before || r.after) && (
              <ChainOfThoughtSearchResults>
                {r.before && (
                  <ChainOfThoughtSearchResult>
                    <span style={{ color: "var(--t4)" }}>before</span>
                    <span className="font-mono">{truncate(r.before)}</span>
                  </ChainOfThoughtSearchResult>
                )}
                {r.after && (
                  <ChainOfThoughtSearchResult>
                    <span style={{ color: "var(--t4)" }}>after</span>
                    <span className="font-mono">{truncate(r.after)}</span>
                  </ChainOfThoughtSearchResult>
                )}
              </ChainOfThoughtSearchResults>
            )}
          </ChainOfThoughtStep>
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}
