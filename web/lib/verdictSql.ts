/**
 * Which SQL a human verdict is ABOUT — the rule, in one place, because it has to be the
 * same rule on every surface that records one.
 *
 * MI-3 measured the cost of getting this wrong in the other direction: on 2026-09-03 the
 * verify store held five verdicts and not one carried SQL, because only the chat surface
 * ever sent it. So the exploration report and the trace explorer now send it too — but
 * sending SOMETHING is not the goal, sending the RIGHT thing is.
 *
 * The rule is deliberately conservative: attribute only when exactly ONE statement could
 * be meant. A chain whose headline synthesises several queries has no single statement its
 * finding rests on, and naming the last one would be a fabricated attribution. A wrong
 * training pair is worse than a missing one — §3.9's reward-integrity law is about the
 * corpus, not only the grader, and a model taught that this question maps to that
 * unrelated query has learned something false with full confidence.
 */

/** A step of an exploration chain, narrowed to what this rule needs. */
export interface SqlBearingStep {
  sql?: string | null;
  error?: string | null;
}

/**
 * The one statement an exploration's verdict is about, or "" when that is ambiguous.
 *
 * Errored steps are excluded before counting: their SQL is an example of what NOT to
 * produce, it is unlabelled as such here, and counting it could also mask a genuine
 * single-statement run behind a failed sibling.
 */
export function soleSqlOfSteps(steps: readonly SqlBearingStep[]): string {
  const usable = steps.filter(s => !s.error && (s.sql ?? "").trim() !== "");
  return usable.length === 1 ? (usable[0].sql ?? "").trim() : "";
}

/** A session event, narrowed to what this rule needs. */
export interface SqlBearingEvent {
  kind?: string | null;
  payload?: unknown;
}

/**
 * The one statement a trace executed, or "" when it ran several (or none).
 *
 * Reads `tool_call` payloads' `input`, which is where the executed statement lands.
 * DISTINCT statements are counted, not events: a retried or re-emitted identical query is
 * one query, and treating it as two would suppress a perfectly unambiguous attribution.
 */
export function soleSqlOfEvents(events: readonly SqlBearingEvent[]): string {
  const seen = new Set<string>();
  for (const e of events) {
    if (e.kind !== "tool_call") continue;
    const input = String((e.payload as { input?: unknown } | null)?.input ?? "").trim();
    if (input) seen.add(input);
  }
  return seen.size === 1 ? [...seen][0] : "";
}
