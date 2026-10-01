/**
 * columnRoles.ts — the SINGLE source of truth for chart column-role classification.
 *
 * Every chart surface classifies columns as date / share / change-metric / ordinal /
 * instrumentation and infers the x / measure / group roles. That logic used to be
 * duplicated three ways (here, `chartTypeInference.ts`, and inline in `Chart.tsx`),
 * which is exactly the drift the platform keeps re-fixing. It now lives here once:
 * both the type-inference (`chartTypeInference.inferChartType`) and the renderer
 * (`Chart.tsx`) import these regexes + `classifyColumns` so they can never disagree.
 */

/** Timestamp-ish column NAMES (ends with _date/_at/_time/created_at/…/timestamp). */
export const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;

/** Date column NAME — the suffix form OR a bare temporal name (month/week/period/…). The
 *  superset used by the shared classifier; a value-prefix match (`DATE_VALUE_RE`) also counts.
 *
 *  The suffixes are anchored to the END of the name. Unanchored, `_time` inside
 *  `total_first_time_customers` made a count of customers a date, and the theLook repeat-rate
 *  answer of 2026-10-01 drew its traffic-source chart with customer counts read as years
 *  ("Jan 1000 … Jan 9000") and its country chart as a heatmap with counts for categories. */
export const DATE_NAME = /(_date|_at|_time|created_at|updated_at|timestamp)$|^(date|month|week|period|quarter|day|year)$/i;

/** A bare calendar-grain NAME — the one way a column of plain numbers is a date (`year` holding
 *  2025, `month` holding 7). */
const GRAIN_NAME = /^(date|month|week|period|quarter|day|year)$/i;

/** Share / ratio column names → render as percentages. */
export const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;

// Change / delta / period-over-period metric column names.
// When ANY numeric column matches this pattern the question is a COMPARISON question
// (MoM, YoY, delta, growth rate) — heatmap and stacked-bar are the wrong charts.
// Also catches lag/prev/prior columns — their presence signals a POP query even when
// no explicit delta column was computed.
export const CHANGE_METRIC_COL = /(change|delta|growth|mom|yoy|wow|qoq|pct_change|percent_change|_chg$|_diff$|vs_prev|^prev_|_prev$|^prior_|_prior$|^lag_|_lag$)/i;

/** Ordinal / identifier columns — never abbreviate or treat as a measure. */
export const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

/** A numeric-VALUED column whose NAME is a fiscal/calendar grain that `DATE_NAME`'s
 *  anchored words miss — `fiscal_year`, `order_month`, `fy`, `qtr`. These are the
 *  x-axis (a time/ordinal dimension), never a measure: without this a yearly series
 *  like `[fiscal_year, net_sales]` has NO dimension left and the chart renders blank
 *  (fiscal_year fell through to a measure because DATE_NAME only matches `^year$`). */
export const TEMPORAL_GRAIN_COL = /^[a-z]+_(fy|year|quarter|qtr|month|week|half)$|^(fy|qtr)$/i;

/** Pure identifier columns — excluded from measure selection. */
export const SKIP_ID = /(_id$|^id$)/i;

/** Identifier detection covering BOTH snake_case (_id, case-insensitive) and camelCase
 *  (franchiseID, supplierId, eventGUID — case-SENSITIVE suffix after a lowercase letter,
 *  so plain words like "valid"/"grid" never match). SKIP_ID alone missed camelCase, which
 *  let `franchiseID` be charted as a measure (bars of summed IDs). Mirrors the backend
 *  profiler's _KEY_PATTERN + _KEY_PATTERN_CAMEL. */
const _CAMEL_ID = /[a-z](ID|Id|Key|Code|Num|Number|Identifier|UUID|Uuid|GUID|Guid|PK|Pk)$/;
const _SNAKE_ID = /(_id|_key|_code|_pk|_uuid|_guid|_sk|_hash)$|^id$/i;
export function isIdLike(name: string): boolean {
  return _SNAKE_ID.test(name) || _CAMEL_ID.test(name);
}

