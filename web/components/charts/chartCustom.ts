/**
 * chartCustom.ts — "how the user wants THIS chart displayed", as a type.
 *
 * It lived in resolveOption.ts, the ECharts resolver, which made an engine-neutral contract
 * look like an ECharts one — six components imported it from there. Phase 5d retired that
 * file; the contract outlives it unchanged.
 */

export interface ChartCustom {
  format?: string;        // d3 number format for the quantitative axis (e.g. ",.0f", "$,.2f", "~s")
  colorScheme?: string;   // categorical palette name (a named scheme, e.g. "set2")
  xTitle?: string;
  yTitle?: string;
  legend?: "right" | "bottom" | "top" | "left" | "none";
  tooltip?: "on" | "off"; // hover tooltip visibility (default on); "off" for a clean tile
  /** Swap the axes of a bar form. Absent → the shared rule decides (category reads
   *  horizontally, time reads vertically). */
  orient?: "vertical" | "horizontal";
  /** Post-processing to apply IN the chart rather than to the data beforehand. Only the
   *  Vega path reads this: the ECharts builders take already-transformed rows, which is why
   *  that path still round-trips through /query/postproc. */
  transform?: { op: "pop" | "contribution" | "rolling" | "cumulative"; valueCol: string;
                window?: number; agg?: "mean" | "sum" | "min" | "max" } | null;
}
