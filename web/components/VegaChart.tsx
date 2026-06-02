"use client";

/**
 * VegaChart — thin wrapper around vega-embed.
 *
 * Usage:
 *   <VegaChart spec={vlSpec} data={rows} />
 *
 * The spec is a plain Vega-Lite JSON object (TopLevelSpec).
 * Aughor's dark-theme config is merged in automatically.
 * Pass `data` to override the `data.values` field of the spec.
 */

import { useEffect, useRef, useState } from "react";

// Minimal type alias — avoids importing the full heavy vega-lite types at component load time.
export type VLSpec = Record<string, unknown>;

// ── Aughor Vega-Lite config (dark theme) ────────────────────────────────────

// Chart token values — must mirror tokens.css --chart-* and --chart-axis/grid/tick.
// Vega renders to SVG and cannot read CSS variables, so we mirror the values here.
const C1 = "#4C8EEE";  // --chart-1  blue
const C2 = "#2EC87B";  // --chart-2  green
const C3 = "#E0AD00";  // --chart-3  amber
const C4 = "#8B68D8";  // --chart-4  purple
const C5 = "#E64848";  // --chart-5  red
const C6 = "#30B8E0";  // --chart-6  cyan
const AXIS_LINE  = "#363940";  // --chart-axis
const AXIS_GRID  = "#292b2f";  // --chart-grid
const AXIS_TICK  = "#9AA0A8";  // --chart-tick

// 20-colour categorical palette — ordered for maximum perceptual distance.
// The first 6 match the Aughor design tokens above; 7-20 extend for high-cardinality data.
export const AUG_PALETTE = [
  C1,        // 1  blue
  C2,        // 2  green
  C3,        // 3  amber
  C4,        // 4  purple
  C5,        // 5  red
  C6,        // 6  cyan
  "#F97316", // 7  orange
  "#EC4899", // 8  pink
  "#10B981", // 9  emerald
  "#6366F1", // 10 indigo
  "#F59E0B", // 11 gold
  "#14B8A6", // 12 teal
  "#A855F7", // 13 violet
  "#22D3EE", // 14 sky
  "#84CC16", // 15 lime
  "#E879F9", // 16 fuchsia
  "#34D399", // 17 seafoam
  "#FB923C", // 18 peach
  "#818CF8", // 19 periwinkle
  "#4ADE80", // 20 light green
];

const AUG_CONFIG = {
  background: "transparent",
  font: "var(--font-ui, 'DM Sans', system-ui, sans-serif)",
  axis: {
    labelColor:    AXIS_TICK,
    titleColor:    AXIS_TICK,
    gridColor:     AXIS_GRID,
    domainColor:   AXIS_LINE,
    tickColor:     AXIS_LINE,
    labelFontSize: 11,
    titleFontSize: 11,
    labelPadding:  6,
    // max 6 ticks on time axis per M23c standard
    tickCount:     6,
  },
  header: {
    labelColor: AXIS_TICK,
    titleColor: AXIS_TICK,
  },
  legend: {
    labelColor:        AXIS_TICK,
    titleColor:        AXIS_TICK,
    labelFontSize:     11,
    symbolStrokeWidth: 0,
    padding:           4,
    orient:            "top",   // time series: legend above, left-aligned
    direction:         "horizontal",
  },
  range: {
    // Use the full 20-colour palette so high-cardinality categoricals don't recycle
    category: AUG_PALETTE,
  },
  view: { stroke: null },
  mark: { tooltip: true },
};

// ── vega-tooltip dark theme — injected once ──────────────────────────────────

let tooltipCssInjected = false;

