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
import { AUG_PALETTE } from "@/lib/palette";
import { vegaV2Config, vegaV2Marks } from "@/aughor-v2/charts/vega-theme-v2";

// Minimal type alias — avoids importing the full heavy vega-lite types at component load time.
export type VLSpec = Record<string, unknown>;

// Re-export so existing `import { AUG_PALETTE } from "@/components/VegaChart"` keeps working.
export { AUG_PALETTE };

// ── Aughor Vega-Lite config (dark theme) ────────────────────────────────────

const C1 = AUG_PALETTE[0];   // primary brand colour — default single-series fill
const AXIS_LINE  = "#363940";
const AXIS_GRID  = "#292b2f";
const AXIS_TICK  = "#9AA0A8";

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

/** v2: remap the legacy hardcoded mark hexes (baked into Chart.tsx spec builders)
 *  to the current theme's --chart-* / --bg-2 tokens. Resolved at call time so it
 *  follows dark/light. Deep-walks the spec replacing only exact-match hex strings,
 *  so it's safe across all chart types without editing each builder. */
function remapLegacyColors(spec: VLSpec): VLSpec {
  const map: Record<string, string> = {
    "#818cf8": vegaV2Marks.bar,         // single-series bar fill   → --chart-1
    "#10b981": vegaV2Marks.line,        // line / area              → --chart-2
    "#f59e0b": vegaV2Marks.paretoLine,  // pareto cumulative line   → --chart-3
    "#71717a": vegaV2Marks.reference,   // reference / 80% rule     → --chart-tick
    "#0e1520": vegaV2Marks.pngBg,       // heatmap null / stroke    → --bg-2
    "#131c27": vegaV2Marks.pngBg,       // treemap stroke / bg      → --bg-2
  };
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") { const hit = map[v.toLowerCase()]; return hit || v; }
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) out[k] = walk(val);
      return out;
    }
    return v;
  };
  return walk(spec) as VLSpec;
}

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
  /** Click a mark to drill in — receives the datum behind the clicked bar/point. */
  onSelect?: (datum: Record<string, unknown>) => void;
}

/** Inject data-label text layers into a Vega-Lite spec, avoiding overlap.
 *  - Skips specs that already draw their own value labels (engine bar/treemap
 *    charts self-label) so toggling labels never double-stamps them.
 *  - Labels each measure ONCE — a line spec built as area+line+point layers
 *    sharing one encoding would otherwise stamp the same point twice.
 *  - Thins dense line/area series (keeps ~10 labels, partitioned by series) so a
 *    13- or 50-point trend doesn't smear its numbers into an unreadable ribbon. */
function injectLabels(spec: VLSpec, data?: Record<string, unknown>[]): VLSpec {
  const existing = (spec.layer || [spec]) as VLSpec[];
  // Already self-labeling? Leave it — a second pass would just overlap the first.
  if (existing.some(l => ((l.mark as Record<string, unknown>)?.type) === "text")) return spec;
  const topEnc = (spec.encoding || {}) as Record<string, unknown>;
  const labeled = new Set<string>();
  const wrapped: VLSpec[] = [];
  let changed = false;
  for (const layer of existing) {
    const enc = (layer.encoding || {}) as Record<string, unknown>;
    const yEnc = (enc.y || topEnc.y) as Record<string, unknown> | undefined;
    const xEnc = (enc.x || topEnc.x) as Record<string, unknown> | undefined;
    const yField = (yEnc?.field || yEnc?.aggregate) as string | undefined;
    const xField = (xEnc?.field || xEnc?.aggregate) as string | undefined;
    const markType = (layer.mark as Record<string, unknown>)?.type as string | undefined;
    if (!yField || !xField || !yEnc || !xEnc ||
        markType === "text" || markType === "point" || markType === "rect" || markType === "rule" || markType === "arc" ||
        labeled.has(yField)) {
      wrapped.push(layer);
      continue;
    }
    labeled.add(yField);
    const colorEnc = (enc.color || topEnc.color) as Record<string, unknown> | undefined;
    const colorField = colorEnc?.field as string | undefined;

    // Thin dense continuous series — keep every Nth point so ~10 labels survive per series.
    let transform: unknown[] | undefined;
    if ((markType === "line" || markType === "area") && data?.length) {
      const distinctX = new Set(data.map(d => d[xField])).size;
      const stride = Math.max(1, Math.ceil(distinctX / 10));
      if (stride > 1) {
        transform = [
          { window: [{ op: "row_number", as: "__li" }], sort: [{ field: xField, order: "ascending" }],
            ...(colorField ? { groupby: [colorField] } : {}) },
          { filter: `(datum.__li - 1) % ${stride} === 0` },
        ];
      }
    }

    const yOffset = markType === "bar" || markType === "area" ? -4 : -8;
    const labelLayer = {
      ...(transform ? { transform } : {}),
      mark: { type: "text", align: "center", baseline: "bottom", dy: yOffset, fontSize: 10, color: "#9AA0A8" },
      encoding: {
        x: { field: xField, ...(xEnc.type ? { type: xEnc.type } : {}) },
        y: { field: yField, ...(yEnc.type ? { type: yEnc.type } : {}) },
        text: { field: yField, type: "quantitative", format: ",.2~f" },
        ...(colorEnc ? { color: colorEnc } : {}),
      },
    };
    wrapped.push({ layer: [layer, labelLayer] });
    changed = true;
  }
  if (!changed) return spec;
  return { ...spec, layer: wrapped };
}

export function VegaChart({ spec, data, height, width, className, showLabels, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{ finalize: () => void } | null>(null);
  // Hold the latest onSelect in a ref so the click listener (registered once per embed)
  // always calls the current callback without re-running the render effect.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [w, setW] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  // v2: bump on dark/light flip so the spec rebuilds with fresh --chart-* token values.
  const [themeTick, setThemeTick] = useState(0);

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

  // v2: re-theme charts when the app toggles data-theme on <html>.
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick(t => t + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    return () => obs.disconnect();
  }, []);

  // Render whenever spec, data, or container width changes
  useEffect(() => {
    setErr(null);
    if (!containerRef.current) return;

    injectTooltipCss();

    const labeled = showLabels ? injectLabels(spec, data) : spec;
    // v2: swap legacy hardcoded mark hexes for current-theme tokens (no per-builder edits).
    const specWithLabels = remapLegacyColors(labeled);
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
          // AUG_CONFIG keeps header/tooltip/legend extras; vegaV2Config() (theme-aware,
          // token-driven axes/grid/palette/rounded bars) overrides on top; per-spec config wins last.
          ...AUG_CONFIG,
          ...vegaV2Config(),
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
        if (cancelled) return;
        viewRef.current = result.view;
        // Drill-down: clicking a mark hands the datum behind it back to the caller.
        // `cursor: pointer` only when interactive so the affordance reads as clickable.
        const view = result.view as unknown as {
          addEventListener?: (t: string, h: (event: unknown, item: unknown) => void) => void;
        };
        if (onSelectRef.current && typeof view.addEventListener === "function") {
          view.addEventListener("click", (_event, item) => {
            const datum = (item as { datum?: Record<string, unknown> } | null)?.datum;
            if (datum) onSelectRef.current?.(datum);
          });
          if (containerRef.current) containerRef.current.style.cursor = "pointer";
        }
      }).catch((e: Error) => {
        if (!cancelled) setErr(e.message || "Chart render failed");
      });
    });

    return () => { cancelled = true; };
  }, [spec, data, w, height, themeTick]);

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
