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
 *
 * Each step leads with the guard's chip (INSTRUMENT.md §7): the mechanism's short name and its
 * verdict — ✓ passed when the guard repaired and the figure survived, ◈ warned when it could only
 * flag or caveat — so a receipt reads as an instrument reading before it reads as a sentence.
 */
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { GuardChip, type GuardVerdict } from "@/components/ui/trust";
import type { GuardReceipt } from "@/lib/chatTurn";

/** Human labels per guard id — the backend names the mechanism; the surface
 *  names what the reader gains. Unknown guards fall back to their raw id, so a
 *  new backend guard is visible before this map learns its nice name.
 *  ONE vocabulary: `aughor/answer/receipts.py` carries the same maps for the export and the
 *  other Python doors, and `tests/unit/test_guard_receipt_vocabulary.py` holds the two equal. */
const GUARD_LABEL: Record<string, string> = {
  fanout_defan: "Join over-count prevented",
  preflight_repair: "SQL repaired before execution",
  sql_repair: "SQL repaired after its first run",
  sql_lint: "Query quality issues fixed",
  headline_grounding: "Headline re-grounded in the returned rows",
  narration_inversion: "Universal claim qualified",
  measure_grain: "Wrong-grain total flagged",
  id_arithmetic: "Untrustworthy magnitude flagged",
  e1_trust_checks: "Trust checks added a caution",
  concentration_pareto: "Chart switched to Pareto for a concentration question",
  fanout_replan: "Queries re-planned around a join fan-out",
  fanout_detected: "Join over-count flagged",
  extra_filter_replan: "Queries re-planned around a filter the metric does not declare",
  ambiguity_probe: "The question's readings were probed",
  count_star_entity_grain: "Row count checked against the entity asked for",
  repair_recheck: "A repair was re-checked before adoption",
  time_order: "Timestamps that run backwards flagged",
  day_window: "A period's last day read whole",
  declared_filter: "The metric's declared filter applied",
  object_policy: "Read as your access policy allows",
};

/** The mechanism's short name, for its chip. */
const GUARD_SHORT: Record<string, string> = {
  fanout_defan: "fan-out",
  preflight_repair: "preflight",
  sql_repair: "repair",
  sql_lint: "sql lint",
  headline_grounding: "grounding",
  narration_inversion: "narration",
  measure_grain: "grain",
  id_arithmetic: "id arithmetic",
  e1_trust_checks: "trust checks",
  concentration_pareto: "chart form",
  fanout_replan: "fan-out",
  fanout_detected: "fan-out",
  extra_filter_replan: "filter",
  ambiguity_probe: "ambiguity",
  count_star_entity_grain: "grain",
  repair_recheck: "recheck",
  time_order: "time order",
  day_window: "day window",
  declared_filter: "declared filter",
  object_policy: "access policy",
};

/** A repair means the check ran and the figure survived it; a flag or a caveat means the check
 *  found something the reader must know — and so does a read the reader's access policy narrowed
 *  or refused, whose receipt says the policy's own words. */
function verdictFor(action: string): GuardVerdict {
  return action === "flagged" || action === "caveated" || action === "caveated_headline"
    || action === "narrowed" || action === "refused" ? "warned" : "passed";
}

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
  flagged: "flagged it — no provable rewrite exists",
  kept_original: "kept the original query",
  narrowed: "narrowed it to the rows you may see",
  refused: "refused it — it reads what you may not see",
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
            label={
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <GuardChip verdict={verdictFor(r.action)}>{GUARD_SHORT[r.guard] ?? r.guard.replace(/_/g, " ")}</GuardChip>
                <span>{GUARD_LABEL[r.guard] ?? r.guard}</span>
              </span>
            }
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
                    <span style={{ color: "var(--t3)" }}>before</span>
                    <span className="font-mono">{truncate(r.before)}</span>
                  </ChainOfThoughtSearchResult>
                )}
                {r.after && (
                  <ChainOfThoughtSearchResult>
                    <span style={{ color: "var(--t3)" }}>after</span>
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
