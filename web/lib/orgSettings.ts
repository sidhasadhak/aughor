/**
 * Org-settings cache for the pure display formatters.
 *
 * The formatters (format.ts, AugTable, PivotTable) are pure and have no per-column
 * unit metadata, so the currency/date preferences live in a tiny module-level cache
 * they read synchronously — set once on app load and refreshed on workspace switch /
 * settings save (see page.tsx + OrgSettingsPanel). No prop-threading and no React
 * dependency, so low-level utils can import it freely. An empty currency_code /
 * date_format makes every formatter behave exactly as before (no regression).
 */
import type { OrgSettings } from "@/lib/api";

const SYMBOLS: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", CNY: "¥", INR: "₹",
  AUD: "A$", CAD: "C$", CHF: "CHF ", SGD: "S$", BRL: "R$", ZAR: "R",
};

/** ISO 4217 code → symbol; unknown codes fall back to "CODE " (e.g. "SEK "); "" for blank. */
export function currencySymbol(code: string | null | undefined): string {
  if (!code) return "";
  const c = code.toUpperCase();
  return SYMBOLS[c] ?? `${c} `;
}

let _cache: OrgSettings | null = null;

let _version = 0;
const _listeners = new Set<() => void>();

export function setOrgSettingsCache(s: OrgSettings | null): void {
  _cache = s;
  _version++;
  _listeners.forEach((l) => l());
}
export function orgSettingsSnapshot(): OrgSettings | null { return _cache; }

// Reactivity primitives (no React here — see lib/useOrgSettings for the hook) so memoized
// consumers (charts) can rebuild when the cache is populated/changed rather than capturing
// a stale empty cache on first render.
export function subscribeOrgSettings(cb: () => void): () => void {
  _listeners.add(cb);
  return () => { _listeners.delete(cb); };
}
export function orgSettingsVersion(): number { return _version; }

// ── The currency a figure is in: the one a PERSON confirmed for its dataset (2026-10-23) ──
// Until then the org's reporting currency labelled every money figure, though nothing converts:
// Olist's reais printed as "$1,258,681.34" (the Olist study, Gap 14). The org setting describes the
// organisation; a figure carries its own dataset's confirmed currency, or none — a plain amount.

/** One dataset's currency, as `GET /business-profile/currency` serves it. */
export interface DataCurrency {
  connection_id: string;
  schema_name: string | null;
  /** Set only when a person confirmed it. */
  code: string;
  status: "confirmed" | "inferred" | "unknown";
  /** The profile's proposal — shown beside a Confirm door, never in front of a number. */
  inferred: string;
  profile_confidence?: number | null;
  confirmed_by: string;
  confirmed_at: string;
}

const _currencies = new Map<string, DataCurrency>();
let _dataset = "";
const datasetKey = (connectionId: string, schema?: string | null) => `${connectionId}|${schema || ""}`;

/** Keep one dataset's currency (read, or just confirmed). */
export function setDataCurrency(c: DataCurrency): void {
  _currencies.set(datasetKey(c.connection_id, c.schema_name), c);
  _version++;
  _listeners.forEach((l) => l());
}

let _loader: ((connectionId: string, schema: string) => void) | null = null;

/** How a dataset's currency is read when it comes into view (the page registers the API call, so
 *  this module stays free of fetches). */
export function registerCurrencyLoader(load: ((connectionId: string, schema: string) => void) | null): void {
  _loader = load;
  const ds = currentDataset();
  if (load && ds && !_currencies.has(_dataset)) load(ds[0], ds[1]);
}

/** The dataset whose figures are on screen: the connection in view and its chosen schema. */
export function setCurrentDataset(connectionId: string, schema?: string | null): void {
  const key = connectionId ? datasetKey(connectionId, schema) : "";
  if (key === _dataset) return;
  _dataset = key;
  _version++;
  _listeners.forEach((l) => l());
  if (key && _loader && !_currencies.has(key)) _loader(connectionId, schema || "");
}

/** The dataset in view, as [connection, schema], or null. */
export function currentDataset(): [string, string] | null {
  if (!_dataset) return null;
  const [conn, schema] = _dataset.split("|");
  return [conn, schema];
}

/** The currency of the dataset in view, when it has been read. */
export function currentDataCurrency(): DataCurrency | null {
  return _currencies.get(_dataset) ?? null;
}

/** The symbol a money figure in view carries: its dataset's CONFIRMED currency, or "" (a plain
 *  amount) — never the org's preference, never the profile's guess, never a default "$". */
export function effectiveCurrencySymbol(): string {
  const c = currentDataCurrency();
  return c?.code ? currencySymbol(c.code) : "";
}

