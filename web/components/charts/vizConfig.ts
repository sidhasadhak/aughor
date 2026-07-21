/**
 * vizConfig — the serializable shape of "how the user wants THIS chart displayed".
 *
 * Every display control in `ResultChartCard` used to be a bare `useState`, so a chart type,
 * a colour binding, a pivot layout or an axis title survived exactly as long as the component
 * stayed mounted. In the Briefing that is brutal: the findings ledger opens one row at a time,
 * so expanding a second row destroyed the first row's edits *without a reload*.
 *
 * This is the one type that crosses the wire. It is stored two ways, both opaque to the backend:
 *   - a PINNED CARD keeps it in `DashboardCard.render` (already persisted, already read on mount)
 *   - a card-less chart (ledger row, digest tile, KPI) keeps it in `viz_configs`, keyed by the
 *     insight it is about
 *
 * Every field is optional and absent-means-default, so an untouched chart persists NOTHING and
 * renders byte-identically to before. That is what makes the storage safe to add everywhere:
 * `isEmptyVizConfig` decides whether there is anything worth saving at all.
 */

import type { ChartType } from "@/components/charts/chartTypeInference";
import type { ExhibitRefLine } from "@/components/charts/exhibit";
import type { PostprocOp } from "@/lib/api";

export type VizAgg = "sum" | "avg" | "count" | "min" | "max";
export type VizView = "chart" | "table" | "pivot";

export interface VizConfig {
  /** chart ⇄ table ⇄ pivot. */
  view?:        VizView;
  /** "auto" defers to the backend's chart hint — the same as never touching Display. */
  type?:        ChartType | "auto";
  metric?:      string | null;
  dim?:         string | null;
  agg?:         VizAgg | null;
  showLabels?:  boolean;
  /** Databricks-style colour binding (PR #187): colour marks by a chosen column. */
  colorField?:  string;
  colorScale?:  "" | "continuous" | "categorical";
  colorName?:   string;
  numberFormat?: string;
  legend?:      string;
  xTitle?:      string;
  yTitle?:      string;
  tooltipOff?:  boolean;
  refLines?:    ExhibitRefLine[];
  /** Post-processing transform (PoP / share / rolling / cumulative). */
  transform?:   PostprocOp | "none";
}

/** True when the config carries no user intent — nothing to persist, nothing to restore.
 *  Treated as "reset to default" on save, which DELETES any stored row rather than pinning
 *  a copy of today's default forever. */
export function isEmptyVizConfig(c: VizConfig | null | undefined): boolean {
  if (!c) return true;
  return (
    (c.view === undefined) &&
    (c.type === undefined || c.type === "auto") &&
    !c.metric && !c.dim && !c.agg &&
    !c.showLabels &&
    !c.colorField && !c.colorScale && !c.colorName &&
    !c.numberFormat && !c.legend && !c.xTitle && !c.yTitle &&
    !c.tooltipOff &&
    !(c.refLines && c.refLines.length) &&
    (c.transform === undefined || c.transform === "none")
  );
}

/** Structural equality — used to skip a redundant PUT when a re-render re-emits the same
 *  config (React state setters fire on every interaction, not only on real changes). */
export function sameVizConfig(a: VizConfig | null | undefined, b: VizConfig | null | undefined): boolean {
  return JSON.stringify(a ?? {}) === JSON.stringify(b ?? {});
}
