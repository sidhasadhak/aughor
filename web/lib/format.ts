/**
 * format.ts — the SINGLE home for value formatting across the web app.
 *
 * Before this module, the same handful of operations were re-implemented in a
 * dozen components, each subtly different:
 *   - large-number abbreviation (1.2M / 1.2m / 1.23M / 12K / 12.3K)  ×8
 *   - ratio → percent                                                ×5
 *   - "revenue_usd" → "Revenue USD" label cleanup                    ×3
 *   - date normalization + granularity detection                    ×2
 * That drift is exactly the class of bug the platform keeps re-fixing. Anything
 * that formats a number, percent, label, or date for display MUST come from here
 * so a change lands once and propagates everywhere.
 *
 * The column-aware *cell* formatter (share-column detection, ordinal passthrough)
 * still lives in ./formatCell and is re-exported below — it is the table-cell
 * formatter that `<DataTable>` will own in Phase 3. Use the leaf helpers here
 * (compactNumber / formatPercent / cleanLabel / date suite) for everything else.
 */

export {
  SHARE_COL_PATTERN,
  ORDINAL_COL_PATTERN,
  isShareColumn,
  formatCell,
  buildColumnFormatter,
} from "./formatCell";

import { effectiveDateFormat, effectiveTimezone } from "./orgSettings";

// ── Column types ─────────────────────────────────────────────────────────────

/** SQL numeric column types — mirrors the backend `_NUMERIC_TYPES` (profiler.py),
 *  including DuckDB's unsigned `U*INT` variants. Distributions/percentiles only
 *  make sense for these, so the UI gates the per-column distribution on it. */
const NUMERIC_TYPE_RE =
  /\b(U?(?:TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|INT)|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|NUMBER)\b/i;

/** True when a column's declared SQL type is numeric (int/float/decimal/…). */
export function isNumericType(type: string | null | undefined): boolean {
  return !!type && NUMERIC_TYPE_RE.test(type);
}

// ── Numbers ──────────────────────────────────────────────────────────────────

/**
 * Compact abbreviation for badges, stat chips, and axis ticks:
 *   1_234_567 → "1.2M",  45_300 → "45.3K",  2_400_000_000 → "2.4B".
 * Below 1000: integers render as-is, decimals to `digits`. Negatives keep sign.
 * This replaces the eight hand-rolled K/M/B formatters — pass `digits` to match
 * a caller that needs more precision (e.g. 2 for a data cell).
 */
export function compactNumber(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(digits)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(digits)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(digits)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

/** Thousands-separated number (e.g. row counts in a table): 1234567 → "1,234,567". */
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return n.toLocaleString("en-US");
}

/**
 * Canonical DATA-TABLE cell value (scale unknown, full precision wanted):
 *   ≥1B → "1.23B", ≥1M → "4.56M", ≥1K → "12,345" (thousands separators),
 *   integers as-is, small decimals trimmed ("3.1400" → "3.14").
 * Use for numeric cells in a results grid. For a compact headline/badge use
 * `compactNumber`; for a known ratio use `pct`/`formatPercent`.
 */
export function formatMetricValue(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(4).replace(/\.?0+$/, "");
}

// ── Percentages ──────────────────────────────────────────────────────────────

/**
 * Display a value that *might* be a stored ratio OR an already-computed percent.
 * |n| ≤ 1 is treated as a ratio and scaled ×100; anything larger is assumed to be
 * already a percentage (e.g. 11.8 → "11.8%", -60.89 → "-60.89%"). Use for data
 * cells where the scale is ambiguous. For a value you KNOW is a ratio (confidence,
 * conversion rate, null rate) use `pct` instead — it never second-guesses.
 */
export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const p = Math.abs(n) <= 1 ? n * 100 : n;
  return `${p.toFixed(digits)}%`;
}

/** A known ratio in [0,1+] → percent, always ×100: 0.118 → "12%" (digits 0). */
export function pct(ratio: number | null | undefined, digits = 0): string {
  if (ratio === null || ratio === undefined || isNaN(ratio)) return "—";
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** Signed variance percent for scorecards: +12.5% / -3.0%. Input is a ratio. */
export function formatVariance(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined || isNaN(ratio)) return "";
  const p = (ratio * 100).toFixed(digits);
  return ratio >= 0 ? `+${p}%` : `${p}%`;
}

