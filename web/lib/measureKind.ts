/**
 * Measure additivity — can a column be summed into a meaningful total?
 *
 * Share-of-total / concentration / Pareto language is ONLY valid for an ADDITIVE measure
 * (revenue, counts, spend). It is meaningless for a NON-ADDITIVE one — an average, rate,
 * ratio or index — because summing per-group averages produces a fake "total" and each
 * group's share of it is noise. The bug this guards: "AOV is concentrated — credit_card
 * alone accounts for 20% of 346.89" for AVG(order_value) (five ~€69 averages summed to
 * 346.89). The truth is AOV is flat across payment types.
 *
 * Single source of the additivity judgement (mirrors aughor/tools/postproc.py).
 */

// Matched against a name normalised so snake_case/camel separators become spaces, so a word
// boundary \b works on "total_spend" → "total spend". Non-additive wins over additive.
const NON_ADDITIVE_NAME =
  /\b(avg|average|mean|median|rate|ratio|pct|percent|proportion|margin|share|per|aov|arpu|arppu|asp|roas|cac|cpa|cpc|cpm|ltv|index|score)\b/i;
const ADDITIVE_NAME =
  /\b(revenue|sales|amount|spend|cost|total|sum|gmv|qty|quantity|orders?|units?|profit|volume|count|customers|users|sessions|clicks|impressions|visits|transactions)\b/i;
// A SELECT whose measure is computed by a non-additive aggregate (AVG/MEDIAN/…) — authoritative
// over the name: "aov" from ROUND(AVG(order_value),2) is non-additive even when the alias hides it.
const NON_ADDITIVE_SQL =
  /\b(avg|mean|median|stddev|std_dev|variance|var_samp|var_pop|corr|percentile_cont|percentile_disc)\s*\(/i;

const norm = (s: string) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ");

/**
 * True when a measure can be summed across groups into a meaningful total (so share-of-total
 * / concentration is valid). The SQL (when given) is authoritative for the non-additive case;
 * otherwise the column name decides, defaulting to non-additive for unknown names (never claim
 * a share-of-total we cannot justify).
 */
export function isAdditiveMeasure(colName: string, sql?: string | null): boolean {
  if (sql && NON_ADDITIVE_SQL.test(sql)) return false;   // AVG/MEDIAN/… → non-additive
  const name = norm(colName);
  if (NON_ADDITIVE_NAME.test(name)) return false;        // name reads as an average/rate/ratio
  if (ADDITIVE_NAME.test(name)) return true;             // clearly a sum/count magnitude
  return false;                                          // unknown → don't claim a share-of-total
}
