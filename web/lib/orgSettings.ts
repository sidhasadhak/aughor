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

/** Currency symbol for the effective reporting currency, or "" when none is set. */
export function effectiveCurrencySymbol(): string {
  return _cache?.currency_code ? currencySymbol(_cache.currency_code) : "";
}

/** The user's date_format token (e.g. "DD/MM/YYYY"), or "" for the default smart labels. */
export function effectiveDateFormat(): string {
  return _cache?.date_format ?? "";
}

/** The selected named chart palette (e.g. "tableau10"), or "" for the theme default. */
export function effectiveChartPalette(): string {
  return _cache?.chart_palette ?? "";
}

// ── Monetary-column detection (name-only; the frontend has no per-column units) ──
// Conservative: a column must name a money concept AND not look like a count / rate /
// id / date, so a count, an id or a rate is never prefixed with a currency symbol.
// Boundaries are letter-only lookarounds (?<![a-z])…(?![a-z]) so snake_case separators
// count as boundaries: "unit_price"/"total_cost" match; "coffee" doesn't match "fee".
const MONEY_RE = /(?<![a-z])(?:revenues?|sales|gmv|prices?|pricing|costs?|amounts?|spend|spent|profits?|payments?|fees?|charges?|balances?|budget|income|expenses?|turnover|takings|payout|aov|arpu|mrr|arr|ltv|cac|gross)(?![a-z])|(?:usd|gbp|eur)$|net_(?:sales|revenue|profit)/i;
const NOT_MONEY_RE = /(?<![a-z])(?:counts?|qty|quantity|numbers?|num|rate|ratio|pct|percent|share|proportion|rank|index|score|days?|months?|years?|weeks?|hours?|minutes?|age|id)(?![a-z])/i;

/** Does this column name read as monetary (so its figures should carry the currency symbol)? */
export function isMoneyColumn(colName: string): boolean {
  return MONEY_RE.test(colName) && !NOT_MONEY_RE.test(colName);
}