function injectTooltipCss() {
  if (tooltipCssInjected || typeof document === "undefined") return;
  tooltipCssInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    .vg-tooltip {
      font-family: var(--font-ui, 'DM Sans', system-ui, sans-serif) !important;
      font-size: 11px !important;
      background: #13151a !important;
      border: 1px solid #2a2d38 !important;
      border-radius: 3px !important;
      color: #D4D7DC !important;
      box-shadow: 0 4px 16px rgba(0,0,0,.4) !important;
      padding: 6px 10px !important;
    }
    .vg-tooltip td.title { font-weight: 600; color: #D4D7DC !important; }
    .vg-tooltip td.value { color: #9AA0A8 !important; }
    .vg-tooltip tr { border-bottom: 1px solid #292b2f !important; }
  `;
  document.head.appendChild(style);
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  spec: VLSpec;
  /** Override / set the data.values field in the spec */
  data?: Record<string, unknown>[];
  height?: number;
  className?: string;
}

export function VegaChart({ spec, data, height, className }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{ finalize: () => void } | null>(null);
  const [w, setW] = useState(0);

  // Track container width for responsive sizing
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => {
      const cw = Math.round(entry.contentRect.width);
      if (cw > 0) setW(cw);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Render whenever spec, data, or container width changes
  useEffect(() => {
    if (!containerRef.current || w === 0) return;

    injectTooltipCss();

    // Detect Vega vs Vega-Lite spec by checking $schema
    const isVega = typeof spec.$schema === "string" && spec.$schema.includes("/vega/");

    let mergedSpec: VLSpec;
    if (isVega) {
      // Vega spec — inject width/height signals and data override only; no VL config merging
      const baseSignals = (spec.signals as unknown[] | undefined) ?? [];
      mergedSpec = {
        ...spec,
        signals: [
          ...baseSignals.filter((s: unknown) => {
            const sig = s as Record<string, unknown>;
            return sig.name !== "width" && sig.name !== "height";
          }),
          { name: "width",  value: w - 2 },
          { name: "height", value: height ?? 340 },
        ],
        ...(data ? {
          data: (spec.data as unknown[]).map((d: unknown) => {
            const ds = d as Record<string, unknown>;
            return ds.name === "tree" ? { ...ds, values: data } : ds;
          }),
        } : {}),
      };
    } else {
      mergedSpec = {
        $schema: "https://vega.github.io/schema/vega-lite/v5.json",
        ...spec,
        // Override/merge config — spec-level config wins over our defaults for
        // anything explicitly set; for anything not set, our defaults apply.
        config: {
          ...AUG_CONFIG,
          ...(spec.config as Record<string, unknown> | undefined ?? {}),
        },
        // "fit + padding" = width/height is the TOTAL SVG size (axes included).
        // Without this, axes overflow the container and get clipped.
        autosize: { type: "fit", contains: "padding" },
        width: w - 2,
        ...(height ? { height } : {}),
        ...(data ? { data: { values: data } } : {}),
      };
    }

    let cancelled = false;

    viewRef.current?.finalize();
    viewRef.current = null;

    import("vega-embed").then(({ default: embed }) => {
      if (cancelled || !containerRef.current) return;
      containerRef.current.innerHTML = "";
      embed(containerRef.current, mergedSpec as never, {
        actions: false,
        renderer: "svg",
        tooltip: { theme: "custom" },
      }).then(result => {
        if (!cancelled) viewRef.current = result.view;
      }).catch(() => {});
    });

    return () => {
      cancelled = true;
    };
  }, [spec, data, w, height]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      viewRef.current?.finalize();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: "100%", overflow: "hidden" }}
    />
  );
}

// ── Preset spec builders ─────────────────────────────────────────────────────

/** Build a Vega-Lite timeseries spec (area + line + dots) */
export function timeseriesSpec(xField: string, yField: string, opts?: {
  color?: string;
  yFormat?: string;
  xFormat?: string;
}): VLSpec {
  const color = opts?.color ?? C1;
  const enc = (extra?: VLSpec) => ({
    x: {
      field: xField,
      type: "temporal",
      axis: { format: opts?.xFormat ?? "%b %y", labelAngle: -30 },
    },
    y: {
      field: yField,
      type: "quantitative",
      axis: {
        format: opts?.yFormat ?? "~s",
        grid: true,
      },
    },
    ...extra,
  });

  return {
    layer: [
      {
        mark: { type: "area", color, opacity: 0.08 },
        encoding: enc(),
      },
      {
        mark: { type: "line", color, strokeWidth: 1.5 },
        encoding: enc(),
      },
      {
        mark: { type: "point", color, size: 25, filled: true, opacity: 0.9 },
        encoding: enc({
          tooltip: [
            { field: xField, type: "temporal", title: xField },
            { field: yField, type: "quantitative", title: yField, format: opts?.yFormat ?? ",.2~f" },
          ],
        }),
      },
    ],
    resolve: { scale: { y: "shared" } },
  };
}

/** Build a Vega-Lite horizontal bar spec */
export function barSpec(xField: string, yField: string, opts?: {
  color?: string;
  xFormat?: string;
  maxBars?: number;
}): VLSpec {
  const color = opts?.color ?? C1;
  return {
    mark: { type: "bar", color, opacity: 0.8, cornerRadiusEnd: 2 },
    transform: [
      { window: [{ op: "row_number", as: "_rank" }], sort: [{ field: xField, order: "descending" }] },
      { filter: `datum._rank <= ${opts?.maxBars ?? 15}` },
    ],
    encoding: {
      x: {
        field: xField,
        type: "quantitative",
        axis: { format: opts?.xFormat ?? "~s", grid: true },
      },
      y: {
        field: yField,
        type: "ordinal",
        sort: { field: xField, order: "descending" },
        axis: { labelLimit: 120 },
      },
      tooltip: [
        { field: yField, type: "nominal" },
        { field: xField, type: "quantitative", format: opts?.xFormat ?? ",.2~f" },
      ],
    },
  };
}