// ── Labels ───────────────────────────────────────────────────────────────────

// Acronyms that should stay fully upper-cased rather than title-cased.
const ABBREVS = /^(usd|id|uk|us|eu|vat|sku|url|api|crm|gmv|mrr|arr|ltv|cac|ctr|aov|roi|pnl|gp|kpi)$/i;

/**
 * Humanize a raw column / field name for a header, axis title, or legend:
 *   "revenue_usd"    → "Revenue USD"
 *   "payment_method" → "Payment Method"
 * Known acronyms are upper-cased; every other word is title-cased.
 */
export function cleanLabel(s: string): string {
  return (s ?? "")
    .replace(/_/g, " ")
    .replace(/\b\w+/g, (w) =>
      ABBREVS.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
    );
}

/**
 * Lower-case humanize for ontology relationship verbs:
 *   "HAS_MANY" → "has many",  "REFERENCES" → "references".
 * Ontology edges use lower-case verbs by convention — distinct from the
 * Title-Case `cleanLabel`. Centralised so the four edge-label sites agree.
 */
export function verbLabel(verb: string): string {
  return (verb ?? "").toLowerCase().replace(/_/g, " ");
}

// ── Dates & granularity ──────────────────────────────────────────────────────
// A date column produced by DATE_TRUNC('week'/'day'/'month'/…) is ALREADY
// aggregated. We match the label/axis granularity to the data rather than re-bin,
// inferring the grain from the column name first, then median spacing of values.

export type Gran = "minute" | "hour" | "day" | "week" | "month" | "quarter" | "year";

/**
 * Tidy a raw cell value for tabular display. A DATE_TRUNC'd dimension comes back as a
 * midnight timestamp ("2025-04-01 00:00:00"); the trailing 00:00:00 is noise in a table,
 * so collapse it to the date ("2025-04-01"). Everything else passes through unchanged.
 */
export function displayCellValue(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[ T]00:00:00(?:\.0+)?$/);
  const dateStr = m ? m[1] : s;
  // A user date_format applies to bare ISO dates in table cells; non-dates pass through.
  const pref = effectiveDateFormat();
  if (pref && /^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return applyUserDateFormat(dateStr, pref);
  return dateStr;
}

/**
 * "2024-01-01 00:00:00" / "2024-01" → a string `new Date()` can parse.
 * DuckDB returns a space-separated timestamp; DATE_TRUNC('month') yields "2018-01".
 * Returns the input unchanged when it doesn't look like a timestamp.
 */
export function normDateStr(v: string): string {
  let s = (v ?? "").replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, "$1T$2");
  if (/^\d{4}-\d{2}$/.test(s)) s += "-01";
  return s;
}

export function granFromName(col: string): Gran | null {
  const n = (col || "").toLowerCase();
  if (/\bminute\b|_minute|per_minute/.test(n)) return "minute";
  if (/\bhour\b|_hour|hourly/.test(n)) return "hour";
  if (/\bweek\b|wk\b|_week|iso_week|week_/.test(n)) return "week";
  if (/\bquarter\b|\bqtr\b|_q$|fiscal_q/.test(n)) return "quarter";
  if (/\bmonth\b|_month|yyyymm/.test(n)) return "month";
  if (/\byear\b|_year|yyyy$/.test(n)) return "year";
  if (/\bday\b|_day|\bdate\b|_date$|^date$/.test(n)) return "day";
  return null;
}

const _DAY_MS = 86_400_000;

