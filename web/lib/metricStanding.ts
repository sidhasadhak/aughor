/**
 * Where a Key Metrics tile stands in the Semantic Layer.
 *
 * The Briefing's tiles are the explorer's north-star metrics, measured in the browser from the
 * business profile's own SQL. They rendered as confidently as an approved definition while the
 * Semantic Layer listed none of them (2026-10-07, `workspace` / `uber_ncr`): six tiles, zero
 * approved metrics. A tile now says what it is — proposed, a draft, or approved.
 */
import type { CatalogueMetric } from "@/lib/api";

export type MetricStanding = "approved" | "draft" | "proposed" | "absent";

/** `normalize_name` in `aughor/semantic/metric_catalogue.py`: the catalogue's identity for a
 *  metric, so "Average Booking Value (ABV)" and `average_booking_value_abv` are one metric. */
export function normalizeMetricName(text: string): string {
  return String(text ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

export function metricStanding(name: string, rows: readonly CatalogueMetric[]): MetricStanding {
  const key = normalizeMetricName(name);
  const row = rows.find(r => normalizeMetricName(r.name) === key || normalizeMetricName(r.label) === key);
  if (!row) return "absent";
  if (row.state === "defined") return row.status === "approved" ? "approved" : "draft";
  return "proposed";
}

/** The few words a tile carries when it is not an approved definition. */
export const STANDING_WORDS: Record<Exclude<MetricStanding, "approved">, string> = {
  proposed: "proposed — not approved",
  draft: "draft — not approved",
  absent: "not in the Semantic Layer",
};
