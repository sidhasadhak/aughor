/**
 * exhibit.ts — the declarative exhibit spec a backend finding/answer can attach
 * to steer HOW its chart encodes meaning (never WHAT data it shows).
 *
 * The spec is additive and optional: no spec → every builder renders exactly as
 * before (byte-identical), so the backend flag `chart.exhibit_grammar` can gate
 * emission without any frontend flag plumbing. Grammar (mirrors the Genie report
 * study, docs/CHART_GRAMMAR_STUDY_2026-07-16):
 *   color.mode  "neutral"      one hue — color has nothing to say (default)
 *               "categorical"  hue = a second dimension (legend carries it)
 *               "severity"     single-hue ramp of the measure value itself —
 *                              redundant encoding for worst/best-N rankings
 *               "sign"         green/red by sign (change metrics; pre-existing)
 *   ref_lines   dashed reference lines on the value axis (peer median, global
 *               average, benchmark) — context the reader otherwise lacks
 *   label_points scatter points carry their entity label (outlier identity)
 *   quadrant    mean/median divider lines on a scatter (x and/or y)
 */

export interface ExhibitRefLine {
  value: number;
  label: string;
  /** Provenance of the line — display-only, but kept for the receipt/tooltip. */
  kind?: "peer_median" | "global_avg" | "benchmark" | "target";
}

export interface ExhibitColor {
  mode: "neutral" | "categorical" | "severity" | "sign";
  /** categorical: the column whose values pick the hue. */
  field?: string | null;
}

export interface ExhibitSpec {
  color?: ExhibitColor | null;
  ref_lines?: ExhibitRefLine[] | null;
  label_points?: boolean | null;
  quadrant?: { x?: number | null; y?: number | null } | null;
  /** "asc" = the query asked for the BOTTOM of the ranking (ORDER BY measure ASC
   *  LIMIT N), so lead with the row it led with instead of burying it at the far
   *  end. Absent → the largest-first default. */
  order?: "asc" | "desc" | null;
}

// ── severity ramp ────────────────────────────────────────────────────────────

/** Columns where a big value is a COST (delay, loss, returns…) — those ramp in
 *  the red family; everything else ramps in the calm primary blue. Deterministic
 *  name test, same spirit as columnRoles' patterns. */
export const COST_METRIC_COL =
  /(delay|late|loss|lost|cancel|refund|return|churn|complaint|defect|error|fail|missing|overdue|wait|downtime|leak)/i;

const BLUE_RAMP = ["#9DC4F5", "#4C8EEE", "#1D4E9E"];
const RED_RAMP = ["#F5C0A0", "#E64848", "#8E1E1E"];

function hexToRgb(h: string): [number, number, number] {
  const v = h.replace("#", "");
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}

function mix(a: [number, number, number], b: [number, number, number], t: number): string {
  const c = a.map((av, i) => Math.round(av + (b[i] - av) * t));
  return `#${c.map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

/** Piecewise-linear interpolation through a 3-stop ramp, normalised to [min, max].
 *  Degenerate ranges (min === max) sit at the middle stop. */
export function severityRamp(min: number, max: number, field: string): (v: number) => string {
  const stops = (COST_METRIC_COL.test(field) ? RED_RAMP : BLUE_RAMP).map(hexToRgb);
  return (v: number) => {
    if (!isFinite(v)) return mix(stops[1], stops[1], 0);
    const t = max > min ? Math.min(1, Math.max(0, (v - min) / (max - min))) : 0.5;
    return t <= 0.5 ? mix(stops[0], stops[1], t * 2) : mix(stops[1], stops[2], (t - 0.5) * 2);
  };
}

// ── markLine helper ──────────────────────────────────────────────────────────

// A reference line is axis FURNITURE, not data: it must not claim a categorical hue from
// the palette (ECharts would otherwise inherit the series colour — which reads as another
// series, and would vanish outright into a same-family severity ramp). The tick colour is
// the same neutral the axis labels use, and it reads on both themes.
const REF_LINE_COLOR = "#9DA1A8";

/** Build the ECharts markLine block for the given reference lines. `axis` picks
 *  which axis carries the VALUE dimension ("x" for horizontal bars, "y" else). */
export function refMarkLine(
  lines: ExhibitRefLine[],
  axis: "x" | "y",
  fmt: (v: unknown) => string,
): Record<string, unknown> | undefined {
  const data = (lines ?? []).filter((l) => isFinite(Number(l.value)));
  if (!data.length) return undefined;
  return {
    silent: true,
    symbol: "none",
    animation: false,
    lineStyle: { type: "dashed", width: 1.25, color: REF_LINE_COLOR },
    // A vertical (xAxis) markLine runs top→bottom, so "start" floats the label above the
    // grid top; a horizontal (yAxis) line's "end" floats it right of the grid. rotate 0
    // keeps the text horizontal — the inside positions rotate it along a vertical line,
    // which is unreadable. Per-line distances stagger neighbouring labels so two close
    // reference values (peer median beside the global average) can't overprint.
    label: {
      position: axis === "x" ? "start" : "end",
      rotate: 0,
      fontSize: 10,
      color: REF_LINE_COLOR,
      formatter: (p: { data?: { name?: string }; value?: unknown }) =>
        `${p.data?.name ?? ""} ${fmt(p.value)}`.trim(),
    },
    data: data.map((l, k) => ({
      name: l.label,
      ...(axis === "x" ? { xAxis: l.value } : { yAxis: l.value }),
      ...(axis === "x" ? { label: { distance: 4 + k * 13 } } : {}),
    })),
  };
}