export function detectGranularity(col: string, values: unknown[]): Gran {
  const named = granFromName(col);
  if (named) return named;

  // Sub-day grain from the time-of-day component, BEFORE the spacing heuristic —
  // DATE_TRUNC('minute') leaves a varying MM, DATE_TRUNC('hour') a varying HH with
  // MM=00, and day+ are all midnight. Sparse minute data (orders hours apart) would
  // otherwise be misread as "day" by the median-delta test and lose its time labels.
  let anyMinute = false, anyHour = false;
  for (const v of values) {
    const mt = String(v ?? "").match(/\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2}):\d{2}/);
    if (!mt) continue;
    if (mt[2] !== "00") { anyMinute = true; break; }  // non-zero minutes → minute grain
    if (mt[1] !== "00") anyHour = true;               // non-zero hour, zero minutes → hour grain
  }
  if (anyMinute) return "minute";
  if (anyHour) return "hour";

  const ts = Array.from(
    new Set(values.map((v) => String(v ?? "")).filter((s) => /^\d{4}-\d{2}(-\d{2})?/.test(s)))
  )
    .map((s) => new Date(normDateStr(s)).getTime())
    .filter((t) => !isNaN(t))
    .sort((a, b) => a - b);
  if (ts.length >= 2) {
    const deltas = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b);
    const med = deltas[Math.floor(deltas.length / 2)];
    if (med <= 1.5 * _DAY_MS) return "day";
    if (med <= 10 * _DAY_MS) return "week";
    if (med <= 45 * _DAY_MS) return "month";
    if (med <= 135 * _DAY_MS) return "quarter";
    return "year";
  }
  return "day";
}

const _MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Render a date per a user date_format token. Pulls Y-M-D straight from the string
 *  (no Date parse) so a "…T00:00:00" timestamp never drifts a day across the local
 *  timezone. Returns the input unchanged for an unknown token or a non-date. */
function applyUserDateFormat(dateStr: string, pref: string): string {
  const m = dateStr.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  if (!m) return dateStr;
  const [, yyyy, mm, dd = "01"] = m;
  const mmm = _MONTHS_SHORT[parseInt(mm, 10) - 1] ?? mm;
  switch (pref) {
    case "YYYY-MM-DD": return `${yyyy}-${mm}-${dd}`;
    case "DD/MM/YYYY": return `${dd}/${mm}/${yyyy}`;
    case "MM/DD/YYYY": return `${mm}/${dd}/${yyyy}`;
    case "DD MMM YYYY": return `${dd} ${mmm} ${yyyy}`;
    default: return dateStr;
  }
}

/**
 * Human label for a single date value at the detected grain. Always carries the
 * year for day/week so a table is unambiguous across years ("19 Sep 2017").
 * A user date_format (Settings ▸ Localization) overrides the day/week label; the
 * aggregated month/quarter/year labels stay smart ("Sep 2024", "Q1 2024").
 */
export function fmtDate(v: string, gran: Gran): string {
  if (!/^\d{4}-\d{2}(-\d{2})?/.test(v)) return v;
  const d = new Date(normDateStr(v));
  if (isNaN(d.getTime())) return v;
  // Org timezone applies ONLY to time-bearing grains (minute/hour) — shifting a date-only
  // bucket (day/month/…) across midnight would be wrong. Empty = the viewer's local zone.
  const _tz = effectiveTimezone();
  const _tzOpt = _tz ? { timeZone: _tz } : {};
  switch (gran) {
    case "minute":
      return d.toLocaleString("default", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", ..._tzOpt });
    case "hour":
      return d.toLocaleString("default", { day: "numeric", month: "short", hour: "numeric", ..._tzOpt });
    case "day":
    case "week": {
      const pref = effectiveDateFormat();
      if (pref) return applyUserDateFormat(v, pref);
      return d.toLocaleString("default", { day: "numeric", month: "short", year: "numeric" });
    }
    case "quarter":
      return `Q${Math.floor(d.getUTCMonth() / 3) + 1} ${d.getUTCFullYear()}`;
    case "year":
      return String(d.getUTCFullYear());
    case "month":
    default:
      return d.toLocaleString("default", { month: "short", year: "numeric" });
  }
}

/**
 * d3-time-format spec for a temporal (continuous) axis at the detected grain.
 * Shows the year on every tick only when the range spans multiple years.
 */
export function chartDateFormat(gran: Gran, multiYear: boolean): string {
  switch (gran) {
    case "minute":
    case "hour":
      return "%b %d %H:%M";
    case "day":
    case "week":
      return multiYear ? "%b %Y" : "%b %d";
    case "year":
      return "%Y";
    case "quarter":
    case "month":
    default:
      return "%b %Y";
  }
}

export const GRAN_WORD: Record<Gran, string> = {
  minute: "Per-minute",
  hour: "Hourly",
  day: "Daily",
  week: "Weekly",
  month: "Monthly",
  quarter: "Quarterly",
  year: "Yearly",
};
