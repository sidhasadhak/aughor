/**
 * Metric favorability — is a move good or bad for the business?
 *
 * "Up" is not always good: a rising CAC, churn, return rate or latency is bad. This is
 * the single source of that judgement, shared by the KPI scorecard and the brief's
 * inline metric deltas so their colours agree (and neither falls back to the naive
 * "minus = red" assumption).
 */

// Metrics where a RISE is UNfavorable (cost, CAC, churn, returns, latency, …).
const LOWER_BETTER = /\b(cac|cpa|cpc|cpm|acquisition cost|cost|spend|churn|attrition|defect|error|bounce|abandon|cancel|complaint|refund|return rate|returns|latency|wait|delay|days? to|time to|aging|overdue|backlog|downtime|fraud|risk|debt)\b/i;

/** For a metric named `name`, is a higher value better? (cost / CAC / churn → false). */
export const betterIsHigher = (name: string): boolean => !LOWER_BETTER.test(name);

/** Is a move favorable for the business? `sign` > 0 = up, < 0 = down, 0 = flat (→ null). */
export function deltaFavorable(name: string, sign: number): boolean | null {
  if (!sign) return null;
  return betterIsHigher(name) ? sign > 0 : sign < 0;
}
