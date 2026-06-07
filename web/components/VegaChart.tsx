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

const C1 = "#4C8EEE";
const C2 = "#2EC87B";
const C3 = "#E0AD00";
const C4 = "#8B68D8";
const C5 = "#E64848";
const C6 = "#30B8E0";
const AXIS_LINE  = "#363940";
const AXIS_GRID  = "#292b2f";
const AXIS_TICK  = "#9AA0A8";

export const AUG_PALETTE = [
  C1, C2, C3, C4, C5, C6,
  "#F97316", "#EC4899", "#10B981", "#6366F1", "#F59E0B", "#14B8A6",
  "#A855F7", "#22D3EE", "#84CC16", "#E879F9", "#34D399", "#FB923C",
  "#818CF8", "#4ADE80",
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
    orient:            "top",
    direction:         "horizontal",
  },
  range: { category: AUG_PALETTE },
  view: { stroke: null },
  mark: { tooltip: true },
};

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

interface Props {
  spec: VLSpec;
  data?: Record<string, unknown>[];
  height?: number;
  width?: number;          // deprecated: chart always fits container width
  className?: string;
  showLabels?: boolean;
}

/** Inject data-label text layers into a Vega-Lite spec.
 *  Keeps every existing mark/layer and appends a matching text mark on top. */
function injectLabels(spec: VLSpec): VLSpec {
  const existing = (spec.layer || [spec]) as VLSpec[];
  const topEnc = (spec.encoding || {}) as Record<string, unknown>;
  const wrapped: VLSpec[] = [];
  let changed = false;
  for (const layer of existing) {
    const enc = (layer.encoding || {}) as Record<string, unknown>;
    const yEnc = (enc.y || topEnc.y) as Record<string, unknown> | undefined;
    const xEnc = (enc.x || topEnc.x) as Record<string, unknown> | undefined;
    if (!yEnc || !xEnc) {
      wrapped.push(layer);
      continue;
    }
    const yField = (yEnc.field || yEnc.aggregate) as string | undefined;
    const xField = (xEnc.field || xEnc.aggregate) as string | undefined;
    if (!yField || !xField) {
      wrapped.push(layer);
      continue;
    }
    const markType = (layer.mark as Record<string, unknown>)?.type;
    if (markType === "text" || markType === "point" || markType === "rect" || markType === "rule") {
      wrapped.push(layer);
      continue;
    }
    const yOffset = markType === "bar" || markType === "area" ? -4 : -8;
    const labelLayer = {
      mark: { type: "text", align: "center", baseline: "bottom", dy: yOffset, fontSize: 10, color: "#9AA0A8" },
      encoding: {
        x: { field: xField, ...(xEnc.type ? { type: xEnc.type } : {}) },
        y: { field: yField, ...(yEnc.type ? { type: yEnc.type } : {}) },
        text: { field: yField, type: "quantitative", format: ",.2~f" },
        ...(enc.color ? { color: enc.color } : {}),
      },
    };
    wrapped.push({ layer: [layer, labelLayer] });
    changed = true;
  }
  if (!changed) return spec;
  return { ...spec, layer: wrapped };
}