/** What a page says once where amounts are plain: "" when the currency is confirmed. */
export function unconfirmedCurrencyNote(): string {
  const c = currentDataCurrency();
  if (c?.code) return "";
  return c?.inferred
    ? `Amounts are plain: no one has confirmed this data's currency (the profile suggests ${c.inferred}).`
    : "Amounts are plain: no one has confirmed this data's currency.";
}

/**
 * Rewrite "$"-prefixed amounts in a DISPLAY string to the confirmed currency of the dataset in view —
 * "$69.81" → "€69.81" — or drop the "$" when none is confirmed, so "$1,258,681" over reais reads
 * "1,258,681" (2026-10-23). The deep-analysis model bakes a literal "$" into figures it writes.
 * A no-op only when the confirmed currency IS USD; only a "$" that prefixes a number is touched.
 */
export function localizeCurrency(text: string): string {
  const sym = effectiveCurrencySymbol();
  if (!text || sym === "$") return text;
  return text.replace(/\$(?=\s?[\d.,])/g, sym);
}

/** The user's date_format token (e.g. "DD/MM/YYYY"), or "" for the default smart labels. */
export function effectiveDateFormat(): string {
  return _cache?.date_format ?? "";
}

/** The selected named chart palette (e.g. "tableau10"), or "" for the theme default. */
export function effectiveChartPalette(): string {
  return _cache?.chart_palette ?? "";
}

/**
 * Whether this org lands on the conversation instead of the workbench (CA-5 / CI-6b).
 * False until the settings actually load, so the workbench — today's behaviour — is
 * what a slow or failed settings fetch degrades to.
 */
export function effectiveChatFirstHome(): boolean {
  return _cache?.chat_first_home === true;
}

/** The org IANA timezone (e.g. "Europe/London"), or "" to use the viewer's local zone. */
export function effectiveTimezone(): string {
  return _cache?.timezone ?? "";
}

// ── Monetary-column detection (name-only; the frontend has no per-column units) ──
// Conservative: a column must name a money concept AND not look like a count / rate /
// id / date, so a count, an id or a rate is never prefixed with a currency symbol.
// Boundaries are letter-only lookarounds (?<![a-z])…(?![a-z]) so snake_case separators
// count as boundaries: "unit_price"/"total_cost" match; "coffee" doesn't match "fee".
// ISO 4217 codes that commonly appear as a column suffix (e.g. refund_chf, amount_usd).
// A column ending in one of these IS monetary AND names its own currency — see currencyFromColumn.
const CURRENCY_SUFFIX_RE = /(?:usd|eur|gbp|chf|jpy|cny|inr|aud|cad|sek|nok|dkk|sgd|hkd|nzd|brl|zar|mxn|pln|aed)$/i;
const MONEY_RE = new RegExp(
  "(?<![a-z])(?:revenues?|sales|gmv|prices?|pricing|costs?|amounts?|spend|spent|profits?|payments?|fees?|charges?|balances?|budget|income|expenses?|turnover|takings|payout|aov|arpu|mrr|arr|ltv|cac|gross)(?![a-z])"
  + "|" + CURRENCY_SUFFIX_RE.source
  + "|net_(?:sales|revenue|profit)",
  "i",
);
const NOT_MONEY_RE = /(?<![a-z])(?:counts?|qty|quantity|numbers?|num|rate|ratio|pct|percent|share|proportion|rank|index|score|days?|months?|years?|weeks?|hours?|minutes?|age|id)(?![a-z])/i;

/** Does this column name read as monetary (so its figures should carry the currency symbol)? */
export function isMoneyColumn(colName: string): boolean {
  return MONEY_RE.test(colName) && !NOT_MONEY_RE.test(colName);
}

/**
 * The explicit ISO currency a column NAMES via its suffix (refund_chf → "CHF", amount_usd →
 * "USD"), or null when the name carries no currency. This is authoritative for THAT column:
 * a `_chf` amount is Swiss francs regardless of the workspace's reporting-currency setting.
 */
export function currencyFromColumn(colName: string): string | null {
  const m = (colName || "").toLowerCase().match(CURRENCY_SUFFIX_RE);
  return m ? m[0].toUpperCase() : null;
}

/**
 * Currency symbol to use for a column's figures: the column's OWN currency (from its suffix)
 * wins over the workspace reporting-currency default — so refund_chf renders "CHF 2.38M", not
 * "€2.38M", even in a EUR workspace. Falls back to the workspace symbol for currency-agnostic
 * money columns (e.g. "revenue").
 */
export function columnCurrencySymbol(colName: string): string {
  const explicit = currencyFromColumn(colName);
  return explicit ? currencySymbol(explicit) : effectiveCurrencySymbol();
}