/** Audit-only instrumentation: the numerator/denominator a ratio is built from, or a bare row-count
 *  `n`. These exist so a ratio is checkable, never as a measure to plot — charting them buries the
 *  real metric (an AOV finding rendered as a giant SUM bar). Excluded from chart measure selection. */
export const INSTRUMENTATION_COL = /(^|_)(numerator|denominator)(_total)?$|^n$|^event_count$/i;

/** A measure whose name PREFERS to be the plotted one (a share/rate over a raw magnitude). */
export const PREFER_COL = /(pct|percent|share|rate|ratio|proportion)/i;

/** An ADDITIVE magnitude (summable) — the only kind you compose in a pie/treemap. */
export const ADDITIVE_COL = /(revenue|sales|amount|count|spend|cost|total|value|gmv|qty|quantity|orders|units|profit|volume)/i;

// Columns whose values are already human-formatted time labels (Month - Year, Q1 2024, etc.)
// → preserve SQL ordering, don't parse as dates, don't re-sort.
export const TIME_LABEL_COL = /(month|quarter|week|half|period)/i;

/** ISO date VALUE prefix ("2024-01" / "2024-01-01…"). */
export const DATE_VALUE_RE = /^\d{4}-\d{2}(-\d{2})?/;

/** Geographic column-name hints. A region/area NAME drives a choropleth (its values must
 *  match the map geojson's feature names); a lat + lon pair drives a point map. */
export const GEO_NAME_COL = /(country|nation|^state$|_state$|province|region|county|^city$|_city$|^iso|geo)/i;
export const LAT_COL = /(^|_)(lat|latitude)$/i;
export const LON_COL = /(^|_)(lon|lng|long|longitude)$/i;

export function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

/** Scan the full row set for the first non-null value of column colIdx.
 *  Falls back to rows[0]?.[colIdx] (which may be null) if all rows are null.
 *  Prevents NULL-heavy leading rows (e.g. first month of MoM lag queries) from
 *  mis-classifying numeric columns as categorical. A 20-row cap breaks LAG/LEAD
 *  queries where the first N rows (one per category for the first period) are all
 *  NULL — so we scan everything. */
export function firstNonNull(rows: unknown[][], colIdx: number): unknown {
  for (let i = 0; i < rows.length; i++) {
    const v = (rows[i] as unknown[])[colIdx];
    if (v !== null && v !== undefined && v !== "") return v;
  }
  return rows[0]?.[colIdx as number];
}

/** Count the distinct values a column takes across all rows. */
export function countUnique(rows: unknown[][], colIdx: number): number {
  return new Set(rows.map((r) => String((r as unknown[])[colIdx]))).size;
}

/** Is a column entirely null/empty across all rows? (carries no information → never plot it). */
export function isDeadColumn(rows: unknown[][], colIdx: number): boolean {
  return rows.every((r) => {
    const v = (r as unknown[])[colIdx];
    return v === null || v === undefined || v === "" || v === "NULL";
  });
}

/** THE classifier — split columns into date / numeric / category index buckets. One implementation,
 *  used by both `inferChartType` (type selection) and `Chart.tsx` (rendering), so the two can't drift.
 *  A date is a date-NAME or a date-VALUE prefix; a numeric is a non-date, non-id numeric value; every
 *  other non-dead column is a category. */
// ── ungraphable grid shapes (chart-grammar gates; mirror aughor/export/charts.py) ──
// A summary-statistics PROFILE grid (min/max/mean/std/p1…p99 per column) and an
// ID-labelled record grid with 3+ heterogeneous measures are TABLES, never charts —
// stacked/grouped bars over them say nothing (the W5 A/B caught both live).
const STAT_COL_RE = /^(min|max|mean|avg|std|stddev|median|p\d{1,2})(_val(ue)?)?$/i;

/** True when the grid has no honest chart — the shapes the chart grammar sends to a
 *  TABLE. Shared by inference (auto path), the renderer, and the answer card (which
 *  flips its default view to table). Mirrors aughor/export/charts.py; keep in sync.
 *    · stats profile (≥3 min/max/mean/std/p-cols)
 *    · wide profile (≥4 measures — a chart can't say four things about one row)
 *    · entity profile (≥3 measures whose only real label is an ID)
 *    · no-label grid (≥3 measures and NO distinguishing label column at all)
 *    · degenerate x (>1 rows but every category column holds ONE value — a chart
 *      with a single x position is one lying bar, e.g. "loyalty_members at 100%") */
