/**
 * One row of the Briefing's "numbers that moved" (Aughor Intelligence · 01 Briefing, §1).
 *
 * A move is read from the metric's TIME SERIES — its latest bucket against the one before —
 * never from the value query beside it. The two are different numbers: a profile's value
 * query is usually the whole-history figure (GMV €45.4M) while the series is per month, so
 * printing the overall value as "now" beside last month as "prior" would read as a collapse
 * that never happened. The overall value stays on the row, labelled as what it is.
 *
 * Nothing here invents a figure. A metric whose value query fails, returns no single scalar
 * or falls outside its declared range is DROPPED with its reason; a chart that is not a time
 * series (a breakdown by platform) leaves the row with a value and no move.
 */
import { betterIsHigher } from "@/lib/favorability";
import { fmtDate } from "@/lib/format";
import { deltaInfo, formatMetric } from "@/components/brief/metricFormat";
import { seriesTrend } from "@/components/brief/Sparkline";

export interface MoveDelta {
  /** In the metric's own terms: pts for a rate, × for a multiple, relative % otherwise. */
  text: string;
  sign: number;
  /** Good for the business? Direction-aware (a rising return rate is not); null when flat. */
  favorable: boolean | null;
}

export interface MoveRow {
  name: string;
  state: "pending" | "ready" | "dropped";
  /** Why a dropped metric has no figures. */
  reason?: string;
  valueSql: string;
  /** The profile's value query, formatted — the metric's overall figure. */
  overall?: string;
  overallRaw?: number;
  /** The latest bucket of the time series and the one before it, formatted. */
  now?: string;
  prior?: string;
  /** Those buckets as dates ("Aug 2025"). */
  nowLabel?: string;
  priorLabel?: string;
  delta?: MoveDelta;
  series?: number[];
  /** MoM / WoW / … */
  period?: string;
  /** The receipt of the query the row's figures came from: the series when there is one. */
  receiptId?: string | null;
  chart?: { columns: string[]; rows: unknown[][] } | null;
}

/** What a query returned, in the shape `runDirectQuery` answers with. */
export interface QueryOutcome {
  columns?: string[];
  rows?: unknown[][];
  error?: string | null;
  receipt_id?: string | null;
}

export function buildMoveRow(args: {
  name: string;
  unit: string;
  sym: string;
  valueSql: string;
  value: QueryOutcome | Error;
  chart?: QueryOutcome | Error | null;
}): MoveRow {
  const { name, unit, sym, valueSql, value, chart } = args;
  const dropped = (reason: string): MoveRow => ({ name, valueSql, state: "dropped", reason });

  if (value instanceof Error) return dropped(`the value query failed: ${value.message}`);
  if (value.error) return dropped(`the value query failed: ${value.error}`);
  if (!value.rows || value.rows.length !== 1) return dropped("the value query did not return exactly one row");
  const cell = value.rows[0].find(c => c != null && c !== "" && !isNaN(Number(c)));
  if (cell == null) return dropped("the value query returned no number");
  const raw = Number(cell);
  const overall = formatMetric(raw, unit, sym, name);
  if (!overall.ok) return dropped("the value is outside the metric's declared range");

  const row: MoveRow = {
    name, valueSql, state: "ready",
    overall: overall.display, overallRaw: raw, receiptId: value.receipt_id ?? null,
  };

  if (!chart || chart instanceof Error || chart.error || !chart.columns || !chart.rows || chart.rows.length < 2) {
    return row;
  }
  row.chart = { columns: chart.columns, rows: chart.rows };
  const trend = seriesTrend(chart.columns, chart.rows as (string | number | null)[][]);
  if (!trend || trend.values.length < 2) return row;

  const n = trend.values.length;
  const now = formatMetric(trend.values[n - 1], unit, sym, name);
  const prior = formatMetric(trend.values[n - 2], unit, sym, name);
  row.series = trend.values;
  row.period = trend.periodLabel;
  row.now = now.ok ? now.display : "—";
  row.prior = prior.ok ? prior.display : "—";
  row.nowLabel = fmtDate(trend.labels[n - 1], trend.gran);
  row.priorLabel = fmtDate(trend.labels[n - 2], trend.gran);
  const d = deltaInfo(trend.values, unit, name);
  if (d) {
    row.delta = {
      text: d.text, sign: d.sign,
      favorable: d.sign === 0 ? null : betterIsHigher(name) ? d.sign > 0 : d.sign < 0,
    };
  }
  row.receiptId = chart.receipt_id ?? row.receiptId;
  return row;
}