export function VegaChart({ spec, data, height, width, className, showLabels }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{ finalize: () => void } | null>(null);
  const [w, setW] = useState(0);
  const [err, setErr] = useState<string | null>(null);

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
    setErr(null);
    if (!containerRef.current) return;

    injectTooltipCss();

    const specWithLabels = showLabels ? injectLabels(spec) : spec;
    const isVega = typeof specWithLabels.$schema === "string" && specWithLabels.$schema.includes("/vega/");
    const safeW = Math.max(w, 320) - 2;

    let mergedSpec: VLSpec;
    const baseSpec = specWithLabels;
    if (isVega) {
      const baseSignals = (spec.signals as unknown[] | undefined) ?? [];
      mergedSpec = {
        ...baseSpec,
        signals: [
          ...baseSignals.filter((s: unknown) => {
            const sig = s as Record<string, unknown>;
            return sig.name !== "width" && sig.name !== "height";
          }),
          { name: "width",  value: safeW - 2 },
          { name: "height", value: height ?? 340 },
        ],
        ...(data ? {
          data: (baseSpec.data as unknown[]).map((d: unknown) => {
            const ds = d as Record<string, unknown>;
            return ds.name === "tree" ? { ...ds, values: data } : ds;
          }),
        } : {}),
      };
    } else {
      mergedSpec = {
        $schema: "https://vega.github.io/schema/vega-lite/v5.json",
        ...baseSpec,
        config: {
          ...AUG_CONFIG,
          ...(baseSpec.config as Record<string, unknown> | undefined ?? {}),
        },
        autosize: { type: "fit", contains: "padding" },
        width: safeW - 2,
        height: height ?? 340,
        ...(data ? { data: { values: data.map((d: Record<string, unknown>) => {
      const sanitized: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(d)) {
        if (typeof v === "number" && (Number.isNaN(v) || !Number.isFinite(v))) {
          sanitized[k] = null;
        } else if (v === "" || v === undefined) {
          sanitized[k] = null;
        } else {
          sanitized[k] = v;
        }
      }
      return sanitized;
    }) } } : {}),
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
      }).catch((e: Error) => {
        if (!cancelled) setErr(e.message || "Chart render failed");
      });
    });

    return () => { cancelled = true; };
  }, [spec, data, w, height]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { viewRef.current?.finalize(); };
  }, []);

  return (
    <div className={className} style={{ width: "100%" }}>
      {err && (
        <div className="text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1 mb-1">
          Chart error: {err}
        </div>
      )}
      <div ref={containerRef} style={{ width: "100%", overflow: "hidden" }} />
    </div>
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
      axis: { format: opts?.xFormat ?? "%b %d, %Y", labelAngle: 0, labelOverlap: true },
    },
    y: {
      field: yField,
      type: "quantitative",
      axis: { format: opts?.yFormat ?? "~s", grid: true },
    },
    ...extra,
  });

  return {
    layer: [
      { mark: { type: "area", color, opacity: 0.08 }, encoding: enc() },
      { mark: { type: "line", color, strokeWidth: 1.5 }, encoding: enc() },
      { mark: { type: "point", color, size: 25, filled: true, opacity: 0.9 }, encoding: enc({
        tooltip: [
          { field: xField, type: "temporal", title: xField },
          { field: yField, type: "quantitative", title: yField, format: opts?.yFormat ?? ",.2~f" },
        ],
      })},
    ],
    resolve: { scale: { y: "shared" } },
  };
}

/** Build a Vega-Lite horizontal bar spec */
export function barSpec(xField: string, yField: string, opts?: {
  color?: string;
  xFormat?: string;
  maxBars?: number;
  xTitle?: string;
  yTitle?: string;
}): VLSpec {
  const color = opts?.color ?? C1;
  const xTitle = opts?.xTitle ?? xField;
  const yTitle = opts?.yTitle ?? yField;
  const maxBars = opts?.maxBars;
  const transform = maxBars != null ? [
    { window: [{ op: "row_number", as: "_rank" }], sort: [{ field: xField, order: "descending" }] },
    { filter: `datum._rank <= ${maxBars}` },
  ] : [];
  return {
    mark: { type: "bar", color, opacity: 0.8, cornerRadiusEnd: 2 },
    transform,
    encoding: {
      x: {
        field: xField,
        type: "quantitative",
        axis: { format: opts?.xFormat ?? "~s", grid: true, title: xTitle },
      },
      y: {
        field: yField,
        type: "ordinal",
        sort: { field: xField, order: "descending" },
        axis: { labelLimit: 120, title: yTitle },
      },
      tooltip: [
        { field: yField, type: "nominal", title: yTitle },
        { field: xField, type: "quantitative", format: opts?.xFormat ?? ",.2~f", title: xTitle },
      ],
    },
  };
}
