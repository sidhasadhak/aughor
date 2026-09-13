/**
 * SE-8C — parameter WIDGET definitions: how a `:name` renders as a control.
 *
 * A parameter marker materialises a widget, configured by a gear icon.
 * This module is that model, kept pure so the resolution rules — the part that decides
 * what actually reaches the engine — are testable without a DOM.
 *
 * A def never changes what is SENT structurally: values still travel as bind values
 * (scalars, or a list the server expands to scalar binds). The def only decides the
 * control (`widget`), its choices (`options` / `optionsQueryId`), and how the typed
 * string is coerced (`number` → a real number, `date` tokens → an ISO date).
 */

export type ParamValue = string | string[];

export interface ParamDef {
  /** Shown instead of `:name` when set. */
  label?: string;
  widget: "text" | "number" | "date" | "dropdown" | "multiselect";
  /** Static choices for dropdown/multiselect; suggestions for text (a combobox). */
  options?: string[];
  /** A saved query whose FIRST column supplies the choices (capped at 1024).
   *  Loaded lazily by the bar, never here. */
  optionsQueryId?: string;
  /** Prefill for a tab that has no value yet. */
  default?: ParamValue;
}

export const DEFAULT_PARAM_DEF: ParamDef = { widget: "text" };

/** How many choices a query-sourced dropdown may offer before it stops being one. */
export const OPTIONS_QUERY_CAP = 1024;

// ── dynamic date values ───────────────────────────────────────────────────────
//
// The ⚡ menu. The TOKEN is what the tab stores, so the query stays dynamic —
// "today" run tomorrow means tomorrow. Resolution happens once, at bind time.

export const DYNAMIC_DATE_TOKENS = [
  "today",
  "yesterday",
  "start of this week",
  "start of last week",
  "start of this month",
  "start of last month",
  "start of this year",
] as const;

export type DynamicDateToken = (typeof DYNAMIC_DATE_TOKENS)[number];

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** The ISO date a token means right now, or null for a plain (non-token) value.
 *  Weeks start Monday — ISO's convention, and the one GROUP BY week queries use. */
export function resolveDynamicDate(value: string, now = new Date()): string | null {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  switch (value) {
    case "today": return iso(d);
    case "yesterday": d.setDate(d.getDate() - 1); return iso(d);
    case "start of this week": {
      const dow = (d.getDay() + 6) % 7;             // Mon=0 … Sun=6
      d.setDate(d.getDate() - dow); return iso(d);
    }
    case "start of last week": {
      const dow = (d.getDay() + 6) % 7;
      d.setDate(d.getDate() - dow - 7); return iso(d);
    }
    case "start of this month": d.setDate(1); return iso(d);
    case "start of last month": d.setDate(1); d.setMonth(d.getMonth() - 1); return iso(d);
    case "start of this year": return iso(new Date(d.getFullYear(), 0, 1));
    default: return null;
  }
}

/** True when this stored value is a dynamic token rather than a literal date. */
export function isDynamicDate(value: ParamValue | undefined): value is DynamicDateToken {
  return typeof value === "string" && (DYNAMIC_DATE_TOKENS as readonly string[]).includes(value);
}

/**
 * The bind value a stored widget value becomes — or undefined when it is UNFILLED,
 * which the caller reports as "not checked" rather than binding an empty string.
 *
 * - multiselect: the (non-empty) array, for the server's list expansion;
 * - number: a real number when the text parses as one — `x = :n` against an integer
 *   column should not depend on the engine's string coercion;
 * - date: a ⚡ token resolves to the ISO date it means TODAY;
 * - everything else: the trimmed string.
 */
export function resolveParamValue(
  def: ParamDef | undefined, value: ParamValue | undefined, now = new Date(),
): string | number | string[] | undefined {
  if (Array.isArray(value)) return value.length ? value : undefined;
  const text = (value ?? "").trim();
  if (!text) return undefined;
  const widget = def?.widget ?? "text";
  if (widget === "number") {
    const n = Number(text);
    return Number.isFinite(n) ? n : text;
  }
  if (widget === "date") {
    return resolveDynamicDate(text, now) ?? text;
  }
  return text;
}