export function isUngraphableGrid(columns: string[], rows: unknown[][]): boolean {
  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);
  const statCols = numericIdxs.filter((i) => STAT_COL_RE.test((columns[i] || "").trim()));
  if (statCols.length >= 3) return true;
  if (numericIdxs.length >= 4 && dateIdxs.length === 0) return true;
  if (dateIdxs.length === 0 && catIdxs.length > 0) {
    // A "real" label column distinguishes rows (a near-constant flag column doesn't).
    const labelish = catIdxs.filter((i) => new Set(rows.map((r) => String((r as unknown[])[i]))).size > 2);
    if (numericIdxs.length >= 3 && (labelish.length === 0 || labelish.every((i) => isIdLike(columns[i] || "")))) return true;
    if (rows.length > 1 && numericIdxs.length > 0
        && catIdxs.every((i) => new Set(rows.map((r) => String((r as unknown[])[i]))).size <= 1)) return true;
  }
  return false;
}

export function classifyColumns(
  columns: string[],
  rows: unknown[][],
): { dateIdxs: number[]; numericIdxs: number[]; catIdxs: number[] } {
  if (!rows.length) return { dateIdxs: [], numericIdxs: [], catIdxs: [] };
  const dateIdxs: number[] = [];
  const numericIdxs: number[] = [];
  const catIdxs: number[] = [];
  columns.forEach((col, i) => {
    if (isDeadColumn(rows, i)) return;
    const firstVal = firstNonNull(rows, i);
    // A column of plain numbers is a date only when it is NAMED as a calendar grain. A
    // timestamp suffix is not enough: `avg_delivery_time` holds hours and `has_shipped_at`
    // a count — measures, whatever their names end with. A timestamp arrives as an ISO
    // string, which the value test reads.
    const plainNumber = isNumeric(firstVal) && !(firstVal instanceof Date);
    const isDate = (DATE_NAME.test(col) && (!plainNumber || GRAIN_NAME.test(col)))
      || TEMPORAL_GRAIN_COL.test(col)
      || (typeof firstVal === "string" && DATE_VALUE_RE.test(firstVal));
    const numeric = !isDate && !isIdLike(col) && isNumeric(firstVal);
    if (isDate) dateIdxs.push(i);
    else if (numeric) numericIdxs.push(i);
    else catIdxs.push(i);
  });
  return { dateIdxs, numericIdxs, catIdxs };
}

/** How far a written value may sit from the number it was rounded from: "6.9" was written to one
 *  place, so anything within 0.05 of it is the same number. An unrounded value gets a hair. */
function writtenTolerance(written: unknown, value: number): number {
  const m = typeof written === "string" ? /^-?\d*\.(\d+)$/.exec(written.trim()) : null;
  return Math.max(m ? 0.5 * 10 ** -m[1].length : 0, Math.abs(value) * 1e-9);
}

/** Does column `r` equal `scale` × column `a` ÷ column `b` on every row that has all three? */
function isRatioOf(rows: unknown[][], r: number, a: number, b: number, scale: number): boolean {
  let checked = 0;
  for (const row of rows) {
    const rv = row[r];
    const x = Number(rv), av = Number(row[a]), bv = Number(row[b]);
    if (rv === null || rv === undefined || rv === "" || !Number.isFinite(x)
        || !Number.isFinite(av) || !Number.isFinite(bv) || bv === 0) continue;
    const want = scale * av / bv;
    if (Math.abs(x - want) > writtenTolerance(rv, want)) return false;
    checked += 1;
  }
  return checked >= 2;
}

export interface RateParts {
  rate: number;
  num: number;
  den: number;
  /** The rate is written ×100 (6.9 for 6.9%), not as a fraction. */
  scaled: boolean;
}

