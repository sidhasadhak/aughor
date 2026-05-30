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

const AUG_CONFIG = {
  background: "transparent",
  font: "var(--font-ui, 'DM Sans', system-ui, sans-serif)",
  axis: {
    labelColor:     "#8296AF",   // --t2 (was --t3 #485E7C — too dark on dark bg)
    titleColor:     "#8296AF",
    gridColor:      "#1B2840",   // --b1
    domainColor:    "#253552",
    tickColor:      "#253552",
    labelFontSize:  11,
    titleFontSize:  11,
    labelPadding:   6,
  },
  header: {
    labelColor: "#8296AF",       // --t2
    titleColor: "#8296AF",
  },
  legend: {
    labelColor:     "#8296AF",
    titleColor:     "#8296AF",
    labelFontSize:  11,
    symbolStrokeWidth: 0,
    padding: 4,
  },
  range: {
    category: [
      "#4C8EEE",   // blue4
      "#2EC87B",   // grn4
      "#f59e0b",   // amber
      "#f87171",   // red
      "#c084fc",   // purple
      "#38bdf8",   // sky
      "#fb923c",   // orange
      "#a3e635",   // lime
    ],
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
      background: #1C2839 !important;
      border: 1px solid #253552 !important;
      border-radius: 3px !important;
      color: #C8D4E4 !important;
      box-shadow: 0 4px 16px rgba(0,0,0,.4) !important;
      padding: 6px 10px !important;
    }
    .vg-tooltip td.title { font-weight: 600; color: #C8D4E4 !important; }
    .vg-tooltip td.value { color: #8296AF !important; }
    .vg-tooltip tr { border-bottom: 1px solid #1B2840 !important; }
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

    const mergedSpec: VLSpec = {
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
  const color = opts?.color ?? "#2EC87B";
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
  const color = opts?.color ?? "#4C8EEE";
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
