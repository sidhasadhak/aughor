/**
 * A figure drafted from a file, written as its statement says it is: money, a percent, or a plain number
 * (`aughor/dashboards/queries.py`, `Shown.format` and `Beside.format`).
 */
import { formatCount, formatWholeMoney, pct } from "@/lib/format";
import { effectiveCurrencySymbol } from "@/lib/orgSettings";

export function draftedFigure(value: number | null | undefined, format?: string): string {
  if (format === "money") return formatWholeMoney(value, effectiveCurrencySymbol() || "$");
  if (format === "percent") return pct(value, 1);
  return formatCount(value);
}
