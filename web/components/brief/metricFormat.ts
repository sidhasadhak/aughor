/**
 * How a north-star metric's figures read — one implementation shared by the KPI tiles
 * (`IndustryKpiStrip`) and the Briefing's "numbers that moved" table (`moves.ts`), so a value
 * and its move are never formatted two ways on one screen.
 *
 * Pure (no React, no fetch): the table's row builder is unit-tested through it.
 */
import type { Format } from "@number-flow/react";

/** How to drive the <NumberFlow> odometer so it renders EXACTLY `display`: the value is
 *  pre-rounded to the digits the display string shows (min === max fraction digits, no
 *  grouping, en-US), so the formatter never re-rounds — the odometer's text is
 *  byte-identical to the plain string. Unit glyphs (×/%/d/B/M/K) ride as `suffix`, the
 *  currency symbol as `prefix`. Built only where the mapping is exact; a case that can't
 *  be expressed this way omits `flow` and stays plain text. */
export interface KpiFlow {
  value: number;
  format: Format;
  prefix?: string;
  suffix?: string;
}
const isMultiplier = (name: string, unit: string) =>
  /\b(x|×|multiple|multiplier|roas|times)\b/i.test(unit) || /\broas\b|return on ad/i.test(name);

// Odometer format presets (module-level so NumberFlow's memoized formatter is reused).
// Fixed fraction digits + no grouping mirror what toFixed()/String() emit — the same
// digits the display string carries — so the animated text can never drift from it.
const FLOW_INT: Format = { maximumFractionDigits: 0, useGrouping: false };
const FLOW_1DP: Format = { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false };
const FLOW_2DP: Format = { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false };

/** Format a raw scalar by its declared unit/range; gate out broken values. The business's
 *  currency symbol is used for money metrics — a €-company never shows '$'. Alongside the
 *  display string, each branch emits the exact `flow` spec that reproduces it (see KpiFlow). */
export function formatMetric(v: number, unit: string, sym: string, name: string): { display: string; ok: boolean; flow?: KpiFlow } {
  const u = (unit || "").toLowerCase();
  let display: string;
  let flow: KpiFlow | undefined;
  if (isMultiplier(name, u)) {
    if (v <= 0 || v > 1000) return { display: "", ok: false };
    const s = v.toFixed(2);
    display = `${s}×`;
    flow = { value: Number(s), format: FLOW_2DP, suffix: "×" };
  } else if (/ratio|0-1|0\.\.1/.test(u) && !/0-100|0\.\.100/.test(u)) {
    if (v < -0.001 || v > 1.05) return { display: "", ok: false };   // broken bounded rate (>1)
    if (v >= 0.9995) return { display: "", ok: false };              // rounds to 100% — degenerate
    const s = (v * 100).toFixed(1);
    display = `${s}%`;
    flow = { value: Number(s), format: FLOW_1DP, suffix: "%" };
  } else if (/percent|0-100|0\.\.100|%/.test(u)) {
    if (v < -0.5 || v > 105) return { display: "", ok: false };
    if (v >= 99.95) return { display: "", ok: false };
    const s = v.toFixed(1);
    display = `${s}%`;
    flow = { value: Number(s), format: FLOW_1DP, suffix: "%" };
  } else if (/day/.test(u)) {
    const s = v.toFixed(1);
    display = `${s}d`;
    flow = { value: Number(s), format: FLOW_1DP, suffix: "d" };
  } else {
    const a = Math.abs(v);
    const [s, mag, fmt] = a >= 1e9 ? [(v / 1e9).toFixed(1), "B", FLOW_1DP] as const
                        : a >= 1e6 ? [(v / 1e6).toFixed(1), "M", FLOW_1DP] as const
                        : a >= 1e3 ? [(v / 1e3).toFixed(1), "K", FLOW_1DP] as const
                        : Number.isInteger(v) ? [String(v), "", FLOW_INT] as const
                        : [v.toFixed(2), "", FLOW_2DP] as const;
    const pre = /usd|eur|gbp|jpy|cny|inr|[$€£¥₹]|revenue|spend|cost|gmv|sales|value|price/.test(u) ? sym : "";
    display = pre + s + mag;
    flow = { value: Number(s), format: fmt, prefix: pre || undefined, suffix: mag || undefined };
  }
  if (Math.abs(parseFloat(display.replace(/[^0-9.eE-]/g, "")) || 0) === 0) return { display: "", ok: false };
  return { display, ok: true, flow };
}

/** Period-over-period delta in the metric's own terms: pts for rates, × for multipliers,
 *  relative % for everything else. null when there aren't two points. */
export function deltaInfo(values: number[], unit: string, name: string): { text: string; sign: number } | null {
  if (values.length < 2) return null;
  const prev = values[values.length - 2], last = values[values.length - 1];
  const diff = last - prev;
  const sign = Math.abs(diff) < 1e-12 ? 0 : diff > 0 ? 1 : -1;
  const u = (unit || "").toLowerCase();
  let text: string;
  if (isMultiplier(name, u)) {
    text = `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}×`;
  } else if (/ratio|0-1|0\.\.1/.test(u) && !/0-100/.test(u)) {
    const pts = diff * 100;
    text = `${pts >= 0 ? "+" : ""}${pts.toFixed(1)}pts`;
  } else if (/percent|0-100|%/.test(u)) {
    text = `${diff >= 0 ? "+" : ""}${diff.toFixed(1)}pts`;
  } else {
    const rel = prev !== 0 ? (diff / Math.abs(prev)) * 100 : 0;
    text = `${rel >= 0 ? "+" : ""}${rel.toFixed(1)}%`;
  }
  return { text, sign };
}

export const periodWord = (label: string) =>
  ({ DoD: "yesterday", WoW: "last week", MoM: "last month", QoQ: "last quarter", YoY: "last year", HoH: "prior hour" } as Record<string, string>)[label] ?? "prior period";