/**
 * Each rate whose numerator and denominator are in the same result: a column NAMED as a share or
 * rate (`repeat_rate`, `pct_returned`) that equals one other numeric column divided by another on
 * every row — as a fraction or ×100, to the precision it was written at.
 *
 * Checked on the values, never assumed from the names: the parts are in the result so the rate
 * can be checked, and the rate is what was asked. Measured 2026-10-01 on the theLook repeat-rate
 * answer: each cut came back as `[cut, total_first_time_customers, repeat_customers, repeat_rate]`
 * and every chart plotted a count — the line took the first measure, the bars the biggest.
 */
export function rateParts(columns: string[], rows: unknown[][], numericIdxs: number[]): RateParts[] {
  const out: RateParts[] = [];
  for (const r of numericIdxs.filter((i) => SHARE_COL.test(columns[i] || ""))) {
    found: for (const a of numericIdxs) {
      if (a === r) continue;
      for (const b of numericIdxs) {
        if (b === r || b === a) continue;
        for (const scale of [1, 100]) {
          if (isRatioOf(rows, r, a, b, scale)) {
            out.push({ rate: r, num: a, den: b, scaled: scale === 100 });
            break found;
          }
        }
      }
    }
  }
  return out;
}

/** A per-row average (`avg_hours_to_ship`) and a row count (`order_count`, `n_orders`). */
const AVERAGE_COL = /(^|_)(avg|average|mean)(_|$)/i;
const COUNT_COL = /(^|_)(count|cnt|num|n)(_|$)/i;

/**
 * The measures a chart of this result plots, in column order: its numeric columns less the ones
 * that are there to make another checkable —
 *   · named instrumentation (`numerator`, `denominator`, a bare `n`);
 *   · a rate's own numerator and denominator (`rateParts`);
 *   · the row count beside an average: the average is the measure, the count is how many rows it
 *     averaged. Plotting both put item counts and hours on one "Value" axis (theLook's fulfilment
 *     answer, 2026-10-01).
 * Every numeric column stands when that would leave none.
 */
export function plottedMeasures(columns: string[], rows: unknown[][], numericIdxs: number[]): number[] {
  const support = new Set<number>();
  for (const p of rateParts(columns, rows, numericIdxs)) {
    support.add(p.num);
    support.add(p.den);
  }
  if (numericIdxs.some((i) => AVERAGE_COL.test(columns[i] || ""))) {
    for (const i of numericIdxs) {
      if (COUNT_COL.test(columns[i] || "") && !AVERAGE_COL.test(columns[i] || "")) support.add(i);
    }
  }
  for (const i of numericIdxs) if (INSTRUMENTATION_COL.test(columns[i] || "")) support.add(i);
  const kept = numericIdxs.filter((i) => !support.has(i));
  return kept.length ? kept : numericIdxs;
}

/**
 * The rates in this result that read as PERCENTAGES with no unit declared: a rate whose numerator
 * and denominator are beside it, written ×100 or as a fraction that never exceeds 1 — a share of
 * a whole. Maps the column to whether it is already ×100. A ratio of parts above 1 (orders per
 * customer) is not a percentage and is left out.
 */
export function percentRates(columns: string[], rows: unknown[][], numericIdxs: number[]): Map<string, boolean> {
  const out = new Map<string, boolean>();
  for (const p of rateParts(columns, rows, numericIdxs)) {
    const fraction = rows.every((row) => {
      const v = Number(row[p.rate]);
      return row[p.rate] === null || row[p.rate] === undefined || row[p.rate] === ""
        || (Number.isFinite(v) && v >= 0 && v <= 1.0001);
    });
    if (p.scaled || fraction) out.set(columns[p.rate], p.scaled);
  }
  return out;
}

/**
 * Above this many categories a ranking stops reading horizontally.
 *
 * Orientation is a density decision, not just a type one. A handful of named categories
 * reads best lying down — the labels get room and the ranking is obvious at a glance. Past
 * roughly a dozen, horizontal bars either shrink below legibility or push the chart into a
 * scroll, and the honest form is the dense upright one, the way a daily series is drawn.
 * Both resolvers read this number so the two engines cannot disagree about it.
 */
export const HORIZONTAL_MAX_CATS = 12;

